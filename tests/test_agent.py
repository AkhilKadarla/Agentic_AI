"""Tests for the streaming research agent, using a scripted fake Claude (no API calls)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

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
