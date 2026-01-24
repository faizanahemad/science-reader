# Lock File Clearance Feature - Quick Reference Map

## Visual Layout: Chat Settings Modal Button Row

```
┌─────────────────────────────────────────────────────────────────────┐
│  Chat Settings Modal                                            [X]  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  [Delete Last] [Memory Pad] [Personal Memory] [User Details]         │
│  [User Prefs]  [Code Editor] [Prompt Manager] [Lock Status] ⬅ NEW   │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

**File**: `interface/interface.html` (Lines 1666-1698)
**New Button ID**: `settings-lock-status-modal-open-button`
**Icon**: `fa fa-lock` (warning/caution style - use btn-warning)

---

## Backend Architecture Flow

```
┌──────────────────────────────┐
│  New Lock Status APIs        │
├──────────────────────────────┤
│ GET /get_lock_status/<id>    │────► Check lock state
│ POST /ensure_locks_cleared   │────► Safe clear with checks
│ POST /force_clear_locks      │────► Emergency force clear
└──────────────────────────────┘
         │
         ▼
┌──────────────────────────────┐
│  Enhanced Conversation.py    │
├──────────────────────────────┤
│ .wait_for_lock_release()     │────► Wait with timeout
│ .force_clear_all_locks()     │────► Force delete + verify
│ .cleanup_on_cancellation()   │────► Emergency cleanup
│ .is_any_lock_held()          │────► Quick status check
│ .get_stale_locks()           │────► Find abandoned locks
└──────────────────────────────┘
         │
         ▼
┌──────────────────────────────┐
│  Safe Lock Operations        │
├──────────────────────────────┤
│ try/finally in save_local()  │────► Ensure release
│ try/finally in set_field()   │────► Ensure release
│ try/finally in set_doc_data()│────► Ensure release
└──────────────────────────────┘
```

---

## Frontend - Lock Status Modal Flow

```
User clicks "Lock Status" button
         │
         ▼
┌─────────────────────────────────┐
│ Fetch: GET /get_lock_status     │
│ Display: Locks held/clear       │
│ Show: Stale locks if detected   │
│ Enable: Clear button if needed  │
└─────────────────────────────────┘
         │
    YES  │  (locks are stuck)
    ┌────┴────┐
    ▼         ▼
 [Clear]   [Skip]
    │
    ▼
┌─────────────────────────────┐
│ POST /ensure_locks_cleared  │
│ Show confirmation           │
│ Reload status after clear   │
└─────────────────────────────┘
```

---

## Critical Files Map

### Backend - What Needs Changes

```
server.py
├── Lines 1598-1605: Lock dir init (KEEP AS-IS)
├── Lines 1877-1886: load_conversation() (FIX: use wait_for_lock_release)
├── Lines 1973-1979: /clear_locks endpoint (KEEP, add notes)
├── LINES 2649-2857: Six streaming endpoints (ADD: finally blocks)
│   ├── /send_message
│   ├── /get_coding_hint
│   ├── /get_full_solution
│   ├── /clear_doubt
│   ├── /temporary_llm_action
│   └── /tts
└── NEW: Add 3 endpoints
    ├── GET /get_lock_status/<id>
    ├── POST /ensure_locks_cleared/<id>
    └── POST /force_clear_locks/<id>

Conversation.py
├── Lines 693-719: save_local() (ADD: try/finally)
├── Lines 769-800: set_field() (ADD: try/finally)
├── Lines 1188-1213: lock management methods (ENHANCE: add 5 new methods)
│   ├── ADD: wait_for_lock_release()
│   ├── ADD: force_clear_all_locks()
│   ├── ADD: cleanup_on_cancellation()
│   ├── ADD: is_any_lock_held()
│   └── ADD: get_stale_locks()
└── Lines 1956-1969: cancellation methods (KEEP AS-IS)

base.py
├── Lines 3515-3518: Cancellation dicts (KEEP AS-IS)
└── ADD: Global lock registry + 3 helper functions
    ├── ADD: _active_conversation_locks dict
    ├── ADD: register_lock()
    ├── ADD: unregister_lock()
    └── ADD: release_all_conversation_locks()

DocIndex.py
└── Lines 1074-1104: set_doc_data() (ADD: try/finally)
```

### Frontend - What Needs Changes

```
interface/interface.html
├── Lines 1666-1698: Button row (ADD: new button)
│   └── New button ID: settings-lock-status-modal-open-button
│       Icon: fa fa-lock
│       Style: btn-warning (caution color)
└── ADD: New Lock Status Modal
    ├── ID: lock-status-modal
    ├── Contains: Status display area
    └── Contains: Clear button (conditional visibility)

interface/chat.js
├── Lines 144-173: Existing button handlers (USE AS PATTERN)
└── ADD: Lock Status button handler (after line 173)
    ├── Click handler for #settings-lock-status-modal-open-button
    ├── displayLockStatus() function
    ├── Lock clear button click handler
    └── getCurrentConversationId() helper function
