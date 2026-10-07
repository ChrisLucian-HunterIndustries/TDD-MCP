# Test-Driven Development MCP

An [MCP](https://modelcontextprotocol.io/) server that makes coding agents follow the
test-driven development cycle. Code files are written through this server, which only
allows each kind of change when the cycle permits it:

```mermaid
stateDiagram-v2
    [*] --> coverage_required
    coverage_required --> plan: advance_tdd_phase, all tests pass, no planned test left
    plan --> red: plan_tests accepts every test's name, arrange, act and assert
    coverage_required --> red: advance_tdd_phase, all tests pass, a planned test waiting
    coverage_required --> green: advance_tdd_phase, exactly one test fails
    red --> green: a test write leaves exactly one failing test, or the run errors
    green --> refactor: a production write makes the suite pass
    green --> red: return_to_red, with the green edits undone
    refactor --> red: advance_tdd_phase passes, every changed production line is covered, and a planned test is left
    refactor --> plan: the same, after the last planned test is checked off
    refactor --> refactor: edit keeps tests passing and adds none (or is reverted)
```

| Phase | Test files | Production files | Leaves when |
|---|---|---|---|
| `coverage_required` | locked | locked | `advance_tdd_phase` passes (plan, or red while a planned test is left) or finds exactly one failing test (green) |
| `plan` | locked | locked | `plan_tests` accepts a plan in which every test has a name, an arrange, an act and an assert (red) |
| `red` | writable | locked | a test write leaves exactly one failing test, or the tests can't be collected or run, with at most one test added since the cycle started |
| `green` | locked | writable | a production write makes the suite pass, or `return_to_red` (see below) |
| `refactor` | writable | writable | `advance_tdd_phase` passes and covers every production line changed this cycle; any write that breaks tests or adds a test is reverted |

Every reply starts with `Phase: <phase>` and ends with what to do next, and every refusal says how
to get unstuck, so agents (including small local models) always know where they are in the cycle.

### Plan the tests first

A session starts in `plan`, with every code file locked. The agent decides every test the task
needs to be covered completely, and no more, and calls `plan_tests` with each test's name,
arrange, act and assert. Every later reply ends with the checklist (`[x]` done, `[>]` current,
`[ ]` waiting) and the next step for the current test: in red, write only that test from its
arrange, act and assert; in green, write only the production code its assert needs; in refactor,
tidy, commit and advance. Each step tells the agent to do only as much as it needs and no more.
Finishing a cycle (refactor, then a clean `advance_tdd_phase`) checks off the current test. After
the last one the session is back in `plan`: plan only the tests the task still lacks, or stop.
Plans with no tests, duplicate or blank names, or a missing arrange, act or assert are refused, and
`plan_tests` is refused outside the plan phase.

### One test at a time, no speculative code

The server counts tests from the runner's JUnit report. Red only advances when exactly one test
fails and no more than one test was added since the cycle started. Write one test, not a batch.
A Python test file that can't be imported yet counts as every `test*` function it defines.
A test run that can't collect or run the tests at all (e.g. a `conftest.py` importing code that
doesn't exist yet) also counts as the failing test, so programming by intention works from the
very first test.

The next cycle only starts when every production line changed since the cycle began (per `git diff`
against the commit at the start of the cycle, plus untracked files) is executed by some test, with
every branch on it taken. Coverage is measured with branches (`--cov-branch` for pytest; istanbul
branch counts for vitest), so an `if` whose false path no test takes counts as uncovered. Code
written for tests that don't exist yet shows up as uncovered and has to be removed. Refactoring
can't add tests to cover it either, because that's new behaviour, and new behaviour needs its own red.

The next cycle also doesn't start while any code line (test or production) changed this cycle holds
a comment. Say it with names instead. Tool directives stay allowed: `# noqa`, `# type:`,
`# pragma`, `# pyright:`, `# fmt:` and shebangs in Python; `// @ts-…`, `eslint-…`, `istanbul`,
`c8`/`v8`, `prettier-ignore`, `biome-ignore` and `///` directives in TypeScript.

Non-code files (docs, config, data) can be written in any phase once a cycle has started, and don't
trigger a test run.

## Tools

- `tdd_status(location)` — current phase and what it allows.
- `plan_tests(location, tests)` — in the plan phase, set the checklist of tests to write, each a
  `{name, arrange, act, assert}`; moves to red. After a finished plan, adds tests to it.
- `advance_tdd_phase(location, language="python")` — run the whole suite with coverage and move to
  the next phase; the only tool that starts a cycle. `language` is `python` or `typescript`.
- `return_to_red(location)` — go back from green to red, once the uncommitted green edits are
  undone, to update existing tests that assert the old behaviour.
- `run_coverage(location, language="python")` — run the whole suite with coverage and show
  untested lines. It never changes the phase.
- `run_tests(location, path=None, test_name=None)` — run tests without coverage, for fast iteration. By default it runs every test; `path` narrows it to a test file or folder, and `test_name` to matching tests (pytest `-k`, vitest `-t`). It never changes the phase: only `advance_tdd_phase` and the test runs that writes trigger do that.
- `write_file(location, path, content)` — create or overwrite a file, then run the tests.
- `edit_file(location, path, old_string, new_string)` — replace exactly one occurrence, then run the tests.

Paths must resolve inside `location`. Cycle state, including the test plan, is kept in memory per
project, so restarting the server starts again at `coverage_required` and needs a new plan.
`rollback_cycle` keeps the plan.

### Resyncing after changes outside the server

`advance_tdd_phase` recomputes the phase from the tests, so call it after a server restart or when
the repository changed underneath the server (e.g. `git reset`): all tests passing gives red,
exactly one failing test gives green. When a reset rewinds past the commit the cycle started from,
the uncovered-changes check is skipped for that run instead of flagging code from before the reset.

### Stale assertions in existing tests

Sometimes the production change for a new test breaks older tests that assert the old behaviour.
Tests are locked in green, so instead of resetting git, undo the uncommitted production edits and
call `return_to_red`. Back in red, edit those older tests so they pass without the old behaviour
(the new failing test already specifies the new one). The first edit returns to green, but further
test edits amend the same uncommitted red step until it's committed.

### Commit every step

Each step's edits must be committed before the next step starts. Uncommitted changes (staged,
unstaged, or untracked; ignored files don't count) anywhere under `location` belong to the step
that was active when the tree was last clean. Repeat edits within that step are allowed, so a
red test or a green change can take several `edit_file` calls. The server refuses an edit when:

- the tree is dirty and no step is open (e.g. after a server restart or an `advance_tdd_phase` run,
  which ends the step), or
- the edit belongs to a later phase than the open step (e.g. production code after an
  uncommitted red test).

This applies to every file, including non-code and exempt files, and gives a history like:

```
. t Add failing test for add()
^ f Implement add()
. r Extract helper
```

The project must be a git repository. `advance_tdd_phase`, `run_coverage`, `run_tests`, and `tdd_status` aren't gated,
and Python coverage data is written to a temp directory so coverage runs don't dirty the tree.

## Languages

| Language | Test files | Tests run with |
|---|---|---|
| `python` | `test_*.py`, `*_test.py`, `conftest.py`, anything under `test/` or `tests/` | the project's `.venv` interpreter (or the server's) running `pytest`, with `pytest-cov` for coverage |
| `typescript` | `*.test.*`, `*.spec.*`, anything under `__tests__/`, `test/` or `tests/` (`.ts`, `.tsx`, `.mts`, `.cts`, and the `.js` equivalents) | the project's own `node_modules/vitest` via `node`, with `@vitest/coverage-v8` for coverage |

