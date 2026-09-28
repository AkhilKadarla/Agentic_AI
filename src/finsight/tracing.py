"""Observability: record every step of every question as OpenTelemetry spans.

A *trace* is one question from start to finish; each *span* inside it is one timed step
(a model call, a tool call, a guardrail check) with details attached as attributes:

    research "Why did Costco's revenue grow?"          14.2s  $0.027
    ├─ guardrail.input                                   0.4s  passed
    ├─ chat us.anthropic.claude-sonnet-4-6               3.1s  1,520 tokens
    ├─ execute_tool get_financial_facts                  0.6s  ok
    └─ ...

Attribute names follow OpenTelemetry's GenAI conventions (gen_ai.*), so tools such as
AWS X-Ray or Datadog can read these traces without translation. Locally, spans are written
as JSON lines to logs/traces/<date>.jsonl (git-ignored), and files older than the
retention period are deleted. Phase 8 can swap the file exporter for an OTLP exporter
without touching the instrumented code.

Settings: FINSIGHT_TRACING=on|off, FINSIGHT_TRACE_CONTENT=on|off (record question and
answer text), FINSIGHT_TRACE_RETENTION_DAYS (default 30).
"""

import json
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode

from finsight import __version__, config

TRACE_DIR = Path("logs/traces")
_provider: TracerProvider | None = None


