---
description: Explore the codebase and documentation and get context around what needs to be done and what already exists and how things will be affected. then ask clarification questions.
agent: build
model: amazon-bedrock/anthropic.claude-sonnet-4-6
---

This command runs inline in your current session, so it has the full conversation context (what you've been asking for). To keep the main context window lean, delegate the heavy exploration (wide/deep file and doc reading) to sub-agents via the Task tool (e.g. the read-only explore agent) and bring back only distilled findings — then ask your clarification questions in the main thread. Delegate aggressively: run several explore sub-agents in parallel and default to handing any non-trivial reading or searching to a sub-agent rather than doing it yourself.

Explore the codebase, plans and documentation iteratively and recursively and get context around what needs to be done and what already exists and how things will be affected. then ask clarification questions.
Read wide and deep to get code and documentation context.
Next use the information of what you found and think of usability, features, implementation, users, interactions and everything else and ask clarification questions.
Clarifications can be about UX, UI, implementation, data models, features, what not to do, interactions. 
Clarifications can also be about controversial ideas or areas which might cause user pain or user discontent later on. Or areas that might make our code a maintaince nightmare.
Do not modify or edit any file.

Ask clarifications only regarding this current session's work or referenced plan doc or its implementation.