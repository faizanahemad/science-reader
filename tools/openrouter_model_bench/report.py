"""Summarize bench results into tables (markdown + plain text)."""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence


def _mean(xs: Sequence[float]) -> Optional[float]:
    return round(statistics.mean(xs), 3) if xs else None


def _median(xs: Sequence[float]) -> Optional[float]:
    return round(statistics.median(xs), 3) if xs else None


def _stats(xs: Sequence[float]) -> Optional[Dict[str, Any]]:
    if not xs:
        return None
    xs = list(xs)
    return {
        "n": len(xs),
        "mean": _mean(xs),
        "median": _median(xs),
        "min": round(min(xs), 3),
        "max": round(max(xs), 3),
    }


def summarize(results: List[Dict[str, Any]], models: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build per-model summary aligned with earlier comparison tables."""
    by_model: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in results:
        by_model[r["model_key"]].append(r)

    model_meta = {m["key"]: m for m in models}
    summary: Dict[str, Any] = {}

    for mk, rows in by_model.items():
        speed_ping = [
            r
            for r in rows
            if r.get("prompt") == "S1_ping" and not r.get("error") and r.get("ok", True)
        ]
        # quality rows: best attempt per non-speed prompt, else attempt 1
        best: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            if r.get("category") == "speed" and r.get("prompt") == "S1_ping":
                continue
            # for speed non-ping include once (attempt 1 preference if equal)
            key = r["prompt"]
            prev = best.get(key)
            if prev is None:
                best[key] = r
            else:
                # prefer higher check_score; tie -> lower attempt / non-empty
                ps, rs = prev.get("check_score") or 0, r.get("check_score") or 0
                if rs > ps:
                    best[key] = r
                elif rs == ps and (prev.get("has_empty_content") and not r.get("has_empty_content")):
                    best[key] = r
        quality_rows = list(best.values())

        all_ok = [r for r in rows if not r.get("error")]
        lats_all = [r["latency_s"] for r in all_ok if r.get("latency_s") is not None]
        lats_ping = [r["latency_s"] for r in speed_ping]
        tps_tot = [r["tokens_per_sec_total"] for r in all_ok if r.get("tokens_per_sec_total")]
        tps_vis = [r["tokens_per_sec_content"] for r in all_ok if r.get("tokens_per_sec_content")]

        cat = defaultdict(lambda: [0, 0])
        for r in quality_rows:
            cat[r["category"]][0] += r.get("check_score") or 0
            cat[r["category"]][1] += r.get("check_total") or 0
        # include speed S2 (and any non-ping speed) in cat via quality_rows already

        score = sum(r.get("check_score") or 0 for r in quality_rows)
        total = sum(r.get("check_total") or 0 for r in quality_rows)
        # also score ping attempts average into speed cat for transparency
        if speed_ping:
            # take best ping attempt
            best_ping = max(speed_ping, key=lambda r: r.get("check_score") or 0)
            cat["speed"][0] += best_ping.get("check_score") or 0
            cat["speed"][1] += best_ping.get("check_total") or 0
            score += best_ping.get("check_score") or 0
            total += best_ping.get("check_total") or 0

        empty_q = sum(1 for r in quality_rows if r.get("has_empty_content"))
        cost = sum((r.get("cost") or 0) for r in rows)

        summary[mk] = {
            "model_id": (model_meta.get(mk) or {}).get("id") or (rows[0].get("model_id") if rows else None),
            "config": (model_meta.get(mk) or {}).get("extra") or {},
            "notes": (model_meta.get(mk) or {}).get("notes"),
            "errors": sum(1 for r in rows if r.get("error")),
            "empty_content_quality": empty_q,
            "ping_latency_s": _stats(lats_ping),
            "all_task_latency_s": _stats(lats_all),
            "avg_tps_total": round(statistics.mean(tps_tot), 2) if tps_tot else None,
            "avg_tps_visible_content": round(statistics.mean(tps_vis), 2) if tps_vis else None,
            "quality_score": f"{score}/{total}",
            "quality_pct": round(100 * score / total, 1) if total else None,
            "by_category": {c: f"{a}/{b}" for c, (a, b) in sorted(cat.items())},
            "total_cost_usd_est": round(cost, 6),
            "total_completion_tokens": sum((r.get("completion_tokens") or 0) for r in rows),
            "total_reasoning_tokens": sum((r.get("reasoning_tokens") or 0) for r in rows),
            "total_prompt_tokens": sum((r.get("prompt_tokens") or 0) for r in rows),
            "per_prompt": {
                r["prompt"]: {
                    "latency_s": r.get("latency_s"),
                    "checks": f"{r.get('check_score')}/{r.get('check_total')}",
                    "detail": r.get("checks"),
                    "comp_tok": r.get("completion_tokens"),
                    "reason_tok": r.get("reasoning_tokens"),
                    "empty": r.get("has_empty_content"),
                    "finish": r.get("finish_reason"),
                    "cost": r.get("cost"),
                }
                for r in sorted(quality_rows, key=lambda x: x["prompt"])
            },
            "ping_attempts": [
                {
                    "attempt": r.get("attempt"),
                    "latency_s": r.get("latency_s"),
                    "comp": r.get("completion_tokens"),
                    "reason": r.get("reasoning_tokens"),
                    "checks": f"{r.get('check_score')}/{r.get('check_total')}",
                    "empty": r.get("has_empty_content"),
                }
                for r in sorted(speed_ping, key=lambda x: x.get("attempt") or 0)
            ],
        }
    return summary


def _md_table(headers: List[str], rows: List[List[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def format_report(
    summary: Dict[str, Any],
    models: List[Dict[str, Any]],
    *,
    title: str = "OpenRouter hard bench",
) -> str:
    """Human report matching the style used in prior comparisons."""
    keys = [m["key"] for m in models if m["key"] in summary]
    # also include any extra keys in summary order
    for k in summary:
        if k not in keys:
            keys.append(k)

    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("## Models")
    lines.append("")
    mrows = []
    for k in keys:
        s = summary[k]
        mrows.append(
            [
                k,
                f"`{s.get('model_id')}`",
                s.get("notes") or "",
            ]
        )
    lines.append(_md_table(["Label", "OpenRouter ID", "Notes"], mrows))
    lines.append("")

    lines.append("## Scoreboard")
    lines.append("")
    headers = [""] + keys
    def row(label, fn):
        return [label] + [str(fn(summary[k])) for k in keys]

    srows = [
        row("Ping mean (s)", lambda s: (s.get("ping_latency_s") or {}).get("mean")),
        row("All-task mean (s)", lambda s: (s.get("all_task_latency_s") or {}).get("mean")),
        row("Ability", lambda s: (s.get("by_category") or {}).get("ability", "—")),
        row("Formatting", lambda s: (s.get("by_category") or {}).get("formatting", "—")),
        row("Speed checks", lambda s: (s.get("by_category") or {}).get("speed", "—")),
        row("Quality total", lambda s: f"{s.get('quality_score')} ({s.get('quality_pct')}%)"),
        row("Empty quality fails", lambda s: s.get("empty_content_quality")),
        row("Suite cost $", lambda s: s.get("total_cost_usd_est")),
        row("Reasoning tokens", lambda s: s.get("total_reasoning_tokens")),
        row("Avg tok/s total", lambda s: s.get("avg_tps_total")),
        row("Avg tok/s visible", lambda s: s.get("avg_tps_visible_content")),
        row("Errors", lambda s: s.get("errors")),
    ]
    lines.append(_md_table(headers, srows))
    lines.append("")

    # winners (simple heuristics)
    lines.append("## Winners (auto)")
    lines.append("")
    winners = _winners(summary, keys)
    for axis, val in winners.items():
        lines.append(f"- **{axis}**: {val}")
    lines.append("")

    lines.append("## Per-prompt detail")
    lines.append("")
    # collect union of prompts
    prompts = []
    for k in keys:
        for p in summary[k].get("per_prompt", {}):
            if p not in prompts:
                prompts.append(p)
    prompts = sorted(prompts)
    for p in prompts:
        lines.append(f"### {p}")
        lines.append("")
        prows = []
        for k in keys:
            cell = (summary[k].get("per_prompt") or {}).get(p) or {}
            prows.append(
                [
                    k,
                    str(cell.get("latency_s")),
                    str(cell.get("checks")),
                    str(cell.get("comp_tok")),
                    str(cell.get("reason_tok")),
                    str(cell.get("empty")),
                    str(cell.get("finish")),
                ]
            )
        lines.append(
            _md_table(
                ["model", "latency_s", "checks", "comp_tok", "reason_tok", "empty", "finish"],
                prows,
            )
        )
        # failed check names
        fail_notes = []
        for k in keys:
            cell = (summary[k].get("per_prompt") or {}).get(p) or {}
            detail = cell.get("detail") or {}
            fails = [n for n, v in detail.items() if not v]
            if fails:
                fail_notes.append(f"- {k}: failed {', '.join(fails)}")
        if fail_notes:
            lines.append("")
            lines.append("Failed checks:")
            lines.extend(fail_notes)
        lines.append("")

    lines.append("## Practical picks")
    lines.append("")
    lines.append(_practical_picks(summary, keys))
    lines.append("")
    return "\n".join(lines)


def _winners(summary: Dict[str, Any], keys: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}

    def best(label, pairs, higher=True):
        pairs = [(k, v) for k, v in pairs if v is not None]
        if not pairs:
            out[label] = "n/a"
            return
        pairs.sort(key=lambda x: x[1], reverse=higher)
        top = pairs[0][1]
        winners = [k for k, v in pairs if v == top]
        out[label] = ", ".join(winners) + f" ({top})"

    best(
        "Speed (ping mean, lower)",
        [(k, (summary[k].get("ping_latency_s") or {}).get("mean")) for k in keys],
        higher=False,
    )
    best(
        "Speed (all-task mean, lower)",
        [(k, (summary[k].get("all_task_latency_s") or {}).get("mean")) for k in keys],
        higher=False,
    )
    best(
        "Quality %",
        [(k, summary[k].get("quality_pct")) for k in keys],
        higher=True,
    )
    best(
        "Cheapest suite $",
        [(k, summary[k].get("total_cost_usd_est")) for k in keys],
        higher=False,
    )
    return out


def _practical_picks(summary: Dict[str, Any], keys: List[str]) -> str:
    if not keys:
        return "No models."
    # quality leaders
    ranked = sorted(
        keys,
        key=lambda k: (
            summary[k].get("quality_pct") or 0,
            -((summary[k].get("all_task_latency_s") or {}).get("mean") or 99),
            -(summary[k].get("total_cost_usd_est") or 99),
        ),
        reverse=True,
    )
    fastest = min(
        keys,
        key=lambda k: (summary[k].get("all_task_latency_s") or {}).get("mean") or 999,
    )
    cheapest = min(keys, key=lambda k: summary[k].get("total_cost_usd_est") or 999)
    reliable = [
        k
        for k in keys
        if (summary[k].get("empty_content_quality") or 0) == 0
        and (summary[k].get("errors") or 0) == 0
    ]
    lines = [
        f"1. Best overall quality (then speed/cost): **{ranked[0]}**",
        f"2. Fastest wall time: **{fastest}**",
        f"3. Cheapest on this suite: **{cheapest}**",
        f"4. Zero empty/error models: {', '.join(f'**{k}**' for k in reliable) if reliable else 'none'}",
    ]
    return "\n".join(lines)
