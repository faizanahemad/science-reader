---
description: Prepare and open a pull request for the current branch following the repo's GitHub workflow — review all commits and the base diff, then write a clear PR description and create it with gh.
agent: build
model: openrouter/anthropic/claude-sonnet-4.6
---

This command is run inline by the main agent, so it can use the PR title/intent you provide via $ARGUMENTS or the conversation. To keep the main context lean, delegate the base-diff and commit review to a sub-agent via the Task tool (have it read `diff <base>...HEAD` and `log <base>..HEAD` and return a structured summary of the changes); the main agent then writes the description from that summary plus the conversation.

Prepare and open a pull request for the current branch, following the Git/GitHub guidelines in AGENTS.md. Only create a PR when this command is invoked.

Steps:
1. Inspect thoroughly before writing the description:
   - `git status` and `git branch --show-current`.
   - Remote tracking state: `git rev-parse --abbrev-ref --symbolic-full-name @{u}` (push first if the branch has no upstream / unpushed commits).
   - Determine the base branch (usually `main`/`master`) and review the FULL diff from base: `git diff <base>...HEAD`.
   - Review ALL commits in the PR, not just the latest: `git log <base>..HEAD --oneline`.
2. Secret scan the cumulative diff before publishing; if credentials are present, STOP and report.
3. Write the PR description:
   - Summary — what this PR does and why.
   - Changes — the key changes grouped logically (not a raw file dump).
   - Testing — how it was verified (tie to `/verify` results if available).
   - Notes / risks — anything reviewers should watch, and any follow-ups.
4. Create the PR with `gh pr create`, targeting the correct base branch, with a clear title matching repo conventions.

Rules:
- Do not force-push. Push the branch normally if needed before creating the PR.
- If the base branch or PR target is ambiguous, ask before creating.
- After creation, return the PR URL.
