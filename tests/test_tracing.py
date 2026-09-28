"""Tests for observability: spans are recorded with the right structure and details."""

import json
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from finsight import config, tracing
from finsight.agent import ResearchAgent
from finsight.guardrail import Guardrail
from tests.test_agent import FakeStream, scripted_client, text_block, tool_use_block
from tests.test_guardrail import blocked_by_topic, fake_bedrock


@pytest.fixture
def spans(monkeypatch):
    """Turn tracing on with an in-memory exporter; returns a function listing spans."""
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(config, "TRACING", True)
    monkeypatch.setattr(config, "TRACE_CONTENT", True)
    tracing.configure(exporter)
    yield lambda: [tracing.span_to_dict(s) for s in exporter.get_finished_spans()]
    monkeypatch.setattr(tracing, "_provider", None)


def by_name(recorded: list[dict]) -> dict[str, dict]:
    return {s["name"]: s for s in recorded}


def test_research_trace_has_model_and_tool_spans_under_one_root(spans) -> None:
    client = scripted_client(
        FakeStream([tool_use_block("get_financial_facts", {"ticker": "AAPL"})], "tool_use"),
        FakeStream([text_block("Apple revenue was $416.2B.")], "end_turn"),
    )
    agent = ResearchAgent(client=client, tool_runner=MagicMock(return_value=('{"x": 1}', False)))

    list(agent.send("Apple revenue?"))

    recorded = spans()
    names = [s["name"] for s in recorded]
    assert names.count("chat claude-opus-5") == 2
    assert "execute_tool get_financial_facts" in names
    root = by_name(recorded)["research"]
    assert {s["trace_id"] for s in recorded} == {root["trace_id"]}  # one question = one trace
    assert all(s["parent_id"] == root["span_id"] for s in recorded if s is not root)
    assert root["attributes"]["finsight.outcome"] == "answered"
    assert root["attributes"]["finsight.question"] == "Apple revenue?"
    assert root["attributes"]["gen_ai.usage.input_tokens"] == 20  # summed over both calls
    tool = by_name(recorded)["execute_tool get_financial_facts"]["attributes"]
    assert tool["gen_ai.tool.name"] == "get_financial_facts"
    assert json.loads(tool["finsight.tool.arguments"]) == {"ticker": "AAPL"}
    assert tool["finsight.tool.is_error"] is False


def test_chat_span_records_usage_and_finish_reason(spans) -> None:
    client = scripted_client(FakeStream([text_block("hi")], "end_turn"))

    list(ResearchAgent(client=client).send("hi"))

    chat = by_name(spans())["chat claude-opus-5"]["attributes"]
    assert chat["gen_ai.operation.name"] == "chat"
    assert chat["gen_ai.response.model"] == "claude-opus-5"
    assert chat["gen_ai.response.finish_reasons"] == ("end_turn",)
    assert (chat["gen_ai.usage.input_tokens"], chat["gen_ai.usage.output_tokens"]) == (10, 5)


def test_blocked_question_is_traced_as_blocked(spans) -> None:
    guard = Guardrail("gr-1", "3", client=fake_bedrock(blocked_by_topic()))
    agent = ResearchAgent(client=MagicMock(), guardrail=guard)

    list(agent.send("Should I buy NVIDIA?"))

    recorded = by_name(spans())
    assert recorded["research"]["attributes"]["finsight.outcome"] == "blocked"
    assert recorded["guardrail.input"]["attributes"]["finsight.guardrail.result"] == "blocked"
    assert not any(name.startswith("chat") for name in recorded)  # Claude never called


def test_content_capture_can_be_turned_off(spans, monkeypatch) -> None:
    monkeypatch.setattr(config, "TRACE_CONTENT", False)
    client = scripted_client(FakeStream([text_block("secret answer")], "end_turn"))

    list(ResearchAgent(client=client).send("my private question"))

    root = by_name(spans())["research"]["attributes"]
    assert "finsight.question" not in root and "finsight.answer" not in root
    assert root["finsight.outcome"] == "answered"  # metadata is still recorded


def test_api_errors_mark_the_trace_as_failed(spans) -> None:
    client = MagicMock()
    client.beta.messages.stream.side_effect = RuntimeError("connection reset")

    with pytest.raises(RuntimeError):
        list(ResearchAgent(client=client).send("hi"))

    root = by_name(spans())["research"]
    assert root["status"] == "ERROR"
    assert root["attributes"]["finsight.outcome"] == "error"


def test_tracing_off_records_nothing(spans, monkeypatch) -> None:
    monkeypatch.setattr(config, "TRACING", False)
    client = scripted_client(FakeStream([text_block("hi")], "end_turn"))

    list(ResearchAgent(client=client).send("hi"))

    assert spans() == []


# ---------- files, retention, reading traces back ----------


def test_file_exporter_writes_json_lines_per_day(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "TRACING", True)
    tracing.configure(tracing.JsonlFileExporter(tmp_path))
    client = scripted_client(FakeStream([text_block("hi")], "end_turn"))

    list(ResearchAgent(client=client).send("hi"))
    monkeypatch.setattr(tracing, "_provider", None)

    lines = (tmp_path / f"{date.today().isoformat()}.jsonl").read_text().splitlines()
    assert {json.loads(line)["name"] for line in lines} == {"research", "chat claude-opus-5"}


def test_retention_deletes_only_old_trace_files(tmp_path) -> None:
    old = tmp_path / f"{(date.today() - timedelta(days=31)).isoformat()}.jsonl"
    recent = tmp_path / f"{(date.today() - timedelta(days=5)).isoformat()}.jsonl"
    other = tmp_path / "notes.jsonl"
    for path in (old, recent, other):
        path.write_text("{}\n")

    removed = tracing.delete_old_traces(tmp_path, retention_days=30)

    assert removed == [old]
    assert recent.exists() and other.exists()


def test_summary_and_tree_rendering(spans) -> None:
    client = scripted_client(
        FakeStream([tool_use_block("get_financial_facts", {"ticker": "AAPL"})], "tool_use"),
        FakeStream([text_block("done")], "end_turn"),
    )
    agent = ResearchAgent(client=client, tool_runner=MagicMock(return_value=("{}", False)))
    list(agent.send("Apple revenue?"))
    recorded = spans()

    [row] = tracing.summarize(recorded)
    tree = tracing.render_tree(recorded, row["trace_id"][:8])

    assert row["question"] == "Apple revenue?" and row["tool_calls"] == 1
    assert row["outcome"] == "answered"
    assert tree.splitlines()[0].startswith("research")
    assert "├─ chat claude-opus-5" in tree
    assert "└─ chat claude-opus-5" in tree
    assert "execute_tool get_financial_facts" in tree


def test_cli_lists_and_shows_traces(tmp_path, monkeypatch, capsys) -> None:
    from finsight.cli import main

    monkeypatch.setattr(config, "TRACING", True)
    monkeypatch.setattr(config, "TRACE_CONTENT", True)
    monkeypatch.setattr(tracing, "TRACE_DIR", tmp_path)
    tracing.configure(tracing.JsonlFileExporter(tmp_path))
    client = scripted_client(FakeStream([text_block("hi")], "end_turn"))
    list(ResearchAgent(client=client).send("What is EBITDA?"))
    monkeypatch.setattr(tracing, "_provider", None)

    main(["traces"])
    listing = capsys.readouterr().out
    trace_id = listing.splitlines()[1].split()[0]
    main(["traces", trace_id])
    tree = capsys.readouterr().out

    assert "What is EBITDA?" in listing and "answered" in listing
    assert tree.startswith("research") and "chat claude-opus-5" in tree
