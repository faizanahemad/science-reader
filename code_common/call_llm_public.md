# `call_llm.py` - Public API Reference

Toolkit for LLM interactions and embeddings via OpenRouter.

## Requirements

- **OpenRouter API key**: `OPENROUTER_API_KEY`

```python
keys = {"OPENROUTER_API_KEY": "sk-or-v1-..."}
```

---

## Quick Import

```python
from code_common.call_llm import (
    # Main LLM function
    call_llm,
    
    # Text embeddings
    get_query_embedding,
    get_document_embedding,
    get_document_embeddings,
    
    # Keyword extraction
    getKeywordsFromText,
    getKeywordsFromImage,
    getKeywordsFromImageText,
    
    # Image embeddings
    getImageQueryEmbedding,
    getImageDocumentEmbedding,
    
    # Joint text+image embeddings
    getJointQueryEmbedding,
    getJointDocumentEmbedding,
)

keys = {"OPENROUTER_API_KEY": "sk-or-v1-..."}
```

---

## `call_llm` - Main LLM Function

```python
def call_llm(
    keys: Dict[str, str],
    model_name: str,
    text: str = "",
    images: List[str] = [],
    temperature: float = 0.7,
    stream: bool = False,
    system: Optional[str] = None,
    messages: Optional[List[Dict[str, Any]]] = None,
) -> Union[str, Generator[str, None, None]]
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `keys` | `Dict[str, str]` | *required* | Credentials with `OPENROUTER_API_KEY` |
| `model_name` | `str` | *required* | Model identifier (e.g., `"openai/gpt-4o-mini"`) |
| `text` | `str` | `""` | User prompt (ignored if `messages` provided) |
| `images` | `List[str]` | `[]` | Image paths/URLs/base64 (ignored if `messages` provided) |
| `temperature` | `float` | `0.7` | Sampling temperature |
| `stream` | `bool` | `False` | Return generator of chunks if True |
| `system` | `Optional[str]` | `None` | System prompt (ignored if `messages` provided) |
| `messages` | `Optional[List[Dict]]` | `None` | OpenAI-style messages (overrides text/images/system) |

**Returns:** String (stream=False) or Generator (stream=True)

### Simple Mode Examples

```python
# Text only
out = call_llm(keys, "openai/gpt-4o-mini", "Say hello", stream=False)

# With system prompt
out = call_llm(keys, "openai/gpt-4o-mini", "What is 2+2?", system="Be concise.")

# With image (local file, URL, or base64)
out = call_llm(keys, "openai/gpt-4o-mini", "Describe this", images=["/path/to/image.jpg"])

# Streaming
for chunk in call_llm(keys, "openai/gpt-4o-mini", "Write a haiku", stream=True):
    print(chunk, end="", flush=True)
```

### Messages Mode Examples

```python
# Multi-turn conversation
messages = [
    {"role": "system", "content": "You are a math tutor."},
    {"role": "user", "content": "What is 2+2?"},
    {"role": "assistant", "content": "4"},
    {"role": "user", "content": "And 3+3?"},
]
out = call_llm(keys, "openai/gpt-4o-mini", messages=messages)

# With images in messages
messages = [
    {"role": "user", "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "/path/to/image.jpg"}}
    ]}
]
out = call_llm(keys, "openai/gpt-4o-mini", messages=messages)
```

---

## Text Embeddings

```python
get_query_embedding(text: str, keys: Dict) -> np.ndarray  # 1D
get_document_embedding(text: str, keys: Dict) -> np.ndarray  # 1D
get_document_embeddings(texts: List[str], keys: Dict) -> np.ndarray  # 2D
```

```python
q = get_query_embedding("running shoes", keys)  # (1536,)
d = get_document_embedding("Nike Air Zoom.", keys)  # (1536,)
docs = get_document_embeddings(["Doc1", "Doc2"], keys)  # (2, 1536)
```

---

## Keyword Extraction

```python
getKeywordsFromText(text, keys, *, llm_model="openai/gpt-4o-mini", max_keywords=30, temperature=0.0) -> List[str]
getKeywordsFromImage(images, keys, *, vlm_model="openai/gpt-4o-mini", max_keywords=30, temperature=0.0) -> List[str]
getKeywordsFromImageText(text, images, keys, *, vlm_model="openai/gpt-4o-mini", max_keywords=30, temperature=0.0) -> List[str]
```

Extracts short keyword phrases (1-3 words) for BM25-style indexing.

```python
kws = getKeywordsFromText("Nike running shoes for marathon", keys)
# ['Nike', 'running shoes', 'marathon', ...]

kws = getKeywordsFromImage("/path/to/dog.jpg", keys)
# ['golden retriever', 'outdoor park', 'adult dog', ...]

