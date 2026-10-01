---
name: tdd-cycle
description: Use when changing code files in a repository that has the `tdd` MCP server configured — how to drive advance_tdd_phase / write_file / edit_file through red, green, and refactor, and what to do when a write is refused or reverted.
---

# Driving the TDD cycle with the `tdd` MCP server

Every reply starts with `Phase: <phase>` and ends with `Next: ...`. Follow the Next line.

1. `advance_tdd_phase(location)` — the only tool that starts a cycle or moves to the next
   phase. All tests pass: red. Read the Missing column: untested lines are candidates for the
   next test. (`run_coverage` shows the same report but never changes the phase.)
2. **Red**: add exactly **one** test that fails, before any production code. Red only advances
   when exactly one test fails and at most one test was added since the cycle started, so never
   write a batch. A collection error (importing something that doesn't exist yet) counts, and so
   does a run that can't collect or run the tests at all (e.g. a broken `conftest.py`); a Python
   file that can't import counts as every `test*` function in it.
   A test that already passes keeps you in red — that's a characterization test; fine to keep.
   Commit the failing test on its own: `. t` (racn `test_only`, `proven_safe`).
3. **Green**: change production code only, as little as possible, until `Phase: refactor`.
   Tests are locked — don't try to weaken the test to get green. Don't write code for cases no
   test exercises yet: the next `advance_tdd_phase` refuses to start a cycle while any production
   line changed this cycle is uncovered.
   Commit the code alone: `^ f` (racn `feature`, `validated`), or `^ b` for a bugfix.
4. **Refactor**: tidy test or production code. A write that breaks the suite or adds a test is
   reverted automatically; read the output and make a smaller step. Commit each step: `. r`.
5. `advance_tdd_phase` to start the next cycle. If it lists uncovered changed lines
   ("calc.py: 6"), delete that code in refactor (adding a test there is reverted), commit, rerun.
   If it lists changed lines holding comments, remove the comments (tool directives such as
   `# noqa` or `// @ts-expect-error` are fine), commit, rerun.

Uncommitted changes belong to the step (phase) that was active when the tree was last clean.
Repeat edits within that step are fine, so a test or a change can take several `edit_file`
calls. Commit before the next phase's edits; `advance_tdd_phase` also ends the step, so commit
before running it. Coverage measures branches: an `if` with an untaken path is uncovered.

## When refused or stuck

- "Uncommitted changes in ..." — commit the listed changes (sequentially: `git add`, then the
  racn `commit` tool), then retry the edit.
- "No TDD cycle started" — call `advance_tdd_phase` first (server restarts reset state).
- "not allowed in the red phase" for production code — write the failing test first.
- "not allowed in the green phase" for a test — finish green first; fix the test in refactor.
- "N tests were added since the cycle started" or "N tests fail" in red — edit the tests until
  exactly one fails: delete extra test functions entirely (a body of only `pass` still counts)
  or fix wrong ones. `advance_tdd_phase` with several failing tests also lands here. If a test
  fails because production code is broken, stop and ask the user instead of deleting it.
- coverage_required after `advance_tdd_phase` — the test runner couldn't run (e.g. pytest-cov
  missing). No tool can fix that: stop and ask the user, then `advance_tdd_phase` again.
- "Expected exactly one match" — widen `old_string` with surrounding lines.
- The repository changed outside the server (e.g. `git reset`) — call `advance_tdd_phase`: it
  recomputes the phase (all pass: red; exactly one fails: green).
- Green, but an existing test that's locked asserts the old behaviour — undo your uncommitted
  production edits (production is still writable), call `return_to_red`, then edit that test so
  it passes without the old behaviour. Further test edits amend the same uncommitted red step;
  commit them as `. t`, then redo the production change. No git reset needed.

Non-code files (docs, config) are written without running tests in any started cycle.
Prefer `edit_file` over `write_file` for existing files; every write runs the whole suite.
Use `run_tests(location, path, test_name)` to iterate quickly on one file, folder, or test
without coverage. Like `run_coverage`, it never changes the phase, so a green result there
unlocks nothing.

## Pitfalls

- Call `tdd` tools strictly one at a time. A write sent in parallel with `advance_tdd_phase` can
  run against the previous phase and be refused. Likewise never batch a racn `commit` with the
  next `tdd` edit: the edit races the commit and is refused as "Uncommitted changes".
- Before a red test that changes behaviour other tests rely on, check which existing tests
  assert the old behaviour and adjust them first, while they still pass.
- A change touching distant parts of a file (e.g. an import and a function) can be several
  `edit_file` calls in the same step; prefer that to rewriting the whole file. A signature
  change plus its callers in one step needs `write_file` (each edit must stay green in refactor).
- Don't use a no-op `edit_file` (identical strings) to "locate" text; read the file instead.
- A characterization test (passes immediately) belongs in red: call `advance_tdd_phase` first.
  Added in refactor, a current server reverts it; a stale server may silently accept it.
- To tell which build a running server is, compare the server process's start time with
  `git log --format="%h %ci"`. Mind the timezones: process times are local, commit times
  carry their own offset. A server that refuses a second edit within one uncommitted step
  predates step amending: ask the user to restart it.
- When `old_string` ends on the first line of the next function (e.g. `def next_test(...):`)
  and `new_string` doesn't repeat it, that function's header is deleted and its body merges
  into yours. Anchor on lines inside the block you're extending instead.
- Before moving on, check that red failed for the *intended* reason. A `NameError` or a broken
  test helper also counts as red. While the red step is uncommitted, just edit the test again
  to fix it. Only restore it if you already moved on.
- A new test that imports a not-yet-existing name at module level makes the whole file
  unimportable, so every test in it counts as failing. Import inside the test (or reach it via
  the module, e.g. `server.new_tool`), then move the import up in refactor.
- Approved snapshot files that must change alongside a test (e.g. `manifest.approved.json`)
  are non-code: update them during red, before the failing test. If that would make
  `advance_tdd_phase` fail, save the change as a patch, run it, then re-apply the patch.
  Alternatively, in green, once the code change leaves only the snapshot failing, review
  and approve the received file. The next production edit re-runs the suite and reaches refactor.
  In refactor, write the approved file first, then the docstring edit that matches it.
- Refactor in steps that each stay green: add a new helper first, then switch callers one edit
  at a time. An edit that references something not yet defined is reverted.
- When a red test needs changes in several places (e.g. a new required constructor argument
  used by many tests), make them as several edits before committing the red step.
- A production change that would break tests you can't touch yet (locked in green) can be
  "faked" first (e.g. a no-op collaborator), then driven out by the next cycle's red test.
- `advance_tdd_phase` language `typescript` needs `npm install -D vitest @vitest/coverage-v8` in
  the project; a missing runner is reported as an error, never as a failing test.
- Editing the server's own entry in `.mcp.json` / `.vscode/mcp.json` makes the client restart
  it, which resets the phase. Call `advance_tdd_phase` again if you see "No TDD cycle started".
- Paths matching the server's `TDD_MCP_EXEMPT` patterns (set in the config's `env`) skip the
  cycle entirely; the write result says "exempt from the TDD cycle".
