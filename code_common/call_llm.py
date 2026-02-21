import base64
import logging
import os.path
import string
import uuid
from datetime import datetime
from uuid import uuid4

# NOTE: `dill` was imported historically but is not used in this module.
# Keeping it as a hard dependency breaks environments that don't have dill installed.
import re
import traceback
import numpy as np

try:
    # `tiktoken` is only used for token counting / logging.
    # Keep it optional so the module can run in minimal environments.
    import tiktoken  # type: ignore
except Exception:  # pragma: no cover
    tiktoken = None
from copy import deepcopy, copy
from functools import partial
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
    Future,
    ProcessPoolExecutor,
)
import json

from typing import Generator


import openai
from typing import Callable, Any, List, Dict, Tuple, Optional, Union


from loggers import getLoggers

logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(
    __name__, logging.INFO, logging.INFO, logging.ERROR, logging.INFO
)

try:
    # `tenacity` is optional. This module only needs `RetryError` for defensive
    # handling in `call_with_stream`; the retry decorators are not used here.
    from tenacity import RetryError  # type: ignore
except Exception:  # pragma: no cover

    class RetryError(Exception):
        """Fallback RetryError when `tenacity` isn't installed."""


import asyncio
import threading

from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import ProcessPoolExecutor
import time
import requests
import json
import random
import more_itertools
import types
from more_itertools import peekable
import inspect


import time
from collections import deque
from threading import Lock

if tiktoken is not None:
    gpt4_enc = tiktoken.encoding_for_model("gpt-4")
else:  # pragma: no cover
    gpt4_enc = None

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


def _get_token_limit(model_name: str) -> int:
    try:
        from common import (
            CHEAP_LONG_CONTEXT_LLM,
            LONG_CONTEXT_LLM,
            EXPENSIVE_LLM,
            CHEAP_LLM,
            VERY_CHEAP_LLM,
        )
    except ImportError:
        return MODEL_TOKEN_LIMITS["default"]

    if model_name in CHEAP_LONG_CONTEXT_LLM:
        return MODEL_TOKEN_LIMITS["cheap_long_context"]
    elif model_name in LONG_CONTEXT_LLM:
        return MODEL_TOKEN_LIMITS["long_context"]
    elif model_name in EXPENSIVE_LLM:
        return MODEL_TOKEN_LIMITS["expensive"]
    elif (
        "google/gemini-flash-1.5" in model_name
        or "google/gemini-flash-1.5-8b" in model_name
        or "google/gemini-pro-1.5" in model_name
    ):
        return MODEL_TOKEN_LIMITS["gemini_flash"]
    elif "gemini" in model_name:
        return MODEL_TOKEN_LIMITS["gemini_other"]
    elif (
        "cohere/command-r-plus" in model_name
        or "llama-3.1" in model_name
        or "deepseek" in model_name
        or "jamba-1-5" in model_name
    ):
        return MODEL_TOKEN_LIMITS["cohere_llama_deepseek_jamba"]
    elif (
        "mistralai/pixtral-large-2411" in model_name
        or "mistralai/mistral-large-2411" in model_name
    ):
        return MODEL_TOKEN_LIMITS["mistral_large_pixtral"]
    elif "mistralai" in model_name:
        return MODEL_TOKEN_LIMITS["mistralai_other"]
    elif "claude-3" in model_name:
        return MODEL_TOKEN_LIMITS["claude_3"]
    elif "anthropic" in model_name:
        return MODEL_TOKEN_LIMITS["anthropic_other"]
    elif "openai" in model_name:
        return MODEL_TOKEN_LIMITS["openai_prefixed"]
    elif (
        model_name in VERY_CHEAP_LLM
        or model_name in CHEAP_LLM
        or model_name in EXPENSIVE_LLM
    ):
        return MODEL_TOKEN_LIMITS["known_cheap_expensive"]
    else:
        return MODEL_TOKEN_LIMITS["default"]


VISION_CAPABLE_MODELS = frozenset(
    {
        "o1",
        "gpt-4-turbo",
        "gpt-4o",
        "gpt-4-vision-preview",
        "gpt-4.5-preview",
        "gpt-5.1",
        "gpt-5.2",
        "minimax/minimax-01",
        "anthropic/claude-3-haiku:beta",
        "qwen/qvq-72b-preview",
        "meta-llama/llama-3.2-90b-vision-instruct",
        "anthropic/claude-3-opus:beta",
        "anthropic/claude-3-sonnet:beta",
        "anthropic/claude-3.5-sonnet:beta",
        "fireworks/firellava-13b",
        "openai/gpt-4o-mini",
        "openai/o1",
        "openai/o1-pro",
        "anthropic/claude-haiku-4.5",
        "openai/gpt-4o",
        "anthropic/claude-sonnet-4",
        "anthropic/claude-opus-4",
        "anthropic/claude-opus-4.5",
        "mistralai/pixtral-large-2411",
        "google/gemini-pro-1.5",
        "google/gemini-flash-1.5",
        "liuhaotian/llava-yi-34b",
        "openai/chatgpt-4o-latest",
        "google/gemini-3-flash-preview",
        "google/gemini-3-pro-preview",
        "openai/gpt-5.2",
        "anthropic/claude-4-opus-20250522",
        "anthropic/claude-4-sonnet-20250522",
        "google/gemini-2.5-pro",
        "google/gemini-2.0-flash-001",
        "google/gemini-2.5-flash",
        "anthropic/claude-3.7-sonnet",
        "anthropic/claude-3.7-sonnet:beta",
        "anthropic/claude-sonnet-4.5",
        "anthropic/claude-sonnet-4.6",
        "google/gemini-3.1-pro-preview",
    }
)


