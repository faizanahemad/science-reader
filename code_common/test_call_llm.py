"""
Integration tests for `code_common/call_llm.py`.

Why this exists
---------------
`code_common/call_llm.py` is a thin wrapper around OpenRouter/OpenAI-compatible APIs.
These tests validate that the four public entrypoints at the bottom of that file
work end-to-end:

- `call_llm`
- `get_query_embedding`
- `get_document_embedding`
- `get_document_embeddings`

Design notes
------------
- These are **networked integration tests**. They will fail without network access,
  with an invalid API key, or if the chosen model is not available on OpenRouter.
- The only required secret is `OPENROUTER_API_KEY`, provided via CLI.
- We keep payloads small to minimize cost and latency.

Usage
-----
Run with:
    python test_call_llm.py --openrouter-api-key "<KEY>"

Optional:
    python test_call_llm.py --openrouter-api-key "<KEY>" --model "openai/gpt-4o-mini"
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import unittest
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def _repo_root() -> str:
    """
    Return the repository root directory.

    This test file lives in `code_common/`, so the repo root is the parent directory.
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_import_paths() -> None:
    """
    Ensure `code_common/call_llm.py` can be imported reliably.

    `code_common/call_llm.py` does `from loggers import getLoggers` (non-package import),
    so we must add `code_common/` to `sys.path` in addition to the repo root.
    """
    root = _repo_root()
    code_common_dir = os.path.join(root, "code_common")
    if root not in sys.path:
        sys.path.insert(0, root)
    if code_common_dir not in sys.path:
        sys.path.insert(0, code_common_dir)


_ensure_import_paths()

# Import after path fix.
from code_common.call_llm import (  # noqa: E402
    call_llm,
    get_document_embedding,
    get_document_embeddings,
    get_query_embedding,
    getImageDocumentEmbedding,
    getImageQueryEmbedding,
    getJointDocumentEmbedding,
    getJointQueryEmbedding,
    getKeywordsFromImage,
    getKeywordsFromImageText,
    getKeywordsFromText,
)


def _coerce_call_llm_result_to_text(res: Any) -> str:
    """
    Coerce `call_llm` results into a single string.

    In this repo, `call_llm(..., stream=False)` returns a string and
    `call_llm(..., stream=True)` yields text chunks (strings). This helper also
    tolerates older chunk-shaped outputs.
    """
    if res is None:
        return ""
    if isinstance(res, str):
        return res
    parts: List[str] = []
    try:
        for ch in res:
            if isinstance(ch, str):
                parts.append(ch)
                continue
            # Backward compatibility: OpenAI-style chunk objects.
            try:
                choices = getattr(ch, "choices", None)
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                if delta is None:
                    continue
                content = getattr(delta, "content", None)
                if isinstance(content, str) and content:
                    parts.append(content)
            except Exception:
                continue
    except Exception:
        return str(res)
    return "".join(parts)


def _collect_stream(stream: Iterable[Any], max_seconds: float = 30.0, max_chunks: int = 500) -> List[Any]:
    """
    Collect a streaming iterable into a list with a time and chunk bound.

    Parameters
    ----------
    stream:
        An iterable/generator of chunks.
    max_seconds:
        Hard wall-clock limit to prevent infinite hangs.
    max_chunks:
        Hard limit on chunks to prevent runaway collection.
    """
    start = time.time()
    out: List[Any] = []
    for ch in stream:
        out.append(ch)
        if len(out) >= max_chunks:
            break
        if time.time() - start > max_seconds:
            break
    return out


@dataclass(frozen=True)
class TestConfig:
    """Configuration for integration tests."""

    openrouter_api_key: str
    model: str
    vlm_model: str
    timeout_seconds: float
    max_keywords: int
    image_url: Optional[str]
    image_path: str

    @property
    def keys(self) -> Dict[str, str]:
        """Return the keys dict expected by `call_llm` and embedding helpers."""
        return {"OPENROUTER_API_KEY": self.openrouter_api_key}


