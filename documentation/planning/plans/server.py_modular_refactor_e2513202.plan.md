---
name: Server.py Modular Refactor
overview: Break down the 5800+ line server.py into modular files organized in an endpoints/ folder, with database functions separated, while keeping server.py as a minimal orchestration file that handles configuration, initialization, and imports.
todos:
  - id: milestone-1
    content: Create database/ module with connection, workspaces, conversations, doubts, users, sections
    status: pending
  - id: milestone-2
    content: Create endpoints/utils.py with shared helpers (keyParser, set_keys_on_docs, etc.)
    status: pending
  - id: milestone-3
    content: Create endpoints/auth.py with authentication routes and decorators
    status: pending
  - id: milestone-4
    content: Create endpoints/static_routes.py with static file and interface routes
    status: pending
  - id: milestone-5
    content: Create endpoints/workspaces.py with workspace CRUD routes
    status: pending
  - id: milestone-6
    content: Create endpoints/conversations.py with conversation and message routes
    status: pending
  - id: milestone-7
    content: Create endpoints/documents.py with document upload/download routes
    status: pending
  - id: milestone-8
    content: Create endpoints/doubts.py with doubt clearing routes
    status: pending
  - id: milestone-9
    content: Add cancellation routes to conversations.py
    status: pending
  - id: milestone-10
    content: Create endpoints/users.py with user detail/preference routes
    status: pending
  - id: milestone-11
    content: Create endpoints/audio.py with TTS and transcription routes
    status: pending
  - id: milestone-12
    content: Create endpoints/pkb.py with all PKB routes (~700 lines)
    status: pending
  - id: milestone-13
    content: Create endpoints/prompts.py with prompt management routes
    status: pending
  - id: milestone-14
    content: Add section hidden details routes to conversations.py
    status: pending
  - id: milestone-15
    content: Add code runner route to appropriate module
    status: pending
  - id: milestone-16
    content: Refactor server.py to minimal orchestration file and create endpoints/__init__.py
    status: pending
---

# Refactoring server.py into Modular Components

## Goals

1. **Improve maintainability** - Organize ~5800 lines into logical, manageable modules
2. **Separation of concerns** - DB layer, authentication, and API endpoints in separate files
3. **Preserve functionality** - No behavioral changes, only structural reorganization
4. **Keep server.py minimal** - Only config, init, imports, and server startup

## Proposed File Structure

```javascript
chatgpt-iterative/
├── server.py                    # Minimal: config, init, register blueprints, run
├── endpoints/
│   ├── __init__.py              # Blueprint registration helper
│   ├── auth.py                  # Authentication routes + decorators
│   ├── conversations.py         # Conversation CRUD, messages, state
│   ├── workspaces.py            # Workspace CRUD operations
│   ├── documents.py             # Document upload/download/list
│   ├── doubts.py                # Doubt clearing, temporary LLM
│   ├── users.py                 # User details/preferences
│   ├── pkb.py                   # Personal Knowledge Base endpoints (~700 lines)
│   ├── audio.py                 # TTS, transcription
│   ├── prompts.py               # Prompt management
│   ├── static_routes.py         # Static files, interface, proxy
│   └── utils.py                 # Shared helpers (keyParser, set_keys_on_docs)
└── database/
    ├── __init__.py              # Export all DB functions
    ├── connection.py            # create_connection, create_table, create_tables
    ├── workspaces.py            # Workspace DB operations
    ├── conversations.py         # Conversation DB operations
    ├── doubts.py                # Doubt clearing DB operations
    ├── users.py                 # User details DB operations
    └── sections.py              # Section hidden details DB operations
```



## Implementation Approach

Use **Flask Blueprints** to modularize endpoints. Each endpoint file creates a blueprint that gets registered in `server.py`. Shared state (app, limiter, cache, conversation_cache) will be passed during blueprint registration or accessed via Flask's `current_app`.

