---
description: Turn clarified requirements into a granular implementation plan written to documentation/planning/plans/<name>.plan.md, following the AGENTS.md planning conventions.
agent: build
model: amazon-bedrock/anthropic.claude-sonnet-4-6
---

This command runs inline in your current session, so it has the full conversation context (the requirements you've been discussing). To keep the main context window lean, delegate the heavy exploration (surveying code and existing plans/docs) to sub-agents via the Task tool (e.g. the read-only explore agent) and bring back only distilled findings before writing the plan. Delegate aggressively: run several explore sub-agents in parallel and default to handing any non-trivial reading or surveying to a sub-agent rather than doing it yourself.

Produce an implementation plan for the work discussed in this session. Follow the planning guidelines in AGENTS.md: focus on quality and correctness, go wide and deep through the relevant code and docs before planning, and build incrementally.

Before writing:
1. Gather context — explore the codebase, existing plans, and documentation relevant to the task (use parallel sub-agents for surveying if the surface is large). Understand what already exists and what will be affected.
2. If key requirements are still ambiguous, ask clarification questions FIRST rather than guessing.

Structure of the plan (write in this order):
1. Requirements and goals — what we are building and why, success criteria, explicit non-goals (what NOT to do).
2. Context — relevant existing code/docs with `file:line` references, current behavior, constraints, inputs.
3. Solution approach — the chosen design, and the main alternatives considered with why they were rejected.
4. Task breakdown — granular tasks and sub-tasks in logical, incremental order, so a failure in a later task does not strand earlier work. Each task should be independently checkable.
5. Risks and challenges — controversial decisions, maintenance traps, possible UX/user-pain points, and notes that give the executor autonomy to make decisions.
6. Verification — how each part will be tested/verified (ties to `/verify`).

Output:
- Write the plan to `documentation/planning/plans/<descriptive-name>.plan.md` (extension `.plan.md` per AGENTS.md).
- Markdown only, no diagrams (our docs are LLM-friendly).
- After writing, report the file path and a short summary of the task breakdown in the chat.

Plan only — do not implement any of the tasks or edit source files. Writing the single `.plan.md` file is the only file write allowed.