class CallLLMIntegrationTests(unittest.TestCase):
    """
    Integration tests for `code_common/call_llm.py`.

    These tests use real API calls. They are intentionally conservative on
    payload size and assert only stable properties (types/shapes/non-empty output).
    """

    CFG: Optional[TestConfig] = None
    VLM_IMAGE_OK: bool = False
    VLM_IMAGE_PROBE_ERROR: Optional[str] = None

    @classmethod
    def setUpClass(cls) -> None:
        if cls.CFG is None:
            raise RuntimeError(
                "TestConfig not initialized. Run this file as a script with "
                "`--openrouter-api-key` so configuration can be injected."
            )
        # Probe whether the selected VLM model can process the image input format we provide.
        # Some providers/models on OpenRouter reject data URLs; in that case we skip image tests
        # with a clear diagnostic.
        cfg = cls.CFG
        assert cfg is not None

        if not os.path.exists(cfg.image_path):
            raise FileNotFoundError(
                f"Expected test image at {cfg.image_path}. "
                "Place `test_image.jpg` in the same directory as this test file."
            )

        # Prefer a user-provided HTTPS URL if present; otherwise use the local test image path.
        probe_image = cfg.image_url or cfg.image_path
        try:
            out = call_llm(
                keys=cfg.keys,
                model_name=cfg.vlm_model,
                text="Describe the image in one short sentence.",
                images=[probe_image],
                temperature=0.0,
                stream=False,
                system="You can see images. Reply with a single sentence.",
            )
            cls.VLM_IMAGE_OK = isinstance(out, str) and len(out.strip()) > 0
            if not cls.VLM_IMAGE_OK:
                cls.VLM_IMAGE_PROBE_ERROR = f"VLM probe returned empty output (model={cfg.vlm_model})."
        except Exception as e:
            cls.VLM_IMAGE_OK = False
            cls.VLM_IMAGE_PROBE_ERROR = (
                f"VLM probe failed for model={cfg.vlm_model}. "
                f"Try a different --vlm-model (e.g. openai/gpt-4o-mini). "
                f"You can also pass --image-url with an https URL. "
                f"Original error: {repr(e)}"
            )

    def test_get_query_embedding_returns_1d_numpy_array(self) -> None:
        """`get_query_embedding` returns a 1D numpy array with finite floats."""
        import numpy as np

        cfg = self.CFG  # type: ignore[assignment]
        emb = get_query_embedding("Hello world", cfg.keys)
        self.assertIsInstance(emb, np.ndarray)
        self.assertEqual(emb.ndim, 1)
        self.assertGreater(emb.shape[0], 10)
        self.assertTrue(np.isfinite(emb).all())

    def test_get_document_embedding_returns_1d_numpy_array(self) -> None:
        """`get_document_embedding` returns a 1D numpy array with finite floats."""
        import numpy as np

        cfg = self.CFG  # type: ignore[assignment]
        emb = get_document_embedding("A small document about embeddings.", cfg.keys)
        self.assertIsInstance(emb, np.ndarray)
        self.assertEqual(emb.ndim, 1)
        self.assertGreater(emb.shape[0], 10)
        self.assertTrue(np.isfinite(emb).all())

    def test_get_document_embeddings_returns_2d_numpy_array(self) -> None:
        """`get_document_embeddings` returns a 2D numpy array, one row per input text."""
        import numpy as np

        cfg = self.CFG  # type: ignore[assignment]
        texts = [
            "Doc A: cats and dogs.",
            "Doc B: physics and math.",
            "Doc C: software testing.",
        ]
        embs = get_document_embeddings(texts, cfg.keys)
        self.assertIsInstance(embs, np.ndarray)
        self.assertEqual(embs.ndim, 2)
        self.assertEqual(embs.shape[0], len(texts))
        self.assertGreater(embs.shape[1], 10)
        self.assertTrue(np.isfinite(embs).all())

    def test_call_llm_non_stream_returns_chunks_with_text(self) -> None:
        """
        `call_llm(..., stream=False)` returns a string and contains text.
        """
        cfg = self.CFG  # type: ignore[assignment]
        prompt = "Reply with exactly: ok"
        res = call_llm(
            keys=cfg.keys,
            model_name=cfg.model,
            text=prompt,
            temperature=0.0,
            stream=False,
            system="You are a precise assistant.",
        )
        self.assertIsInstance(res, str)
        text = res.strip()
        self.assertGreater(len(text), 0, msg=f"No assistant content extracted from chunks; model={cfg.model}")

    def test_call_llm_stream_yields_chunks_with_text(self) -> None:
        """`call_llm(..., stream=True)` yields text chunks; collecting yields non-empty text."""
        cfg = self.CFG  # type: ignore[assignment]
        prompt = "Write a 3-word greeting."
        stream = call_llm(
            keys=cfg.keys,
            model_name=cfg.model,
            text=prompt,
            temperature=0.2,
            stream=True,
            system="Be brief.",
        )
        chunks = _collect_stream(stream, max_seconds=cfg.timeout_seconds)
        self.assertGreater(len(chunks), 0)
        text = _coerce_call_llm_result_to_text(chunks).strip()
        self.assertGreater(len(text), 0, msg=f"No assistant content extracted from streaming chunks; model={cfg.model}")

    def test_call_llm_messages_mode_text_only(self) -> None:
        """
        `call_llm` with `messages` parameter (OpenAI chat completions style, text-only).
        """
        cfg = self.CFG  # type: ignore[assignment]
        messages = [
            {"role": "system", "content": "You are a helpful assistant. Be very brief."},
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
            {"role": "user", "content": "And what is 3+3?"},
        ]
        res = call_llm(
            keys=cfg.keys,
            model_name=cfg.model,
            messages=messages,
            temperature=0.0,
            stream=False,
        )
        self.assertIsInstance(res, str)
        text = res.strip()
        self.assertGreater(len(text), 0)
        # The answer should mention 6
        print(f"\n[MESSAGES MODE TEXT] model={cfg.model}\nMessages: {messages}\nResponse: {text}\n")

    def test_call_llm_messages_mode_with_image(self) -> None:
        """
        `call_llm` with `messages` parameter containing image_url (multimodal).
        """
        cfg = self.CFG  # type: ignore[assignment]
        self.assertTrue(self.VLM_IMAGE_OK, self.VLM_IMAGE_PROBE_ERROR or "VLM image probe failed.")

        img = cfg.image_url or cfg.image_path
        messages = [
            {"role": "system", "content": "You are a helpful assistant. Be brief."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What do you see in this image? Describe briefly."},
                    {"type": "image_url", "image_url": {"url": img}},
                ],
            },
        ]
        res = call_llm(
            keys=cfg.keys,
            model_name=cfg.vlm_model,
            messages=messages,
            temperature=0.0,
            stream=False,
        )
        self.assertIsInstance(res, str)
        text = res.strip()
        self.assertGreater(len(text), 0)
        print(f"\n[MESSAGES MODE IMAGE] model={cfg.vlm_model} image={img}\nResponse: {text}\n")

    def test_call_llm_messages_mode_multi_turn_with_image(self) -> None:
        """
        `call_llm` with `messages` parameter: multi-turn conversation with image in one turn.
        """
        cfg = self.CFG  # type: ignore[assignment]
        self.assertTrue(self.VLM_IMAGE_OK, self.VLM_IMAGE_PROBE_ERROR or "VLM image probe failed.")

        img = cfg.image_url or cfg.image_path
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "I'm going to show you an image and ask questions."},
            {"role": "assistant", "content": "Sure, go ahead!"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is the main subject of this image?"},
                    {"type": "image_url", "image_url": {"url": img}},
                ],
            },
        ]
        res = call_llm(
            keys=cfg.keys,
            model_name=cfg.vlm_model,
            messages=messages,
            temperature=0.0,
            stream=False,
        )
        self.assertIsInstance(res, str)
        text = res.strip()
        self.assertGreater(len(text), 0)
        print(f"\n[MESSAGES MODE MULTI-TURN+IMAGE] model={cfg.vlm_model} image={img}\nResponse: {text}\n")

    def test_call_llm_image_only_generic(self) -> None:
        """
        Generic diagnostic: does `call_llm` + selected `--vlm-model` accept an image at all?
        """
        cfg = self.CFG  # type: ignore[assignment]
        self.assertTrue(self.VLM_IMAGE_OK, self.VLM_IMAGE_PROBE_ERROR or "VLM image probe failed.")

        img = cfg.image_url or cfg.image_path
        out = call_llm(
            keys=cfg.keys,
            model_name=cfg.vlm_model,
            text=(
                "Describe this image in detail for future reference and indexing.\n"
                "Include: main subjects, setting, notable objects, spatial relationships if clear,\n"
                "any readable text (OCR), and overall semantic meaning.\n"
                "Be detailed but structured (short paragraphs or bullet-like sentences are fine)."
            ),
            images=[img],
            temperature=0.0,
            stream=False,
            system="Be detailed and retrieval/indexing focused.",
        )
        self.assertIsInstance(out, str)
        self.assertGreater(len(out.strip()), 0)
        print(f"\n[IMAGE->TEXT INDEXING] model={cfg.vlm_model} image={img}\n{out.strip()}\n")

    def test_call_llm_image_text_generic(self) -> None:
        """
        Generic diagnostic: does `call_llm` accept image + text together for the selected `--vlm-model`?
        """
        cfg = self.CFG  # type: ignore[assignment]
        self.assertTrue(self.VLM_IMAGE_OK, self.VLM_IMAGE_PROBE_ERROR or "VLM image probe failed.")

        img = cfg.image_url or cfg.image_path
        out = call_llm(
            keys=cfg.keys,
            model_name=cfg.vlm_model,
            text=(
                "TEXT CONTEXT:\n"
                "The user says: 'white pixel'\n\n"
                "Task: Describe the image in detail for future reference and indexing, and relate it to the text context.\n"
                "Include: main subjects, setting, notable objects, OCR, and any details that help match this image to the text intent."
            ),
            images=[img],
            temperature=0.0,
            stream=False,
            system="Be detailed, structured, and retrieval/indexing focused.",
        )
        self.assertIsInstance(out, str)
        self.assertGreater(len(out.strip()), 0)
        print(f"\n[IMAGE+TEXT->TEXT INDEXING] model={cfg.vlm_model} image={img}\n{out.strip()}\n")

    def test_get_keywords_from_text(self) -> None:
        """`getKeywordsFromText` returns short keyword phrases."""
        cfg = self.CFG  # type: ignore[assignment]
        kws = getKeywordsFromText(
            "Nike running shoes in New York City marathon training plan.",
            cfg.keys,
            llm_model=cfg.vlm_model,
            max_keywords=cfg.max_keywords,
            temperature=0.0,
        )
        self.assertIsInstance(kws, list)
        self.assertGreater(len(kws), 0)
        self.assertTrue(all(isinstance(k, str) for k in kws))
        print(f"\n[KEYWORDS TEXT] model={cfg.vlm_model} max_keywords={cfg.max_keywords}\n{kws}\n")

    def test_get_keywords_from_image(self) -> None:
        """`getKeywordsFromImage` works end-to-end on the local test image."""
        cfg = self.CFG  # type: ignore[assignment]
        self.assertTrue(self.VLM_IMAGE_OK, self.VLM_IMAGE_PROBE_ERROR or "VLM image probe failed.")
        img_b64 = cfg.image_url or cfg.image_path
        kws = getKeywordsFromImage(
            img_b64,
            cfg.keys,
            vlm_model=cfg.vlm_model,
            max_keywords=cfg.max_keywords,
            temperature=0.0,
        )
        self.assertIsInstance(kws, list)
        self.assertGreater(len(kws), 0)
        self.assertTrue(all(isinstance(k, str) for k in kws))
        print(f"\n[KEYWORDS IMAGE] model={cfg.vlm_model} image={img_b64} max_keywords={cfg.max_keywords}\n{kws}\n")

    def test_get_keywords_from_image_text(self) -> None:
        """`getKeywordsFromImageText` works end-to-end on the local test image + a short text context."""
        cfg = self.CFG  # type: ignore[assignment]
        self.assertTrue(self.VLM_IMAGE_OK, self.VLM_IMAGE_PROBE_ERROR or "VLM image probe failed.")
        img = cfg.image_url or cfg.image_path
        kws = getKeywordsFromImageText(
            "This should be searchable by color, object type, and any text in the image.",
            img,
            cfg.keys,
            vlm_model=cfg.vlm_model,
            max_keywords=cfg.max_keywords,
            temperature=0.0,
        )
        self.assertIsInstance(kws, list)
        self.assertGreater(len(kws), 0)
        self.assertTrue(all(isinstance(k, str) for k in kws))
        print(f"\n[KEYWORDS IMAGE+TEXT] model={cfg.vlm_model} image={img} max_keywords={cfg.max_keywords}\n{kws}\n")

    def test_image_and_joint_embeddings(self) -> None:
        """Image and joint embeddings return finite 1D numpy vectors in both modes."""
        import numpy as np

        cfg = self.CFG  # type: ignore[assignment]
        self.assertTrue(self.VLM_IMAGE_OK, self.VLM_IMAGE_PROBE_ERROR or "VLM image probe failed.")
        img_b64 = cfg.image_url or cfg.image_path

        img_q = getImageQueryEmbedding(img_b64, cfg.keys, vlm_model=cfg.vlm_model, max_keywords=cfg.max_keywords)
        img_d = getImageDocumentEmbedding(img_b64, cfg.keys, vlm_model=cfg.vlm_model, max_keywords=cfg.max_keywords)
        self.assertIsInstance(img_q, np.ndarray)
        self.assertIsInstance(img_d, np.ndarray)
        self.assertEqual(img_q.ndim, 1)
        self.assertEqual(img_d.ndim, 1)
        self.assertTrue(np.isfinite(img_q).all())
        self.assertTrue(np.isfinite(img_d).all())

        joint_sep = getJointQueryEmbedding(
            "white pixel",
            img_b64,
            cfg.keys,
            mode="separate",
            vlm_model=cfg.vlm_model,
            max_keywords=cfg.max_keywords,
        )
        joint_vlm = getJointDocumentEmbedding(
            "white pixel",
            img_b64,
            cfg.keys,
            mode="vlm",
            vlm_model=cfg.vlm_model,
            max_keywords=cfg.max_keywords,
        )
        self.assertIsInstance(joint_sep, np.ndarray)
        self.assertIsInstance(joint_vlm, np.ndarray)
        self.assertEqual(joint_sep.ndim, 1)
        self.assertEqual(joint_vlm.ndim, 1)
        self.assertTrue(np.isfinite(joint_sep).all())
        self.assertTrue(np.isfinite(joint_vlm).all())


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for configuring the integration tests."""
    p = argparse.ArgumentParser(description="Integration tests for code_common/call_llm.py")
    p.add_argument(
        "--openrouter-api-key",
        required=True,
        help="OpenRouter API key used by code_common/call_llm.py (required).",
    )
    p.add_argument(
        "--model",
        default="openai/gpt-4o-mini",
        help="OpenRouter chat model for `call_llm` tests (default: openai/gpt-4o-mini).",
    )
    p.add_argument(
        "--vlm-model",
        default=None,
        help="OpenRouter vision(-language) model for image tests (default: same as --model).",
    )
    p.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="Timeout budget used when collecting streaming responses (default: 30).",
    )
    p.add_argument(
        "--max-keywords",
        type=int,
        default=15,
        help="Max number of keywords to request/keep in keyword extraction tests (default: 15).",
    )
    p.add_argument(
        "--image-url",
        default=None,
        help="Optional HTTPS image URL to use for image tests (useful for providers that reject base64/data URLs).",
    )
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entrypoint for running these tests as a script."""
    args = _parse_args(argv)
    vlm_model = args.vlm_model or args.model
    CallLLMIntegrationTests.CFG = TestConfig(
        openrouter_api_key=args.openrouter_api_key,
        model=args.model,
        vlm_model=vlm_model,
        timeout_seconds=args.timeout_seconds,
        max_keywords=args.max_keywords,
        image_url=args.image_url,
        image_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_image.jpg"),
    )
    # Delegate to unittest runner; keep argv minimal.
    unittest_args = [sys.argv[0]]
    return 0 if unittest.main(argv=unittest_args, exit=False).result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())


