"""
LLM-powered recovery agent for service restart failures.

Two modes of operation:

1. **Diagnosis only** (``diagnose_restart_failure``): single LLM call that
   returns a text analysis with suggestions.  Fast, read-only.

2. **Active recovery** (``recover_service``): agentic tool-calling loop where
   the LLM can execute bash commands, interact with GNU screen sessions,
   check ports, and read logs — iterating until the service is running or
   it gives up.  This is the "get the job done" mode.

The recovery agent talks to the OpenRouter API directly (OpenAI-compatible)
so we get full control over the tool-calling request/response cycle.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Ensure project root is importable (for code_common).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_RECOVERY_ITERATIONS = 12
_BASH_TIMEOUT = 30  # seconds per command
_OUTPUT_CHAR_LIMIT = 8000  # max chars returned per tool call
_MODEL = "openai/gpt-4o-mini"

# Commands we refuse to execute.
_BLOCKED_PATTERNS = [
    r"\brm\s+(-\w*\s+)*-rf?\s+/\s",  # rm -rf /
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bpoweroff\b",
    r"\bmkfs\b",
    r"\bdd\s+.*of=/dev/",
    r"\b:(){ :\|:& };:",  # fork bomb
]

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling format)
# ---------------------------------------------------------------------------

RECOVERY_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": (
                "Execute a bash command on the server and return stdout + stderr. "
                "Use for diagnostics (ps, netstat, cat, grep, journalctl, head, "
                "tail, etc.), checking files, inspecting environment, or running "
                "small fix-up commands. Do NOT use for long-running processes — "
                "use screen_send_keys for those."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 30, max 60)",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screen_send_keys",
            "description": (
                "Type a command (followed by Enter) into a GNU screen session. "
                "Use this to start long-running services. For very long commands "
                "with env vars, first write the command to a /tmp script with "
                "run_bash, then send 'bash /tmp/script.sh' here."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "screen_name": {
                        "type": "string",
                        "description": "Screen session name",
                    },
                    "command": {
                        "type": "string",
                        "description": "Command to type into the session",
                    },
                },
                "required": ["screen_name", "command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screen_send_ctrl_c",
            "description": "Send Ctrl+C (SIGINT) to a screen session to interrupt the running process.",
            "parameters": {
                "type": "object",
                "properties": {
                    "screen_name": {
                        "type": "string",
                        "description": "Screen session name",
                    },
                },
                "required": ["screen_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_port",
            "description": (
                "Check if a TCP port is listening on localhost. Returns whether "
                "the service is responding. Use after sending a startup command "
                "to verify the service came up."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "port": {"type": "integer", "description": "TCP port number"},
                },
                "required": ["port"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_screen_output",
            "description": (
                "Dump the recent scrollback output from a screen session. "
                "Use to read error messages, stack traces, startup logs, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "screen_name": {
                        "type": "string",
                        "description": "Screen session name",
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of scrollback lines (default 150)",
                    },
                },
                "required": ["screen_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait_seconds",
            "description": (
                "Pause for N seconds. Use after sending a startup command to "
                "give the service time to boot before checking the port."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {
                        "type": "integer",
                        "description": "Seconds to wait (max 30)",
                    },
                },
                "required": ["seconds"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_result",
            "description": (
                "Call this when recovery is complete. You MUST call this to "
                "end the recovery session — either on success or when you've "
                "exhausted your options."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "success": {
                        "type": "boolean",
                        "description": "True if service is now running",
                    },
                    "summary": {
                        "type": "string",
                        "description": "What you did and the final outcome",
                    },
                },
                "required": ["success", "summary"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------


def _is_command_blocked(command: str) -> bool:
    """Return True if the command matches a dangerous pattern."""
    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, command):
            return True
    return False


def _truncate(text: str, limit: int = _OUTPUT_CHAR_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated, {len(text)} total chars)"


def _exec_run_bash(args: dict) -> str:
    """Execute a bash command and return combined output."""
    command = args.get("command", "")
    timeout = min(args.get("timeout", _BASH_TIMEOUT), 60)

    if not command:
        return "Error: empty command"

    if _is_command_blocked(command):
        return (
            f"BLOCKED: command matched a safety filter. Refused to execute: {command}"
        )

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_PROJECT_ROOT,
        )
        output_parts = []
        if result.stdout:
            output_parts.append(result.stdout)
        if result.stderr:
            output_parts.append(f"[stderr]\n{result.stderr}")
        output_parts.append(f"[exit code: {result.returncode}]")
        return _truncate("\n".join(output_parts))
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except Exception as exc:
        return f"Error executing command: {exc}"


def _exec_screen_send_keys(args: dict) -> str:
    """Send keystrokes to a screen session."""
    screen_name = args.get("screen_name", "")
    command = args.get("command", "")

    if not screen_name or not command:
        return "Error: screen_name and command are required"

    # For long commands, use the script-file approach
    if len(command) > 700:
        script_path = f"/tmp/recovery_cmd_{screen_name}.sh"
        try:
            with open(script_path, "w") as fh:
                fh.write("#!/usr/bin/env bash\n")
                fh.write(command + "\n")
            os.chmod(script_path, 0o700)
            send_cmd = f"bash {script_path}"
        except Exception as exc:
            return f"Error writing script: {exc}"
    else:
        send_cmd = command

    result = subprocess.run(
        ["screen", "-S", screen_name, "-X", "stuff", f"{send_cmd}\n"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return f"Sent to screen '{screen_name}': {send_cmd[:200]}"
    return f"Failed to send to screen (exit {result.returncode}): {result.stderr}"


def _exec_screen_send_ctrl_c(args: dict) -> str:
    """Send Ctrl+C to a screen session."""
    screen_name = args.get("screen_name", "")
    if not screen_name:
        return "Error: screen_name is required"

    result = subprocess.run(
        ["screen", "-S", screen_name, "-X", "stuff", "\x03"],
        capture_output=True,
        text=True,
    )
    return (
        f"Ctrl+C sent to '{screen_name}'"
        if result.returncode == 0
        else f"Failed: {result.stderr}"
    )


def _exec_check_port(args: dict) -> str:
    """Check if a port is listening."""
    port = args.get("port", 0)
    if not port:
        return "Error: port is required"
    try:
        with socket.create_connection(("localhost", port), timeout=3):
            return f"Port {port}: OPEN — service is responding"
    except (socket.timeout, ConnectionRefusedError, OSError):
        return f"Port {port}: CLOSED — service is not responding"


def _exec_get_screen_output(args: dict) -> str:
    """Dump screen scrollback."""
    screen_name = args.get("screen_name", "")
    lines = min(args.get("lines", 150), 500)

    if not screen_name:
        return "Error: screen_name is required"

    # Check screen exists first
    ls_result = subprocess.run(["screen", "-ls"], capture_output=True, text=True)
    if screen_name not in ls_result.stdout:
        return f"Screen session '{screen_name}' does not exist"

    tmp_path = tempfile.mktemp(suffix=".txt", prefix=f"recovery_{screen_name}_")
    try:
        subprocess.run(
            ["screen", "-S", screen_name, "-X", "scrollback", str(lines)],
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["screen", "-S", screen_name, "-X", "hardcopy", "-h", tmp_path],
            capture_output=True,
            text=True,
        )
        time.sleep(0.5)
        if os.path.exists(tmp_path):
            with open(tmp_path, "r", errors="replace") as fh:
                return _truncate(fh.read())
        return "(hardcopy produced no output)"
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _exec_wait_seconds(args: dict) -> str:
    """Pause execution."""
    seconds = min(args.get("seconds", 5), 30)
    time.sleep(seconds)
    return f"Waited {seconds} seconds"


# Dispatcher
_TOOL_HANDLERS = {
    "run_bash": _exec_run_bash,
    "screen_send_keys": _exec_screen_send_keys,
    "screen_send_ctrl_c": _exec_screen_send_ctrl_c,
    "check_port": _exec_check_port,
    "get_screen_output": _exec_get_screen_output,
    "wait_seconds": _exec_wait_seconds,
    # report_result is handled specially in the loop
}


def _execute_tool(name: str, raw_args: str, action_log: List[str]) -> str:
    """Parse tool arguments, execute, and log the action."""
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
    except json.JSONDecodeError:
        return f"Error: could not parse tool arguments: {raw_args}"

    handler = _TOOL_HANDLERS.get(name)
    if not handler:
        return f"Unknown tool: {name}"

    # Log the action
    if name == "run_bash":
        action_log.append(f"[bash] {args.get('command', '')[:120]}")
    elif name == "screen_send_keys":
        action_log.append(
            f"[screen → {args.get('screen_name')}] {args.get('command', '')[:80]}"
        )
    elif name == "screen_send_ctrl_c":
        action_log.append(f"[Ctrl+C → {args.get('screen_name')}]")
    elif name == "check_port":
        action_log.append(f"[check port {args.get('port')}]")
    elif name == "get_screen_output":
        action_log.append(f"[read screen → {args.get('screen_name')}]")
    elif name == "wait_seconds":
        action_log.append(f"[wait {args.get('seconds', 5)}s]")

    result = handler(args)
    return result


# ---------------------------------------------------------------------------
# OpenRouter API (direct HTTP, for tool-calling control)
# ---------------------------------------------------------------------------


def _call_openrouter(
    messages: List[dict],
    tools: List[dict],
    api_key: str,
    model: str = _MODEL,
) -> dict:
    """Make a single chat completion call to OpenRouter with tools.

    Returns the assistant message dict (with possible tool_calls).
    Raises on HTTP/API errors.
    """
    import requests as _requests

    response = _requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.3,
        },
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        raise RuntimeError(f"OpenRouter API error: {data['error']}")

    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError(f"OpenRouter returned no choices: {data}")

    return choices[0]["message"]


# ---------------------------------------------------------------------------
# Public API: diagnosis (read-only, single call)
# ---------------------------------------------------------------------------


def diagnose_restart_failure(
    service_name: str,
    display_name: str,
    restart_logs: List[str],
    screen_output: Optional[str] = None,
) -> str:
    """Single-shot LLM diagnosis. Returns analysis text.

    This is the lightweight, read-only version — no commands are executed.
    """
    try:
        from code_common.call_llm import call_llm
    except ImportError:
        logger.error("Could not import call_llm from code_common")
        return "LLM diagnosis unavailable — could not import call_llm module."

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return "LLM diagnosis unavailable — OPENROUTER_API_KEY not set."

    keys = {"OPENROUTER_API_KEY": api_key}

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
            model_name=_MODEL,
            text=user_prompt,
            system=system_prompt,
            temperature=0.3,
            stream=False,
        )
        return str(result)
    except Exception as exc:
        logger.error("LLM diagnosis call failed: %s", exc)
        return f"LLM diagnosis failed: {exc}"


# ---------------------------------------------------------------------------
# Public API: active recovery (agentic, executes commands)
# ---------------------------------------------------------------------------


def recover_service(
    service_name: str,
    display_name: str,
    screen_name: str,
    port: int,
    restart_logs: List[str],
    screen_output: Optional[str] = None,
    cached_command: Optional[str] = None,
) -> Tuple[bool, str, List[str]]:
    """LLM-driven recovery agent that can execute commands until the service is up.

    Parameters
    ----------
    service_name:
        Internal key (e.g. ``"main_server"``).
    display_name:
        Human-readable label.
    screen_name:
        GNU screen session name.
    port:
        TCP port the service should listen on.
    restart_logs:
        Logs from the failed restart attempt.
    screen_output:
        Recent screen scrollback.
    cached_command:
        The known startup command, if available.

    Returns
    -------
    (success, summary, action_log)
        success: whether the service port is now open.
        summary: LLM's final report or error message.
        action_log: list of human-readable action descriptions.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return False, "Recovery unavailable — OPENROUTER_API_KEY not set.", []

    action_log: List[str] = []
    action_log.append("Starting LLM recovery agent…")

    # -- Build initial context for the LLM --
    system_prompt = (
        "You are an expert Linux sysadmin recovery agent. A service failed to "
        "restart and you must get it running. You have tools to execute bash "
        "commands, interact with GNU screen sessions, check ports, and read "
        "screen output.\n\n"
        "APPROACH:\n"
        "1. Read the screen output to understand the error.\n"
        "2. Diagnose the root cause.\n"
        "3. Fix it — run commands, kill stuck processes, fix permissions, "
        "   restart the service, whatever is needed.\n"
        "4. Verify the service is running by checking the port.\n"
        "5. Call report_result when done.\n\n"
        "RULES:\n"
        "- Be methodical: diagnose first, then act.\n"
        "- After sending a startup command to screen, wait 10-20 seconds "
        "  before checking the port.\n"
        "- If a command is too long for screen_send_keys, write it to a "
        "  /tmp/*.sh file with run_bash first, then send 'bash /tmp/file.sh' "
        "  to the screen session.\n"
        "- If you don't know the startup command, check screen scrollback "
        "  or shell history (~/.bash_history, ~/.zsh_history).\n"
        "- Don't give up after one try. If the first fix doesn't work, "
        "  read the new error and try again.\n"
        "- You MUST call report_result to finish.\n"
    )

    log_text = "\n".join(restart_logs) if restart_logs else "(none)"
    screen_text = _truncate(screen_output, 6000) if screen_output else "(not captured)"
    cmd_text = (
        cached_command
        if cached_command
        else "(unknown — discover from screen or history)"
    )

    user_prompt = (
        f"SERVICE: {display_name}\n"
        f"SCREEN SESSION: {screen_name}\n"
        f"EXPECTED PORT: {port}\n"
        f"STARTUP COMMAND: {cmd_text}\n\n"
        f"FAILED RESTART LOGS:\n{log_text}\n\n"
        f"RECENT SCREEN OUTPUT:\n{screen_text}\n\n"
        f"The service is NOT running. Port {port} is not responding. "
        f"Please diagnose and fix it."
    )

    messages: List[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # -- Agent loop --
    iterations = 0
    final_success = False
    final_summary = "Recovery agent did not complete."

    try:
        while iterations < _MAX_RECOVERY_ITERATIONS:
            iterations += 1
            action_log.append(f"--- LLM call #{iterations} ---")

            try:
                assistant_msg = _call_openrouter(messages, RECOVERY_TOOLS, api_key)
            except Exception as exc:
                action_log.append(f"LLM API error: {exc}")
                final_summary = f"Recovery aborted — LLM API error: {exc}"
                break

            messages.append(assistant_msg)

            # If the LLM returned text (thinking/explanation), log it
            text_content = assistant_msg.get("content")
            if text_content:
                action_log.append(f"[LLM] {text_content[:300]}")

            # Process tool calls
            tool_calls = assistant_msg.get("tool_calls")
            if not tool_calls:
                # No tool calls and no report_result — LLM is done talking
                action_log.append("LLM returned no tool calls — ending loop")
                final_summary = (
                    text_content or "Recovery agent finished without explicit report."
                )
                break

            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                fn_args = tc["function"]["arguments"]
                tc_id = tc["id"]

                # Handle the terminal report_result tool
                if fn_name == "report_result":
                    try:
                        parsed = (
                            json.loads(fn_args) if isinstance(fn_args, str) else fn_args
                        )
                    except json.JSONDecodeError:
                        parsed = {"success": False, "summary": fn_args}

                    final_success = parsed.get("success", False)
                    final_summary = parsed.get("summary", "No summary provided")
                    action_log.append(
                        f"[report_result] success={final_success}: {final_summary}"
                    )

                    # Append tool response so the API is happy
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": "Acknowledged. Session ended.",
                        }
                    )
                    # Break out of both loops
                    iterations = _MAX_RECOVERY_ITERATIONS
                    break

                # Execute the tool
                tool_result = _execute_tool(fn_name, fn_args, action_log)
                action_log.append(f"  → {tool_result[:200]}")

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": tool_result,
                    }
                )

        else:
            action_log.append(f"Hit max iterations ({_MAX_RECOVERY_ITERATIONS})")
            final_summary = (
                f"Recovery agent hit iteration limit ({_MAX_RECOVERY_ITERATIONS})."
            )

    except Exception as exc:
        logger.error("Recovery agent crashed: %s", exc, exc_info=True)
        action_log.append(f"Recovery agent error: {exc}")
        final_summary = f"Recovery agent crashed: {exc}"

    # Final port check regardless of what the LLM said
    try:
        with socket.create_connection(("localhost", port), timeout=3):
            final_success = True
            if "not responding" in final_summary.lower() or not final_success:
                action_log.append(f"Port {port} is actually OPEN now — marking success")
                final_summary += " (port verified open)"
    except (socket.timeout, ConnectionRefusedError, OSError):
        if final_success:
            action_log.append(f"Port {port} still closed despite LLM claiming success")
            final_success = False
            final_summary += " (WARNING: port still closed)"

    action_log.append(f"Recovery finished: success={final_success}")
    return final_success, final_summary, action_log