## Challenges and Mitigations

| Challenge | Mitigation ||-----------|------------|| Circular imports | Use late imports, dependency injection patterns || Shared global state (conversation_cache, limiter) | Create a shared state module or pass via app.config || Flask decorators (@login_required, @limiter) | Define in auth.py, import where needed || Database `users_dir` global | Pass as config or use app.config |---

## Milestone 1: Create Database Module

Move all database functions to `database/` folder.

### Task 1.1: Create `database/connection.py`

- Move `create_connection()`, `create_table()`, `delete_table()`, `create_tables()` (lines 93-241)
- Accept `users_dir` as parameter or read from config

### Task 1.2: Create `database/workspaces.py`

- Move: `load_workspaces_for_user`, `addConversationToWorkspace`, `moveConversationToWorkspace`, `removeConversationFromWorkspace`, `getWorkspaceForConversation`, `getConversationsForWorkspace`, `createWorkspace`, `collapseWorkspaces`, `updateWorkspace`, `deleteWorkspace` (lines 246-1089)

### Task 1.3: Create `database/conversations.py`

- Move: `addConversation`, `checkConversationExists`, `getCoversationsForUser`, `deleteConversationForUser`, `cleanup_deleted_conversations`, `getAllCoversations`, `getConversationById`, `removeUserFromConversation` (lines 1091-1310)

### Task 1.4: Create `database/doubts.py`

- Move: `add_doubt`, `delete_doubt`, `get_doubt`, `get_doubts_for_message`, `get_doubt_history`, `get_doubt_children`, `build_doubt_tree` (lines 450-810)

### Task 1.5: Create `database/users.py`

- Move: `addUserToUserDetailsTable`, `getUserFromUserDetailsTable`, `updateUserInfoInUserDetailsTable` (lines 1313-1448)

### Task 1.6: Create `database/sections.py`

- Move: `get_section_hidden_details`, `bulk_update_section_hidden_detail` (lines 813-928)

### Task 1.7: Create `database/__init__.py`

- Export all functions for easy importing

---

## Milestone 2: Create Shared Utilities Module

### Task 2.1: Create `endpoints/utils.py`

- Move `keyParser()` (lines 1451-1491)
- Move `load_conversation()`, `conversation_cache` setup (lines 1877-1888)
- Move `set_keys_on_docs()` (lines 1914-1931)
- Move `delayed_execution()` (lines 1945-1947)
- Move `cached_get_file()` (lines 2236-2300)
- Move conversation pinned claims functions (lines 1894-1912)

---

## Milestone 3: Create Authentication Module

### Task 3.1: Create `endpoints/auth.py`

- Move `check_login()`, `login_required` decorator (lines 1622-1635)
- Move `check_credentials()` (lines 1637-1638)
- Move token functions: `generate_remember_token`, `verify_remember_token`, `store_remember_token`, `cleanup_tokens` (lines 1646-1804)
- Create Blueprint with routes:
- `@app.before_request check_remember_token` (lines 1806-1818)
- `/login` (lines 1820-1853)
- `/logout` (lines 1856-1865)
- `/get_user_info` (lines 1868-1875)

**Blueprint signature:**

```python
auth_bp = Blueprint('auth', __name__)
# Routes: /login, /logout, /get_user_info
```

---

## Milestone 4: Create Static Routes Module

### Task 4.1: Create `endpoints/static_routes.py`

- Create Blueprint with routes:
- `/favicon.ico`, `/loader.gif` (lines 1959-1969)
- `/clear_session` (lines 1936-1942)
- `/clear_locks` (lines 1973-1980)
- `/get_lock_status`, `/ensure_locks_cleared`, `/force_clear_locks` (lines 1983-2042)
- `/interface`, `/interface/<path>` (lines 2045-2098)
- `/shared/<conversation_id>` (lines 2102-2116)
- `/proxy`, `/proxy_shared` (lines 2121-2132)
- `/` index redirect (lines 2134-2138)