A collection error (such as importing a function that doesn't exist yet) counts as a failing
test. For TypeScript, install the runner in the project first: `npm install -D vitest @vitest/coverage-v8`.
If vitest is missing, the run is reported as an error rather than a failing test.

## Running the server

```bash
git clone <this repository>
cd TDD-MCP
mise run run
```

Example `.mcp.json`:

```json
{
  "mcpServers": {
    "tdd": {
      "command": "mise",
      "args": ["-C", "/path/to/TDD-MCP", "run", "run"]
    }
  }
}
```

For the cycle to be enforced, block the agent's built-in editing of code files. In Claude Code,
add to `.claude/settings.json`:

```json
{ "permissions": { "deny": ["Edit(**/*.py)", "Write(**/*.py)", "Edit(**/*.ts)", "Write(**/*.ts)"] } }
```

### Exempting files from the cycle

Set `TDD_MCP_EXEMPT` in the server's `env` to a comma-separated list of
[fnmatch](https://docs.python.org/3/library/fnmatch.html) patterns. Patterns match paths relative
to the project root, with `/` separators, and `*` also matches across directories. Once a cycle
has started, matching files can be written in any phase, with no failing test needed and no test run:

```json
"env": { "TDD_MCP_EXEMPT": "scripts/*, migrations/*, *.pyi" }
```

`"*"` exempts everything. An empty value, or leaving the variable unset, exempts nothing.
Restart the server after changing it.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
