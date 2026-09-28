"""Build the number-accuracy eval cases, with expected values taken from SEC XBRL data.

Run once to (re)generate cases.jsonl, then REVIEW the file: expected values are frozen in
the file, so later bugs in FinSight's own data code can't silently change the answer key.

    uv run python evals/number_accuracy/build_cases.py
"""

import json
from pathlib import Path

from finsight import config, sec  # config loads .env (SEC_USER_AGENT)

OUT = Path(__file__).with_name("cases.jsonl")
assert config  # imported for its side effect
http = sec.make_http_client()


def fact(ticker: str, metric: str, index: int = 0) -> dict:
    """The index-th most recent annual value (0 = latest fiscal year)."""
    data = sec.get_annual_financials(ticker, metric, http, years=5)
    row = data["annual_values"][index]
    return {
        "value": row["value"],
        "unit": data["unit"],
        "source": f"{data['company']} {data['xbrl_concept']} FY ended {row['period_end']}",
        "period_end": row["period_end"],
    }


def expect(label: str, f: dict, tolerance: float = 0.01) -> dict:
    return {
        "label": label,
        "value": f["value"],
        "unit": f["unit"],
        "tolerance": tolerance,
        "source": f["source"],
    }


def derived(label: str, value: float, unit: str, source: str, tolerance: float) -> dict:
    return {"label": label, "value": value, "unit": unit, "tolerance": tolerance, "source": source}


cases = []


def add(
    case_id: str,
    tag: str,
    question: str,
    expected: list[dict],
    note: str = "",
    inputs: list[dict] | None = None,
) -> None:
    """`inputs`: for calculated answers, the source figures the calculation needs; the
    "from the data" check looks for these in the tool results."""
    cases.append(
        {
            "id": case_id,
            "tags": [tag],
            "question": question,
            "expected": expected,
            "inputs": inputs if inputs is not None else expected,
            "unavailable": not expected,
            "note": note,
        }
    )


# --- single facts (incl. regression cases for bugs we fixed in Phase 4) ---
for cid, ticker, metric, label, note in [
    ("aapl_revenue", "AAPL", "revenue", "Apple revenue", ""),
    ("nvda_revenue", "NVDA", "revenue", "NVIDIA revenue", ""),
    ("msft_net_income", "MSFT", "net_income", "Microsoft net income", ""),
    ("cost_revenue", "COST", "revenue", "Costco revenue", ""),
    ("v_net_income", "V", "net_income", "Visa net income", "regression: Visa data was missing"),
    ("ma_net_income", "MA", "net_income", "Mastercard net income", "regression: stuck at FY2013"),
    ("tsla_ocf", "TSLA", "operating_cash_flow", "Tesla operating cash flow", ""),
    ("jpm_net_income", "JPM", "net_income", "JPMorgan net income", ""),
    ("gs_revenue", "GS", "revenue", "Goldman Sachs revenue", "regression: bank revenue tag"),
    ("ko_ltd", "KO", "long_term_debt", "Coca-Cola long-term debt", "regression: debt tag"),
]:
    f = fact(ticker, metric)
    names = {
        "revenue": "revenue",
        "net_income": "net income",
        "operating_cash_flow": "operating cash flow",
        "long_term_debt": "long-term debt",
    }
    add(
        cid,
        "single",
        f"What was {label.split()[0] if ticker != 'GS' else 'Goldman Sachs'}'s "
        f"{names[metric]} in its most recent fiscal year?",
        [expect(label, f)],
        note,
    )

# --- units, periods and the other tool ---
aapl_fy24 = fact("AAPL", "revenue", 1)
assert aapl_fy24["period_end"].startswith("2024"), aapl_fy24  # FY2024 ended Sep 2024
add(
    "aapl_revenue_2024",
    "single",
    "What was Apple's revenue in 2024?",
    [expect("Apple revenue FY2024", aapl_fy24)],
    "calendar vs fiscal year: Apple's FY2024 ended Sep 28, 2024",
)
add(
    "aapl_eps",
    "single",
    "What was Apple's diluted EPS in its latest fiscal year?",
    [expect("Apple diluted EPS", fact("AAPL", "eps_diluted"), tolerance=0.01)],
    "per-share unit",
)
add(
    "jpm_total_assets",
    "single",
    "What were JPMorgan's total assets at the end of its latest fiscal year?",
    [expect("JPMorgan total assets", fact("JPM", "total_assets"))],
    "balance-sheet item",
)
nvda_10k = sec.get_recent_filings("NVDA", http, form_type="10-K", limit=1)["filings"][0]
add(
    "nvda_10k_date",
    "single",
    "When did NVIDIA file its most recent 10-K?",
    [
        {
            "label": "NVIDIA 10-K filing date",
            "value": nvda_10k["filing_date"],
            "unit": "date",
            "tolerance": 0,
            "source": f"EDGAR submissions, 10-K for period {nvda_10k['report_date']}",
        }
    ],
    "uses get_company_filings; answer is a date",
)

