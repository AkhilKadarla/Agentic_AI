"""Calls to Claude.

Phase 3, step 1 - `ask()`: a single request/response, no tools.
Phase 3, step 2 - `research()`: one tool-use round trip. Claude can ask us to run a tool,
we run it and send back the result, and Claude answers using real data.
"""

from collections.abc import Callable
from dataclasses import dataclass

import anthropic

from finsight.config import MODEL
from finsight.tools import TOOLS, run_tool

SYSTEM_PROMPT = """You are FinSight, a financial research analyst assistant.
Explain financial concepts, companies, and filings clearly and accurately.
When you are unsure or lack current data, say so instead of guessing.
You provide educational analysis, not investment advice."""


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
) -> Answer:
    """Answer a question with ONE round of tool use.

    1. Send the question plus the tool definitions.
    2. If Claude replies with stop_reason "tool_use", run each requested tool.
    3. Send the results back so Claude can write its final answer.

    If Claude still wants more tools after that, we stop - handling any number of rounds
    is exactly what the agent loop in step 3 adds.
    """
    client = client or anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]

    response = _create(client, messages, tools=TOOLS)
    input_tokens, output_tokens = response.usage.input_tokens, response.usage.output_tokens

    if response.stop_reason == "tool_use":
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

        response = _create(client, messages, tools=TOOLS)
        input_tokens += response.usage.input_tokens
        output_tokens += response.usage.output_tokens

        if response.stop_reason == "tool_use":
            return Answer(
                "Claude wanted to call more tools - multi-step research arrives with the "
                "agent loop in Phase 3, step 3.",
                input_tokens,
                output_tokens,
            )

    return Answer(_text_of(response), input_tokens, output_tokens)
