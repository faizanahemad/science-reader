---
description: Read and explore the documentation folder to provide context, details, and references from project documentation that agents can use.
agent: build
model: openrouter/anthropic/claude-sonnet-4.6
---

This command runs inline in your current session, so it has the full conversation context (the ask you've been discussing). To keep the main context window lean, delegate the heavy exploration (wide/deep file reading and searching) to sub-agents via the Task tool (e.g. the read-only explore agent) and bring back only distilled findings — do not pull raw file contents into the main thread. Delegate aggressively: run several explore sub-agents in parallel and default to handing any non-trivial reading or searching to a sub-agent rather than doing it yourself.

Read and explore the documentation folder iteratively to find relevant documentation, details, and references. This is the docs-only deep-dive counterpart to /context (which covers source code) — focus here on the documentation/ folder and markdown.
Focus on the documentation/ folder and related markdown files in the project.
Provide comprehensive summaries of relevant documentation with specific file paths and line references relevant to our ask.
Extract key information about features, implementation details, data models, and architecture from docs.
List relevant documentation files found and their purposes.
Provide direct references to documentation sections that relate to the user's query.
Do not modify or edit any file.
if there are multiple areas or tasks then analyse them independently and provide necessary docs that might be needed for each of them.

Return documentation context and file references that other agents can use in their work.

Ask the main model to write down the doc names or file names you provide so that it can be used in the conversation later.
Provide context and docs on code, code files , documentation files like markdown files and other relevant info.