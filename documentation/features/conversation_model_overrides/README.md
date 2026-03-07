# Conversation Model Overrides

Conversation model overrides let users pick non-reply models on a per-conversation basis (internal operations, quick actions, artefact edits, Doc Index operations, and clarification). Overrides are stored on the conversation and sent to the server so they apply consistently across sessions and devices.

## What We Added

- **Conversation-level settings store**: new `conversation_settings` field in `Conversation.py` persisted with the conversation.
- **Model override UI**: chat settings now exposes a **Model Overrides** modal with 5 dropdowns organized by section (defaults + full model list).
- **Dynamic model catalog**: dropdown options are fetched from `/model_catalog`, which dedupes models from the common model lists.
- **Server application points**: overrides are applied to internal conversation operations (summaries, TLDR, memory pad, context extraction, next question suggestions, web result summarization), quick actions (doubt clearing, context menu actions), artefact propose-edits, Doc Index summarization/answers, and clarification.

## Background & Motivation

The override system originally had 9 separate keys (including 3 Doc Index keys). This was consolidated in two phases:

1. **Doc Index consolidation**: 3 doc override keys (`doc_long_summary_model`, `doc_long_summary_v2_model`, `doc_short_answer_model`) merged into a single `doc_model` key.
2. **Conversation override consolidation**: 4 conversation keys (`summary_model`, `tldr_model`, `doubt_clearing_model`, `context_action_model`) merged into 2 (`conversation_internal_model`, `quick_action_model`). Additionally, 5 previously hardcoded CallLLm sites were brought under `conversation_internal_model` override control, and 2 hardcoded model references were fixed (`EXPENSIVE_LLM[0]` → `CHEAP_LLM[0]` in `base.py` image captioning, `"gpt-4o-mini"` → `CHEAP_LLM[0]` in `Conversation.py` content type detection).

3. **Model cost optimization**: Several hardcoded expensive defaults were replaced with cheaper alternatives — `EXPENSIVE_LLM[0]` → `CHEAP_LLM[0]` for image captioning in `base.py`, `"gpt-4o-mini"` → `CHEAP_LLM[0]` in `Conversation.py`, `VERY_CHEAP_LLM[0]` → `SUPERFAST_LLM[0]` for Jina search results in `search_and_information_agents.py`, `CHEAP_LONG_CONTEXT_LLM[0]` → `VERY_CHEAP_LLM[0]` for ContextualReader fallback and DocIndex utility classes (`MultiFacetDocSummarizer`, `MultiDocAnswerAgent`). `SUPERFAST_LLM` (`inception/mercury-2`) was also added to `_get_token_limit()` in `call_llm.py` with a 100k token context window (previously fell through to the 48k default).
The result is 5 override keys (down from 9), covering more CallLLm sites with fewer controls.

## User Experience

- Open chat settings → **Model Overrides**.
- The modal has 5 dropdowns organized into sections:
  - **Conversation Internal** — `conversation_internal_model`
  - **Quick Actions** — `quick_action_model`
  - **Artefacts** — `artefact_propose_edits_model`
  - **Doc Index** — `doc_model`
  - **Clarify** — `clarify_intent_model`
- Each dropdown has:
  - **Default (recommended)** which means "use the current code default."
  - A default entry showing the actual default model name.
  - All deduped models from the shared lists.
- Overrides are saved per conversation and do not affect other chats.
- Old conversations with legacy keys (`summary_model`, `tldr_model`, `doubt_clearing_model`, `context_action_model`) gracefully fall back to defaults since those keys are no longer read.

## Settings Schema

Stored on the conversation as:

```json
{
  "model_overrides": {
    "conversation_internal_model": "...",
    "quick_action_model": "...",
    "artefact_propose_edits_model": "...",
    "doc_model": "...",
    "clarify_intent_model": "..."
  }
}
```

If a key is missing or empty, the server falls back to the existing default in code.

### Override Key Details

| Key | Default | Sites Covered |
|---|---|---|
| `conversation_internal_model` | `SUPERFAST_LLM[0]` (`inception/mercury-2`) | Running summary, TLDR generation (2 sites), next question suggestions, memory pad extraction, memory pad merge, prior context retrieval, web result summarization |
| `quick_action_model` | `SUPERFAST_LLM[0]` (`inception/mercury-2`) | Doubt clearing, context menu actions (explain/critique/expand/ELI5), `endpoints/doubts.py` fallback |
| `artefact_propose_edits_model` | `EXPENSIVE_LLM[2]` | Artefact propose-edits |
| `doc_model` | `CHEAP_LONG_CONTEXT_LLM[0]` | DocIndex long summary, long summary v2, chain-of-density, short answer, contextual reader, multi-facet summarizer |
| `clarify_intent_model` | `VERY_CHEAP_LLM[0]` | `/clarify` slash command LLM call |

### Legacy Key Migration

The following keys are **no longer used** and can be ignored in old conversation data:

| Removed Key | Absorbed Into |
|---|---|
| `summary_model` | `conversation_internal_model` |
| `tldr_model` | `conversation_internal_model` |
| `doubt_clearing_model` | `quick_action_model` |
| `context_action_model` | `quick_action_model` |
| `doc_long_summary_model` | `doc_model` |
| `doc_long_summary_v2_model` | `doc_model` |
| `doc_short_answer_model` | `doc_model` |

## API Endpoints

- `GET /get_conversation_settings/<conversation_id>`
  - Returns `{ conversation_id, settings }`.
- `PUT /set_conversation_settings/<conversation_id>`
  - Payload: `{ "model_overrides": { ... } }`
  - Validates model names using `model_name_to_canonical_name`.
  - Only keys in `allowed_keys` are accepted.