def get_gpt4_word_count(my_string):
    """
    Approximate GPT-4 token count for a string.

    - If `tiktoken` is installed, this returns the exact token count under the GPT-4
      encoding.
    - Otherwise, it falls back to a rough heuristic based on character length.

    This function is used for context-window safety checks and debug logging; it is
    *not* used to construct the request payload.
    """
    if tiktoken is not None:
        enc = tiktoken.encoding_for_model("gpt-4")
        str_encoded = enc.encode(my_string)
        return len(str_encoded)
    # Fallback heuristic: ~4 characters per token for English-like text.
    # Ensure non-zero for non-empty strings.
    s = my_string or ""
    return max(0, (len(s) + 3) // 4)


def check_if_stream_and_raise_exception(iterable_or_str):
    if isinstance(iterable_or_str, str):
        # If it's a string, just return it as it is.
        return iterable_or_str
    elif isinstance(iterable_or_str, more_itertools.more.peekable):
        return iterable_or_str
    elif isinstance(iterable_or_str, types.GeneratorType):
        # If it's a generator, we need to peek at it.
        try:
            peek_start = time.perf_counter()
            logger.warning(
                "[code_common] check_if_stream_and_raise_exception peek start | t=%.3fs",
                peek_start,
            )
            peeked = peekable(iterable_or_str)
            peek_val = (
                peeked.peek()
            )  # This will raise StopIteration if the generator is empty.
            logger.warning(
                "[code_common] check_if_stream_and_raise_exception peek done | dt=%.3fs",
                time.perf_counter() - peek_start,
            )
            return peeked
        except StopIteration:
            # Here you could handle the empty generator case.
            raise
        except Exception as e:
            # Here you could handle other exceptions.
            raise e
    elif isinstance(iterable_or_str, peekable):
        return iterable_or_str
    else:
        # If it's not a string or a generator, raise an exception.
        raise ValueError("Unexpected input type.")


def make_stream(res, do_stream: bool):
    is_generator = inspect.isgenerator(res)
    if is_generator and do_stream:
        res = check_if_stream_and_raise_exception(res)
        return res
    if do_stream and not is_generator:
        assert (
            isinstance(res, (str, list, tuple))
            or isinstance(res, more_itertools.more.peekable)
            or isinstance(res, peekable)
            or hasattr(res, "__iter__")
            or hasattr(res, "__next__")
        )
        return convert_iterable_to_stream(res)
    elif not do_stream and is_generator:
        return convert_stream_to_iterable(res)
    return res


def call_with_stream(fn, do_stream, *args, **kwargs):
    _cws_start = time.perf_counter()
    # Get function/model name for logging
    _fn_name = getattr(fn, "__name__", str(fn))
    # Try to get model name from args if available
    _model_hint = args[0] if args else "unknown"
    logger.warning(
        "[code_common] call_with_stream start | fn=%s | model=%s | do_stream=%s | t=%.3fs",
        _fn_name,
        _model_hint,
        do_stream,
        _cws_start,
    )

    backup = kwargs.pop("backup_function", None)
    try:
        res = fn(*args, **kwargs)
    except RetryError as e:
        logger.error(f"RetryError: {e}")
        if backup is not None:
            res = backup(*args, **kwargs)
        else:
            raise e
    except Exception as e:
        trace = traceback.format_exc()
        logger.error(f"Exception: {e}, \n{trace}")
        if backup is not None:
            res = backup(*args, **kwargs)
        else:
            raise e
    is_generator = inspect.isgenerator(res)
    logger.warning(
        "[code_common] call_with_stream fn returned | is_generator=%s | dt=%.3fs",
        is_generator,
        time.perf_counter() - _cws_start,
    )
    if is_generator:
        res = check_if_stream_and_raise_exception(res)
    logger.warning(
        "[code_common] call_with_stream returning | dt=%.3fs",
        time.perf_counter() - _cws_start,
    )
    if do_stream and not is_generator:
        assert isinstance(res, (str, list, tuple))
        return convert_iterable_to_stream(res)
    elif not do_stream and is_generator:
        return convert_stream_to_iterable(res)
    return res


def convert_iterable_to_stream(iterable):
    for t in iterable:
        yield t


def convert_stream_to_iterable(stream, join_strings=True):
    """Convert a stream/generator to a list or concatenated string.

    This function periodically yields control (via time.sleep(0)) to allow
    other threads to run, preventing GIL starvation during long-running
    stream consumption.

    Args:
        stream: An iterable/generator to consume
        join_strings: If True and all items are strings, join them into one string

    Returns:
        Either a joined string or list of items from the stream
    """
    ans = []
    chunk_count = 0
    for t in stream:
        ans.append(t)
        chunk_count += 1
        # Every 5 chunks, yield control to other threads to prevent GIL starvation
        # Using 0.001s (1ms) instead of 0 to force actual thread scheduling
        if chunk_count % 5 == 0:
            time.sleep(0.001)
    if ans and isinstance(ans[0], str) and join_strings:
        ans = "".join(ans)
    return ans


def _extract_text_from_openai_response(response: Any) -> Generator[str, None, None]:
    """
    Extract text from an OpenAI-style chunk.
    """

    for chk in response:
        # 'chk' is the streamed chunk response from the LLM
        chunk = chk.model_dump()

        if (
            "choices" not in chunk
            or len(chunk["choices"]) == 0
            or "delta" not in chunk["choices"][0]
        ):
            continue
        # Some completions might not have 'content' in the delta:
        if "content" not in chunk["choices"][0]["delta"]:
            continue

        text_content = chunk["choices"][0]["delta"]["content"]
        if not isinstance(text_content, str):
            continue
        yield text_content


def call_chat_model(model, text, images, temperature, system, keys, messages=None):
    """
    Core chat model function that calls OpenRouter/OpenAI-compatible APIs.

    Parameters
    ----------
    model : str
        Model identifier (e.g., "openai/gpt-4o-mini").
    text : str
        User prompt text (ignored if `messages` is provided).
    images : list
        List of encoded image URLs/data URLs (ignored if `messages` is provided).
    temperature : float
        Sampling temperature.
    system : str or None
        System prompt (ignored if `messages` is provided).
    keys : dict
        Credentials dict with `OPENROUTER_API_KEY`.
    messages : list or None
        If provided, use this as the messages array directly (OpenAI chat completions style).
        When provided, `text`, `images`, and `system` are ignored.

    Yields
    ------
    str
        Text chunks from the streaming response.
    """
    api_key = keys["OPENROUTER_API_KEY"]
    extras = dict(
        base_url="https://openrouter.ai/api/v1",
    )
    openrouter_used = True

    extras_2 = (
        dict(stop=["</s>", "Human:", "User:", "<|eot_id|>", "<|/assistant_response|>"])
        if "claude" in model or openrouter_used
        else dict()
    )

    from openai import OpenAI

    client = OpenAI(api_key=api_key, **extras)

    # If messages is provided directly, use it; otherwise construct from text/images/system
    if messages is not None:
        # Use the provided messages array directly
        pass
    elif len(images) > 0:
        messages = []
        if system is not None and isinstance(system, str):
            messages.append({"role": "system", "content": system})
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    *[
                        {"type": "image_url", "image_url": {"url": base64_image}}
                        for base64_image in images
                    ],
                ],
            }
        )
    else:
        messages = []
        if system is not None and isinstance(system, str):
            messages.append({"role": "system", "content": system})
        messages.append(
            {
                "role": "user",
                "content": text,
            }
        )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            stream=True,
            timeout=60,
            # max_tokens=300,
            **extras_2,
        )

        for formatted_chunk in _extract_text_from_openai_response(response):
            yield formatted_chunk

    except Exception as e:
        logger.error(
            f"[call_chat_model_original]: Error in calling chat model {model} with error {str(e)}, more info: openrouter_used = {openrouter_used}, len messages = {len(messages)}, extras = {extras}, extras_2 = {extras_2}"
        )
        # Save function parameters to JSON for debugging/replay
        error_data = {
            "model": model,
            "text": text,
            "images": images,
            "temperature": temperature,
            "system": system,
            "keys": keys,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }
        with open("error.json", "w") as f:
            json.dump(error_data, f, indent=2)
        traceback.print_exc()
        raise e


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def _encode_image_reference(img: str) -> str:
    """
    Encode a single image reference to a data URL or pass through URLs.

    Parameters
    ----------
    img : str
        Can be:
        - A local file path (will be base64-encoded with correct MIME type)
        - An HTTP/HTTPS URL (passed through as-is)
        - A raw base64 string (wrapped as data:image/png;base64,...)
        - A data URL (passed through as-is)

    Returns
    -------
    str
        Encoded image URL suitable for OpenAI-compatible APIs.
    """
    if not isinstance(img, str):
        return img

    img_stripped = img.strip()

    if img_stripped.lower().startswith("data:image/"):
        if img_stripped.lower().startswith("data:image/jpg;"):
            img_stripped = "data:image/jpeg;" + img_stripped[len("data:image/jpg;") :]
        return img_stripped

    # Local file path - encode with proper MIME type
    if os.path.exists(img):
        base64_image = encode_image(img)
        ext = os.path.splitext(img)[1].lower().lstrip(".")
        mime_map = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
            "gif": "image/gif",
            "tif": "image/tiff",
            "tiff": "image/tiff",
        }
        mime_type = mime_map.get(ext, "image/png")
        return f"data:{mime_type};base64,{base64_image}"

    # HTTP/HTTPS URL - pass through
    if img_stripped.lower().startswith(("http://", "https://")):
        return img_stripped

    # Assume raw base64 - wrap it
    return f"data:image/png;base64,{img_stripped}"


