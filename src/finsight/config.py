"""App configuration, loaded from environment variables (and the local `.env` file)."""

import os

from dotenv import load_dotenv

# Reads `.env` into os.environ. Real environment variables win over `.env` values,
# so CI or production can override anything without touching files.
load_dotenv()

MODEL = os.getenv("FINSIGHT_MODEL", "claude-opus-5")

# USD per million tokens (Anthropic list prices). Cache writes cost 1.25x input,
# cache reads 0.1x input.
PRICING = {
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}
