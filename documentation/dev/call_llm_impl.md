# `call_llm.py` - Implementation Details

Internal documentation covering architecture, benchmarks, testing, and implementation details. For public API usage, see `call_llm_public.md`.

---

## Architecture Overview

### Two-File Split: Shim + Engine

The LLM calling stack is split across two files with distinct responsibilities:

| File | Role | Consumers |
|------|------|-----------|
| `call_llm.py` (root) | UI shim — math formatting, `base_system` prompt, `CallLLm`/`CallMultipleLLM`/`MockCallLLm` classes | `Conversation.py`, endpoints, agents, tests |
| `code_common/call_llm.py` | Engine — API calls, image encoding, token limits, embeddings, keyword extraction | TMS (`truth_management_system/`), extension (`endpoints/ext_*.py`), and the root shim |

**Root shim responsibilities (UI concerns only)**:
- `base_system` prompt with `math_formatting_instructions`
- Math formatting wrapper (`stream_text_with_math_formatting` / `process_math_formatting`)
- Image-specific system prompt augmentation
- `CallMultipleLLM` (multi-model streaming via `stream_multiple_models`)
- `MockCallLLm` (test fixture with math-formatted mock response)

**Engine responsibilities (`code_common/call_llm.py`)**:
- All OpenRouter API calls (`call_chat_model`, `call_llm`)
- Image validation (`VISION_CAPABLE_MODELS`) and encoding (`_encode_image_reference`)
- Per-model token limit enforcement (`_get_token_limit`)
- Embeddings, keyword extraction, joint embeddings

All models route through OpenRouter. There is no direct OpenAI API path in the shim.

### Dependencies

```
code_common/call_llm.py (engine):
  Required:
    - openai          # OpenAI-compatible client (pointed at OpenRouter)
    - requests        # HTTP requests for embeddings
    - numpy           # Embedding arrays
    - more_itertools  # Stream handling
  Optional:
    - tiktoken        # Token counting (falls back to heuristic)
    - tenacity        # RetryError handling (graceful fallback)

call_llm.py (root shim):
  - code_common/call_llm.py  # Engine
  - math_formatting.py       # stream_text_with_math_formatting, process_math_formatting
  - prompts.py               # math_formatting_instructions for base_system
  - common.py                # checkNoneOrEmpty, collapsible_wrapper, EXPENSIVE_LLM, CHEAP_LLM
```

### Key Internal Functions

**`code_common/call_llm.py` (engine)**:

| Function | Purpose |
|----------|---------|
| `call_chat_model()` | Core chat API call — always uses OpenRouter, yields text strings |
| `call_llm()` | High-level entry point: image validation, encoding, token limits, stream handling |
| `_encode_image_reference()` | Convert image refs to data URLs (local paths, URLs, base64, data URLs) |
| `_process_images_in_messages()` | Encode images in messages array |
| `_extract_text_from_openai_response()` | Extract text chunks from OpenAI streaming response |
| `call_with_stream()` | Stream/non-stream unification |
| `_get_token_limit()` | Per-model context window limit lookup |
| `get_openai_embedding()` | Raw embedding API call |

**`call_llm.py` (root shim)**:

| Function/Class | Purpose |
|----------------|---------|
| `call_chat_model()` | Wraps `code_common`'s `call_chat_model` with `stream_text_with_math_formatting` |
| `CallLLm.__call__()` | Prepends `base_system`, delegates to `code_common.call_llm`, wraps result with math formatting |
| `CallMultipleLLM` | Multi-model streaming; delegates to `stream_multiple_models` from `common.py` |
| `MockCallLLm` | Test fixture returning hardcoded math-formatted response |

### Embedding Model

Uses `openai/text-embedding-3-small` via OpenRouter. The `OpenAIEmbeddingsParallel` class handles batching and parallel execution with a 256-worker thread pool.

---

## Keyword Extraction Details

### Categories Extracted from Images

The VLM extracts keywords across 8 categories for comprehensive BM25 retrieval:

| Category | Description | Examples |
|----------|-------------|----------|
| Subjects | Main subjects, people, animals | 'golden retriever', 'businessman' |
| Objects | Notable items, products | 'laptop', 'coffee cup' |
| Actions | What is happening | 'running', 'typing' |
| Setting | Location, environment | 'office', 'beach sunset' |
| Text/OCR | Readable text, brands | 'Nike logo', 'stop sign' |
| Attributes | Visual qualities | 'vintage', 'blue striped' |
| Potential Queries | Questions about image | 'dog breed identification' |
| Concepts | Abstract themes | 'teamwork', 'celebration' |

