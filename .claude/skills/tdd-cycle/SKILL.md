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
3. **Green**: change production code only, as little as possible, until `Phase: refactor`.
   Tests are locked — don't try to weaken the test to get green.
4. **Refactor**: tidy test or production code. A write that breaks the suite is reverted
   automatically; read the output and make a smaller step.
5. Commit (e.g. with the `racn` MCP), then `run_coverage` to start the next cycle.

## When refused

- "No TDD cycle started" — call `run_coverage` first (server restarts reset state).
- "not allowed in the red phase" for production code — write the failing test first.
- "not allowed in the green phase" for a test — finish green first; fix the test in refactor.
- "Expected exactly one match" — widen `old_string` with surrounding lines.

Non-code files (docs, config) are written without running tests in any started cycle.
Prefer `edit_file` over `write_file` for existing files; every write runs the whole suite.
