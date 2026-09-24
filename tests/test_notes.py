"""Tests for research note formatting and saving (pure Python, no API)."""

import json

import pytest

from finsight.notes import Metric, ResearchNote, Source, format_value, render_markdown, save_note


def sample_note() -> ResearchNote:
    return ResearchNote(
        title="Apple: Revenue Check / FY2025",
        tickers=["AAPL"],
        summary="Revenue grew modestly.",
        key_metrics=[
            Metric(
                name="Revenue",
                company="AAPL",
                period="FY2025",
                value=416_161_000_000,
                unit="USD",
                derived=False,
            ),
            Metric(
                name="Growth", company="AAPL", period="FY2025", value=6.4, unit="%", derived=True
            ),
        ],
        findings=["Growth accelerated."],
        risks=["Only one metric fetched."],
        sources=[Source(description="Apple 10-K XBRL", url="https://www.sec.gov/x")],
        data_as_of="2025-09-27",
        confidence="medium",
    )


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (416_161_000_000, "USD", "$416.2B"),
        (12_500_000, "USD", "$12.5M"),
        (6.08, "USD/shares", "$6.08 per share"),
        (950.5, "USD", "$950.50"),
        (55.64, "%", "55.6%"),
    ],
)
def test_format_value(value, unit, expected) -> None:
    assert format_value(value, unit) == expected


def test_render_markdown_includes_every_section() -> None:
    md = render_markdown(sample_note())

    assert md.startswith("# Apple: Revenue Check / FY2025")
    assert "| AAPL | Revenue | FY2025 | $416.2B |" in md
    assert "| AAPL | Growth (derived) | FY2025 | 6.4% |" in md
    for section in ("## Findings", "## Risks & caveats", "## Sources", "not investment advice"):
        assert section in md


def test_save_note_writes_json_and_markdown(tmp_path) -> None:
    path = save_note(sample_note(), directory=tmp_path)

    assert path.name.endswith("apple-revenue-check-fy2025.json")
    assert json.loads(path.read_text())["tickers"] == ["AAPL"]
    assert path.with_suffix(".md").exists()


def test_note_rejects_invalid_confidence() -> None:
    data = sample_note().model_dump() | {"confidence": "very sure"}

    with pytest.raises(ValueError):
        ResearchNote(**data)
