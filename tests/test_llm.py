"""Tests for the single LLM call.

We never call the real API in tests: it costs money, needs a key, and gives
different answers each time. Instead we pass in a fake client that returns a
canned response, and check that our code sends the right request and reads the
response correctly.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from finsight.cli import main
from finsight.llm import Answer, ask, research


def fake_client(content, stop_reason="end_turn"):
    client = MagicMock()
    client.beta.messages.create.return_value = SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=50, output_tokens=20),
    )
    return client


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def test_ask_returns_text_and_usage() -> None:
    client = fake_client([text_block("EBITDA is earnings before ...")])

    answer = ask("What is EBITDA?", client=client)

    assert answer == Answer(text="EBITDA is earnings before ...", input_tokens=50, output_tokens=20)


def test_ask_sends_question_with_system_prompt() -> None:
    client = fake_client([text_block("ok")])

    ask("What is EBITDA?", client=client)

    request = client.beta.messages.create.call_args.kwargs
    assert request["messages"] == [{"role": "user", "content": "What is EBITDA?"}]
    assert "FinSight" in request["system"]


def test_ask_ignores_non_text_blocks() -> None:
    thinking = SimpleNamespace(type="thinking", thinking="")
    client = fake_client([thinking, text_block("Hello"), text_block(" world")])

    assert ask("hi", client=client).text == "Hello world"


def test_ask_handles_refusal() -> None:
    client = fake_client([], stop_reason="refusal")

    assert "declined" in ask("something", client=client).text


def test_cli_ask_prints_answer_and_tokens(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "finsight.cli.ask", lambda q: Answer(text=f"answer to {q}", input_tokens=1, output_tokens=2)
    )

    main(["ask", "What is P/E?"])

    output = capsys.readouterr().out
    assert "answer to What is P/E?" in output
    assert "1 in / 2 out" in output


# ---------- research(): one tool-use round trip ----------


def tool_use_block(name, tool_input, block_id="toolu_1"):
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=tool_input)


def scripted_client(*responses):
    """A fake client that returns the given (content, stop_reason) pairs in order."""
    client = MagicMock()
    client.beta.messages.create.side_effect = [
        SimpleNamespace(
            content=content,
            stop_reason=stop_reason,
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )
        for content, stop_reason in responses
    ]
    return client


def test_research_without_tool_use_answers_directly() -> None:
    client = scripted_client(([text_block("EBITDA is ...")], "end_turn"))

    answer = research("What is EBITDA?", client=client, tool_runner=MagicMock())

    assert answer.text == "EBITDA is ..."
    assert client.beta.messages.create.call_count == 1


def test_research_runs_requested_tool_and_sends_result_back() -> None:
    call = tool_use_block("get_company_filings", {"ticker": "AAPL"})
    client = scripted_client(
        ([call], "tool_use"),
        ([text_block("Apple filed a 10-K on ...")], "end_turn"),
    )
    tool_runner = MagicMock(return_value=('{"filings": []}', False))
    seen = []

    answer = research(
        "When did Apple file?",
        client=client,
        tool_runner=tool_runner,
        on_tool_call=lambda name, args: seen.append(name),
    )

    tool_runner.assert_called_once_with("get_company_filings", {"ticker": "AAPL"})
    assert seen == ["get_company_filings"]
    assert answer.text == "Apple filed a 10-K on ..."
    assert (answer.input_tokens, answer.output_tokens) == (20, 10)  # summed over both calls

    followup = client.beta.messages.create.call_args.kwargs["messages"]
    assert followup[1] == {"role": "assistant", "content": [call]}
    assert followup[2]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_1",
            "content": '{"filings": []}',
            "is_error": False,
        }
    ]


def test_research_loops_through_multiple_rounds() -> None:
    # Round 1: Claude looks up revenue. Round 2: having seen it, asks for net income.
    revenue = tool_use_block("get_financial_facts", {"ticker": "AAPL", "metric": "revenue"})
    income = tool_use_block("get_financial_facts", {"ticker": "AAPL", "metric": "net_income"}, "t2")
    client = scripted_client(
        ([revenue], "tool_use"),
        ([income], "tool_use"),
        ([text_block("Apple's net margin is ...")], "end_turn"),
    )
    tool_runner = MagicMock(return_value=("{}", False))

    answer = research("What is Apple's net margin?", client=client, tool_runner=tool_runner)

    assert answer.text == "Apple's net margin is ..."
    assert tool_runner.call_count == 2
    assert client.beta.messages.create.call_count == 3
    # user, assistant, tool results, assistant, tool results
    assert len(client.beta.messages.create.call_args.kwargs["messages"]) == 5


def test_research_stops_at_max_turns() -> None:
    call = tool_use_block("get_company_filings", {"ticker": "AAPL"})
    client = scripted_client(*[([call], "tool_use")] * 3)

    answer = research(
        "q", client=client, tool_runner=MagicMock(return_value=("{}", False)), max_turns=3
    )

    assert "safety limit" in answer.text
    assert client.beta.messages.create.call_count == 3


def test_research_flags_truncated_answer() -> None:
    client = scripted_client(([text_block("Partial answ")], "max_tokens"))

    answer = research("q", client=client, tool_runner=MagicMock())

    assert answer.text.startswith("Partial answ")
    assert "max_tokens" in answer.text
