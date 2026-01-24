---
name: Deliberate Memory Attachment
overview: "Add mechanisms to deliberately attach specific PKB memories at runtime through: (1) global pinning for memories that should always be included, (2) conversation-level pinning for session-specific context, (3) UI controls in the PKB modal for selecting memories to use, and (4) @memory references in chat messages."
todos:
  - id: global-pin-backend
    content: Add pin_claim() and get_pinned_claims() to StructuredAPI and server endpoints
    status: completed
  - id: global-pin-frontend
    content: Add pin/unpin button to PKB modal claim cards and related JS functions
    status: completed
  - id: use-now-ui
    content: Add 'Use in next message' feature with pending attachments state and visual indicator
    status: completed
  - id: send-message-integration
    content: Modify /send_message and Conversation.reply() to accept attached_claim_ids
    status: completed
  - id: context-retrieval-merge
    content: Update _get_pkb_context() to merge pinned, attached, and auto-retrieved claims with priority
    status: completed
  - id: conversation-pin-backend
    content: Add conversation-level pinning endpoints and session state
    status: completed
  - id: at-memory-parsing
    content: Add @memory reference parsing and autocomplete in chat input
    status: completed
---

# Deliberate Memory Attachment for PKB

## Problem Statement

Currently, PKB memories are **only retrieved automatically** via hybrid search based on query relevance. There's no way to:

- Force specific memories to always be included (pinning)
- Select memories to use for a specific conversation
- Reference a memory directly in a message
- Manually override the automatic retrieval

## Solution Architecture

```mermaid
flowchart TB
    subgraph triggers [Attachment Triggers]
        GlobalPin[Global Pin via meta_json]
        ConvPin[Conversation-level Pin]
        AtMention[@memory:id reference]
        UISelect[UI "Use Now" selection]
    end
    
    subgraph storage [Storage]
        MetaJson[meta_json.pinned=true]
        SessionState[Session: pinned_claim_ids]
        MessageParse[Parse @memory refs]
    end
    
    subgraph retrieval [Context Retrieval]
        GetPinned[Get globally pinned]
        GetSession[Get session-pinned]
        GetMentioned[Get @mentioned]
        AutoSearch[Hybrid search]
    end
    
    subgraph merge [Merge Strategy]
        Dedupe[Deduplicate by claim_id]
        Prioritize[Pinned first, then auto]
        Format[Format for prompt]
    end
    
    GlobalPin --> MetaJson
    ConvPin --> SessionState
    AtMention --> MessageParse
    UISelect --> SessionState
    
    MetaJson --> GetPinned
    SessionState --> GetSession
    MessageParse --> GetMentioned
    
    GetPinned --> Dedupe
    GetSession --> Dedupe
    GetMentioned --> Dedupe
    AutoSearch --> Dedupe
    Dedupe --> Prioritize --> Format
```

---

## Phase 1: Global Pinning via meta_json

Store pinned status in the extensible `meta_json` field already present on claims.

### Backend Changes

**File: [truth_management_system/interface/structured_api.py](truth_management_system/interface/structured_api.py)**Add methods:

```python
def pin_claim(self, claim_id: str, pin: bool = True) -> ActionResult:
    """Toggle pinned status in meta_json."""
    
def get_pinned_claims(self, limit: int = 50) -> ActionResult:
    """Get all claims with meta_json.pinned = true."""
```

**File: [server.py](server.py)**Add endpoints:

```python
@app.route('/pkb/claims/<claim_id>/pin', methods=['POST'])
def pkb_pin_claim(claim_id): ...

@app.route('/pkb/pinned', methods=['GET'])
def pkb_get_pinned(): ...
```

**File: [Conversation.py](Conversation.py)**Modify `_get_pkb_context()` to:

1. First fetch pinned claims: `api.get_pinned_claims()`
2. Then run hybrid search for additional context
3. Merge results (pinned claims come first, deduplicated)

### Frontend Changes

