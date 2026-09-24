"""Tests for the SEC EDGAR client, using a fake SEC server (no network)."""

import httpx
import pytest

from finsight import sec

TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
}

SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["4", "10-Q", "8-K", "10-K"],
            "filingDate": ["2026-09-17", "2026-08-01", "2026-07-30", "2025-10-31"],
            "reportDate": ["2026-09-15", "2026-06-27", "2026-07-30", "2025-09-27"],
            "accessionNumber": [
                "0001-26-000004",
                "0001-26-000003",
                "0001-26-000002",
                "0001-25-000001",
            ],
            "primaryDocument": ["form4.xml", "q3.htm", "8k.htm", "10k.htm"],
            "primaryDocDescription": ["FORM 4", "10-Q", "8-K", "10-K"],
        }
    }
}


def fake_sec_server(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/files/company_tickers.json":
        return httpx.Response(200, json=TICKERS)
    if request.url.path == "/submissions/CIK0000320193.json":
        return httpx.Response(200, json=SUBMISSIONS)
    return httpx.Response(404)


@pytest.fixture
def http() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(fake_sec_server))


def test_lookup_company_is_case_insensitive(http) -> None:
    company = sec.lookup_company("aapl", http)

    assert company == {"cik": 320193, "name": "Apple Inc.", "ticker": "AAPL"}


def test_lookup_unknown_ticker_raises(http) -> None:
    with pytest.raises(sec.CompanyNotFoundError):
        sec.lookup_company("NOPE", http)


def test_get_recent_filings_respects_limit(http) -> None:
    result = sec.get_recent_filings("AAPL", http, limit=2)

    assert result["company"] == "Apple Inc."
    assert [f["form"] for f in result["filings"]] == ["4", "10-Q"]


def test_get_recent_filings_filters_by_form_and_builds_url(http) -> None:
    [filing] = sec.get_recent_filings("AAPL", http, form_type="10-K")["filings"]

    assert filing["filing_date"] == "2025-10-31"
    assert filing["url"] == "https://www.sec.gov/Archives/edgar/data/320193/000125000001/10k.htm"
