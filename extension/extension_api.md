# Extension Server API Reference (Compact)

**Base URL:** `http://localhost:5001` • **Content-Type:** `application/json` • **Auth:** `Authorization: Bearer <token>` (all endpoints except `/ext/health` and `/ext/auth/login`)

## Endpoint Index

| Category | Method | Path |
|---------|--------|------|
| Auth | POST | `/ext/auth/login` |
| Auth | POST | `/ext/auth/logout` |
| Auth | POST | `/ext/auth/verify` |
| Prompts (RO) | GET | `/ext/prompts` |
| Prompts (RO) | GET | `/ext/prompts/<prompt_name>` |
| Memories (RO) | GET | `/ext/memories` |
| Memories (RO) | POST | `/ext/memories/search` |
| Memories (RO) | GET | `/ext/memories/<claim_id>` |
| Memories (RO) | GET | `/ext/memories/pinned` |
| Conversations | GET | `/ext/conversations` |
| Conversations | POST | `/ext/conversations` |
| Conversations | GET | `/ext/conversations/<conversation_id>` |
| Conversations | PUT | `/ext/conversations/<conversation_id>` |
| Conversations | DELETE | `/ext/conversations/<conversation_id>` |
| Conversations | POST | `/ext/conversations/<conversation_id>/save` |
| Chat | POST | `/ext/chat/<conversation_id>` |
| Chat | POST | `/ext/chat/<conversation_id>/message` |
| Chat | DELETE | `/ext/chat/<conversation_id>/messages/<message_id>` |
| Settings | GET | `/ext/settings` |
| Settings | PUT | `/ext/settings` |
| Utility | GET | `/ext/models` |
| Utility | GET | `/ext/health` |
| Utility | POST | `/ext/ocr` |
| Utility | GET | `/ext/agents` |
| Workflows | GET | `/ext/workflows` |
| Workflows | POST | `/ext/workflows` |
| Workflows | GET | `/ext/workflows/<workflow_id>` |
| Workflows | PUT | `/ext/workflows/<workflow_id>` |
| Workflows | DELETE | `/ext/workflows/<workflow_id>` |
| Custom Scripts | GET | `/ext/scripts` |
| Custom Scripts | POST | `/ext/scripts` |
| Custom Scripts | GET | `/ext/scripts/<script_id>` |
| Custom Scripts | PUT | `/ext/scripts/<script_id>` |
| Custom Scripts | DELETE | `/ext/scripts/<script_id>` |
| Custom Scripts | GET | `/ext/scripts/for-url` |
| Custom Scripts | POST | `/ext/scripts/<script_id>/toggle` |
| Custom Scripts | POST | `/ext/scripts/generate` |
| Custom Scripts | POST | `/ext/scripts/validate` |

## Common Error Format

`{"error": "Error message description"}`

Common HTTP codes: `400` bad request • `401` unauthorized • `404` not found • `500` server error • `503` unavailable

## Auth

### POST `/ext/auth/login`
- **Auth**: none
- **Request**: `{ "email": string, "password": string }`
- **Response**: `{ "token": string, "email": string, "name": string }`
- **Errors**: `400` missing fields, `401` invalid credentials

### POST `/ext/auth/logout`
- **Auth**: required
- **Response**: `{ "message": "Logged out successfully" }`

### POST `/ext/auth/verify`
- **Auth**: required
- **Response (valid)**: `{ "valid": true, "email": string }`
- **Response (invalid)**: `{ "valid": false, "error": string }`

## Prompts (Read-Only)

**Extension prompt allowlist:** `/ext/prompts` only returns prompts listed in `EXTENSION_PROMPT_ALLOWLIST` in `extension_server.py`. If the allowlist is empty, all prompts from `prompts.json` are exposed. Requests for non-allowlisted prompts return `404`.

### GET `/ext/prompts`
- **Response**: `{ "prompts": [ { "name": string, "description": string, "category": string }, ... ] }` (filtered by allowlist)

### GET `/ext/prompts/<prompt_name>`
- **Response**: `{ "name": string, "content": string, "raw_content": string, "description": string, "category": string, "tags": [] }`
- **Errors**: `404` prompt not found or not allowlisted, `503` prompt library unavailable

