"""The FinSight research agent: an agent loop with conversation memory and streaming.

`ResearchAgent.send()` does not print anything. It *yields events* (text as it is written,
tool calls, tool results, and a final summary). Any interface can consume the same events:
the terminal CLI and the Streamlit web UI.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import anthropic
from pydantic import ValidationError

from finsight.config import PRICING
from finsight.llm import SYSTEM_PROMPT
from finsight.notes import NOTE_INSTRUCTIONS, ResearchNote
from finsight.providers import (
    automatic_caching,
    make_client,
    model_id,
    pricing_key,
    provider_options,
)
from finsight.tools import TOOLS, run_tool

MAX_TURNS = 10
CACHE = {"type": "ephemeral"}  # prompt-cache marker (5-minute lifetime)


# ---------- Events the agent yields ----------


@dataclass
class TextDelta:
    """A small piece of Claude's answer, streamed as it is generated."""

    text: str


@dataclass
class ToolCall:
    name: str
    input: dict


@dataclass
class ToolResult:
    name: str
    is_error: bool


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0  # input tokens served from the prompt cache (~10% of the price)
    cache_write_tokens: int = 0

    def cost_usd(self, model: str | None = None) -> float | None:
        """Estimated cost in dollars, or None if we don't know the model's price."""
        price = PRICING.get(pricing_key(model or model_id()))
        if price is None:
            return None
        return (
            self.input_tokens * price["input"]
            + self.cache_write_tokens * price["input"] * 1.25
            + self.cache_read_tokens * price["input"] * 0.10
            + self.output_tokens * price["output"]
        ) / 1_000_000

    def add(self, api_usage) -> None:
        self.input_tokens += api_usage.input_tokens
        self.output_tokens += api_usage.output_tokens
        self.cache_read_tokens += api_usage.cache_read_input_tokens or 0
        self.cache_write_tokens += api_usage.cache_creation_input_tokens or 0


@dataclass
class Done:
    """The final event of a send(): the complete answer and this message's token usage."""

    text: str
    usage: Usage


Event = TextDelta | ToolCall | ToolResult | Done


# ---------- The agent ----------


class ResearchAgent:
    """An agent that remembers the conversation, so follow-up questions work."""

    def __init__(
        self,
        client: anthropic.Anthropic | anthropic.AnthropicBedrock | None = None,
        tool_runner: Callable[[str, dict], tuple[str, bool]] = run_tool,
        max_turns: int = MAX_TURNS,
    ) -> None:
        self.client = client or make_client()  # Anthropic API or Bedrock, per .env
        self.tool_runner = tool_runner
        self.max_turns = max_turns
        # The memory: the full conversation, re-sent to Claude on every request
        # (the API itself is stateless).
        self.messages: list[dict] = []
        self.total_usage = Usage()

    def reset(self) -> None:
        """Forget the conversation and start fresh."""
        self.messages = []

    def send(self, user_message: str) -> Iterator[Event]:
        """Send one user message and run the agent loop, yielding events as they happen."""
        self.messages.append({"role": "user", "content": user_message})
        usage = Usage()

        for _turn in range(self.max_turns):
            with self._stream() as stream:
                for event in stream:
                    if event.type == "text":  # a chunk of answer text
                        yield TextDelta(event.text)
                response = stream.get_final_message()
            usage.add(response.usage)
            self.total_usage.add(response.usage)

            # Claude's turn goes into memory unchanged (text, tool_use and thinking blocks).
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                yield Done(self._final_text(response), usage)
                return

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                yield ToolCall(block.name, block.input)
                result, is_error = self.tool_runner(block.name, block.input)
                yield ToolResult(block.name, is_error)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,  # links this result to Claude's request
                        "content": result,
                        "is_error": is_error,
                    }
                )
            # All results go back together, in a single user message.
            self.messages.append({"role": "user", "content": tool_results})

        yield Done(
            f"Stopped after {self.max_turns} turns without a final answer (safety limit). "
            "Try a narrower question.",
            usage,
        )

    def write_note(self) -> tuple[ResearchNote, Usage]:
        """Turn the research conversation so far into a structured, validated ResearchNote.

        The request is the same conversation plus one instruction, so the cached prefix is
        reused. The note request is not added to memory, so chatting can continue after it.
        """
        if not self.messages:
            raise ValueError("Nothing to summarize yet - ask a research question first.")
        note_request = {"role": "user", "content": NOTE_INSTRUCTIONS}
        # Streamed, with a large max_tokens: thinking tokens and the note's JSON share
        # one output budget, and a long comparison can need a lot of both. (With 16k,
        # Sonnet 4.6 thought for ~15k tokens and the JSON was cut off mid-string.)
        with self.client.beta.messages.stream(
            **self._request_options([*self.messages, note_request]),
            max_tokens=64000,
            tool_choice={"type": "none"},  # write the note now; no more data fetching
            output_format=ResearchNote,  # the reply must match this Pydantic model
        ) as stream:
            try:
                response = stream.get_final_message()  # parses + validates the JSON
            except ValidationError as e:
                raise ValueError(
                    "The note came back incomplete or malformed. Try again, or narrow the "
                    "question (fewer companies or metrics)."
                ) from e
        usage = Usage()
        usage.add(response.usage)
        self.total_usage.add(response.usage)
        if response.stop_reason == "max_tokens":
            raise ValueError("The note hit the output limit before it was finished.")
        if response.parsed_output is None:  # e.g. a refusal, so there is no JSON to parse
            raise ValueError(f"Could not produce a note (stop reason: {response.stop_reason})")
        return response.parsed_output, usage

    def _stream(self):
        return self.client.beta.messages.stream(
            **self._request_options(self.messages),
            max_tokens=64000,  # streaming avoids HTTP timeouts, so give long answers room
        )

    @staticmethod
    def _request_options(messages: list[dict]) -> dict:
        """Settings shared by every request. Keeping system + tools identical across
        requests is what lets the prompt cache be reused.

        Prompt caching: the conversation prefix (tools + system + history) is re-sent every
        turn; caching it makes those repeated input tokens ~90% cheaper.
        """
        options = {"tools": TOOLS, **provider_options()}  # model, thinking, fallbacks...
        if automatic_caching():
            # One setting: the API caches up to the end of the request automatically.
            return {
                **options,
                "system": SYSTEM_PROMPT,
                "messages": messages,
                "cache_control": CACHE,
            }
        # Explicit breakpoints: cache everything up to the end of the system prompt, and
        # everything up to the end of the newest message.
        return {
            **options,
            "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": CACHE}],
            "messages": _with_cache_breakpoint(messages),
        }

    @staticmethod
    def _final_text(response) -> str:
        if response.stop_reason == "refusal":
            return "Claude declined to answer this request."
        text = "".join(block.text for block in response.content if block.type == "text")
        if response.stop_reason == "max_tokens":
            text += "\n\n[Answer cut off: hit the max_tokens limit.]"
        return text


def _with_cache_breakpoint(messages: list[dict]) -> list[dict]:
    """Copy of `messages` with a cache breakpoint on the last block of the last message.

    Copies instead of editing in place, so the agent's memory never accumulates markers
    (a request may have at most 4 breakpoints).
    """
    *earlier, last = messages
    content = last["content"]
    if isinstance(content, str):
        blocks = [{"type": "text", "text": content}]
    else:  # a list of blocks: dicts (tool results) or SDK objects (Claude's replies)
        blocks = [b if isinstance(b, dict) else b.model_dump(exclude_none=True) for b in content]
    blocks[-1] = {**blocks[-1], "cache_control": CACHE}
    return [*earlier, {**last, "content": blocks}]
