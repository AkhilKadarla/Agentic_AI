"""Command-line interface: `uv run finsight <command>`."""

import argparse
import subprocess
import sys
from pathlib import Path

import anthropic

from finsight import __version__, config
from finsight.agent import (
    Done,
    GuardrailBlocked,
    GuardrailReport,
    ResearchAgent,
    TextDelta,
    ToolCall,
    ToolResult,
    Usage,
)
from finsight.llm import ask
from finsight.notes import render_markdown, save_note
from finsight.providers import AWS_CREDENTIAL_ERRORS, AWS_LOGIN_HINT, describe

CHAT_HELP = (
    "Commands: /note (save a research note), /reset (forget conversation), "
    "/usage (tokens so far), /exit"
)


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
    note_cmd = commands.add_parser(
        "note", help="research a question and save a structured research note"
    )
    note_cmd.add_argument("question", help='e.g. "Assess Apple\'s financial health"')
    commands.add_parser("chat", help="interactive research chat with follow-up questions")
    commands.add_parser("ui", help="open the FinSight web app in your browser")
    commands.add_parser(
        "remote", help="log in and chat with the deployed FinSight (AgentCore Runtime)"
    )
    commands.add_parser(
        "mcp", help="run FinSight's SEC tools as an MCP server (started by Claude Code etc.)"
    )
    index_cmd = commands.add_parser(
        "index", help="add companies' latest 10-K text to the Knowledge Base (or --list)"
    )
    index_cmd.add_argument("tickers", nargs="*", help="e.g. TSLA AAPL")
    index_cmd.add_argument("--list", action="store_true", help="show what is indexed")
    traces_cmd = commands.add_parser("traces", help="list recent traces, or show one step by step")
    traces_cmd.add_argument("trace_id", nargs="?", help="show this trace (first few characters)")
    traces_cmd.add_argument("--limit", type=int, default=15)
    args = parser.parse_args(argv)

    if args.command is None:
        print(f"FinSight v{__version__} - AI financial research agent")
        print('Try: uv run finsight ask "What is EBITDA?"')
        print('     uv run finsight research "How has NVIDIA\'s revenue grown?"')
        print("     uv run finsight chat")
        print("     uv run finsight ui")
        return
    if args.command == "traces":
        return show_traces(args.trace_id, args.limit)
    if args.command == "index":
        return index(args.tickers, show_list=args.list)
    if args.command == "remote":
        return remote_chat()
    if args.command == "mcp":
        # stdout carries the MCP protocol itself, so nothing else may be printed here
        from finsight import mcp_server

        return mcp_server.main()
    if args.command == "ui":
        app = Path(__file__).with_name("ui.py")
        print("Starting FinSight - open http://localhost:8501 (Ctrl+C to stop)")
        raise SystemExit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(app)]))

    try:
        if args.command == "ask":
            answer = ask(args.question)
            print(answer.text)
            print(f"\n[tokens used: {answer.input_tokens} in / {answer.output_tokens} out]")
        elif args.command == "research":
            print_events(ResearchAgent().send(args.question))
        elif args.command == "note":
            agent = ResearchAgent()
            print_events(agent.send(args.question))
            make_note(agent)
        else:
            chat()
    except anthropic.AuthenticationError:
        raise SystemExit("Invalid API key - check ANTHROPIC_API_KEY in your .env file.") from None
    except anthropic.RateLimitError:
        raise SystemExit("Rate limited by the API - wait a minute and try again.") from None
    except anthropic.APIConnectionError:
        raise SystemExit("Could not reach the Claude API - check your connection.") from None
    except AWS_CREDENTIAL_ERRORS:
        raise SystemExit(AWS_LOGIN_HINT.format(profile=config.AWS_PROFILE)) from None


def show_traces(trace_id: str | None, limit: int) -> None:
    from finsight import tracing

    spans = tracing.load_spans()
    if trace_id:
        print(tracing.render_tree(spans, trace_id))
        return
    rows = tracing.summarize(spans)[:limit]
    if not rows:
        print(f"No traces yet in {tracing.TRACE_DIR}/ - ask FinSight something first.")
        return
    print(f"{'trace':9} {'when':16} {'secs':>5} {'cost':>7} {'tools':>5}  {'outcome':10} question")
    for r in rows:
        cost = f"${r['cost_usd']:.3f}" if r["cost_usd"] is not None else "-"
        print(
            f"{r['trace_id'][:8]:9} {r['when']:16} {r['seconds']:5.1f} {cost:>7} "
            f"{r['tool_calls']:5}  {r['outcome']:10} {r['question'][:60]}"
        )
    print("\nShow one: uv run finsight traces <trace>")


