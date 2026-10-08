# Contributing

README.md is for people using the server; this file is for people changing it.

## Setup

Install [mise](https://mise.jdx.dev/), then:

```bash
./build_and_test        # or build_and_test.cmd on Windows
```

This installs Python, uv, and Node, syncs dependencies, and runs the tests with coverage. The
TypeScript adapter tests `npm install` vitest into a temporary project once per run, and are
skipped when npm isn't available.

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

## Writing text for the model

Every reply, refusal, tool description and the server instructions are read by an agent, often a
small local model (Gemma 4) with weak attention to the middle of long text. When changing them:

- Put the state first and the next action last. `Report.render` puts the test output between the
  `Phase:` line and the message, so the message's closing `Next:` is what the model reads last.
- Lead a refusal with what didn't happen (`Not written: <path> is unchanged.`). Models that miss
  a refusal build on edits that never landed.
- One instruction per sentence, imperative, with the exact tool name. Name the one next call.
- Cut what the model doesn't need: duplicate phrasing, test-runner headers, rows for fully covered
  files. Tool descriptions and instructions are sent on every request, so they cost the most.
- Keep the lesson, not the wording. Tests pinning guidance cite the Gemma failure that motivated
  them in their docstrings; reword freely, but keep what each one guards against.

## Tests

`tests/manifest.approved.json` is an [approval test](https://approvaltests.com/) of the tool
manifest clients see. When a tool signature or docstring changes on purpose, review
`manifest.received.json` and rename it over the approved file.