**File: [interface/pkb-manager.js](interface/pkb-manager.js)**Add functions:

```javascript
function pinClaim(claimId, pin) { ... }
function getPinnedClaims() { ... }
```

**File: [interface/interface.html](interface/interface.html)**Add pin/unpin button to claim cards in PKB modal:

```html
<button class="btn btn-sm btn-outline-warning claim-pin-btn" data-claim-id="...">
  <i class="bi bi-pin"></i>
</button>
```

---

## Phase 2: Conversation-Level Pinning

Allow users to pin memories for the current conversation session only.

### Backend Changes

**File: [server.py](server.py)**Add conversation-scoped state:

```python
# Store in session or conversation metadata
_conversation_pinned_claims: Dict[str, List[str]] = {}  # conv_id -> [claim_ids]

@app.route('/pkb/conversation/<conv_id>/pin', methods=['POST'])
def pkb_conversation_pin(conv_id): ...

@app.route('/pkb/conversation/<conv_id>/pinned', methods=['GET'])
def pkb_conversation_get_pinned(conv_id): ...
```

**File: [Conversation.py](Conversation.py)**Modify `_get_pkb_context()` to also fetch conversation-pinned claims:

```python
def _get_pkb_context(self, user_email, query, summary, k=10, 
                     conversation_id=None) -> str:
    # 1. Get globally pinned
    # 2. Get conversation-pinned (if conv_id provided)
    # 3. Get auto-retrieved via search
    # 4. Merge and format
```



### Frontend Changes

**File: [interface/pkb-manager.js](interface/pkb-manager.js)**Add:

```javascript
function pinToConversation(convId, claimId) { ... }
function getConversationPinned(convId) { ... }
```

**File: [interface/interface.html](interface/interface.html)**Add "Pin to this conversation" option in claim actions dropdown.---

## Phase 3: UI Selection - "Use Now" Feature

Allow users to select memories from PKB modal to inject into next message.

### Frontend Changes

**File: [interface/pkb-manager.js](interface/pkb-manager.js)**Add session state and functions:

```javascript
var pendingMemoryAttachments = [];  // Claim IDs to attach to next message

function addToNextMessage(claimId) {
    pendingMemoryAttachments.push(claimId);
    updateAttachmentIndicator();
}

function clearPendingAttachments() { ... }

function getPendingAttachments() {
    return pendingMemoryAttachments;
}
```

**File: [interface/common-chat.js](interface/common-chat.js)**Modify `sendMessageCallback()`:

```javascript
// Before sending, check for pending attachments
var attachedClaimIds = PKBManager.getPendingAttachments();
if (attachedClaimIds.length > 0) {
    options.attached_claim_ids = attachedClaimIds;
    PKBManager.clearPendingAttachments();
}
```

**File: [interface/interface.html](interface/interface.html)**

- Add "Use in next message" button on claim cards
- Add visual indicator near chat input showing attached memories
- Add chip/badge showing pending attachments with remove option

### Backend Changes

**File: [server.py](server.py)**Modify `/send_message` to accept `attached_claim_ids` and pass to Conversation.**File: [Conversation.py](Conversation.py)**Modify `reply()` to accept and use `attached_claim_ids`:

```python
def reply(self, query, userData=None, attached_claim_ids=None):
    # Fetch attached claims directly by ID
    # Merge with auto-retrieved context
```

---

## Phase 4: @memory Reference in Messages

Allow users to reference memories inline in messages like `@memory:abc123`.

### Frontend Changes

**File: [interface/common-chat.js](interface/common-chat.js)**Add memory reference autocomplete (similar to @file/@folder):

```javascript
// On typing "@memory:" show search dropdown
// Parse @memory:claim_id patterns before sending
function parseMemoryReferences(text) {
    var regex = /@memory:([a-zA-Z0-9-]+)/g;
    var matches = [];
    // Extract claim IDs
    return { cleanText: text.replace(regex, ''), claimIds: matches };
}
```