def index(tickers: list[str], show_list: bool = False) -> None:
    """Prepare companies ahead of time: extract 10-K sections, upload, then one sync."""
    from finsight import knowledge_base, sec
    from finsight.filings import latest_10k

    try:
        knowledge_base.require_config()
        if show_list or not tickers:
            indexed = knowledge_base.indexed_filings()
            print("Indexed 10-Ks:" if indexed else "Nothing indexed yet.")
            for ticker, years in indexed.items():
                print(f"  {ticker}: fiscal years ending {', '.join(years)}")
            return
        http = sec.make_http_client()
        uploaded = 0
        for ticker in tickers:
            try:
                filing = latest_10k(ticker, http)
            except sec.CompanyNotFoundError as e:
                print(f"  {ticker}: skipped ({e})")
                continue
            knowledge_base.upload_filing(filing)
            uploaded += len(filing.sections)
            sizes = ", ".join(f"{s.title} {len(s.text) // 1000}K chars" for s in filing.sections)
            print(f"  {filing.ticker}: 10-K for FY ending {filing.report_date} - {sizes}")
            if filing.missing:
                print(f"    not found in the 10-K: {', '.join(filing.missing)}")
        if not uploaded:
            return
        print("Syncing the Knowledge Base (chunking + embedding; usually 1-5 minutes)...")
        stats = knowledge_base.sync()
        print(
            f"Done: {stats.get('numberOfNewDocumentsIndexed', 0)} new, "
            f"{stats.get('numberOfModifiedDocumentsIndexed', 0)} updated, "
            f"{stats.get('numberOfDocumentsFailed', 0)} failed."
        )
    except knowledge_base.KnowledgeBaseError as e:
        raise SystemExit(str(e)) from None


def chat(agent: ResearchAgent | None = None, read=input, label: str | None = None) -> None:
    """A read-eval-print loop: the same agent (and its memory) answers every message."""
    agent = agent or ResearchAgent()
    label = label or describe()
    print(f"FinSight chat [{label}] - ask about any US-listed company. {CHAT_HELP}\n")
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
        elif message == "/note":
            make_note(agent)
        elif message == "/usage":
            print(f"({format_usage(agent.total_usage)})\n")
        elif message:
            print("\nfinsight> ", end="")
            print_events(agent.send(message))
            print()


def remote_chat() -> None:
    """Chat with the deployed agent: same chat loop, a RemoteAgent instead of a local one."""
    from finsight import remote

    if not config.RUNTIME_ARN:
        raise SystemExit("Set FINSIGHT_RUNTIME_ARN in .env (the deployed runtime's ARN).")
    try:
        token = remote.login()
        chat(remote.RemoteAgent(token, config.RUNTIME_ARN), label="deployed on AgentCore")
    except (remote.LoginError, remote.RemoteError) as e:
        raise SystemExit(str(e)) from None


def make_note(agent: ResearchAgent) -> None:
    # This is one large, non-streamed call, so there is no progress output until it
    # finishes (can take a while for a long conversation) - print a note so it's not
    # mistaken for a hang.
    print("Writing research note... (this can take a minute, no streaming for structured output)")
    try:
        note, usage = agent.write_note()
    except ValueError as e:
        print(f"({e})\n")
        return
    except anthropic.APIStatusError as e:
        print(f"(Could not write the note: {e})\n")
        return
    except AWS_CREDENTIAL_ERRORS:
        print(f"({AWS_LOGIN_HINT.format(profile=config.AWS_PROFILE)})\n")
        return
    path = save_note(note)
    print(f"\n{render_markdown(note)}\n")
    print(f"Saved: {path} (+ .md)  [{format_usage(usage)}]\n")


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
            case GuardrailBlocked(message, reasons):
                print(f"[guardrail blocked: {', '.join(reasons) or 'policy'}] {message}", end="")
            case GuardrailReport():
                print(f"\n\n{describe_report(event)}", end="")
            case Done(usage=usage):
                print(f"\n\n[{format_usage(usage)}]")


def describe_report(report: GuardrailReport) -> str:
    """One terminal line (plus flagged paragraphs) for the guardrail's answer review."""
    if report.error:
        return f"[guardrail] UNVERIFIED - do not rely on this answer. {report.error}"
    if report.output and report.output.blocked:
        reasons = ", ".join(report.output.reasons) or "policy"
        return (
            f"[guardrail] FLAGGED ({reasons}) - disregard the answer above. {report.output.message}"
        )
    grounding = report.grounding
    if grounding and grounding.flagged:
        lines = [
            f"[guardrail] {len(grounding.flagged)} of {grounding.checked} paragraphs not directly "
            "supported by the fetched data (often calculations) - verify:"
        ]
        lines += [f"  - ({p.grounding:.2f}) {p.text[:100]}..." for p in grounding.flagged]
        return "\n".join(lines)
    checked = f", {grounding.checked} paragraphs grounded" if grounding else ""
    return f"[guardrail] passed{checked}"


def format_usage(usage: Usage) -> str:
    """Input tokens are billed in three buckets: uncached, written to cache, read from cache."""
    return (
        f"tokens in: {usage.input_tokens} new + {usage.cache_write_tokens} cache-write"
        f" + {usage.cache_read_tokens} cache-read | out: {usage.output_tokens}"
    )
