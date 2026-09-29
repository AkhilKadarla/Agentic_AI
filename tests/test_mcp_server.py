"""Tests for the MCP server, using the MCP SDK's in-process client (no subprocess, no network).

The server's tools run tools.run_tool; here it's replaced with a fake so no SEC calls happen.
"""

import asyncio
import json

import pytest
from mcp import Client

from finsight import config, mcp_server
from finsight.tools import SEARCH_FILINGS_TOOL, TOOLS


def call(server, method: str, *args, **kwargs):
    """Connect an MCP client to the server in-process, make one call, return the result."""

    async def go():
        async with Client(server) as client:
            return await getattr(client, method)(*args, **kwargs)

    return asyncio.run(go())


@pytest.fixture
def fake_tools(monkeypatch):
    calls = []

    def fake_run_tool(name, tool_input):
        calls.append((name, tool_input))
        if tool_input.get("ticker") == "ZZQX":
            return "No company found for ticker ZZQX", True
        return json.dumps({"tool": name, "ticker": tool_input["ticker"]}), False

    monkeypatch.setattr(mcp_server, "run_tool", fake_run_tool)
    return calls


def enum_values(schema: dict) -> set:
    """Allowed values in a JSON schema, including inside anyOf (optional parameters)."""
    values = set(schema.get("enum", []))
    for option in schema.get("anyOf", []):
        values |= enum_values(option)
    return values


def tools_by_name(server) -> dict:
    return {tool.name: tool for tool in call(server, "list_tools").tools}


def test_offers_the_sec_tools_read_only():
    tools = tools_by_name(mcp_server.build_server())
    assert set(tools) == {"get_company_filings", "get_financial_facts"}  # no KB configured
    for tool in tools.values():
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False


def test_offers_10k_search_only_with_a_knowledge_base(monkeypatch):
    monkeypatch.setattr(config, "KB_ID", "kb123")
    assert "search_filings" in tools_by_name(mcp_server.build_server())


@pytest.mark.parametrize("definition", [*TOOLS, SEARCH_FILINGS_TOOL], ids=lambda t: t["name"])
def test_mcp_tools_match_the_agent_tool_definitions(definition, monkeypatch):
    # The agent (tools.py) and MCP clients must see the same tools: same description, same
    # parameters, same required ones, same allowed values. This fails if they drift apart.
    monkeypatch.setattr(config, "KB_ID", "kb123")
    tool = tools_by_name(mcp_server.build_server())[definition["name"]]
    agent_schema = definition["input_schema"]
    mcp_schema = tool.input_schema

    assert tool.description == definition["description"]
    assert set(mcp_schema["properties"]) == set(agent_schema["properties"])
    assert set(mcp_schema.get("required", [])) == set(agent_schema["required"])
    for name, prop in agent_schema["properties"].items():
        if "enum" in prop:
            assert enum_values(mcp_schema["properties"][name]) == set(prop["enum"])


def test_calls_run_the_agents_tool_code(fake_tools):
    server = mcp_server.build_server()
    result = call(
        server, "call_tool", "get_financial_facts", {"ticker": "AAPL", "metric": "revenue"}
    )

    assert not result.is_error
    assert json.loads(result.content[0].text) == {"tool": "get_financial_facts", "ticker": "AAPL"}
    assert fake_tools == [
        ("get_financial_facts", {"ticker": "AAPL", "metric": "revenue", "years": 5})
    ]


def test_omitted_optional_arguments_are_not_sent_as_none(fake_tools):
    call(mcp_server.build_server(), "call_tool", "get_company_filings", {"ticker": "MSFT"})
    assert fake_tools == [("get_company_filings", {"ticker": "MSFT", "limit": 5})]


def test_tool_errors_reach_the_client_as_readable_errors(fake_tools):
    result = call(
        mcp_server.build_server(),
        "call_tool",
        "get_financial_facts",
        {"ticker": "ZZQX", "metric": "revenue"},
    )
    assert result.is_error
    assert "No company found for ticker ZZQX" in result.content[0].text


def test_invalid_arguments_are_rejected_before_any_sec_call(fake_tools):
    server = mcp_server.build_server()
    bad_metric = call(
        server, "call_tool", "get_financial_facts", {"ticker": "AAPL", "metric": "vibes"}
    )
    too_many = call(server, "call_tool", "get_company_filings", {"ticker": "AAPL", "limit": 500})
    assert bad_metric.is_error and too_many.is_error
    assert fake_tools == []


def test_metrics_resource_lists_supported_metrics():
    result = call(mcp_server.build_server(), "read_resource", "finsight://metrics")
    metrics = json.loads(result.contents[0].text)
    assert "revenue" in metrics and "net_income" in metrics


def test_research_prompt_names_the_company():
    result = call(mcp_server.build_server(), "get_prompt", "research_company", {"ticker": "cost"})
    text = result.messages[0].content.text
    assert "Research COST" in text
    assert "not investment advice" in text
