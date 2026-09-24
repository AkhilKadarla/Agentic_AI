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


def fy(start, end, val, filed, form="10-K"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form}


# Apple-style revenue: each 10-K repeats prior years, and quarterly rows are mixed in.
REVENUE_ROWS = [
    fy("2023-10-01", "2024-09-28", 391, "2024-11-01"),
    fy("2023-10-01", "2024-09-28", 391, "2025-10-31"),  # repeated in the next 10-K
    fy("2024-09-29", "2025-09-27", 416, "2025-10-31"),
    fy("2025-06-29", "2025-09-27", 102, "2025-10-31"),  # Q4-only row inside a 10-K
    fy("2025-09-28", "2025-12-27", 143, "2026-01-30", form="10-Q"),
]
# Old concept name, only used in earlier years.
OLD_REVENUE_ROWS = [fy("2017-10-01", "2018-09-29", 265, "2018-11-05")]
# Balance-sheet items are a point in time, so they have no "start".
ASSET_ROWS = [
    {"end": "2024-09-28", "val": 365, "filed": "2024-11-01", "form": "10-K"},
    {"end": "2025-09-27", "val": 359, "filed": "2025-10-31", "form": "10-K"},
]
CONCEPTS = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": REVENUE_ROWS,
    "Revenues": OLD_REVENUE_ROWS,
    "Assets": ASSET_ROWS,
}


def fake_sec_server(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/files/company_tickers.json":
        return httpx.Response(200, json=TICKERS)
    if path == "/submissions/CIK0000320193.json":
        return httpx.Response(200, json=SUBMISSIONS)
    if path.startswith("/api/xbrl/companyconcept/CIK0000320193/us-gaap/"):
        concept = path.rsplit("/", 1)[1].removesuffix(".json")
        if concept in CONCEPTS:
            return httpx.Response(200, json={"units": {"USD": CONCEPTS[concept]}})
    return httpx.Response(404)


@pytest.fixture(autouse=True)
def clear_ticker_cache():
    sec._tickers_cache.clear()


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


def test_annual_financials_keeps_one_full_year_value_per_period(http) -> None:
    result = sec.get_annual_financials("AAPL", "revenue", http)

    assert result["xbrl_concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert [(v["period_end"], v["value"]) for v in result["annual_values"]] == [
        ("2025-09-27", 416),
        ("2024-09-28", 391),
    ]


def test_annual_financials_handles_balance_sheet_items(http) -> None:
    result = sec.get_annual_financials("AAPL", "total_assets", http, years=1)

    assert result["annual_values"] == [
        {"period_end": "2025-09-27", "value": 359, "filed": "2025-10-31"}
    ]


def test_annual_financials_missing_metric_raises(http) -> None:
    with pytest.raises(sec.CompanyNotFoundError):
        sec.get_annual_financials("AAPL", "gross_profit", http)


def test_annual_financials_unknown_metric_raises(http) -> None:
    with pytest.raises(ValueError, match="Unknown metric"):
        sec.get_annual_financials("AAPL", "vibes", http)


def test_ticker_list_is_downloaded_once(http) -> None:
    calls = []
    counting = httpx.Client(
        transport=httpx.MockTransport(lambda r: calls.append(r.url.path) or fake_sec_server(r))
    )

    sec.lookup_company("AAPL", counting)
    sec.lookup_company("NVDA", counting)

    assert calls.count("/files/company_tickers.json") == 1
