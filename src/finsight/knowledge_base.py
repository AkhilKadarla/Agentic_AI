"""FinSight's Amazon Bedrock Knowledge Base: 10-K text the agent can search by meaning.

  index  : 10-K sections -> S3 (text + labels) -> "sync" -> Bedrock chunks and embeds them
           into the S3 Vectors index (Titan Text Embeddings V2)
  search : question -> Bedrock finds the closest chunks, filtered by ticker

Each section is uploaded as `filings/<TICKER>/<fiscal-year-end>/<section>.txt` next to a
`.metadata.json` "label" file. Labels are what let one store hold many companies: a
search for Tesla only looks at chunks labelled ticker=TSLA.
"""

import json
import time
from dataclasses import dataclass

import boto3

from finsight import config
from finsight.filings import Filing10K


class KnowledgeBaseError(RuntimeError):
    pass


@dataclass
class Passage:
    """One chunk returned by a search."""

    text: str
    score: float  # 0-1: closeness of meaning to the question
    ticker: str
    section: str
    fiscal_year_end: str
    source_url: str


def _session():
    return boto3.Session(profile_name=config.AWS_PROFILE, region_name=config.AWS_REGION)


def require_config() -> None:
    missing = [
        name
        for name, value in [
            ("FINSIGHT_KB_ID", config.KB_ID),
            ("FINSIGHT_KB_DATA_SOURCE_ID", config.KB_DATA_SOURCE_ID),
            ("FINSIGHT_FILINGS_BUCKET", config.FILINGS_BUCKET),
        ]
        if not value
    ]
    if missing:
        raise KnowledgeBaseError(f"Set {', '.join(missing)} in .env to use the Knowledge Base")


def upload_filing(filing: Filing10K, s3=None) -> list[str]:
    """Upload each extracted section plus its metadata file. Returns the S3 keys."""
    s3 = s3 or _session().client("s3")
    keys = []
    for section in filing.sections:
        key = f"filings/{filing.ticker}/{filing.report_date}/{section.name}.txt"
        # A short header gives the first chunk context; the labels carry it for all chunks.
        header = (
            f"{filing.company} ({filing.ticker}) - Form 10-K for the fiscal year ended "
            f"{filing.report_date} - {section.title}\n\n"
        )
        labels = {
            "metadataAttributes": {
                "ticker": filing.ticker,
                "company": filing.company,
                "section": section.name,
                "fiscal_year_end": filing.report_date,
                "filing_date": filing.filing_date,
                "form": "10-K",
                "source_url": filing.url,
            }
        }
        s3.put_object(
            Bucket=config.FILINGS_BUCKET,
            Key=key,
            Body=(header + section.text).encode(),
            ContentType="text/plain; charset=utf-8",
        )
        s3.put_object(
            Bucket=config.FILINGS_BUCKET,
            Key=f"{key}.metadata.json",
            Body=json.dumps(labels).encode(),
            ContentType="application/json",
        )
        keys.append(key)
    return keys


def sync(agent=None, poll_seconds: float = 10, timeout_seconds: float = 1800) -> dict:
    """Ask Bedrock to (re)index the bucket: chunk, embed and store new or changed files.

    Only changed files are re-embedded, so syncing again is cheap. Returns the job's
    statistics (documents scanned, indexed, failed).
    """
    agent = agent or _session().client("bedrock-agent")
    job = agent.start_ingestion_job(
        knowledgeBaseId=config.KB_ID, dataSourceId=config.KB_DATA_SOURCE_ID
    )["ingestionJob"]
    deadline = time.monotonic() + timeout_seconds
    while job["status"] not in ("COMPLETE", "FAILED", "STOPPED"):
        if time.monotonic() > deadline:
            raise KnowledgeBaseError(f"Sync still running after {timeout_seconds:.0f}s")
        time.sleep(poll_seconds)
        job = agent.get_ingestion_job(
            knowledgeBaseId=config.KB_ID,
            dataSourceId=config.KB_DATA_SOURCE_ID,
            ingestionJobId=job["ingestionJobId"],
        )["ingestionJob"]
    if job["status"] != "COMPLETE":
        reasons = "; ".join(job.get("failureReasons", [])) or job["status"]
        raise KnowledgeBaseError(f"Sync failed: {reasons}")
    return job.get("statistics", {})


def search(ticker: str, query: str, limit: int = 5, runtime=None) -> list[Passage]:
    """The `limit` chunks of a company's filings closest in meaning to `query`."""
    runtime = runtime or _session().client("bedrock-agent-runtime")
    response = runtime.retrieve(
        knowledgeBaseId=config.KB_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": limit,
                # The labels at work: only search this company's chunks.
                "filter": {"equals": {"key": "ticker", "value": ticker.upper()}},
            }
        },
    )
    passages = []
    for result in response["retrievalResults"]:
        labels = result.get("metadata", {})
        passages.append(
            Passage(
                text=result["content"]["text"],
                score=result.get("score", 0.0),
                ticker=labels.get("ticker", ticker.upper()),
                section=labels.get("section", ""),
                fiscal_year_end=labels.get("fiscal_year_end", ""),
                source_url=labels.get("source_url", ""),
            )
        )
    return passages


def indexed_filings(s3=None) -> dict[str, list[str]]:
    """Which companies have filings in the bucket: {ticker: [fiscal-year-end, ...]}."""
    s3 = s3 or _session().client("s3")
    found: dict[str, set[str]] = {}
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=config.FILINGS_BUCKET, Prefix="filings/"
    ):
        for obj in page.get("Contents", []):
            parts = obj["Key"].split("/")  # filings/<TICKER>/<date>/<file>
            if len(parts) == 4 and parts[3].endswith(".txt"):
                found.setdefault(parts[1], set()).add(parts[2])
    return {ticker: sorted(dates) for ticker, dates in sorted(found.items())}
