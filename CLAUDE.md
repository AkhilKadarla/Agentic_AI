# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project
FinSight: an AI research analyst agent for the finance industry (SEC filings, financials,
market data -> research notes). The owner is learning agentic AI; explain the *why* of
changes, keep steps small, and prefer simple, readable code over clever abstractions.

## Commands
- `uv sync` - install dependencies into `.venv`
- `uv run finsight ask "<question>"` - single Claude call (costs real money)
- `uv run pytest` - run tests (with coverage)
- `uv run ruff check --fix . && uv run ruff format .` - lint and format
- `uv run pre-commit run --all-files` - run all commit hooks
- `uv add <pkg>` / `uv add --dev <pkg>` - add a dependency (never edit versions by hand)

## Conventions
- Python 3.12, `src/` layout, package `finsight`
- Secrets live in `.env` (git-ignored); document new ones in `.env.example`
- Workflow: feature branch -> pull request -> CI green -> merge to `main`
- Every new feature gets tests in `tests/`; all checks must pass before committing
- Model: `claude-opus-5` by default (override with FINSIGHT_MODEL); SDK: `anthropic`
- Tests must never call the real API or network - inject a fake client (tests/test_llm.py)
  or an httpx.MockTransport (tests/test_sec.py)
- New tools: add the definition to TOOLS and the implementation to run_tool() in tools.py;
  return errors to Claude as (message, True) instead of raising
- Never present outputs as financial advice
