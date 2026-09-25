"""Tests for provider selection (Anthropic API vs Amazon Bedrock). No network calls."""

import anthropic
import pytest

from finsight import config, providers
from finsight.agent import ResearchAgent, Usage
from tests.test_agent import FakeStream, scripted_client, sent_messages, text_block


def test_anthropic_options_include_fallbacks() -> None:
    options = providers.provider_options("anthropic")

    assert options["model"] == "claude-opus-5"
    assert options["fallbacks"] == "default"
    assert options["thinking"] == {"type": "adaptive"}


def test_bedrock_options_use_bedrock_model_without_fallbacks() -> None:
    options = providers.provider_options("bedrock")

    assert options["model"] == "us.anthropic.claude-sonnet-4-6"
    assert "fallbacks" not in options  # not supported on Bedrock
    assert "betas" not in options


def test_make_client_returns_the_right_client_type() -> None:
    assert isinstance(providers.make_client("bedrock"), anthropic.AnthropicBedrock)


def test_unknown_provider_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(config, "PROVIDER", "openai")

    with pytest.raises(ValueError, match="FINSIGHT_PROVIDER"):
        providers.provider_options()


def test_agent_sends_bedrock_settings_when_bedrock_is_active(monkeypatch) -> None:
    monkeypatch.setattr(config, "PROVIDER", "bedrock")
    client = scripted_client(FakeStream([text_block("ok")], "end_turn"))

    list(ResearchAgent(client=client).send("hi"))

    request = client.beta.messages.stream.call_args.kwargs
    assert request["model"] == "us.anthropic.claude-sonnet-4-6"
    assert "fallbacks" not in request
    # Bedrock rejects top-level cache_control, so breakpoints are marked on blocks instead.
    assert "cache_control" not in request
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert sent_messages(client)[0]["content"] == [
        {"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}
    ]


def test_anthropic_uses_one_automatic_cache_setting() -> None:
    client = scripted_client(FakeStream([text_block("ok")], "end_turn"))

    list(ResearchAgent(client=client).send("hi"))

    request = client.beta.messages.stream.call_args.kwargs
    assert request["cache_control"] == {"type": "ephemeral"}
    assert request["system"].startswith("You are FinSight")


def test_cache_breakpoint_moves_to_the_newest_message_and_memory_stays_clean(monkeypatch) -> None:
    monkeypatch.setattr(config, "PROVIDER", "bedrock")
    client = scripted_client(
        FakeStream([text_block("first answer")], "end_turn"),
        FakeStream([text_block("second answer")], "end_turn"),
    )
    agent = ResearchAgent(client=client)

    list(agent.send("first"))
    list(agent.send("second"))

    history = sent_messages(client)
    marked = [
        m
        for m in history
        if isinstance(m["content"], list)
        and any("cache_control" in b for b in m["content"] if isinstance(b, dict))
    ]
    assert marked == [history[-1]]  # only the newest message carries the breakpoint
    assert agent.messages[0]["content"] == "first"  # memory has no cache markers
    assert agent.messages[2]["content"] == "second"


def test_breakpoint_on_tool_results_and_sdk_blocks() -> None:
    from types import SimpleNamespace

    from finsight.agent import _with_cache_breakpoint

    class Block(SimpleNamespace):
        def model_dump(self, exclude_none=False):
            return dict(vars(self))

    tool_results = [{"type": "tool_result", "tool_use_id": "t1", "content": "{}"}]
    reply = [Block(type="text", text="done")]

    marked = _with_cache_breakpoint([{"role": "user", "content": tool_results}])
    assert marked[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in tool_results[0]  # the original was not modified

    marked = _with_cache_breakpoint([{"role": "assistant", "content": reply}])
    assert marked[0]["content"] == [
        {"type": "text", "text": "done", "cache_control": {"type": "ephemeral"}}
    ]


@pytest.mark.parametrize(
    ("model", "key"),
    [
        ("claude-opus-5", "claude-opus-5"),
        ("us.anthropic.claude-sonnet-4-6", "claude-sonnet-4-6"),
        ("global.anthropic.claude-opus-4-6-v1", "claude-opus-4-6"),
        ("anthropic.claude-haiku-4-5-20251001-v1:0", "claude-haiku-4-5"),
    ],
)
def test_pricing_key_normalizes_provider_model_ids(model, key) -> None:
    assert providers.pricing_key(model) == key


def test_cost_uses_the_active_providers_model(monkeypatch) -> None:
    monkeypatch.setattr(config, "PROVIDER", "bedrock")
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)

    assert usage.cost_usd() == pytest.approx(3.00 + 15.00)  # Sonnet 4.6 prices


def test_describe_shows_provider_region_and_model(monkeypatch) -> None:
    monkeypatch.setattr(config, "PROVIDER", "bedrock")

    assert providers.describe() == "bedrock (us-east-1) / us.anthropic.claude-sonnet-4-6"