- `GET /model_catalog`
  - Returns `{ models: [...], defaults: { ... } }`.
  - Models are deduped from: `VERY_CHEAP_LLM`, `CHEAP_LLM`, `EXPENSIVE_LLM`, `CHEAP_LONG_CONTEXT_LLM`, `LONG_CONTEXT_LLM`, `SUPERFAST_LLM`.

## Application Points (Server)

### `conversation_internal_model` (8 sites in Conversation.py)

- **Running summary**: updated after each reply turn.
- **TLDR generation**: two sites — one in main reply flow, one in tab-based multi-model response.
- **Next question suggestions**: `create_next_question_suggestions()`.
- **Memory pad extraction**: `add_to_memory_pad_from_response()` — extracting key points.
- **Memory pad merge**: `add_to_memory_pad_from_response()` — merging into existing pad.
- **Prior context retrieval**: `retrieve_prior_context_llm_based()`.
- **Web result summarization**: summarizing web search results before injecting into context.

Override retrieval pattern:
```python
self.get_conversation_settings().get("model_overrides", {}).get("conversation_internal_model", SUPERFAST_LLM[0])
```

### `quick_action_model` (3 sites)

- **Doubt clearing**: `Conversation.reply()` doubt-clearing flow.
- **Context menu actions**: `Conversation.reply()` explain/critique/expand/ELI5 actions.
- **Doubts endpoint fallback**: `endpoints/doubts.py` context action path.

### `artefact_propose_edits_model` (1 site)

- **Artefact propose edits**: `endpoints/artefacts.py`.

### `doc_model` (10 override sites + 5 hardcoded in DocIndex.py)

**Override-controlled (10 sites):**
- `set_title_summary()` — short summary and title generation (2 CallLLm, default `VERY_CHEAP_LLM[0]`)
- `get_doc_long_summary()` — long summary generation (4 CallLLm: main summary at `CHEAP_LONG_CONTEXT_LLM[0]`, paper-quality at `EXPENSIVE_LLM[0]`, v2 summary, follow-up)
- `get_doc_density_summary()` — chain-of-density summary (2 CallLLm, default `EXPENSIVE_LLM[0]`)
- `title` property — fallback title generation (default `VERY_CHEAP_LLM[0]`)
- `short_summary` property — fallback short summary (default `VERY_CHEAP_LLM[0]`)

**Hardcoded (5 sites — intentionally not overridden):**
- `MultiFacetDocSummarizer._get_llm()` — multi-facet summarization (default `VERY_CHEAP_LLM[0]`)
- `MultiDocAnswerAgent._get_llm()` — multi-doc Q&A (default `VERY_CHEAP_LLM[0]`)
- `ImageDocIndex` init — 2 CallLLm using `IMAGE_VISION_MODEL` (`google/gemini-3.1-flash-lite-preview`) for image description
- `YouTubeDocIndex.streaming_get_short_answer()` — 1 CallLLm using `IMAGE_VISION_MODEL` for video frame analysis

The hardcoded vision sites use a specialized vision model and should not be overridden. The utility classes (`MultiFacetDocSummarizer`, `MultiDocAnswerAgent`) accept `model_name` as a constructor parameter but default to `VERY_CHEAP_LLM[0]`.
### `clarify_intent_model` (1 site)

- **Clarify intent**: `endpoints/conversations.py` `/clarify_intent` endpoint.

## UI Implementation Details

- **Modal**: `interface/interface.html` — Model Overrides modal with 5 dropdowns organized into labeled sections.
- **Data loading**: `interface/chat.js` `populateModelOverrides()` creates dropdowns for each of the 5 keys.
- **Loading values**: `interface/chat.js` `loadConversationSettings()` reads saved overrides into the dropdowns.
- **Saving**: `interface/chat.js` `saveConversationSettings()` collects values from the 5 dropdowns and PUTs to the server.
- **Conversation switching**: `interface/common-chat.js` fetches settings on conversation load and updates `chatSettingsState`.

## Extending the Feature

To add a new override:

1) **Server allowlist**: add the key to `allowed_keys` in `endpoints/conversations.py`.
2) **Defaults**: include the default in the `defaults` dict in `get_models_list()` in `endpoints/conversations.py`.
3) **Storage**: no change needed (same `model_overrides` map).
4) **Usage**: apply `conversation.get_model_override("new_key", DEFAULT)` or the `.get("model_overrides", {}).get(...)` pattern at the callsite.
5) **UI**: add a dropdown in `interface/interface.html` and wire load/save in `interface/chat.js` (update `populateModelOverrides`, `loadConversationSettings`, `saveConversationSettings`).
6) **Docs**: update this file and any relevant API docs.

## Key Files

- `Conversation.py` — override retrieval at 8+ CallLLm sites
- `DocIndex.py` — `doc_model` override for 10 sites; 5 hardcoded (3 vision, 2 utility class defaults)
- `common.py` — `SUPERFAST_LLM` and other model constant definitions
- `code_common/call_llm.py` — `_get_token_limit()` maps model constants to context window sizes; `SUPERFAST_LLM` mapped to 100k tokens
- `endpoints/conversations.py` — `allowed_keys`, `defaults`, model catalog, settings endpoints
- `endpoints/artefacts.py` — `artefact_propose_edits_model` override
- `endpoints/doubts.py` — `quick_action_model` override
- `interface/interface.html` — Model Overrides modal UI
- `interface/chat.js` — populate/load/save override dropdowns
- `interface/common-chat.js` — settings fetch on conversation switch
