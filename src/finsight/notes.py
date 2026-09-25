"""Structured research notes.

A `ResearchNote` is a Pydantic model: a Python class with typed fields. We give it to
Claude as the required output format, and the API guarantees the reply matches the schema,
so we get a validated Python object instead of free text we would have to parse.
"""

import json
import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

REPORTS_DIR = Path("reports")  # git-ignored


class Metric(BaseModel):
    name: str = Field(description="Metric name, e.g. 'Revenue' or 'Net margin'")
    company: str = Field(description="Ticker the metric belongs to, e.g. 'AAPL'")
    period: str = Field(description="Fiscal period, e.g. 'FY2025 (ended 2025-09-27)'")
    value: float = Field(description="The number in full units, e.g. 416161000000 for $416.2B")
    unit: str = Field(description="'USD', 'USD/share', or '%'")
    derived: bool = Field(description="True if calculated from other figures, not reported")


class Source(BaseModel):
    description: str = Field(description="e.g. 'Apple 10-K XBRL data, fiscal years 2023-2025'")
    url: str = Field(description="Link to the filing, or empty string if none")


class ResearchNote(BaseModel):
    title: str
    tickers: list[str]
    summary: str = Field(description="2-4 sentence answer to the research question")
    key_metrics: list[Metric] = Field(description="The figures the analysis relies on")
    findings: list[str] = Field(description="Main analytical points, one sentence each")
    risks: list[str] = Field(description="Caveats, risks, or data limitations")
    sources: list[Source]
    data_as_of: str = Field(description="Latest period end date in the data, YYYY-MM-DD")
    confidence: Literal["high", "medium", "low"] = Field(
        description="How well the fetched data supports the conclusions"
    )


NOTE_INSTRUCTIONS = """Write a research note from the conversation so far.
Use only figures that appear in the tool results above; do not add numbers from memory.
Mark calculated figures (growth rates, margins, free cash flow) as derived.
If the data does not support a conclusion, say so in risks and lower the confidence.
Keep it focused: at most 12 key metrics (the figures your conclusions depend on) and
at most 6 findings."""


def format_value(value: float, unit: str) -> str:
    if unit == "%":
        return f"{value:.1f}%"
    if unit == "USD" and abs(value) >= 1e9:
        return f"${value / 1e9:,.1f}B"
    if unit == "USD" and abs(value) >= 1e6:
        return f"${value / 1e6:,.1f}M"
    if unit.startswith("USD/"):  # per-share figures such as EPS ("USD/shares")
        return f"${value:,.2f} per share"
    if unit == "USD":
        return f"${value:,.2f}"
    return f"{value:,} {unit}"


def render_markdown(note: ResearchNote) -> str:
    """Turn a note into readable Markdown (the terminal shows it; files keep it)."""
    lines = [
        f"# {note.title}",
        f"*{', '.join(note.tickers)} | data as of {note.data_as_of} | "
        f"confidence: {note.confidence}*",
        "",
        note.summary,
        "",
        "## Key metrics",
        "| Company | Metric | Period | Value |",
        "|---|---|---|---|",
    ]
    for m in note.key_metrics:
        flag = " (derived)" if m.derived else ""
        lines.append(
            f"| {m.company} | {m.name}{flag} | {m.period} | {format_value(m.value, m.unit)} |"
        )
    lines += ["", "## Findings", *[f"- {f}" for f in note.findings]]
    lines += ["", "## Risks & caveats", *[f"- {r}" for r in note.risks]]
    lines += ["", "## Sources"]
    lines += [f"- {s.description}" + (f" ({s.url})" if s.url else "") for s in note.sources]
    lines += ["", "*Educational analysis, not investment advice.*"]
    return "\n".join(lines)


def save_note(note: ResearchNote, directory: Path = REPORTS_DIR) -> Path:
    """Save the note as JSON (for code) and Markdown (for people). Returns the JSON path."""
    directory.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", note.title.lower()).strip("-")[:60]
    base = directory / f"{date.today().isoformat()}-{slug}"
    base.with_suffix(".json").write_text(json.dumps(note.model_dump(), indent=2))
    base.with_suffix(".md").write_text(render_markdown(note))
    return base.with_suffix(".json")