def _process_images_in_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Process a messages array and encode any image references found within.

    This function walks through OpenAI-style messages and encodes local file paths,
    raw base64, etc. into proper data URLs.

    Parameters
    ----------
    messages : list
        OpenAI-style messages array. Each message is a dict with 'role' and 'content'.
        Content can be:
        - A string (no images)
        - A list of content parts (may contain image_url items)

    Returns
    -------
    list
        A new messages array with all image references encoded.
    """
    processed = []
    for msg in messages:
        new_msg = dict(msg)  # Shallow copy
        content = msg.get("content")

        if isinstance(content, list):
            # Content is a list of parts (text, image_url, etc.)
            new_content = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    # Process the image URL
                    image_url_obj = part.get("image_url", {})
                    url = image_url_obj.get("url", "")
                    encoded_url = _encode_image_reference(url)
                    new_part = {"type": "image_url", "image_url": {"url": encoded_url}}
                    # Preserve any extra fields like 'detail'
                    for k, v in image_url_obj.items():
                        if k != "url":
                            new_part["image_url"][k] = v
                    new_content.append(new_part)
                else:
                    new_content.append(part)
            new_msg["content"] = new_content
        # If content is a string, leave it as-is

        processed.append(new_msg)
    return processed


def extract_code_blocks(text):
    # Pattern to find code blocks
    code_block_pattern = re.compile(r"(?s)(```.*?```|`.*?`|<code>.*?</code>)")
    # Find all code blocks
    code_blocks = code_block_pattern.findall(text)

    # Function to replace each match with an incrementing number
    def replace_with_counter(match):
        replace_with_counter.counter += 1
        return f"CODE_BLOCK_{replace_with_counter.counter}"

        # Initialize the counter attribute

    replace_with_counter.counter = -1

    # Replace code blocks with unique identifiers
    modified_text = code_block_pattern.sub(replace_with_counter, text)

    return modified_text, code_blocks


def restore_code_blocks(modified_text, code_blocks):
    restored_text = modified_text
    for i, code_block in enumerate(code_blocks):
        restored_text = restored_text.replace(f"CODE_BLOCK_{i}", code_block)
    return restored_text


def enhanced_robust_url_extractor(text):
    modified_text, code_blocks = extract_code_blocks(text)
    # Regex pattern to capture URLs, allowing for punctuation and parentheses
    pattern = r"(?:\b(?:https?://|www\.)\S+\b|\((?:https?://|www\.)\S+\))"
    raw_urls = re.findall(pattern, modified_text, re.IGNORECASE)
    # Post-processing to clean up URLs
    cleaned_urls = []
    for url in raw_urls:
        # Remove surrounding parentheses and trailing punctuation
        cleaned_url = re.sub(r'^[\(\'"]*|[\.,;:!?\)\'"]+$', "", url)

        # Check if the cleaned_url is a valid URL
        if re.match(r"^(https?://|www\.)\S+$", cleaned_url):
            if cleaned_url not in cleaned_urls:
                cleaned_urls.append(cleaned_url)
        else:
            # Split URLs separated by pipe (|) or semicolon (;), but not comma (,)
            split_urls = re.split(r"[|;]", cleaned_url)
            for split_url in split_urls:
                if split_url and split_url not in cleaned_urls:
                    cleaned_urls.append(split_url)
    restored_text = restore_code_blocks(modified_text, code_blocks)
    return cleaned_urls


def get_openai_embedding(
    input_text: Union[str, List[str]],
    model_name: str,
    api_key: str,
    ctx_length: int = 10_000,
    ctx_chunk_size: int = 4_000,
) -> Union[List[float], List[List[float]]]:
    """
    Fetches the embedding(s) for the given input text using the specified model,
    similarly to the logic in `get_jina_embedding`. It accepts two parameters:
    `ctx_length` and `ctx_chunk_size`.
    - We first reduce the text length to `ctx_length`
    - Then limit the number of tokens/words to `ctx_chunk_size`.
    If the request fails and `ctx_length` is still above 2000, we retry with half
    of both parameters, providing a fallback for extremely large inputs or partial failures.

    Parameters:
    -----------
    input_text : str or List[str]
        The text (or list of texts) for which to generate the embedding(s).
    model_name : str
        The OpenAI model name to use for generating the embeddings.
    api_key : str
        The OpenAI API key for authorization.
    ctx_length : int, optional
        Maximum length in characters to keep from the input text, defaults to 10,000.
    ctx_chunk_size : int, optional
        Maximum number of tokens/words to slice from the text, defaults to 4,000.

    Returns:
    --------
    List[float] or List[List[float]]
        If a single string is passed in, returns a single list of floats.
        If a list of strings is passed in, returns a list of lists of floats.

    Raises:
    -------
    Exception
        If the API request to OpenAI fails or returns a non-200 response, and
        the fallback recursion fails once ctx_length <= 2000.
    """

    # Define the OpenAI embeddings endpoint
    url = "https://openrouter.ai/api/v1/embeddings"

    # Prepare request headers
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    # Preprocess input text with ctx_length & ctx_chunk_size
    if isinstance(input_text, list):
        processed_texts = [
            " ".join(text[:ctx_length].strip().split()[:ctx_chunk_size])
            if text
            else "<EMPTY STRING>"
            for text in input_text
        ]
        # Make sure we replace empty strings with a placeholder
        processed_texts = [
            text if len(text.strip()) > 0 else "<EMPTY STRING>"
            for text in processed_texts
        ]
    else:
        processed_texts = [
            " ".join(input_text[:ctx_length].strip().split()[:ctx_chunk_size])
        ]

    # Construct the JSON payload
    data = {"input": processed_texts, "model": model_name}

    try:
        # Send request
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()  # Will trigger exception if status is not 2xx

        response_json = response.json()
        # Extract embeddings
        embeddings = [item["embedding"] for item in response_json["data"]]

        # If the original input was a single string, return the first embedding as a list
        if not isinstance(input_text, list):
            return embeddings[0]
        return embeddings

    except Exception as e:
        logger.error(f"Exception in get_openai_embedding: {str(e)}")
        # If ctx_length > 2000, try again with smaller ctx_length & ctx_chunk_size
        if ctx_length > 2000:
            return get_openai_embedding(
                input_text=input_text,
                model_name=model_name,
                api_key=api_key,
                ctx_length=ctx_length // 2,
                ctx_chunk_size=ctx_chunk_size // 2,
            )
        # Otherwise, raise after final fallback
        raise Exception(f"Failed to fetch embedding(s) from OpenAI: {str(e)}")


embed_executor = ThreadPoolExecutor(max_workers=256)
embed_fn = get_openai_embedding

executor = ThreadPoolExecutor(max_workers=256)


def make_async(fn, execution_trace=""):
    def async_fn(*args, **kwargs):
        func_part = partial(fn, *args, **kwargs)
        future = executor.submit(func_part)
        setattr(future, "execution_trace", execution_trace)
        return future

    return async_fn


def get_async_future(fn, *args, **kwargs):
    import traceback

    execution_trace = traceback.format_exc()
    # Make your function async
    afn = make_async(fn, execution_trace)
    # This will return a Future object, you can call .result() on it to get the result
    future = afn(*args, **kwargs)
    return future


def wrap_in_future(s):
    future = Future()
    future.set_result(s)
    return future


def sleep_and_get_future_result(future, sleep_time=0.2, timeout=1000):
    start_time = time.time()
    while not future.done():
        time.sleep(sleep_time)
        if time.time() - start_time > timeout:
            raise TimeoutError(f"Timeout waiting for future for {timeout} sec")
    return future.result()


def sleep_and_get_future_exception(future, sleep_time=0.2, timeout=1000):
    start_time = time.time()
    while not future.done():
        time.sleep(sleep_time)
        if time.time() - start_time > timeout:
            return TimeoutError(f"Timeout waiting for future for {timeout} sec")
    return future.exception()


class OpenAIEmbeddingsParallel:
    def __init__(self, openai_api_key, model, chunk_size=8000):
        self.openai_api_key = openai_api_key
        self.model = model
        self.chunk_size = chunk_size

    def __call__(self, text: str) -> List[float]:
        return self.embed_query(text)

    def _embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.embed_documents(texts, chunk_size=self.chunk_size)

    def _embed_query(self, text: str) -> List[float]:
        return self.embed_query(text)

    def encode(self, text: str) -> List[float]:
        return self.embed_query(text)

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]

    def embed_documents(
        self, texts: List[str], chunk_size: Optional[int] = 0
    ) -> List[List[float]]:
        if len(texts) >= 8:
            futures = []
            for i in range(0, len(texts), 8):
                futures.append(
                    embed_executor.submit(
                        embed_fn,
                        texts[i : i + 8],
                        model_name=self.model,
                        api_key=self.openai_api_key,
                    )
                )
            results = [sleep_and_get_future_result(future) for future in futures]
            return [item for sublist in results for item in sublist]
        else:
            return embed_fn(texts, model_name=self.model, api_key=self.openai_api_key)

    def _get_len_safe_embeddings(
        self, texts: List[str], *, engine: str, chunk_size: Optional[int] = None
    ) -> List[List[float]]:
        return self._embed_documents(texts)


def get_embedding_model(keys):
    openai_key = keys["OPENROUTER_API_KEY"]
    assert openai_key
    openai_embed = OpenAIEmbeddingsParallel(
        openai_api_key=openai_key,
        model="openai/text-embedding-3-small",
        chunk_size=2000,
    )
    return openai_embed


# The below functions are the main functions to get the embedding of a text or a list of texts.


def get_query_embedding(text, keys):
    openai_embed = get_embedding_model(keys)
    embedding = openai_embed.embed_query(text)
    embedding = np.array(embedding)
    return embedding


def get_document_embedding(text, keys):
    openai_embed = get_embedding_model(keys)
    embedding = openai_embed.embed_documents([text])
    embedding = np.array(embedding[0])
    return embedding


def get_document_embeddings(texts, keys):
    openai_embed = get_embedding_model(keys)
    embedding = openai_embed.embed_documents(texts)
    embedding = np.array(embedding)
    return embedding


# The below function is the main function to call the LLM.


def call_llm(
    keys: Dict[str, str],
    model_name: str,
    text: str = "",
    images: List[str] = [],
    temperature: float = 0.7,
    stream: bool = False,
    system: Optional[str] = None,
    messages: Optional[List[Dict[str, Any]]] = None,
):
    """
    Call an LLM via OpenRouter (OpenAI-compatible API).

    This function supports two calling conventions:

    1. **Simple mode** (backward-compatible):
       Provide `text`, optionally `images`, and optionally `system`.
       The function constructs the messages array internally.

    2. **Messages mode** (OpenAI chat completions style):
       Provide `messages` directly as an array of message dicts.
       When `messages` is provided, `text`, `images`, and `system` are ignored.

    Parameters
    ----------
    keys : dict
        Credentials dict. Must include `OPENROUTER_API_KEY`.
    model_name : str
        OpenRouter model identifier (e.g., "openai/gpt-4o-mini").
    text : str
        User prompt (ignored if `messages` is provided).
    images : list
        List of image references: local paths, URLs, base64 strings, or data URLs.
        (ignored if `messages` is provided; images in `messages` are still processed)
    temperature : float
        Sampling temperature (default: 0.7).
    stream : bool
        If False, returns a single string. If True, returns a generator of text chunks.
    system : str or None
        System prompt (ignored if `messages` is provided).
    messages : list or None
        OpenAI-style messages array. Each message is a dict with 'role' and 'content'.
        Content can be a string or a list of content parts (for multimodal).
        Example:
            [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello!"},
                {"role": "assistant", "content": "Hi there!"},
                {"role": "user", "content": [
                    {"type": "text", "text": "What's in this image?"},
                    {"type": "image_url", "image_url": {"url": "/path/to/image.jpg"}}
                ]}
            ]
        Local file paths and raw base64 in image_url items are automatically encoded.

    Returns
    -------
    str or generator
        If `stream=False`: returns the full response as a string.
        If `stream=True`: returns a generator yielding text chunks.

    Examples
    --------
    # Simple mode (text only)
    >>> out = call_llm(keys, "openai/gpt-4o-mini", "Say hello", stream=False)

    # Simple mode (with image)
    >>> out = call_llm(keys, "openai/gpt-4o-mini", "Describe this", images=["./photo.jpg"])

    # Messages mode (multi-turn conversation)
    >>> msgs = [
    ...     {"role": "system", "content": "You are a helpful assistant."},
    ...     {"role": "user", "content": "What is 2+2?"},
    ...     {"role": "assistant", "content": "4"},
    ...     {"role": "user", "content": "And 3+3?"},
    ... ]
    >>> out = call_llm(keys, "openai/gpt-4o-mini", messages=msgs, stream=False)

    # Messages mode (with images in messages)
    >>> msgs = [
    ...     {"role": "user", "content": [
    ...         {"type": "text", "text": "What's in this image?"},
    ...         {"type": "image_url", "image_url": {"url": "/path/to/image.jpg"}}
    ...     ]}
    ... ]
    >>> out = call_llm(keys, "openai/gpt-4o-mini", messages=msgs, stream=False)
    """
    # If messages is provided, use it directly (after processing images within)
    if messages is not None:
        processed_messages = _process_images_in_messages(messages)
        # Estimate token count for logging/safety
        total_text = ""
        image_count = 0
        for msg in processed_messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_text += content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            total_text += part.get("text", "")
                        elif part.get("type") == "image_url":
                            image_count += 1
        if image_count > 0 and model_name not in VISION_CAPABLE_MODELS:
            raise ValueError(f"{model_name} is not supported for image input.")
        tok_count = get_gpt4_word_count(total_text) + (image_count * 1000)
        if tok_count > _get_token_limit(model_name):
            raise AssertionError(
                f"Model {model_name} is selected. Please reduce the context window. "
                f"Current context window is {tok_count} tokens."
            )
        logger.debug(
            f"CallLLM (messages mode) with temperature = {temperature}, stream = {stream}, est tokens = {tok_count}"
        )
        streaming_solution = call_with_stream(
            call_chat_model,
            stream,
            model_name,
            "",
            [],
            temperature,
            None,
            keys,
            processed_messages,
        )
        return streaming_solution

    # Simple mode: construct messages from text/images/system
    if len(images) > 0 and model_name not in VISION_CAPABLE_MODELS:
        raise ValueError(f"{model_name} is not supported for image input.")
    if len(images) > 0:
        encoded_images = [_encode_image_reference(img) for img in images]
        images = encoded_images

    if gpt4_enc is not None:
        text_len = len(gpt4_enc.encode(text))
    else:  # pragma: no cover
        text_len = len(text)
    logger.debug(
        f"CallLLM with temperature = {temperature}, stream = {stream}, token len = {text_len}"
    )
    tok_count = get_gpt4_word_count((system if system is not None else "") + text) + (
        len(images) * 1000
    )
    if tok_count > _get_token_limit(model_name):
        assertion_error_message = f"Model {model_name} is selected. Please reduce the context window. Current context window is {tok_count} tokens."
        raise AssertionError(assertion_error_message)
    streaming_solution = call_with_stream(
        call_chat_model, stream, model_name, text, images, temperature, system, keys
    )
    return streaming_solution


def _normalize_images(
    images: Union[None, str, List[str], Tuple[str, ...]],
) -> List[str]:
    """
    Normalize image input into a list of strings.

    Parameters
    ----------
    images:
        - None
        - A single image reference (local path, URL, or base64 string)
        - A list/tuple of image references

    Returns
    -------
    List[str]
        Normalized list of image references (may be empty).
    """
    if images is None:
        return []
    if isinstance(images, (list, tuple)):
        return [img for img in images if img is not None]
    return [images]


def _strip_code_fences(s: str) -> str:
    """Remove common markdown code fences surrounding JSON."""
    if not s:
        return s
    s2 = s.strip()
    if s2.startswith("```"):
        # Drop first fence line and last fence if present.
        lines = s2.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return s2


def _extract_first_json_object(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract and parse the first JSON object found in `text` (best-effort).

    Returns None if no JSON object can be parsed.
    """
    if not text:
        return None
    s = _strip_code_fences(text)
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = s[start : end + 1]
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _dedupe_and_clip_keywords(
    keywords: List[str],
    *,
    max_keywords: int,
    max_words_per_keyword: int = 3,
) -> List[str]:
    """
    Normalize, dedupe, and clip keyword phrases.

    A "keyword" here is meant for BM25-style indexing: short phrases (1-3 words).
    """
    cleaned: List[str] = []
    seen = set()
    for kw in keywords:
        if not kw:
            continue
        k = str(kw).strip()
        if not k:
            continue
        # Normalize whitespace and trim punctuation.
        k = re.sub(r"\s+", " ", k).strip().strip(".,;:!?'\"`()[]{}")
        if not k:
            continue
        if len(k.split()) > max_words_per_keyword:
            continue
        lk = k.lower()
        if lk in seen:
            continue
        seen.add(lk)
        cleaned.append(k)
        if len(cleaned) >= max_keywords:
            break
    return cleaned


