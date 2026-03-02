# Image Generation Feature

AI image generation integrated into the chat app via OpenRouter's multimodal models (Nano Banana 2 and others). Two entry points: a `/image` slash command that generates images inline in conversation, and a standalone modal accessible from Settings.

---

## Entry Points

### 1. `/image` Slash Command (Inline Chat)

Type `/image <prompt>` in the chat input. The image is generated and rendered directly inside the conversation as a persistent message card — part of the conversation history, downloadable, and visible to the LLM on subsequent turns.

```
/image a watercolour painting of a mountain at sunrise
```

### 2. Image Generation Modal (Settings → Image)

Click the **Image** button (green, `bi-image` icon) in Settings → Actions. A modal opens with a full form: prompt, model selector, conversation context controls, and a "Better context" toggle. The generated image is shown in the modal and can be downloaded — it is **not** saved into the conversation.

---

## Architecture

### `/image` Command Flow

```
User types "/image <prompt>"
        │
        ▼
parseMessageForCheckBoxes()   ← interface/parseMessageForCheckBoxes.js:133
  strips "/image", sets generate_image: true
  remaining text becomes the prompt in messageText
        │
        ▼
POST /send_message/<conv_id>  ← endpoints/conversations.py
  checkboxes.generate_image = true
        │
        ▼
Conversation.reply()          ← Conversation.py:~6668
  detects generate_image flag
  calls yield from self._handle_image_generation(...)
  returns early (skips normal LLM path)
        │
        ▼
_handle_image_generation()    ← Conversation.py:~9729
  ┌─────────────────────────────────────────────┐
  │ 1. Gather context                           │
  │    gather_conversation_context(             │
  │      include_summary=True,                  │
  │      include_messages=True,                 │
  │      deep_context=True,                     │
  │      history_count=2                        │
  │    )                                        │
  ├─────────────────────────────────────────────┤
  │ 2. Refine prompt (better context)           │
  │    _refine_prompt_with_llm(                 │
  │      raw_prompt, context_parts, keys        │
  │    )                                        │
  │    model: CHEAP_LLM[0] (claude-haiku)       │
  │    system: BETTER_CONTEXT_SYSTEM prompt     │
  │    fallback: plain concatenation            │
  ├─────────────────────────────────────────────┤
  │ 3. Call image model                         │
  │    generate_image_from_prompt(              │
  │      refined_prompt, keys,                  │
  │      model=DEFAULT_IMAGE_MODEL              │
  │    )                                        │
  │    POST https://openrouter.ai/api/v1/       │
  │         chat/completions                    │
  │    modalities: ["image", "text"]            │
  │    response: message.images[0].image_url.url│
  ├─────────────────────────────────────────────┤
  │ 4. Store image                              │
  │    {conv_storage}/images/img_{hash16}.png   │
  │    serve URL: /api/conversation-image/      │
  │               {conv_id}/{filename}          │
  ├─────────────────────────────────────────────┤
  │ 5. Yield response (streaming)               │
  │    "![Generated Image]({url})\n\n"          │
  │    → renders as <img> via marked.js         │
  ├─────────────────────────────────────────────┤
  │ 6. Persist turn                             │
  │    persist_current_turn(...)                │
  │    msg["generated_images"] = [{             │
  │      "filename": "img_abc.png",             │
  │      "url": "/api/conversation-image/..."   │
  │    }]                                       │
  └─────────────────────────────────────────────┘
        │
        ▼
Frontend renders image card
  MutationObserver wraps <img> with download button
  Clicking image → opens in new tab
```

### Modal Flow

```
Settings → Image button (#settings-generate-image-button)
        │
        ▼
ImageGenManager.show()        ← interface/image-gen-manager.js
  disables Bootstrap focus trap
  grays out context checkboxes if no active conversation
        │
  User fills form + clicks Generate
        │
        ▼
POST /api/generate-image      ← endpoints/image_gen.py
  gather_conversation_context() (if conversation_id provided)
  _refine_prompt_with_llm()   (if better_context=true)
  generate_image_from_prompt()
        │
        ▼
JSON response:
  { images: ["data:image/png;base64,..."], text, model, refined_prompt }
        │
        ▼
ImageGenManager._renderPreview()
  shows refined prompt (blue info box)
  renders <img> + Download button + click-to-new-tab
```

