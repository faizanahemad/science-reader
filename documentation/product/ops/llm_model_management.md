# LLM Model Management

How to add, remove, or update LLM models used in the platform — both for the main conversation reply flow (UI model selector) and for per-conversation model overrides in settings.

All LLM calls are routed through **OpenRouter** (`https://openrouter.ai/api/v1`), so any model available on OpenRouter can be added without provider-specific code.

---

## Architecture Overview

```
UI Model Selector (interface.html)
        |
        |  user selects model(s) → checkboxes["main_model"]
        v
Conversation.reply() (Conversation.py)
        |
        |  model_name_to_canonical_name() normalizes display name → API name
        v
CallLLm (call_llm.py root)
        |
        v
call_llm() (code_common/call_llm.py)
        |
        |  OpenRouter API call
        v
OpenRouter → Provider (OpenAI, Anthropic, Google, etc.)
```

For model overrides:
```
GET /model_catalog → combines tier lists from common.py → returns model list + defaults
        |
        v
chat.js loadModelCatalog() → populateModelOverrideOptions() → fills 8 override <select> dropdowns
        |
        v
User saves settings → PUT /set_conversation_settings → stored per conversation
        |
        v
Conversation.get_model_override(key, default) → returns override or falls back to default
```

---

## Files Involved

| File | Role |
|---|---|
| `common.py` (lines 82-135) | Central model registry — tier lists |
| `interface/interface.html` (lines ~1862-1934) | Main model selector dropdown (hardcoded `<option>` elements) |
| `interface/interface.html` (lines ~2374-2412) | Model override `<select>` dropdowns (dynamically populated) |
| `interface/chat.js` (lines 761-838) | `loadModelCatalog()` and `populateModelOverrideOptions()` |
| `Conversation.py` (lines 10052-10289) | `model_name_to_canonical_name()` — display name → API name mapping |
| `Conversation.py` (lines 1166-1189) | `get_model_override()` — reads per-conversation override |
| `Conversation.py` (line 6138) | Where `checkboxes["main_model"]` is extracted in the reply flow |
| `endpoints/conversations.py` (lines 191-212) | `/model_catalog` endpoint — combines tier lists, returns with defaults |
| `endpoints/conversations.py` (lines 234-269) | `/set_conversation_settings` endpoint — saves overrides |
| `code_common/call_llm.py` (lines 152-193) | `VISION_CAPABLE_MODELS` frozenset |
| `code_common/call_llm.py` (lines 79-149) | `MODEL_TOKEN_LIMITS` dict and `_get_token_limit()` function |

---

## Part 1: Main Conversation Model Selector

The main model selector is the dropdown in the chat settings panel that lets the user choose which LLM(s) to use for the conversation reply.

### How It Works

1. **UI** — `interface/interface.html` has a `<select multiple>` with `id="settings-main-model-selector"` (line 1864). Each model is a hardcoded `<option>` element.
2. **Frontend** — `chat.js` reads selected values via `getSelectPickerValue('#settings-main-model-selector', [])` (line 641) and sends them as `checkboxes.main_model`.
3. **Backend** — `Conversation.reply()` extracts `checkboxes["main_model"]` (line 6138), then calls `model_name_to_canonical_name()` to normalize the display name to the API model identifier.
4. **LLM Call** — The canonical name is passed to `CallLLm` → `code_common.call_llm.call_llm()` → OpenRouter.

### Adding a New Model to the Main Selector

**Step 1: Add to common.py tier list**

Open `common.py` and add the model's OpenRouter identifier to the appropriate tier list (lines 82-135):

| Tier | Constant | Use When |
|---|---|---|
| Ultra-budget | `VERY_CHEAP_LLM` (line 84) | Very cheap, fast, background tasks |
| Budget | `CHEAP_LLM` (line 89) | Good balance of cost and quality |
| Premium | `EXPENSIVE_LLM` (line 94) | High-capability, complex tasks |
| Budget + Long Context | `CHEAP_LONG_CONTEXT_LLM` (line 128) | Cheap models with 128K+ context |
| Premium + Long Context | `LONG_CONTEXT_LLM` (line 135) | Max context window models |

