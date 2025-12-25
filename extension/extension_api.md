# Extension Server API Reference

**Base URL:** `http://localhost:5001`  
**Authentication:** JWT Bearer Token (except where noted)  
**Content-Type:** `application/json`

---

## Authentication

All endpoints except `/ext/health` and `/ext/auth/login` require authentication via:
```
Authorization: Bearer <token>
```

### POST `/ext/auth/login`
Login and receive JWT token.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "password"
}
```

**Response:**
```json
{
  "token": "eyJ...",
  "email": "user@example.com",
  "name": "User"
}
```

**Errors:** `400` (missing fields), `401` (invalid credentials)

---

### POST `/ext/auth/logout`
Logout (client should delete token).

**Headers:** `Authorization: Bearer <token>`

**Response:**
```json
{"message": "Logged out successfully"}
```

---

### POST `/ext/auth/verify`
Verify if token is still valid.

**Headers:** `Authorization: Bearer <token>`

**Response (valid):**
```json
{"valid": true, "email": "user@example.com"}
```

**Response (invalid):**
```json
{"valid": false, "error": "Token expired"}
```

---

## Prompts (Read-Only)

### GET `/ext/prompts`
List all available prompts.

**Response:**
```json
{
  "prompts": [
    {"name": "Short", "description": "...", "category": "..."},
    {"name": "Creative", "description": "...", "category": "..."}
  ]
}
```

---

### GET `/ext/prompts/<prompt_name>`
Get specific prompt content.

**Response:**
```json
{
  "name": "Short",
  "content": "Composed prompt content...",
  "raw_content": "Original template...",
  "description": "...",
  "category": "...",
  "tags": []
}
```

**Errors:** `404` (prompt not found), `503` (prompt library unavailable)

---

## Memories / PKB (Read-Only)

### GET `/ext/memories`
List user's memories (PKB claims).

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 50 | Max results |
| `offset` | int | 0 | Pagination offset |
| `status` | string | "active" | Filter by status |
| `claim_type` | string | null | Filter by type |

**Response:**
```json
{
  "memories": [
    {
      "claim_id": "uuid",
      "user_email": "user@example.com",
      "claim_type": "fact",
      "statement": "The capital of France is Paris",
      "context_domain": "geography",
      "status": "active",
      "confidence": 0.95,
      "created_at": "2024-01-01T00:00:00",
      "updated_at": "2024-01-01T00:00:00"
    }
  ],
  "total": 42
}
```

---

### POST `/ext/memories/search`
Search memories using hybrid search.

**Request:**
```json
{
  "query": "search text",
  "k": 10,
  "strategy": "hybrid"
}
```

**Response:**
```json
{
  "results": [
    {"claim": {...}, "score": 0.95},
    {"claim": {...}, "score": 0.87}
  ]
}
```

---

### GET `/ext/memories/<claim_id>`
Get specific memory by ID.

**Response:**
```json
{"memory": {...}}
```

**Errors:** `404` (not found)

---

### GET `/ext/memories/pinned`
Get user's globally pinned memories.

**Response:**
```json
{"memories": [...]}
```

---

## Conversations

### GET `/ext/conversations`
List user's conversations.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 50 | Max results |
| `offset` | int | 0 | Pagination offset |
| `include_temporary` | bool | true | Include temporary convs |

**Response:**
```json
{
  "conversations": [
    {
      "conversation_id": "uuid",
      "title": "Chat about Python",
      "is_temporary": false,
      "model": "openai/gpt-4o-mini",
      "prompt_name": "Short",
      "history_length": 10,
      "created_at": "2024-01-01T00:00:00",
      "updated_at": "2024-01-01T00:00:00"
    }
  ],
  "total": 15
}
```

---

### POST `/ext/conversations`
Create new conversation. **By default, deletes all temporary conversations** before creating a new one.

**Request:**
```json
{
  "title": "My Chat",
  "is_temporary": true,
  "model": "openai/gpt-4o-mini",
  "prompt_name": "Short",
  "history_length": 10,
  "delete_temporary": true
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | string | "New Chat" | Conversation title |
| `is_temporary` | bool | true | If true, will be auto-deleted on next new chat |
| `model` | string | "openai/gpt-4o-mini" | LLM model to use |
| `prompt_name` | string | null | System prompt name |
| `history_length` | int | 10 | Messages to include in context |
| `delete_temporary` | bool | true | Delete existing temporary convs first |

**Response:**
```json
{
  "conversation": {
    "conversation_id": "uuid",
    "title": "My Chat",
    ...
  },
  "deleted_temporary": 3
}
```

The `deleted_temporary` field shows how many old temporary conversations were cleaned up.

---

### GET `/ext/conversations/<conversation_id>`
Get conversation with all messages.

**Response:**
```json
{
  "conversation": {
    "conversation_id": "uuid",
    "title": "My Chat",
    "messages": [
      {
        "message_id": "uuid",
        "role": "user",
        "content": "Hello!",
        "page_context": null,
        "created_at": "..."
      },
      {
        "message_id": "uuid",
        "role": "assistant",
        "content": "Hi there!",
        "page_context": null,
        "created_at": "..."
      }
    ],
    ...
  }
}
```

**Errors:** `404` (not found)

---

### PUT `/ext/conversations/<conversation_id>`
Update conversation metadata.

**Request:**
```json
{
  "title": "New Title",
  "is_temporary": false,
  "model": "anthropic/claude-3.5-sonnet",
  "history_length": 20
}
```

**Response:**
```json
{"conversation": {...}}
```

**Errors:** `404` (not found)

---

### DELETE `/ext/conversations/<conversation_id>`
Delete conversation and all messages.

**Response:**
```json
{"message": "Deleted successfully"}
```

**Errors:** `404` (not found)

---

### POST `/ext/conversations/<conversation_id>/save`
Save a conversation (mark as non-temporary). Saved conversations won't be auto-deleted when creating new conversations.

**Response:**
```json
{
  "conversation": {
    "conversation_id": "uuid",
    "title": "My Chat",
    "is_temporary": false,
    ...
  },
  "message": "Conversation saved"
}
```

**Errors:** `404` (not found), `500` (save failed)

---

## Chat

### POST `/ext/chat/<conversation_id>`
Send message and get LLM response.

**Request:**
```json
{
  "message": "What is Python?",
  "page_context": {
    "url": "https://example.com",
    "title": "Page Title",
    "content": "Page content snippet..."
  },
  "model": "openai/gpt-4o-mini",
  "stream": false
}
```

**Response (non-streaming):**
```json
{
  "response": "Python is a programming language...",
  "message_id": "assistant-msg-uuid",
  "user_message_id": "user-msg-uuid"
}
```

**Response (streaming, `stream: true`):**
Server-Sent Events:
```
data: {"chunk": "Python"}

data: {"chunk": " is"}

data: {"chunk": " a programming language..."}

data: {"done": true, "message_id": "uuid"}
```

**Errors:** `400` (message required), `404` (conversation not found), `503` (LLM unavailable)

---

### POST `/ext/chat/<conversation_id>/message`
Add message without LLM response.

**Request:**
```json
{
  "role": "user",
  "content": "Note to self: remember this",
  "page_context": null
}
```

**Response:**
```json
{
  "message": {
    "message_id": "uuid",
    "role": "user",
    "content": "...",
    "created_at": "..."
  }
}
```

---

### DELETE `/ext/chat/<conversation_id>/messages/<message_id>`
Delete a specific message.

**Response:**
```json
{"message": "Deleted successfully"}
```

**Errors:** `404` (not found)

---

## Settings

### GET `/ext/settings`
Get user's extension settings.

**Response:**
```json
{
  "settings": {
    "default_model": "openai/gpt-4o-mini",
    "default_prompt": "Short",
    "history_length": 10,
    "auto_save_conversations": true,
    "theme": "dark"
  }
}
```

---

### PUT `/ext/settings`
Update user's extension settings.

**Request:**
```json
{
  "default_model": "anthropic/claude-3.5-sonnet",
  "history_length": 20
}
```

**Response:**
```json
{"settings": {...}}
```

---

## Utility

### GET `/ext/models`
List available LLM models.

**Response:**
```json
{
  "models": [
    {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini", "provider": "OpenAI"},
    {"id": "anthropic/claude-3.5-sonnet", "name": "Claude 3.5 Sonnet", "provider": "Anthropic"},
    ...
  ]
}
```

---

### GET `/ext/health`
Health check (no authentication required).

**Response:**
```json
{
  "status": "healthy",
  "services": {
    "prompt_lib": true,
    "pkb": true,
    "llm": true
  },
  "timestamp": "2024-01-01T00:00:00"
}
```

---

## Error Responses

All errors follow this format:
```json
{"error": "Error message description"}
```

**Common HTTP Status Codes:**
| Code | Meaning |
|------|---------|
| `400` | Bad Request - Missing or invalid parameters |
| `401` | Unauthorized - Invalid or missing token |
| `404` | Not Found - Resource doesn't exist |
| `500` | Internal Server Error |
| `503` | Service Unavailable - Dependent service not ready |

---

## Example Flow: Multi-turn Conversation

```python
import requests

BASE = "http://localhost:5001"

# 1. Login
resp = requests.post(f"{BASE}/ext/auth/login", json={
    "email": "test@example.com",
    "password": "testpass"
})
token = resp.json()["token"]
headers = {"Authorization": f"Bearer {token}"}

# 2. Create conversation
resp = requests.post(f"{BASE}/ext/conversations", json={
    "title": "Python Help",
    "model": "openai/gpt-4o-mini"
}, headers=headers)
conv_id = resp.json()["conversation"]["conversation_id"]

# 3. Send first message
resp = requests.post(f"{BASE}/ext/chat/{conv_id}", json={
    "message": "What is a decorator in Python?"
}, headers=headers)
print(resp.json()["response"])

# 4. Follow-up question (uses conversation history)
resp = requests.post(f"{BASE}/ext/chat/{conv_id}", json={
    "message": "Can you show an example?"
}, headers=headers)
print(resp.json()["response"])

# 5. Get full conversation
resp = requests.get(f"{BASE}/ext/conversations/{conv_id}", headers=headers)
print(resp.json()["conversation"]["messages"])

# 6. Cleanup
requests.delete(f"{BASE}/ext/conversations/{conv_id}", headers=headers)
requests.post(f"{BASE}/ext/auth/logout", headers=headers)
```

