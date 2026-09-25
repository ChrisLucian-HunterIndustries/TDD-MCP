# Contributing

README.md is for people using the server; this file is for people changing it.

## Setup

Install [mise](https://mise.jdx.dev/), then:

```bash
./build_and_test        # or build_and_test.cmd on Windows
```

This installs Python and uv, syncs dependencies, and runs the tests with coverage.

Other tasks: `mise run run` (start the server on stdio), `mise run format` (ruff format).

## Dogfooding

This repository is developed with its own server. [.mcp.json](.mcp.json) registers `tdd` (this
server, from local source) and `racn` ([Risk-Aware Commit Notation](https://github.com/JayBazuzi/RiskAwareCommitNotationMcp)).
[.claude/settings.json](.claude/settings.json) blocks direct `git commit` and built-in edits of
Python files, so agents must go through the cycle and commit with RACN. See [CLAUDE.md](CLAUDE.md).

## Layout

- `src/tdd_mcp/cycle.py` — the phase state machine; pure, no I/O.
- `src/tdd_mcp/workspace.py` — root-confined file writes with undo snapshots.
- `src/tdd_mcp/service.py` — ties a project's session, language, and files together.
- `src/tdd_mcp/server.py` — MCP tool bindings only.
- `src/tdd_mcp/languages/` — one `LanguageAdapter` per language.

## Adding a language

1. Create `src/tdd_mcp/languages/<language>.py` with a class that has a `name` and implements
   `classify`, `run_tests`, and `run_coverage` (see `LanguageAdapter` in `languages/base.py`).
   Use `run_suite` with a map from the test runner's exit codes to `Outcome`s; unmapped codes are
   treated as errors.
2. Register an instance in `ADAPTERS` in `languages/__init__.py`.
3. Add tests like `tests/test_python_adapter.py`, then re-approve `tests/manifest.approved.json`
   (the `language` parameter's enum changes).

## Tests

`tests/manifest.approved.json` is an [approval test](https://approvaltests.com/) of the tool
manifest clients see. When a tool signature or docstring changes on purpose, review
`manifest.received.json` and rename it over the approved file.
