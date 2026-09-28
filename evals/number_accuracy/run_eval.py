"""Run the number-accuracy eval: the real FinSight agent on every case, graded and logged.

    uv run python -m evals.number_accuracy.run_eval --approve-harness   # you, after review
    uv run python -m evals.number_accuracy.run_eval --only aapl_revenue,fake_ticker  # pilot
    uv run python -m evals.number_accuracy.run_eval                     # all cases
    uv run python -m evals.number_accuracy.run_eval --report            # summary only

Setup under test (agreed Phase 7): Claude Sonnet 4.6 on Amazon Bedrock, guardrail OFF
and Knowledge Base OFF (this eval measures the agent's numbers, nothing else). Traps are
judged by Claude Haiku 4.5 on Bedrock.

Output: .claude/hillclimb/number_accuracy/<variant>/
  results.jsonl        one row per (case, rep), written as each case finishes (resumable)
  traces/<id>_rep<k>.json   the full conversation for that case
  errors.jsonl         attempts that failed before they could be graded
  report.md            summary + per-case table (regenerate with --report)
"""

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic

from evals.number_accuracy.grading import grade_numbers, judge_trap
from finsight import config
from finsight.agent import Done, ResearchAgent, ToolCall, Usage
from finsight.llm import SYSTEM_PROMPT
from finsight.providers import make_client, model_id, pricing_key

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FLOW = ROOT / ".claude/hillclimb/number_accuracy"
JUDGE_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
STATE = {
    "flow": "number_accuracy",
    "metrics": [
        {"id": "correct", "label": "Correct", "kind": "binary"},
        {"id": "from_data", "label": "From data", "kind": "binary"},
    ],
    "perf_fields": ["latency_s", "tool_calls", "cost_usd"],
    # Everything that can change a score. Editing any of these requires re-approval.
    "harness_paths": [
        "evals/number_accuracy/run_eval.py",
        "evals/number_accuracy/grading.py",
        "evals/number_accuracy/cases.jsonl",
        "src/finsight/agent.py",
        "src/finsight/tools.py",
        "src/finsight/llm.py",
        "src/finsight/sec.py",
        "src/finsight/providers.py",
        "src/finsight/config.py",
    ],
}
RETRYABLE = (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError)
_write_lock = threading.Lock()


# ---------- harness gate ----------


def harness_sha() -> str:
    digest = hashlib.sha256()
    for path in STATE["harness_paths"]:
        digest.update(path.encode() + b"\0" + (ROOT / path).read_bytes())
    return digest.hexdigest()


def check_harness(approve: bool) -> None:
    approval = FLOW / "_harness_approval.json"
    current = harness_sha()
    if approve:
        FLOW.mkdir(parents=True, exist_ok=True)
        approval.write_text(json.dumps({"sha": current, "approved_at": time.ctime()}))
        print(f"Harness approved (sha {current[:12]}).")
        return
    approved = json.loads(approval.read_text())["sha"] if approval.exists() else None
    if approved != current:
        print(
            "The eval harness (runner, grader, cases or FinSight code) changed since it was "
            "last approved.\nReview the changes, then run:\n"
            "  uv run python -m evals.number_accuracy.run_eval --approve-harness"
        )
        raise SystemExit(2)


# ---------- running one case ----------


def configure_system_under_test() -> None:
    config.PROVIDER = "bedrock"
    config.GUARDRAIL_ID = None
    config.KB_ID = None


def run_agent(question: str) -> dict:
    agent = ResearchAgent()
    start = time.monotonic()
    done, tool_calls = None, 0
    for event in agent.send(question):
        if isinstance(event, ToolCall):
            tool_calls += 1
        elif isinstance(event, Done):
            done = event
    return {
        "answer": done.text,
        "model": done.model,
        "stop_reason": done.stop_reason,
        "usage": done.usage,
        "latency_s": round(time.monotonic() - start, 2),
        "tool_calls": tool_calls,
        "messages": agent.messages,
    }


def tool_result_texts(messages: list[dict]) -> list[str]:
    return [
        block["content"]
        for m in messages
        if m["role"] == "user" and isinstance(m["content"], list)
        for block in m["content"]
        if block.get("type") == "tool_result" and not block.get("is_error")
    ]