def getKeywordsFromText(
    text: str,
    keys: Dict[str, str],
    *,
    llm_model: str = "openai/gpt-4o-mini",
    max_keywords: int = 30,
    temperature: float = 0.0,
) -> List[str]:
    """
    Extract short keyword phrases from text for BM25-style indexing.

    The output is intended to be *keywords/phrases* (1-3 words each), not long
    sentences. This function uses an LLM so it can extract semantic/product/entity
    keywords beyond simple tokenization.
    """
    prompt = (
        "Extract search keywords and short phrases (1-3 words each) from the text.\n"
        "Include: entities, products, brands, locations, actions, topics, and relevant attributes.\n"
        "Return STRICT JSON only with this schema:\n"
        '{ "keywords": ["keyword 1", "keyword 2", "..."] }\n\n'
        f"TEXT:\n{text}"
    )
    out = call_llm(
        keys=keys,
        model_name=llm_model,
        text=prompt,
        images=[],
        temperature=temperature,
        stream=False,
        system=None,
    )

    obj = _extract_first_json_object(out)
    if obj and isinstance(obj.get("keywords"), list):
        return _dedupe_and_clip_keywords(obj["keywords"], max_keywords=max_keywords)
    # Fallback: parse bullet/line separated keywords.
    raw = [re.sub(r"^[\-\*\d\.\)\s]+", "", ln).strip() for ln in out.splitlines()]
    raw = [x for x in raw if x]
    return _dedupe_and_clip_keywords(raw, max_keywords=max_keywords)


