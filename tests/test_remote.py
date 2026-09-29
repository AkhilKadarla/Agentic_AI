"""Tests for `finsight remote`: PKCE login pieces and the deployed-agent client.

No network: Cognito and AgentCore are replaced with httpx.MockTransport.
"""

import json
import urllib.parse

import httpx
import pytest

from finsight import api, remote
from finsight.agent import (
    Done,
    GuardrailBlocked,
    GuardrailReport,
    TextDelta,
    ToolCall,
    ToolResult,
    Usage,
)
from finsight.guardrail import FlaggedParagraph, Grounding, Verdict
from tests.test_notes import sample_note

ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/finsight-abc"


def test_pkce_challenge_matches_rfc_7636_example():
    # The worked example from the PKCE standard (RFC 7636, appendix B)
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert remote.challenge_for(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_pkce_pairs_are_random_and_consistent():
    (v1, c1), (v2, _) = remote.pkce_pair(), remote.pkce_pair()
    assert v1 != v2
    assert c1 == remote.challenge_for(v1)
    assert 43 <= len(v1) <= 128  # the standard's allowed verifier length


def test_authorize_url_sends_challenge_not_verifier():
    url = remote.authorize_url("login.example.com", "client1", "CHALLENGE", "STATE")
    parsed = urllib.parse.urlparse(url)
    params = dict(urllib.parse.parse_qsl(parsed.query))
    assert parsed.netloc == "login.example.com" and parsed.path == "/oauth2/authorize"
    assert params["code_challenge"] == "CHALLENGE"
    assert params["code_challenge_method"] == "S256"
    assert params["state"] == "STATE"
    assert params["redirect_uri"] == "http://localhost:8501/"
    assert params["response_type"] == "code"


def test_callback_parsing():
    assert remote.parse_callback("/?code=abc&state=S1", "S1") == "abc"
    assert remote.parse_callback("/favicon.ico", "S1") is None
    with pytest.raises(remote.LoginError, match="state mismatch"):
        remote.parse_callback("/?code=abc&state=OTHER", "S1")
    with pytest.raises(remote.LoginError, match="access_denied"):
        remote.parse_callback("/?error=access_denied&state=S1", "S1")


def test_code_exchange_sends_the_verifier():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["form"] = dict(urllib.parse.parse_qsl(request.content.decode()))
        return httpx.Response(200, json={"access_token": "TOKEN", "id_token": "x"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        token = remote.exchange_code(http, "login.example.com", "client1", "CODE", "VERIFIER")
    assert token == "TOKEN"
    assert seen["url"] == "https://login.example.com/oauth2/token"
    assert seen["form"]["code_verifier"] == "VERIFIER"
    assert seen["form"]["grant_type"] == "authorization_code"


def test_failed_code_exchange_is_a_login_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(400, text='{"error":"invalid_grant"}'))
    with httpx.Client(transport=transport) as http, pytest.raises(remote.LoginError):
        remote.exchange_code(http, "login.example.com", "client1", "CODE", "VERIFIER")


EVENTS = [
    TextDelta("Apple revenue was $416.2B."),
    ToolCall("get_financial_facts", {"ticker": "AAPL", "metric": "revenue"}),
    ToolResult("get_financial_facts", False),
    GuardrailBlocked("I can't help with that.", ["topic: Investment advice"]),
    GuardrailReport(
        output=Verdict(blocked=False),
        grounding=Grounding(checked=3, flagged=[FlaggedParagraph("Margins grew.", 0.2, 0.9)]),
    ),
    GuardrailReport(error="guardrail unreachable"),
    Done("Apple revenue was $416.2B.", Usage(10, 20, 30, 40), "claude-sonnet-4-6", "end_turn"),
]


@pytest.mark.parametrize("event", EVENTS, ids=lambda e: type(e).__name__)
def test_every_api_event_round_trips(event):
    # What the server sends (api.event_to_dict) must come back as the same event object
    wire = json.loads(json.dumps(api.event_to_dict(event)))
    assert remote.dict_to_event(wire) == event


def sse(*payloads: dict) -> str:
    return "".join(f"data: {json.dumps(p)}\n\n" for p in payloads)


def agent_with(handler) -> remote.RemoteAgent:
    return remote.RemoteAgent(
        "TOKEN", ARN, http=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_send_streams_events_with_token_and_session():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        body = sse(
            api.event_to_dict(TextDelta("Hi")),
            api.event_to_dict(Done("Hi", Usage(5, 7), "m", "end_turn")),
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    agent = agent_with(handler)
    events = list(agent.send("What was Apple's revenue?"))
    assert events == [TextDelta("Hi"), Done("Hi", Usage(5, 7), "m", "end_turn")]
    request = seen["request"]
    assert request.headers["Authorization"] == "Bearer TOKEN"
    assert len(request.headers[api.SESSION_HEADER]) >= 33  # AgentCore's minimum
    assert urllib.parse.unquote(str(request.url)).endswith(
        f"/runtimes/{ARN}/invocations?qualifier=DEFAULT"
    )
    assert json.loads(request.content) == {"prompt": "What was Apple's revenue?", "action": "chat"}
    assert agent.total_usage == Usage(5, 7)


def test_session_stays_the_same_across_messages():
    sessions = []

    def handler(request):
        sessions.append(request.headers[api.SESSION_HEADER])
        return httpx.Response(200, text=sse({"type": "text", "text": "ok"}))

    agent = agent_with(handler)
    list(agent.send("one"))
    list(agent.send("two"))
    agent.reset()
    assert len(set(sessions)) == 1  # one conversation = one AgentCore session


def test_expired_login_and_server_errors_are_clear():
    agent = agent_with(lambda r: httpx.Response(401, json={"message": "Unauthorized"}))
    with pytest.raises(remote.RemoteError, match="login expired"):
        list(agent.send("hi"))
    agent = agent_with(
        lambda r: httpx.Response(200, text=sse({"type": "error", "message": "boom"}))
    )
    with pytest.raises(remote.RemoteError, match="boom"):
        list(agent.send("hi"))


def test_write_note_returns_the_note_and_usage():
    note = sample_note()

    def handler(request):
        assert json.loads(request.content) == {"action": "note"}
        return httpx.Response(200, json={"note": note.model_dump(), "usage": {"output_tokens": 9}})

    agent = agent_with(handler)
    got, usage = agent.write_note()
    assert got == note
    assert usage.output_tokens == 9
    assert agent.total_usage.output_tokens == 9


def test_write_note_without_research_raises_value_error():
    # The CLI's make_note() shows ValueError messages, same as for a local agent
    agent = agent_with(lambda r: httpx.Response(400, json={"error": "Nothing to summarize yet"}))
    with pytest.raises(ValueError, match="Nothing to summarize"):
        agent.write_note()


def test_web_login_verifier_is_used_once(monkeypatch):
    monkeypatch.setattr(remote, "PENDING_LOGINS", {})
    url = remote.start_web_login("login.example.com", "client1")
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))["state"]
    verifier = remote.PENDING_LOGINS[state]
    used = []
    monkeypatch.setattr(remote, "exchange_code", lambda http, d, c, code, v: used.append(v) or "T")

    assert remote.finish_web_login("login.example.com", "client1", {"code": "C", "state": state})
    assert used == [verifier]
    with pytest.raises(remote.LoginError, match="already used"):
        remote.finish_web_login("login.example.com", "client1", {"code": "C", "state": state})
    with pytest.raises(remote.LoginError, match="access_denied"):
        remote.finish_web_login("login.example.com", "client1", {"error": "access_denied"})


def test_pending_logins_are_capped(monkeypatch):
    monkeypatch.setattr(remote, "PENDING_LOGINS", {})
    for _ in range(remote.MAX_PENDING + 5):
        remote.start_web_login("login.example.com", "client1")
    assert len(remote.PENDING_LOGINS) == remote.MAX_PENDING


def test_logout_returns_to_the_app():
    url = remote.logout_url("login.example.com", "client1")
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    assert url.startswith("https://login.example.com/logout?")
    assert params == {"client_id": "client1", "logout_uri": "http://localhost:8501/"}


def test_model_is_remembered_for_cost_estimates():
    done = {
        "type": "done",
        "text": "",
        "model": "claude-sonnet-4-6",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 1},
    }
    agent = agent_with(lambda r: httpx.Response(200, text=sse(done)))
    list(agent.send("hi"))
    assert agent.model == "claude-sonnet-4-6"
