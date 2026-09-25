"""Tests for the streaming research agent, using a scripted fake Claude (no API calls)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from finsight.agent import Done, ResearchAgent, TextDelta, ToolCall, ToolResult
from finsight.cli import chat


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(name, tool_input, block_id="toolu_1"):
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=tool_input)


class FakeStream:
    """Mimics the SDK stream: iterate for text events, then get_final_message()."""

    def __init__(self, content, stop_reason, cache_read=0):
        self.message = SimpleNamespace(
            content=content,
            stop_reason=stop_reason,
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                cache_read_input_tokens=cache_read,
                cache_creation_input_tokens=None,
            ),
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for block in self.message.content:
            if block.type == "text":
                yield SimpleNamespace(type="text", text=block.text)

    def get_final_message(self):
        return self.message


def scripted_client(*streams):
    client = MagicMock()
    client.beta.messages.stream.side_effect = list(streams)
    return client


def sent_messages(client):
    return client.beta.messages.stream.call_args.kwargs["messages"]


def test_answer_without_tools_streams_text_then_done() -> None:
    client = scripted_client(FakeStream([text_block("EBITDA "), text_block("is ...")], "end_turn"))

    events = list(ResearchAgent(client=client).send("What is EBITDA?"))

    assert events[:2] == [TextDelta("EBITDA "), TextDelta("is ...")]
    assert isinstance(events[-1], Done)
    assert events[-1].text == "EBITDA is ..."


def test_tool_calls_are_run_and_reported_as_events() -> None:
    call = tool_use_block("get_company_filings", {"ticker": "AAPL"})
    client = scripted_client(
        FakeStream([call], "tool_use"), FakeStream([text_block("Filed on ...")], "end_turn")
    )
    tool_runner = MagicMock(return_value=('{"filings": []}', False))

    events = list(ResearchAgent(client=client, tool_runner=tool_runner).send("q"))

    assert ToolCall("get_company_filings", {"ticker": "AAPL"}) in events
    assert ToolResult("get_company_filings", is_error=False) in events
    assert sent_messages(client)[2]["content"][0]["tool_use_id"] == "toolu_1"
    done = events[-1]
    assert (done.usage.input_tokens, done.usage.output_tokens) == (20, 10)


def test_memory_carries_over_between_messages() -> None:
    client = scripted_client(
        FakeStream([text_block("Apple's revenue was ...")], "end_turn"),
        FakeStream([text_block("Compared with Microsoft ...")], "end_turn"),
    )
    agent = ResearchAgent(client=client)

    list(agent.send("Apple revenue?"))
    list(agent.send("Now compare with Microsoft"))

    history = sent_messages(client)
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]
    assert history[0]["content"] == "Apple revenue?"
    assert history[2]["content"] == "Now compare with Microsoft"


def test_reset_forgets_the_conversation() -> None:
    client = scripted_client(
        FakeStream([text_block("a")], "end_turn"), FakeStream([text_block("b")], "end_turn")
    )
    agent = ResearchAgent(client=client)

    list(agent.send("first"))
    agent.reset()
    list(agent.send("second"))

    assert sent_messages(client)[0]["content"] == "second"


def test_total_usage_accumulates_across_messages_including_cache() -> None:
    client = scripted_client(
        FakeStream([text_block("a")], "end_turn"),
        FakeStream([text_block("b")], "end_turn", cache_read=900),
    )
    agent = ResearchAgent(client=client)

    list(agent.send("first"))
    list(agent.send("second"))

    assert agent.total_usage.input_tokens == 20
    assert agent.total_usage.cache_read_tokens == 900


def test_stops_at_max_turns() -> None:
    call = tool_use_block("get_company_filings", {"ticker": "AAPL"})
    client = scripted_client(*[FakeStream([call], "tool_use") for _ in range(3)])
    agent = ResearchAgent(
        client=client, tool_runner=MagicMock(return_value=("{}", False)), max_turns=3
    )

    events = list(agent.send("q"))

    assert "safety limit" in events[-1].text
    assert client.beta.messages.stream.call_count == 3


def test_truncated_answer_is_flagged() -> None:
    client = scripted_client(FakeStream([text_block("Partial answ")], "max_tokens"))

    done = list(ResearchAgent(client=client).send("q"))[-1]

    assert done.text.startswith("Partial answ")
    assert "max_tokens" in done.text


def test_chat_loop_handles_commands(capsys) -> None:
    client = scripted_client(FakeStream([text_block("Hi there")], "end_turn"))
    agent = ResearchAgent(client=client)
    inputs = iter(["hello", "/usage", "/reset", "/exit"])

    chat(agent, read=lambda prompt: next(inputs))

    output = capsys.readouterr().out
    assert "Hi there" in output
    assert "conversation cleared" in output
    assert agent.messages == []
    assert "Session total" in output


def test_usage_line_shows_all_input_buckets(capsys) -> None:
    client = scripted_client(FakeStream([text_block("ok")], "end_turn", cache_read=900))

    inputs = iter(["hi", "/exit"])

    chat(ResearchAgent(client=client), read=lambda prompt: next(inputs))

    assert "10 new + 0 cache-write + 900 cache-read | out: 5" in capsys.readouterr().out


# ---------- write_note(): structured output ----------


def parse_response(parsed_output, stop_reason="end_turn"):
    return SimpleNamespace(
        parsed_output=parsed_output,
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=3,
            output_tokens=400,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=2000,
        ),
    )


class NoteStream(FakeStream):
    """A streamed structured-output reply: get_final_message() returns the parsed note,
    or raises the error Pydantic would raise for truncated JSON."""

    def __init__(self, parsed_output=None, stop_reason="end_turn", error=None):
        self.response = parse_response(parsed_output, stop_reason)
        self.error = error

    def __iter__(self):
        return iter([])

    def get_final_message(self):
        if self.error:
            raise self.error
        return self.response


def truncated_json_error():
    from pydantic import ValidationError

    from finsight.notes import ResearchNote

    try:
        ResearchNote.model_validate_json('{"title": "Walmart vs. Ta')
    except ValidationError as e:
        return e


def test_write_note_requests_structured_output_without_changing_memory() -> None:
    from tests.test_notes import sample_note

    client = scripted_client(
        FakeStream([text_block("Apple grew ...")], "end_turn"), NoteStream(sample_note())
    )
    agent = ResearchAgent(client=client)
    list(agent.send("Apple revenue?"))

    note, usage = agent.write_note()

    request = client.beta.messages.stream.call_args.kwargs
    assert request["output_format"].__name__ == "ResearchNote"
    assert request["tool_choice"] == {"type": "none"}
    assert request["max_tokens"] == 64000  # thinking + JSON share this budget
    assert "research note" in request["messages"][-1]["content"]
    assert note.tickers == ["AAPL"]
    assert usage.cache_write_tokens == 2000
    assert len(agent.messages) == 2  # the note request was not added to memory


def test_write_note_with_empty_conversation_raises() -> None:
    with pytest.raises(ValueError, match="Nothing to summarize"):
        ResearchAgent(client=MagicMock()).write_note()


def test_write_note_without_parsed_output_raises() -> None:
    client = scripted_client(
        FakeStream([text_block("hi")], "end_turn"), NoteStream(None, stop_reason="refusal")
    )
    agent = ResearchAgent(client=client)
    list(agent.send("q"))

    with pytest.raises(ValueError, match="refusal"):
        agent.write_note()


def test_write_note_hitting_max_tokens_says_so() -> None:
    client = scripted_client(
        FakeStream([text_block("hi")], "end_turn"), NoteStream(None, stop_reason="max_tokens")
    )
    agent = ResearchAgent(client=client)
    list(agent.send("q"))

    with pytest.raises(ValueError, match="output limit"):
        agent.write_note()


def test_write_note_with_truncated_json_gives_a_clear_error() -> None:
    # Regression: the Bedrock run showed Pydantic's raw "EOF while parsing" error.
    client = scripted_client(
        FakeStream([text_block("hi")], "end_turn"), NoteStream(error=truncated_json_error())
    )
    agent = ResearchAgent(client=client)
    list(agent.send("q"))

    with pytest.raises(ValueError, match="incomplete or malformed"):
        agent.write_note()


def test_chat_note_command_saves_note(monkeypatch, tmp_path, capsys) -> None:
    from tests.test_notes import sample_note

    monkeypatch.chdir(tmp_path)  # save_note writes to ./reports
    client = scripted_client(
        FakeStream([text_block("Apple grew ...")], "end_turn"), NoteStream(sample_note())
    )
    inputs = iter(["Apple revenue?", "/note", "/exit"])

    chat(ResearchAgent(client=client), read=lambda prompt: next(inputs))

    assert "# Apple: Revenue Check / FY2025" in capsys.readouterr().out
    assert len(list((tmp_path / "reports").glob("*.json"))) == 1
