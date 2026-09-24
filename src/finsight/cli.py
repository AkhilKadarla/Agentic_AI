"""Command-line interface: `uv run finsight <command>`."""

import argparse

import anthropic

from finsight import __version__
from finsight.llm import ask


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="finsight", description="FinSight - AI financial research agent"
    )
    commands = parser.add_subparsers(dest="command")
    ask_cmd = commands.add_parser("ask", help="ask Claude a finance question (single LLM call)")
    ask_cmd.add_argument("question", help='e.g. "What is free cash flow?"')
    args = parser.parse_args(argv)

    if args.command != "ask":
        print(f"FinSight v{__version__} - AI financial research agent")
        print('Try: uv run finsight ask "What is EBITDA?"')
        return

    try:
        answer = ask(args.question)
    except anthropic.AuthenticationError:
        raise SystemExit("Invalid API key - check ANTHROPIC_API_KEY in your .env file.") from None
    except anthropic.RateLimitError:
        raise SystemExit("Rate limited by the API - wait a minute and try again.") from None
    except anthropic.APIConnectionError:
        raise SystemExit("Could not reach the Anthropic API - check your connection.") from None

    print(answer.text)
    print(f"\n[tokens used: {answer.input_tokens} in / {answer.output_tokens} out]")