---

## Image Model

**Default:** `google/gemini-3.1-flash-image-preview` (OpenRouter name: **Nano Banana 2**)

| OpenRouter Name | Model ID | Notes |
|---|---|---|
| Nano Banana 2 *(default)* | `google/gemini-3.1-flash-image-preview` | Best quality/speed balance |
| Nano Banana | `google/gemini-2.5-flash-image` | Slightly faster |
| Nano Banana Pro | `google/gemini-3-pro-image-preview` | Highest quality, slower |
| GPT-5 Image Mini | `openai/gpt-5-image-mini` | OpenAI alternative |
| GPT-5 Image | `openai/gpt-5-image` | OpenAI highest quality |

All models are called via:

```
POST https://openrouter.ai/api/v1/chat/completions
{
  "model": "<model_id>",
  "messages": [{"role": "user", "content": "<refined_prompt>"}],
  "modalities": ["image", "text"],
  "max_tokens": 4096
}
```

The image is returned in `choices[0].message.images[0].image_url.url` as a `data:image/png;base64,...` data URI (~2–3 MB).

---

## Better Context (Prompt Refinement)

An intermediate LLM call that acts as an image-prompt engineer before the image model is called.

**System prompt** (`BETTER_CONTEXT_SYSTEM` in `endpoints/image_gen.py`):

> You are an expert image-prompt engineer. Given the user's raw image prompt and conversation context, produce a SINGLE refined prompt that incorporates relevant details, is concrete and visual, specifies style/mood/lighting/composition if vague, and removes conversational noise. Return ONLY the refined prompt, 1–4 sentences.

**Model:** `CHEAP_LLM[0]` (currently `anthropic/claude-haiku-4.5`)
**Temperature:** 0.4
**Max tokens:** 500
**Fallback:** If the LLM call fails or returns empty, falls back to plain concatenation of context + raw prompt.

**When active:**
- `/image` command: always on (always runs refinement + context)
- Modal: controlled by "Better context" checkbox (checked by default)

---

## Image Storage

Images are stored per-conversation as PNG files, **not** inline in conversation JSON.

```
storage/
  conversations/
    {conversation_id}/
      images/
        img_{sha256_16}.png     ← one file per generated image
```

- **Filename:** `img_` + first 16 hex chars of SHA-256 of the PNG bytes. Deterministic — same image bytes always produce the same filename (dedup).
- **Served by:** `GET /api/conversation-image/<conv_id>/<filename>` — auth-protected, login required, validates filename against `^[a-zA-Z0-9_-]+\.(png|jpg|jpeg|webp)$`, checks conversation ownership.
- **Message metadata:** The assistant message dict gets `generated_images: [{"filename": "...", "url": "..."}]` stored in the conversation history file.
- **Rendered as:** `![Generated Image](/api/conversation-image/{conv_id}/{filename})` — a standard markdown image tag that the marked.js renderer turns into `<img>`.

---

## LLM Vision Context (Subsequent Turns)

When the user sends a follow-up message after the `/image` command, the stored images are automatically included in the LLM call so vision-capable models can "see" and reason about them.

**Implementation** (`Conversation.py` ~line 8843):

```python
# After merging query_images and page_context screenshots:
recent_msgs = (self.get_field("messages") or [])[-6:]  # last 3 turns
for msg in recent_msgs:
    gen_imgs = msg.get("generated_images", [])
    if gen_imgs and msg.get("sender") == "model":
        for img_info in gen_imgs[:2]:  # max 2 per message
            img_path = os.path.join(self._storage, "images", img_info["filename"])
            if os.path.isfile(img_path):
                img_data = base64.b64encode(open(img_path, "rb").read()).decode()
                images.append(f"data:image/png;base64,{img_data}")
```

The `images` list is then passed to `CallLLm(...)(..., images=images)` which includes them as `image_url` content parts in the OpenAI-compatible messages array.

