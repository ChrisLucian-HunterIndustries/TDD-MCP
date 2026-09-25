# Writing code

Always use the `tdd` MCP server's `write_file` / `edit_file` tools to change
`.py` files in this repository. Built-in editing of Python files is blocked.
Start each cycle with `run_coverage`, write a failing test, make it pass, then
refactor. Call `tdd_status` if unsure what the current phase allows.

# Committing

Always use the `racn` MCP server's `commit` tool to commit changes in this
repository. Never run `git commit` from the command line — it is blocked.
Stage with `git add` and commit in separate, sequential steps (never in
parallel). Prefer small, focused microcommits: typically one per completed
green or refactor step.

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, running the server, and
development notes.
