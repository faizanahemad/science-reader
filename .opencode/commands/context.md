---
description: Explore the codebase and documentation and get context around what files need to be read and modified for this action or ask
agent: build
model: openrouter/anthropic/claude-sonnet-4.6
---

This command runs inline in your current session, so it has the full conversation context (the ask you've been discussing). To keep the main context window lean, delegate the heavy exploration (wide/deep file reading and searching) to sub-agents via the Task tool (e.g. the read-only explore agent) and bring back only distilled findings — do not pull raw file contents into the main thread. Delegate aggressively: run several explore sub-agents in parallel and default to handing any non-trivial reading or searching to a sub-agent rather than doing it yourself.

Explore the codebase and get context around what files need to be read and modified for this action or ask. Focus on source code and plans; for a deep walk of the documentation/ folder use the /docread command instead (only skim docs here for pointers).
Read wide and deep to get code context.
Next write the information of what you found and what all files are needed to be read or touched with information on maybe what parts of those files need to be seen.
If possible also write what information you got from those files.
Do not modify or edit any file.