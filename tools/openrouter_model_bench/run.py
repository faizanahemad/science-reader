#!/usr/bin/env python3
"""OpenRouter hard-bench runner.

Usage examples:
  # run all models in models.yaml
  python -m tools.openrouter_model_bench.run

  # only some keys
  python -m tools.openrouter_model_bench.run --models mercury-2,gemini-3.1-lite-nr

  # ad-hoc models without editing yaml (repeatable)
  python -m tools.openrouter_model_bench.run \\
    --add 'flash-prev|google/gemini-2.5-flash|{}' \\
    --add 'qwen-plus|qwen/qwen-2.5-72b-instruct|{}'

  # ad-hoc with extra JSON (reasoning etc)
  python -m tools.openrouter_model_bench.run \\
    --add 'g35|google/gemini-3.5-flash|{"reasoning":{"effort":"minimal"},"include_reasoning":false}'

  # write report under results/
  python -m tools.openrouter_model_bench.run --out-dir tools/openrouter_model_bench/results
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow `python tools/openrouter_model_bench/run.py` as well as -m
_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_DIR.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.openrouter_model_bench.client import chat_completion, load_api_key  # noqa: E402
from tools.openrouter_model_bench.prompts import all_prompts  # noqa: E402
from tools.openrouter_model_bench.report import format_report, summarize  # noqa: E402
from tools.openrouter_model_bench.scoring import score_checks  # noqa: E402


def _load_yaml_models(path: Path) -> List[Dict[str, Any]]:
    try:
        import yaml  # type: ignore
    except ImportError:
        # minimal yaml subset for our flat registry file
        return _load_models_miniyaml(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    models = data.get("models") or []
    out = []
    for m in models:
        if m.get("enabled", True) is False:
            continue
        out.append(
            {
                "key": m["key"],
                "id": m["id"],
                "extra": m.get("extra") or {},
                "notes": m.get("notes"),
            }
        )
    return out


def _load_models_miniyaml(path: Path) -> List[Dict[str, Any]]:
    """Tiny fallback parser for models.yaml without PyYAML (best-effort)."""
    # Prefer json sibling if present; otherwise require pyyaml via error.
    # Real runs should have pyyaml in env; fallback uses json.loads for --add only.
    try:
        import yaml  # noqa
        return _load_yaml_models(path)
    except ImportError:
        pass
    # Manual: use json by converting via a soft dependency-free path —
    # actually re-implement with pure line-oriented parse for our known schema.
    text = path.read_text(encoding="utf-8")
    # Very small state machine for list of models with nested extra.
    # If this fails, instruct user to install pyyaml.
    try:
        return _manual_parse_models_yaml(text)
    except Exception as e:
        raise RuntimeError(
            f"Failed to parse {path} without PyYAML ({e}). "
            "Install pyyaml or pass models only via --add."
        ) from e


def _manual_parse_models_yaml(text: str) -> List[Dict[str, Any]]:
    # Convert a constrained yaml subset → structures using indentation talk.
    # We only need key/id/extra/notes/enabled.
    models: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    extra_lines: List[str] = []
    in_extra = False
    extra_indent = 0

    def flush_extra():
        nonlocal extra_lines, in_extra, cur
        if cur is None or not extra_lines:
            in_extra = False
            extra_lines = []
            return
        # parse nested yaml-ish dict with 2-level keys using json after crude transform is hard.
        # Use yaml-less approach: only support shallow and one nested mapping for reasoning.
        # Join and evaluate via a micro-parser:
        extra = _parse_extra_block(extra_lines)
        cur["extra"] = extra
        in_extra = False
        extra_lines = []

    for raw in text.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if line.startswith("- key:"):
            if cur:
                flush_extra()
                if cur.get("enabled", True) is not False:
                    models.append(cur)
            cur = {
                "key": line.split(":", 1)[1].strip().strip('"').strip("'"),
                "id": "",
                "extra": {},
                "notes": None,
            }
            in_extra = False
            continue
        if cur is None:
            continue
        if line.startswith("id:"):
            flush_extra()
            cur["id"] = line.split(":", 1)[1].strip().strip('"').strip("'")
            continue
        if line.startswith("notes:"):
            flush_extra()
            notes = line.split(":", 1)[1].strip()
            if notes.startswith('"') and notes.endswith('"'):
                notes = notes[1:-1]
            cur["notes"] = notes
            continue
        if line.startswith("enabled:"):
            flush_extra()
            cur["enabled"] = line.split(":", 1)[1].strip().lower() == "true"
            continue
        if line.startswith("extra:"):
            flush_extra()
            in_extra = True
            extra_indent = indent
            extra_lines = []
            rest = line.split(":", 1)[1].strip()
            if rest and rest != "{}":
                # inline json?
                try:
                    cur["extra"] = json.loads(rest)
                    in_extra = False
                except Exception:
                    pass
            continue
        if in_extra:
            if indent <= extra_indent and not line.startswith("-"):
                flush_extra()
                # reprocess? skip; next fields handled above only on exact startswith
            else:
                extra_lines.append(raw)
                continue
    if cur:
        flush_extra()
        if cur.get("enabled", True) is not False:
            models.append(cur)
    return models


def _parse_extra_block(lines: List[str]) -> Dict[str, Any]:
    """Parse indented key: value block; supports one nested mapping."""
    root: Dict[str, Any] = {}
    stack = [( -1, root )]  # indent, dict
    for raw in lines:
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if val == "" or val == "|" or val == ">":
            child: Dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _coerce_scalar(val)
    return root


def _coerce_scalar(val: str) -> Any:
    if (val.startswith('"') and val.endswith('"')) or (
        val.startswith("'") and val.endswith("'")
    ):
        return val[1:-1]
    low = val.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low == "null" or low == "~":
        return None
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        return val


def _parse_add(spec: str) -> Dict[str, Any]:
    """key|model_id|json_extra"""
    parts = spec.split("|", 2)
    if len(parts) < 2:
        raise argparse.ArgumentTypeError(
            "--add format: key|provider/model|optional_json_extra"
        )
    key, mid = parts[0].strip(), parts[1].strip()
    extra = {}
    if len(parts) == 3 and parts[2].strip():
        extra = json.loads(parts[2])
    return {"key": key, "id": mid, "extra": extra, "notes": "ad-hoc via --add"}


def run_one(
    api_key: str,
    model: Dict[str, Any],
    prompt: Dict[str, Any],
    attempt: int,
    timeout: float,
) -> Dict[str, Any]:
    resp = chat_completion(
        api_key=api_key,
        model_id=model["id"],
        system=prompt["system"],
        user=prompt["user"],
        max_tokens=prompt["max_tokens"],
        temperature=prompt["temp"],
        extra=model.get("extra") or {},
        timeout=timeout,
    )
    text = resp.get("text") or ""
    checks = score_checks(text, prompt.get("checks") or {})
    return {
        "model_key": model["key"],
        "model_id": model["id"],
        "prompt": prompt["key"],
        "category": prompt["category"],
        "attempt": attempt,
        "ok": resp.get("ok", False),
        "error": resp.get("error"),
        "latency_s": resp.get("latency_s"),
        "text": text,
        "usage": resp.get("usage") or {},
        "completion_tokens": resp.get("completion_tokens"),
        "reasoning_tokens": resp.get("reasoning_tokens"),
        "content_tokens_est": resp.get("content_tokens_est"),
        "prompt_tokens": resp.get("prompt_tokens"),
        "cost": resp.get("cost"),
        "tokens_per_sec_total": resp.get("tokens_per_sec_total"),
        "tokens_per_sec_content": resp.get("tokens_per_sec_content"),
        "finish_reason": resp.get("finish_reason"),
        "message_keys": resp.get("message_keys"),
        "has_empty_content": resp.get("has_empty_content"),
        "checks": checks,
        "check_score": sum(1 for v in checks.values() if v),
        "check_total": len(checks),
    }


def run_bench(
    models: List[Dict[str, Any]],
    *,
    api_key: str,
    categories: Optional[List[str]] = None,
    only_prompts: Optional[List[str]] = None,
    timeout: float = 180.0,
    parallel_models: bool = True,
) -> List[Dict[str, Any]]:
    prompts = all_prompts()
    if categories:
        cats = set(categories)
        prompts = [p for p in prompts if p["category"] in cats]
    if only_prompts:
        want = set(only_prompts)
        prompts = [p for p in prompts if p["key"] in want]

    results: List[Dict[str, Any]] = []
    workers = max(1, len(models)) if parallel_models else 1

    for p in prompts:
        repeats = int(p.get("speed_repeats") or 1)
        for attempt in range(1, repeats + 1):
            label = (
                f"{p['key']} attempt {attempt}/{repeats}"
                if repeats > 1
                else p["key"]
            )
            print(f"\n=== {label} ({p['category']}) ===", flush=True)
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {
                    ex.submit(run_one, api_key, m, p, attempt, timeout): m["key"]
                    for m in models
                }
                for fut in as_completed(futs):
                    r = fut.result()
                    results.append(r)
                    ok = f"{r['check_score']}/{r['check_total']}"
                    print(
                        f"  {r['model_key']}: {r['latency_s']}s  "
                        f"comp={r.get('completion_tokens')} reason={r.get('reasoning_tokens')} "
                        f"content~{r.get('content_tokens_est')}  "
                        f"tps={r.get('tokens_per_sec_total')}  checks={ok} "
                        f"empty={r.get('has_empty_content')} err={bool(r.get('error'))}",
                        flush=True,
                    )
                    preview = (r.get("text") or "").replace("\n", " \\n ")[:200]
                    print(f"    preview: {preview}", flush=True)
    return results


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="OpenRouter hard multi-model bench")
    ap.add_argument(
        "--models-yaml",
        default=str(_PKG_DIR / "models.yaml"),
        help="Path to models registry yaml",
    )
    ap.add_argument(
        "--models",
        default="",
        help="Comma-separated model keys from yaml to include (default: all)",
    )
    ap.add_argument(
        "--add",
        action="append",
        default=[],
        help="Ad-hoc model key|id|json_extra (repeatable). Added on top of yaml selection.",
    )
    ap.add_argument(
        "--categories",
        default="",
        help="Comma filter: speed,ability,formatting",
    )
    ap.add_argument(
        "--prompts",
        default="",
        help="Comma filter of prompt keys",
    )
    ap.add_argument(
        "--out-dir",
        default=str(_PKG_DIR / "results"),
        help="Directory for results json + report md",
    )
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument(
        "--serial-models",
        action="store_true",
        help="Call models sequentially instead of parallel per prompt",
    )
    ap.add_argument(
        "--api-key",
        default="",
        help="Override OPENROUTER_API_KEY (else env / launch.json)",
    )
    ap.add_argument(
        "--tag",
        default="",
        help="Optional tag suffix for output filenames",
    )
    ap.add_argument(
        "--list-prompts",
        action="store_true",
        help="List hard-bench prompts and exit",
    )
    args = ap.parse_args(argv)

    if args.list_prompts:
        for p in all_prompts():
            n = len(p.get("checks") or {})
            print(f"{p['key']:24}  {p['category']:11}  checks={n}  max_tokens={p['max_tokens']}")
        return 0

    models: List[Dict[str, Any]] = []
    yaml_path = Path(args.models_yaml)
    if yaml_path.is_file():
        models.extend(_load_yaml_models(yaml_path))
    if args.models.strip():
        want = {x.strip() for x in args.models.split(",") if x.strip()}
        models = [m for m in models if m["key"] in want]
    for spec in args.add:
        models.append(_parse_add(spec))
    # dedupe by key (later wins)
    dedup: Dict[str, Dict[str, Any]] = {}
    for m in models:
        dedup[m["key"]] = m
    models = list(dedup.values())
    if not models:
        print("No models selected. Use models.yaml and/or --add.", file=sys.stderr)
        return 2

    api_key = load_api_key(args.api_key or None)
    cats = [c.strip() for c in args.categories.split(",") if c.strip()] or None
    only = [p.strip() for p in args.prompts.split(",") if p.strip()] or None

    print(f"Models ({len(models)}): " + ", ".join(f"{m['key']}={m['id']}" for m in models))
    t0 = time.perf_counter()
    results = run_bench(
        models,
        api_key=api_key,
        categories=cats,
        only_prompts=only,
        timeout=args.timeout,
        parallel_models=not args.serial_models,
    )
    elapsed = time.perf_counter() - t0
    summary = summarize(results, models)
    report = format_report(summary, models, title="OpenRouter hard bench")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tag = f"_{args.tag}" if args.tag else ""
    base = f"hardbench_{stamp}{tag}"
    (out_dir / f"{base}_results.json").write_text(
        json.dumps(
            {
                "models": models,
                "elapsed_s": round(elapsed, 2),
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / f"{base}_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (out_dir / f"{base}_report.md").write_text(report, encoding="utf-8")
    # also refresh latest pointers
    (out_dir / "latest_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (out_dir / "latest_report.md").write_text(report, encoding="utf-8")

    print("\n\n" + report)
    print(f"\nElapsed wall: {elapsed:.1f}s")
    print(f"Wrote {out_dir / (base + '_results.json')}")
    print(f"Wrote {out_dir / (base + '_summary.json')}")
    print(f"Wrote {out_dir / (base + '_report.md')}")
    print(f"Latest: {out_dir / 'latest_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