class JsonlFileExporter(SpanExporter):
    """Writes each finished span as one JSON line in a per-day file."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or TRACE_DIR

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{date.today().isoformat()}.jsonl"
        with path.open("a") as f:
            for span in spans:
                f.write(json.dumps(span_to_dict(span)) + "\n")
        return SpanExportResult.SUCCESS


def span_to_dict(span: ReadableSpan) -> dict:
    return {
        "trace_id": f"{span.context.trace_id:032x}",
        "span_id": f"{span.context.span_id:016x}",
        "parent_id": f"{span.parent.span_id:016x}" if span.parent else None,
        "name": span.name,
        "start_ns": span.start_time,
        "end_ns": span.end_time,
        "status": span.status.status_code.name,
        "attributes": dict(span.attributes or {}),
    }


def delete_old_traces(directory: Path, retention_days: int) -> list[Path]:
    """Retention: remove per-day trace files older than `retention_days`."""
    cutoff = date.today() - timedelta(days=retention_days)
    removed = []
    for path in directory.glob("*.jsonl"):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue  # not a trace file
        if day < cutoff:
            path.unlink()
            removed.append(path)
    return removed


def configure(exporter: SpanExporter | None = None) -> TracerProvider:
    """Set up the tracer provider (once). Tests pass an in-memory exporter."""
    global _provider
    _provider = TracerProvider(
        resource=Resource.create({"service.name": "finsight", "service.version": __version__})
    )
    if exporter is None:
        exporter = JsonlFileExporter()
        delete_old_traces(TRACE_DIR, config.TRACE_RETENTION_DAYS)
    # Simple (synchronous) processor: every span is on disk the moment it ends, which suits
    # short CLI runs. A server would use BatchSpanProcessor to export in the background.
    _provider.add_span_processor(SimpleSpanProcessor(exporter))
    return _provider


def tracer() -> trace.Tracer:
    if not config.TRACING:
        return trace.NoOpTracer()
    return (_provider or configure()).get_tracer("finsight")


def content(text: str) -> str | None:
    """Question/answer text, only when content capture is on (it may be sensitive)."""
    return text[:4000] if config.TRACE_CONTENT else None


def set_attributes(span: trace.Span, **attributes) -> None:
    """Set attributes, skipping None values (OpenTelemetry rejects them)."""
    span.set_attributes({k.replace("__", "."): v for k, v in attributes.items() if v is not None})


# ---------- reading traces back (finsight traces) ----------


def load_spans(directory: Path | None = None) -> list[dict]:
    spans = []
    for path in sorted((directory or TRACE_DIR).glob("*.jsonl")):
        spans += [json.loads(line) for line in path.open()]
    return spans


def summarize(spans: list[dict]) -> list[dict]:
    """One summary row per trace (question), newest first."""
    roots = [s for s in spans if s["parent_id"] is None]
    children: dict[str, list[dict]] = {}
    for s in spans:
        children.setdefault(s["trace_id"], []).append(s)
    rows = []
    for root in roots:
        attrs = root["attributes"]
        steps = children[root["trace_id"]]
        rows.append(
            {
                "trace_id": root["trace_id"],
                "name": root["name"],
                "when": datetime.fromtimestamp(root["start_ns"] / 1e9).strftime("%Y-%m-%d %H:%M"),
                "seconds": (root["end_ns"] - root["start_ns"]) / 1e9,
                "question": attrs.get("finsight.question", "(content capture off)"),
                "model": attrs.get("gen_ai.request.model", ""),
                "cost_usd": attrs.get("finsight.cost_usd"),
                "tool_calls": sum(1 for s in steps if s["name"].startswith("execute_tool")),
                "outcome": attrs.get("finsight.outcome", root["status"]),
            }
        )
    return sorted(rows, key=lambda r: r["when"], reverse=True)


def render_tree(spans: list[dict], trace_id_prefix: str) -> str:
    """A trace as an indented tree with timing and key details per step."""
    trace_spans = [s for s in spans if s["trace_id"].startswith(trace_id_prefix)]
    if not trace_spans:
        return f"No trace starting with {trace_id_prefix!r}."
    by_parent: dict[str | None, list[dict]] = {}
    for s in trace_spans:
        by_parent.setdefault(s["parent_id"], []).append(s)
    lines: list[str] = []

    def walk(span: dict, prefix: str, last: bool, depth: int) -> None:
        seconds = (span["end_ns"] - span["start_ns"]) / 1e9
        branch = "" if depth == 0 else ("└─ " if last else "├─ ")
        lines.append(f"{prefix}{branch}{span['name']}  {seconds:.1f}s  {_details(span)}".rstrip())
        kids = sorted(by_parent.get(span["span_id"], []), key=lambda s: s["start_ns"])
        for i, kid in enumerate(kids):
            extension = "" if depth == 0 else ("   " if last else "│  ")
            walk(kid, prefix + extension, i == len(kids) - 1, depth + 1)

    for root in by_parent.get(None, []):
        walk(root, "", True, 0)
    return "\n".join(lines)


def _details(span: dict) -> str:
    a = span["attributes"]
    parts = []
    if "gen_ai.usage.input_tokens" in a:
        parts.append(
            f"{a['gen_ai.usage.input_tokens']}+{a.get('finsight.cache_read_tokens', 0)}"
            f" cached in / {a['gen_ai.usage.output_tokens']} out"
        )
    for key in (
        "gen_ai.response.finish_reasons",
        "finsight.tool.is_error",
        "finsight.outcome",
        "finsight.guardrail.result",
        "finsight.cost_usd",
    ):
        if key in a:
            value = a[key]
            label = key.rsplit(".", 1)[-1]
            parts.append(f"{label}={value:.4f}" if isinstance(value, float) else f"{label}={value}")
    if "finsight.question" in a:
        parts.append(repr(a["finsight.question"][:70]))
    return " · ".join(parts)


# ---------- creating spans ----------


@contextmanager
def child_span(t: trace.Tracer, parent: Context, name: str, **attributes):
    """A span under `parent`, ended when the block exits.

    Deliberately does NOT make the span "current": the agent is a generator that yields
    mid-span (streaming), and a context attached before a `yield` can't safely be detached
    after it. Passing the parent explicitly avoids that.
    """
    span = t.start_span(name, context=parent)
    set_attributes(span, **attributes)
    try:
        yield span
    except Exception as e:  # not GeneratorExit: a reader stopping early isn't an error
        span.record_exception(e)
        span.set_status(Status(StatusCode.ERROR, str(e)[:200]))
        raise
    finally:
        span.end()


PROVIDER_NAMES = {"anthropic": "anthropic", "bedrock": "aws.bedrock"}  # gen_ai.provider.name
