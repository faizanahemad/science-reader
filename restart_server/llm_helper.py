"""
LLM helper for diagnosing service restart failures.

Uses the project's ``code_common.call_llm`` utility to send recent screen
output and restart logs to an LLM, which analyses the failure and suggests
concrete fix steps.

This module is intentionally fail-safe: if the LLM call cannot be made
(missing key, import error, API failure) a descriptive fallback string is
returned instead of raising.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import List, Optional

logger = logging.getLogger(__name__)

# Ensure the project root is importable (for ``code_common``).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def diagnose_restart_failure(
    service_name: str,
    display_name: str,
    restart_logs: List[str],
    screen_output: Optional[str] = None,
) -> str:
    """Use an LLM to diagnose why a service restart failed.

    Parameters
    ----------
    service_name:
        Internal service identifier (e.g. ``"main_server"``).
    display_name:
        Human-readable name (e.g. ``"Main Python Server"``).
    restart_logs:
        Log messages produced during the restart attempt.
    screen_output:
        Recent screen scrollback output for additional context.

    Returns
    -------
    str
        LLM analysis text, or a fallback error string.
    """
    # -- Import guard --
    try:
        from code_common.call_llm import call_llm  # type: ignore[import-untyped]
    except ImportError:
        logger.error("Could not import call_llm from code_common")
        return "LLM diagnosis unavailable — could not import call_llm module."

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return "LLM diagnosis unavailable — OPENROUTER_API_KEY not set."

    keys = {"OPENROUTER_API_KEY": api_key}
    model = "openai/gpt-4o-mini"

    system_prompt = (
        "You are a Linux sysadmin assistant. A service restart was attempted "
        "via GNU screen and it failed. Analyse the logs and screen output to "
        "determine the root cause and suggest concrete fix steps. Be concise "
        "and actionable. If the output shows a specific error message, quote it."
    )

    log_text = "\n".join(restart_logs) if restart_logs else "(no restart logs)"
    screen_text = (
        screen_output[:6000] if screen_output else "(no screen output available)"
    )

    user_prompt = (
        f"Service: {display_name} ({service_name})\n\n"
        f"Restart attempt logs:\n{log_text}\n\n"
        f"Recent screen output (last ~200 lines):\n{screen_text}\n\n"
        "What went wrong and how to fix it?"
    )

    try:
        result = call_llm(
            keys=keys,
            model_name=model,
            text=user_prompt,
            system=system_prompt,
            temperature=0.3,
            stream=False,
        )
        return str(result)
    except Exception as exc:
        logger.error("LLM diagnosis call failed: %s", exc)
        return f"LLM diagnosis failed: {exc}"
