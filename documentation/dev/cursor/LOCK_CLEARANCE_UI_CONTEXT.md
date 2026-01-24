# Lock File Clearance Feature - Complete Context Analysis

## Executive Summary
Adding a lock file clearance button to the Chat Settings Modal requires:
1. **Backend API**: New endpoints in `server.py` for checking and clearing locks
2. **Backend Logic**: Enhanced methods in `Conversation.py` for safer lock management
3. **Frontend UI**: New button in the Chat Settings Modal in `interface/interface.html` and its event handler in `interface/chat.js`
4. **Supporting Infrastructure**: Updates to cancellation handling and lock lifecycle management

---

## Part 1: Backend - Lock File Management APIs

### A. Current Lock Architecture

**Lock Storage Location**: `storage/locks/` directory

**Lock File Naming**:
- Main conversation lock: `{conversation_id}.lock`
- Field-specific locks: `{conversation_id}_{key}.lock`
  - Keys: `""`, `"all"`, `"message_operations"`, `"memory"`, `"messages"`, `"uploaded_documents_list"`
- DocIndex locks: `{doc_id}.lock`, `{doc_id}-{top_key}.lock`

**FileLock Timeout**: Currently 600 seconds (10 minutes) - very long for streaming operations

### B. Files to Modify - Backend

#### 1. **server.py** (Main Changes Required)

**Lines 1598-1605: Server Initialization**
```python
# Current code initializes locks directory and clears on startup
locks_dir = os.path.join(folder, "locks")
os.makedirs(locks_dir, exist_ok=True)
for file in os.listdir(locks_dir):
    os.remove(os.path.join(locks_dir, file))
```
- Location: `locks_dir` variable (line 1598)
- Action needed: Keep as-is, will be used by new lock management APIs

**Lines 1877-1886: load_conversation() Function**
```python
def load_conversation(conversation_id):
    path = os.path.join(conversation_folder, conversation_id)
    conversation: Conversation = Conversation.load_local(path)
    conversation.clear_lockfile("")           # Force delete - UNSAFE
    conversation.clear_lockfile("all")
    conversation.clear_lockfile("message_operations")
    conversation.clear_lockfile("memory")
    conversation.clear_lockfile("messages")
    conversation.clear_lockfile("uploaded_documents_list")
    return conversation
```
- **Problem**: Force-deletes locks without checking if in use
- **Action needed**: Replace with safer lock wait + check logic

**Lines 1973-1979: Existing /clear_locks Endpoint**
```python
@app.route('/clear_locks')
@limiter.limit("100 per minute")
@login_required
def clear_locks():
    for file in os.listdir(locks_dir):
        os.remove(os.path.join(locks_dir, file))
    return jsonify({'result': 'locks cleared'})
```
- **Problem**: Clears ALL locks for entire server
- **Action needed**: Keep for emergency, but add conversation-specific endpoint

**Streaming Endpoints (All need finally blocks for lock cleanup)**:
- `POST /send_message/<conversation_id>` (line 2805)
- `POST /get_coding_hint/<conversation_id>` (line 2649)
- `POST /get_full_solution/<conversation_id>` (line 2727)
- `POST /clear_doubt/<conversation_id>/<message_id>` (line 2983)
- `POST /temporary_llm_action` (line 3099)
- `POST /tts/<conversation_id>/<message_id>` (line 3578)

**New Endpoints to Add**:
```python
# 1. GET /get_lock_status/<conversation_id>
# Returns comprehensive lock status information
# Response:
{
    "conversation_id": "conv_id",
    "locks_status": {
        "": bool,
        "all": bool,
        "message_operations": bool,
        "memory": bool,
        "messages": bool,
        "uploaded_documents_list": bool
    },
    "any_locked": bool,
    "stale_locks": [],  # locks > timeout age
    "can_cleanup": bool  # safe to cleanup
}

# 2. POST /ensure_locks_cleared/<conversation_id>
# Safely clears locks with pre-flight checks
# Response:
{
    "success": bool,
    "cleared": [list of cleared locks],
    "message": "string"
}

# 3. POST /force_clear_locks/<conversation_id>
# Emergency endpoint - force clears with warning
# Response:
{
    "success": bool,
    "cleared": [list of cleared locks],
    "warning": "string"
}
```