---

## Milestone 5: Create Workspace Endpoints

### Task 5.1: Create `endpoints/workspaces.py`

- Create Blueprint with routes:
- `/create_workspace/<domain>/<workspace_name>` POST (lines 2506-2523)
- `/list_workspaces/<domain>` GET (lines 2525-2539)
- `/update_workspace/<workspace_id>` PUT (lines 2541-2552)
- `/collapse_workspaces` POST (lines 2554-2561)
- `/delete_workspace/<domain>/<workspace_id>` DELETE (lines 2566-2583)
- `/move_conversation_to_workspace/<conversation_id>` PUT (lines 2585-2608)

---

## Milestone 6: Create Conversation Endpoints

### Task 6.1: Create `endpoints/conversations.py`

- Create Blueprint with routes:
- `/list_conversation_by_user/<domain>` GET (lines 2434-2493)
- `/create_conversation/<domain>/<workspace_id>` POST (lines 2495-2504)
- `/shared_chat/<conversation_id>` GET (lines 2623-2637)
- `/list_messages_by_conversation/<conversation_id>` GET (lines 2642-2656)
- `/list_messages_by_conversation_shareable/<conversation_id>` GET (lines 2658-2675)
- `/get_conversation_history/<conversation_id>` GET (lines 2677-2709)
- `/get_coding_hint/<conversation_id>` POST (lines 2711-2787)
- `/get_full_solution/<conversation_id>` POST (lines 2789-2865)
- `/send_message/<conversation_id>` POST (lines 2867-2919)
- `/get_conversation_details/<conversation_id>` GET (lines 2922-2955)
- `/make_conversation_stateless/<conversation_id>` DELETE (lines 2957-2970)
- `/make_conversation_stateful/<conversation_id>` PUT (lines 2972-2985)
- `/edit_message_from_conversation/...` POST (lines 2988-3002)
- `/move_messages_up_or_down/<conversation_id>` POST (lines 3004-3021)
- `/get_next_question_suggestions/<conversation_id>` GET (lines 3025-3041)
- `/clone_conversation/<conversation_id>` POST (lines 3503-3542)
- `/delete_conversation/<conversation_id>` DELETE (lines 3544-3559)
- `/delete_message_from_conversation/...` DELETE (lines 3560-3573)
- `/delete_last_message/<conversation_id>` DELETE (lines 3575-3589)
- `/set_memory_pad/<conversation_id>` POST (lines 3591-3604)
- `/fetch_memory_pad/<conversation_id>` GET (lines 3606-3618)
- `/set_flag/<conversation_id>/<flag>` POST (lines 2410-2431)
- `/get_conversation_output_docs/...` GET (lines 3620-3637)
- `/show_hide_message_from_conversation/...` POST (lines 3487-3501)
- Move `create_conversation_simple()` helper (lines 2610-2621)

---

## Milestone 7: Create Document Endpoints

### Task 7.1: Create `endpoints/documents.py`

- Create Blueprint with routes:
- `/upload_doc_to_conversation/<conversation_id>` POST (lines 2141-2173)
- `/delete_document_from_conversation/<conversation_id>/<document_id>` DELETE (lines 2175-2192)
- `/list_documents_by_conversation/<conversation_id>` GET (lines 2194-2211)
- `/download_doc_from_conversation/<conversation_id>/<doc_id>` GET (lines 2213-2234)

---

## Milestone 8: Create Doubt Endpoints

### Task 8.1: Create `endpoints/doubts.py`

- Create Blueprint with routes:
- `/clear_doubt/<conversation_id>/<message_id>` POST (lines 3045-3157)
- `/temporary_llm_action` POST (lines 3161-3270)
- `/get_doubt/<doubt_id>` GET (lines 3390-3419)
- `/delete_doubt/<doubt_id>` DELETE (lines 3421-3459)
- `/get_doubts/<conversation_id>/<message_id>` GET (lines 3461-3485)
- Move `direct_temporary_llm_action()` helper (lines 3273-3387)

