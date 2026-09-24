"""App configuration, loaded from environment variables (and the local `.env` file)."""

import os

from dotenv import load_dotenv

# Reads `.env` into os.environ. Real environment variables win over `.env` values,
# so CI or production can override anything without touching files.
load_dotenv()

MODEL = os.getenv("FINSIGHT_MODEL", "claude-opus-5")
