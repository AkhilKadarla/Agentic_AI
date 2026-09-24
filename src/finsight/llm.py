"""Calls to Claude.

- `ask()`: a single request/response, no tools.
- `research()`: the agent loop. Claude calls tools (live SEC data) as many rounds as it
  needs, then answers.
"""

from collections.abc import Callable
from dataclasses import dataclass

import anthropic

from finsight.config import MODEL
from finsight.tools import TOOLS, run_tool

SYSTEM_PROMPT = """You are FinSight, a financial research analyst assistant.
Explain financial concepts, companies, and filings clearly and accurately.
When you are unsure or lack current data, say so instead of guessing.
You provide educational analysis, not investment advice.

When a question is about a specific company, use your tools to get real data from SEC
filings rather than relying on memory. Plan which data you need, fetch it (in parallel
when calls are independent), and base your answer on the fetched figures. State the fiscal
periods you are using and show key numbers, including any calculations you make."""

MAX_TURNS = 10


@dataclass
class Answer:
    text: str
    input_tokens: int
    output_tokens: int


def _create(client: anthropic.Anthropic, messages: list, **kwargs):
    return client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=messages,
        # If a safety classifier declines the request, the API retries it on a
        # fallback model automatically instead of just stopping.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        **kwargs,
    )


def _text_of(response) -> str:
    if response.stop_reason == "refusal":
        return "Claude declined to answer this request."
    # The response is a list of content blocks (text, thinking, tool_use...); keep only text.
    return "".join(block.text for block in response.content if block.type == "text")


def ask(question: str, client: anthropic.Anthropic | None = None) -> Answer:
    """Send one question to Claude and return its answer plus token usage."""
    client = client or anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    response = _create(client, [{"role": "user", "content": question}])
    return Answer(
        text=_text_of(response),
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


def research(
    question: str,
    client: anthropic.Anthropic | None = None,
    tool_runner: Callable[[str, dict], tuple[str, bool]] = run_tool,
    on_tool_call: Callable[[str, dict], None] | None = None,
    max_turns: int = MAX_TURNS,
) -> Answer:
    """The agent loop: let Claude call tools, round after round, until it has an answer.

    Each turn:
      1. Send the whole conversation so far (plus the tool definitions) to Claude.
      2. If Claude is done (stop_reason != "tool_use"), return its answer.
      3. Otherwise run every tool it asked for, append the results, and go again.

    `max_turns` is a safety limit: an agent that keeps calling tools would otherwise
    keep spending money forever.
    """
    client = client or anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]
    input_tokens = output_tokens = 0

    for _turn in range(max_turns):
        response = _create(client, messages, tools=TOOLS)
        input_tokens += response.usage.input_tokens
        output_tokens += response.usage.output_tokens

        if response.stop_reason != "tool_use":
            text = _text_of(response)
            if response.stop_reason == "max_tokens":
                text += "\n\n[Answer cut off: hit the max_tokens limit.]"
            return Answer(text, input_tokens, output_tokens)

        # Claude's turn (including its tool_use blocks) must go into the history unchanged.
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if on_tool_call:
                on_tool_call(block.name, block.input)
            result, is_error = tool_runner(block.name, block.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,  # links this result to Claude's request
                    "content": result,
                    "is_error": is_error,
                }
            )
        # All results go back together, in a single user message.
        messages.append({"role": "user", "content": tool_results})

    return Answer(
        f"Stopped after {max_turns} turns without a final answer (safety limit). "
        "Try a narrower question.",
        input_tokens,
        output_tokens,
    )
