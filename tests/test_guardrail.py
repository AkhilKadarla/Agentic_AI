"""Tests for the guardrail layer, with a fake Bedrock client (no AWS calls).

Response shapes mirror real ApplyGuardrail responses captured while designing this step.
"""

import json
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from finsight import config
from finsight.agent import Done, GuardrailBlocked, GuardrailReport, ResearchAgent, ToolResult
from finsight.cli import describe_report
from finsight.guardrail import (
    Guardrail,
    GuardrailUnavailable,
    make_guardrail,
    readable_source,
    split_paragraphs,
    tables_to_sentences,
)
from tests.test_agent import FakeStream, scripted_client, text_block, tool_use_block

BLOCK_MESSAGE = "FinSight can't provide personalized investment advice."


def passed():
    return {"action": "NONE", "outputs": [], "assessments": [{}]}


def blocked_by_topic(name="Personalized investment advice"):
    return {
        "action": "GUARDRAIL_INTERVENED",
        "outputs": [{"text": BLOCK_MESSAGE}],
        "assessments": [
            {"topicPolicy": {"topics": [{"name": name, "type": "DENY", "action": "BLOCKED"}]}}
        ],
    }


def grounding(score, relevance=0.9, threshold=0.75):
    action = "BLOCKED" if score < threshold else "NONE"
    filters = [
        {"type": "GROUNDING", "threshold": threshold, "score": score, "action": action},
        {"type": "RELEVANCE", "threshold": 0.5, "score": relevance, "action": "NONE"},
    ]
    return {
        "action": "GUARDRAIL_INTERVENED" if action == "BLOCKED" else "NONE",
        "outputs": [],
        "assessments": [{"contextualGroundingPolicy": {"filters": filters}}],
    }


def fake_bedrock(*responses):
    client = MagicMock()
    client.apply_guardrail.side_effect = list(responses)
    return client


def calls(client):
    return [c.kwargs for c in client.apply_guardrail.call_args_list]


# ---------- Guardrail ----------


def test_input_that_passes() -> None:
    guard = Guardrail("gr-1", "3", client=fake_bedrock(passed()))

    assert not guard.check_input("What was Apple's revenue?").blocked


def test_input_blocked_by_topic_reports_message_and_reason() -> None:
    client = fake_bedrock(blocked_by_topic())
    verdict = Guardrail("gr-1", "3", client=client).check_input("Should I buy NVIDIA?")

    assert verdict.blocked
    assert verdict.message == BLOCK_MESSAGE
    assert verdict.reasons == ["topic: Personalized investment advice"]
    assert calls(client)[0]["source"] == "INPUT"
    assert calls(client)[0]["guardrailVersion"] == "3"


def test_service_errors_become_guardrail_unavailable() -> None:
    client = MagicMock()
    client.apply_guardrail.side_effect = ClientError(
        {"Error": {"Code": "ExpiredTokenException", "Message": "expired"}}, "ApplyGuardrail"
    )

    with pytest.raises(GuardrailUnavailable):
        Guardrail("gr-1", "3", client=client).check_input("hi")


def test_grounding_flags_only_unsupported_paragraphs() -> None:
    answer = "A" * 300 + "\n\n" + "B" * 300
    client = fake_bedrock(grounding(0.99), grounding(0.04))

    result = Guardrail("gr-1", "3", client=client).check_grounding(answer, ["src"], "q")

    assert result.checked == 2
    assert [p.text[0] for p in result.flagged] == ["B"]
    assert result.flagged[0].grounding == 0.04
    qualifiers = [c["text"]["qualifiers"][0] for c in calls(client)[0]["content"]]
    assert qualifiers == ["grounding_source", "query", "guard_content"]


def test_guardrail_is_off_without_an_id() -> None:
    assert make_guardrail() is None


def test_guardrail_version_must_be_pinned(monkeypatch) -> None:
    monkeypatch.setattr(config, "GUARDRAIL_ID", "gr-1")

    with pytest.raises(ValueError, match="FINSIGHT_GUARDRAIL_VERSION"):
        make_guardrail()


