---
name: tdd-cycle
description: Use when changing code files in a repository that has the `tdd` MCP server configured — how to drive run_coverage / write_file / edit_file through red, green, and refactor, and what to do when a write is refused or reverted.
---

# Driving the TDD cycle with the `tdd` MCP server

1. `run_coverage(location)` — must pass. Read the Missing column: untested lines are
   candidates for the next test.
2. **Red**: add exactly **one** test that fails. Red only advances when exactly one test fails
   and at most one test was added since the coverage run, so never write a batch. A collection
   error (importing something that doesn't exist yet) counts; a Python file that can't import
   counts as every `test*` function in it.
   A test that already passes keeps you in red — that's a characterization test; fine to keep.
   Commit the failing test on its own: `. t` (racn `test_only`, `proven_safe`).
3. **Green**: change production code only, as little as possible, until `Phase: refactor`.
   Tests are locked — don't try to weaken the test to get green. Don't write code for cases no
   test exercises yet: the next `run_coverage` refuses to start a cycle while any production
   line changed this cycle is uncovered.
   Commit the code alone: `^ f` (racn `feature`, `validated`), or `^ b` for a bugfix.
4. **Refactor**: tidy test or production code. A write that breaks the suite or adds a test is
   reverted automatically; read the output and make a smaller step. Commit each step: `. r`.
5. `run_coverage` to start the next cycle. If it lists uncovered changed lines
   ("calc.py: 6"), delete that code in refactor (adding a test there is reverted), commit, rerun.

Uncommitted changes belong to the step (phase) that was active when the tree was last clean.
Repeat edits within that step are fine, so a test or a change can take several `edit_file`
calls. Commit before the next phase's edits; `run_coverage` also ends the step, so commit
before running it. Coverage measures branches: an `if` with an untaken path is uncovered.

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
  against the previous phase and be refused. Likewise never batch a racn `commit` with the
  next `tdd` edit: the edit races the commit and is refused as "Uncommitted changes".
- A change touching distant parts of a file (e.g. an import and a function) can be several
  `edit_file` calls in the same step; prefer that to rewriting the whole file.
- Don't use a no-op `edit_file` (identical strings) to "locate" text; read the file instead.
- A characterization test (passes immediately) belongs in red: call `run_coverage` first.
  Added in refactor, a current server reverts it; a stale server may silently accept it.
- To tell which build a running server is, compare the server process's start time with
  `git log --format="%h %ci"`. Mind the timezones: process times are local, commit times
  carry their own offset.
- When `old_string` ends on the first line of the next function (e.g. `def next_test(...):`)
  and `new_string` doesn't repeat it, that function's header is deleted and its body merges
  into yours. Anchor on lines inside the block you're extending instead.
- Before moving on, check that red failed for the *intended* reason. A `NameError` or a broken
  test helper also counts as red. While the red step is uncommitted, just edit the test again
  to fix it. Only restore it if you already moved on.
- Approved snapshot files that must change alongside a test (e.g. `manifest.approved.json`)
  are non-code: update them during red, before the failing test. If that would make
  `run_coverage` fail, save the change as a patch, run coverage, then re-apply it.
  Alternatively, in green, once the code change leaves only the snapshot failing, review
  and approve the received file. The next production edit re-runs the suite and reaches refactor.
- Refactor in steps that each stay green: add a new helper first, then switch callers one edit
  at a time. An edit that references something not yet defined is reverted.
- When a red test needs changes in several places (e.g. a new required constructor argument
  used by many tests), make them as several edits before committing the red step.
- A production change that would break tests you can't touch yet (locked in green) can be
  "faked" first (e.g. a no-op collaborator), then driven out by the next cycle's red test.
- `run_coverage` language `typescript` needs `npm install -D vitest @vitest/coverage-v8` in the
  project; a missing runner is reported as an error, never as a failing test.
- Editing the server's own entry in `.mcp.json` / `.vscode/mcp.json` makes the client restart
  it, which resets the phase. Call `run_coverage` again if you see "No TDD cycle started".
- Paths matching the server's `TDD_MCP_EXEMPT` patterns (set in the config's `env`) skip the
  cycle entirely; the write result says "exempt from the TDD cycle".
