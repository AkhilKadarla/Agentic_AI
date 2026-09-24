# FinSight

An AI research analyst agent for the finance industry. FinSight reads public company
filings (SEC EDGAR), financial statements and market data, then produces analyst-style
research notes, built step by step to learn modern agentic AI engineering.

## Roadmap

- [x] **Phase 0 - Foundation:** uv, Python 3.12, project layout, secrets handling
- [ ] **Phase 1 - Code quality:** ruff, pytest, pre-commit hooks
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
```

## Project layout

```
src/finsight/   # application code
tests/          # automated tests (Phase 1)
```

> Disclaimer: FinSight is a learning project and does not provide financial advice.