Example — adding `anthropic/claude-sonnet-5` to the expensive tier:
```python
# common.py, line 94
EXPENSIVE_LLM = [
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-sonnet-5",       # <-- add here
    "openai/gpt-5.1",
    ...
]
```

Note: The position within the list matters for defaults. Index `[0]` of each list is used as default for some override settings (see Part 2).

**Step 2: Add `<option>` to interface.html**

Open `interface/interface.html` and add an `<option>` inside `#settings-main-model-selector` (lines 1864-1934).

- Add to the "Newer Models" `<optgroup>` (line 1865) for prominent new models.
- Add to the "Others" `<optgroup>` (line 1877) for secondary/niche models.
- Use `hidden` attribute on the `<option>` to include a model in the dropdown data without showing it in the visible list. Hidden models can still be selected programmatically or restored from saved state.

Example:
```html
<optgroup label="Newer Models">
    <option>Sonnet 5</option>           <!-- display name -->
    ...
</optgroup>
```

The `<option>` text is the display name the user sees. This is what gets sent as `checkboxes["main_model"]`.

**Step 3: Add canonical name mapping in Conversation.py**

Open `Conversation.py` and add an entry to `model_name_to_canonical_name()` (starts at line 10052). This function maps display names (from the UI dropdown `<option>` text) to OpenRouter API identifiers.

Example:
```python
elif model_name == "Sonnet 5":
    model_name = "anthropic/claude-sonnet-5"
```

If the display name in the `<option>` is already the full API identifier (e.g. `anthropic/claude-sonnet-5`), you still need an entry — most entries for API-named models map to themselves as a passthrough validation. The function raises `ValueError` at the end (line 10288) for any unrecognized name.

The function also handles aliases. Multiple display names can map to the same canonical name:
```python
elif model_name == "anthropic/claude-sonnet-5" or model_name == "Sonnet 5":
    model_name = "anthropic/claude-sonnet-5"
```

**Step 4 (if vision-capable): Add to VISION_CAPABLE_MODELS**

If the model supports image/vision input, add its API identifier to the `VISION_CAPABLE_MODELS` frozenset in `code_common/call_llm.py` (line 152).

```python
VISION_CAPABLE_MODELS = frozenset(
    {
        ...
        "anthropic/claude-sonnet-5",   # <-- add here
    }
)
```

Without this, any images attached to the message will be stripped before the API call.

**Step 5 (if custom token limit needed): Update _get_token_limit()**

`_get_token_limit()` in `code_common/call_llm.py` (line 96) determines the max input tokens for each model. It first checks if the model is in any `common.py` tier list, then falls back to substring matching (e.g. `"anthropic"` in model_name).

