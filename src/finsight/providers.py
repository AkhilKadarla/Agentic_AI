"""Where Claude runs: the Anthropic API or Amazon Bedrock.

The agent code is the same either way. Only two things differ per provider:
  - the client object (API key vs. AWS credentials), from `make_client()`
  - a few request settings, from `provider_options()` (e.g. server-side fallbacks exist
    only on the Anthropic API; Bedrock uses its own model IDs)

Switch with FINSIGHT_PROVIDER=anthropic|bedrock in .env - no code changes.
"""

import re

import anthropic
from botocore.exceptions import BotoCoreError

from finsight import config

PROVIDERS = ("anthropic", "bedrock")

# Raised by the AWS SDK when credentials are missing or the SSO login has expired.
AWS_CREDENTIAL_ERRORS = (BotoCoreError,)
AWS_LOGIN_HINT = "AWS credentials missing or expired - run: aws sso login --profile {profile}"


def active_provider() -> str:
    if config.PROVIDER not in PROVIDERS:
        raise ValueError(f"FINSIGHT_PROVIDER must be one of {PROVIDERS}, not {config.PROVIDER!r}")
    return config.PROVIDER


def model_id(provider: str | None = None) -> str:
    return config.BEDROCK_MODEL if (provider or active_provider()) == "bedrock" else config.MODEL


def make_client(provider: str | None = None):
    """Create the client for the chosen provider. Both expose the same messages API."""
    if (provider or active_provider()) == "bedrock":
        # Signs each request with your AWS credentials (SSO profile) - no API key involved.
        return anthropic.AnthropicBedrock(
            aws_region=config.AWS_REGION, aws_profile=config.AWS_PROFILE
        )
    return anthropic.Anthropic()  # reads ANTHROPIC_API_KEY


def provider_options(provider: str | None = None) -> dict:
    """Request settings that depend on the provider."""
    provider = provider or active_provider()
    options = {
        "model": model_id(provider),
        # Let Claude decide when to think before answering. (Claude Opus 5 does this by
        # default; Sonnet 4.6 on Bedrock only thinks when asked.)
        "thinking": {"type": "adaptive"},
    }
    if provider == "anthropic":
        # If a safety classifier declines the request, the API retries it on a fallback
        # model automatically. Not available on Bedrock.
        options["betas"] = ["server-side-fallback-2026-07-01"]
        options["fallbacks"] = "default"
    return options


def automatic_caching(provider: str | None = None) -> bool:
    """Whether the provider accepts one top-level `cache_control` for automatic caching.

    Bedrock's bedrock-runtime integration rejects it ("Extra inputs are not permitted"),
    so there we mark cache breakpoints on individual blocks instead (see agent.py).
    """
    return (provider or active_provider()) == "anthropic"


def pricing_key(model: str) -> str:
    """Map a provider's model ID to the price table key.

    "us.anthropic.claude-sonnet-4-6" -> "claude-sonnet-4-6"
    "anthropic.claude-haiku-4-5-20251001-v1:0" -> "claude-haiku-4-5"
    """
    name = model.rsplit("anthropic.", 1)[-1]
    return re.sub(r"(-\d{8})?(-v\d+(:\d+)?)?$", "", name)


def describe() -> str:
    """Human-readable 'provider / model' for display."""
    provider = active_provider()
    where = f" ({config.AWS_REGION})" if provider == "bedrock" else ""
    return f"{provider}{where} / {model_id(provider)}"