```

---

## Lock File Location & Naming

```
storage/
└── locks/
    ├── {conversation_id}.lock              ← Main conversation lock
    ├── {conversation_id}_.lock             ← All-keys lock
    ├── {conversation_id}_all.lock          ← All-keys lock (alt)
    ├── {conversation_id}_memory.lock       ← Memory field lock
    ├── {conversation_id}_messages.lock     ← Messages field lock
    ├── {conversation_id}_message_operations.lock
    ├── {conversation_id}_uploaded_documents_list.lock
    ├── {doc_id}.lock                       ← DocIndex main lock
    └── {doc_id}-{top_key}.lock             ← DocIndex field lock

Lock Timeout: 600 seconds (10 minutes) - Consider reducing for streaming
```

---

## Streaming Endpoint Lock Lifecycle Issue

### Problem: Locks persist after stream cancellation

```
Request Start
    │
    ├─ Acquire Lock(s)
    │
    ├─ Generate Response (in background thread/process)
    │
    ├─ Three outcomes:
    │  ├─ [OK] Completes → Lock released ✓
    │  ├─ [CANCEL] User clicks stop → Lock NOT released ✗
    │  └─ [DISCONNECT] Browser closes → Lock NOT released ✗
    │
    └─ Lock hangs for 600 seconds
        └─ Next request hangs on FileLock.acquire()
```

### Solution: Add finally blocks

```python
# CURRENT (PROBLEMATIC)
with lock.acquire(timeout=600):
    # streaming logic - may exit via exception/disconnect
    pass
# Lock may not be released!

# NEW (SAFE)
try:
    with lock.acquire(timeout=600):
        # streaming logic
        pass
finally:
    # ALWAYS cleanup, even on disconnect/exception
    conversation.cleanup_on_cancellation()
```

---

## API Response Examples

### GET /get_lock_status/{conversation_id}

```json
{
  "conversation_id": "user_8a9f7c3d",
  "locks_status": {
    "": false,
    "all": false,
    "message_operations": true,      ← HELD
    "memory": false,
    "messages": false,
    "uploaded_documents_list": false
  },
  "any_locked": true,
  "stale_locks": [
    "conversation_id_memory.lock"     ← Old lock file
  ],
  "can_cleanup": false               ← unsafe to clear
}
```

### POST /ensure_locks_cleared/{conversation_id}

```json
{
  "success": true,
  "cleared": [
    "conversation_id_memory.lock",
    "conversation_id_.lock"
  ],
  "message": "2 locks cleared successfully"
}
```

### POST /force_clear_locks/{conversation_id}

```json
{
  "success": true,
  "cleared": [
    "conversation_id_memory.lock",
    "conversation_id_all.lock"
  ],
  "warning": "Force cleared 2 locks. This may cause data corruption if locks were still in use."
}
```

---

## Implementation Order (Recommended)

### Phase 1: Backend Lock Methods (HIGH PRIORITY)
1. Add enhanced lock methods to `Conversation.py` (5 new methods)
2. Add try/finally blocks to `save_local()` and `set_field()`
3. Add global lock registry to `base.py`
4. Add try/finally to `DocIndex.py.set_doc_data()`

### Phase 2: Backend APIs (HIGH PRIORITY)
5. Add 3 new endpoints to `server.py`
6. Update `load_conversation()` in `server.py`
7. Add finally blocks to 6 streaming endpoints

### Phase 3: Frontend UI (HIGH PRIORITY)
8. Add Lock Status button to `interface/interface.html`
9. Add Lock Status modal to `interface/interface.html`
10. Add button handlers to `interface/chat.js`

### Phase 4: Testing & Polish (MEDIUM PRIORITY)
11. Test all 5 scenarios (see below)
12. Documentation/comments
13. Error handling refinements

---

## Five Test Scenarios

### Test 1: Check Status When Clear
- Precondition: No active streaming
- Action: Click "Lock Status"
- Expected: All locks CLEAR, button hidden

### Test 2: Check Status During Streaming
- Precondition: Streaming in progress
- Action: Click "Lock Status" in different browser tab
- Expected: Some locks HELD, clear button hidden

### Test 3: Clear Stuck Lock After Cancellation
- Precondition: Manually create old lock file
- Action: Click "Lock Status" → confirm clear
- Expected: Lock file deleted, status updated

### Test 4: Multiple Conversations Isolation
- Precondition: 2 conversations with locks
- Action: Clear locks in Conv1
- Expected: Conv2 locks unaffected

### Test 5: Stale Lock Detection
- Precondition: Lock file > 10 minutes old
- Action: Click "Lock Status"
- Expected: Stale lock warning shown, clearable

---

## Context Files Reference

| File | Purpose |
|------|---------|
| `.cursor/LOCKFILE_MANAGEMENT_CONTEXT.md` | Deep technical analysis (created previously) |
| `.cursor/LOCK_CLEARANCE_UI_CONTEXT.md` | Complete implementation guide (NEW - comprehensive) |
| `.cursor/LOCK_CLEARANCE_QUICK_REF.md` | This file - quick visual reference |


