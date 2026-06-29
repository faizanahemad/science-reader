---
description: Create a git commit for the current changes following the repo's git rules — inspect first, stage only intended files, write a concise message matching repo style, never commit secrets.
agent: build
model: amazon-bedrock/anthropic.claude-sonnet-4-6
---

This command is run inline by the main agent, so it can use the commit message or details you provide via $ARGUMENTS or the conversation. To keep the main context lean, delegate inspection of large diffs to a sub-agent via the Task tool (have it summarize what changed and flag anything unexpected); the main agent decides the final staged set and the message.

Create a git commit for the work in this session, following the Git guidelines in AGENTS.md. Only commit when this command is invoked — never commit unprompted.

Steps:
1. Inspect before staging:
   - `git status` to see all changed/untracked files.
   - `git diff` (and `git diff --staged`) to review the actual changes.
   - `git log --oneline -10` to learn the repo's commit message style.
2. Stage only the files intended for this change. Do NOT blindly `git add .` — exclude unrelated edits, scratch files, logs, and anything not part of this task.
3. Check for secrets: scan the staged diff for API keys, tokens, passwords, JWT secrets, `.env` contents, or credentials. If any are present, STOP and report instead of committing.
4. Write a concise commit message that matches the repo's existing style (tense, prefix conventions, length). Describe what and why, not a file list.
5. Commit the staged changes.

Rules:
- Do not push, force-push, amend, create empty commits, use interactive rebase, or skip hooks unless explicitly asked.
- If a pre-commit hook rejects the commit, fix the issue and create a NEW commit — do not amend the failed one.
- If anything is ambiguous (which files belong, message wording for a mixed change), ask before committing.
- After committing, report the commit hash and message.