**Constraints:**
- Only the last 3 turns (6 messages) are scanned.
- Max 2 images per message are included.
- The model receiving the image must be in `VISION_CAPABLE_MODELS` (see `code_common/call_llm.py`).
- Images are loaded from disk on each request (not cached in memory between requests).

---

## Frontend Rendering

### In Chat Cards

Generated images from the `/image` command render as standard markdown images (`![alt](url)`). The MutationObserver in `interface/interface.html` watches `#chatView` for new `img[src*="/api/conversation-image/"]` elements and wraps them:

```html
<div class="generated-image-wrapper">
  <img src="/api/conversation-image/..." class="...">
  <button class="generated-image-download-btn">⬇ Download</button>
</div>
```

- **Download button**: appears on hover, triggers `<a download>` with a timestamped filename.
- **Click on image**: opens the image URL in a new tab (`window.open`).
- **CSS**: images get `max-width: 100%; border-radius: 8px; border: 1px solid #dee2e6;`.

### In the Modal

`ImageGenManager._renderPreview(images, text, refinedPrompt)`:

1. If `refined_prompt` is present, renders a blue info box showing the LLM-refined prompt.
2. Renders each image as `<img>` with click-to-new-tab.
3. Shows **Download** and **Clear** buttons once images are present.

---

## API Reference

### `POST /api/generate-image`

Rate limit: 10/minute. Auth required.

**Request:**

```json
{
  "prompt": "string (required)",
  "model": "google/gemini-3.1-flash-image-preview",
  "input_image": "data:image/png;base64,...  (optional — base64 data URI of image to edit)",
  "conversation_id": "optional, for context gathering",
  "include_summary": false,
  "include_messages": false,
  "include_memory_pad": false,
  "history_count": 10,
  "deep_context": false,
  "better_context": true
}
```

**Response (success):**

```json
{
  "status": "success",
  "images": ["data:image/png;base64,..."],
  "text": "Here is your generated image.",
  "model": "google/gemini-3.1-flash-image-preview",
  "refined_prompt": "A hyper-detailed watercolour..."
}
```

**Response (no images returned):**

```json
{
  "status": "success",
  "images": [],
  "text": "",
  "warning": "Model did not return any images. Try a different prompt or model.",
  "model": "...",
  "refined_prompt": null
}
```

**Error codes:**

| HTTP | `code` | Meaning |
|---|---|---|
| 400 | `missing_prompt` | Empty prompt |
| 500 | `missing_api_key` | `OPENROUTER_API_KEY` not configured |
| 502 | `openrouter_error` | OpenRouter returned non-200 |
| 502 | `empty_response` | No `choices` in response |
| 504 | `timeout` | OpenRouter call timed out (120s) |
| 500 | `internal_error` | Unexpected exception |

### `GET /api/conversation-image/<conversation_id>/<image_filename>`

Auth required. Conversation ownership validated. Filename validated against safe pattern.

Returns `image/png` binary. Used as the `src` in rendered `<img>` tags.

---

## Key Files

| File | Role |
|---|---|
| `endpoints/image_gen.py` | Core backend: `image_gen_bp`, `generate_image_from_prompt()`, `_refine_prompt_with_llm()`, `_build_image_prompt()`, `BETTER_CONTEXT_SYSTEM`, `DEFAULT_IMAGE_MODEL`, `/api/generate-image` endpoint, `/api/conversation-image/` serve endpoint |
| `endpoints/__init__.py` | Blueprint registration: `from .image_gen import image_gen_bp` |
| `Conversation.py` | `_handle_image_generation()` (line ~9729) — `/image` command handler; `reply()` (line ~6668) — flag intercept; image context injection (line ~8843) |
| `interface/image-gen-manager.js` | `ImageGenManager` IIFE — modal frontend: `show()`, `hide()`, `generate()`, `_renderPreview()`, `downloadCurrent()`, Bootstrap focus-trap management |
| `interface/parseMessageForCheckBoxes.js` | Line 133: `processCommand(/\/image\b/i, "generate_image", true)` |
| `interface/interface.html` | `#image-gen-modal` HTML; `#settings-generate-image-button`; MutationObserver + download button logic; CSS for `.generated-image-wrapper` and `.generated-image-download-btn` |
| `endpoints/llm_edit_utils.py` | `gather_conversation_context()` — used for context collection |
| `call_llm.py` | `CallLLm` — used for the "better context" prompt refinement step |
| `common.py` | `CHEAP_LLM` — model list for refinement LLM |