### Keyword Post-Processing

`_dedupe_and_clip_keywords()` normalizes extracted keywords:
- Removes duplicates (case-insensitive)
- Strips punctuation and excess whitespace
- Limits to `max_words_per_keyword` (default: 3)
- Clips to `max_keywords` count

---

## Image Embedding Prompts

### Query Embedding Prompt Focus

Optimized for retrieval intent - concise and discriminative:
1. Main subjects with specific IDs
2. Key objects, products, tools
3. Actions and interactions
4. Setting and environment
5. Visual attributes (colors, textures)
6. Text/OCR content
7. 2-3 potential questions
8. Unique identifiers

### Document Embedding Prompt Focus

Optimized for indexing - exhaustive coverage:
1. **Detailed Description**: All subjects with attributes, all objects, spatial relationships, actions, visual qualities
2. **Text/Labels (OCR)**: All readable text, brands, logos
3. **Potential Questions**: Identification, how-to, comparison, troubleshooting (3-5 questions)
4. **Key Observations**: What stands out, domain/category, required expertise
5. **Semantic Meaning**: Purpose, context, story conveyed

---

## Joint Embedding Modes

### `mode="separate"`

1. Embed text directly via `get_query/document_embedding()`
2. Generate image description via VLM, embed that
3. Combine with weighted mean: `(text_weight * text_emb + image_weight * image_emb) / (text_weight + image_weight)`

**Use when**: Text and image are independent or loosely related.

### `mode="vlm"` (Recommended for Multimodal)

1. Send text + image together to VLM
2. VLM generates a combined description aligning image content with text intent
3. Embed the combined description

**Use when**: Text provides context/intent for the image (e.g., questions about the image).

### Joint Document Embedding Includes

1. **Text-Image Relationship**: How text relates to image content
2. **Comprehensive Image Description**: All visible elements guided by text context
3. **Combined Semantic Meaning**: Overall meaning when text and image are together
4. **Potential Questions**: 4-6 questions this combination could answer
5. **Key Observations**: Domain relevance, uniqueness, corrections text provides

---

## Performance Benchmarks

Benchmarked on `openai/gpt-4o-mini` via OpenRouter:

### Summary Table

| Function | Time (s) | Notes |
|----------|----------|-------|
| **Text Embeddings** | | |
| `get_query_embedding` | ~1.1 | Single text |
| `get_document_embedding` | ~0.8 | Single text |
| `get_document_embeddings` (3 docs) | ~0.7 | Batch embedding |
| **LLM Calls** | | |
| `call_llm` (text only) | ~1.3 | Non-streaming |
| `call_llm` (text, stream) | ~1.0 | Streaming |
| `call_llm` (with image) | ~3.1 | +2s image overhead |
| `call_llm` (messages, text) | ~1.0 | Multi-turn |
| `call_llm` (messages, image) | ~2.4 | Multi-turn with image |
| **Keyword Extraction** | | |
| `getKeywordsFromText` | ~1.1 | |
| `getKeywordsFromImage` | ~3.9 | |
| `getKeywordsFromImageText` | ~4.2 | |
| **Image Embeddings** | | |
| `getImageQueryEmbedding` | ~14.2 | VLM + keywords + embed |
| `getImageDocumentEmbedding` | ~16.0 | VLM + keywords + embed |
| **Joint Embeddings** | | |
| `getJointQueryEmbedding` (separate) | ~16.8 | Text + image embed + combine |
| `getJointQueryEmbedding` (vlm) | ~14.7 | VLM combined + embed |
| `getJointDocumentEmbedding` (separate) | ~22.4 | Slowest: multiple API calls |
| `getJointDocumentEmbedding` (vlm) | ~19.1 | VLM combined + embed |

### Performance Tiers

1. **Fast (~0.7-1.3s)**: Text embeddings, simple LLM calls
2. **Medium (~2-4s)**: Image LLM calls, keyword extraction
3. **Slow (~14-22s)**: Image/joint embeddings (multiple API calls)

### Optimization Tips

- Set `use_keywords=False` to reduce image embedding time by ~4-5s
- Use `mode="vlm"` for joint embeddings (faster, fewer API calls)
- Use streaming for interactive applications
- Batch with `get_document_embeddings()` when possible

---

## Running Tests

