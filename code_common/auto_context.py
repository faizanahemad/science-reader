"""
auto_context.py — Auto history mode building blocks.

Public API
----------
AutoContextMode          Enum: DEEP | MEDIUM | LIGHT
AUTO_CONTEXT_CONFIGS     Per-mode parameter dict
retrieve_prior_context_llm_based(conversation, query, past_message_ids, lookback)
    Moved from Conversation.py. Windowed parallel LLM fact-extraction.
classify_messages_for_context(conversation, query, running_summary, mode)
    Windowed LLM classification: verbatim / summarised / none per message.
agentic_context_finder(conversation, query, running_summary, last_turn_text, api_keys, mode)
    Tool-calling agent that searches/reads messages for relevant context.
assemble_auto_context(conversation, classifier_result, agent_result,
                      llm_based_extracted_context, mode)
    Merges both finders with mode-aware dedup into a <messages>…</messages> string.

Nothing here touches the main reply flow. Import and call from Conversation.py
when integrating auto mode.
"""

from __future__ import annotations

import json
import logging
import re
import time
from enum import Enum
from textwrap import dedent
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mode definitions
# ---------------------------------------------------------------------------

class AutoContextMode(Enum):
    DEEP   = "deep"
    MEDIUM = "medium"
    LIGHT  = "light"


