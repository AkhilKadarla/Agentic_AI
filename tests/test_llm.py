"""Tests for the single LLM call.

We never call the real API in tests: it costs money, needs a key, and gives
different answers each time. Instead we pass in a fake client that returns a
canned response, and check that our code sends the right request and reads the
response correctly.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from finsight.cli import main
from finsight.llm import Answer, ask


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