#### 2. **Conversation.py** (Main Changes Required)

**Lines 1188-1213: Current Lock Management Methods**

```python
def clear_lockfile(self, key="all"):
    """Forcefully deletes lock file - UNSAFE"""
    lock_location = self._get_lock_location(key)
    if os.path.exists(f"{lock_location}.lock"):
        os.remove(f"{lock_location}.lock")

def check_lockfile(self, key="all"):
    """Check if lock is held"""
    lock_location = self._get_lock_location(key)
    lock = FileLock(f"{lock_location}.lock")
    return lock.is_locked

def check_all_lockfiles(self):
    """Get status of all locks"""
    lock_status = {...}
    any_lock_acquired = any(lock_status.values())
    return {
        "any_lock_acquired": any_lock_acquired,
        "lock_status": lock_status
    }
```

**Methods to ADD**:
```python
# 1. wait_for_lock_release(timeout=30)
# Wait for locks to be released with timeout
# Returns: bool (True if released, False if timeout)

# 2. force_clear_all_locks()
# Force delete all lock files with verification
# Logs which files were cleared
# Returns: dict with cleared lock files

# 3. cleanup_on_cancellation()
# Safely release locks when operation is cancelled
# Ensures all locks related to current operation are released
# Returns: dict with cleanup results

# 4. is_any_lock_held()
# Quick check if ANY lock is held
# Returns: bool

# 5. get_stale_locks(age_threshold=600)
# Find locks that have been held > age_threshold seconds
# Returns: list of lock info dicts
```

**Lines 693-719: save_local() Function**
```python
def save_local(self):
    # ... initialization code ...
    lock = FileLock(f"{lock_location}.lock")
    
    # CURRENT: Simple context manager
    with lock.acquire(timeout=600):
        # ... save logic ...
```

**Needed changes**:
- Add try/except/finally block around lock acquisition
- Ensure lock is released even if exception occurs
- Log any lock release failures

**Lines 769-800: set_field() Function**
```python
def set_field(self, top_key, value, overwrite=False):
    # ... initialization code ...
    lock = FileLock(f"{lock_location}.lock")
    
    # CURRENT: Simple context manager
    with lock.acquire(timeout=600):
        # ... update logic ...
```

**Needed changes**:
- Same as save_local() - add try/except/finally

**Lines 762-767: _get_lock_location() Function**
```python
def _get_lock_location(self, key="all"):
    doc_id = self.conversation_id
    folder = self._storage
    path = Path(folder)
    lock_location = os.path.join(os.path.join(path.parent.parent, "locks"), f"{doc_id}_{key}")
    return lock_location
```
- Action: Keep as-is, already used by all lock operations

#### 3. **base.py** (Supporting Changes)

**Lines 3515-3518: Current Cancellation Dictionaries**
```python
cancellation_requests = {}
coding_hint_cancellation_requests = {}
coding_solution_cancellation_requests = {}
doubt_cancellation_requests = {}
```

**New Global to ADD**:
```python
# Global registry of active locks for monitoring/cleanup
_active_conversation_locks = {}  # {conversation_id: {lock_types: [...]}}

def register_lock(conversation_id, lock_type):
    """Register a lock in global tracking"""
    if conversation_id not in _active_conversation_locks:
        _active_conversation_locks[conversation_id] = []
    _active_conversation_locks[conversation_id].append(lock_type)

def unregister_lock(conversation_id, lock_type):
    """Unregister a lock from tracking"""
    if conversation_id in _active_conversation_locks:
        if lock_type in _active_conversation_locks[conversation_id]:
            _active_conversation_locks[conversation_id].remove(lock_type)

def release_all_conversation_locks(conversation_id):
    """Release all locks for a conversation"""
    # Implementation: Get conversation and call cleanup methods
    # Returns: dict with results
```

**Lines 2903-2910, 2984-2991: Cancellation Check Methods**
- Keep as-is, already implemented for different operation types
- Will be used by new lock cleanup logic

#### 4. **DocIndex.py** (Supporting Changes)

**Lines 1074-1104: set_doc_data() Function**
```python
def set_doc_data(self, top_key, inner_key, value, overwrite=False):
    lock_location = self._get_lock_location(top_key)
    lock = FileLock(f"{lock_location}.lock")
    with lock.acquire(timeout=600):
        # ... update logic ...
```

