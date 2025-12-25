# Chrome Extension Design Document

## Project: AI Assistant Chrome Extension

**Version:** 1.0  
**Date:** December 2024  
**Status:** Design Phase

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Existing Backend APIs](#3-existing-backend-apis)
4. [Existing Web UI Capabilities](#4-existing-web-ui-capabilities)
5. [Extension Features & Requirements](#5-extension-features--requirements)
6. [New APIs to Build](#6-new-apis-to-build)
7. [Functional Requirements](#7-functional-requirements)
8. [Non-Functional Requirements](#8-non-functional-requirements)
9. [Phase Planning](#9-phase-planning)
10. [File Structure](#10-file-structure)
11. [Data Models](#11-data-models)
12. [Security Considerations](#12-security-considerations)

---

## 1. Executive Summary

### 1.1 Project Goal

Build a Chrome extension that provides AI-powered assistance for web browsing, including page content analysis, Q&A, summarization, multi-tab reading, and custom script execution. The extension reuses the existing Flask backend for LLM calls, prompts, and memories while maintaining a separate conversation storage.

### 1.2 Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Codebase** | Independent extension UI in `extension/` folder | Clean separation, independent development |
| **Server** | Same `server.py` with additional extension endpoints | Code reuse, single deployment |
| **Backend Logic** | Python-only (`extension.py`) | Extension UI is presentation-only, all logic server-side |
| **Prompts & Memories** | Shared with web UI | Consistent experience, no duplication |
| **Conversations** | Separate storage from web UI | Extension conversations don't clutter web UI |
| **Authentication** | Username/password (same system) | Single user account for both |
| **API Keys** | Server-side only | Security: keys never exposed to browser |

### 1.3 Phase 1 Scope (This Document)

- Page content extraction & Q&A
- Multi-tab reading
- Conversation management (no workspaces)
- Prompt/Memory/Model selection
- Custom scripts (Tampermonkey-like)
- Right-click context menu augmentation
- STT for input fields
- Screenshot capture
- Temporary conversations (default)

### 1.4 Phase 2 Scope (Future)

- Browser automation (click, fill, navigate)
- MCP tools integration
- Workflow orchestration
- Auto-complete in input fields (Google Docs, Gmail, etc.)

---

## 2. Architecture Overview

### 2.1 Extension UI Layout

The extension uses a **full-height sidepanel** on the right side of Chrome, activated by a floating button.

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              BROWSER WINDOW                                          │
├───────────────────────────────────────────────────────┬─────────────────────────────┤
│                                                       │                             │
│                                                       │    EXTENSION SIDEPANEL      │
│                                                       │    (Full Height - Right)    │
│                    WEB PAGE CONTENT                   │                             │
│                                                       │  ┌─────────────────────┐   │
│                                                       │  │ Conversations List  │   │
│                                                       │  ├─────────────────────┤   │
│                                                       │  │ Model/Prompt Select │   │
│                                                       │  ├─────────────────────┤   │
│                                                       │  │                     │   │
│                                                       │  │   CHAT MESSAGES     │   │
│                                                       │  │                     │   │
│                                                       │  │                     │   │
│                                                       │  ├─────────────────────┤   │
│                                                       │  │ [📎][🎤] Input [➤] │   │
│                                                       │  └─────────────────────┘   │
│                                               ┌───┐   │                             │
│                                               │ ⚡ │◄──┼── Floating Toggle Button   │
│                                               └───┘   │    (Bottom Right Corner)   │
└───────────────────────────────────────────────────────┴─────────────────────────────┘
```

**UI Activation:**
- A floating button (⚡) appears in the **bottom right corner** of every page
- Clicking it opens the **full-height sidepanel** on the right side
- The sidepanel occupies the full height of the browser viewport
- Clicking the button again closes the sidepanel
- The sidepanel width is ~350-400px (responsive)

### 2.2 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CHROME EXTENSION                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │   Popup     │  │  Sidepanel  │  │   Content   │  │   Background    │ │
│  │    UI       │  │    UI       │  │   Scripts   │  │ Service Worker  │ │
│  │ (Settings,  │  │ (Main Chat  │  │ (Page DOM,  │  │ (Multi-tab,     │ │
│  │  Quick Act) │  │  Interface) │  │  Injection) │  │  API calls)     │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └────────┬────────┘ │
│         │                │                │                   │          │
│         └────────────────┴────────────────┴───────────────────┘          │
│                                    │                                      │
│                            Message Passing                                │
│                                    │                                      │
└────────────────────────────────────┼────────────────────────────────────┘
                                     │
                              HTTPS API Calls
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         FLASK SERVER (server.py)                         │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                    Extension API Layer (New)                        │ │
│  │  /ext/auth  /ext/chat  /ext/conversations  /ext/scripts  etc.     │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                    │                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ extension.py │  │ Existing     │  │ Existing     │  │ Existing     │ │
│  │ (New Logic)  │  │ Prompts      │  │ PKB/Memory   │  │ LLM Calls    │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                         Storage Layer                               │ │
│  │  extension_conversations.db  │  users.db  │  prompts  │  pkb.db   │ │
│  │  (NEW - Extension Only)      │  (Shared)  │  (Shared) │  (Shared) │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Data Flow

```
User Action (Extension)
        │
        ▼
┌───────────────────┐
│ Content Script    │──── Extracts page content, screenshots
│ (Page Context)    │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Background Worker │──── Coordinates multi-tab, makes API calls
│ (Service Worker)  │
└─────────┬─────────┘
          │
          ▼ HTTPS POST
┌───────────────────┐
│ Flask Server      │──── Processes request, calls LLM, stores data
│ /ext/chat         │
└─────────┬─────────┘
          │
          ▼ Streaming Response
┌───────────────────┐
│ Sidepanel UI      │──── Renders response, updates conversation
│ (Chat Interface)  │
└───────────────────┘
```

---

## 3. Existing Backend APIs

### 3.1 Authentication APIs (Reusable)

| Endpoint | Method | Description | Extension Use |
|----------|--------|-------------|---------------|
| `/login` | POST | Username/password login | ✅ Direct use with token adaptation |
| `/logout` | GET | Logout user | ✅ Direct use |
| `/get_user_info` | GET | Get current user email/name | ✅ Direct use |

### 3.2 Prompt Management APIs (Reusable)

| Endpoint | Method | Description | Extension Use |
|----------|--------|-------------|---------------|
| `/get_prompts` | GET | List all prompts with metadata | ✅ Direct use |
| `/get_prompt_by_name/<name>` | GET | Get specific prompt content | ✅ Direct use |
| `/create_prompt` | POST | Create new prompt | ✅ Direct use |
| `/update_prompt` | PUT | Update existing prompt | ✅ Direct use |

### 3.3 Memory/PKB APIs (Reusable)

| Endpoint | Method | Description | Extension Use |
|----------|--------|-------------|---------------|
| `/pkb/claims` | GET | List claims with filters | ✅ For memory selection |
| `/pkb/claims` | POST | Add new claim | ✅ Direct use |
| `/pkb/claims/<id>` | PUT | Update claim | ✅ Direct use |
| `/pkb/claims/<id>` | DELETE | Delete claim | ✅ Direct use |
| `/pkb/claims/bulk` | POST | Bulk add claims | ✅ Direct use |
| `/pkb/search` | POST | Semantic search claims | ✅ For relevant memory retrieval |
| `/pkb/relevant_context` | POST | Get relevant claims for query | ✅ Auto-attach memories |
| `/pkb/pinned` | GET | Get pinned claims | ✅ For memory attachment |
| `/pkb/entities` | GET | List entities | ✅ For memory browsing |
| `/pkb/tags` | GET | List tags | ✅ For memory browsing |

### 3.4 User Preferences APIs (Reusable)

| Endpoint | Method | Description | Extension Use |
|----------|--------|-------------|---------------|
| `/get_user_detail` | GET | Get user details | ✅ For context |
| `/get_user_preference` | GET | Get user preferences | ✅ For settings |
| `/modify_user_detail` | POST | Update user details | ✅ Direct use |
| `/modify_user_preference` | POST | Update preferences | ✅ Direct use |

### 3.5 LLM/Chat APIs (Need Extension Variants)

| Endpoint | Method | Description | Extension Use |
|----------|--------|-------------|---------------|
| `/send_message/<conv_id>` | POST | Send message, stream response | ⚠️ Need extension variant |
| `/temporary_llm_action` | POST | Ephemeral LLM action | ✅ For quick actions |
| `/transcribe` | POST | Audio to text | ✅ For STT |

### 3.6 Utility APIs (Reusable)

| Endpoint | Method | Description | Extension Use |
|----------|--------|-------------|---------------|
| `/proxy` | GET | Proxy external URLs | ✅ For fetching web content |

### 3.7 APIs NOT Used by Extension

| Endpoint | Reason |
|----------|--------|
| `/create_workspace/*` | Extension has no workspaces |
| `/list_workspaces/*` | Extension has no workspaces |
| `/move_conversation_to_workspace/*` | Extension has no workspaces |
| `/upload_doc_to_conversation/*` | Extension handles docs differently |
| `/tts/*` | Not in Phase 1 |
| `/get_coding_hint/*` | Not needed |
| `/get_full_solution/*` | Not needed |
| `/clear_doubt/*` | Extension uses temporary LLM |

---

## 4. Existing Web UI Capabilities

### 4.1 Conversation Management

| Feature | Web UI Implementation | Extension Equivalent |
|---------|----------------------|---------------------|
| Create conversation | `ConversationManager.createConversation()` | Yes - simpler version |
| Delete conversation | `ConversationManager.deleteConversation(id)` | Yes |
| Clone conversation | `ConversationManager.cloneConversation(id)` | No - not needed |
| List conversations | `WorkspaceManager.loadConversationsWithWorkspaces()` | Yes - flat list, no workspaces |
| Stateless mode | `ConversationManager.statelessConversation(id)` | Yes - default for extension |
| Stateful mode | `ConversationManager.statefulConversation(id)` | Yes - opt-in save |

### 4.2 Message Operations

| Feature | Web UI Implementation | Extension Equivalent |
|---------|----------------------|---------------------|
| Send message | `ChatManager.sendMessage()` | Yes |
| Delete last message | `ChatManager.deleteLastMessage(id)` | Yes |
| Edit message | `saveMessageEditText()` | Yes |
| Load messages | `ChatManager.loadMessages(id)` | Yes |
| Streaming response | SSE/fetch streaming | Yes |

### 4.3 Settings & Preferences

| Feature | Web UI Location | Extension Equivalent |
|---------|-----------------|---------------------|
| Model selection | Settings modal dropdown | Yes - in extension settings |
| Response length | Settings modal | Yes - history length setting |
| Use web search | Settings modal checkbox | Yes |
| Detailed answers | Settings modal checkbox | Yes |
| Think step by step | Settings modal checkbox | Yes |

### 4.4 Context Menu Actions

| Feature | Web UI (`ContextMenuManager`) | Extension Equivalent |
|---------|------------------------------|---------------------|
| Explain | `TempLLMManager.executeAction('explain')` | Yes - on any page |
| Critique | `TempLLMManager.executeAction('critique')` | Yes |
| Expand | `TempLLMManager.executeAction('expand')` | Yes |
| ELI5 | `TempLLMManager.executeAction('eli5')` | Yes |
| Ask temporarily | `TempLLMManager.openTempChatModal()` | Yes |
| Search Google | Native link | Yes |
| Copy | Native copy | Yes |

### 4.5 Memory/PKB Management

| Feature | Web UI (`PKBManager`) | Extension Equivalent |
|---------|----------------------|---------------------|
| List claims | Modal with pagination | Yes - selection list |
| Add claim | Form in modal | No - use web UI |
| Edit claim | Inline edit | No - use web UI |
| Delete claim | Delete button | No - use web UI |
| Search claims | Search input | Yes - for selection |
| Pin claims | Pin button | Yes - attach to conversation |
| Memory proposals | Review modal | No - use web UI |

### 4.6 Prompt Management

| Feature | Web UI (`PromptManager`) | Extension Equivalent |
|---------|-------------------------|---------------------|
| List prompts | Modal with list | Yes - selection dropdown |
| View prompt | Editor panel | No - use web UI |
| Create prompt | Form | No - use web UI |
| Edit prompt | Editor | No - use web UI |
| Select prompt | Click to select | Yes - for conversation |

### 4.7 Document Handling

| Feature | Web UI | Extension Equivalent |
|---------|--------|---------------------|
| Upload PDF | Modal form | No - extension reads pages directly |
| Upload audio | File input | No - use native page content |
| Document indexing | Server-side | No - live page extraction |

---

## 5. Extension Features & Requirements

### 5.1 Phase 1 Features

#### 5.1.1 Core Chat

| Feature | Description | Priority |
|---------|-------------|----------|
| **Conversation List** | Flat list of conversations (no workspaces) | P0 |
| **New Chat** | Create new conversation | P0 |
| **Delete Chat** | Remove conversation | P0 |
| **Send Message** | Send user message, receive streaming LLM response | P0 |
| **Delete Messages** | Remove specific messages from conversation | P1 |
| **Temporary Mode** | Default: conversations not saved unless explicitly saved | P0 |
| **Save Conversation** | Opt-in: save temporary conversation permanently | P0 |
| **History Length** | Setting: number of messages to include in context | P0 |
| **Conversation Summary** | Auto-summarize old messages to reduce context | P1 |

#### 5.1.2 Page Interaction

| Feature | Description | Priority |
|---------|-------------|----------|
| **Read Current Page** | Extract text content from active tab | P0 |
| **Read Multiple Tabs** | Extract content from selected tabs | P0 |
| **Screenshot Capture** | Capture visible viewport as image | P1 |
| **Selection Context** | Use selected text as query context | P0 |
| **Page Summarization** | One-click summarize current page | P0 |
| **Page Q&A** | Ask questions about page content | P0 |

#### 5.1.3 Personalization

| Feature | Description | Priority |
|---------|-------------|----------|
| **Model Selection** | Choose LLM model for conversation | P0 |
| **Prompt Selection** | Select system prompt from library | P0 |
| **Memory Selection** | Attach specific memories to conversation | P1 |
| **Auto Memory Retrieval** | Automatically retrieve relevant memories | P1 |

#### 5.1.4 Context Menu (Right-Click)

| Feature | Description | Priority |
|---------|-------------|----------|
| **Explain Selection** | Explain selected text | P0 |
| **Summarize Selection** | Summarize selected text | P0 |
| **Translate Selection** | Translate selected text | P1 |
| **Custom Action** | Run selected prompt on selection | P1 |
| **Answer Modal** | Show response in floating modal | P0 |

#### 5.1.5 Custom Scripts (Tampermonkey-like)

| Feature | Description | Priority |
|---------|-------------|----------|
| **Script Storage** | Store custom JS scripts per domain | P0 |
| **Script Execution** | Run scripts on matching pages | P0 |
| **Script Editor** | Create/edit scripts (use web UI) | P1 |
| **Script Versioning** | Track script versions | P2 |
| **LLM-Assisted Creation** | Generate scripts via LLM | P1 |

#### 5.1.6 Voice Input

| Feature | Description | Priority |
|---------|-------------|----------|
| **STT Recording** | Record audio from microphone | P0 |
| **Transcription** | Convert audio to text via server | P0 |
| **Voice Commands** | Trigger actions via voice | P2 |

#### 5.1.7 Authentication

| Feature | Description | Priority |
|---------|-------------|----------|
| **Login** | Username/password authentication | P0 |
| **Session Management** | Token-based session | P0 |
| **Logout** | Clear session | P0 |
| **Auto-Login** | Remember session across browser restarts | P1 |

### 5.2 Phase 2 Features (Future)

| Feature | Description |
|---------|-------------|
| **Browser Automation** | Click elements, fill forms, navigate |
| **MCP Tools** | Access MCP tool ecosystem |
| **Workflow Orchestration** | Multi-step automated workflows |
| **Auto-Complete** | LLM-powered autocomplete in text fields |
| **Form Filling Assistance** | AI-assisted form completion |
| **Gmail/Docs Integration** | Deep integration with Google apps |

---

## 6. New APIs to Build

### 6.1 Extension Authentication

```
POST /ext/auth/login
    Request:  { "username": "...", "password": "..." }
    Response: { "token": "...", "user": { "email": "...", "name": "..." } }

POST /ext/auth/logout
    Headers:  Authorization: Bearer <token>
    Response: { "success": true }

GET /ext/auth/verify
    Headers:  Authorization: Bearer <token>
    Response: { "valid": true, "user": { ... } }
```

### 6.2 Extension Conversations

```
GET /ext/conversations
    Headers:  Authorization: Bearer <token>
    Query:    ?limit=50&offset=0
    Response: { "conversations": [...], "total": 100 }

POST /ext/conversations
    Headers:  Authorization: Bearer <token>
    Request:  { "title": "...", "is_temporary": true }
    Response: { "conversation_id": "...", "created_at": "..." }

GET /ext/conversations/<id>
    Headers:  Authorization: Bearer <token>
    Response: { "conversation_id": "...", "messages": [...], "metadata": {...} }

DELETE /ext/conversations/<id>
    Headers:  Authorization: Bearer <token>
    Response: { "success": true }

PUT /ext/conversations/<id>
    Headers:  Authorization: Bearer <token>
    Request:  { "title": "...", "is_temporary": false }  # Save permanently
    Response: { "conversation_id": "...", "updated_at": "..." }

POST /ext/conversations/<id>/summarize
    Headers:  Authorization: Bearer <token>
    Request:  { "message_count": 10 }  # Summarize oldest N messages
    Response: { "summary": "...", "messages_summarized": 10 }
```

### 6.3 Extension Chat

```
POST /ext/chat/<conversation_id>
    Headers:  Authorization: Bearer <token>
    Request:  {
        "message": "...",
        "page_content": "...",           # Optional: current page text
        "page_url": "...",               # Optional: current page URL
        "page_title": "...",             # Optional: current page title
        "screenshot_base64": "...",      # Optional: viewport screenshot
        "multi_tab_content": [           # Optional: content from multiple tabs
            { "url": "...", "title": "...", "content": "..." }
        ],
        "selected_text": "...",          # Optional: user selection
        "model": "gpt-4",                # Model selection
        "prompt_name": "default",        # System prompt to use
        "memory_ids": ["...", "..."],    # Attached memory IDs
        "history_length": 10,            # Number of messages to include
        "settings": {
            "use_web_search": false,
            "detailed_answer": true,
            "think_step_by_step": false
        }
    }
    Response: Streaming text/plain (SSE-like)

POST /ext/chat/quick
    Headers:  Authorization: Bearer <token>
    Request:  {
        "action": "explain|summarize|translate|critique|expand|eli5",
        "text": "...",
        "context": "...",                # Optional: surrounding context
        "model": "gpt-4"
    }
    Response: Streaming text/plain
```

### 6.4 Extension Messages

```
DELETE /ext/conversations/<conv_id>/messages/<msg_id>
    Headers:  Authorization: Bearer <token>
    Response: { "success": true }

PUT /ext/conversations/<conv_id>/messages/<msg_id>
    Headers:  Authorization: Bearer <token>
    Request:  { "content": "..." }
    Response: { "message_id": "...", "updated_at": "..." }
```

### 6.5 Custom Scripts

```
GET /ext/scripts
    Headers:  Authorization: Bearer <token>
    Query:    ?domain=mail.google.com  # Optional filter
    Response: { "scripts": [...] }

POST /ext/scripts
    Headers:  Authorization: Bearer <token>
    Request:  {
        "name": "Gmail Email Extractor",
        "domain": "mail.google.com",
        "match_patterns": ["https://mail.google.com/*"],
        "script": "function extract() { ... }",
        "enabled": true,
        "created_with_llm": false
    }
    Response: { "script_id": "...", "created_at": "..." }

GET /ext/scripts/<id>
    Headers:  Authorization: Bearer <token>
    Response: { "script_id": "...", "script": "...", ... }

PUT /ext/scripts/<id>
    Headers:  Authorization: Bearer <token>
    Request:  { "script": "...", "enabled": true }
    Response: { "script_id": "...", "updated_at": "..." }

DELETE /ext/scripts/<id>
    Headers:  Authorization: Bearer <token>
    Response: { "success": true }

POST /ext/scripts/generate
    Headers:  Authorization: Bearer <token>
    Request:  {
        "domain": "mail.google.com",
        "description": "Extract email sender, subject, and body",
        "sample_html": "..."  # Optional: sample page HTML
    }
    Response: { "suggested_script": "...", "explanation": "..." }
```

### 6.6 Page Content Helpers

```
POST /ext/page/extract
    Headers:  Authorization: Bearer <token>
    Request:  {
        "html": "...",
        "url": "...",
        "extraction_type": "auto|readability|full|structured"
    }
    Response: { "content": "...", "title": "...", "metadata": {...} }
```

### 6.7 Settings Sync

```
GET /ext/settings
    Headers:  Authorization: Bearer <token>
    Response: { 
        "default_model": "gpt-4",
        "default_prompt": "default",
        "history_length": 10,
        "auto_save": false,
        ...
    }

PUT /ext/settings
    Headers:  Authorization: Bearer <token>
    Request:  { "default_model": "claude-3-opus", ... }
    Response: { "success": true }
```

---

## 7. Functional Requirements

### 7.1 User Authentication

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-AUTH-01 | User can login with username/password | Login form, success redirects to main UI |
| FR-AUTH-02 | Failed login shows error message | Clear error for invalid credentials |
| FR-AUTH-03 | Session persists across browser restart | Token stored in chrome.storage |
| FR-AUTH-04 | User can logout | Clears token, shows login screen |
| FR-AUTH-05 | Expired token prompts re-login | Automatic redirect to login |

### 7.2 Conversation Management

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-CONV-01 | User can create new conversation | New conversation appears in list |
| FR-CONV-02 | User can delete conversation | Conversation removed from list and storage |
| FR-CONV-03 | User can view conversation list | Scrollable list with title and date |
| FR-CONV-04 | User can switch between conversations | Messages load when selected |
| FR-CONV-05 | Conversations are temporary by default | Not saved unless explicitly saved |
| FR-CONV-06 | User can save temporary conversation | Conversation persists after browser close |
| FR-CONV-07 | Conversation shows unread indicator | Visual indicator for new messages |

### 7.3 Messaging

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-MSG-01 | User can send text message | Message appears in chat, response streams back |
| FR-MSG-02 | Response streams in real-time | Progressive display of LLM response |
| FR-MSG-03 | User can stop response generation | Stop button cancels streaming |
| FR-MSG-04 | User can delete individual messages | Message removed from conversation |
| FR-MSG-05 | User can edit sent messages | Edit mode, save updates message |
| FR-MSG-06 | Messages render markdown | Code blocks, lists, bold, links rendered |
| FR-MSG-07 | Code blocks have copy button | One-click copy code |
| FR-MSG-08 | History length is configurable | Settings control how many messages sent to LLM |

### 7.4 Page Interaction

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-PAGE-01 | Extension can read current page content | Text extracted accurately |
| FR-PAGE-02 | User can include page content in message | Page content attached to message |
| FR-PAGE-03 | User can capture viewport screenshot | Screenshot captured and attached |
| FR-PAGE-04 | User can select text to include | Selected text used as context |
| FR-PAGE-05 | User can read multiple tabs | Tab selector, content from multiple tabs |
| FR-PAGE-06 | One-click page summarization | Summary generated and displayed |
| FR-PAGE-07 | Custom scripts run on matching pages | Scripts execute automatically |

### 7.5 Context Menu

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-CTX-01 | Right-click shows extension menu | Custom menu items appear |
| FR-CTX-02 | "Explain" generates explanation | Explanation shown in modal |
| FR-CTX-03 | "Summarize" generates summary | Summary shown in modal |
| FR-CTX-04 | Modal is draggable/resizable | User can position modal |
| FR-CTX-05 | Modal has copy button | One-click copy response |
| FR-CTX-06 | User can continue conversation in modal | Multi-turn in modal context |

### 7.6 Personalization

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-PERS-01 | User can select LLM model | Dropdown with available models |
| FR-PERS-02 | User can select system prompt | Dropdown with prompt names |
| FR-PERS-03 | User can attach memories | Multi-select memory list |
| FR-PERS-04 | Relevant memories auto-suggested | Based on conversation context |
| FR-PERS-05 | Settings persist across sessions | Stored in extension storage |

### 7.7 Voice Input

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-VOICE-01 | User can record audio | Microphone button, recording indicator |
| FR-VOICE-02 | Audio transcribed to text | Text appears in input field |
| FR-VOICE-03 | Transcription shows loading state | Spinner during transcription |

### 7.8 Custom Scripts

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-SCRIPT-01 | Scripts stored per domain | Script associated with URL pattern |
| FR-SCRIPT-02 | Scripts run automatically on match | Script executes on page load |
| FR-SCRIPT-03 | Scripts can be enabled/disabled | Toggle without deleting |
| FR-SCRIPT-04 | Script editor accessible (web UI) | Link to web UI for editing |
| FR-SCRIPT-05 | LLM can generate scripts | Prompt describes extraction, LLM writes code |

---

## 8. Non-Functional Requirements

### 8.1 Performance

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-PERF-01 | Page content extraction | < 500ms for typical page |
| NFR-PERF-02 | UI response time | < 100ms for user actions |
| NFR-PERF-03 | LLM response start | < 2s to first token |
| NFR-PERF-04 | Extension memory usage | < 50MB idle, < 100MB active |
| NFR-PERF-05 | Extension load time | < 1s to interactive |

### 8.2 Security

| ID | Requirement | Implementation |
|----|-------------|----------------|
| NFR-SEC-01 | API keys never in extension | All LLM calls via server |
| NFR-SEC-02 | Auth tokens encrypted | Use chrome.storage secure storage |
| NFR-SEC-03 | HTTPS only | All API calls over HTTPS |
| NFR-SEC-04 | Content script isolation | Minimal permissions, sandboxed |
| NFR-SEC-05 | Script execution sandboxed | Custom scripts in isolated context |

### 8.3 Reliability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-REL-01 | Extension uptime | 99.9% (browser dependent) |
| NFR-REL-02 | Server error handling | Graceful degradation, retry logic |
| NFR-REL-03 | Offline behavior | Show cached data, queue actions |
| NFR-REL-04 | Data persistence | No data loss on browser crash |

### 8.4 Usability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-USE-01 | First-use onboarding | < 2 minutes to send first message |
| NFR-USE-02 | Keyboard shortcuts | Common actions have shortcuts |
| NFR-USE-03 | Accessibility | WCAG 2.1 AA compliance |
| NFR-USE-04 | Responsive UI | Works in popup and sidepanel |

### 8.5 Compatibility

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-COMPAT-01 | Chrome version | Chrome 120+ (Manifest V3) |
| NFR-COMPAT-02 | Server compatibility | Works with existing server |
| NFR-COMPAT-03 | Mobile | Designed for desktop, basic mobile |

---

## 9. Phase Planning

### 9.1 Phase 1: MVP (Target: 4-6 weeks)

#### Week 1-2: Foundation

| Task | Description | Deliverable |
|------|-------------|-------------|
| Extension boilerplate | Manifest V3, folder structure | Working extension shell |
| Auth API | `/ext/auth/*` endpoints | Token-based auth working |
| Auth UI | Login form in popup | User can login |
| Basic conversation API | `/ext/conversations` CRUD | Conversations persist |
| Service worker setup | Background script scaffold | Message passing works |

#### Week 3-4: Core Chat

| Task | Description | Deliverable |
|------|-------------|-------------|
| Chat API | `/ext/chat/<id>` streaming | LLM responses stream |
| Sidepanel UI | Chat interface | Send/receive messages |
| Content script | Page text extraction | Read current page |
| Page context | Include page in message | Page Q&A works |
| Temporary mode | Default temporary conversations | No accidental saves |

#### Week 5-6: Personalization & Polish

| Task | Description | Deliverable |
|------|-------------|-------------|
| Model selection | Dropdown in UI, server routing | Multiple models work |
| Prompt selection | Fetch prompts, apply to conversation | Prompts work |
| Memory selection | List memories, attach to conversation | Memories work |
| Context menu | Right-click actions | Explain/summarize works |
| Settings UI | Preferences panel | Settings persist |
| Multi-tab | Tab selector, aggregate content | Multi-page Q&A |

### 9.2 Phase 1.5: Stabilization (2 weeks)

| Task | Description |
|------|-------------|
| Bug fixes | Address issues from testing |
| Performance optimization | Reduce latency, memory usage |
| Error handling | Graceful failures, user feedback |
| Documentation | User guide, API docs |
| Security audit | Review permissions, data handling |

### 9.3 Phase 2: Advanced Features (Future)

| Feature | Estimated Effort |
|---------|------------------|
| Custom scripts (Tampermonkey) | 2 weeks |
| Browser automation | 3-4 weeks |
| MCP tools | 2-3 weeks |
| Workflow orchestration | 3-4 weeks |
| Auto-complete | 2-3 weeks |
| Gmail/Docs deep integration | 2-3 weeks |

---

## 10. File Structure

### 10.1 Extension Folder Structure

```
extension/
├── EXTENSION_DESIGN.md          # This document
├── README.md                     # Setup and usage instructions
│
├── manifest.json                 # Chrome extension manifest (V3)
│
├── popup/                        # Popup UI (click on extension icon)
│   ├── popup.html
│   ├── popup.js
│   └── popup.css
│
├── sidepanel/                    # Sidepanel UI (main chat interface)
│   ├── sidepanel.html
│   ├── sidepanel.js
│   └── sidepanel.css
│
├── content_scripts/              # Scripts injected into web pages
│   ├── extractor.js              # Page content extraction
│   ├── context_menu.js           # Right-click menu handler
│   ├── modal.js                  # Response modal overlay
│   └── custom_scripts.js         # Tampermonkey-like script runner
│
├── background/                   # Service worker
│   └── service-worker.js         # Multi-tab, API calls, messaging
│
├── shared/                       # Shared code between contexts
│   ├── api.js                    # API client for server calls
│   ├── auth.js                   # Authentication handling
│   ├── storage.js                # Chrome storage wrapper
│   ├── constants.js              # Shared constants
│   └── utils.js                  # Utility functions
│
├── assets/                       # Static assets
│   ├── icons/
│   │   ├── icon16.png
│   │   ├── icon32.png
│   │   ├── icon48.png
│   │   └── icon128.png
│   └── styles/
│       └── common.css
│
└── lib/                          # Third-party libraries (if needed)
    └── (bundled libs)
```

### 10.2 Server-Side Additions

```
chatgpt-iterative/
├── server.py                     # Add /ext/* endpoints
├── extension.py                  # NEW: Extension-specific logic
│
├── extension_storage/            # NEW: Extension data storage
│   ├── conversations/            # Extension conversations (separate from web)
│   └── scripts/                  # Custom scripts storage
│
└── (existing folders unchanged)
```

### 10.3 Database Schema Additions

```sql
-- New table in users.db or new extension.db

CREATE TABLE ExtensionConversations (
    conversation_id TEXT PRIMARY KEY,
    user_email TEXT NOT NULL,
    title TEXT,
    is_temporary BOOLEAN DEFAULT TRUE,
    model TEXT DEFAULT 'gpt-4',
    prompt_name TEXT,
    history_length INTEGER DEFAULT 10,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    summary TEXT,  -- Compressed summary of old messages
    FOREIGN KEY (user_email) REFERENCES UserDetails(user_email)
);

CREATE TABLE ExtensionMessages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,  -- 'user' or 'assistant'
    content TEXT NOT NULL,
    page_context TEXT,  -- JSON: { url, title, content_snippet }
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES ExtensionConversations(conversation_id)
);

CREATE TABLE ExtensionConversationMemories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,  -- Reference to PKB claim
    attached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES ExtensionConversations(conversation_id)
);

CREATE TABLE CustomScripts (
    script_id TEXT PRIMARY KEY,
    user_email TEXT NOT NULL,
    name TEXT NOT NULL,
    domain TEXT NOT NULL,
    match_patterns TEXT NOT NULL,  -- JSON array
    script TEXT NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    created_with_llm BOOLEAN DEFAULT FALSE,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_email) REFERENCES UserDetails(user_email)
);

CREATE TABLE ExtensionSettings (
    user_email TEXT PRIMARY KEY,
    default_model TEXT DEFAULT 'gpt-4',
    default_prompt TEXT DEFAULT 'default',
    history_length INTEGER DEFAULT 10,
    auto_save BOOLEAN DEFAULT FALSE,
    settings_json TEXT,  -- Additional settings as JSON
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_email) REFERENCES UserDetails(user_email)
);
```

---

## 11. Data Models

### 11.1 Extension Conversation

```typescript
interface ExtensionConversation {
    conversation_id: string;
    user_email: string;
    title: string;
    is_temporary: boolean;
    model: string;
    prompt_name: string | null;
    history_length: number;
    created_at: string;  // ISO timestamp
    updated_at: string;
    summary: string | null;
    messages: ExtensionMessage[];
    attached_memories: string[];  // claim_ids
}
```

### 11.2 Extension Message

```typescript
interface ExtensionMessage {
    message_id: string;
    conversation_id: string;
    role: 'user' | 'assistant';
    content: string;
    page_context: PageContext | null;
    created_at: string;
}

interface PageContext {
    url: string;
    title: string;
    content_snippet: string;  // First 500 chars
    full_content_hash: string;  // For deduplication
}
```

### 11.3 Custom Script

```typescript
interface CustomScript {
    script_id: string;
    user_email: string;
    name: string;
    domain: string;
    match_patterns: string[];
    script: string;
    enabled: boolean;
    created_with_llm: boolean;
    version: number;
    created_at: string;
    updated_at: string;
}
```

### 11.4 Chat Request

```typescript
interface ExtensionChatRequest {
    message: string;
    page_content?: string;
    page_url?: string;
    page_title?: string;
    screenshot_base64?: string;
    multi_tab_content?: TabContent[];
    selected_text?: string;
    model: string;
    prompt_name: string;
    memory_ids: string[];
    history_length: number;
    settings: ChatSettings;
}

interface TabContent {
    url: string;
    title: string;
    content: string;
}

interface ChatSettings {
    use_web_search: boolean;
    detailed_answer: boolean;
    think_step_by_step: boolean;
}
```

---

## 12. Security Considerations

### 12.1 Authentication

| Concern | Mitigation |
|---------|------------|
| Token storage | Use `chrome.storage.session` for sensitive data |
| Token expiry | Short-lived tokens (1 hour), refresh mechanism |
| CSRF | Token-based auth, no cookies |
| Brute force | Rate limiting on login endpoint |

### 12.2 Content Script Security

| Concern | Mitigation |
|---------|------------|
| XSS from pages | Content scripts run in isolated world |
| Data exfiltration | Minimal permissions, explicit user consent |
| Injection attacks | Sanitize all page content before use |

### 12.3 Custom Scripts

| Concern | Mitigation |
|---------|------------|
| Malicious scripts | Scripts run in isolated context |
| Credential theft | Scripts can't access extension storage |
| Page manipulation | User explicitly enables scripts |
| LLM-generated code | Human review before production use |

### 12.4 API Security

| Concern | Mitigation |
|---------|------------|
| API key exposure | Keys only on server, never in extension |
| Man-in-the-middle | HTTPS only, certificate pinning |
| Injection | Parameterized queries, input validation |
| Rate limiting | Per-user rate limits on all endpoints |

### 12.5 Permission Model

```json
// manifest.json permissions (minimal)
{
    "permissions": [
        "activeTab",           // Read current tab only when clicked
        "storage",             // Store settings and cache
        "sidePanel",           // Sidepanel UI
        "contextMenus",        // Right-click menu
        "scripting"            // Inject content scripts
    ],
    "optional_permissions": [
        "tabs",                // Multi-tab reading (request when needed)
        "history"              // Optional: recent pages
    ],
    "host_permissions": [
        "https://your-server.com/*"  // API calls
    ]
}
```

---

## Appendix A: API Summary Table

| Category | Endpoint | Method | New/Existing |
|----------|----------|--------|--------------|
| **Auth** | `/ext/auth/login` | POST | New |
| **Auth** | `/ext/auth/logout` | POST | New |
| **Auth** | `/ext/auth/verify` | GET | New |
| **Conversations** | `/ext/conversations` | GET | New |
| **Conversations** | `/ext/conversations` | POST | New |
| **Conversations** | `/ext/conversations/<id>` | GET | New |
| **Conversations** | `/ext/conversations/<id>` | DELETE | New |
| **Conversations** | `/ext/conversations/<id>` | PUT | New |
| **Conversations** | `/ext/conversations/<id>/summarize` | POST | New |
| **Chat** | `/ext/chat/<id>` | POST | New |
| **Chat** | `/ext/chat/quick` | POST | New |
| **Messages** | `/ext/conversations/<id>/messages/<mid>` | DELETE | New |
| **Messages** | `/ext/conversations/<id>/messages/<mid>` | PUT | New |
| **Scripts** | `/ext/scripts` | GET | New |
| **Scripts** | `/ext/scripts` | POST | New |
| **Scripts** | `/ext/scripts/<id>` | GET | New |
| **Scripts** | `/ext/scripts/<id>` | PUT | New |
| **Scripts** | `/ext/scripts/<id>` | DELETE | New |
| **Scripts** | `/ext/scripts/generate` | POST | New |
| **Page** | `/ext/page/extract` | POST | New |
| **Settings** | `/ext/settings` | GET | New |
| **Settings** | `/ext/settings` | PUT | New |
| **Prompts** | `/get_prompts` | GET | Existing |
| **Prompts** | `/get_prompt_by_name/<name>` | GET | Existing |
| **Memory** | `/pkb/claims` | GET | Existing |
| **Memory** | `/pkb/search` | POST | Existing |
| **Memory** | `/pkb/relevant_context` | POST | Existing |
| **Utility** | `/transcribe` | POST | Existing |

---

## Appendix B: Message Sequence Diagrams

### B.1 Page Q&A Flow

```
User                Extension             Server              LLM
 │                     │                     │                  │
 │  Click "Ask about   │                     │                  │
 │  this page"         │                     │                  │
 │────────────────────▶│                     │                  │
 │                     │                     │                  │
 │                     │ Extract page content│                  │
 │                     │◀──────────────────┐ │                  │
 │                     │                   │ │                  │
 │                     │                     │                  │
 │                     │ POST /ext/chat      │                  │
 │                     │ { message, page_content, model }       │
 │                     │────────────────────▶│                  │
 │                     │                     │                  │
 │                     │                     │  Call LLM API    │
 │                     │                     │─────────────────▶│
 │                     │                     │                  │
 │                     │                     │  Stream response │
 │                     │                     │◀─────────────────│
 │                     │                     │                  │
 │                     │ Stream chunks       │                  │
 │                     │◀────────────────────│                  │
 │                     │                     │                  │
 │  Display streaming  │                     │                  │
 │◀────────────────────│                     │                  │
 │                     │                     │                  │
```

### B.2 Context Menu Action Flow

```
User                Page              Extension           Server
 │                    │                   │                  │
 │ Select text        │                   │                  │
 │───────────────────▶│                   │                  │
 │                    │                   │                  │
 │ Right-click        │                   │                  │
 │───────────────────▶│                   │                  │
 │                    │                   │                  │
 │                    │ Show context menu │                  │
 │                    │──────────────────▶│                  │
 │                    │                   │                  │
 │ Click "Explain"    │                   │                  │
 │───────────────────▶│                   │                  │
 │                    │                   │                  │
 │                    │ Get selected text │                  │
 │                    │◀─────────────────▶│                  │
 │                    │                   │                  │
 │                    │                   │ POST /ext/chat/quick
 │                    │                   │ { action: "explain", text }
 │                    │                   │─────────────────▶│
 │                    │                   │                  │
 │                    │                   │ Stream response  │
 │                    │                   │◀─────────────────│
 │                    │                   │                  │
 │                    │ Show modal with   │                  │
 │                    │ streaming response│                  │
 │◀───────────────────│◀──────────────────│                  │
 │                    │                   │                  │
```

---

## Appendix C: UI Wireframes (Conceptual)

### C.1 Sidepanel Layout

```
┌─────────────────────────────────────────┐
│ ☰  AI Assistant              [Settings] │
├─────────────────────────────────────────┤
│ ┌─────────────────────────────────────┐ │
│ │ Conversations                    [+] │ │
│ │ ─────────────────────────────────── │ │
│ │ ○ Chat about React docs    2m ago   │ │
│ │ ● Current page Q&A         5m ago   │ │
│ │ ○ Research project        1h ago   │ │
│ │ ○ Code review             2h ago   │ │
│ └─────────────────────────────────────┘ │
├─────────────────────────────────────────┤
│ ┌─────────────────────────────────────┐ │
│ │ Model: [GPT-4 ▼]                    │ │
│ │ Prompt: [Default ▼]                 │ │
│ │ Memories: [+ Add]                   │ │
│ └─────────────────────────────────────┘ │
├─────────────────────────────────────────┤
│                                         │
│  ┌───────────────────────────────────┐  │
│  │ 👤 Can you summarize this page?   │  │
│  └───────────────────────────────────┘  │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │ 🤖 This page discusses the new    │  │
│  │    React 19 features including... │  │
│  │    [Continue streaming...]        │  │
│  └───────────────────────────────────┘  │
│                                         │
├─────────────────────────────────────────┤
│ ┌─────────────────────────────────────┐ │
│ │ 📎 📷 🌐 [ Type your message... ] ➤ │ │
│ └─────────────────────────────────────┘ │
│ [Include page] [Multi-tab] [🎤 Voice]   │
└─────────────────────────────────────────┘
```

### C.2 Popup Layout

```
┌─────────────────────────────────┐
│ AI Assistant         [Settings] │
├─────────────────────────────────┤
│                                 │
│  [📝 Open Sidepanel]            │
│                                 │
├─────────────────────────────────┤
│  Quick Actions:                 │
│  [Summarize Page]               │
│  [Ask about Selection]          │
│  [Read All Tabs]                │
│                                 │
├─────────────────────────────────┤
│  Recent Conversations:          │
│  • Chat about React docs        │
│  • Current page Q&A             │
│  • Research project             │
│                                 │
├─────────────────────────────────┤
│  [Open Web Dashboard]           │
│  [Logout: user@email.com]       │
└─────────────────────────────────┘
```

### C.3 Context Menu Modal

```
┌─────────────────────────────────────┐
│ Explanation                    [×]  │
├─────────────────────────────────────┤
│                                     │
│  The selected text "React hooks"    │
│  refers to a feature introduced     │
│  in React 16.8 that allows you to   │
│  use state and other React...       │
│                                     │
│  [Streaming...]                     │
│                                     │
├─────────────────────────────────────┤
│ [📋 Copy] [💬 Continue] [❌ Close]   │
└─────────────────────────────────────┘
```

---

*Document Version: 1.0*  
*Last Updated: December 2024*  
*Author: AI Assistant & User*

