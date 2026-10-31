"""Build the number-accuracy eval cases, with expected values taken from SEC XBRL data.

Run once to (re)generate cases.jsonl, then REVIEW the file: expected values are frozen in
the file, so later bugs in FinSight's own data code can't silently change the answer key.

    uv run python evals/number_accuracy/build_cases.py
"""

import json
from datetime import date
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


def fy(period_end: str) -> str:
    """Name a fiscal year by its end date, e.g. "fiscal year ended August 31, 2025".

    Questions name the year instead of saying "most recent": the expected values are
    frozen, so when a company files a newer 10-K a "latest year" question would have a
    new right answer and the case would fail even though the agent was correct."""
    d = date.fromisoformat(period_end)
    return f"fiscal year ended {d:%B} {d.day}, {d.year}"


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
        f"{names[metric]} in its {fy(f['period_end'])}?",
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
aapl_eps = fact("AAPL", "eps_diluted")
add(
    "aapl_eps",
    "single",
    f"What was Apple's diluted EPS in its {fy(aapl_eps['period_end'])}?",
    [expect("Apple diluted EPS", aapl_eps, tolerance=0.01)],
    "per-share unit",
)
jpm_assets = fact("JPM", "total_assets")
add(
    "jpm_total_assets",
    "single",
    f"What were JPMorgan's total assets at the end of its {fy(jpm_assets['period_end'])}?",
    [expect("JPMorgan total assets", jpm_assets)],
    "balance-sheet item",
)
nvda_10k = sec.get_recent_filings("NVDA", http, form_type="10-K", limit=1)["filings"][0]
add(
    "nvda_10k_date",
    "single",
    f"When did NVIDIA file its 10-K for its {fy(nvda_10k['report_date'])}?",
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
nvda_3y = [fact("NVDA", "revenue", i) for i in range(3)]
add(
    "nvda_revenue_3y",
    "multi_year",
    f"What was NVIDIA's revenue in each of its last three fiscal years, up to and "
    f"including its {fy(nvda_3y[0]['period_end'])}?",
    [expect(f"NVIDIA revenue FY{i}", f) for i, f in enumerate(nvda_3y)],
)
wmt_2y = [fact("WMT", "revenue", i) for i in range(2)]
add(
    "wmt_revenue_2y",
    "multi_year",
    f"What was Walmart's revenue in each of its last two fiscal years, up to and "
    f"including its {fy(wmt_2y[0]['period_end'])}?",
    [expect(f"Walmart revenue FY{i}", f) for i, f in enumerate(wmt_2y)],
)

# --- derived (calculations) ---
ni, rev = fact("AAPL", "net_income"), fact("AAPL", "revenue")
add(
    "aapl_net_margin",
    "derived",
    f"What was Apple's net profit margin in its {fy(rev['period_end'])}?",
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
    "What was Costco's free cash flow (operating cash flow minus capex) in its "
    f"{fy(ocf['period_end'])}?",
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
    f"By what percentage did Tesla's revenue change in its {fy(r0['period_end'])}, "
    "compared with the year before?",
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
v_rev, ma_rev = fact("V", "revenue"), fact("MA", "revenue")
add(
    "v_vs_ma_revenue",
    "comparison",
    f"Compare Visa's revenue in its {fy(v_rev['period_end'])} with Mastercard's revenue "
    f"in its {fy(ma_rev['period_end'])}.",
    [expect("Visa revenue", v_rev), expect("Mastercard revenue", ma_rev)],
)
wmt_rev, tgt_rev = fact("WMT", "revenue"), fact("TGT", "revenue")
add(
    "wmt_vs_tgt_revenue",
    "comparison",
    f"Compare Walmart's revenue in its {fy(wmt_rev['period_end'])} with Target's revenue "
    f"in its {fy(tgt_rev['period_end'])}.",
    [expect("Walmart revenue", wmt_rev), expect("Target revenue", tgt_rev)],
)
aapl_ni, msft_ni = fact("AAPL", "net_income"), fact("MSFT", "net_income")
add(
    "aapl_vs_msft_net_income",
    "comparison",
    f"Which earned more net income: Apple in its {fy(aapl_ni['period_end'])}, or "
    f"Microsoft in its {fy(msft_ni['period_end'])}? Give both figures.",
    [expect("Apple net income", aapl_ni), expect("Microsoft net income", msft_ni)],
)

# --- data that does not exist ---
# These keep "latest": there is no frozen value to drift, and the traps are about the agent
# admitting a gap in the data, whichever year it looks at.
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