## Memories / PKB (Read-Only)

### GET `/ext/memories`
- **Query**: `limit:int=50`, `offset:int=0`, `status:string="active"`, `claim_type:string|null`
- **Response**: `{ "memories": [ { "claim_id": string, "user_email": string, "claim_type": string, "statement": string, "context_domain": string, "status": string, "confidence": number, "created_at": string, "updated_at": string }, ... ], "total": number }`

### POST `/ext/memories/search`
- **Request**: `{ "query": string, "k": number, "strategy": "hybrid" }`
- **Response**: `{ "results": [ { "claim": object, "score": number }, ... ] }`

### GET `/ext/memories/<claim_id>`
- **Response**: `{ "memory": object }`
- **Errors**: `404` not found

### GET `/ext/memories/pinned`
- **Response**: `{ "memories": array }`

## Conversations

### GET `/ext/conversations`
- **Query**: `limit:int=50`, `offset:int=0`, `include_temporary:bool=true`
- **Response**: `{ "conversations": [ { "conversation_id": string, "title": string, "is_temporary": bool, "model": string, "prompt_name": string|null, "history_length": number, "created_at": string, "updated_at": string }, ... ], "total": number }`

### POST `/ext/conversations`
- **Note**: by default deletes all temporary conversations before creating a new one.
- **Request**: `{ "title": string="New Chat", "is_temporary": bool=true, "model": string="openai/gpt-4o-mini", "prompt_name": string|null, "history_length": number=10, "delete_temporary": bool=true }`
- **Response**: `{ "conversation": object, "deleted_temporary": number }`

### GET `/ext/conversations/<conversation_id>`
- **Response**: `{ "conversation": { "conversation_id": string, "title": string, "messages": [ { "message_id": string, "role": string, "content": string, "page_context": object|null, "created_at": string }, ... ], ... } }`
- **Errors**: `404` not found

### PUT `/ext/conversations/<conversation_id>`
- **Request**: partial update allowed (e.g. `{ "title": string, "is_temporary": bool, "model": string, "history_length": number }`)
- **Response**: `{ "conversation": object }`
- **Errors**: `404` not found

### DELETE `/ext/conversations/<conversation_id>`
- **Response**: `{ "message": "Deleted successfully" }`
- **Errors**: `404` not found

### POST `/ext/conversations/<conversation_id>/save`
- **Response**: `{ "conversation": { "is_temporary": false, ... }, "message": "Conversation saved" }`
- **Errors**: `404` not found, `500` save failed

## Chat

### POST `/ext/chat/<conversation_id>`
- **Request**: `{ "message": string, "page_context": { "url": string, "title": string, "content": string }|null, "images": string[]|null, "model": string, "stream": bool, "agent": string|null, "detail_level": number|null, "workflow_id": string|null }`
- **Response (non-streaming)**: `{ "response": string, "message_id": string, "user_message_id": string }`
- **Response (streaming)**: Server-Sent Events with `data: {"chunk": "..."}` and final `data: {"done": true, "message_id": "..."}`.
- **Errors**: `400` message required, `404` conversation not found, `503` LLM unavailable

### POST `/ext/chat/<conversation_id>/message`
- **Request**: `{ "role": string, "content": string, "page_context": object|null }`
- **Response**: `{ "message": { "message_id": string, "role": string, "content": string, "created_at": string } }`

### DELETE `/ext/chat/<conversation_id>/messages/<message_id>`
- **Response**: `{ "message": "Deleted successfully" }`
- **Errors**: `404` not found

## Settings

### GET `/ext/settings`
- **Response**: `{ "settings": { "default_model": string, "default_prompt": string, "history_length": number, "auto_save_conversations": bool, "theme": string } }`

### PUT `/ext/settings`
- **Request**: partial update allowed (e.g. `{ "default_model": string, "history_length": number }`)
- **Response**: `{ "settings": object }`
- **Errors**: `400` if `default_prompt` is not allowlisted or does not exist

## Utility

### GET `/ext/models`
- **Response**: `{ "models": [ { "id": string, "name": string, "provider": string }, ... ] }`