If the new model fits an existing pattern (e.g. it's already in `EXPENSIVE_LLM` or its provider prefix is already handled), no changes needed. Otherwise, add a new branch.

The token limit categories are defined in `MODEL_TOKEN_LIMITS` (line 79):
```python
MODEL_TOKEN_LIMITS = {
    "cheap_long_context": 800_000,
    "long_context": 900_000,
    "expensive": 200_000,
    "gemini_flash": 400_000,
    "gemini_other": 500_000,
    "cohere_llama_deepseek_jamba": 100_000,
    "mistral_large_pixtral": 100_000,
    "mistralai_other": 146_000,
    "claude_3": 180_000,
    "anthropic_other": 160_000,
    "openai_prefixed": 160_000,
    "known_cheap_expensive": 160_000,
    "default": 48_000,
}
```

### Removing a Model from the Main Selector

1. **interface.html** — Either delete the `<option>` or add `hidden` attribute to keep it for backward compatibility with saved conversation states.
2. **common.py** — Remove from the active tier list. Optionally move to `UNUSED_EXPENSIVE_LLM` (line 108) to keep a record.
3. **Conversation.py** — Keep the `model_name_to_canonical_name()` entry so existing conversations with that model saved don't break (it will raise `ValueError` otherwise). Alternatively, remap old name to a replacement model.
4. **code_common/call_llm.py** — Optionally remove from `VISION_CAPABLE_MODELS` (cosmetic only — no harm leaving it).

### Hiding a Model (Keep Available but Not Shown)

Add the `hidden` attribute to the `<option>` in `interface.html`:
```html
<option hidden>old-model-name</option>
```
This keeps the model functional for existing conversations but hides it from the dropdown. No backend changes needed.

---

## Part 2: Model Override Dropdowns (Per-Conversation Settings)

Model overrides let users customize which LLM is used for specific subtasks within a conversation (e.g. summaries, TLDR, artefact edits). These are separate from the main model selector.

### The 8 Override Slots

| Override Key | UI Label | Default Tier | Default Index |
|---|---|---|---|
| `summary_model` | Summary Model | `VERY_CHEAP_LLM` | `[0]` |
| `tldr_model` | TLDR Model | `CHEAP_LONG_CONTEXT_LLM` | `[0]` |
| `artefact_propose_edits_model` | Artefact Propose Edits Model | `EXPENSIVE_LLM` | `[2]` |
| `doubt_clearing_model` | Doubt Clearing Model | `EXPENSIVE_LLM` | `[2]` |
| `context_action_model` | Context Menu Action Model | `EXPENSIVE_LLM` | `[2]` |
| `doc_long_summary_model` | Doc Long Summary Model | `CHEAP_LONG_CONTEXT_LLM` | `[0]` |
| `doc_long_summary_v2_model` | Doc Long Summary V2 Model | `CHEAP_LONG_CONTEXT_LLM` | `[0]` |
| `doc_short_answer_model` | Doc Short Answer Model | `CHEAP_LONG_CONTEXT_LLM` | `[0]` |

Defaults are defined in `endpoints/conversations.py` (lines 202-210).

### How Override Dropdowns Are Populated

1. On page load, `chat.js` calls `loadModelCatalog()` (line 802) which hits `GET /model_catalog`.
2. The `/model_catalog` endpoint (line 191 in `endpoints/conversations.py`) combines all tier lists from `common.py` and deduplicates:
   ```python
   models = _dedupe_models(
       VERY_CHEAP_LLM + CHEAP_LLM + EXPENSIVE_LLM
       + CHEAP_LONG_CONTEXT_LLM + LONG_CONTEXT_LLM
   )
   ```
3. The response is stored as `window.ModelCatalog`.
4. `populateModelOverrideOptions()` (line 761 in `chat.js`) iterates over 8 `<select>` elements and fills each with:
   - A "Default (recommended)" option (value `__default__`)
   - The tier default for that key (labelled `"model-name (default)"`)
   - All other models from the catalog

The 8 `<select>` elements in `interface.html` (lines 2374-2412) start empty and are populated dynamically:
```html
<select class="form-control" id="settings-summary-model"></select>
<select class="form-control" id="settings-tldr-model"></select>
<select class="form-control" id="settings-artefact-propose-model"></select>
<select class="form-control" id="settings-doubt-clearing-model"></select>
<select class="form-control" id="settings-context-action-model"></select>
<select class="form-control" id="settings-doc-long-summary-model"></select>
<select class="form-control" id="settings-doc-long-summary-v2-model"></select>
<select class="form-control" id="settings-doc-short-answer-model"></select>
```

### Adding a Model to Override Dropdowns

Since override dropdowns are populated dynamically from the `/model_catalog` endpoint, adding a model to any tier list in `common.py` (Step 1 from Part 1) automatically makes it available in all 8 override dropdowns. **No additional HTML or JS changes needed.**

If you only want a model in override dropdowns but not in the main selector, add it to the appropriate `common.py` tier list but skip adding the `<option>` in `interface.html`.

### Removing a Model from Override Dropdowns

Remove the model from all tier lists in `common.py`. It will no longer appear in the `/model_catalog` response and therefore won't show in override dropdowns.

If the removed model was the default for any override slot (check `endpoints/conversations.py` lines 202-210), update the default to point at a valid model or adjust the list index.

### Changing Override Defaults

Edit the `defaults` dict in `get_model_catalog()` at `endpoints/conversations.py` (lines 202-210):
```python
defaults = {
    "summary_model": VERY_CHEAP_LLM[0],
    "tldr_model": CHEAP_LONG_CONTEXT_LLM[0],
    "artefact_propose_edits_model": EXPENSIVE_LLM[2],
    ...
}
```

The default is referenced by list index. Reordering items in the `common.py` tier list changes which model is default. To set an explicit default regardless of list position, use the model name string directly instead of an index.

### How Overrides Are Read at Runtime

In `Conversation.py`, `get_model_override(key, default)` (line 1166) reads the stored conversation settings:
```python
def get_model_override(self, key, default=None):
    settings = self.get_conversation_settings()
    overrides = settings.get("model_overrides")
    value = overrides.get(key)
    return value or default
```

If no override is set (user left it on "Default (recommended)"), the code falls back to the `default` argument, which is typically one of the `common.py` tier list constants.

### Allowed Override Keys

The `set_conversation_settings` endpoint validates against a whitelist (line 260 in `endpoints/conversations.py`):
```python
allowed_keys = {
    "summary_model",
    "tldr_model",
    "artefact_propose_edits_model",
    "doubt_clearing_model",
    "context_action_model",
    "doc_long_summary_model",
    "doc_long_summary_v2_model",
    "doc_short_answer_model",
}
```

To add a new override slot, you must update: `allowed_keys` in the endpoint, add a `<select>` in `interface.html`, add it to the `selects` array in `populateModelOverrideOptions()` in `chat.js`, add it to the `defaults` dict in `get_model_catalog()`, and use `get_model_override()` in the backend code that performs the subtask.

---

## Quick Reference: Checklist for Adding a New Model

### Minimum (model appears in override dropdowns only)
- [ ] Add to appropriate tier list in `common.py` (lines 82-135)

### Standard (model appears in main selector + overrides)
- [ ] Add to appropriate tier list in `common.py` (lines 82-135)
- [ ] Add `<option>` to `#settings-main-model-selector` in `interface/interface.html` (lines 1864-1934)
- [ ] Add entry in `model_name_to_canonical_name()` in `Conversation.py` (line 10052+)

### Full (vision model with custom token limits)
- [ ] All of the above
- [ ] Add to `VISION_CAPABLE_MODELS` in `code_common/call_llm.py` (line 152) if vision-capable
- [ ] Add/verify token limit in `_get_token_limit()` / `MODEL_TOKEN_LIMITS` in `code_common/call_llm.py` (line 79+) if needed

### Removing a Model
- [ ] Remove or add `hidden` to `<option>` in `interface/interface.html`
- [ ] Remove from tier list in `common.py` (or move to `UNUSED_EXPENSIVE_LLM`)
- [ ] Keep `model_name_to_canonical_name()` entry for backward compatibility (or remap to replacement)
- [ ] Check if model was a default in `get_model_catalog()` defaults — update index if needed

---

## Notes

- **No server restart needed for HTML changes** — just refresh the browser. Backend changes (`common.py`, `Conversation.py`, `call_llm.py`, `endpoints/`) require a server restart.
- **Model names are OpenRouter identifiers** — format is `provider/model-name` (e.g. `anthropic/claude-sonnet-5`). Some legacy models use bare names (e.g. `gpt-4o`) without the provider prefix.
- **The `FILLER_MODEL`** (value `"Filler"`, defined at `common.py` line 63) is a special placeholder that skips the LLM call entirely. It must not be combined with other models in multi-model selection.
- **`UNUSED_EXPENSIVE_LLM`** (line 108 in `common.py`) is a parking lot for deactivated expensive models. Models here are not included in the `/model_catalog` response and don't appear in any dropdown.
- **`OPENAI_CHEAP_LLM`** (line 125 in `common.py`) is a single string constant (not a list) used as a fallback in some internal code paths. Update it if the preferred cheap OpenAI model changes.
