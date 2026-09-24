"""SEC EDGAR client: free, public data on every US-listed company's filings.

EDGAR requires a User-Agent header with your name and email (set SEC_USER_AGENT in .env)
and allows at most 10 requests per second.
"""

import os

import httpx

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"


class CompanyNotFoundError(ValueError):
    pass


def make_http_client() -> httpx.Client:
    user_agent = os.getenv("SEC_USER_AGENT")
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is not set - add your name and email to .env")
    return httpx.Client(headers={"User-Agent": user_agent}, timeout=30.0)


def lookup_company(ticker: str, http: httpx.Client) -> dict:
    """Map a stock ticker (e.g. "AAPL") to the company's name and SEC CIK number."""
    response = http.get(TICKERS_URL)
    response.raise_for_status()
    for company in response.json().values():
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
