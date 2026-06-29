---
description: Map the full blast radius of a proposed change before editing — find every caller, test, mock, config, and doc that touches the symbol/behavior, so nothing is missed. Read-only.
agent: build
model: amazon-bedrock/anthropic.claude-sonnet-4-6
---

This command runs inline in your current session, so it has the full conversation context (the change you've been discussing). To keep the main context window lean, delegate the heavy searching across the repo to sub-agents via the Task tool (e.g. the read-only explore agent) and bring back only the impact checklist — do not pull raw file contents into the main thread. Delegate aggressively: run several explore sub-agents in parallel (e.g. one per caller-search, one for tests, one for docs) rather than searching the repo yourself.

Map the complete impact ("blast radius") of the change under discussion, BEFORE any code is edited. The goal is to ensure nothing that depends on the changed code is missed — models tend to under-survey and update only the obvious call site.

Steps:
1. Identify the exact target(s) of the change: the function(s), class(es), method signature(s), return type(s), config key(s), endpoint(s), or behavior being modified.
2. Search exhaustively across the whole repo for everything that depends on each target. Use parallel searches and sub-agents for breadth. Find:
   - All callers / usages (direct and indirect).
   - Tests and fixtures that exercise it.
   - Mocks / stubs / fakes that mirror its signature or behavior.
   - Config values, env vars, or abstractions it flows through.
   - Documentation and markdown that describe it.
   - Cross-layer consumers (e.g. if you change an embedding/search computation, find every other layer that must use the same parameters to stay consistent).
3. For a signature or return-type change, explicitly enumerate every site that must be updated in the same change to avoid breakage.

Reporting:
- Produce a checklist grouped by category (callers / tests / mocks / config / docs / cross-layer), each entry as `file:line` with a one-line note on what must change there.
- Call out the riskiest / easiest-to-miss dependencies first.
- Note anything ambiguous that needs a decision before editing.

Do not edit or modify any file. This is survey-only; report the checklist so the implementing agent can act on it.
