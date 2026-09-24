"""Tools Claude can ask us to run.

Each tool has two halves:
  1. A *definition* (name, description, JSON schema) that we send to Claude, so it knows
     the tool exists and how to call it. Claude never runs code itself.
  2. A Python *implementation* that we run when Claude asks for it.
"""

import json

import httpx

from finsight import sec

FORM_TYPES = ["10-K", "10-Q", "8-K", "DEF 14A", "4", "S-1", "20-F"]

TOOLS = [
    {
        "name": "get_company_filings",
        "description": (
            "Look up a US-listed company's most recent SEC filings by stock ticker. "
            "Returns the company name and, for each filing: form type, filing date, "
            "report period, and a link to the document. Use this to find out what a company "
            "has filed recently (annual reports = 10-K, quarterly = 10-Q, material events = 8-K, "
            "insider trades = 4). It does not return the filing's contents."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker, e.g. AAPL"},
                "form_type": {
                    "type": "string",
                    "enum": FORM_TYPES,
                    "description": "Only return filings of this form type. Omit for all types.",
                },
                "limit": {
                    "type": "integer",
                    "description": "How many filings to return (1-20, default 5)",
                },
            },
            "required": ["ticker"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_financial_facts",
        "description": (
            "Get a company's reported annual figures for one financial metric, taken from the "
            "structured (XBRL) data in its 10-K filings. Returns one value per fiscal year, "
            "newest first, with the period end date and unit (USD, or USD/shares for EPS). "
            "Call it once per metric; call it several times to compare metrics or companies. "
            "Values are as reported (not adjusted for inflation or splits)."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker, e.g. AAPL"},
                "metric": {"type": "string", "enum": list(sec.METRICS)},
                "years": {
                    "type": "integer",
                    "description": "How many fiscal years to return (1-10, default 5)",
                },
            },
            "required": ["ticker", "metric"],
            "additionalProperties": False,
        },
    },
]


def run_tool(name: str, tool_input: dict, http: httpx.Client | None = None) -> tuple[str, bool]:
    """Run the tool Claude asked for. Returns (result_text, is_error).

    Errors are returned to Claude as text rather than raised, so the model can read what
    went wrong (e.g. a bad ticker) and recover, instead of the whole program crashing.
    """
    http = http or sec.make_http_client()
    try:
        if name == "get_company_filings":
            limit = max(1, min(int(tool_input.get("limit", 5)), 20))
            result = sec.get_recent_filings(
                tool_input["ticker"], http, form_type=tool_input.get("form_type"), limit=limit
            )
            return json.dumps(result), False
        if name == "get_financial_facts":
            years = max(1, min(int(tool_input.get("years", 5)), 10))
            result = sec.get_annual_financials(
                tool_input["ticker"], tool_input["metric"], http, years=years
            )
            return json.dumps(result), False
        return f"Unknown tool: {name}", True
    except (sec.CompanyNotFoundError, ValueError) as e:
        return str(e), True
    except httpx.HTTPError as e:
        return f"SEC EDGAR request failed: {e}", True
