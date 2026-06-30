---
description: Rebuild lost context after compaction or summarization — reconstruct what was being done, what changed, and what is left, using git state and session history. Read-only.
agent: build
model: openrouter/anthropic/claude-sonnet-4.6
---

This command is run inline by the main agent so the reconstructed context lands in the main thread where it is needed. To avoid bloating it with raw material, delegate the gathering to sub-agents via the Task tool: have them read the git diffs, run `session_search`/`session_read`, and scan plan/hand-off docs, returning ONLY a distilled reconstruction. Take any hint from $ARGUMENTS.

Reconstruct the working context after a context loss (compaction, summarization, or a fresh session continuing earlier work). Do not start new work — first re-establish what was already happening.

Steps:
1. Inspect the working tree:
   - `git status` — what files are modified/untracked (the in-flight change).
   - `git diff` and `git diff --staged` — the actual edits made so far.
   - `git log --oneline -15` — recent commits for trajectory.
2. Recover the conversation/task history:
   - Use the session tools (`session_search`, `session_list`, `session_read`) to find the original user ask, decisions made, and any plan or hand-off doc referenced.
   - Look for a referenced `.plan.md` in `documentation/planning/plans/` or a hand-off summary from `/shorten`.
3. Read the relevant files surfaced above just enough to understand the current state of the change.

Report (do not edit anything):
- Original goal / user ask, as best reconstructed.
- What has been done already (with `file:line` references from the diff).
- What remains, and the immediate next step.
- Any constraints, decisions, or open questions found in history.
- Anything ambiguous that should be confirmed before resuming.

Do not modify or edit any file. This is recovery/orientation only.
