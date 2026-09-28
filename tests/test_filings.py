"""Tests for 10-K section extraction. Each case mirrors a quirk found in a real filing."""

import httpx
import pytest

from finsight import filings, sec
from finsight.filings import SECTIONS, extract_section, latest_10k
from tests.test_sec import SUBMISSIONS, TICKERS

BODY = "The risks described below could harm our business. " * 120  # ~6,200 chars
RISK = SECTIONS["risk_factors"][1:]
MDNA = SECTIONS["mdna"][1:]


def test_skips_table_of_contents_entry() -> None:
    text = (
        "Item 1A. Risk Factors 14 Item 1B. Unresolved Staff Comments 29 "
        "Item 1. Business We make phones. "
        f"Item 1A. Risk Factors {BODY} Item 1B. Unresolved Staff Comments None."
    )

    section = extract_section(text, *RISK)

    assert section.startswith("Item 1A. Risk Factors The risks")
    assert "We make phones" not in section


def test_skips_cross_references_in_quotes() -> None:
    # Costco: 'see "Item 1A-Risk Factors", and other factors' appears before the section.
    text = (
        'Forward-looking statements; see "Item 1A-Risk Factors", and other factors. '
        f"Item 1 Business stuff. Item 1A—Risk Factors {BODY} Item 1B—Unresolved Staff Comments"
    )

    assert extract_section(text, *RISK).startswith("Item 1A—Risk Factors The risks")


def test_tolerates_words_split_by_styling() -> None:
    # Microsoft's 10-K renders the heading as "ITEM 1A. RIS K FACTORS".
    text = f"ITEM 1A. RIS K FACTORS {BODY} ITEM 1B. UNRESOLVED STAFF COMMENTS"

    assert extract_section(text, *RISK).startswith("ITEM 1A. RIS K FACTORS")


def test_mdna_ends_at_item_7a() -> None:
    text = (
        f"Item 7. Management’s Discussion and Analysis of Financial Condition {BODY} "
        "Item 7A. Quantitative and Qualitative Disclosures About Market Risk"
    )

    section = extract_section(text, *MDNA)

    assert section.startswith("Item 7. Management’s Discussion")
    assert "Market Risk" not in section


def test_missing_section_returns_empty() -> None:
    assert extract_section("No headings here at all.", *RISK) == ""


def fake_edgar(document_html: str):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/files/company_tickers.json":
            return httpx.Response(200, json=TICKERS)
        if request.url.path == "/submissions/CIK0000320193.json":
            return httpx.Response(200, json=SUBMISSIONS)
        if request.url.path.endswith("/10k.htm"):
            return httpx.Response(200, text=document_html)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def clear_caches():
    sec._tickers_cache.clear()


def test_latest_10k_extracts_sections_and_reports_cross_referenced_ones() -> None:
    html = (
        f"<html><body><p>Item 1A. Risk Factors</p><p>{BODY}</p>"
        "<p>Item 1B. Unresolved Staff Comments</p>"
        # JPMorgan-style MD&A: only a pointer to the annual report.
        "<p>Item 7. Management's Discussion and Analysis: see pages 50-140 of the Annual "
        "Report.</p><p>Item 7A. Market risk</p></body></html>"
    )

    filing = latest_10k("AAPL", fake_edgar(html))

    assert filing.ticker == "AAPL" and filing.report_date == "2025-09-27"
    assert [s.name for s in filing.sections] == ["risk_factors"]
    assert filing.missing == ["Management's Discussion and Analysis (MD&A)"]
    assert filing.url.endswith("/10k.htm")


def test_html_to_text_collapses_whitespace() -> None:
    assert filings.html_to_text("<p>Risk\n\n  Factors</p><div>More</div>") == "Risk Factors More"
