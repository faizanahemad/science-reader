"""CodeCommon LLM provider — wraps code_common.call_llm for chat-app integration.

This is the provider the chat app injects. It delegates to the existing
code_common functions, preserving all current behavior (model routing,
retry logic, embedding model selection, etc.).
"""

from typing import Any, Dict, List, Optional

import numpy as np


class CodeCommonProvider:
    """LLMProvider implementation backed by code_common.call_llm."""

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
        from code_common.call_llm import call_llm
        return call_llm(
            keys, model, text,
            images=images or [],
            temperature=temperature,
            stream=stream,
            system=system,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )

    def get_query_embedding(self, text: str, keys: Dict[str, str]) -> np.ndarray:
        from code_common.call_llm import get_query_embedding
        return get_query_embedding(text, keys)

    def get_document_embedding(self, text: str, keys: Dict[str, str]) -> np.ndarray:
        from code_common.call_llm import get_document_embedding
        return get_document_embedding(text, keys)

    def get_keywords(self, text: str, keys: Dict[str, str], **kwargs) -> List[str]:
        from code_common.call_llm import getKeywordsFromText
        return getKeywordsFromText(text, keys, **kwargs)