---

## Milestone 9: Create Cancellation Endpoints

### Task 9.1: Add to `endpoints/conversations.py` or create `endpoints/cancellations.py`

- Routes:
- `/cancel_response/<conversation_id>` POST (lines 2304-2322)
- `/cleanup_cancellations` POST (lines 2327-2341)
- `/cancel_coding_hint/<conversation_id>` POST (lines 2343-2363)
- `/cancel_coding_solution/<conversation_id>` POST (lines 2365-2385)
- `/cancel_doubt_clearing/<conversation_id>` POST (lines 2387-2407)

---

## Milestone 10: Create User Endpoints

### Task 10.1: Create `endpoints/users.py`

- Create Blueprint with routes:
- `/get_user_detail` GET (lines 3707-3729)
- `/get_user_preference` GET (lines 3731-3753)
- `/modify_user_detail` POST (lines 3755-3790)
- `/modify_user_preference` POST (lines 3792-3827)

---

## Milestone 11: Create Audio Endpoints

### Task 11.1: Create `endpoints/audio.py`

- Create Blueprint with routes:
- `/tts/<conversation_id>/<message_id>` POST (lines 3640-3681)
- `/is_tts_done/<conversation_id>/<message_id>` POST (lines 3683-3686)
- `/transcribe` POST (lines 3688-3703)

---

## Milestone 12: Create PKB Endpoints

### Task 12.1: Create `endpoints/pkb.py`

- Move PKB helper functions: `get_pkb_db`, `get_pkb_api_for_user`, serialization functions (lines 3841-3939)
- Move global PKB state (lines 3835-3839)
- Create Blueprint with all `/pkb/*` routes (lines 3944-5323)

---

## Milestone 13: Create Prompts Endpoints

### Task 13.1: Create `endpoints/prompts.py`

- Create Blueprint with routes:
- `/get_prompts` GET (lines 5336-5391)
- `/get_prompt_by_name/<prompt_name>` GET (lines 5394-5453)
- `/create_prompt` POST (lines 5456-5537)
- `/update_prompt` PUT (lines 5540-5626)

---

## Milestone 14: Create Section Endpoints

### Task 14.1: Add to `endpoints/conversations.py` or `endpoints/sections.py`

- Routes:
- `/get_section_hidden_details` GET (lines 5629-5638)
- `/update_section_hidden_details` POST (lines 5640-5769)

---

## Milestone 15: Create Code Runner Endpoint

### Task 15.1: Add to existing module or create `endpoints/code_runner.py`

- Route: `/run_code_once` POST (lines 5325-5331)

---

## Milestone 16: Refactor server.py

### Task 16.1: Slim down `server.py`

Final server.py should contain:

1. Imports (Flask, necessary libs)
2. Flask app creation with `OurFlask` class
3. App configuration (session, CORS, limiter, cache)
4. Logger setup
5. Blueprint registration
6. `create_tables()` call
7. Main run block

**Final server.py structure (~150-200 lines):**

```python
# Imports
from flask import Flask
from endpoints import register_all_blueprints
from database import create_tables

# Flask app setup
app = OurFlask(__name__)
# ... config ...

# Register all blueprints
register_all_blueprints(app, limiter, cache)

# Initialize database
create_tables()

if __name__ == "__main__":
    app.run(...)
```



### Task 16.2: Create `endpoints/__init__.py`

```python
def register_all_blueprints(app, limiter, cache):
    from .auth import auth_bp
    from .conversations import conversations_bp
    # ... register all blueprints ...
    app.register_blueprint(auth_bp)
    app.register_blueprint(conversations_bp, url_prefix='')
    # ...
```

---

## Testing Strategy

After each milestone:

1. Run server to verify startup
2. Test affected endpoints manually or via existing tests