### Basic Usage

```bash
python code_common/test_call_llm.py --openrouter-api-key "$OPENROUTER_API_KEY"
```

### With Custom Models

```bash
python code_common/test_call_llm.py \
  --openrouter-api-key "$OPENROUTER_API_KEY" \
  --model "openai/gpt-4o-mini" \
  --vlm-model "openai/gpt-4o-mini"
```

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--openrouter-api-key` | *required* | OpenRouter API key |
| `--model` | `openai/gpt-4o-mini` | Model for text tests |
| `--vlm-model` | Same as `--model` | Model for vision tests |
| `--timeout-seconds` | `30` | Streaming timeout |
| `--max-keywords` | `15` | Max keywords in tests |
| `--image-url` | `None` | URL instead of local test image |

### Running Benchmarks

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
python code_common/benchmark_call_llm.py
```

### Test Coverage

- ✓ Text embeddings (query, document, batch)
- ✓ LLM calls (text-only, streaming, non-streaming)
- ✓ Messages mode (multi-turn text, with images)
- ✓ Image calls (image-only, image+text)
- ✓ Keyword extraction (text, image, image+text)
- ✓ Image embeddings (query, document)
- ✓ Joint embeddings (separate mode, vlm mode)

---

## Internal Utilities

### Token Counting and Per-Model Limits

`get_gpt4_word_count()` estimates tokens:
- Uses `tiktoken` if available (exact count)
- Falls back to `len(text) // 4` heuristic

`_get_token_limit(model_name)` returns the per-model context window limit used by `call_llm()`. Limits are determined by model family membership (checked against `common.py` model lists with a lazy import to avoid circular deps):

| Model family | Token limit |
|---|---|
| `CHEAP_LONG_CONTEXT_LLM` (e.g., Gemini 2.0 Flash) | 800K |
| `LONG_CONTEXT_LLM` (e.g., Gemini 1.5 Pro) | 900K |
| `EXPENSIVE_LLM` (e.g., GPT-4o) | 200K |
| Google Gemini Flash 1.5 / Pro 1.5 | 400K |
| Other Gemini models | 500K |
| Cohere, Llama-3.1, DeepSeek, Jamba | 100K |
| Mistral large / Pixtral large | 100K |
| Other Mistral | 146K |
| Claude 3 family | 180K |
| Other Anthropic | 160K |
| `openai/` prefixed models | 160K |
| Other known models | 160K |
| Unknown models (default) | 48K |

`call_llm()` raises `AssertionError` if the estimated token count exceeds the model's limit.

### Stream Handling

- `call_with_stream()`: Unifies streaming/non-streaming responses
- `make_stream()`: Converts between iterables and generators
- `check_if_stream_and_raise_exception()`: Validates stream input

### Math Formatting Pipeline (`math_formatting.py`)

The root `call_llm.py` shim wraps `code_common`'s text output with math formatting before yielding to callers. This module handles math delimiter escaping and formatting for the frontend MathJax renderer.

**File**: `math_formatting.py`

| Function | Purpose |
|----------|---------|
| `process_math_formatting(text)` | Doubles backslashes on math delimiters: `\[` → `\\[`, `\]` → `\\]`, `\(` → `\\(`, `\)` → `\\)`. This ensures MathJax sees `\[` in the DOM after markdown processing. |
| `_find_safe_split_point(text, min_keep=1)` | Finds a safe point to split the buffer that doesn't break a math delimiter across chunks. Returns index where text can be safely split. |
| `stream_with_math_formatting(response)` | Generator wrapping a **raw OpenAI streaming response object**. Extracts text via `.model_dump()`, buffers tokens, applies `process_math_formatting()` and `ensure_display_math_newlines()`. Used for any code that has a direct OpenAI response object. |
| `stream_text_with_math_formatting(text_iterator)` | Generator wrapping an **iterator of plain text strings** (e.g., from `code_common/call_llm.py`). Same buffering/formatting logic as `stream_with_math_formatting` but accepts already-extracted text. Used by the root shim. |
| `ensure_display_math_newlines(text)` | Inserts `\n` before `\\[` and after `\\]` when adjacent to non-newline content. Helps the frontend's `getTextAfterLastBreakpoint()` detect display math boundaries for section splitting. Only affects display math, not inline math (`\\(`, `\\)`). |

**Usage in the root shim**:

