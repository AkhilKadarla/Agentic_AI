# FinSight

[![CI](https://github.com/AkhilKadarla/Agentic_AI/actions/workflows/ci.yml/badge.svg)](https://github.com/AkhilKadarla/Agentic_AI/actions/workflows/ci.yml)

An AI research analyst agent for the finance industry. FinSight reads public company
filings (SEC EDGAR), financial statements and market data, then produces analyst-style
research notes, built step by step to learn modern agentic AI engineering.

## Roadmap

- [x] **Phase 0 - Foundation:** uv, Python 3.12, project layout, secrets handling
- [x] **Phase 1 - Code quality:** ruff, pytest, pre-commit hooks
- [x] **Phase 2 - CI/CD:** GitHub Actions, branch protection
- [x] **Phase 3 - First agent:** raw LLM call → tool use → agent loop
- [ ] **Phase 4 - Real agent:** SEC EDGAR tools, memory, MCP, structured outputs
- [ ] **Phase 5 - Evals & observability:** test agent quality, tracing
- [ ] **Phase 6 - Deploy:** Docker + cloud deployment

## Quickstart

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                  # create .venv and install dependencies
cp .env.example .env     # then fill in your keys
uv run finsight ask "What is EBITDA?"   # ask Claude a finance question
uv run finsight research "Compare Apple and Microsoft revenue growth"   # agent + live SEC data
uv run pre-commit install   # one-time: enable git commit hooks
```

## Development checks

```bash
uv run ruff check .          # lint (find bugs & style issues)
uv run ruff format .         # auto-format code
uv run pytest                # run tests with coverage
uv run pre-commit run --all-files   # run every commit hook
```

## Project layout

```
src/finsight/   # application code
  cli.py        # command-line interface
  llm.py        # calls to Claude (ask, research)
  tools.py      # tool definitions Claude can call
  sec.py        # SEC EDGAR API client
  config.py     # settings loaded from .env
tests/          # automated tests (Phase 1)
```

> Disclaimer: FinSight is a learning project and does not provide financial advice.