**Needed changes**:
- Add try/except/finally block similar to Conversation.py

---

## Part 2: Frontend - UI for Lock Clearance

### A. HTML UI Elements

#### Location: `interface/interface.html`

**Current Settings Row** (Lines 1666-1698):
```html
<div class="row mb-3">
    <div class="col">
        <button class="btn btn-primary btn-sm rounded-pill w-100" id="settings-delete-last-turn">
            <i class="fa fa-trash"></i> Delete Last Turn
        </button>
    </div>
    <div class="col">
        <button class="btn btn-primary btn-sm rounded-pill w-100" id="settings-memory-pad-text-open-button">
            <i class="bi bi-pen"></i> Memory Pad
        </button>
    </div>
    <div class="col">
        <button class="btn btn-primary btn-sm rounded-pill w-100" id="settings-pkb-modal-open-button">
            <i class="bi bi-brain"></i> Personal Memory
        </button>
    </div>
    <div class="col">
        <button class="btn btn-outline-secondary btn-sm rounded-pill w-100" id="settings-user-details-modal-open-button">
            <i class="bi bi-pen"></i> User Details
        </button>
    </div>
    <div class="col">
        <button class="btn btn-outline-secondary btn-sm rounded-pill w-100" id="settings-user-preferences-modal-open-button">
            <i class="bi bi-pen"></i> User Preferences
        </button>
    </div>
    <div class="col">
        <button class="btn btn-primary btn-sm rounded-pill w-100" id="settings-code-editor-modal-open-button">
            <i class="bi bi-code-slash"></i> Code Editor
        </button>
    </div>
    <div class="col">
        <button class="btn btn-primary btn-sm rounded-pill w-100" id="settings-prompt-manager-modal-open-button">
            <i class="bi bi-chat-left-text"></i> Prompt Manager
        </button>
    </div>
</div>
```

**New Button to ADD** (in same row, after existing buttons):
```html
<div class="col">
    <button class="btn btn-warning btn-sm rounded-pill w-100" 
            id="settings-lock-status-modal-open-button"
            title="Check and clear lock files that may be stuck">
        <i class="fa fa-lock"></i> Lock Status
    </button>
</div>
```

**Also needed**: A new modal for lock status display and management:
```html
<!-- Lock Status Modal -->
<div id="lock-status-modal" class="modal fade" tabindex="-1" aria-hidden="true" style="z-index: 1065;">
    <div class="modal-dialog">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title">
                    <i class="fa fa-lock"></i> Lock File Status
                </h5>
                <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                    <span aria-hidden="true">&times;</span>
                </button>
            </div>
            <div class="modal-body">
                <div id="lock-status-content">
                    <!-- Status will be populated here -->
                    <div class="spinner-border" role="status">
                        <span class="sr-only">Loading...</span>
                    </div>
                </div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-dismiss="modal">Close</button>
                <button type="button" class="btn btn-warning" id="lock-clear-button" style="display:none;">
                    <i class="fa fa-eraser"></i> Clear Stuck Locks
                </button>
            </div>
        </div>
    </div>
</div>
```

### B. JavaScript Event Handlers

#### Location: `interface/chat.js`

**Current Event Handler Pattern** (Lines 153-165):
```javascript
$('#settings-user-details-modal-open-button').click(function () {
    fetchUserDetail().then(function() {
        $('#user-details-modal').modal('show');
    });
});

$('#settings-user-preferences-modal-open-button').click(function () {
    fetchUserPreference().then(function() {
        $('#user-preferences-modal').modal('show');
    });
});
```

