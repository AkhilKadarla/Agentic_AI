"""Tests for the Knowledge Base client, with fake AWS clients (no network)."""

import json
from unittest.mock import MagicMock

import pytest

from finsight import config
from finsight import knowledge_base as kb
from finsight.filings import Filing10K, Section


@pytest.fixture(autouse=True)
def kb_settings(monkeypatch):
    monkeypatch.setattr(config, "KB_ID", "KB123")
    monkeypatch.setattr(config, "KB_DATA_SOURCE_ID", "DS456")
    monkeypatch.setattr(config, "FILINGS_BUCKET", "finsight-filings-test")


def sample_filing() -> Filing10K:
    return Filing10K(
        ticker="TSLA",
        company="Tesla, Inc.",
        report_date="2025-12-31",
        filing_date="2026-01-29",
        url="https://www.sec.gov/Archives/edgar/data/1318605/x/tsla-20251231.htm",
        sections=[Section("risk_factors", "Risk Factors", "We rely on suppliers...")],
        missing=["Management's Discussion and Analysis (MD&A)"],
    )


def test_upload_writes_text_and_labels_side_by_side() -> None:
    s3 = MagicMock()

    keys = kb.upload_filing(sample_filing(), s3=s3)

    assert keys == ["filings/TSLA/2025-12-31/risk_factors.txt"]
    text_call, label_call = [c.kwargs for c in s3.put_object.call_args_list]
    assert text_call["Bucket"] == "finsight-filings-test"
    assert text_call["Body"].decode().startswith("Tesla, Inc. (TSLA) - Form 10-K")
    assert label_call["Key"] == "filings/TSLA/2025-12-31/risk_factors.txt.metadata.json"
    labels = json.loads(label_call["Body"])["metadataAttributes"]
    assert labels["ticker"] == "TSLA" and labels["section"] == "risk_factors"


def test_sync_polls_until_complete() -> None:
    agent = MagicMock()
    agent.start_ingestion_job.return_value = {
        "ingestionJob": {"ingestionJobId": "J1", "status": "STARTING"}
    }
    agent.get_ingestion_job.side_effect = [
        {"ingestionJob": {"ingestionJobId": "J1", "status": "IN_PROGRESS"}},
        {
            "ingestionJob": {
                "ingestionJobId": "J1",
                "status": "COMPLETE",
                "statistics": {"numberOfNewDocumentsIndexed": 2},
            }
        },
    ]

    stats = kb.sync(agent=agent, poll_seconds=0)

    assert stats == {"numberOfNewDocumentsIndexed": 2}
    assert agent.start_ingestion_job.call_args.kwargs == {
        "knowledgeBaseId": "KB123",
        "dataSourceId": "DS456",
    }


def test_sync_failure_raises_with_reasons() -> None:
    agent = MagicMock()
    agent.start_ingestion_job.return_value = {
        "ingestionJob": {
            "ingestionJobId": "J1",
            "status": "FAILED",
            "failureReasons": ["AccessDenied on s3:GetObject"],
        }
    }

    with pytest.raises(kb.KnowledgeBaseError, match="AccessDenied"):
        kb.sync(agent=agent, poll_seconds=0)


def test_search_filters_by_ticker_and_maps_results() -> None:
    runtime = MagicMock()
    runtime.retrieve.return_value = {
        "retrievalResults": [
            {
                "content": {"text": "single-source suppliers"},
                "score": 0.73,
                "metadata": {
                    "ticker": "TSLA",
                    "section": "risk_factors",
                    "fiscal_year_end": "2025-12-31",
                    "source_url": "https://sec.gov/x",
                },
            }
        ]
    }

    [passage] = kb.search("tsla", "supply risks", limit=3, runtime=runtime)

    request = runtime.retrieve.call_args.kwargs
    search_config = request["retrievalConfiguration"]["vectorSearchConfiguration"]
    assert search_config["filter"] == {"equals": {"key": "ticker", "value": "TSLA"}}
    assert search_config["numberOfResults"] == 3
    assert passage == kb.Passage(
        "single-source suppliers", 0.73, "TSLA", "risk_factors", "2025-12-31", "https://sec.gov/x"
    )


def test_indexed_filings_lists_companies_and_years() -> None:
    s3 = MagicMock()
    s3.get_paginator.return_value.paginate.return_value = [
        {
            "Contents": [
                {"Key": "filings/TSLA/2025-12-31/risk_factors.txt"},
                {"Key": "filings/TSLA/2025-12-31/risk_factors.txt.metadata.json"},
                {"Key": "filings/AAPL/2025-09-27/mdna.txt"},
            ]
        }
    ]

    assert kb.indexed_filings(s3=s3) == {"AAPL": ["2025-09-27"], "TSLA": ["2025-12-31"]}


def test_missing_settings_are_named(monkeypatch) -> None:
    monkeypatch.setattr(config, "KB_ID", None)

    with pytest.raises(kb.KnowledgeBaseError, match="FINSIGHT_KB_ID"):
        kb.require_config()
