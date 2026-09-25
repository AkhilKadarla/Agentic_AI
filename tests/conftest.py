"""Shared test setup, applied to every test automatically."""

import pytest

from finsight import config


@pytest.fixture(autouse=True)
def default_provider(monkeypatch):
    """Tests run against the Anthropic provider, whatever your local .env says, so
    FINSIGHT_PROVIDER=bedrock on your laptop can't change test results."""
    monkeypatch.setattr(config, "PROVIDER", "anthropic")
    monkeypatch.setattr(config, "MODEL", "claude-opus-5")
    monkeypatch.setattr(config, "BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-6")
    monkeypatch.setattr(config, "AWS_REGION", "us-east-1")
    monkeypatch.setattr(config, "AWS_PROFILE", None)
    monkeypatch.setattr(config, "GUARDRAIL_ID", None)  # no guardrail unless a test adds one
    monkeypatch.setattr(config, "GUARDRAIL_VERSION", None)
