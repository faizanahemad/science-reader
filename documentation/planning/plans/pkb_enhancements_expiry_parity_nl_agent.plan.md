# PKB Enhancements: Expiry System, API Parity, NL Agent, Validation

**Created:** 2026-03-09
**Status:** Implemented (pending integration testing)
**Depends On:** PKB v0.7 (`truth_management_system/`), MCP PKB server (`mcp_server/pkb.py`), LLM Tool Calling (`code_common/tools.py`), REST API (`endpoints/pkb.py`)
**Related Docs:**
- `truth_management_system/api.md` — PKB Python/REST API reference
- `documentation/features/tool_calling/README.md` — LLM tool calling framework
- `documentation/dev/MCP_ARCHITECTURE_REFERENCE.md` — MCP server patterns
- `documentation/features/truth_management_system/` — PKB feature docs

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Goals](#goals)
3. [Non-Goals](#non-goals)
4. [Item 1: Mandatory valid_to for Task/Reminder](#item-1-mandatory-valid_to-for-taskreminder)
5. [Item 2: Agentic NL Processor for PKB](#item-2-agentic-nl-processor-for-pkb)
6. [Item 3: API/MCP/Tool Parity + pkb_delete_claim](#item-3-apimcptool-parity--pkb_delete_claim)
7. [Item 4: Auto-Expiry Mechanism](#item-4-auto-expiry-mechanism)
8. [Implementation Order](#implementation-order)
9. [Files to Create/Modify](#files-to-createmodify)
10. [Testing Plan](#testing-plan)
11. [Risks and Mitigations](#risks-and-mitigations)

---

## Problem Statement

The PKB system has several gaps:

1. **No validation** on temporal fields for time-bound claim types. Tasks and reminders can be created without a deadline (`valid_to`), making them impossible to track or auto-expire.

2. **No natural language agent** for PKB. The existing `TextOrchestrator` does simple single-shot LLM intent → single API call routing. It can't handle multi-step operations ("add a reminder for July 20th and tag it as gift-shopping"), date extraction from natural language, or entity/tag management. Users want an NL interface like "add a reminder to buy gift for my friend on 20th July" that extracts dates, creates entities, links tags, and confirms the result.

3. **API surface parity gaps**. MCP server and LLM tool calling are missing `pkb_delete_claim`. MCP `pkb_autocomplete` is only in the "full" tier. The NL interface doesn't exist as an MCP/tool/API surface.

4. **No auto-expiry**. Claims with `valid_to` in the past remain `active` forever. Expired reminders and completed todos clutter search results. There's no mechanism to transition them to an expired state.

---

## Goals

1. **Enforce `valid_to` for task/reminder claim types** — Return a clarification-needed response (not a hard error) when `valid_to` is missing, guiding the caller to provide a date.
2. **Build an agentic NL processor** — An internal tool-calling loop that can handle multi-step PKB operations from natural language, exposed as MCP tool + LLM tool + REST endpoint.
3. **Achieve API parity** — Add `pkb_delete_claim` to MCP and LLM tools. Move `pkb_autocomplete` to baseline MCP tier.
4. **Add auto-expiry** — New `expired` status, background expiry check on search/API calls, exclude expired from search by default.
5. **Update documentation** — `chat_app_capabilities.md`, `api.md`, ops guidelines.

## Non-Goals

- Hard deletion of claims (remains soft-delete only)
- Scheduled cron/background daemon for expiry (we use lazy expiry on API access)
- Building a full conversation-aware PKB agent (this NL processor is stateless per invocation)
- Migrating existing `TextOrchestrator` or `ConversationDistiller` (they remain for their specific use cases)

---

## Item 1: Mandatory valid_to for Task/Reminder

### Behavior

When `claim_type` is `"task"` or `"reminder"` and `valid_to` is `None`/missing:

| Surface | Behavior |
|---------|----------|
| **StructuredAPI.add_claim()** | Return `ActionResult(success=False, action="add", errors=["valid_to is required for task/reminder claims. Please provide a deadline date."])` |
| **MCP tool `pkb_add_claim`** | Return JSON error: `{"error": "valid_to_required", "message": "Task and reminder claims require a valid_to date."}` — the calling LLM should fire the clarification tool and retry with a date. |
| **LLM tool `pkb_add_claim`** | Return error in `ToolCallResult.result` — the LLM sees this and can ask the user for a date via `ask_clarification`. |
| **REST API `POST /pkb/claims`** | Return `400 {"error": "valid_to is required for task/reminder claims"}` |
| **PKB UI modal (Add Memory)** | When claim_type dropdown changes to "task" or "reminder": show a popover/tooltip on the valid_to field saying "Required for tasks and reminders". Make valid_to field required via HTML validation. |
| **NL Processor** | The agentic NL processor should extract dates from natural language. If no date is found for task/reminder, return clarification needed. |

### Code Changes

**`truth_management_system/interface/structured_api.py`** — `add_claim()` method (~line 156):
```python
# After extracting claim_type, before Claim.create():
if claim_type in ("task", "reminder") and not valid_to:
    return ActionResult(
        success=False,
        action="add",
        object_type="claim",
        errors=["valid_to is required for task and reminder claims. Please provide a deadline date (ISO 8601 format, e.g. '2025-07-20T23:59:59Z')."],
    )
```

**`endpoints/pkb.py`** — `pkb_add_claim_route()`:
Add validation before calling `api.add_claim()`:
```python
if claim_type in ("task", "reminder") and not data.get("valid_to"):
    return jsonify({"error": "valid_to is required for task and reminder claims"}), 400
```

**`mcp_server/pkb.py`** — `pkb_add_claim` tool: Add `valid_to` parameter and pass it through. Validation is handled by StructuredAPI.

**`code_common/tools.py`** — `handle_pkb_add_claim`: Add `valid_to` parameter schema and pass through. Validation handled by StructuredAPI.

**`interface/interface.html`** — PKB Add Memory modal: JavaScript to show popover when type is task/reminder.

---

## Item 2: Agentic NL Processor for PKB

### Architecture

**Hybrid approach**: Use OpenAI-native tool calling API (via `call_llm` with `tools` parameter) as primary, with structured-JSON fallback for models that don't support tool calling.

The processor is a new module `truth_management_system/interface/nl_agent.py` containing class `PKBNLAgent`:

```
User NL command
  → PKBNLAgent.process(command, user_email)
    → Build system prompt with available tools
    → call_llm(messages, tools=internal_tools, tool_choice="auto")
    → Loop (max 5 iterations):
      → If tool_calls: execute via StructuredAPI, feed results back
      → If text response: return as NL result
    → Return PKBNLResult(response_text, actions_taken, errors)
```

### Internal Tools (available to the NL agent's LLM)

| Tool | Description | Maps to |
|------|-------------|---------|
| `search_claims` | Search PKB claims | `StructuredAPI.search()` |
| `add_claim` | Add a new claim (with all fields including valid_from, valid_to, tags, entities) | `StructuredAPI.add_claim()` |
| `edit_claim` | Edit existing claim | `StructuredAPI.edit_claim()` |
| `delete_claim` | Soft-delete a claim | `StructuredAPI.delete_claim()` |
| `get_claim` | Get claim by ID | `StructuredAPI.get_claim()` |
| `add_entity` | Create a new entity | `StructuredAPI.add_entity()` |
| `add_tag` | Create a new tag | `StructuredAPI.add_tag()` |
| `list_entities` | List user's entities | `EntityCRUD.list()` |
| `list_tags` | List user's tags | `TagCRUD.list()` |
| `pin_claim` | Pin/unpin a claim | `StructuredAPI.pin_claim()` |
| `resolve_reference` | Resolve @reference | `StructuredAPI.resolve_reference()` |

### System Prompt Structure

The system prompt should:
1. Describe the agent's role (PKB operations assistant)
2. Explain available tools and when to use each
3. Instruct on date extraction: "When the user mentions dates (e.g., 'on July 20th', 'next Friday', 'in 2 weeks'), convert to ISO 8601 format for valid_from/valid_to fields. Today's date is {current_date}."
4. Instruct on claim type inference: "Infer claim_type from context (reminder → 'reminder', todo → 'task', preference → 'preference', etc.)"
5. Instruct on multi-step operations: "You may need multiple tool calls. For example, to add a tagged reminder: first add_claim, then check if the tag exists, create if needed."
6. Instruct on response format: "After completing all operations, respond with a natural language summary of what you did."

### Safety & Iteration Design

- **Max iterations**: 5 (same as `_run_tool_loop` in Conversation.py)
- **Final iteration**: `tool_choice="none"` to force text response
- **Timeout**: 30 seconds total for the entire process
- **Fail-safe**: All StructuredAPI calls are already fail-safe (return ActionResult with errors). The agent loop catches all exceptions.
- **No partial corruption**: SQLite transactions in ClaimCRUD ensure atomicity per operation.

### Exposure (3 surfaces)

1. **MCP tool** `pkb_nl_command` in `mcp_server/pkb.py`:
   ```python
   @mcp.tool()
   def pkb_nl_command(user_email: str, command: str) -> str:
       agent = PKBNLAgent(api.for_user(user_email), keys, config)
       result = agent.process(command)
       return json.dumps({"response": result.response_text, "actions": result.actions_taken, "errors": result.errors})
   ```

2. **LLM tool** `pkb_nl_command` in `code_common/tools.py`:
   ```python
   @register_tool(name="pkb_nl_command", category="pkb", ...)
   def handle_pkb_nl_command(args, context):
       agent = PKBNLAgent(user_api, keys, config)
       result = agent.process(args["command"])
       return ToolCallResult(result=result.response_text, ...)
   ```

3. **REST endpoint** `POST /pkb/nl_command` in `endpoints/pkb.py`:
   ```python
   @pkb_bp.route("/pkb/nl_command", methods=["POST"])
   def pkb_nl_command_route():
       command = request.json.get("command", "")
       result = agent.process(command)
       return jsonify({"response": result.response_text, ...})
   ```

### File Structure

```
truth_management_system/
  interface/
    nl_agent.py          # NEW: PKBNLAgent class, internal tool definitions, agentic loop
    text_orchestration.py  # UNCHANGED (legacy, still used by ConversationDistiller)
    structured_api.py      # MODIFIED (add valid_to validation)
```

---

## Item 3: API/MCP/Tool Parity + pkb_delete_claim

### Add pkb_delete_claim

**MCP server** (`mcp_server/pkb.py`) — Add as baseline tool (not full-tier):
```python
@mcp.tool()
def pkb_delete_claim(user_email: str, claim_id: str) -> str:
    """Soft-delete (retract) a claim from the PKB."""
    api = _get_pkb_api()
    user_api = api.for_user(user_email)
    result = user_api.delete_claim(claim_id=claim_id)
    return _serialize_action_result(result)
```

**LLM tool** (`code_common/tools.py`) — Add registration:
```python
@register_tool(
    name="pkb_delete_claim",
    description="Soft-delete (retract) a claim from the PKB. The claim is not permanently removed but marked as retracted.",
    parameters={"type": "object", "properties": {"claim_id": {"type": "string"}}, "required": ["claim_id"]},
    category="pkb",
)
def handle_pkb_delete_claim(args, context):
    # Use StructuredAPI.delete_claim()
```

### Move pkb_autocomplete to baseline

In `mcp_server/pkb.py`, move the `pkb_autocomplete` tool definition from inside the `if is_full:` block to the baseline section (before the `if is_full:` check).

### Parity summary after changes

| Tool | MCP | LLM Tools | REST |
|------|:---:|:---------:|:----:|
| search | ✅ | ✅ | ✅ |
| get_claim | ✅ | ✅ | ✅ |
| add_claim | ✅ | ✅ | ✅ |
| edit_claim | ✅ | ✅ | ✅ |
| delete_claim | ✅ | ✅ | ✅ |
| resolve_reference | ✅ | ✅ | ✅ |
| get_pinned | ✅ | ✅ | ✅ |
| pin_claim | ✅ | ✅ | ✅ |
| get_claims_by_ids | ✅ | ✅ | - |
| autocomplete | ✅ | ✅ | - |
| resolve_context | ✅ | ✅ | - |
| nl_command | ✅ | ✅ | ✅ |
| list_contexts | ✅ (full) | ❌ | ✅ |
| list_entities | ✅ (full) | ❌ | ✅ |
| list_tags | ✅ (full) | ❌ | ✅ |

Note: `list_contexts`, `list_entities`, `list_tags` remain MCP full-tier only. Adding them to LLM tools is optional (available through the NL agent).

---

## Item 4: Auto-Expiry Mechanism

### New 'expired' Status

**`truth_management_system/constants.py`** — Add to `ClaimStatus`:
```python
EXPIRED = "expired"  # Time-bound claim whose valid_to has passed
```

**Update `default_search_statuses()`**:
```python
@classmethod
def default_search_statuses(cls) -> List[str]:
    return [cls.ACTIVE.value, cls.CONTESTED.value]
    # expired and retracted are excluded by default
```

**Update `all_visible_statuses()`**:
```python
@classmethod
def all_visible_statuses(cls) -> List[str]:
    return [
        cls.ACTIVE.value, cls.CONTESTED.value,
        cls.HISTORICAL.value, cls.SUPERSEDED.value,
        cls.DRAFT.value, cls.EXPIRED.value,
    ]
```

### Lazy Expiry Mechanism

Instead of a background daemon, we use **lazy expiry** — check and expire claims during API access points. This is simpler, needs no scheduler, and catches expired claims exactly when they'd be visible.

**New function in `truth_management_system/utils.py`**:
```python
def expire_stale_claims(db: PKBDatabase, user_email: Optional[str] = None) -> int:
    """Mark active claims with valid_to in the past as 'expired'.
    
    Returns the number of claims expired.
    """
    now = now_iso()
    sql = """
        UPDATE claims SET status = 'expired', updated_at = ?
        WHERE status = 'active'
          AND valid_to IS NOT NULL
          AND valid_to != ''
          AND valid_to < ?
    """
    params = [now, now]
    if user_email:
        sql += " AND user_email = ?"
        params.append(user_email)
    
    with db.transaction() as conn:
        cursor = conn.execute(sql, tuple(params))
        count = cursor.rowcount
    
    if count > 0:
        logger.info(f"Expired {count} stale claims for user={user_email or 'all'}")
    return count
```

**Call sites** (lazy, on access):

1. **`StructuredAPI.search()`** — Call `expire_stale_claims(self.db, self.user_email)` before executing search.
2. **`StructuredAPI.__init__()`** or `for_user()` — Could also call on API init, but search is more targeted.
3. **Server startup** — Call `expire_stale_claims(db)` once during `get_pkb_db()` initialization.

**Frequency guard**: To avoid running the UPDATE on every search call, add a simple time-based guard:
```python
_last_expiry_check = {}  # {user_email: timestamp}
EXPIRY_CHECK_INTERVAL = 300  # 5 minutes

def _maybe_expire_claims(self):
    import time
    now = time.time()
    key = self.user_email or "__global__"
    if now - _last_expiry_check.get(key, 0) < EXPIRY_CHECK_INTERVAL:
        return
    _last_expiry_check[key] = now
    expire_stale_claims(self.db, self.user_email)
```

### Search Behavior

- `default_search_statuses()` already returns `["active", "contested"]` — expired is excluded automatically.
- `get_claim()` returns the full Claim object including `status` — caller sees "expired" status.
- UI should show expired claims with a visual indicator (like how contested shows warnings).

### Schema Migration

The `expired` status is just a new string value in the `status` column — no schema migration needed. SQLite stores TEXT.

---

## Implementation Order

1. **Item 1b**: Add `expired` status to `ClaimStatus` enum (needed by Item 4)
2. **Item 4**: Auto-expiry mechanism (`expire_stale_claims` function + lazy check in search)
3. **Item 4b**: Verify search excludes expired by default (already handled by default_search_statuses)
4. **Item 1**: `valid_to` validation for task/reminder in StructuredAPI, REST, MCP, LLM tools, UI
5. **Item 3**: Add `pkb_delete_claim` to MCP and LLM tools, move autocomplete to baseline
6. **Item 2**: Build NL agent (largest task — depends on Items 1, 3, 4 being done)
7. **Documentation**: Update `chat_app_capabilities.md`, `api.md`, ops guidelines

### Rationale
- Items 1b and 4 are foundational (new status used everywhere)
- Item 1 validation is small and self-contained
- Item 3 parity is straightforward additions
- Item 2 (NL agent) is the largest and depends on the others being stable

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `truth_management_system/constants.py` | Modify | Add `EXPIRED` to `ClaimStatus`, update `default_search_statuses()`, `all_visible_statuses()` |
| `truth_management_system/utils.py` | Modify | Add `expire_stale_claims()` function |
| `truth_management_system/interface/structured_api.py` | Modify | Add valid_to validation in `add_claim()`, add lazy expiry call in `search()` |
| `truth_management_system/interface/nl_agent.py` | **New** | PKBNLAgent class with internal tool-calling loop |
| `mcp_server/pkb.py` | Modify | Add `pkb_delete_claim` (baseline), `pkb_nl_command`, move `pkb_autocomplete` to baseline |
| `code_common/tools.py` | Modify | Add `pkb_delete_claim` tool, add `pkb_nl_command` tool, add `valid_to` param to `pkb_add_claim` |
| `endpoints/pkb.py` | Modify | Add valid_to validation in add_claim route, add `POST /pkb/nl_command` endpoint |
| `interface/interface.html` | Modify | PKB modal: popover for valid_to on task/reminder |
| `interface/pkb-manager.js` | Modify | JS logic for type-dependent valid_to requirement |
| `documentation/product/behavior/chat_app_capabilities.md` | Modify | Document PKB expiry, NL agent, validation changes |
| `truth_management_system/api.md` | Modify | Document expired status, valid_to requirement, NL agent API |

---

## Testing Plan

### Item 1: valid_to Validation
- Test: Add task claim without valid_to → expect error with "valid_to is required"
- Test: Add task claim with valid_to → expect success
- Test: Add fact claim without valid_to → expect success (not required)
- Test: Add reminder without valid_to via REST → expect 400

### Item 2: NL Agent
- Test: "add a reminder to buy gift on 20th July" → creates reminder with correct valid_to
- Test: "what are my reminders" → returns search results filtered by claim_type=reminder
- Test: "delete the coffee preference" → searches, confirms, deletes
- Test: Invalid command → returns clarification message
- Test: Max iterations → forced text response on iteration 5

### Item 3: Parity
- Test: MCP pkb_delete_claim → soft-deletes claim
- Test: LLM tool pkb_delete_claim → soft-deletes claim
- Test: MCP pkb_autocomplete in baseline tier → works without MCP_TOOL_TIER=full

### Item 4: Auto-Expiry
- Test: Create claim with valid_to in the past → after search, status is "expired"
- Test: Create claim with valid_to in the future → stays "active"
- Test: Search → expired claims not in results by default
- Test: Search with filters `statuses=["expired"]` → only expired claims
- Test: get_claim on expired claim → shows status="expired"

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| NL agent LLM latency (5-15s per invocation) | Slow UX | Use fastest available model; set 30s timeout; cache StructuredAPI instance |
| NL agent wrong date parsing | Wrong valid_to dates | Include current date in system prompt; validate ISO 8601 format before passing to API |
| Lazy expiry misses claims if user never searches | Stale active claims | Also run expiry on server startup; consider periodic check (every 5 min in search) |
| Model doesn't support tool calling | NL agent fails | Implement structured-JSON fallback (like existing TextOrchestrator) |
| valid_to validation breaks existing bulk imports | Import failures | Only enforce for new add_claim calls; bulk_add_claims can optionally bypass |
| SQLite UPDATE performance on large claim sets | Slow expiry | The WHERE clause uses indexed columns (status, valid_to); should be fast. Add EXPLAIN QUERY PLAN verification. |