**File: [interface/interface.html](interface/interface.html)**Add autocomplete dropdown for memory search (triggered by @memory:).

### Backend Changes

**File: [server.py](server.py) and [Conversation.py](Conversation.py)**

- Accept `referenced_claim_ids` extracted from message
- Fetch those claims and include prominently in context

---

## Phase 5: Context Retrieval Integration

### Modified Context Flow

**File: [Conversation.py](Conversation.py)**Update `_get_pkb_context()`:

```python
def _get_pkb_context(
    self, 
    user_email: str, 
    query: str, 
    conversation_summary: str = "",
    k: int = 10,
    conversation_id: str = None,
    attached_claim_ids: List[str] = None,
    referenced_claim_ids: List[str] = None
) -> str:
    """
    Retrieve PKB context with multiple sources:
    1. Referenced claims (@memory mentions) - highest priority
    2. Attached claims (from UI selection) - high priority
    3. Globally pinned claims - medium priority
    4. Conversation-pinned claims - medium priority
    5. Auto-retrieved via hybrid search - normal priority
    
    Returns:
        Formatted string with sections for different memory sources.
    """
    all_claims = []
    seen_ids = set()
    
    # 1. Referenced claims (explicit @memory)
    if referenced_claim_ids:
        for cid in referenced_claim_ids:
            claim = api.get_claim(cid)
            if claim.success and claim.data.claim_id not in seen_ids:
                all_claims.append(("referenced", claim.data))
                seen_ids.add(claim.data.claim_id)
    
    # 2. Attached claims (UI selection)
    if attached_claim_ids:
        # Similar logic...
    
    # 3. Globally pinned
    pinned = api.get_pinned_claims()
    # Add to all_claims with dedup...
    
    # 4. Conversation-pinned
    if conversation_id:
        # Fetch from session state...
    
    # 5. Auto-retrieved (fill remaining k slots)
    search_k = max(1, k - len(all_claims))
    if search_k > 0:
        results = api.search(query, strategy='hybrid', k=search_k)
        # Add with dedup...
    
    # Format with section headers
    return self._format_pkb_context(all_claims)

def _format_pkb_context(self, claims_with_source):
    """Format claims with source indicators."""
    lines = []
    for source, claim in claims_with_source:
        prefix = ""
        if source == "referenced":
            prefix = "[REFERENCED] "
        elif source == "pinned":
            prefix = "[PINNED] "
        lines.append(f"- {prefix}[{claim.claim_type}] {claim.statement}")
    return "\n".join(lines)
```

---

## Files to Modify

| File | Changes |

|------|---------|

| [truth_management_system/interface/structured_api.py](truth_management_system/interface/structured_api.py) | Add `pin_claim()`, `get_pinned_claims()` |

| [server.py](server.py) | New endpoints for pinning, modify `/send_message` |

| [Conversation.py](Conversation.py) | Enhanced `_get_pkb_context()` with multiple sources |

| [interface/pkb-manager.js](interface/pkb-manager.js) | Pin functions, pending attachments, UI helpers |

| [interface/common-chat.js](interface/common-chat.js) | @memory parsing, attachment handling |

| [interface/interface.html](interface/interface.html) | Pin buttons, attachment indicator, autocomplete |---

## Implementation Order

1. **Phase 1** (Global Pinning): Foundation - allows marking memories as "always include"
2. **Phase 3** (UI Selection): High value - immediate use case for "use this memory now"
3. **Phase 5** (Integration): Wire everything together in context retrieval
4. **Phase 2** (Conversation Pinning): Nice-to-have for session-level control
5. **Phase 4** (@memory mentions): Power user feature

---

## Risks and Mitigations

| Risk | Mitigation |

|------|------------|

| Too many pinned claims overwhelming context | Limit pinned claims (e.g., max 10 global, 5 per conversation) |

| @memory syntax conflicts with other @mentions | Use distinctive prefix like `@mem:` or `@recall:` |

| Performance with many attached claims | Fetch in parallel, cache pinned claims |