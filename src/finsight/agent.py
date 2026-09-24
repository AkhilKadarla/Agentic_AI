"""The FinSight research agent: an agent loop with conversation memory and streaming.

`ResearchAgent.send()` does not print anything. It *yields events* (text as it is written,
tool calls, tool results, and a final summary). Any interface can consume the same events:
the terminal CLI today, a web UI in Phase 5.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import anthropic

from finsight.config import MODEL
from finsight.llm import SYSTEM_PROMPT
from finsight.tools import TOOLS, run_tool

MAX_TURNS = 10


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
        client: anthropic.Anthropic | None = None,
        tool_runner: Callable[[str, dict], tuple[str, bool]] = run_tool,
        max_turns: int = MAX_TURNS,
    ) -> None:
        self.client = client or anthropic.Anthropic()
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

    def _stream(self):
        return self.client.beta.messages.stream(
            model=MODEL,
            max_tokens=64000,  # streaming avoids HTTP timeouts, so give long answers room
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=self.messages,
            # Prompt caching: the conversation prefix (system + tools + history) is re-sent
            # every turn; caching it makes those repeated input tokens ~90% cheaper.
            cache_control={"type": "ephemeral"},
            # If a safety classifier declines the request, the API retries it on a
            # fallback model automatically instead of just stopping.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

    @staticmethod
    def _final_text(response) -> str:
        if response.stop_reason == "refusal":
            return "Claude declined to answer this request."
        text = "".join(block.text for block in response.content if block.type == "text")
        if response.stop_reason == "max_tokens":
            text += "\n\n[Answer cut off: hit the max_tokens limit.]"
        return text
