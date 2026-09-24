"""Command-line interface: `uv run finsight <command>`."""

import argparse

import anthropic

from finsight import __version__
from finsight.agent import Done, ResearchAgent, TextDelta, ToolCall, ToolResult, Usage
from finsight.llm import ask

CHAT_HELP = "Commands: /reset (forget conversation), /usage (tokens so far), /exit"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="finsight", description="FinSight - AI financial research agent"
    )
    commands = parser.add_subparsers(dest="command")
    ask_cmd = commands.add_parser("ask", help="ask Claude a finance question (single LLM call)")
    ask_cmd.add_argument("question", help='e.g. "What is free cash flow?"')
    research_cmd = commands.add_parser(
        "research", help="research one question using live SEC data (agent + tools)"
    )
    research_cmd.add_argument("question", help='e.g. "How has Apple\'s revenue changed?"')
    commands.add_parser("chat", help="interactive research chat with follow-up questions")
    args = parser.parse_args(argv)

    if args.command is None:
        print(f"FinSight v{__version__} - AI financial research agent")
        print('Try: uv run finsight ask "What is EBITDA?"')
        print('     uv run finsight research "How has NVIDIA\'s revenue grown?"')
        print("     uv run finsight chat")
        return

    try:
        if args.command == "ask":
            answer = ask(args.question)
            print(answer.text)
            print(f"\n[tokens used: {answer.input_tokens} in / {answer.output_tokens} out]")
        elif args.command == "research":
            print_events(ResearchAgent().send(args.question))
        else:
            chat()
    except anthropic.AuthenticationError:
        raise SystemExit("Invalid API key - check ANTHROPIC_API_KEY in your .env file.") from None
    except anthropic.RateLimitError:
        raise SystemExit("Rate limited by the API - wait a minute and try again.") from None
    except anthropic.APIConnectionError:
        raise SystemExit("Could not reach the Anthropic API - check your connection.") from None


def chat(agent: ResearchAgent | None = None, read=input) -> None:
    """A read-eval-print loop: the same agent (and its memory) answers every message."""
    agent = agent or ResearchAgent()
    print(f"FinSight chat - ask about any US-listed company. {CHAT_HELP}\n")
    while True:
        try:
            message = read("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            message = "/exit"

        if message == "/exit":
            print(f"\nBye! Session total: {format_usage(agent.total_usage)}")
            return
        if message == "/reset":
            agent.reset()
            print("(conversation cleared)\n")
        elif message == "/usage":
            print(f"({format_usage(agent.total_usage)})\n")
        elif message:
            print("\nfinsight> ", end="")
            print_events(agent.send(message))
            print()


def print_events(events) -> None:
    """Render agent events in the terminal as they arrive."""
    after_tools = False
    for event in events:
        match event:
            case TextDelta(text):
                if after_tools:  # start the answer on a fresh line after tool output
                    print("\n")
                    after_tools = False
                print(text, end="", flush=True)
            case ToolCall(name, tool_input):
                args = ", ".join(f"{key}={value!r}" for key, value in tool_input.items())
                print(f"\n  -> {name}({args})", end="", flush=True)
            case ToolResult(is_error=is_error):
                print("  [error]" if is_error else "  [ok]", end="", flush=True)
                after_tools = True
            case Done(usage=usage):
                print(f"\n\n[{format_usage(usage)}]")


def format_usage(usage: Usage) -> str:
    """Input tokens are billed in three buckets: uncached, written to cache, read from cache."""
    return (
        f"tokens in: {usage.input_tokens} new + {usage.cache_write_tokens} cache-write"
        f" + {usage.cache_read_tokens} cache-read | out: {usage.output_tokens}"
    )