# All tuneable parameters in one place.
AUTO_CONTEXT_CONFIGS: dict[AutoContextMode, dict] = {
    AutoContextMode.DEEP: {
        # retrieve_prior_context: raw verbatim anchor turns
        "lookback_turns": 2,          # last N turns included verbatim as anchor
        # retrieve_prior_context_llm_based
        "llm_based_lookback": 50,
        "llm_based_single_call": False,
        # classify_messages_for_context
        "classify_lookback": 50,
        "classify_window_size": 5,
        # agentic_context_finder
        "agent_max_iterations": 3,
        # assemble: dedup rule
        # "any_verbatim_wins" — if ANY finder says verbatim, use verbatim
        "dedup_rule": "any_verbatim_wins",
        # memory pad injected into main prompt
        "inject_memory_pad": True,
    },
    AutoContextMode.MEDIUM: {
        "lookback_turns": 2,
        "llm_based_lookback": 30,
        "llm_based_single_call": False,
        "classify_lookback": 30,
        "classify_window_size": 5,
        "agent_max_iterations": 3,
        "dedup_rule": "any_verbatim_wins",
        "inject_memory_pad": False,
    },
    AutoContextMode.LIGHT: {
        "lookback_turns": 1,
        "llm_based_lookback": 20,
        "llm_based_single_call": True,   # single call, no windowing
        "classify_lookback": 20,
        "classify_window_size": 20,      # single window = single call
        "agent_max_iterations": 2,
        # "paraphrase_wins" — if ANY finder says paraphrase, use paraphrase
        "dedup_rule": "paraphrase_wins",
        "inject_memory_pad": False,
    },
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_llm(api_keys, model_name):
    from call_llm import CallLLm
    return CallLLm(api_keys, model_name=model_name, use_gpt4=False, use_16k=True)


def _superfast_model(conversation):
    from common import SUPERFAST_LLM
    return conversation.get_model_override("conversation_internal_model", SUPERFAST_LLM[0])


def _extract_user_answer(text: str) -> str:
    from Conversation import extract_user_answer
    return extract_user_answer(text)


def _compact_message_repr(msg: dict, index: int) -> dict:
    """Compact metadata-only representation for classifier input."""
    sender = msg.get("sender", "")
    entry: dict[str, Any] = {
        "index": index,
        "message_id": msg.get("message_id", ""),
        "sender": sender,
    }
    if sender == "user":
        entry["tldr"] = msg.get("user_ask_tldr") or msg.get("text", "")[:200]
        kw = msg.get("user_ask_keywords")
        if kw:
            entry["keywords"] = kw
        pc = msg.get("user_ask_prior_context")
        if pc:
            entry["prior_context"] = pc
    else:
        entry["tldr"] = msg.get("answer_tldr") or msg.get("text", "")[:200]
        kw = msg.get("answer_keywords")
        if kw:
            entry["keywords"] = kw
    return entry


# ---------------------------------------------------------------------------
# retrieve_prior_context_llm_based  (moved from Conversation.py)
# ---------------------------------------------------------------------------

_EXTRACT_SYSTEM = dedent("""
You are an assistant that extracts relevant information from conversation messages to help answer a user query.
Write in compact bullet points. Include specific details: numbers, names, dates, code references, technical terms.
Focus on actual information extraction. Be brief and concise.
If the messages contain nothing relevant to the query, write "No relevant information in this segment."
""").strip()

_EXTRACT_PROMPT = """\
## User Query (to be answered later):
{query}

## Conversation Summary (for context):
{summary}

## Messages to Extract From:
{messages_text}

---

## Your Task:
Extract facts, details, numbers, code snippets, decisions, preferences, and any other information \
from the above messages that would be useful for answering the user query.

Guidelines:
- Focus ONLY on extracting relevant information, do NOT attempt to answer the query.
- Write in compact bullet points.
- Include specific details: numbers, names, dates, code references, technical terms.
- Capture user preferences, constraints, requirements, decisions, conclusions.
- If nothing is relevant, write "No relevant information in this segment."
- Be short, brief and concise.

## Extracted Information (bullet points):
"""

_EXTRACT_PROMPT_MEDIUM = """\
## User Query:
{query}

## Conversation Summary:
{summary}

## Messages:
{messages_text}

Extract ONLY the most directly relevant facts for answering the query. \
Omit background, context, and tangential details. 3-5 bullet points max per window.

## Key facts (bullet points):
"""

_EXTRACT_PROMPT_LIGHT = """\
Query: {query}
Summary: {summary}
Messages:
{messages_text}

List only facts strictly necessary to answer the query. 1-3 bullets max. Be extremely terse.
"""


def _extraction_prompt_for_mode(mode: AutoContextMode) -> str:
    if mode == AutoContextMode.DEEP:
        return _EXTRACT_PROMPT
    if mode == AutoContextMode.MEDIUM:
        return _EXTRACT_PROMPT_MEDIUM
    return _EXTRACT_PROMPT_LIGHT


def retrieve_prior_context_llm_based(
    conversation,
    query: str,
    past_message_ids: list = [],
    required_message_lookback: int | None = None,
    mode: AutoContextMode = AutoContextMode.DEEP,
) -> dict:
    """
    Windowed parallel LLM fact-extraction from conversation history.

    Moved from Conversation.py. Conversation.retrieve_prior_context_llm_based
    now delegates here.

    Returns dict(extracted_context, summary, window_count, message_count).
    """
    from common import get_async_future, sleep_and_get_future_result, get_gpt4_word_count

    cfg = AUTO_CONTEXT_CONFIGS[mode]
    if required_message_lookback is None:
        required_message_lookback = cfg["llm_based_lookback"]
    single_call = cfg["llm_based_single_call"]
    extraction_prompt_template = _extraction_prompt_for_mode(mode)

    st = time.time()
    running_summary = conversation.running_summary

    futures_load = [
        get_async_future(conversation.get_field, "memory"),
        get_async_future(conversation.get_field, "messages"),
    ]
    _memory, messages = [sleep_and_get_future_result(f) for f in futures_load]

    _empty = dict(extracted_context="", summary=running_summary, window_count=0, message_count=0)
    if not messages:
        return _empty

    if past_message_ids:
        messages = [m for m in messages if m["message_id"] in past_message_ids]
        required_message_lookback = min(required_message_lookback, 16)

    messages = messages[-required_message_lookback:] if len(messages) > required_message_lookback else messages
    if not messages:
        return _empty

    # Build windows
    if single_call:
        # Light mode: one window covering everything
        message_windows = [messages[:-2]] if len(messages) > 2 else [messages]
        stride = len(messages)
    else:
        temp_messages = messages.copy()
        messages = messages[:-2]
        message_windows = []
        i = 0
        stride = 3  # default, overwritten per iteration
        while i < len(messages):
            remaining = len(messages) - i
            if remaining <= 6:
                window_size = stride = 3
            elif remaining <= 16:
                window_size = stride = 5
            else:
                window_size = stride = 6
            window = messages[i:i + window_size]
            if window:
                message_windows.append(window)
            i += stride
        if len(message_windows) > 1 and len(message_windows[-1]) == 1:
            message_windows[-2].extend(message_windows.pop())
        messages = temp_messages

    internal_model = _superfast_model(conversation)
    api_keys = conversation.get_api_keys()

    extraction_futures = []
    for window_idx, window in enumerate(message_windows):
        messages_text = "\n\n".join(
            f"<{m['sender']}>\n{_extract_user_answer(m['text'])}\n</{m['sender']}>"
            for m in window
        )
        prompt = extraction_prompt_template.format(
            query=query,
            summary=running_summary or "(No summary available)",
            messages_text=messages_text,
        )
        llm = _get_llm(api_keys, internal_model)
        future = get_async_future(llm, prompt, temperature=0.2, system=_EXTRACT_SYSTEM, stream=False)
        extraction_futures.append((window_idx, future))

    extraction_results = []
    for window_idx, future in extraction_futures:
        try:
            result = sleep_and_get_future_result(future, timeout=120)
            if result and result.strip() and "No relevant information" not in result:
                extraction_results.append((window_idx, re.sub(r"\n{3,}", "\n\n", result.strip())))
        except Exception as e:
            logger.warning("retrieve_prior_context_llm_based: window %d failed: %s", window_idx, e)

    extraction_results.sort(key=lambda x: x[0])

    if extraction_results:
        extracted_parts = []
        for wi, r in extraction_results:
            extracted_parts.append(f"### Context segment {wi + 1}:\n{r}")
        extracted_context = "\n\n".join(extracted_parts)
    else:
        extracted_context = ""

    logger.info(
        "retrieve_prior_context_llm_based [%s]: %d windows, %d yielded, %d tokens",
        mode.value, len(message_windows), len(extraction_results),
        get_gpt4_word_count(extracted_context),
    )
    return dict(
        extracted_context=extracted_context,
        summary=running_summary,
        window_count=len(message_windows),
        message_count=len(messages),
    )


# ---------------------------------------------------------------------------
# classify_messages_for_context
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM_DEEP = dedent("""
You classify conversation messages by how much detail is needed to answer a user query.
For each message output one of:
  "verbatim"    — full message text is needed (complex reasoning, code, exact details)
  "summarised"  — the TLDR/summary is sufficient
  "none"        — not relevant, skip

Output ONLY a JSON array. Each element: {"index": <int>, "message_id": "<str>", "classification": "<str>"}
No explanation, no markdown fences.
""").strip()

_CLASSIFY_SYSTEM_MEDIUM = dedent("""
You classify conversation messages for relevance to a user query. Be conservative — only mark
messages verbatim if the exact wording is truly necessary. Prefer "summarised" over "verbatim".
Output ONLY a JSON array: [{"index": <int>, "message_id": "<str>", "classification": "verbatim"|"summarised"|"none"}, ...]
""").strip()

_CLASSIFY_SYSTEM_LIGHT = dedent("""
Classify messages as "summarised" or "none" only. Never output "verbatim".
Output ONLY a JSON array: [{"index": <int>, "message_id": "<str>", "classification": "summarised"|"none"}, ...]
Mark only the most directly relevant messages as "summarised". Be aggressive about "none".
""").strip()

_CLASSIFY_PROMPT = dedent("""
Current user query: {query}
Conversation summary: {summary}
Messages (compact metadata):
{messages_json}

Classify each message. Output JSON array only.
""").strip()


def classify_messages_for_context(
    conversation,
    query: str,
    running_summary: str,
    mode: AutoContextMode = AutoContextMode.DEEP,
) -> list[dict]:
    """
    Classify each message as verbatim/summarised/none using windowed parallel LLM calls.
    Light mode uses a single call and never outputs verbatim.
    """
    from common import get_async_future, sleep_and_get_future_result

    cfg = AUTO_CONTEXT_CONFIGS[mode]
    max_messages = cfg["classify_lookback"]
    window_size = cfg["classify_window_size"]

    system = {
        AutoContextMode.DEEP:   _CLASSIFY_SYSTEM_DEEP,
        AutoContextMode.MEDIUM: _CLASSIFY_SYSTEM_MEDIUM,
        AutoContextMode.LIGHT:  _CLASSIFY_SYSTEM_LIGHT,
    }[mode]

    try:
        messages = conversation.get_message_list() or []
    except Exception:
        return []
    if not messages:
        return []

    window = messages[:-2] if len(messages) > 2 else messages
    window = window[-max_messages:]
    base_offset = max(0, len(messages) - 2 - len(window))

    compact = [_compact_message_repr(msg, base_offset + i) for i, msg in enumerate(window)]
    windows = [compact[i:i + window_size] for i in range(0, len(compact), window_size)]

    model = _superfast_model(conversation)
    api_keys = conversation.get_api_keys()

    futures = []
    for w in windows:
        llm = _get_llm(api_keys, model)
        prompt = _CLASSIFY_PROMPT.format(
            query=query,
            summary=running_summary or "(none)",
            messages_json=json.dumps(w, ensure_ascii=False),
        )
        futures.append(get_async_future(llm, prompt, system=system, temperature=0.1, stream=False))

    results: list[dict] = []
    for future in futures:
        try:
            raw = sleep_and_get_future_result(future, timeout=60)
            if not raw:
                continue
            raw = re.sub(r"```(?:json)?|```", "", raw).strip()
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and "classification" in item:
                        results.append(item)
        except Exception as e:
            logger.warning("classify_messages_for_context [%s]: window failed: %s", mode.value, e)

    results.sort(key=lambda x: x.get("index", 0))
    return results


# ---------------------------------------------------------------------------
# agentic_context_finder
# ---------------------------------------------------------------------------

_AGENT_SYSTEM_DEEP = dedent("""
You are a context-finding agent. Find conversation messages relevant to answering the current user query.
Use tools to search and read messages. You may make multiple tool calls per turn.
After reading, output your findings as JSON:
{"decisions": [{"message_id": "<id>", "mode": "verbatim"|"paraphrased", "reason": "<brief>"}], "done": true}
Rules:
- "verbatim" = full message text needed; "paraphrased" = TLDR sufficient
- Only include genuinely relevant messages
- Output the JSON when done
- If nothing relevant: {"decisions": [], "done": true}
""").strip()

_AGENT_SYSTEM_MEDIUM = dedent("""
You are a context-finding agent. Find the most relevant conversation messages for the user query.
Prefer "paraphrased" over "verbatim" unless exact wording is critical.
Use tools efficiently. Output JSON when done:
{"decisions": [{"message_id": "<id>", "mode": "verbatim"|"paraphrased"}], "done": true}
""").strip()

_AGENT_SYSTEM_LIGHT = dedent("""
You are a context-finding agent. Find only the most essential messages for the user query.
Use at most 2 tool calls total. Output only "paraphrased" (never "verbatim").
Output JSON when done: {"decisions": [{"message_id": "<id>", "mode": "paraphrased"}], "done": true}
If unsure, output {"decisions": [], "done": true}.
""").strip()

_AGENT_INITIAL_PROMPT = dedent("""
User query: {query}
Conversation summary: {summary}
Last turn: {last_turn}

Use tools to find relevant messages from earlier in the conversation, then output your decisions JSON.
""").strip()


def agentic_context_finder(
    conversation,
    query: str,
    running_summary: str,
    last_turn_text: str,
    api_keys: dict,
    mode: AutoContextMode = AutoContextMode.DEEP,
) -> list[dict]:
    """
    Tool-calling agent that searches/reads messages to find relevant context.
    Returns list of {message_id, mode: "verbatim"|"paraphrased"}.
    Completely fault-tolerant — any exception returns [].
    """
    try:
        from code_common.call_llm import call_llm as _cc_call_llm
        from code_common.tools import TOOL_REGISTRY, ToolContext
        from common import get_async_future, sleep_and_get_future_result

        cfg = AUTO_CONTEXT_CONFIGS[mode]
        max_iterations = cfg["agent_max_iterations"]
        model = _superfast_model(conversation)
        conversation_id = conversation.conversation_id

        tool_names = ["search_messages", "list_messages", "read_message",
                      "get_conversation_details", "get_conversation_memory_pad"]
        tools_config = TOOL_REGISTRY.get_openai_tools_param(tool_names)
        if not tools_config:
            return []

        system = {
            AutoContextMode.DEEP:   _AGENT_SYSTEM_DEEP,
            AutoContextMode.MEDIUM: _AGENT_SYSTEM_MEDIUM,
            AutoContextMode.LIGHT:  _AGENT_SYSTEM_LIGHT,
        }[mode]

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": _AGENT_INITIAL_PROMPT.format(
                query=query,
                summary=running_summary or "(none)",
                last_turn=last_turn_text[:800] if last_turn_text else "(none)",
            )},
        ]

        decisions: list[dict] = []

        for iteration in range(max_iterations + 1):
            is_last = iteration == max_iterations
            try:
                gen = _cc_call_llm(
                    keys=api_keys,
                    model_name=model,
                    messages=messages,
                    temperature=0.2,
                    stream=True,
                    tools=tools_config if not is_last else None,
                    tool_choice="none" if is_last else "auto",
                )
            except Exception as e:
                logger.warning("agentic_context_finder [%s]: LLM call failed iter=%d: %s", mode.value, iteration, e)
                break

            accumulated_text = ""
            tool_calls_in_round = []
            for chunk in gen:
                if isinstance(chunk, str):
                    accumulated_text += chunk
                elif isinstance(chunk, dict) and chunk.get("type") == "tool_call":
                    tool_calls_in_round.append(chunk)

            if accumulated_text:
                parsed = _parse_agent_decisions(accumulated_text)
                if parsed is not None:
                    decisions = parsed
                    break

            if not tool_calls_in_round:
                break

            # Build assistant message
            assistant_msg: dict = {"role": "assistant"}
            if accumulated_text:
                assistant_msg["content"] = accumulated_text
            assistant_msg["tool_calls"] = [
                {"id": tc.get("tool_id", f"call_{i}"), "type": "function",
                 "function": {"name": tc.get("tool_name", ""),
                              "arguments": json.dumps(tc.get("tool_input", {}))}}
                for i, tc in enumerate(tool_calls_in_round)
            ]
            messages.append(assistant_msg)

            # Execute tool calls in parallel
            tool_futures = []
            for tc in tool_calls_in_round:
                tool_input = {**tc.get("tool_input", {}), "conversation_id": conversation_id}
                tool_name = tc.get("tool_name", "")
                tool_id = tc.get("tool_id", "")
                ctx = ToolContext(conversation_id=conversation_id,
                                  user_email=getattr(conversation, "user_id", ""))
                tool_futures.append((tc, get_async_future(
                    TOOL_REGISTRY.execute, tool_name, tool_input, ctx, tool_id
                )))

            for tc, future in tool_futures:
                try:
                    result = sleep_and_get_future_result(future, timeout=30)
                    result_text = result.result or result.error or "no result"
                except Exception as e:
                    result_text = f"Tool error: {e}"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("tool_id", ""),
                    "content": str(result_text)[:4000],
                })

        return decisions

    except Exception as e:
        logger.warning("agentic_context_finder [%s]: failed: %s", mode.value, e)
        return []


