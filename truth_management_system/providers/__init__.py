"""LLM provider abstraction for the PKB/TMS package.

The LLMProvider protocol defines the interface that decouples the TMS core
from any specific LLM implementation. Two providers ship:

- CodeCommonProvider: wraps the chat app's code_common.call_llm (host injects)
- (future) DefaultProvider: self-contained OpenRouter/OpenAI impl for standalone
"""

from .base import LLMProvider
from .codecommon_provider import CodeCommonProvider

__all__ = ["LLMProvider", "CodeCommonProvider"]
