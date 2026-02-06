# `call_llm.py` - Implementation Details

Internal documentation covering architecture, benchmarks, testing, and implementation details. For public API usage, see `call_llm_public.md`.

---

## Architecture Overview

### Dependencies

```
Required:
  - openai          # OpenAI-compatible client
  - requests        # HTTP requests for embeddings
  - numpy           # Embedding arrays
  - more_itertools  # Stream handling

Optional:
  - tiktoken        # Token counting (falls back to heuristic)
  - tenacity        # Retry handling (graceful fallback)
```

### Key Internal Functions

| Function | Purpose |
|----------|---------|
| `call_chat_model()` | Core chat API call with streaming |
| `_encode_image_reference()` | Convert image refs to data URLs |
| `_process_images_in_messages()` | Encode images in messages array |
| `_extract_text_from_openai_response()` | Stream chunk extraction |
| `call_with_stream()` | Stream/non-stream unification |
| `get_openai_embedding()` | Raw embedding API call |

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

### Token Counting

`get_gpt4_word_count()` estimates tokens:
- Uses `tiktoken` if available (exact count)
- Falls back to `len(text) // 4` heuristic

Used for context-window safety checks (100K token limit).

### Stream Handling

- `call_with_stream()`: Unifies streaming/non-streaming responses
- `make_stream()`: Converts between iterables and generators
- `check_if_stream_and_raise_exception()`: Validates stream input

### Math Formatting Pipeline (`math_formatting.py`)

The main `call_llm.py` wraps LLM streaming responses through `stream_with_math_formatting()` before yielding chunks. This module handles math delimiter escaping and formatting for the frontend MathJax renderer.

**File**: `math_formatting.py`

| Function | Purpose |
|----------|---------|
| `process_math_formatting(text)` | Doubles backslashes on math delimiters: `\[` → `\\[`, `\]` → `\\]`, `\(` → `\\(`, `\)` → `\\)`. This ensures MathJax sees `\[` in the DOM after markdown processing. |
| `_find_safe_split_point(text, min_keep=1)` | Finds a safe point to split the buffer that doesn't break a math delimiter across chunks. Returns index where text can be safely split. |
| `stream_with_math_formatting(response)` | Generator wrapping the OpenAI streaming response. Buffers tokens, finds safe split points, applies `process_math_formatting()` and `ensure_display_math_newlines()` before yielding. Includes a 5ms sleep per chunk to prevent GIL starvation. |
| `ensure_display_math_newlines(text)` | Inserts `\n` before `\\[` and after `\\]` when adjacent to non-newline content. Helps the frontend's `getTextAfterLastBreakpoint()` detect display math boundaries for section splitting. Only affects display math, not inline math (`\\(`, `\\)`). |

**Usage in `call_llm.py`**:

```python
# In call_chat_model_original():
for formatted_chunk in stream_with_math_formatting(response):
    yield formatted_chunk
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

### Image Encoding

`_encode_image_reference()` handles:
- Local paths → base64 data URLs with correct MIME type
- HTTP/HTTPS URLs → pass through
- Raw base64 → wrap as `data:image/png;base64,...`
- Data URLs → pass through

MIME type detection from extension: jpg/jpeg, png, webp, gif, tif/tiff.

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

On exception, `call_chat_model()` writes debug info to `error.json`:
- Model, text, images, temperature, system
- Error message and timestamp

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

`call_llm` raises `AssertionError` if estimated tokens > 100K. Reduce input or use larger-context model.
