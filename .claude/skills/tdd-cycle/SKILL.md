---
name: tdd-cycle
description: Use when changing code files in a repository that has the `tdd` MCP server configured — how to drive run_coverage / write_file / edit_file through red, green, and refactor, and what to do when a write is refused or reverted.
---

# Driving the TDD cycle with the `tdd` MCP server

1. `run_coverage(location)` — must pass. Read the Missing column: untested lines are
   candidates for the next test.
2. **Red**: `write_file`/`edit_file` a test file. Keep going until the response says
   `Phase: green`. A collection error (importing something that doesn't exist yet) counts.
   A test that already passes keeps you in red — that's a characterization test; fine to keep.
   Commit the failing test on its own: `. t` (racn `test_only`, `proven_safe`).
3. **Green**: change production code only, as little as possible, until `Phase: refactor`.
   Tests are locked — don't try to weaken the test to get green.
   Commit the code alone: `^ f` (racn `feature`, `validated`), or `^ b` for a bugfix.
4. **Refactor**: tidy test or production code. A write that breaks the suite is reverted
   automatically; read the output and make a smaller step. Commit each step: `. r`.
5. `run_coverage` to start the next cycle.

The server refuses every edit while `git status` shows uncommitted changes under the
project, so each step has to be committed before the next edit.

## When refused

- "Uncommitted changes in ..." — commit the listed changes (sequentially: `git add`, then the
  racn `commit` tool), then retry the edit.
- "No TDD cycle started" — call `run_coverage` first (server restarts reset state).
- "not allowed in the red phase" for production code — write the failing test first.
- "not allowed in the green phase" for a test — finish green first; fix the test in refactor.
- "Expected exactly one match" — widen `old_string` with surrounding lines.

Non-code files (docs, config) are written without running tests in any started cycle.
Prefer `edit_file` over `write_file` for existing files; every write runs the whole suite.
Use `run_tests(location, path, test_name)` to iterate quickly on one file, folder, or test
without coverage. It never changes the phase, so a green result there unlocks nothing.

## Pitfalls

- Call `tdd` tools strictly one at a time. A write sent in parallel with `run_coverage` can run
  against the previous phase and be refused.
- Before moving on, check that red failed for the *intended* reason. A `NameError` or a broken
  test helper also counts as red, and then the test is locked in green. Fix: `git restore` the
  uncommitted test, `run_coverage`, and write it again.
- Approved snapshot files that must change alongside a test (e.g. `manifest.approved.json`)
  are non-code: update them during red, before the failing test. If that would make
  `run_coverage` fail, save the change as a patch, run coverage, then re-apply it.
  Alternatively, in green, once the code change leaves only the snapshot failing, review
  and approve the received file. The next production edit re-runs the suite and reaches refactor.
- Refactor in steps that each stay green: add a new helper first, then switch callers one edit
  at a time. An edit that references something not yet defined is reverted.
- When a red test needs changes in several places (e.g. a new required constructor argument
  used by many tests), make them in one `write_file` of the whole test file. The first
  failing edit locks the tests, so there is no second chance to update the rest.
- A production change that would break tests you can't touch yet (locked in green) can be
  "faked" first (e.g. a no-op collaborator), then driven out by the next cycle's red test.
- `run_coverage` language `typescript` needs `npm install -D vitest @vitest/coverage-v8` in the
  project; a missing runner is reported as an error, never as a failing test.
- Editing the server's own entry in `.mcp.json` / `.vscode/mcp.json` makes the client restart
  it, which resets the phase. Call `run_coverage` again if you see "No TDD cycle started".
- Paths matching the server's `TDD_MCP_EXEMPT` patterns (set in the config's `env`) skip the
  cycle entirely; the write result says "exempt from the TDD cycle".
