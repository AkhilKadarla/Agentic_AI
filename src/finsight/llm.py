"""The simplest possible Claude call: `ask()` sends one request and gets one response.

The full agent (tools, loop, memory, streaming) lives in agent.py.
"""

from dataclasses import dataclass

import anthropic

from finsight.config import MODEL

SYSTEM_PROMPT = """You are FinSight, a financial research analyst assistant.
Explain financial concepts, companies, and filings clearly and accurately.
When you are unsure or lack current data, say so instead of guessing.
You provide educational analysis, not investment advice.

When a question is about a specific company, use your tools to get real data from SEC
filings rather than relying on memory. Plan which data you need, fetch it (in parallel
when calls are independent), and base your answer on the fetched figures. State the fiscal
periods you are using and show key numbers, including any calculations you make."""


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
