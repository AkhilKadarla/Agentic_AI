"""FinSight's SEC tools as an MCP server, for any MCP client (Claude Code, Claude Desktop, ...).

MCP (Model Context Protocol) is a standard plug between AI apps and tools. Our agent calls
its tools directly; an MCP server offers the same tools to *other* AI apps, which discover
them (names, descriptions, input schemas) and call them over the protocol.

    uv run finsight mcp      # speaks MCP over stdin/stdout; the client app starts it

What this server offers:
  tools      get_company_filings, get_financial_facts, and search_filings (10-K text) when
             FINSIGHT_KB_ID is set - the same code the agent runs (tools.run_tool)
  resource   finsight://metrics - the metrics get_financial_facts understands
  prompt     research_company - FinSight's research approach for one company

Compliance note: with MCP, the *client's* model writes the answer, so FinSight's guardrail
(which reviews FinSight's own answers) is not in the loop. The tools return public SEC
data only, and are read-only.
"""

import json
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from finsight import __version__, config, sec
from finsight.tools import FORM_TYPES, SEARCH_FILINGS_TOOL, TOOLS, run_tool

# One source of truth: the descriptions Claude sees in the agent are the ones MCP clients see.
DESCRIPTIONS = {tool["name"]: tool["description"] for tool in [*TOOLS, SEARCH_FILINGS_TOOL]}

# Tells clients these tools only read data (safe to call without asking) and reach the
# outside world (SEC EDGAR, the Knowledge Base).
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)

INSTRUCTIONS = (
    "FinSight gives you US public-company data from SEC EDGAR: recent filings, reported "
    "annual financials (XBRL), and - when available - passages from 10-K text. Use the tools "
    "instead of memory for company figures, state the fiscal periods you use, and present "
    "the results as educational analysis, not investment advice."
)

Ticker = Annotated[str, Field(description="Stock ticker, e.g. AAPL")]
FormType = Literal[tuple(FORM_TYPES)]
Metric = Literal[tuple(sec.METRICS)]


def _run(name: str, **tool_input) -> str:
    """Run the agent's tool; its error text becomes an MCP tool error the client can read."""
    text, is_error = run_tool(name, {k: v for k, v in tool_input.items() if v is not None})
    if is_error:
        raise ToolError(text)
    return text


def build_server() -> MCPServer:
    server = MCPServer("finsight", title="FinSight", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(description=DESCRIPTIONS["get_company_filings"], annotations=READ_ONLY)
    def get_company_filings(
        ticker: Ticker,
        form_type: Annotated[
            FormType | None, Field(description="Only filings of this type; omit for all")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=20, description="How many filings (1-20)")] = 5,
    ) -> str:
        return _run("get_company_filings", ticker=ticker, form_type=form_type, limit=limit)

    @server.tool(description=DESCRIPTIONS["get_financial_facts"], annotations=READ_ONLY)
    def get_financial_facts(
        ticker: Ticker,
        metric: Metric,
        years: Annotated[int, Field(ge=1, le=10, description="Fiscal years (1-10)")] = 5,
    ) -> str:
        return _run("get_financial_facts", ticker=ticker, metric=metric, years=years)

    if config.KB_ID:  # same rule as the agent: offer 10-K search only when a KB exists

        @server.tool(description=DESCRIPTIONS["search_filings"], annotations=READ_ONLY)
        def search_filings(
            ticker: Ticker,
            query: Annotated[str, Field(description="What to look for, in plain words")],
            section: Annotated[
                Literal["risk_factors", "mdna"] | None,
                Field(description="Only search this section; omit to search both"),
            ] = None,
        ) -> str:
            return _run("search_filings", ticker=ticker, query=query, section=section)

    @server.resource(
        "finsight://metrics",
        name="metrics",
        description="Financial metrics get_financial_facts supports, with the XBRL concepts "
        "tried for each (in order)",
        mime_type="application/json",
    )
    def metrics() -> str:
        return json.dumps(sec.METRICS, indent=2)

    @server.prompt(
        title="Research a company",
        description="FinSight's approach: multi-year figures from SEC data, periods stated, "
        "calculations shown, risks from the 10-K",
    )
    def research_company(ticker: str) -> str:
        return (
            f"Research {ticker.upper()} with the FinSight tools.\n"
            "1. Get revenue, net income and operating cash flow for the last 3 fiscal years "
            "(get_financial_facts), and the latest 10-K date (get_company_filings).\n"
            "2. Calculate growth rates and net margin; show each calculation.\n"
            "3. If search_filings is available, summarize the top risks from the 10-K and "
            "quote the filing.\n"
            "State the fiscal periods you use, label anything not from the tools as general "
            "background, and present it as educational analysis, not investment advice."
        )

    return server


def main() -> None:
    build_server().run("stdio")
