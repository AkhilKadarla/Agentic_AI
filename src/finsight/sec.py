"""SEC EDGAR client: free, public data on every US-listed company's filings.

EDGAR requires a User-Agent header with your name and email (set SEC_USER_AGENT in .env)
and allows at most 10 requests per second.
"""

import os
from datetime import date, timedelta

import httpx

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
# All of a company's reported XBRL figures in one file (~250-550 KB compressed).
# (The per-concept endpoint is not reliable: it returned no rows for Visa's net income.)
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
STALE_AFTER = timedelta(days=548)  # ~18 months: an annual figure older than this is suspect

# Companies tag the same number with different XBRL "concepts" (e.g. Apple reports revenue as
# RevenueFromContract..., NVIDIA as Revenues), so each metric lists the candidates to try.
METRICS = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    # ProfitLoss includes minority (noncontrolling) interests; e.g. Mastercard uses it.
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capital_expenditures": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "shareholders_equity": ["StockholdersEquity"],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
}

# The ticker list is ~1 MB and rarely changes: download it once per run, not per tool call.
_tickers_cache: dict = {}
# Company facts by CIK, so several metrics for one company cost one download.
_facts_cache: dict[int, dict] = {}


class CompanyNotFoundError(ValueError):
    pass


def make_http_client() -> httpx.Client:
    user_agent = os.getenv("SEC_USER_AGENT")
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is not set - add your name and email to .env")
    return httpx.Client(headers={"User-Agent": user_agent}, timeout=30.0)


def lookup_company(ticker: str, http: httpx.Client) -> dict:
    """Map a stock ticker (e.g. "AAPL") to the company's name and SEC CIK number."""
    if not _tickers_cache:
        response = http.get(TICKERS_URL)
        response.raise_for_status()
        _tickers_cache.update(response.json())
    for company in _tickers_cache.values():
        if company["ticker"].upper() == ticker.upper():
            return {"cik": company["cik_str"], "name": company["title"], "ticker": ticker.upper()}
    raise CompanyNotFoundError(f"No SEC-registered company found for ticker '{ticker}'")


def get_recent_filings(
    ticker: str, http: httpx.Client, form_type: str | None = None, limit: int = 5
) -> dict:
    """Return a company's most recent filings, optionally only one form type (e.g. "10-K")."""
    company = lookup_company(ticker, http)
    response = http.get(SUBMISSIONS_URL.format(cik=company["cik"]))
    response.raise_for_status()
    recent = response.json()["filings"]["recent"]

    filings = []
    # EDGAR returns parallel arrays (one per field), newest first.
    for i, form in enumerate(recent["form"]):
        if form_type and form != form_type:
            continue
        accession = recent["accessionNumber"][i]
        filings.append(
            {
                "form": form,
                "filing_date": recent["filingDate"][i],
                "report_date": recent["reportDate"][i],
                "description": recent["primaryDocDescription"][i],
                "url": ARCHIVE_URL.format(
                    cik=company["cik"],
                    accession=accession.replace("-", ""),
                    document=recent["primaryDocument"][i],
                ),
            }
        )
        if len(filings) == limit:
            break

    return {"company": company["name"], "ticker": company["ticker"], "filings": filings}


def get_annual_financials(ticker: str, metric: str, http: httpx.Client, years: int = 5) -> dict:
    """Return a company's annual values for one metric, from its 10-K filings, newest first."""
    if metric not in METRICS:
        raise ValueError(f"Unknown metric '{metric}'. Choose from: {', '.join(METRICS)}")
    company = lookup_company(ticker, http)
    us_gaap = _company_facts(company["cik"], http).get("us-gaap", {})

    best: dict | None = None
    for concept in METRICS[metric]:
        if concept not in us_gaap:  # this company doesn't use this concept
            continue
        unit, rows = next(iter(us_gaap[concept]["units"].items()))
        values = _annual_values(rows)
        # Prefer whichever concept has the most recent data (companies switch tags over time).
        if values and (best is None or values[0]["period_end"] > best["values"][0]["period_end"]):
            best = {"concept": concept, "unit": unit, "values": values}

    if best is None:
        raise CompanyNotFoundError(f"No annual '{metric}' data reported by {company['name']}")
    result = {
        "company": company["name"],
        "ticker": company["ticker"],
        "metric": metric,
        "xbrl_concept": best["concept"],
        "unit": best["unit"],
        "annual_values": best["values"][:years],
    }
    latest = date.fromisoformat(best["values"][0]["period_end"])
    if date.today() - latest > STALE_AFTER:
        # Tell the model explicitly, so old data is never presented as current.
        result["warning"] = (
            f"Latest value is for the period ending {latest}. The company may now report this "
            "metric under a different XBRL concept; do not treat this as current data."
        )
    return result


def _company_facts(cik: int, http: httpx.Client) -> dict:
    if cik not in _facts_cache:
        response = http.get(FACTS_URL.format(cik=cik))
        response.raise_for_status()
        _facts_cache[cik] = response.json()["facts"]
    return _facts_cache[cik]


def _annual_values(rows: list[dict]) -> list[dict]:
    """Keep one full-year value per fiscal period, taken from the most recent 10-K.

    Each 10-K also repeats prior years for comparison, and flow metrics (revenue, cash flow)
    include quarterly rows too, so we filter to ~12-month periods and de-duplicate by period
    end date. The latest filing wins, which picks up any restatements.
    """
    by_period: dict[str, dict] = {}
    for row in rows:
        if row.get("form") not in ("10-K", "10-K/A"):
            continue
        if "start" in row and not _is_full_year(row["start"], row["end"]):
            continue
        current = by_period.get(row["end"])
        if current is None or row["filed"] > current["filed"]:
            by_period[row["end"]] = row
    return [
        {"period_end": end, "value": row["val"], "filed": row["filed"]}
        for end, row in sorted(by_period.items(), reverse=True)
    ]


def _is_full_year(start: str, end: str) -> bool:
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    return 350 <= days <= 380
