"""Tests for the AgentCore-compatible web API (fake agent, no API calls)."""

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from finsight import api
from finsight.agent import ResearchAgent
from tests.test_agent import FakeStream, NoteStream, scripted_client, text_block, tool_use_block
from tests.test_notes import sample_note


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "_sessions", {})
    return TestClient(api.app)


def use_agents(monkeypatch, *agents):
    queue = list(agents)
    monkeypatch.setattr(api, "agent_factory", lambda: queue.pop(0))


def events(response) -> list[dict]:
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def test_ping_reports_healthy(client) -> None:
    assert client.get("/ping").json() == {"status": "Healthy"}


def test_chat_streams_agent_events_as_sse(client, monkeypatch) -> None:
    fake = scripted_client(
        FakeStream([tool_use_block("get_financial_facts", {"ticker": "AAPL"})], "tool_use"),
        FakeStream([text_block("Apple revenue was $416.2B.")], "end_turn"),
    )
    use_agents(
        monkeypatch,
        ResearchAgent(client=fake, tool_runner=MagicMock(return_value=("{}", False))),
    )

    response = client.post("/invocations", json={"prompt": "Apple revenue?"})

    assert response.headers["content-type"].startswith("text/event-stream")
    got = events(response)
    assert [e["type"] for e in got] == ["tool_call", "tool_result", "text", "done"]
    assert got[0] == {
        "type": "tool_call",
        "name": "get_financial_facts",
        "input": {"ticker": "AAPL"},
    }
    assert got[-1]["text"] == "Apple revenue was $416.2B."
    assert got[-1]["model"] == "claude-opus-5" and got[-1]["usage"]["input_tokens"] == 20


def test_sessions_keep_separate_memory(client, monkeypatch) -> None:
    alice = ResearchAgent(client=scripted_client(*[FakeStream([text_block("a")], "end_turn")] * 2))
    bob = ResearchAgent(client=scripted_client(FakeStream([text_block("b")], "end_turn")))
    use_agents(monkeypatch, alice, bob)
    header = api.SESSION_HEADER

    client.post("/invocations", json={"prompt": "first"}, headers={header: "alice"})
    client.post("/invocations", json={"prompt": "hi"}, headers={header: "bob"})
    client.post("/invocations", json={"prompt": "second"}, headers={header: "alice"})

    assert [m["content"] for m in alice.messages if m["role"] == "user"] == ["first", "second"]
    assert [m["content"] for m in bob.messages if m["role"] == "user"] == ["hi"]


def test_note_and_reset_actions(client, monkeypatch) -> None:
    fake = scripted_client(
        FakeStream([text_block("Apple grew")], "end_turn"), NoteStream(sample_note())
    )
    agent = ResearchAgent(client=fake)
    use_agents(monkeypatch, agent)

    client.post("/invocations", json={"prompt": "Apple revenue?"})
    note = client.post("/invocations", json={"action": "note"}).json()
    reset = client.post("/invocations", json={"action": "reset"}).json()

    assert note["note"]["tickers"] == ["AAPL"]
    assert reset == {"status": "reset"} and agent.messages == []


def test_note_without_conversation_is_a_400(client, monkeypatch) -> None:
    use_agents(monkeypatch, ResearchAgent(client=MagicMock()))

    response = client.post("/invocations", json={"action": "note"})

    assert response.status_code == 400
    assert "Nothing to summarize" in response.json()["error"]


def test_empty_prompt_is_rejected(client, monkeypatch) -> None:
    use_agents(monkeypatch, ResearchAgent(client=MagicMock()))

    assert client.post("/invocations", json={"prompt": "   "}).status_code == 400


def test_api_errors_arrive_as_an_error_event(client, monkeypatch) -> None:
    import anthropic

    broken = MagicMock()
    broken.beta.messages.stream.side_effect = anthropic.APIConnectionError(request=MagicMock())
    use_agents(monkeypatch, ResearchAgent(client=broken))

    got = events(client.post("/invocations", json={"prompt": "hi"}))

    assert got[-1]["type"] == "error" and "Claude API error" in got[-1]["message"]


def test_guardrail_block_is_streamed(client, monkeypatch) -> None:
    from finsight.guardrail import Guardrail
    from tests.test_guardrail import blocked_by_topic, fake_bedrock

    guard = Guardrail("gr-1", "3", client=fake_bedrock(blocked_by_topic()))
    use_agents(monkeypatch, ResearchAgent(client=MagicMock(), guardrail=guard))

    got = events(client.post("/invocations", json={"prompt": "Should I buy NVIDIA?"}))

    assert got[0]["type"] == "guardrail_blocked"
    assert got[0]["reasons"] == ["topic: Personalized investment advice"]
