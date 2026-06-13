"""LLMProvider protocol — the single seam between TMS core and LLM implementations."""

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM + embedding operations.

    Mirrors the signatures of code_common.call_llm so the swap is 1:1.
    Hosts inject their implementation; standalone supplies a default.
    """

    def call_llm(
        self,
        keys: Dict[str, str],
        model: str,
        text: str = "",
        *,
        images: Optional[List[str]] = None,
        temperature: float = 0.7,
        stream: bool = False,
        system: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
    ) -> Any:
        """Call an LLM. Returns response text (or stream)."""
        ...

    def get_query_embedding(self, text: str, keys: Dict[str, str]) -> np.ndarray:
        """Get embedding optimized for queries (search)."""
        ...

    def get_document_embedding(self, text: str, keys: Dict[str, str]) -> np.ndarray:
        """Get embedding optimized for documents (storage)."""
        ...

    def get_keywords(self, text: str, keys: Dict[str, str], **kwargs) -> List[str]:
        """Extract keywords from text."""
        ...