### GET `/ext/health`
- **Auth**: none
- **Response**: `{ "status": "healthy", "services": { "prompt_lib": bool, "pkb": bool, "llm": bool }, "timestamp": string }`

### POST `/ext/ocr`
- **Request**: `{ "images": [ "data:image/png;base64,...", ... ], "url": string|null, "title": string|null, "model": string|null }`
- **Response**: `{ "text": string, "pages": [ { "index": number, "text": string }, ... ] }`
- **Errors**: `400` images required/too many, `503` LLM unavailable

### GET `/ext/agents`
- **Response**: `{ "agents": [ string, ... ] }` (filtered by `EXTENSION_AGENT_ALLOWLIST`)

## Workflows

### GET `/ext/workflows`
- **Response**: `{ "workflows": [ { "workflow_id": string, "name": string, "steps": array, "created_at": string, "updated_at": string }, ... ] }`

### POST `/ext/workflows`
- **Request**: `{ "name": string, "steps": [ { "title": string, "prompt": string }, ... ] }`
- **Response**: `{ "workflow": object }`

### GET `/ext/workflows/<workflow_id>`
- **Response**: `{ "workflow": object }`

### PUT `/ext/workflows/<workflow_id>`
- **Request**: `{ "name": string, "steps": [ { "title": string, "prompt": string }, ... ] }`
- **Response**: `{ "workflow": object }`

### DELETE `/ext/workflows/<workflow_id>`
- **Response**: `{ "message": "Workflow deleted" }`

## Custom Scripts

### GET `/ext/scripts`
- **Query**: `enabled_only:bool=false`
- **Response**: `{ "scripts": [ { "script_id": string, "name": string, "description": string|null, "script_type": "functional"|"parsing", "match_patterns": string[], "match_type": "glob"|"regex", "enabled": bool, "version": number, "created_at": string, "updated_at": string }, ... ] }`

### POST `/ext/scripts`
- **Request**: `{ "name": string, "description": string|null, "script_type": "functional"|"parsing", "match_patterns": string[], "match_type": "glob"|"regex", "code": string, "actions": array }`
- **Response**: `{ "script": object }`

### GET `/ext/scripts/<script_id>`
- **Response**: `{ "script": { "script_id": string, "name": string, "code": string, "actions": array, ... } }`

### PUT `/ext/scripts/<script_id>`
- **Request**: partial update supported (e.g. `{ "name": string, "code": string, "enabled": bool }`)
- **Response**: `{ "script": object }`

### DELETE `/ext/scripts/<script_id>`
- **Response**: `{ "message": "Script deleted successfully" }`

### GET `/ext/scripts/for-url`
- **Query**: `url:string` (required)
- **Response**: `{ "scripts": [ { "script_id": string, "name": string, "code": string, "actions": array, ... }, ... ] }`

### POST `/ext/scripts/<script_id>/toggle`
- **Response**: `{ "script": object, "enabled": bool }`

### POST `/ext/scripts/generate`
- **Request**: `{ "description": string, "page_url": string, "page_html": string, "page_context": object, "refinement": string|null }`
- **Response**: `{ "script": { "name": string, "description": string, "match_patterns": string[], "script_type": string, "code": string, "actions": array }, "explanation": string }`
- **Errors**: `400` description required, `503` LLM unavailable

### POST `/ext/scripts/validate`
- **Request**: `{ "code": string }`
- **Response (valid)**: `{ "valid": true }`
- **Response (invalid)**: `{ "valid": false, "error": string }`

## Custom Scripts Runtime Notes (Important)

Scripts execute via a sandboxed extension page for CSP safety:
- **No direct DOM access** in user scripts (`document`, `querySelector`, etc.).
- Use `aiAssistant.dom.*` instead (content script performs DOM interactions safely).
- Common helpers: `click`, `setValue` (dispatches `input`/`change`), `type({ clearFirst, delayMs })`, `hide`, `remove`.

## Example Flow (Compact)

1) `POST /ext/auth/login` → store `token`  
2) `POST /ext/conversations` → get `conversation_id`  
3) `POST /ext/chat/<conversation_id>` (optionally `stream:true`)  
4) `GET /ext/conversations/<conversation_id>` to retrieve full messages  
5) `POST /ext/auth/logout` (client clears token)

