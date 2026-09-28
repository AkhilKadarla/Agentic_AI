"""Amazon Bedrock Guardrails as an independent control layer around the agent.

The guardrail is called through the standalone ApplyGuardrail API, separately from the
model call, so the same compliance policy applies whichever provider runs Claude:

  question --> check_input()  --blocked--> guardrail message (Claude is never called)
  answer   --> check_output()     topics, personal data, content filters on the whole answer
           --> check_grounding()  is each paragraph supported by the SEC data we fetched?

Policy decisions (Phase 6):
  - "stream, then flag": answers stream live; the output checks run when they finish.
  - "fail closed": if the guardrail itself can't be reached, FinSight refuses to answer.
"""

import json
from dataclasses import dataclass, field
from datetime import date

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from finsight import config

# The grounding check accepts at most 5 text units (5,000 characters) of answer per call.
MAX_GROUNDING_CHARS = 5000
MIN_PARAGRAPH_CHARS = 200  # merge short pieces (headings, one-liners) into the next one
MAX_SOURCE_CHARS = 90_000  # keep the grounding source within the API's size limit

FAIL_CLOSED_MESSAGE = (
    "The compliance guardrail could not be reached, so FinSight won't answer right now "
    "(fail-closed policy). If your AWS login expired, run: aws sso login --profile {profile}"
)


class GuardrailUnavailable(Exception):
    """The guardrail service could not be called (network, permissions, expired login)."""


@dataclass
class Verdict:
    blocked: bool
    message: str = ""  # the guardrail's replacement text when it intervenes
    reasons: list[str] = field(default_factory=list)  # e.g. "topic: Insider information"


@dataclass
class FlaggedParagraph:
    text: str
    grounding: float  # 0-1: how well the source data supports it
    relevance: float  # 0-1: how well it addresses the question


@dataclass
class Grounding:
    checked: int  # paragraphs checked
    flagged: list[FlaggedParagraph]


class Guardrail:
    def __init__(self, guardrail_id: str, version: str, client=None) -> None:
        self.guardrail_id = guardrail_id
        self.version = version
        self.client = client or boto3.Session(
            profile_name=config.AWS_PROFILE, region_name=config.AWS_REGION
        ).client("bedrock-runtime")

    def check_input(self, question: str) -> Verdict:
        return self._verdict(self._apply("INPUT", [{"text": {"text": question}}]))

    def check_output(self, answer: str) -> Verdict:
        """Topics, personal data and content filters on the whole answer."""
        return self._verdict(self._apply("OUTPUT", [{"text": {"text": answer}}]))

    def check_grounding(self, answer: str, sources: list[str], question: str) -> Grounding:
        """Check each paragraph of the answer against the data the agent fetched.

        Paragraph by paragraph, because the check has a 5,000-character limit and one
        whole-answer score would hide *which* part is unsupported. Note: the check can't
        verify arithmetic, so calculated figures (growth rates, margins) often score low.
        """
        source = "\n".join(sources)[:MAX_SOURCE_CHARS]
        paragraphs = split_paragraphs(answer)
        flagged = []
        for paragraph in paragraphs:
            # Tables are checked as sentences (a correct table scored 0.61 as a grid,
            # 0.98 as sentences); the user still sees the original paragraph.
            checked_text = tables_to_sentences(paragraph)
            response = self._apply(
                "OUTPUT",
                [
                    {"text": {"text": source, "qualifiers": ["grounding_source"]}},
                    {"text": {"text": question[:1000], "qualifiers": ["query"]}},
                    {"text": {"text": checked_text, "qualifiers": ["guard_content"]}},
                ],
            )
            scores = _grounding_scores(response)
            if scores.get("GROUNDING", 1.0) < self._threshold(response, "GROUNDING"):
                flagged.append(
                    FlaggedParagraph(paragraph, scores["GROUNDING"], scores.get("RELEVANCE", 1.0))
                )
        return Grounding(checked=len(paragraphs), flagged=flagged)

    def _apply(self, source: str, content: list[dict]) -> dict:
        try:
            return self.client.apply_guardrail(
                guardrailIdentifier=self.guardrail_id,
                guardrailVersion=self.version,
                source=source,
                content=content,
            )
        except (BotoCoreError, ClientError) as e:
            raise GuardrailUnavailable(str(e)) from e

    @staticmethod
    def _verdict(response: dict) -> Verdict:
        if response["action"] != "GUARDRAIL_INTERVENED":
            return Verdict(blocked=False)
        message = "".join(o["text"] for o in response.get("outputs", []))
        return Verdict(blocked=True, message=message, reasons=_reasons(response))

    @staticmethod
    def _threshold(response: dict, kind: str) -> float:
        for a in response.get("assessments", []):
            for f in a.get("contextualGroundingPolicy", {}).get("filters", []):
                if f["type"] == kind:
                    return f["threshold"]
        return 0.0


def make_guardrail() -> Guardrail | None:
    """The configured guardrail, or None when FINSIGHT_GUARDRAIL_ID is not set."""
    if not config.GUARDRAIL_ID:
        return None
    if not config.GUARDRAIL_VERSION:
        raise ValueError(
            "FINSIGHT_GUARDRAIL_VERSION must be set when FINSIGHT_GUARDRAIL_ID is - pin a "
            'published version such as "3" ("DRAFT" is for testing policy changes only).'
        )
    return Guardrail(config.GUARDRAIL_ID, config.GUARDRAIL_VERSION)