```python
# In call_llm.py — call_chat_model() wraps code_common's text output:
raw_stream = _cc_call_chat_model(model, text, images, temperature, system, keys)
for chunk in stream_text_with_math_formatting(raw_stream):
    yield chunk

# In CallLLm.__call__() for streaming:
result = _cc_call_llm(keys=..., model_name=..., stream=True, ...)
return stream_text_with_math_formatting(result)

# In CallLLm.__call__() for non-streaming:
result = _cc_call_llm(keys=..., model_name=..., stream=False, ...)
formatted = process_math_formatting(result)
return ensure_display_math_newlines(formatted)
```

**How the escaping works**:
1. LLM outputs `\[E=mc^2\]` (raw tokens)
2. `process_math_formatting`: `\[E=mc^2\]` → `\\[E=mc^2\\]`
3. `ensure_display_math_newlines`: adds `\n` around `\\[` and `\\]`
4. JSON serialization on wire: `\\[` → `\\\\[` in JSON text
5. Frontend `JSON.parse`: `\\\\[` → `\\[` in JS string
6. `marked.marked()` passes `\\[` through to HTML
7. MathJax sees `\\[` in innerHTML → interprets as display math

**Testing**: Run `python math_formatting.py` for the built-in 7-test suite covering character-by-character streaming, word-by-word streaming, boundary splits, and edge cases.

### Image Validation

`VISION_CAPABLE_MODELS` is a `frozenset` of 39 model identifiers known to accept image input. `call_llm()` raises `ValueError` if `images` is non-empty and `model_name` is not in this set.

Models in the set span: OpenAI (`gpt-4o`, `gpt-4-turbo`, `o1`, `gpt-4.5-preview`, `gpt-5.1`/`gpt-5.2`), Anthropic Claude 3/3.5/3.7/4/Haiku/Sonnet/Opus variants, Google Gemini (Flash/Pro/2.0/2.5/3.x), Mistral Pixtral, Meta Llama Vision, MiniMax, Qwen VL, Fireworks FireLLaVA, LLaVA-Yi.

To check before calling:
```python
from code_common.call_llm import VISION_CAPABLE_MODELS
if model not in VISION_CAPABLE_MODELS:
    raise ValueError(f"{model} does not support images")
```

### Image Encoding

`_encode_image_reference()` handles all image reference types:
- Local paths → base64 data URLs with correct MIME type (jpg/jpeg, png, webp, gif, tif/tiff)
- `data:image/jpg;...` → normalized to `data:image/jpeg;...` (Anthropic/OpenRouter reject `image/jpg`)
- HTTP/HTTPS URLs → pass through
- Raw base64 → wrap as `data:image/png;base64,...`
- Data URLs → pass through

`_process_images_in_messages()` applies `_encode_image_reference()` to all `image_url` parts in an OpenAI-style messages array.

### JSON Extraction

`_extract_first_json_object()` parses LLM responses:
- Strips markdown code fences
- Finds first `{...}` block
- Returns None on parse failure (graceful fallback)

---

## Error Handling

### Embedding Fallback

`get_openai_embedding()` implements recursive retry:
- On failure with `ctx_length > 2000`, retries with half values
- Handles extremely large inputs gracefully

### LLM Error Logging

On exception, `code_common/call_llm.py`'s `call_chat_model()` writes debug info to `error.json`:
- Model, text, images, temperature, system, keys
- Error message and timestamp

The root shim's `test_error_replay()` reads this file and replays the call through `call_chat_model()` (which delegates to code_common) for debugging.

---

## Thread Pools

```python
embed_executor = ThreadPoolExecutor(max_workers=256)  # Embedding parallelism
executor = ThreadPoolExecutor(max_workers=256)        # General async
```

`get_async_future()` wraps any function for async execution with traceback preservation.

---

## Troubleshooting

### Image Format Errors

Some providers reject certain formats:
1. Try HTTPS URLs instead of local paths
2. Use PNG instead of JPEG
3. Resize to ~1024px max dimension

### Rate Limits

OpenRouter may rate-limit. Implement backoff:
```python
import time
try:
    result = call_llm(...)
except Exception as e:
    if "rate" in str(e).lower():
        time.sleep(5)
        result = call_llm(...)
```

### Context Window Exceeded

`call_llm` raises `AssertionError` if estimated tokens exceed the per-model limit (see Token Counting section above). For large inputs, use a model from `CHEAP_LONG_CONTEXT_LLM` or `LONG_CONTEXT_LLM` (limits up to 900K). Unknown models default to 48K.