def getKeywordsFromImage(
    images: Union[str, List[str], Tuple[str, ...]],
    keys: Dict[str, str],
    *,
    vlm_model: str = "openai/gpt-4o-mini",
    max_keywords: int = 30,
    temperature: float = 0.0,
) -> List[str]:
    """
    Extract short keyword phrases from an image (or images) for BM25-style indexing.

    Keywords include: main subjects, objects, brands/logos, setting, notable text (OCR),
    products, colors, actions, potential questions, and other retrieval-friendly phrases.
    """
    prompt = (
        "You are extracting comprehensive BM25 search keywords from an image for maximum retrieval coverage.\n\n"
        "Extract keywords in these categories:\n"
        "1. SUBJECTS: Main subjects, people, animals, characters (e.g., 'golden retriever', 'businessman')\n"
        "2. OBJECTS: Notable objects, items, products (e.g., 'laptop', 'coffee cup', 'red car')\n"
        "3. ACTIONS: What is happening (e.g., 'running', 'typing', 'cooking')\n"
        "4. SETTING: Location, environment, scene type (e.g., 'office', 'beach sunset', 'kitchen')\n"
        "5. TEXT/OCR: Any readable text, brands, logos, signs (e.g., 'Nike logo', 'stop sign')\n"
        "6. ATTRIBUTES: Colors, sizes, materials, styles (e.g., 'vintage', 'blue striped', 'wooden')\n"
        "7. POTENTIAL QUERIES: What questions might someone ask about this image?\n"
        "   Convert to keyword form (e.g., 'dog breed identification', 'plant species', 'recipe ingredients')\n"
        "8. CONCEPTS: Abstract concepts, emotions, themes (e.g., 'teamwork', 'celebration', 'nature')\n\n"
        "Rules:\n"
        "- Return ONLY short phrases (1-3 words each)\n"
        "- Prefer specific over generic (e.g., 'golden retriever' not just 'dog')\n"
        "- Include synonyms for important items (e.g., both 'laptop' and 'computer')\n"
        "- Include domain-specific terms if applicable\n\n"
        "Return STRICT JSON only with this schema:\n"
        '{ "keywords": ["keyword 1", "keyword 2", "..."] }\n'
    )
    out = call_llm(
        keys=keys,
        model_name=vlm_model,
        text=prompt,
        images=_normalize_images(images),
        temperature=temperature,
        stream=False,
        system="Return JSON only. No extra commentary.",
    )

    obj = _extract_first_json_object(out)
    if obj and isinstance(obj.get("keywords"), list):
        return _dedupe_and_clip_keywords(obj["keywords"], max_keywords=max_keywords)
    raw = [re.sub(r"^[\-\*\d\.\)\s]+", "", ln).strip() for ln in out.splitlines()]
    raw = [x for x in raw if x]
    return _dedupe_and_clip_keywords(raw, max_keywords=max_keywords)


