"""Tests for the Streamlit UI, run headless with Streamlit's AppTest (no browser, no API)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from streamlit.testing.v1 import AppTest

from finsight.agent import ResearchAgent, Usage
from finsight.charts import chart_rows, display_unit, metric_chart
from tests.test_agent import (
    FakeStream,
    NoteStream,
    scripted_client,
    text_block,
    tool_use_block,
)
from tests.test_notes import sample_note

APP = str(Path(__file__).parents[1] / "src" / "finsight" / "ui.py")


def app_with(agent: ResearchAgent) -> AppTest:
    # Generous timeout: the first Streamlit import on a cold machine (CI) is slow.
    app = AppTest.from_file(APP, default_timeout=30)
    app.session_state["agent"] = agent  # inject a fake-backed agent before the first run
    return app.run()


def test_empty_app_shows_examples_and_note_hint() -> None:
    app = app_with(ResearchAgent(client=MagicMock()))

    assert not app.exception
    assert "FinSight" in app.sidebar.title[0].value
    assert any("NVIDIA" in m.value for m in app.markdown)
    assert "Generate research note" in app.info[0].value


def test_chat_message_streams_answer_and_records_tool_calls() -> None:
    call = tool_use_block("get_financial_facts", {"ticker": "AAPL", "metric": "revenue"})
    client = scripted_client(
        FakeStream([call], "tool_use"), FakeStream([text_block("Apple grew 6%.")], "end_turn")
    )
    agent = ResearchAgent(client=client, tool_runner=MagicMock(return_value=("{}", False)))
    app = app_with(agent)

    app.chat_input[0].set_value("Apple revenue?").run()

    assert not app.exception
    chat = app.session_state["chat"]
    assert [m["role"] for m in chat] == ["user", "assistant"]
    assert chat[1]["text"] == "Apple grew 6%."
    assert chat[1]["tools"] == [("`get_financial_facts(ticker=AAPL, metric=revenue)`", False)]


def test_generate_note_button_renders_note(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)  # the button also saves the note to ./reports
    client = scripted_client(
        FakeStream([text_block("Apple grew ...")], "end_turn"), NoteStream(sample_note())
    )
    agent = ResearchAgent(client=client)
    app = app_with(agent)
    app.chat_input[0].set_value("Apple revenue?").run()

    app.sidebar.button[0].click().run()

    assert not app.exception
    assert app.header[0].value == "Apple: Revenue Check / FY2025"
    assert len(list((tmp_path / "reports").glob("*.json"))) == 1


def test_new_conversation_clears_everything() -> None:
    client = scripted_client(FakeStream([text_block("hi")], "end_turn"))
    app = app_with(ResearchAgent(client=client))
    app.chat_input[0].set_value("hello").run()

    app.sidebar.button[1].click().run()

    assert app.session_state["chat"] == []
    assert app.session_state["agent"].messages == []


# ---------- charts & cost ----------


def test_chart_rows_groups_metrics_and_skips_single_points() -> None:
    rows = chart_rows(sample_note())  # the sample has one Revenue and one Growth value

    assert rows == {}


def test_chart_rows_scales_dollars_to_billions() -> None:
    note = sample_note()
    note.key_metrics.append(note.key_metrics[0].model_copy(update={"period": "FY2024"}))

    [revenue] = chart_rows(note)["Revenue"][:1]

    assert revenue["value"] == pytest.approx(416.161)
    assert revenue["unit"] == "$B"


def test_metric_chart_builds_a_valid_spec() -> None:
    rows = [
        {"company": "AAPL", "period": "FY2024", "value": 391.0, "unit": "$B"},
        {"company": "AAPL", "period": "FY2025", "value": 416.2, "unit": "$B"},
    ]

    spec = metric_chart("Revenue", rows, ["AAPL"]).to_dict()

    assert spec["mark"]["type"] == "bar"
    assert spec["encoding"]["color"]["scale"]["range"] == ["#2a78d6"]


@pytest.mark.parametrize(
    ("unit", "expected"), [("USD", "$B"), ("USD/shares", "$/share"), ("%", "%")]
)
def test_display_unit(unit, expected) -> None:
    assert display_unit(unit) == expected


def test_cost_usd_uses_cache_multipliers() -> None:
    usage = Usage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_tokens=1_000_000,
        cache_write_tokens=1_000_000,
    )

    # opus-5: 5 input + 25 output + 5*1.25 write + 5*0.1 read
    assert usage.cost_usd("claude-opus-5") == pytest.approx(36.75)
    assert usage.cost_usd("unknown-model") is None


def test_answer_after_tool_calls_starts_a_new_paragraph() -> None:
    preamble_and_call = [
        text_block("Let me fetch the data."),
        tool_use_block("get_financial_facts", {"ticker": "AAPL", "metric": "revenue"}),
    ]
    client = scripted_client(
        FakeStream(preamble_and_call, "tool_use"),
        FakeStream([text_block("## Result")], "end_turn"),
    )
    agent = ResearchAgent(client=client, tool_runner=MagicMock(return_value=("{}", False)))
    app = app_with(agent)

    app.chat_input[0].set_value("q").run()

    assert app.session_state["chat"][-1]["text"] == "Let me fetch the data.\n\n## Result"


# ---------- guardrail display ----------


def test_blocked_question_shows_guardrail_warning() -> None:
    from finsight.guardrail import Guardrail
    from tests.test_guardrail import BLOCK_MESSAGE, blocked_by_topic, fake_bedrock

    guard = Guardrail("gr-1", "3", client=fake_bedrock(blocked_by_topic()))
    agent = ResearchAgent(client=MagicMock(), guardrail=guard)
    app = app_with(agent)

    app.chat_input[0].set_value("Should I buy NVIDIA?").run()

    assert not app.exception
    message = app.session_state["chat"][-1]
    assert message["text"] == BLOCK_MESSAGE
    assert message["guard"]["status"] == "blocked"
    assert "Claude was not called" in app.warning[0].value
    agent.client.beta.messages.stream.assert_not_called()


def test_flagged_paragraphs_are_listed_for_review() -> None:
    from finsight.guardrail import Guardrail
    from tests.test_guardrail import fake_bedrock, grounding, passed

    guard = Guardrail("gr-1", "3", client=fake_bedrock(passed(), passed(), grounding(0.04)))
    client = scripted_client(
        FakeStream([tool_use_block("get_financial_facts", {"ticker": "AAPL"})], "tool_use"),
        FakeStream([text_block("Revenue grew 6.4% year over year, a solid result.")], "end_turn"),
    )
    agent = ResearchAgent(
        client=client, tool_runner=MagicMock(return_value=("{}", False)), guardrail=guard
    )
    app = app_with(agent)

    app.chat_input[0].set_value("Apple growth?").run()

    assert not app.exception
    guard_info = app.session_state["chat"][-1]["guard"]
    assert guard_info["status"] == "flagged"
    assert guard_info["flagged"][0][1] == 0.04
    assert "1 of 1 paragraphs" in app.expander[-1].label


# ---------- deployed mode (FINSIGHT_UI_BACKEND=deployed): Cognito login, RemoteAgent ----------


@pytest.fixture
def deployed_mode(monkeypatch):
    from finsight import config, remote

    monkeypatch.setattr(config, "UI_BACKEND", "deployed")
    monkeypatch.setattr(config, "COGNITO_DOMAIN", "login.example.com")
    monkeypatch.setattr(config, "COGNITO_CLIENT_ID", "client1")
    monkeypatch.setattr(config, "RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:1:runtime/x")
    monkeypatch.setattr(remote, "PENDING_LOGINS", {})
    return remote


def test_deployed_mode_asks_to_log_in_first(deployed_mode) -> None:
    app = AppTest.from_file(APP, default_timeout=30).run()

    assert not app.exception
    assert not app.chat_input  # no chat until logged in
    login_link = next(m.value for m in app.markdown if "Log in" in m.value)
    assert "https://login.example.com/oauth2/authorize?" in login_link
    assert "code_challenge_method=S256" in login_link
    assert len(deployed_mode.PENDING_LOGINS) == 1  # the verifier waits server-side


def test_returning_from_cognito_logs_in(deployed_mode, monkeypatch) -> None:
    app = AppTest.from_file(APP, default_timeout=30).run()
    ((state, verifier),) = deployed_mode.PENDING_LOGINS.items()
    seen = {}

    def fake_exchange(http, domain, client_id, code, code_verifier):
        seen.update(code=code, verifier=code_verifier)
        return "ACCESS_TOKEN"

    monkeypatch.setattr(deployed_mode, "exchange_code", fake_exchange)
    app.query_params["code"] = "ONE_TIME_CODE"
    app.query_params["state"] = state
    app.run()

    assert not app.exception
    agent = app.session_state["agent"]
    assert isinstance(agent, deployed_mode.RemoteAgent)
    assert agent.token == "ACCESS_TOKEN"
    assert seen == {"code": "ONE_TIME_CODE", "verifier": verifier}
    assert app.chat_input  # the chat is available now
    assert deployed_mode.PENDING_LOGINS == {}  # a login link works only once


def test_unknown_or_reused_login_is_refused(deployed_mode) -> None:
    app = AppTest.from_file(APP, default_timeout=30)
    app.query_params["code"] = "CODE"
    app.query_params["state"] = "not-a-login-we-started"
    app.run()

    assert not app.exception
    assert "expired or was already used" in app.error[0].value
    assert "agent" not in app.session_state


def test_expired_login_returns_to_the_login_page(deployed_mode) -> None:
    class ExpiredAgent:
        total_usage = Usage()
        model = ""

        def send(self, prompt):
            raise deployed_mode.LoginExpired("login expired - log in again")
            yield  # a generator, like the real send()

    app = AppTest.from_file(APP, default_timeout=30)
    app.session_state["agent"] = ExpiredAgent()
    app.run()
    app.chat_input[0].set_value("Apple revenue?").run()

    assert not app.exception
    assert "login expired" in app.session_state["chat"][-1]["text"]
    assert "agent" not in app.session_state