def _parse_agent_decisions(text: str) -> list[dict] | None:
    """Extract decisions list from agent output. Returns None if not found/done."""
    # Try to find any JSON object containing "decisions" and "done": true
    # Use a broad search then validate — handles nested objects in the JSON
    for match in re.finditer(r'\{', text):
        start = match.start()
        # Find matching closing brace by counting depth
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        obj = json.loads(candidate)
                        if obj.get("done") is True and isinstance(obj.get("decisions"), list):
                            return [
                                {"message_id": d["message_id"], "mode": d.get("mode", "paraphrased")}
                                for d in obj["decisions"]
                                if isinstance(d, dict) and "message_id" in d
                            ]
                    except Exception:
                        pass
                    break
    return None


# ---------------------------------------------------------------------------
# assemble_auto_context
# ---------------------------------------------------------------------------

_RANK = {"verbatim": 2, "paraphrased": 1, "summarised": 1, "none": 0}


def assemble_auto_context(
    conversation,
    classifier_result: list[dict],
    agent_result: list[dict],
    llm_based_extracted_context: str = "",
    mode: AutoContextMode = AutoContextMode.DEEP,
) -> str:
    """
    Merge classifier and agent finder outputs into a <messages>…</messages> string.

    Dedup rules by mode:
      DEEP / MEDIUM  — any_verbatim_wins: if ANY finder says verbatim → verbatim
      LIGHT          — paraphrase_wins:   if ANY finder says paraphrase → paraphrase
                       (light mode classifier never outputs verbatim anyway)

    Appends llm_based_extracted_context after the messages block.
    """
    cfg = AUTO_CONTEXT_CONFIGS[mode]
    dedup_rule = cfg["dedup_rule"]

    try:
        messages = conversation.get_message_list() or []
    except Exception:
        return ""
    if not messages:
        return ""

    id_to_idx = {msg.get("message_id", ""): i for i, msg in enumerate(messages)}
    id_to_msg = {msg.get("message_id", ""): msg for msg in messages}

    # Collect all decisions
    all_decisions: dict[str, list[str]] = {}  # message_id → [mode, ...]

    for item in classifier_result:
        mid = item.get("message_id", "")
        cls = item.get("classification", "none")
        mode_str = "paraphrased" if cls == "summarised" else cls
        all_decisions.setdefault(mid, []).append(mode_str)

    for item in agent_result:
        mid = item.get("message_id", "")
        mode_str = item.get("mode", "paraphrased")
        all_decisions.setdefault(mid, []).append(mode_str)

    # Apply dedup rule
    merged: dict[str, str] = {}
    for mid, modes in all_decisions.items():
        if dedup_rule == "any_verbatim_wins":
            # highest rank wins
            final = max(modes, key=lambda m: _RANK.get(m, 0))
        else:  # paraphrase_wins (light)
            # lowest non-none rank wins: verbatim → paraphrased, paraphrased stays
            non_none = [m for m in modes if m != "none"]
            if not non_none:
                final = "none"
            else:
                final = "paraphrased"  # light never uses verbatim
        if final != "none":
            merged[mid] = final

    if not merged:
        result = ""
    else:
        ordered = sorted(merged.items(), key=lambda x: id_to_idx.get(x[0], 999999))
        parts = []
        for mid, final_mode in ordered:
            msg = id_to_msg.get(mid)
            if msg is None:
                continue
            sender = msg.get("sender", "user")
            if final_mode == "verbatim":
                text = _extract_user_answer(msg.get("text", ""))
            else:
                if sender == "user":
                    text = msg.get("user_ask_tldr") or msg.get("text", "")[:300]
                else:
                    text = msg.get("answer_tldr") or msg.get("text", "")[:300]
            parts.append(f"<{sender}>\n{text}\n</{sender}>")
        result = "\n\n".join(parts)

    if llm_based_extracted_context and llm_based_extracted_context.strip():
        result = (result + "\n\n" + llm_based_extracted_context) if result else llm_based_extracted_context

    if not result:
        return "<messages>\n\n</messages>"
    return "<messages>\n" + result + "\n</messages>"
