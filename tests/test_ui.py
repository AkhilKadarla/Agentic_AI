"""Tests for the Streamlit UI, run headless with Streamlit's AppTest (no browser, no API)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from streamlit.testing.v1 import AppTest

from finsight.agent import ResearchAgent, Usage
from finsight.charts import chart_rows, display_unit, metric_chart
from tests.test_agent import FakeStream, parse_response, scripted_client, text_block, tool_use_block
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
    client = scripted_client(FakeStream([text_block("Apple grew ...")], "end_turn"))
    client.beta.messages.parse.return_value = parse_response(sample_note())
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
