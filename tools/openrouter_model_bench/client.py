"""OpenRouter chat client (stdlib only)."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


DEFAULT_URL = "https://openrouter.ai/api/v1/chat/completions"


def load_api_key(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit.strip()
    env = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OR_API_KEY")
    if env:
        return env.strip()
    # crawl up for .vscode/launch.json
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        launch = parent / ".vscode" / "launch.json"
        if launch.is_file():
            text = launch.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'"OPENROUTER_API_KEY"\s*:\s*"([^"]+)"', text)
            if m:
                return m.group(1).strip()
        # stop at filesystem root-ish after a few
        if parent == parent.parent:
            break
    # also try CWD
    launch = Path.cwd() / ".vscode" / "launch.json"
    if launch.is_file():
        text = launch.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'"OPENROUTER_API_KEY"\s*:\s*"([^"]+)"', text)
        if m:
            return m.group(1).strip()
    raise RuntimeError(
        "OPENROUTER_API_KEY not found in env or .vscode/launch.json"
    )


def chat_completion(
    *,
    api_key: str,
    model_id: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
    extra: Optional[Dict[str, Any]] = None,
    timeout: float = 180.0,
    url: str = DEFAULT_URL,
) -> Dict[str, Any]:
    """POST /chat/completions. Returns normalized result dict (never raises for HTTP)."""
    body: Dict[str, Any] = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if extra:
        # shallow merge; nested dicts from yaml already structured
        for k, v in extra.items():
            body[k] = v

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://local.openrouter-model-bench",
            "X-Title": "openrouter-model-bench",
        },
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        latency = time.perf_counter() - t0
        payload = json.loads(raw)
        return _normalize_success(payload, latency, model_id)
    except urllib.error.HTTPError as e:
        latency = time.perf_counter() - t0
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = str(e)
        return {
            "ok": False,
            "error": err_body,
            "latency_s": round(latency, 3),
            "model_id": model_id,
            "text": "",
            "usage": {},
            "finish_reason": None,
            "message_keys": [],
            "raw": None,
        }
    except Exception as e:
        latency = time.perf_counter() - t0
        return {
            "ok": False,
            "error": str(e),
            "latency_s": round(latency, 3),
            "model_id": model_id,
            "text": "",
            "usage": {},
            "finish_reason": None,
            "message_keys": [],
            "raw": None,
        }


def _normalize_success(payload: Dict[str, Any], latency: float, model_id: str) -> Dict[str, Any]:
    choice = (payload.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):
        text = "".join(
            (c.get("text") or "") if isinstance(c, dict) else str(c) for c in content
        )
    elif content is None:
        text = ""
    else:
        text = str(content)

    usage = payload.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    completion_tokens = usage.get("completion_tokens") or 0
    reasoning_tokens = details.get("reasoning_tokens") or 0
    content_tokens_est = max(0, int(completion_tokens) - int(reasoning_tokens))
    tps_total = (
        (completion_tokens / latency) if latency > 0 and completion_tokens else None
    )
    tps_content = (
        (content_tokens_est / latency) if latency > 0 and content_tokens_est else None
    )

    return {
        "ok": True,
        "error": None,
        "latency_s": round(latency, 3),
        "model_id": model_id,
        "text": text,
        "usage": usage,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
        "content_tokens_est": content_tokens_est,
        "prompt_tokens": usage.get("prompt_tokens"),
        "cost": usage.get("cost"),
        "tokens_per_sec_total": round(tps_total, 2) if tps_total else None,
        "tokens_per_sec_content": round(tps_content, 2) if tps_content else None,
        "finish_reason": choice.get("finish_reason"),
        "message_keys": list(msg.keys()),
        "has_empty_content": not bool(text.strip()),
        "raw": payload,
    }
