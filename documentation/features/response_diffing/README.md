# Response Diffing (Compare)

## Motivation

When working with LLMs, the same prompt can produce meaningfully different responses depending on the model, temperature, or system prompt. Response Diffing lets users re-run any assistant response with different parameters and see a structured side-by-side comparison — enabling model comparison, fact-checking (if two models disagree, one may be hallucinating), and prompt optimization without the manual copy-paste workflow.

## UX Flow

1. User opens the triple-dot menu (⋮) on any assistant message card
2. Clicks "Compare with…" (only visible on assistant messages)
3. A full-width modal opens:
   - **Left pane**: Original response (rendered markdown)
   - **Right pane**: Placeholder until generation starts
   - **Controls bar**: Model picker dropdown, temperature slider (0–2), optional steering instruction text input, Generate button
4. User selects a model, adjusts temperature if desired, optionally adds a steering instruction (e.g. "be more concise" or "focus on security")
5. Clicks "Generate" → right pane streams the new response in real-time
6. Once streaming completes, user can toggle to "Diff View" to see word-level differences:
   - Green highlighting: text added in new response
   - Red + strikethrough: text removed from original

## API

### `POST /rerun_message/<conversation_id>/<message_id>`

Re-runs the user turn preceding the specified assistant message with different model/parameters. Streams the response without persisting it.

**Request body (JSON):**
```json
{
  "model": "anthropic/claude-opus-latest",
  "temperature": 0.7,
  "system_prompt_override": "be more concise"
}
```

**Response:** Newline-delimited JSON stream (`content_type: text/plain`):
```json
{"text": "", "status": "Starting comparison...", "type": "compare"}
{"text": "chunk of text", "type": "compare", "accumulated_text": "all text so far"}
{"text": "", "type": "compare", "completed": true, "accumulated_text": "full response", "model": "..."}
```

**Error responses:**
- 400: `model` not provided, message is not from assistant, no preceding user message
- 404: Conversation or message not found

## Frontend API

### `CompareManager.open(conversationId, messageId, originalText)`

Opens the comparison modal. Called from the vote-dropdown-menu click handler.

- `conversationId`: Active conversation ID
- `messageId`: The assistant message ID to compare against
- `originalText`: Raw markdown text of the original response

## Implementation Details

### Backend (`endpoints/compare.py`)

- Loads the conversation and finds the target assistant message by `message_id`
- Finds the preceding user message to get the original query text
- Builds lightweight context: `running_summary` + last 6 messages before the target
- Calls `CallLLm` directly with the specified model/temperature (bypasses full `reply()` pipeline)
- Streams JSON chunks without persisting anything

### Frontend (`interface/compare-manager.js`)

- Self-contained IIFE module exposing `CompareManager.open()`
- Creates Bootstrap 4 modal on first use (lazy DOM injection)
- Model dropdown populated from `window.ModelCatalog.getAll()` (falls back to hardcoded list)
- Streaming: `fetch()` + `ReadableStream` reader, same pattern as `TempLLMManager`
- Word-level diff: LCS-based dynamic programming algorithm comparing word arrays
- Falls back to line-level diff for very long texts (>2M word pairs)
- View toggle: "Side by Side" (both panes visible) vs "Diff View" (single pane with inline diff markup)

### Menu Integration (`interface/common.js`)

- "Compare with…" dropdown item added in `initialiseVoteBank()` after the "Save to Memory" item
- Only rendered for assistant messages (`!disable_voting`)
- Gets `message-id` from card header attribute, `text` from function parameter (raw markdown)

## Files Modified

- `endpoints/compare.py` — New endpoint blueprint
- `endpoints/__init__.py` — Blueprint registration
- `interface/compare-manager.js` — New frontend module
- `interface/common.js` — Menu item in `initialiseVoteBank()`
- `interface/interface.html` — Script tag + CSS for diff highlighting

## Future Enhancements

- **Semantic diff**: Use an LLM to annotate agreement/disagreement/different-framing between the two responses
- **Keep/Replace/Merge**: Let users replace the original with the new response, or open a merge editor
- **Model tracking**: Store which model generated each message for comparison history
- **Batch comparison**: Run the same prompt against multiple models simultaneously