def split_paragraphs(text: str, limit: int = MAX_GROUNDING_CHARS) -> list[str]:
    """Split an answer into paragraphs of at most `limit` characters.

    Short pieces (headings, one-liners) are merged with the paragraph after them so each
    check has enough context; over-long paragraphs are split on line breaks.
    """
    pieces = []
    for block in (b.strip() for b in text.split("\n\n")):
        if not block:
            continue
        while len(block) > limit:  # rare: split an over-long block on a line break
            cut = block.rfind("\n", 0, limit)
            cut = cut if cut > 0 else limit
            pieces.append(block[:cut].strip())
            block = block[cut:].strip()
        pieces.append(block)

    merged: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 2 > limit:
            merged.append(current)  # adding this piece would exceed the limit
            current = ""
        current = f"{current}\n\n{piece}" if current else piece
        if len(current) >= MIN_PARAGRAPH_CHARS:
            merged.append(current)
            current = ""
    if current:  # a short leftover joins the last paragraph when it fits
        if merged and len(merged[-1]) + len(current) + 2 <= limit:
            merged[-1] = f"{merged[-1]}\n\n{current}"
        else:
            merged.append(current)
    return merged


def tables_to_sentences(text: str) -> str:
    """Rewrite markdown table rows as sentences: "| Revenue | $254.5B |" under a header
    "| Metric | FY 2024 |" becomes "Revenue, FY 2024: $254.5B." Other lines are unchanged."""
    lines, header = [], None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            lines.append(line)
            header = None
            continue
        cells = [c.strip().strip("*").strip() for c in stripped.strip("|").split("|")]
        if header is None:
            header = cells
        elif not all(set(c) <= set("-: ") for c in cells):  # skip the |---|---| row
            label, *values = cells
            facts = [f"{label}, {h}: {v}." for h, v in zip(header[1:], values, strict=False) if v]
            lines.append(" ".join(facts))
    return "\n".join(lines)


def readable_source(tool_name: str, result: str) -> str:
    """Rewrite a tool's JSON result as plain sentences for the grounding check.

    The grounding model compares text with text. Measured on real answers: raw JSON scored
    0.02 for a correct answer; ISO-only dates (2024-09-01) scored 0.33 when the answer said
    "Sep 1, 2024"; this form, with written-out dates, scored 0.96.
    """
    try:
        return _readable(tool_name, json.loads(result))
    except (ValueError, KeyError, TypeError):  # unexpected shape: use the raw text
        return result


def _readable(tool_name: str, data: dict) -> str:
    company = f"{data['company']} ({data['ticker']})"
    if tool_name == "get_financial_facts":
        metric = data["metric"].replace("_", " ")
        lines = [
            f"{company} {metric} for the fiscal year ended {_written(v['period_end'])}: "
            f"{_money(v['value'], data['unit'])}."
            for v in data["annual_values"]
        ]
        return f"From {company}'s 10-K filings: " + " ".join(lines)
    if tool_name == "get_company_filings":
        lines = [
            f"{company} filed a {f['form']} on {_written(f['filing_date'])}"
            + (f" for the period ended {_written(f['report_date'])}" if f["report_date"] else "")
            + "."
            for f in data["filings"]
        ]
        return " ".join(lines)
    return json.dumps(data)


def _written(iso_date: str) -> str:
    """2024-09-01 -> "September 1, 2024 (2024-09-01)" - answers use written dates."""
    d = date.fromisoformat(iso_date)
    return f"{d:%B} {d.day}, {d.year} ({iso_date})"


def _money(value: float, unit: str) -> str:
    if unit.startswith("USD/"):
        return f"${value:,.2f} per share"
    if unit == "USD":
        full = f"${value:,.0f}"
        if abs(value) >= 1e9:
            return f"${value / 1e9:,.1f} billion ({full})"
        if abs(value) >= 1e6:
            return f"${value / 1e6:,.1f} million ({full})"
        return full
    return f"{value:,} {unit}"


def _grounding_scores(response: dict) -> dict[str, float]:
    return {
        f["type"]: f["score"]
        for a in response.get("assessments", [])
        for f in a.get("contextualGroundingPolicy", {}).get("filters", [])
    }


def _reasons(response: dict) -> list[str]:
    """Which policies intervened, in plain words."""
    reasons = []
    for a in response.get("assessments", []):
        for t in a.get("topicPolicy", {}).get("topics", []):
            if t.get("action") == "BLOCKED":
                reasons.append(f"topic: {t['name']}")
        for f in a.get("contentPolicy", {}).get("filters", []):
            if f.get("action") == "BLOCKED":
                reasons.append(f"content: {f['type'].lower().replace('_', ' ')}")
        for e in a.get("sensitiveInformationPolicy", {}).get("piiEntities", []):
            if e.get("action") in ("BLOCKED", "ANONYMIZED"):
                reasons.append(f"personal data: {e['type'].lower().replace('_', ' ')}")
        for w in a.get("wordPolicy", {}).get("managedWordLists", []):
            if w.get("action") == "BLOCKED":
                reasons.append("word filter: profanity")
    return reasons
