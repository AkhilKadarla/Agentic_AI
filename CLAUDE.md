# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project
FinSight: an AI research analyst agent for the finance industry (SEC filings, financials,
market data -> research notes). The owner is learning agentic AI; explain the *why* of
changes, keep steps small, and prefer simple, readable code over clever abstractions.

## Commands
- `uv sync` - install dependencies into `.venv`
- `uv run finsight` - run the app
- `uv run pytest` - run tests (with coverage)
- `uv run ruff check --fix . && uv run ruff format .` - lint and format
- `uv run pre-commit run --all-files` - run all commit hooks
- `uv add <pkg>` / `uv add --dev <pkg>` - add a dependency (never edit versions by hand)

## Conventions
- Python 3.12, `src/` layout, package `finsight`
- Secrets live in `.env` (git-ignored); document new ones in `.env.example`
- Workflow: feature branch -> pull request -> CI green -> merge to `main`
- Every new feature gets tests in `tests/`; all checks must pass before committing
- Never present outputs as financial advice
