---
description: Create or update documentation for the change made in this session, following the AGENTS.md documentation guidelines. Updates the documentation/ folder and relevant feature docs.
agent: build
model: openrouter/anthropic/claude-sonnet-4.6
---

This command is run inline by the main agent, so it can use the focus/details you provide via $ARGUMENTS or the conversation. To keep the main context lean, delegate the heavy work to sub-agents via the Task tool: have one survey existing docs (to find where the change belongs) and one summarize the code change from `git diff` — pull back only what is needed to write accurate docs. The main agent writes the doc updates.

Document the behavior added or changed in this session. Follow the documentation guidelines in AGENTS.md.

Before writing:
1. Identify what changed this session (use `git diff`/`git status` and the task list) and which behavior, feature, API, or UI it affects.
2. Search existing docs for the right place to update rather than creating new files: check `documentation/README.md` (feature index), `documentation/product/behavior/chat_app_capabilities.md` (system overview), and `documentation/features/`. Prefer updating an existing doc over creating a new one.

What to write (include the relevant items):
- Motivation and background — why this exists / why it changed.
- UI details — if there is a user-facing surface (buttons, menus, flows).
- API details — endpoints, request/response shape, auth, rate limits.
- Function/feature details — key functions with `file:line` references, inputs/outputs, behavior.
- Implementation notes — important decisions, gotchas, constraints.
- Files modified — list the source files touched by this change.

Rules:
- Markdown only. Do NOT make diagrams (our docs are intended to be LLM-friendly).
- Keep it accurate to the code as written — reference real `file:line` locations, do not invent behavior.
- If you update or add a feature doc, also update the one-line entry in `documentation/README.md` so the index stays current.
- After writing, report which doc files you created or modified.

Only edit documentation/markdown files. Do not modify source code.