# ---------- paragraph splitting & readable sources ----------


def test_split_merges_short_headings_into_the_next_paragraph() -> None:
    text = "## Revenue\n\n" + "Apple grew. " * 30 + "\n\n" + "Margins held. " * 30

    parts = split_paragraphs(text)

    assert len(parts) == 2
    assert parts[0].startswith("## Revenue\n\nApple grew.")


def test_split_respects_the_5000_character_limit() -> None:
    text = "\n".join(["x" * 90] * 150)  # one 13,650-character block with line breaks

    parts = split_paragraphs(text)

    assert all(len(p) <= 5000 for p in parts)
    assert "".join(parts).replace("\n", "") == text.replace("\n", "")


def test_readable_source_for_financial_facts() -> None:
    result = json.dumps(
        {
            "company": "Apple Inc.",
            "ticker": "AAPL",
            "metric": "net_income",
            "unit": "USD",
            "annual_values": [{"period_end": "2025-09-27", "value": 112_010_000_000}],
        }
    )

    text = readable_source("get_financial_facts", result)

    assert text == (
        "From Apple Inc. (AAPL)'s 10-K filings: Apple Inc. (AAPL) net income for the fiscal "
        "year ended September 27, 2025 (2025-09-27): $112.0 billion ($112,010,000,000)."
    )


def test_readable_source_for_eps_and_filings() -> None:
    eps = json.dumps(
        {
            "company": "Apple Inc.",
            "ticker": "AAPL",
            "metric": "eps_diluted",
            "unit": "USD/shares",
            "annual_values": [{"period_end": "2025-09-27", "value": 7.46}],
        }
    )
    filings = json.dumps(
        {
            "company": "NVIDIA CORP",
            "ticker": "NVDA",
            "filings": [{"form": "10-K", "filing_date": "2026-02-25", "report_date": "2026-01-25"}],
        }
    )

    assert "$7.46 per share" in readable_source("get_financial_facts", eps)
    assert readable_source("get_company_filings", filings) == (
        "NVIDIA CORP (NVDA) filed a 10-K on February 25, 2026 (2026-02-25) for the period "
        "ended January 25, 2026 (2026-01-25)."
    )


def test_readable_source_falls_back_to_raw_text() -> None:
    assert readable_source("get_financial_facts", "not json") == "not json"


def test_tables_are_checked_as_sentences() -> None:
    table = (
        "Here is the data:\n"
        "| Metric | FY 2024 | FY 2025 |\n"
        "|---|---|---|\n"
        "| **Revenue** | $254.5B | $275.2B |"
    )

    assert tables_to_sentences(table) == (
        "Here is the data:\nRevenue, FY 2024: $254.5B. Revenue, FY 2025: $275.2B."
    )


def test_grounding_checks_table_as_sentences_but_reports_original() -> None:
    table = "| Metric | FY 2025 |\n|---|---|\n| Revenue | $275.2B |" + " " * 200
    client = fake_bedrock(grounding(0.1))

    result = Guardrail("gr-1", "3", client=client).check_grounding(table, ["src"], "q")

    checked = calls(client)[0]["content"][2]["text"]["text"]
    assert checked.startswith("Revenue, FY 2025: $275.2B.")
    assert result.flagged[0].text.startswith("| Metric |")  # the user sees the table


# ---------- agent integration ----------


def agent_with(guard_client, *streams, tool_result=("{}", False)):
    guard = Guardrail("gr-1", "3", client=guard_client)
    tool_runner = MagicMock(return_value=tool_result)
    return ResearchAgent(client=scripted_client(*streams), tool_runner=tool_runner, guardrail=guard)


def test_blocked_question_never_reaches_claude_or_memory() -> None:
    agent = agent_with(fake_bedrock(blocked_by_topic()))

    events = list(agent.send("Should I buy NVIDIA?"))

    assert events[0] == GuardrailBlocked(BLOCK_MESSAGE, ["topic: Personalized investment advice"])
    assert events[-1] == Done(BLOCK_MESSAGE, events[-1].usage)
    agent.client.beta.messages.stream.assert_not_called()
    assert agent.messages == []


