# Writing System: Actionable Improvements

> Addendum to `writing_system_implementation.plan.md`. Small, high-value additions that work through existing UI (chat, artefact modal, tool system). No new pages or frameworks. Each independently shippable.

## 3. `propose_artefact_edit` as a Chat Tool (1 day)

Wrap the existing `propose_edits` endpoint as a tool the LLM can invoke from chat. User says "make section 3 shorter" → LLM calls tool → diff card renders in chat message with Accept/Reject buttons.

**Implementation:**
- Add tool definition in `code_common/tools.py` under the `artefacts` category
- Tool params: `artefact_id`, `instruction`, `selection` (optional), `include_context` (bool)
- Tool calls existing `propose_edits` logic (already in `endpoints/artefacts.py`)
- Return format: render diff card in chat (reuse artefact diff rendering)
- Accept button calls `apply_edits` endpoint

**Files:** `code_common/tools.py`, `interface/common-chat.js` (diff card rendering in chat messages)

## 4. Standing Directives on Artefacts (1 day)

A JSON array of strings stored on artefact metadata. Injected into every `propose_edits` LLM prompt for that artefact. CRUD via chat tool.

**Implementation:**
- Add `directives` field to artefact metadata schema (list of strings)
- In `propose_artefact_edits_route`: inject directives into prompt as "Standing directives (MUST be respected):\n- ..."
- Add chat tool: `manage_artefact_directives` with actions: `add`, `remove`, `list`
- Example: user says "add directive: don't modify the legal section" → LLM calls tool → directive stored

**Files:** `endpoints/artefacts.py` (inject into prompt), `code_common/tools.py` (tool def), `Conversation.py` (artefact metadata helpers)

## 5. Writing Workflow Presets for PromptWorkflowAgent (2 days)

Pre-built `workflow_prompts` lists triggered via slash command or chat.

**Presets:**

```python
WRITING_PRESETS = {
    "style-draft": [
        "Analyze the writing config (brief, audience, constraints, exemplars). Extract the key style rules and content requirements. Output a structured summary.",
        "Using the style rules and content from step 1, write the document. Follow the structure template. Include all required data points. Match the exemplar tone.",
        "Verify the draft against all constraints: word count, required sections, forbidden terms, tone match. List any violations with line numbers and fixes."
    ],
    "edit-pass": [
        "Read the document and the writing config. Identify: weak arguments, redundancy, unclear passages, tone drift, unsupported claims. List issues by priority.",
        "For each issue from step 1, propose a minimal fix. Show before/after for each change. Don't rewrite what works.",
    ],
    "fact-check": [
        "Scan the document for all factual/quantitative claims. For each, note the line number and the claim text.",
        "Cross-reference each claim against the available sources (#doc references, supporting docs). Mark each as: sourced (cite), unsourced (flag), or opinion (acceptable). List results.",
    ],
    "reduce": [
        "Identify all hedge words, passive voice, redundant phrases, and filler. List with line numbers.",
        "Remove or tighten each identified item. Preserve meaning. Show the reduction in word count.",
    ],
}
```

**Trigger:** `/write style-draft` or "run the style-draft workflow on artefact 1" in chat.

**Implementation:**
- Add presets dict in `code_common/writing_presets.py` (new, small)
- Slash command handler in `endpoints/slash_commands.py`: parse preset name, invoke `PromptWorkflowAgent` with artefact content as `user_query` + preset prompts as `workflow_prompts`
- Inject `writing_config` (if present on artefact) as preamble context

**Files:** `code_common/writing_presets.py` (new), `endpoints/slash_commands.py`, `agents/search_and_information_agents.py`

## 6. PKB as MCP Server (3-4 days)

Expose PKB operations as MCP tools so external agentic software (Claude Code, Cursor, Kiro) can query/use your knowledge base.

**Tools to expose:**
- `pkb_search(query, limit)` → returns matching claims with scores
- `pkb_get_claim(claim_id)` → full claim with source, tags, confidence
- `pkb_get_claims_by_tag(tag)` → all claims with a specific tag
- `pkb_get_conversation_claims(conversation_id)` → claims scoped to a conversation
- `pkb_add_claim(text, source?, tags?)` → create new claim (write access)