---

## Configuration

| Key | Source | Default | Purpose |
|---|---|---|---|
| `OPENROUTER_API_KEY` | Env var → `keyParser(session)` | — | Required for all image generation calls |
| `DEFAULT_IMAGE_MODEL` | `endpoints/image_gen.py` constant | `google/gemini-3.1-flash-image-preview` | Default model when none specified |
| `CHEAP_LLM[0]` | `common.py` | `anthropic/claude-haiku-4.5` | Model used for "better context" prompt refinement |

---

## Differentiators vs Plain ChatGPT

- **Inline persistence**: Images are stored as files and served via authenticated URLs — they survive page refreshes, appear in history on reload, and are accessible across sessions without re-generation.
- **Automatic vision context**: Generated images are silently included in the next LLM call, enabling natural follow-up questions ("make it darker", "add a mountain in the background") using the model's vision capability.
- **Conversation-aware prompts**: The "better context" refinement step incorporates conversation summary, recent messages, deep extracted context, and memory pad — producing prompts grounded in the user's actual conversation rather than just the raw text input.
- **Two workflows**: The `/image` command for in-flow generation (no context switching) and the modal for standalone generation with granular control over context and model.
- **Image editing**: Both entry points support image editing — the modal via a drag-and-drop or click-to-upload zone, the `/image` command by automatically detecting the last generated image or a user-uploaded image in the current message as an `input_image` for the model.

---

## Image Editing

Image editing allows passing an existing image to the model alongside the prompt. The model decides whether to edit the image, use it as a style reference, or generate something new based on both.

### Modal (drag-drop or upload)

A dashed upload zone appears between the prompt textarea and model selector. You can:
- **Drag and drop** any image file onto the zone
- **Click the zone** to open a file picker

Once an image is loaded, a thumbnail is shown with an ×  remove button. When Generate is clicked, the image is included as `input_image` in the API request.

**Clearing**: the Clear button clears both the output preview and the uploaded input image.

### `/image` Command (auto-detect)

The `/image` command automatically detects an input image to pass via two priority rules:

1. **Current message attachment** (priority 1): if the user attached image(s) to the message that contains the `/image` command (via `query["images"]`), the first one is used.
2. **Last-turn generated image** (priority 2): if the immediately preceding assistant message has `generated_images` metadata, its first image is loaded from disk and used.

If neither is found, the command behaves as plain text-to-image generation.

Example flow:

```
/image a mountain at sunrise          ← generates a new image
[assistant shows an image]
/image make it night time              ← auto-detects last image, edits it
```

### API change

`POST /api/generate-image` now accepts an optional `input_image` field:

```json
{
  "prompt": "make the sky purple",
  "input_image": "data:image/png;base64,...",
  "model": "google/gemini-3.1-flash-image-preview",
  ...
}
```

When provided, the OpenRouter call changes from a plain string `content` to a multipart array:

```json
{
  "messages": [{
    "role": "user",
    "content": [
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
      {"type": "text", "text": "make the sky purple"}
    ]
  }],
  "modalities": ["image", "text"]
}
```

### Files modified

| File | Change |
|---|---|
| `endpoints/image_gen.py` | `generate_image_from_prompt()` gains `input_image` param; endpoint parses `input_image` from request JSON; OpenRouter call builds multipart content when `input_image` present; endpoint body refactored to call shared function |
| `Conversation.py` | `_handle_image_generation()` detects input image (current message attachment → last-turn generated → None); passes `input_image` to `generate_image_from_prompt()` |
| `interface/interface.html` | Upload zone HTML added to `#image-gen-modal`; CSS for drag-over state |
| `interface/image-gen-manager.js` | `_initUploadZone()`, `_loadInputImage()`, `_clearInputImage()` added; `state.inputImageDataUrl` tracked; payload includes `input_image` when set; `clearResult()` clears input image |
