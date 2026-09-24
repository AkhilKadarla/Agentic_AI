"""Tests for the tool dispatcher: results and errors are returned to Claude as text."""

import json

import httpx

from finsight.tools import TOOLS, run_tool
from tests.test_sec import clear_ticker_cache, fake_sec_server  # noqa: F401 (autouse fixture)


def make_http() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(fake_sec_server))


def test_every_tool_has_a_complete_definition() -> None:
    for tool in TOOLS:
        assert tool["name"] and tool["description"]
        assert tool["input_schema"]["type"] == "object"


def test_run_get_company_filings_returns_json() -> None:
    result, is_error = run_tool(
        "get_company_filings", {"ticker": "AAPL", "form_type": "10-Q"}, http=make_http()
    )

    assert not is_error
    assert json.loads(result)["filings"][0]["form"] == "10-Q"


def test_limit_is_clamped_to_a_safe_range() -> None:
    result, _ = run_tool("get_company_filings", {"ticker": "AAPL", "limit": 500}, http=make_http())

    assert len(json.loads(result)["filings"]) == 4  # all fake filings, not 500


def test_run_get_financial_facts_returns_json() -> None:
    result, is_error = run_tool(
        "get_financial_facts", {"ticker": "AAPL", "metric": "revenue", "years": 1}, http=make_http()
    )

    assert not is_error
    assert json.loads(result)["annual_values"][0]["value"] == 416


def test_missing_metric_is_reported_as_error() -> None:
    result, is_error = run_tool(
        "get_financial_facts", {"ticker": "AAPL", "metric": "gross_profit"}, http=make_http()
    )

    assert is_error
    assert "gross_profit" in result


def test_unknown_ticker_is_reported_as_error() -> None:
    result, is_error = run_tool("get_company_filings", {"ticker": "NOPE"}, http=make_http())

    assert is_error
    assert "NOPE" in result


def test_unknown_tool_is_reported_as_error() -> None:
    _, is_error = run_tool("delete_everything", {}, http=make_http())

    assert is_error