def to_trace(messages: list[dict]) -> list[dict]:
    """The conversation in the report's trace format."""
    trace = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in messages:
        if isinstance(m["content"], str):
            trace.append({"role": m["role"], "content": m["content"]})
            continue
        thinking = None
        for block in m["content"]:
            kind = block["type"] if isinstance(block, dict) else block.type
            if kind == "tool_result":
                trace.append({"role": "tool_result", "content": block["content"]})
            elif kind == "thinking":
                thinking = block.thinking or None
            elif kind == "tool_use":
                turn = {
                    "role": "tool_call",
                    "name": block.name,
                    "content": json.dumps(block.input, indent=2),
                }
                trace.append(turn | ({"thinking": thinking} if thinking else {}))
                thinking = None
            elif kind == "text":
                turn = {"role": "assistant", "content": block.text}
                trace.append(turn | ({"thinking": thinking} if thinking else {}))
                thinking = None
    return trace


def with_retries(fn, attempts: int = 3):
    """Retry transient API errors with jittered backoff; returns (result, retries)."""
    for attempt in range(attempts):
        try:
            return fn(), attempt
        except RETRYABLE:
            if attempt == attempts - 1:
                raise
            time.sleep(2**attempt * 5 + random.uniform(0, 3))
    raise AssertionError("unreachable")


def run_case(case: dict, rep: int, out: Path, judge_client) -> None:
    run, retries = with_retries(lambda: run_agent(case["question"]))
    expected_model = pricing_key(model_id())
    if pricing_key(run["model"]) != expected_model:
        raise RuntimeError(f"model mismatch: asked {expected_model}, served {run['model']}")

    judge_usage, judge_model = None, None
    if case["unavailable"]:
        result, judge_usage = judge_trap(case, run["answer"], judge_client, JUDGE_MODEL)
        judge_model = result.pop("judge_model")
    else:
        result = grade_numbers(case, run["answer"], tool_result_texts(run["messages"]))

    usage: Usage = run["usage"]
    row = {
        "prompt_id": case["id"],
        "rep": rep,
        "prompt": case["question"],
        "tags": case["tags"],
        "status": "truncated" if run["stop_reason"] == "max_tokens" else "ok",
        "stop_reason": run["stop_reason"],
        "grade": result["grade"],
        "explanation": result["explanation"],
        "model": run["model"],
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_input_tokens": usage.cache_read_tokens,
            "cache_creation_input_tokens": usage.cache_write_tokens,
        },
        "judge_model": judge_model,
        "judge_usage": judge_usage,
        "latency_s": run["latency_s"],
        "tool_calls": run["tool_calls"],
        "retries": retries,
        "answer": run["answer"],
    }
    (out / "traces").mkdir(parents=True, exist_ok=True)
    trace = to_trace(run["messages"])
    (out / "traces" / f"{case['id']}_rep{rep}.json").write_text(json.dumps(trace, indent=1))
    with _write_lock, (out / "results.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")


def run_with_ceiling(case: dict, rep: int, out: Path, judge_client, timeout_s: float) -> None:
    """Run one case with a hard wall-clock limit; failures go to errors.jsonl."""
    error: list[BaseException] = []

    def target():
        try:
            run_case(case, rep, out, judge_client)
        except BaseException as e:  # recorded below, never silently dropped
            error.append(e)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        failure, detail = "timeout", f"no result after {timeout_s:.0f}s"
    elif error:
        e = error[0]
        failure = (
            "refusal_or_api_error"
            if isinstance(e, anthropic.APIError)
            else "model_mismatch"
            if "model mismatch" in str(e)
            else "harness_error"
        )
        detail = f"{type(e).__name__}: {e}"
    else:
        print(f"  done  {case['id']} (rep {rep})")
        return
    print(f"  ERROR {case['id']} (rep {rep}): {failure} - {detail[:120]}")
    with _write_lock, (out / "errors.jsonl").open("a") as f:
        row = {"prompt_id": case["id"], "rep": rep, "failure": failure, "detail": detail}
        f.write(json.dumps(row) + "\n")


# ---------- report ----------


