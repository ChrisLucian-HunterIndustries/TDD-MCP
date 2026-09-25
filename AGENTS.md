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
In this repo, write `.py` files only through the `tdd` MCP server (`run_coverage` -> failing test -> passing code -> refactor); see the `tdd-cycle` skill. If the `tdd` tools aren't loaded in the current session, drive the server over stdio with an MCP client script rather than bypassing the cycle. VS Code loads MCP servers from `.vscode/mcp.json`, Claude Code from `.mcp.json`: register a server in both.
The running `tdd` server keeps its code from when it was started. After changing the server's own code, ask the user to restart it before relying on the fix.
Commit each green or refactor step with the `racn` MCP `commit` tool. Run `git add` and `commit` sequentially, never in the same parallel batch (it races and fails).
For anything that spawns test subprocesses, run the suite both with and without `--cov`: timing differences expose caching and race bugs.

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