# Agent Instructions
Always create the below checklist for every prompt:

## Checklist Manifesto
Always use your checklist or todo list tool to track items. Do not leave it to chance that you will remember later.
Immediately before implementing any prompts set up the following tasks as a checklist.
- Prod Check
- Preparatory Unit Test Coverage
- Make it easy to change (which may be hard) (refactoring)
- Make the easy change
- Security Review
- Scout Rule
- Single Loop Learning
- Double Loop Learning
- Canary

## Prod Check
When applicable, evaluate the existing health of the production system.

## Preparatory Unit Test Coverage
Ensure the area that will be changed has approrpriate characterization tests making it safe to refactor.
Ensure characterization tests pass before starting any refactoring. 

## Make it easy to change (which may be hard)
Refactor to common computer science grounded design patterns.
The resulting code should be easy to read, limited in file length, appropriately decoupled, and cohesive.

## Make the easy change
Complete the prompt considering YAGNI and DRY concepts in software development. 
In this repo, write `.py` files only through the `tdd` MCP server (`advance_tdd_phase` -> failing test -> passing code -> refactor); see the `tdd-cycle` skill. Call `tdd` tools strictly sequentially, and confirm each red fails for the intended reason before writing production code. If the `tdd` tools aren't loaded in the current session, drive the server over stdio with an MCP client script rather than bypassing the cycle. VS Code loads MCP servers from `.vscode/mcp.json`, Claude Code from `.mcp.json`: register a server in both.
The running `tdd` server keeps its code from when it was started. After changing the server's own code, ask the user to restart it before relying on the fix. When the server behaves unlike the source, first check whether it predates the relevant commit (process start time vs `git log %ci`, in the same timezone) before debugging the code.
When built-in file tools are disabled, write non-code files through the `tdd` server (allowed in any started phase), and pass one-off scripts to `python -` on stdin instead of saving them.
Commit every TDD step with the `racn` MCP `commit` tool: the failing test alone as `. t`, the passing code alone as `^ f`/`^ b`, each refactor as `. r`. The `tdd` server enforces this: edits within one step may repeat, but the next phase's edits are refused until the step is committed, and `advance_tdd_phase` ends the step (commit before running it). Run `git add` and `commit` sequentially, never in the same parallel batch (it races and fails). A `commit` call always goes alone in its batch, never alongside the next `tdd` edit.
Before building on an external tool's output (test runner reports, coverage formats), spike it in a temp dir on the edge cases first, e.g. import errors, syntax errors, and empty suites.
When one request spans several commits, group them with an inline racn theme (`theme_slug` + `theme_mode="inline"`).
Before relying on a new test, reread its assertions: one that can never fail (e.g. `x == [...] or x`) is a false red/green.
For anything that spawns test subprocesses, run the suite both with and without `--cov`: timing differences expose caching and race bugs.
Before a red test that changes behaviour, grep the tests for assertions on the old behaviour (message text, phase names) and adjust them first, while they still pass. Otherwise green locks a conflicting test: undo the production edits and call `return_to_red` to fix it (no git reset needed).
Never send `tdd` edits in parallel, even for non-code files: concurrent edits to one file race and silently drop all but one. When a no-op edit is reported (identical `old_string`/`new_string`), the insert was forgotten: put the new text in `new_string`.
When changing a message or tool text agents read, remember the audience includes small local models: state the current phase and the concrete next tool call. A blocking result must lead with the block (never "passed") and must not end with generic phase guidance that contradicts it (e.g. "optionally tidy"). Budget tokens too: local models may have ~131k context, and every tool reply stays in it, so return runner logs only when something failed. A refusal must repeat the state-specific guidance of the last run (e.g. "delete extra tests"), not fall back to generic phase text.
When reviewing a weaker model's session log, find each refusal it retried and check that the message's "Next" step actually works from that state; if no tool can, say "stop and ask the user" explicitly. Prefer removing the dead end itself: a state the agent can enter but no tool can leave (e.g. every code file locked) is a design bug, not a wording problem; reserve "ask the user" for causes outside the repo (missing runner, broken production code).
Don't add code comments: `advance_tdd_phase` refuses while any line changed this cycle holds one (tool directives excepted). Express intent through names, docstrings, and tests.
When adding a phase rule, check every tool that changes phase (`write_file`/`edit_file`, `advance_tdd_phase`, `return_to_red`) enforces it, and reset per-cycle baselines only when a cycle truly starts; otherwise one tool becomes a loophole around another.

## Security Review
Evaluate for common OWASP pitfalls.
Run automated audits like pip audit, npm audit and correct package issues. For uv projects: `uv export --format requirements-txt --no-hashes --all-groups -o <tmp>` then `uvx pip-audit -r <tmp>`.
For tools that take a path, verify root confinement against `..`, absolute paths, and symlinks.
Evaluate for harder to detect problems with the system such as IDOR vulnerabilities.

## Scout Rule
Always leave the code better than you found it. Perform one of the following in priority order each time a prompt leads you to this area of the code.
- Evaluate Code Coverage and add more complete tests
- File length gate, reduce the file length of the files when over 500 lines by refactoring
- Mutation testing, use a analysis tool to perform mutant hunting on the modified files. For example Cosmic Ray in Python or Striker in Angular.

## Single Loop Learning
Learn from the tasks you complete:
Always end all of our chats with a list of skills that you used.
Always create new skills in your skills folder that you wish you had before starting the prompt. Actually write the file now.
Personal skills go in `~/.copilot/skills/<name>/SKILL.md`; skills that teach use of this repo's own tools go in `.claude/skills/<name>/SKILL.md` and are committed.

## Double Loop Learning
Learn from the process improvement opportunities:
Always evaluate the the process used here using a lens of Lean Software Development, Agile, Systems Thinking, Safety, Security, and Continuous Improvement. 
Always make the changes to the AGENTS.md with these changes. Update this very list you are reading now.
When delegating research to a subagent, verify exact import paths and API names in the source before relying on them. Summaries can paraphrase them incorrectly (seen: `approvaltests.namer` vs `approvaltests.namer.templated_custom_namer`).

## Canary
Always end all of our chats with "# 🪁" Emoji. It should render as a markdown header so the Emoji will be large.