def getKeywordsFromImageText(
    text: str,
    images: Union[str, List[str], Tuple[str, ...]],
    keys: Dict[str, str],
    *,
    vlm_model: str = "openai/gpt-4o-mini",
    max_keywords: int = 30,
    temperature: float = 0.0,
) -> List[str]:
    """
    Extract keyword phrases from *both* image(s) and accompanying text.

    This is useful when the text provides additional context (e.g., product name,
    location, or intent) that should be reflected in keyword indexing.
    """
    prompt = (
        "Extract comprehensive BM25 search keywords from BOTH the image(s) AND the text context.\n\n"
        "The text provides intent/context that should guide your keyword extraction from the image.\n\n"
        "Extract keywords in these categories:\n"
        "1. FROM TEXT: Key entities, topics, intent, questions asked\n"
        "2. FROM IMAGE: Subjects, objects, actions, setting, OCR text\n"
        "3. CROSS-MODAL: Keywords that connect the text intent to image content\n"
        "   (e.g., if text asks 'What breed?' and image shows a dog → 'dog breed', 'breed identification')\n"
        "4. POTENTIAL QUERIES: What questions might someone ask about this image+text combination?\n"
        "5. DOMAIN TERMS: Technical or domain-specific terminology\n"
        "6. SYNONYMS: Alternative terms for important concepts\n\n"
        "Rules:\n"
        "- Return ONLY short phrases (1-3 words each)\n"
        "- Prioritize keywords that bridge text and image\n"
        "- Include both specific (e.g., 'golden retriever') and general (e.g., 'dog') terms\n\n"
        "Return STRICT JSON only with this schema:\n"
        '{ "keywords": ["keyword 1", "keyword 2", "..."] }\n\n'
        f"TEXT CONTEXT:\n{text}"
    )
    out = call_llm(
        keys=keys,
        model_name=vlm_model,
        text=prompt,
        images=_normalize_images(images),
        temperature=temperature,
        stream=False,
        system="Return JSON only. No extra commentary.",
    )

    obj = _extract_first_json_object(out)
    if obj and isinstance(obj.get("keywords"), list):
        return _dedupe_and_clip_keywords(obj["keywords"], max_keywords=max_keywords)
    raw = [re.sub(r"^[\-\*\d\.\)\s]+", "", ln).strip() for ln in out.splitlines()]
    raw = [x for x in raw if x]
    return _dedupe_and_clip_keywords(raw, max_keywords=max_keywords)


