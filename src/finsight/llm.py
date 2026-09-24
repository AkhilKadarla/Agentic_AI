"""Phase 3, step 1: a single call to Claude. No tools and no loop yet.

Everything an "agent" does is built on top of this one request/response cycle:
we send a system prompt + a user message, and Claude sends back content blocks.
"""

from dataclasses import dataclass

import anthropic

from finsight.config import MODEL

SYSTEM_PROMPT = """You are FinSight, a financial research analyst assistant.
Explain financial concepts, companies, and filings clearly and accurately.
When you are unsure or lack current data, say so instead of guessing.
You provide educational analysis, not investment advice."""


@dataclass
class Answer:
    text: str
    input_tokens: int
    output_tokens: int


def ask(question: str, client: anthropic.Anthropic | None = None) -> Answer:
    """Send one question to Claude and return its answer plus token usage."""
    client = client or anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": question}],
        # If a safety classifier declines the request, the API retries it on a
        # fallback model automatically instead of just stopping.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )

    if response.stop_reason == "refusal":
        text = "Claude declined to answer this request."
    else:
        # The response is a list of content blocks (text, thinking, ...); keep only text.
        text = "".join(block.text for block in response.content if block.type == "text")

    return Answer(
        text=text,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
