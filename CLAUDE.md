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
- `uv run finsight ui` - Streamlit app on localhost:8501 (config in .streamlit/config.toml)
- `uv add <pkg>` / `uv add --dev <pkg>` - add a dependency (never edit versions by hand)

## Conventions
- Python 3.12, `src/` layout, package `finsight`
- Secrets live in `.env` (git-ignored); document new ones in `.env.example`
- Workflow: feature branch -> pull request -> CI green -> merge to `main`
- Every new feature gets tests in `tests/`; all checks must pass before committing
- Agent: `ResearchAgent` in agent.py (loop capped by MAX_TURNS, memory in .messages,
  yields TextDelta/ToolCall/ToolResult/Done events; UIs render events, never print in agent); SEC financial metrics map to
  candidate XBRL concepts in `sec.METRICS`
- Structured output: `ResearchNote` (notes.py) via streamed `client.beta.messages.stream(output_format=...)`
  with max_tokens=64000 (thinking + JSON share the budget);
  notes save to reports/ (git-ignored)
- UI: ui.py renders ResearchAgent events; state in st.session_state; tests use Streamlit
  AppTest with an injected fake-backed agent (tests/test_ui.py)
- Model: `claude-opus-5` by default (override with FINSIGHT_MODEL); SDK: `anthropic`
- Providers: FINSIGHT_PROVIDER=anthropic|bedrock; all provider differences live in
  providers.py (client, model ID, fallbacks only on anthropic, caching style). Bedrock uses
  AnthropicBedrock (bedrock-runtime) + SSO profile; it rejects top-level cache_control, so
  agent.py marks explicit breakpoints. tests/conftest.py pins tests to the anthropic provider
- Tests must never call the real API or network - inject a fake client (tests/test_llm.py)
  or an httpx.MockTransport (tests/test_sec.py)
- New tools: add the definition to TOOLS and the implementation to run_tool() in tools.py;
  return errors to Claude as (message, True) instead of raising
- Guardrail: guardrail.py via ApplyGuardrail (provider-independent); input check before
  Claude, output + per-paragraph grounding after ("stream, then flag"); fail closed on
  errors; version must be pinned (FINSIGHT_GUARDRAIL_VERSION). Grounding sources are
  readable text with written dates, tables checked as sentences (measured: big score gains).
  Run scripts/guardrail_suite.py before publishing a guardrail version
- Never present outputs as financial advice