def getImageQueryEmbedding(
    image: Union[str, List[str], Tuple[str, ...]],
    keys: Dict[str, str],
    *,
    vlm_model: str = "openai/gpt-4o-mini",
    use_keywords: bool = True,
    max_keywords: int = 30,
    temperature: float = 0.2,
) -> np.ndarray:
    """
    Generate a query embedding for an image by captioning it with a VLM and embedding the text.

    Query embeddings are optimized for retrieval intent: concise, discriminative,
    and focused on objects/attributes likely to be searched.
    """
    base_prompt = (
        "Describe this image comprehensively for RETRIEVAL as a QUERY.\n\n"
        "Your description will be used to find similar images and relevant information.\n\n"
        "Include ALL of the following:\n"
        "1. MAIN SUBJECTS: What/who is the primary focus? Be specific (e.g., 'adult golden retriever' not just 'dog')\n"
        "2. KEY OBJECTS: Notable items, products, tools visible\n"
        "3. ACTIONS: What is happening? Any activities or interactions?\n"
        "4. SETTING: Where is this? Environment, location type, indoor/outdoor\n"
        "5. VISUAL ATTRIBUTES: Colors, textures, sizes, styles that stand out\n"
        "6. TEXT/OCR: Any readable text, signs, labels, brands\n"
        "7. POTENTIAL QUESTIONS: List 2-3 questions someone might ask about this image:\n"
        "   - 'What is this?' type questions\n"
        "   - 'How to...' type questions\n"
        "   - Identification questions (species, brand, model, etc.)\n"
        "8. UNIQUE IDENTIFIERS: What makes this specific image unique or recognizable?\n\n"
        "Format: Write as flowing prose, dense with information. Not bullet points.\n"
        "Return plain text (not JSON).\n"
    )
    details = call_llm(
        keys=keys,
        model_name=vlm_model,
        text=base_prompt,
        images=_normalize_images(image),
        temperature=temperature,
        stream=False,
        system="Be concise and retrieval-focused.",
    )

    if use_keywords:
        kws = getKeywordsFromImage(
            image, keys, vlm_model=vlm_model, max_keywords=max_keywords, temperature=0.0
        )
        details = details + "\n\nKeywords: " + ", ".join(kws)
    return get_query_embedding(details, keys)


def getImageDocumentEmbedding(
    image: Union[str, List[str], Tuple[str, ...]],
    keys: Dict[str, str],
    *,
    vlm_model: str = "openai/gpt-4o-mini",
    use_keywords: bool = True,
    max_keywords: int = 30,
    temperature: float = 0.2,
) -> np.ndarray:
    """
    Generate a document embedding for an image by captioning it with a VLM and embedding the text.

    Document embeddings are optimized for indexing: richer, more complete descriptions
    than query embeddings, including background details and semantics.
    """
    base_prompt = (
        "Create a COMPREHENSIVE description of this image for INDEXING and future retrieval.\n\n"
        "This description will be stored and searched against future queries. Be thorough.\n\n"
        "Include ALL of the following sections:\n\n"
        "1. DETAILED DESCRIPTION:\n"
        "   - Main subjects with specific attributes (species, breed, model, brand if identifiable)\n"
        "   - All visible objects, even background items\n"
        "   - Setting, environment, location indicators\n"
        "   - Spatial relationships (what is where, relative positions)\n"
        "   - Actions, activities, states (sitting, running, open, closed)\n"
        "   - Visual qualities: colors, textures, lighting, style\n\n"
        "2. TEXT AND LABELS (OCR):\n"
        "   - All readable text, signs, labels, logos\n"
        "   - Brand names, product names, identifiers\n\n"
        "3. POTENTIAL QUESTIONS this image could answer:\n"
        "   - What identification questions? (What is this? What breed/species/model?)\n"
        "   - What 'how-to' questions? (How to use this? How to make this?)\n"
        "   - What comparison questions? (Is this X or Y?)\n"
        "   - What troubleshooting questions? (What's wrong here? Why is this happening?)\n"
        "   List 3-5 specific questions.\n\n"
        "4. KEY OBSERVATIONS:\n"
        "   - What stands out or is unusual?\n"
        "   - What domain/category does this belong to?\n"
        "   - What expertise would be needed to understand this image?\n\n"
        "5. SEMANTIC MEANING:\n"
        "   - What is the purpose or context of this image?\n"
        "   - What story or information does it convey?\n\n"
        "Format: Write as detailed prose paragraphs. Be exhaustive - more detail is better for retrieval.\n"
        "Return plain text (not JSON).\n"
    )
    details = call_llm(
        keys=keys,
        model_name=vlm_model,
        text=base_prompt,
        images=_normalize_images(image),
        temperature=temperature,
        stream=False,
        system="Be detailed and descriptive.",
    )

    if use_keywords:
        kws = getKeywordsFromImage(
            image, keys, vlm_model=vlm_model, max_keywords=max_keywords, temperature=0.0
        )
        details = details + "\n\nKeywords: " + ", ".join(kws)
    return get_document_embedding(details, keys)


def _combine_embeddings_weighted_mean(
    a: Optional[np.ndarray],
    b: Optional[np.ndarray],
    *,
    weight_a: float = 1.0,
    weight_b: float = 1.0,
) -> np.ndarray:
    """
    Combine two embeddings into a single embedding using a weighted mean.

    This keeps the output dimensionality identical to the input dimensionality.
    """
    if a is None and b is None:
        raise ValueError("At least one embedding must be provided.")
    if a is None:
        return b  # type: ignore[return-value]
    if b is None:
        return a
    if a.shape != b.shape:
        raise ValueError(f"Embedding shapes differ: {a.shape} vs {b.shape}")
    wa = float(weight_a)
    wb = float(weight_b)
    denom = wa + wb if (wa + wb) != 0 else 1.0
    return (wa * a + wb * b) / denom