**New Event Handler to ADD** (after existing handlers):
```javascript
$('#settings-lock-status-modal-open-button').click(function () {
    // Load lock status and show modal
    const conversationId = getCurrentConversationId(); // Utility function
    
    if (!conversationId) {
        alert('No active conversation');
        return;
    }
    
    $('#lock-status-content').html(
        '<div class="spinner-border" role="status"><span class="sr-only">Loading...</span></div>'
    );
    
    fetch(`/get_lock_status/${conversationId}`, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        displayLockStatus(data);
        $('#lock-status-modal').modal('show');
    })
    .catch(error => {
        console.error('Error fetching lock status:', error);
        $('#lock-status-content').html('<div class="alert alert-danger">Error loading lock status</div>');
        $('#lock-status-modal').modal('show');
    });
});

$('#lock-clear-button').click(function () {
    const conversationId = getCurrentConversationId();
    
    if (!confirm('Clear stuck locks? This should only be done if locks are preventing normal operation.')) {
        return;
    }
    
    fetch(`/ensure_locks_cleared/${conversationId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            $('#lock-status-content').html(
                '<div class="alert alert-success">' +
                '<i class="fa fa-check"></i> Locks cleared successfully<br>' +
                'Cleared: ' + data.cleared.join(', ') +
                '</div>'
            );
            // Reload lock status after 2 seconds
            setTimeout(function() {
                $('#settings-lock-status-modal-open-button').click();
            }, 2000);
        } else {
            $('#lock-status-content').html(
                '<div class="alert alert-warning">Could not clear all locks: ' + data.message + '</div>'
            );
        }
    })
    .catch(error => {
        console.error('Error clearing locks:', error);
        $('#lock-status-content').html('<div class="alert alert-danger">Error: ' + error + '</div>');
    });
});

// Helper function to display lock status in modal
function displayLockStatus(data) {
    let html = '<div>';
    
    if (data.any_locked) {
        html += '<div class="alert alert-warning">';
        html += '<i class="fa fa-exclamation-triangle"></i> Some locks are held';
        html += '</div>';
    } else {
        html += '<div class="alert alert-success">';
        html += '<i class="fa fa-check"></i> All locks are clear';
        html += '</div>';
    }
    
    html += '<h6>Lock Status:</h6>';
    html += '<table class="table table-sm">';
    html += '<tbody>';
    
    for (const [lockKey, isLocked] of Object.entries(data.locks_status)) {
        const status = isLocked 
            ? '<span class="badge badge-warning">HELD</span>' 
            : '<span class="badge badge-success">CLEAR</span>';
        const displayKey = lockKey || '(main)';
        html += `<tr><td><code>${displayKey}</code></td><td>${status}</td></tr>`;
    }
    
    html += '</tbody></table>';
    
    if (data.stale_locks && data.stale_locks.length > 0) {
        html += '<div class="alert alert-danger">';
        html += '<strong>Stale Locks Detected:</strong>';
        html += '<ul>';
        data.stale_locks.forEach(lock => {
            html += `<li>${lock}</li>`;
        });
        html += '</ul>';
        html += '<p>These locks appear to be abandoned and can be safely cleared.</p>';
        html += '</div>';
    }
    
    html += '</div>';
    
    $('#lock-status-content').html(html);
    
    // Show clear button if there are locks held
    if (data.any_locked || (data.stale_locks && data.stale_locks.length > 0)) {
        $('#lock-clear-button').show();
    } else {
        $('#lock-clear-button').hide();
    }
}

// Helper to get current conversation ID (may already exist in codebase)
function getCurrentConversationId() {
    // Try to get from window variable or URL
    if (typeof currentConversationId !== 'undefined') {
        return currentConversationId;
    }
    // Or from DOM if available
    const urlParts = window.location.pathname.split('/');
    if (urlParts.length > 2) {
        return urlParts[2];
    }
    return null;
}
```

---

## Part 3: Integration Points - Streaming Endpoints

### Streaming Endpoints Needing Lock Cleanup (in `server.py`)

All streaming endpoints follow this pattern:

#### Current Pattern (PROBLEMATIC):
```python
def generate_response():
    for chunk in conversation(query, user_details):
        response_queue.put(chunk)
    response_queue.put("<--END-->")
    conversation.clear_cancellation()  # Insufficient

def run_queue():
    try:
        while True:
            chunk = response_queue.get()
            if chunk == "<--END-->":
                break
            yield chunk
    except GeneratorExit:
        print("Client disconnected, but continuing background processing")

return Response(run_queue(), content_type='text/plain')
```

#### New Pattern (SAFE):
```python
def generate_response():
    try:
        for chunk in conversation(query, user_details):
            response_queue.put(chunk)
        response_queue.put("<--END-->")
    finally:
        # ALWAYS cleanup locks regardless of how streaming ends
        try:
            conversation.cleanup_on_cancellation()
        except Exception as e:
            logger.error(f"Error during lock cleanup: {e}")
        conversation.clear_cancellation()

