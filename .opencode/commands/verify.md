---
description: Run the project's tests, linter and type checks and report structured ground-truth results (pass/fail with actual output). Does not claim success without running.
agent: build
model: amazon-bedrock/anthropic.claude-sonnet-4-6
---

This command is run inline by the main agent, so it keeps the full conversation context and any scope you pass via $ARGUMENTS. To protect the main context window, delegate the actual run to a sub-agent via the Task tool: have it execute the tests/lint/typecheck and return ONLY the PASS/FAIL digest plus the salient failing lines (with file:line and error text) — keep verbose output out of the main thread. Use the conversation and `git status`/`git diff` to scope the run.

Verify the current state of the code by actually running it. Do not assert that anything works without executing it — your job is to produce ground truth, not opinion.

Steps:
1. Activate the project environment first: `conda activate science-reader` (per AGENTS.md). All Python runs in this env.
2. Detect what verification the repo supports, then run the relevant subset for the work in this session:
   - Tests: run `pytest` (scope to the files/areas touched this session when possible, e.g. `pytest tests/test_x.py`, otherwise the relevant test module). Use the narrowest scope that still covers the change.
   - Lint: run `ruff check` on the changed files (a `.ruff_cache` exists, so ruff is configured).
   - Type / import sanity: import or syntax-check changed modules if no type checker is configured.
3. Prefer the narrowest scope that covers what changed this session over running everything; only run the full suite if explicitly asked or if the change is broad.

Reporting rules:
- Report a clear PASS / FAIL per check.
- Paste the ACTUAL command output (or the salient failing lines) as evidence — never paraphrase a pass.
- For each failure: give the command run, the failing file:line, and the error text. Do not propose fixes here; just report.
- If a check could not be run (missing dep, no test for the area), say so explicitly rather than silently skipping it.

Do not edit or modify any file. Running code and tests is allowed; changing source is not.