kws = getKeywordsFromImageText("What breed?", "/path/to/dog.jpg", keys)
# ['dog breed', 'breed identification', 'golden retriever', ...]
```

---

## Image Embeddings

```python
getImageQueryEmbedding(image, keys, *, vlm_model, use_keywords=True, max_keywords=30, temperature=0.2) -> np.ndarray
getImageDocumentEmbedding(image, keys, *, vlm_model, use_keywords=True, max_keywords=30, temperature=0.2) -> np.ndarray
```

Converts image → VLM description → text embedding.

- **Query embedding**: Concise, retrieval-focused description
- **Document embedding**: Exhaustive description for indexing

```python
query_emb = getImageQueryEmbedding("/path/to/photo.jpg", keys)  # (1536,)
doc_emb = getImageDocumentEmbedding("/path/to/photo.jpg", keys)  # (1536,)
```

---

## Joint Text+Image Embeddings

```python
getJointQueryEmbedding(text, image, keys, *, mode="separate", vlm_model, use_keywords=True, max_keywords=30, temperature=0.2, text_weight=1.0, image_weight=1.0) -> np.ndarray
getJointDocumentEmbedding(text, image, keys, *, mode="separate", vlm_model, use_keywords=True, max_keywords=30, temperature=0.2, text_weight=1.0, image_weight=1.0) -> np.ndarray
```

| Mode | Description |
|------|-------------|
| `"separate"` | Embed text + embed image, combine with weighted mean |
| `"vlm"` | Send text+image to VLM, embed combined description |

```python
# VLM mode (recommended for related text+image)
emb = getJointQueryEmbedding("What breed?", "/path/dog.jpg", keys, mode="vlm")

# Separate mode with custom weights
emb = getJointDocumentEmbedding("Golden Retriever", "/path/dog.jpg", keys, 
                                 mode="separate", text_weight=0.7, image_weight=1.0)
```

---

## Common Models (OpenRouter)

| Model | Use Case |
|-------|----------|
| `openai/gpt-4o-mini` | Fast, cheap, good for most tasks |
| `openai/gpt-4o` | Higher quality |
| `anthropic/claude-3.5-sonnet` | High quality reasoning |
| `google/gemini-2.0-flash-exp` | Fast multimodal |

---

## Image Generation (OpenRouter)

Image generation is **not** handled by `call_llm`. It uses a dedicated HTTP call to OpenRouter's chat completions endpoint with `modalities: ["image", "text"]`.

See `endpoints/image_gen.py` for the implementation:

```python
from endpoints.image_gen import generate_image_from_prompt, DEFAULT_IMAGE_MODEL

result = generate_image_from_prompt(
    prompt="A futuristic city at sunset",
    keys=keys,                         # must contain OPENROUTER_API_KEY
    model=DEFAULT_IMAGE_MODEL,         # "google/gemini-3.1-flash-image-preview"
)

# result = {"images": ["data:image/png;base64,..."], "text": "...", "error": None}
if result["error"]:
    print("Failed:", result["error"])
else:
    data_uri = result["images"][0]     # base64 PNG data URI, ready to embed in <img src>
```

### Available Image Models (via OpenRouter)

| OpenRouter Name | Model ID | Notes |
|---|---|---|
| Nano Banana 2 (default) | `google/gemini-3.1-flash-image-preview` | Best quality, recommended |
| Nano Banana | `google/gemini-2.5-flash-image` | Faster, slightly lower quality |
| Nano Banana Pro | `google/gemini-3-pro-image-preview` | Highest quality, slower |
| GPT-5 Image Mini | `openai/gpt-5-image-mini` | OpenAI alternative |
| GPT-5 Image | `openai/gpt-5-image` | OpenAI highest quality |

### Prompt Refinement (Better Context)

An intermediate LLM call can refine the raw prompt before sending to the image model:

```python
from endpoints.image_gen import _refine_prompt_with_llm, _build_image_prompt
from endpoints.llm_edit_utils import gather_conversation_context

# 1. Gather conversation context
context_parts = gather_conversation_context(
    conversation, prompt,
    include_context=True, deep_context=True,
    include_summary=True, include_messages=True,
    history_count=2,
)

# 2. Refine via cheap LLM (claude-haiku)
refined_prompt = _refine_prompt_with_llm(prompt, context_parts, keys)

# 3. Generate
result = generate_image_from_prompt(refined_prompt, keys)
```

---

## Image Input Formats

All image parameters accept:

| Format | Example |
|--------|---------|
| Local file path | `"/path/to/image.jpg"` |
| HTTP/HTTPS URL | `"https://example.com/img.jpg"` |
| Raw base64 | `"iVBORw0KGgo..."` |
| Data URL | `"data:image/jpeg;base64,..."` |

---

## Error Handling

```python
# Rate limit handling
import time
try:
    result = call_llm(...)
except Exception as e:
    if "rate" in str(e).lower():
        time.sleep(5)
        result = call_llm(...)
```

**Context window**: `call_llm` raises `AssertionError` if estimated tokens exceed 100K.

---

For implementation details, benchmarks, and testing, see `call_llm_impl.md`.