def getJointQueryEmbedding(
    text: Optional[str],
    image: Union[None, str, List[str], Tuple[str, ...]],
    keys: Dict[str, str],
    *,
    mode: str = "separate",
    vlm_model: str = "openai/gpt-4o-mini",
    use_keywords: bool = True,
    max_keywords: int = 30,
    temperature: float = 0.2,
    text_weight: float = 1.0,
    image_weight: float = 1.0,
) -> np.ndarray:
    """
    Generate a query embedding from (text, image) jointly.

    Modes
    -----
    - "separate": embed text directly; embed image via VLM->text->embedding; then combine embeddings.
    - "vlm": send both text+image to the VLM to generate a combined description, then embed that text.
    """
    mode = (mode or "").strip().lower()
    has_text = bool(text and str(text).strip())
    has_image = len(_normalize_images(image)) > 0

    if mode not in {"separate", "vlm"}:
        raise ValueError('mode must be either "separate" or "vlm"')

    if mode == "vlm":
        prompt = (
            "Create a JOINT retrieval description combining the image(s) with the text context.\n\n"
            "The text provides the USER'S INTENT - use it to focus your image analysis.\n\n"
            "Include:\n"
            "1. INTENT ALIGNMENT: How does the image relate to the text query/context?\n"
            "2. RELEVANT IMAGE DETAILS: Focus on aspects of the image that address the text intent\n"
            "   - If text asks 'what is this?' → identify and describe the subject specifically\n"
            "   - If text asks 'how to?' → describe relevant procedural elements\n"
            "   - If text is a statement → describe how image confirms/contradicts it\n"
            "3. KEY OBJECTS & SUBJECTS: Main items visible, with specific identifications\n"
            "4. SETTING & CONTEXT: Where/when this appears to be\n"
            "5. TEXT/OCR: Any readable text in the image\n"
            "6. POTENTIAL ANSWERS: Based on text+image, what questions could this combination answer?\n\n"
            "Be concise but information-dense. Prioritize details relevant to the text context.\n"
            "Return plain text.\n\n"
            f"TEXT CONTEXT:\n{text or ''}"
        )
        details = call_llm(
            keys=keys,
            model_name=vlm_model,
            text=prompt,
            images=_normalize_images(image),
            temperature=temperature,
            stream=False,
            system="Be retrieval-focused. Connect image content to text intent.",
        )

        if use_keywords and (has_text or has_image):
            kws = getKeywordsFromImageText(
                text or "",
                image,
                keys,
                vlm_model=vlm_model,
                max_keywords=max_keywords,
                temperature=0.0,
            )
            details = details + "\n\nKeywords: " + ", ".join(kws)
        return get_query_embedding(details, keys)

    # mode == "separate"
    text_emb: Optional[np.ndarray] = None
    if has_text:
        t = str(text).strip()
        if use_keywords:
            kws_t = getKeywordsFromText(
                t, keys, llm_model=vlm_model, max_keywords=max_keywords, temperature=0.0
            )
            t = t + "\n\nKeywords: " + ", ".join(kws_t)
        text_emb = get_query_embedding(t, keys)

    image_emb: Optional[np.ndarray] = None
    if has_image:
        image_emb = getImageQueryEmbedding(
            image,
            keys,
            vlm_model=vlm_model,
            use_keywords=use_keywords,
            max_keywords=max_keywords,
            temperature=temperature,
        )

    return _combine_embeddings_weighted_mean(
        text_emb, image_emb, weight_a=text_weight, weight_b=image_weight
    )


def getJointDocumentEmbedding(
    text: Optional[str],
    image: Union[None, str, List[str], Tuple[str, ...]],
    keys: Dict[str, str],
    *,
    mode: str = "separate",
    vlm_model: str = "openai/gpt-4o-mini",
    use_keywords: bool = True,
    max_keywords: int = 30,
    temperature: float = 0.2,
    text_weight: float = 1.0,
    image_weight: float = 1.0,
) -> np.ndarray:
    """
    Generate a document embedding from (text, image) jointly.

    Modes
    -----
    - "separate": embed text directly; embed image via VLM->text->embedding; then combine embeddings.
    - "vlm": send both text+image to the VLM to generate a combined detailed description, then embed that text.
    """
    mode = (mode or "").strip().lower()
    has_text = bool(text and str(text).strip())
    has_image = len(_normalize_images(image)) > 0

    if mode not in {"separate", "vlm"}:
        raise ValueError('mode must be either "separate" or "vlm"')

    if mode == "vlm":
        prompt = (
            "Create a COMPREHENSIVE JOINT description for INDEXING, combining image(s) with text context.\n\n"
            "The text provides additional context that enriches understanding of the image.\n"
            "This combined description will be stored and searched against future queries.\n\n"
            "Include ALL of the following:\n\n"
            "1. TEXT-IMAGE RELATIONSHIP:\n"
            "   - How does the text relate to what's shown in the image?\n"
            "   - Does the text provide labels, explanations, or context for the image?\n\n"
            "2. COMPREHENSIVE IMAGE DESCRIPTION:\n"
            "   - All subjects with specific identifications (species, breed, model, brand)\n"
            "   - All visible objects, even background items\n"
            "   - Actions, activities, states, relationships\n"
            "   - Setting, environment, location\n"
            "   - Visual qualities: colors, textures, lighting, composition\n\n"
            "3. TEXT/OCR IN IMAGE:\n"
            "   - All readable text, signs, labels, logos\n"
            "   - How does image text relate to the provided text context?\n\n"
            "4. COMBINED SEMANTIC MEANING:\n"
            "   - What is the overall meaning when text and image are considered together?\n"
            "   - What information does this combination convey?\n\n"
            "5. POTENTIAL QUESTIONS this text+image could answer:\n"
            "   - Identification questions (What is this? What type?)\n"
            "   - How-to questions (How to use/make/fix this?)\n"
            "   - Comparison questions (Is this correct? What's wrong?)\n"
            "   - Explanation questions (Why does this happen?)\n"
            "   List 4-6 specific questions.\n\n"
            "6. KEY OBSERVATIONS:\n"
            "   - What domain expertise is relevant?\n"
            "   - What makes this text+image combination unique?\n"
            "   - What corrections or clarifications does the text provide?\n\n"
            "Be exhaustive - more detail enables better retrieval.\n"
            "Return plain text.\n\n"
            f"TEXT CONTEXT:\n{text or ''}"
        )
        details = call_llm(
            keys=keys,
            model_name=vlm_model,
            text=prompt,
            images=_normalize_images(image),
            temperature=temperature,
            stream=False,
            system="Be detailed and exhaustive. Connect text context with image content.",
        )

        if use_keywords and (has_text or has_image):
            kws = getKeywordsFromImageText(
                text or "",
                image,
                keys,
                vlm_model=vlm_model,
                max_keywords=max_keywords,
                temperature=0.0,
            )
            details = details + "\n\nKeywords: " + ", ".join(kws)
        return get_document_embedding(details, keys)

    # mode == "separate"
    text_emb: Optional[np.ndarray] = None
    if has_text:
        t = str(text).strip()
        if use_keywords:
            kws_t = getKeywordsFromText(
                t, keys, llm_model=vlm_model, max_keywords=max_keywords, temperature=0.0
            )
            t = t + "\n\nKeywords: " + ", ".join(kws_t)
        text_emb = get_document_embedding(t, keys)

    image_emb: Optional[np.ndarray] = None
    if has_image:
        image_emb = getImageDocumentEmbedding(
            image,
            keys,
            vlm_model=vlm_model,
            use_keywords=use_keywords,
            max_keywords=max_keywords,
            temperature=temperature,
        )

    return _combine_embeddings_weighted_mean(
        text_emb, image_emb, weight_a=text_weight, weight_b=image_weight
    )