**Implementation:**
- New file: `mcp_server/pkb.py` (MCP tool definitions)
- Wraps existing PKB backend (`truth_management_system/` endpoints)
- Auth: same session/token mechanism as existing MCP server
- Register in MCP server startup

**Files:** `mcp_server/pkb.py` (new), `mcp_server/__init__.py` (register)

**Why:** Bridges the gap between your app's knowledge base and external writing tools. The folder-based workflow can query PKB directly.

## 7. Folder Template Generator — `/new-writing-project` (0.5 day)

Slash command that creates a complete writing project folder from templates.

**Implementation:**
- `/new-writing-project <name>` in chat
- Creates: `writing-projects/<name>/` with all template files:
  - `agents.md` (from the template in this plan)
  - `guidelines.md` (from the template in this plan, with TODO markers)
  - `brief.md` (empty with section headers)
  - `output.md` (empty)
  - `directives.md` (empty with instructions header)
  - `worklog.md` (empty with date header)
  - `check.py` (from the script in this plan)
  - `.writing_config.json` (default constraints)
  - `supporting_docs/` (empty folder)
- Location: configurable, default `~/writing-projects/` or server's file browser root
- Returns: confirmation with folder path

**Files:** `endpoints/slash_commands.py` (handler), template strings inline or in `templates/writing_project/`

---

## 8. Artefact-Level Conversation Threading (2-3 days)

Focused editing conversations scoped to a single artefact, separate from the main chat. Like Google Docs comment threads — users iterate on writing without polluting the main conversation.

**Motivation:** When editing a document, the conversation often becomes a mix of general discussion and specific editorial back-and-forth ("make section 3 shorter", "now fix the intro", "add a transition"). This clutters the main chat and makes it hard to resume a general conversation. Artefact threads give each document its own editing history.

**UX:**
- Clicking an artefact opens its panel (already exists). A "Thread" tab shows the artefact's conversation.
- Messages in the artefact thread automatically have the artefact content as context (no need to re-read it each time).
- The `propose_artefact_edit` and `read_artefact` tools work within the thread — edits proposed here only affect this artefact.
- Thread messages are stored separately from main chat messages but are still searchable.
- The thread has its own message input at the bottom of the artefact panel.

**Implementation:**
- Store artefact threads as a sub-list in conversation metadata: `conversation.artefact_threads[artefact_id] = [messages]`
- New endpoint: `POST /artefacts/<conversation_id>/<artefact_id>/thread` — send a message in the artefact thread, LLM responds with artefact content auto-injected as context
- New endpoint: `GET /artefacts/<conversation_id>/<artefact_id>/thread` — retrieve thread messages
- Frontend: Add thread UI in artefact modal/panel (message list + input box), reuse existing chat message rendering
- LLM prompt for thread messages includes: artefact content (always), thread history, and user's new message. No main chat context unless explicitly requested.
- Thread responses can invoke `propose_artefact_edit` tool naturally since the artefact is already in context.

**Files:** `endpoints/artefacts.py` (thread endpoints), `Conversation.py` (thread storage/retrieval), `interface/artefacts-manager.js` (thread UI), `interface/common-chat.js` (reuse message rendering)

---

## Implementation Order

| # | Item | Effort | Dependency |
|---|------|--------|-----------|
| 3 | propose_edit as chat tool | 1 day | None (DONE) |
| 8 | Artefact conversation threading | 2-3 days | #3 (uses propose_artefact_edit in threads) |
| 4 | Standing directives | 1 day | #3 (inject into same flow) |
| 7 | Folder template generator | 0.5 day | None |
| 5 | Writing workflow presets | 2 days | None (uses existing PromptWorkflowAgent) |
| 6 | PKB as MCP | 3-4 days | Existing PKB backend (ALREADY DONE) |

Total: ~8 days. Items 3, 4, 7 can ship in a single day each. Item 8 is the highest-leverage UX improvement for iterative writing.
