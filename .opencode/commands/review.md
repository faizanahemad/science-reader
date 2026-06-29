---
description: Independently review the current diff against its stated intent and report findings as severity + file:line + evidence. The main agent dispatches an isolated reviewer sub-agent and supplies it the intent + changes.
agent: build
model: amazon-bedrock/anthropic.claude-sonnet-4-6
---

This command runs inline, so YOU (the main agent) have the full conversation context. Do NOT review the code yourself — that would be self-reviewing and would also bloat this context. Instead, dispatch the review to an isolated sub-agent via the Task tool, and relay back only its findings.

Your responsibilities as the orchestrator:
1. Assemble a complete, self-contained briefing for the reviewer, because the sub-agent starts fresh and cannot see this conversation. The briefing MUST include:
   - The stated intent / goal of the change, drawn from our conversation, the referenced plan doc, and $ARGUMENTS. Be explicit — the reviewer has no other way to know what we were trying to do.
   - Which files/areas were changed this session (so it knows where to look). Let it run `git diff`/`git status` itself for the exact contents.
   - Any constraints or decisions we made that bear on correctness.
2. Launch the reviewer with the Task tool. Prefer a read-only sub-agent (e.g. the `explore` agent, or a dedicated reviewer agent / different model if one is configured, for genuine independence). Pass it the briefing plus the reviewer instructions below.
3. When it returns, surface its findings to the user verbatim or lightly summarized. Do not soften or defend.

Reviewer instructions (include these in the Task prompt):
"You are an independent reviewer. You are NOT the author — do not assume the code is correct or defend the approach. Review the change described in the briefing with fresh eyes.
- Run `git diff` (and `git status` for untracked files) to see exactly what changed, and read the surrounding code, not just the hunks.
- Look for: correctness (logic errors, off-by-one, unhandled cases, broken contracts with callers/callees); consistency (follows existing patterns? bypasses a config-driven abstraction or hardcodes something that should flow through config?); completeness (were all callers, tests, mocks, docs updated for any changed signature/return type? was a corner cut that the intent required?); risk (side effects, error handling, secret leakage, maintenance traps); mismatch with the stated intent.
- Report each finding as: SEVERITY (blocker / major / minor / nit) + `file:line` + one-line claim + EVIDENCE (quoted code or the reasoning that proves it). Lead with blockers/majors; if a severity is empty, say so. Never a bare verdict — if you can't prove it, mark it a question.
- End with a short overall verdict: ship / fix-then-ship / rework.
- Do not edit or modify any file. You report; the author fixes."