def run_queue():
    try:
        while True:
            chunk = response_queue.get()
            if chunk == "<--END-->":
                break
            yield chunk
    except GeneratorExit:
        logger.info("Client disconnected - streaming ended")
    finally:
        # Extra safety: ensure cleanup happened
        try:
            conversation.cleanup_on_cancellation()
        except Exception as e:
            logger.error(f"Error during streaming cleanup: {e}")

return Response(run_queue(), content_type='text/plain')
```

**Affected Endpoints**:
1. `/send_message/<conversation_id>` (line 2805)
2. `/get_coding_hint/<conversation_id>` (line 2649)
3. `/get_full_solution/<conversation_id>` (line 2727)
4. `/clear_doubt/<conversation_id>/<message_id>` (line 2983)
5. `/temporary_llm_action` (line 3099)
6. `/tts/<conversation_id>/<message_id>` (line 3578)

---

## Part 4: Implementation Files Summary

### Primary Files to Create/Modify:

| File | Lines/Sections | Changes | Priority |
|------|----------------|---------|----------|
| **server.py** | 1598-1605, 1877-1886, 1973-1979, 2649-2857, 2983-3095, 3099-3208, 3578-3619 | Add 3 new endpoints + update streaming endpoints + fix load_conversation | HIGH |
| **Conversation.py** | 693-719, 769-800, 1188-1213, 1956-1969 | Add 5 new methods + update save_local/set_field with try/finally blocks | HIGH |
| **interface/interface.html** | 1666-1698, (after line 1698) | Add Lock Status button + Lock Status Modal | HIGH |
| **interface/chat.js** | 153-173 | Add Lock Status modal open handler + display/clear functions | HIGH |
| **base.py** | 3515-3518 | Add global lock registry + helper functions | MEDIUM |
| **DocIndex.py** | 1074-1104 | Add try/finally blocks to set_doc_data | MEDIUM |

### Secondary Files (Reference Only):

| File | Purpose |
|------|---------|
| `.cursor/LOCKFILE_MANAGEMENT_CONTEXT.md` | Existing comprehensive analysis (reference) |
| `interface/common-chat.js` | May need updates for streaming cancellation UI |
| Other interface JS files | May reference lock status display logic |

---

## Part 5: Lock File Lifecycle Diagram

```
STREAMING REQUEST STARTS
│
├─> Acquire Lock(s)
│   ├─> save_local() uses main lock
│   ├─> set_field() uses field-specific locks
│   └─> Locks registered in global tracking
│
├─> User sends message/request
│   └─> Response generation in progress
│
├─> THREE POSSIBLE OUTCOMES:
│   │
│   ├─> [SUCCESS] Generation completes normally
│   │   └─> Locks released via __exit__ in context manager ✓
│   │
│   ├─> [CANCELLATION] User clicks Cancel/Stop button
│   │   ├─> cancellation_requests[conv_id] = True
│   │   ├─> Generator checks is_cancelled() and breaks
│   │   └─> finally block calls cleanup_on_cancellation() ✓
│   │
│   └─> [CLIENT DISCONNECT] Browser closed/page navigated away
│       ├─> Socket closes
│       ├─> GeneratorExit raised
│       └─> finally block calls cleanup_on_cancellation() ✓
│
└─> LOCK CLEANUP
    ├─> context manager __exit__ called
    ├─> FileLock released
    ├─> Lock file deleted (if properly released)
    └─> Lock unregistered from global tracking

[PROBLEM SCENARIO]
If any exception in finally block or __exit__:
└─> Lock file persists
    └─> Next request hangs on FileLock.acquire(timeout=600)
    └─> Solution: Check and clear via new API endpoints