# --- multi-year ---
add(
    "nvda_revenue_3y",
    "multi_year",
    "What was NVIDIA's revenue in each of its last three fiscal years?",
    [expect(f"NVIDIA revenue FY{i}", fact("NVDA", "revenue", i)) for i in range(3)],
)
add(
    "wmt_revenue_2y",
    "multi_year",
    "What was Walmart's revenue in each of its last two fiscal years?",
    [expect(f"Walmart revenue FY{i}", fact("WMT", "revenue", i)) for i in range(2)],
)

# --- derived (calculations) ---
ni, rev = fact("AAPL", "net_income"), fact("AAPL", "revenue")
add(
    "aapl_net_margin",
    "derived",
    "What was Apple's net profit margin in its latest fiscal year?",
    [
        derived(
            "Apple net margin",
            round(100 * ni["value"] / rev["value"], 2),
            "%",
            f"net income / revenue, FY ended {rev['period_end']}",
            0.25,
        )
    ],
    inputs=[expect("Apple net income", ni), expect("Apple revenue", rev)],
)
ocf, capex = fact("COST", "operating_cash_flow"), fact("COST", "capital_expenditures")
add(
    "cost_fcf",
    "derived",
    "What was Costco's free cash flow (operating cash flow minus capex) in its latest fiscal year?",
    [
        derived(
            "Costco free cash flow",
            ocf["value"] - capex["value"],
            "USD",
            f"OCF - capex, FY ended {ocf['period_end']}",
            0.02,
        )
    ],
    inputs=[expect("Costco operating cash flow", ocf), expect("Costco capex", capex)],
)
r0, r1 = fact("TSLA", "revenue", 0), fact("TSLA", "revenue", 1)
add(
    "tsla_growth",
    "derived",
    "By what percentage did Tesla's revenue change in its latest fiscal year?",
    [
        derived(
            "Tesla revenue growth",
            round(100 * (r0["value"] / r1["value"] - 1), 2),
            "%",
            f"FY ended {r0['period_end']} vs {r1['period_end']}",
            0.25,
        )
    ],
    inputs=[expect("Tesla revenue latest", r0), expect("Tesla revenue prior", r1)],
)

# --- comparisons ---
add(
    "v_vs_ma_revenue",
    "comparison",
    "Compare Visa's and Mastercard's revenue in their most recent fiscal years.",
    [
        expect("Visa revenue", fact("V", "revenue")),
        expect("Mastercard revenue", fact("MA", "revenue")),
    ],
)
add(
    "wmt_vs_tgt_revenue",
    "comparison",
    "Compare Walmart's and Target's revenue in their most recent fiscal years.",
    [
        expect("Walmart revenue", fact("WMT", "revenue")),
        expect("Target revenue", fact("TGT", "revenue")),
    ],
)
add(
    "aapl_vs_msft_net_income",
    "comparison",
    "Which earned more net income in its latest fiscal year, Apple or Microsoft? "
    "Give both figures.",
    [
        expect("Apple net income", fact("AAPL", "net_income")),
        expect("Microsoft net income", fact("MSFT", "net_income")),
    ],
)

# --- data that does not exist ---
# Rule (agreed with the project owner): the answer MUST say the figure isn't available from
# SEC data; it MAY add a figure from memory only if clearly labelled as unverified
# background; presenting a memory figure as verified data FAILS.
add(
    "jpm_gross_profit",
    "unavailable",
    "What was JPMorgan's gross profit in its latest fiscal year?",
    [],
    "banks don't report gross profit",
)
add("fake_ticker", "unavailable", "What was ZZQX's revenue last year?", [], "ticker doesn't exist")
add(
    "xom_revenue",
    "unavailable",
    "What was ExxonMobil's (XOM) revenue in its latest fiscal year?",
    [],
    "XOM now maps to a new holding company with no 10-K data yet; memory would be a guess",
)

OUT.write_text("".join(json.dumps(c) + "\n" for c in cases))
print(f"wrote {len(cases)} cases to {OUT}")
