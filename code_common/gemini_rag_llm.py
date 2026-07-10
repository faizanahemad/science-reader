"""Back-compat facade for host-local CLI Main Models.

All logic lives in ``code_common.local_cli_llms`` (both ``local/gemini-rag``
and ``local/gemini-agent``). This module re-exports the gemini-rag names so
existing imports keep working.
"""

from code_common.local_cli_llms import (  # noqa: F401
    GEMINI_AGENT_AVAILABLE,
    GEMINI_AGENT_MODEL,
    GEMINI_AGENT_MODEL_ALIASES,
    GEMINI_AGENT_SCRIPT_PATH,
    GEMINI_RAG_AVAILABLE,
    GEMINI_RAG_MODEL,
    GEMINI_RAG_MODEL_ALIASES,
    GEMINI_RAG_SCRIPT_PATH,
    build_lean_query,
    call_gemini_agent_llm,
    call_gemini_rag_llm,
    call_local_cli_llm,
    canonicalize_gemini_rag_model,
    canonicalize_local_cli_model,
    is_gemini_agent_model,
    is_gemini_rag_model,
    is_local_cli_model,
    run_gemini_agent_query,
    run_gemini_rag_query,
)