```

---

## Part 6: Testing Scenarios

### Test Cases for Lock Clearance Feature:

1. **Check Lock Status When No Locks**
   - Click "Lock Status" button
   - Verify all locks shown as CLEAR
   - Verify "Clear Stuck Locks" button is hidden

2. **Check Lock Status During Streaming**
   - Start streaming message
   - While streaming, click "Lock Status" button in another tab
   - Verify locks shown as HELD
   - Verify "Clear Stuck Locks" button is hidden (locks still in use)

3. **Clear Stuck Locks After Cancellation**
   - Start streaming message
   - Click Cancel before completion
   - Click "Lock Status" button
   - If locks still held (edge case), verify "Clear Stuck Locks" button shown
   - Click "Clear Stuck Locks"
   - Verify confirmation dialog appears
   - Verify locks are cleared after confirmation

4. **Multiple Concurrent Conversations**
   - Open 2 conversations
   - Lock Status should be conversation-specific
   - Clearing locks in Conv1 should not affect Conv2

5. **Stale Lock Detection**
   - Manually create old lock file in storage/locks/
   - Check lock status
   - Verify stale lock detected and warning shown
   - Clear stale locks
   - Verify lock file removed

---

## Part 7: Error Handling & Edge Cases

### Potential Issues & Solutions:

| Issue | Prevention | Recovery |
|-------|-----------|----------|
| Lock cleared while still in use | Wait before clearing, show warning | Will cause data corruption - log error |
| Concurrent lock checks race condition | Use atomic operations | Retry mechanism with backoff |
| Lock file permissions issue | Verify file permissions on startup | Log and alert admin |
| Timeout during lock acquisition | Reduce timeout for non-critical ops | Manual cleanup via API |
| Lock registry out of sync | Use DB for permanent tracking | Rebuild from lock file inspection |

---

## Part 8: DRY & SOLID Principles

### Current Violations (To Fix):
1. **Lock file clearing code duplicated** in:
   - `load_conversation()` - multiple clear_lockfile() calls
   - `/clear_locks` endpoint - raw file deletion
   - Stream endpoint finally blocks - cleanup needed

2. **Lock checking logic duplicated**:
   - `check_lockfile()` method
   - `check_all_lockfiles()` method
   - Streaming generators checking locks

### Proposed Abstraction:
```python
class LockManager:
    """Centralized lock management - Single Responsibility Principle"""
    
    def __init__(self, conversation_id, locks_dir):
        self.conversation_id = conversation_id
        self.locks_dir = locks_dir
        self.tracked_locks = {}
    
    def acquire_lock(self, lock_type, timeout=60):
        """Acquire specific lock with tracking"""
        
    def release_all_locks(self):
        """Safely release all tracked locks"""
        
    def get_status(self):
        """Get comprehensive lock status"""
        
    def is_any_held(self):
        """Quick check if ANY lock held"""
        
    def wait_for_release(self, timeout=30):
        """Wait for locks to release"""
```

This eliminates duplication and centralizes lock logic per conversation.

---

## Summary: Files & Functions Reference

### Backend Implementation Checklist:

**server.py**:
- [ ] Add `GET /get_lock_status/<conversation_id>` endpoint
- [ ] Add `POST /ensure_locks_cleared/<conversation_id>` endpoint  
- [ ] Add `POST /force_clear_locks/<conversation_id>` endpoint
- [ ] Update `load_conversation()` to use `wait_for_lock_release()`
- [ ] Add finally blocks to all 6 streaming endpoints

**Conversation.py**:
- [ ] Add `wait_for_lock_release(timeout=30)` method
- [ ] Add `force_clear_all_locks()` method
- [ ] Add `cleanup_on_cancellation()` method
- [ ] Add `is_any_lock_held()` method
- [ ] Add `get_stale_locks(age_threshold)` method
- [ ] Update `save_local()` with try/finally
- [ ] Update `set_field()` with try/finally

**base.py**:
- [ ] Add `_active_conversation_locks` global dict
- [ ] Add `register_lock()` function
- [ ] Add `unregister_lock()` function
- [ ] Add `release_all_conversation_locks()` function

**DocIndex.py**:
- [ ] Update `set_doc_data()` with try/finally

### Frontend Implementation Checklist:

**interface/interface.html**:
- [ ] Add Lock Status button to settings row (line ~1699)
- [ ] Add Lock Status modal HTML (after Chat Settings modal)

**interface/chat.js**:
- [ ] Add Lock Status button click handler
- [ ] Add `displayLockStatus()` function
- [ ] Add Lock Clear button click handler
- [ ] Add `getCurrentConversationId()` helper


