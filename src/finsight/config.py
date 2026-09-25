"""App configuration, loaded from environment variables (and the local `.env` file)."""

import os

from dotenv import load_dotenv

# Reads `.env` into os.environ. Real environment variables win over `.env` values,
# so CI or production can override anything without touching files.
load_dotenv()

# Which service runs Claude: "anthropic" (the Anthropic API) or "bedrock" (Amazon Bedrock).
PROVIDER = os.getenv("FINSIGHT_PROVIDER", "anthropic").lower()

# Model for the Anthropic API.
MODEL = os.getenv("FINSIGHT_MODEL", "claude-opus-5")

# Bedrock settings. The "us." prefix is a US-only cross-region inference profile: requests
# are processed only in US regions (data residency). "global." would allow any region.
BEDROCK_MODEL = os.getenv("FINSIGHT_BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-6")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_PROFILE = os.getenv("AWS_PROFILE")  # e.g. "finsight" (SSO); None = default AWS chain

# USD per million tokens (Anthropic list prices; Bedrock on-demand prices are similar but
# check the AWS pricing page). Cache writes cost 1.25x input, cache reads 0.1x input.
PRICING = {
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-opus-4-6": {"input": 5.00, "output": 25.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}