def load_rows(out: Path) -> list[dict]:
    path = out / "results.jsonl"
    return [json.loads(line) for line in path.open()] if path.exists() else []


def wilson(passed: int, n: int) -> tuple[float, float]:
    """95% confidence interval for a pass rate (honest about small samples)."""
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, passed / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def row_cost(row: dict) -> float:
    u = row["usage"]
    usage = Usage(
        u["input_tokens"],
        u["output_tokens"],
        u["cache_read_input_tokens"],
        u["cache_creation_input_tokens"],
    )
    cost = usage.cost_usd(row["model"]) or 0.0
    if row.get("judge_usage"):
        judge = Usage(row["judge_usage"]["input_tokens"], row["judge_usage"]["output_tokens"])
        cost += judge.cost_usd(row["judge_model"]) or 0.0
    return cost


def report(out: Path) -> str:
    rows = [r for r in load_rows(out) if r["status"] == "ok"]
    all_rows = load_rows(out)
    errors = (
        (out / "errors.jsonl").read_text().splitlines() if (out / "errors.jsonl").exists() else []
    )
    lines = [f"# Number accuracy - {out.name}", ""]
    if not all_rows:
        return "\n".join([*lines, "No results yet."])
    lines.append(
        f"{len(all_rows)} graded rows ({len(all_rows) - len(rows)} truncated, excluded) · "
        f"{len(errors)} failed attempts · model {all_rows[0]['model']}"
    )
    lines.append("")
    for metric in STATE["metrics"]:
        passed = sum(r["grade"][metric["id"]] for r in rows)
        low, high = wilson(int(passed), len(rows))
        lines.append(
            f"- **{metric['label']}: {passed:.0f}/{len(rows)} = {passed / len(rows):.0%}** "
            f"(95% CI {low:.0%}-{high:.0%})"
        )
    costs, latencies = [row_cost(r) for r in all_rows], [r["latency_s"] for r in all_rows]
    lines += [
        f"- Cost: ${sum(costs):.3f} total, ${statistics.median(costs):.4f} median per case",
        f"- Latency: {statistics.median(latencies):.1f}s median, {max(latencies):.1f}s max",
        "",
        "| Case | Type | Correct | From data | Tools | Latency | Cost | Why |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(all_rows, key=lambda r: (r["tags"][0], r["prompt_id"])):
        g, why = r["grade"], r["explanation"]
        note = (
            why["correct"] if not g["correct"] else (why["from_data"] if not g["from_data"] else "")
        )
        lines.append(
            f"| [{r['prompt_id']}](traces/{r['prompt_id']}_rep{r['rep']}.json) | {r['tags'][0]} | "
            f"{'✅' if g['correct'] else '❌'} | {'✅' if g['from_data'] else '❌'} | "
            f"{r['tool_calls']} | {r['latency_s']:.0f}s | ${row_cost(r):.4f} | {note[:90]} |"
        )
    return "\n".join(lines)


# ---------- main ----------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--variant", default="baseline")
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--only", help="comma-separated case ids (pilot runs)")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--timeout-s", type=float, default=420)
    parser.add_argument("--approve-harness", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    out = FLOW / args.variant
    if args.report:
        text = report(out)
        (out / "report.md").write_text(text)
        print(text)
        return 0

    check_harness(args.approve_harness)
    if args.approve_harness:
        return 0

    FLOW.mkdir(parents=True, exist_ok=True)
    (FLOW / "_state.json").write_text(json.dumps(STATE, indent=2))
    configure_system_under_test()
    cases = [json.loads(line) for line in (HERE / "cases.jsonl").open()]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    done = {(r["prompt_id"], r["rep"]) for r in load_rows(out)}
    todo = [(c, rep) for c in cases for rep in range(args.reps) if (c["id"], rep) not in done]
    print(f"{len(todo)} case runs to do ({len(done)} already done) on {model_id()}")
    out.mkdir(parents=True, exist_ok=True)
    judge_client = make_client("bedrock")

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for case, rep in todo:
            pool.submit(run_with_ceiling, case, rep, out, judge_client, args.timeout_s)
    text = report(out)
    (out / "report.md").write_text(text)
    print(f"\nFinished in {time.monotonic() - started:.0f}s\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
