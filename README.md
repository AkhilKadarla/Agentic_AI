# FinSight

An AI research analyst agent for the finance industry. FinSight reads public company
filings (SEC EDGAR), financial statements and market data, then produces analyst-style
research notes, built step by step to learn modern agentic AI engineering.

## Roadmap

- [x] **Phase 0 - Foundation:** uv, Python 3.12, project layout, secrets handling
- [x] **Phase 1 - Code quality:** ruff, pytest, pre-commit hooks
- [ ] **Phase 2 - CI/CD:** GitHub Actions, branch protection
- [ ] **Phase 3 - First agent:** raw LLM call → tool use → agent loop
- [ ] **Phase 4 - Real agent:** SEC EDGAR tools, memory, MCP, structured outputs
- [ ] **Phase 5 - Evals & observability:** test agent quality, tracing
- [ ] **Phase 6 - Deploy:** Docker + cloud deployment

## Quickstart

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                  # create .venv and install dependencies
cp .env.example .env     # then fill in your keys
uv run finsight          # run the app
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
tests/          # automated tests (Phase 1)
```

> Disclaimer: FinSight is a learning project and does not provide financial advice.