def test_guardrail_outage_fails_closed() -> None:
    client = MagicMock()
    client.apply_guardrail.side_effect = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "ApplyGuardrail"
    )
    agent = agent_with(client)

    events = list(agent.send("What was Apple's revenue?"))

    assert isinstance(events[0], GuardrailBlocked)
    assert "fail-closed" in events[0].message
    agent.client.beta.messages.stream.assert_not_called()


def test_answer_is_reviewed_and_grounded_against_fetched_data() -> None:
    facts = json.dumps(
        {
            "company": "Apple Inc.",
            "ticker": "AAPL",
            "metric": "revenue",
            "unit": "USD",
            "annual_values": [{"period_end": "2025-09-27", "value": 416_161_000_000}],
        }
    )
    guard_client = fake_bedrock(passed(), passed(), grounding(0.99))
    agent = agent_with(
        guard_client,
        FakeStream([tool_use_block("get_financial_facts", {"ticker": "AAPL"})], "tool_use"),
        FakeStream([text_block("Apple revenue was $416.2 billion in fiscal 2025.")], "end_turn"),
        tool_result=(facts, False),
    )

    events = list(agent.send("Apple revenue?"))

    report = next(e for e in events if isinstance(e, GuardrailReport))
    assert not report.output.blocked
    assert report.grounding.checked == 1 and report.grounding.flagged == []
    source = calls(guard_client)[2]["content"][0]["text"]["text"]
    assert "$416.2 billion ($416,161,000,000)" in source  # readable, not raw JSON
    assert isinstance(events[-1], Done)


def test_failed_tool_results_are_not_used_as_evidence() -> None:
    agent = agent_with(
        fake_bedrock(passed(), passed()),
        FakeStream([tool_use_block("get_financial_facts", {"ticker": "XYZ"})], "tool_use"),
        FakeStream([text_block("I couldn't find that company.")], "end_turn"),
        tool_result=("No company found", True),
    )

    events = list(agent.send("XYZ revenue?"))

    assert any(isinstance(e, ToolResult) and e.is_error for e in events)
    report = next(e for e in events if isinstance(e, GuardrailReport))
    assert report.grounding is None  # no evidence fetched, so no grounding check
    assert agent.sources == []


def test_output_check_outage_marks_answer_unverified() -> None:
    client = MagicMock()
    client.apply_guardrail.side_effect = [
        passed(),
        ClientError({"Error": {"Code": "ServiceUnavailable", "Message": "down"}}, "ApplyGuardrail"),
    ]
    agent = agent_with(client, FakeStream([text_block("EBITDA is ...")], "end_turn"))

    report = next(e for e in agent.send("What is EBITDA?") if isinstance(e, GuardrailReport))

    assert "fail-closed" in report.error


def test_reset_clears_the_evidence() -> None:
    agent = agent_with(fake_bedrock())
    agent.sources = ["something"]

    agent.reset()

    assert agent.sources == []


# ---------- CLI rendering ----------


def test_cli_describes_each_report_kind() -> None:
    from finsight.guardrail import FlaggedParagraph, Grounding, Verdict

    ok = GuardrailReport(output=Verdict(False), grounding=Grounding(3, []))
    flagged = GuardrailReport(
        output=Verdict(False), grounding=Grounding(3, [FlaggedParagraph("Up 6.4%", 0.04, 0.9)])
    )
    retracted = GuardrailReport(output=Verdict(True, "masked", ["personal data: email"]))

    assert describe_report(ok) == "[guardrail] passed, 3 paragraphs grounded"
    assert "1 of 3 paragraphs" in describe_report(flagged)
    assert "(0.04) Up 6.4%" in describe_report(flagged)
    assert "FLAGGED (personal data: email)" in describe_report(retracted)
    assert "UNVERIFIED" in describe_report(GuardrailReport(error="down"))
