"""Hard-bench prompt pack: speed / ability / formatting.

Each prompt:
  key, category in {speed, ability, formatting}, system, user,
  max_tokens, temp, optional speed_repeats, checks dict of name->fn(text)->bool
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .scoring import (
    compiles_python,
    count_lines_matching,
    csv_rows,
    first_nonempty_line,
    has_fence,
    parse_json_loose,
    run_python_fn,
    word_count,
    yaml_like_frontmatter,
)


HARD_PROMPTS: List[Dict[str, Any]] = []


def _reg(p: Dict[str, Any]) -> Dict[str, Any]:
    HARD_PROMPTS.append(p)
    return p


# ---------------------------------------------------------------------------
# SPEED
# ---------------------------------------------------------------------------
_reg(
    {
        "key": "S1_ping",
        "category": "speed",
        "system": "Be maximally concise.",
        "user": "Reply with exactly: OK",
        "max_tokens": 128,
        "temp": 0,
        "speed_repeats": 3,
        "checks": {
            "exact_ok": lambda t: t.strip() == "OK",
            "starts_ok": lambda t: t.strip().startswith("OK"),
        },
    }
)

_reg(
    {
        "key": "S2_medium_list",
        "category": "speed",
        "system": "Follow the format exactly. No commentary.",
        "user": (
            "List integers from 1 to 20 inclusive, one per line, zero-padded to 2 digits "
            "(01, 02, ... 20). Nothing else."
        ),
        "max_tokens": 256,
        "temp": 0,
        "speed_repeats": 1,
        "checks": {
            "twenty_lines": lambda t: len([ln for ln in t.strip().splitlines() if ln.strip()]) == 20,
            "padded": lambda t: all(
                re.fullmatch(r"\d{2}", ln.strip()) for ln in t.strip().splitlines() if ln.strip()
            ),
            "ends_20": lambda t: any(ln.strip() == "20" for ln in t.strip().splitlines()),
            "starts_01": lambda t: first_nonempty_line(t) == "01",
        },
    }
)

# ---------------------------------------------------------------------------
# ABILITY — harder
# ---------------------------------------------------------------------------
_reg(
    {
        "key": "A1_trap_math",
        "category": "ability",
        "system": "Solve carefully. Put the final integer on its own line as ANSWER: <n>.",
        "user": (
            "A train leaves City A at 09:00 traveling east at 60 km/h. Another leaves City B "
            "(240 km east of A) at 10:00 traveling west at 80 km/h. At what clock time (HH:MM, "
            "24h) do they meet? Ignore timezone; same day. "
            "Also report minutes after 09:00 as integer M. Final line: ANSWER: M"
        ),
        "max_tokens": 1200,
        "temp": 0,
        # eastbound 1h headstart = 60km, remaining 180km at closing 140km/h => 180/140 h = 9/7 h ≈ 1h17.14m
        # meet at 10:00 + 77.14m ≈ 11:17; M from 09:00 = 60+77 = 137 minutes (approx). Exact: 60 + 180/140*60 = 60 + 540/7 = 60 + 77 + 1/7 ≈ 137.14 → floor/round ambiguity.
        # Prefer exact fractional: 180/140 hours after 10:00 = 9/7 h = 1 h + (2/7)*60 min = 1h + 120/7 min = 1h + 17 + 1/7 min.
        # For integer M after 09:00: 60 + 540/7 = (420+540)/7 = 960/7 ≈ 137.142 → if forced integer nearest is 137.
        "checks": {
            "answer_137": lambda t: bool(re.search(r"ANSWER:\s*137\b", t)),
            "mentions_11_17": lambda t: bool(re.search(r"11:17", t)),
        },
    }
)

_reg(
    {
        "key": "A2_code_fix_exec",
        "category": "ability",
        "system": (
            "You are a careful Python engineer. Output ONLY bare Python source for the "
            "requested function(s). No markdown fences, no prose."
        ),
        "user": (
            "Write `def merge_intervals(intervals):` that merges overlapping [start,end] "
            "closed integer intervals. intervals is List[List[int]]. Return merged sorted "
            "list of lists. Handle empty input. Also write `def interval_coverage(intervals):` "
            "that returns total covered length after merge. No other top-level names required."
        ),
        "max_tokens": 900,
        "temp": 0,
        "checks": {
            "no_fence": lambda t: not has_fence(t),
            "has_merge": lambda t: "def merge_intervals" in t,
            "has_coverage": lambda t: "def interval_coverage" in t,
            "compiles": lambda t: compiles_python(t),
            "merge_correct": lambda t: _merge_ok(t),
            "coverage_correct": lambda t: _coverage_ok(t),
        },
    }
)

_reg(
    {
        "key": "A3_sql_window",
        "category": "ability",
        "system": "Output only a single SQL query. No fences, no comments, no explanation.",
        "user": (
            "Tables:\n"
            "orders(order_id INT, customer_id INT, order_date DATE, amount DECIMAL)\n"
            "Write SQL (ANSI) that returns for each customer_id:\n"
            "  customer_id,\n"
            "  order_id of their highest-amount order (tie: latest order_date, then highest order_id),\n"
            "  amount of that order,\n"
            "  running_total of amount ordered by order_date, order_id over that customer,\n"
            "  but ONLY for customers with at least 3 orders.\n"
            "Use window functions. Final result rows = only the single top order row per qualifying customer."
        ),
        "max_tokens": 700,
        "temp": 0,
        "checks": {
            "no_fence": lambda t: not has_fence(t),
            "has_window": lambda t: bool(re.search(r"\bover\s*\(", t, re.I)),
            "has_partition": lambda t: bool(re.search(r"partition\s+by", t, re.I)),
            "mentions_customer": lambda t: "customer_id" in t.lower(),
            "filters_3plus": lambda t: bool(
                re.search(r"count\s*\(|>=\s*3|count\s*\(\*\)", t, re.I)
            ),
            "rank_or_row_number": lambda t: bool(
                re.search(r"row_number\s*\(|rank\s*\(|dense_rank\s*\(", t, re.I)
            ),
        },
    }
)

_reg(
    {
        "key": "A4_bugfix_and_patch",
        "category": "ability",
        "system": (
            "Return ONLY a corrected full function as bare Python. No fences, no prose, "
            "no explanations of the bug."
        ),
        "user": (
            "This function is supposed to return True iff `s` is a permutation of `t` "
            "ignoring spaces and case. Fix all bugs.\n\n"
            "def is_perm(s, t):\n"
            "    s = s.replace(' ', '')\n"
            "    t = t.replace(' ', '')\n"
            "    if len(s) != len(t):\n"
            "        return False\n"
            "    return sorted(s) == sorted(t)\n"
        ),
        "max_tokens": 500,
        "temp": 0,
        "checks": {
            "no_fence": lambda t: not has_fence(t),
            "has_def": lambda t: "def is_perm" in t,
            "compiles": lambda t: compiles_python(t),
            "case_insensitive": lambda t: _is_perm_case_ok(t),
            "space_ok": lambda t: _is_perm_space_ok(t),
            "rejects_nonperm": lambda t: _is_perm_reject_ok(t),
        },
    }
)

_reg(
    {
        "key": "A5_nested_instructions",
        "category": "ability",
        "system": "Obey every constraint. Any violation is failure.",
        "user": (
            "Transform the word list L = [alpha, beta, gamma, delta] as follows:\n"
            "1) Uppercase each word\n"
            "2) Drop any word containing the letter 'A' (after uppercasing)\n"
            "3) Reverse the remaining sequence\n"
            "4) Join with '|' \n"
            "5) Prefix with 'OUT:' and suffix with ':END'\n"
            "6) Do not use the words list, array, result, or output anywhere in your reply\n"
            "7) Your entire reply must be a single line\n"
            "Compute using the rules; do not restate the rules."
        ),
        "max_tokens": 400,
        "temp": 0,
        # After upper: ALPHA BETA GAMMA DELTA — every word contains 'A', so all are dropped.
        # Remaining: empty sequence → join → "" → OUT::END
        "checks": {
            "exact": lambda t: t.strip() == "OUT::END",
            "single_line": lambda t: t.strip().count("\n") == 0,
            "no_banned": lambda t: not bool(
                re.search(r"\b(list|array|result|output)\b", t, re.I)
            ),
        },
    }
)

_reg(
    {
        "key": "A6_reading_trap",
        "category": "ability",
        "system": "Answer from the passage only. If unknown, say UNKNOWN.",
        "user": (
            "Passage:\n"
            "In 2017, Riverbend opened a solar plant with nameplate capacity 48 MW. "
            "In 2019 it added a 12 MW battery (2-hour). In 2021 the solar capacity was "
            "repowered to 55 MW but the battery was not expanded. A consultant report "
            "erroneously listed 2017 capacity as 84 MW. The city council minutes from "
            "2022 claim the plant 'nearly doubled' since opening; that claim is disputed.\n\n"
            "Q: What was the solar nameplate capacity immediately AFTER the 2021 repower, in MW? "
            "Reply with ONLY the integer."
        ),
        "max_tokens": 64,
        "temp": 0,
        "checks": {
            "exact_55": lambda t: t.strip() == "55",
            "not_84": lambda t: "84" not in t.strip(),
            "not_48": lambda t: t.strip() != "48",
        },
    }
)

# ---------------------------------------------------------------------------
# FORMATTING — harder multi-constraint
# ---------------------------------------------------------------------------
_reg(
    {
        "key": "F1_nested_json_schema",
        "category": "formatting",
        "system": "Return ONLY valid JSON. No markdown, no commentary.",
        "user": (
            "Extract to this exact schema (types matter):\n"
            "{\n"
            '  "event": str,\n'
            '  "participants": [{"name": str, "role": str}],\n'
            '  "metrics": {"latency_ms": int, "success": bool},\n'
            '  "tags": [str],\n'
            '  "version": int\n'
            "}\n"
            "Source: 'Deploy bot v3 canary: Alice (owner) and Bob (sre) saw p95 latency 240ms; "
            "run succeeded. tags=canary,prod-eu. version 3.'\n"
            "participants ordered Alice then Bob. tags alphabetical. version integer 3. success true."
        ),
        "max_tokens": 500,
        "temp": 0,
        "checks": {
            "valid_json": lambda t: parse_json_loose(t)[0],
            "no_fence": lambda t: not has_fence(t),
            "schema_ok": lambda t: _nested_json_ok(t),
            "tags_alpha": lambda t: _tags_alpha(t),
            "participants_order": lambda t: _participants_order(t),
        },
    }
)

_reg(
    {
        "key": "F2_csv_only",
        "category": "formatting",
        "system": "Output ONLY CSV. No markdown table. No prose. No fences.",
        "user": (
            "Header exactly: sku,units,unit_price,region\n"
            "Rows:\n"
            "1) SKU-9, 12 units, $3.50, US\n"
            "2) SKU-2, 4 units, $10, EU\n"
            "3) SKU-5, 0 units, $2.25, US\n"
            "Sort rows by sku ascending. unit_price as decimal with 2 places. No currency symbols."
        ),
        "max_tokens": 300,
        "temp": 0,
        "checks": {
            "no_fence": lambda t: not has_fence(t),
            "no_pipe_table": lambda t: "|" not in t,
            "header": lambda t: (csv_rows(t)[0] if csv_rows(t) else [])
            == ["sku", "units", "unit_price", "region"],
            "three_data_rows": lambda t: len(csv_rows(t)) == 4,
            "sorted_sku": lambda t: _csv_sorted(t),
            "price_format": lambda t: _csv_prices(t),
        },
    }
)

_reg(
    {
        "key": "F3_md_strict_report",
        "category": "formatting",
        "system": "Emit clean Markdown that satisfies every structural constraint.",
        "user": (
            "Topic: blue/green deploy vs rolling deploy for a 50-service mesh.\n"
            "Constraints:\n"
            "- First line must be an H1 (# ...)\n"
            "- Then exactly one horizontal rule line (---) on its own\n"
            "- Then exactly 2 H2 sections: ## Tradeoffs , ## Decision\n"
            "- Under Tradeoffs: a markdown table with columns Factor | Blue/Green | Rolling | Prefer\n"
            "  and exactly 4 data rows\n"
            "- Under Decision: exactly 3 numbered items (1. 2. 3.)\n"
            "- Final line exactly: EOF\n"
            "- Total words outside the table between 80 and 160 inclusive\n"
            "No code fences anywhere."
        ),
        "max_tokens": 1800,
        "temp": 0.2,
        "checks": {
            "h1_first": lambda t: bool(re.match(r"^#\s+\S", (t or "").lstrip())),
            "has_rule": lambda t: bool(re.search(r"(?m)^---\s*$", t or "")),
            "two_h2": lambda t: count_lines_matching(t, r"^##\s+") == 2,
            "h2_names": lambda t: bool(re.search(r"(?m)^##\s+Tradeoffs\s*$", t or ""))
            and bool(re.search(r"(?m)^##\s+Decision\s*$", t or "")),
            "table_header": lambda t: bool(
                re.search(
                    r"Factor\s*\|\s*Blue/Green\s*\|\s*Rolling\s*\|\s*Prefer", t or ""
                )
            ),
            "four_data_rows": lambda t: _table_data_rows(t) == 4,
            "three_numbered": lambda t: count_lines_matching(t, r"^\s*1\.\s+") == 1
            and count_lines_matching(t, r"^\s*2\.\s+") == 1
            and count_lines_matching(t, r"^\s*3\.\s+") == 1,
            "ends_eof": lambda t: (t or "").rstrip().endswith("EOF"),
            "no_fence": lambda t: not has_fence(t),
            "word_band": lambda t: _outside_table_words(t, 80, 160),
        },
    }
)

_reg(
    {
        "key": "F4_frontmatter_yaml",
        "category": "formatting",
        "system": "Follow the template exactly.",
        "user": (
            "Produce a document with YAML front matter then body:\n"
            "---\n"
            "title: <string>\n"
            "priority: <one of high|medium|low>\n"
            "owners: [<email>, <email>]\n"
            "estimate_days: <int>\n"
            "---\n"
            "Then a body that is EXACTLY two paragraphs separated by one blank line, "
            "each paragraph 25-40 words, about triaging flaky CI.\n"
            "title must be Flaky CI triage. priority high. owners alice@ex.com and bob@ex.com. "
            "estimate_days 3. No markdown headings in body. No fences."
        ),
        "max_tokens": 700,
        "temp": 0.2,
        "checks": {
            "frontmatter": lambda t: yaml_like_frontmatter(t)[0],
            "title": lambda t: _fm_has(t, r"(?m)^title:\s*Flaky CI triage\s*$"),
            "priority": lambda t: _fm_has(t, r"(?m)^priority:\s*high\s*$"),
            "estimate": lambda t: _fm_has(t, r"(?m)^estimate_days:\s*3\s*$"),
            "owners": lambda t: _fm_owners(t),
            "two_paragraphs": lambda t: _two_paragraphs(t),
            "no_fence": lambda t: not has_fence(t),
            "no_md_heading_body": lambda t: not bool(
                re.search(r"(?m)^#", yaml_like_frontmatter(t)[2] or "")
            ),
        },
    }
)

_reg(
    {
        "key": "F5_multi_block_labels",
        "category": "formatting",
        "system": "Obey label structure with zero extra text.",
        "user": (
            "Topic: choose between Redis and Memcached for session store at 50k QPS.\n"
            "Emit EXACTLY these blocks in order, each starting at column 0:\n"
            "CHOICE: <one word Redis or Memcached>\n"
            "BECAUSE: <exactly one sentence, 12-25 words>\n"
            "RISKS:\n"
            "- <risk1 <= 12 words>\n"
            "- <risk2 <= 12 words>\n"
            "METRICS: p50_ms=<int>;p99_ms=<int>;hit_ratio=<float 0-1 with 2 decimals>\n"
            "No other lines. No blank lines. No markdown headings."
        ),
        "max_tokens": 900,
        "temp": 0,
        "checks": {
            "choice": lambda t: bool(re.match(r"^CHOICE:\s*(Redis|Memcached)\s*$", t or "", re.M)),
            "because": lambda t: _because_band(t, 12, 25),
            "two_risks": lambda t: count_lines_matching(t, r"^- .+") == 2,
            "metrics": lambda t: bool(
                re.search(
                    r"(?m)^METRICS: p50_ms=\d+;p99_ms=\d+;hit_ratio=(0\.\d{2}|1\.00)\s*$",
                    t or "",
                )
            ),
            "line_count_le_6": lambda t: len([ln for ln in (t or "").splitlines() if ln.strip()])
            <= 6,
            "no_blank": lambda t: all(ln.strip() for ln in (t or "").splitlines()),
            "starts_choice": lambda t: first_nonempty_line(t).startswith("CHOICE:"),
        },
    }
)


# -------------------- check helpers --------------------

def _merge_ok(text: str) -> bool:
    ok, res = run_python_fn(
        text,
        "merge_intervals",
        [[1, 3], [2, 6], [8, 10], [15, 18]],
    )
    return ok and res == [[1, 6], [8, 10], [15, 18]]


def _coverage_ok(text: str) -> bool:
    ok, res = run_python_fn(
        text,
        "interval_coverage",
        [[1, 3], [2, 6], [8, 10], [15, 18]],
    )
    # lengths: 5 + 2 + 3 = 10 if closed? wait closed [1,6] length 5? 
    # ambiguous open/closed. Prefer end-start for half-open OR end-start+1 for closed.
    # Common leetcode merge uses end-start for coverage on [start,end) OR for closed ends many use end-start.
    # Leetcode 56 intervals are closed but coverage problems often sum (e-s).
    # Accept 10 (half-open / end-start) or 13 (closed end-start+1): [1,6]=5or6, [8,10]=2or3, [15,18]=3or4 => 10 or 13.
    return ok and res in (10, 13)


def _is_perm_case_ok(text: str) -> bool:
    ok, res = run_python_fn(text, "is_perm", "Listen", "Silent")
    return ok and res is True


def _is_perm_space_ok(text: str) -> bool:
    ok, res = run_python_fn(text, "is_perm", "a b c", "cba")
    return ok and res is True


def _is_perm_reject_ok(text: str) -> bool:
    ok, res = run_python_fn(text, "is_perm", "abc", "abd")
    return ok and res is False


def _nested_json_ok(text: str) -> bool:
    ok, obj = parse_json_loose(text)
    if not ok or not isinstance(obj, dict):
        return False
    try:
        assert isinstance(obj.get("event"), str) and obj["event"]
        parts = obj.get("participants")
        assert isinstance(parts, list) and len(parts) == 2
        for p in parts:
            assert set(p.keys()) >= {"name", "role"}
            assert isinstance(p["name"], str) and isinstance(p["role"], str)
        metrics = obj.get("metrics")
        assert isinstance(metrics, dict)
        assert isinstance(metrics.get("latency_ms"), int)
        assert metrics.get("latency_ms") == 240
        assert metrics.get("success") is True
        tags = obj.get("tags")
        assert isinstance(tags, list) and all(isinstance(x, str) for x in tags)
        assert obj.get("version") == 3
        return True
    except Exception:
        return False


def _tags_alpha(text: str) -> bool:
    ok, obj = parse_json_loose(text)
    if not ok or not isinstance(obj, dict):
        return False
    tags = obj.get("tags") or []
    return list(tags) == sorted(tags)


def _participants_order(text: str) -> bool:
    ok, obj = parse_json_loose(text)
    if not ok or not isinstance(obj, dict):
        return False
    parts = obj.get("participants") or []
    if len(parts) < 2:
        return False
    names = [p.get("name", "").lower() for p in parts]
    return names[0].startswith("alice") and names[1].startswith("bob")


def _csv_sorted(text: str) -> bool:
    rows = csv_rows(text)
    if len(rows) < 2:
        return False
    skus = [r[0] for r in rows[1:]]
    return skus == sorted(skus) and skus == ["SKU-2", "SKU-5", "SKU-9"]


def _csv_prices(text: str) -> bool:
    rows = csv_rows(text)
    if len(rows) < 2:
        return False
    for r in rows[1:]:
        if len(r) < 3:
            return False
        if not re.fullmatch(r"\d+\.\d{2}", r[2]):
            return False
    return True


def _table_data_rows(text: str) -> int:
    """Count markdown table data rows (exclude header + separator)."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip().startswith("|")]
    if len(lines) < 3:
        return 0
    # drop header + alignment
    data = []
    for ln in lines[2:]:
        if re.match(r"^\s*\|?\s*:?-{3,}", ln.replace("|", " ").strip() or ""):
            continue
        # alignment row like |---|---|
        if re.match(r"^\s*\|?\s*[-:| ]+\|?\s*$", ln) and re.search(r"-{3,}", ln):
            continue
        data.append(ln)
    # if first after header is separator, lines[1] is sep, already skipped via [2:]
    return len(data)


def _outside_table_words(text: str, lo: int, hi: int) -> bool:
    lines = []
    in_table = False
    for ln in (text or "").splitlines():
        if ln.strip().startswith("|"):
            in_table = True
            continue
        if in_table and not ln.strip().startswith("|"):
            in_table = False
        if not in_table:
            lines.append(ln)
    body = "\n".join(lines)
    # exclude EOF token from count? still a word - keep simple
    n = word_count(body)
    return lo <= n <= hi


def _fm_has(text: str, pat: str) -> bool:
    ok, front, _ = yaml_like_frontmatter(text)
    return ok and bool(re.search(pat, front))


def _fm_owners(text: str) -> bool:
    ok, front, _ = yaml_like_frontmatter(text)
    if not ok:
        return False
    return "alice@ex.com" in front and "bob@ex.com" in front


def _two_paragraphs(text: str) -> bool:
    ok, _, body = yaml_like_frontmatter(text)
    if not ok:
        return False
    parts = re.split(r"\n\s*\n", body.strip())
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) != 2:
        return False
    return all(25 <= word_count(p) <= 40 for p in parts)


def _because_band(text: str, lo: int, hi: int) -> bool:
    m = re.search(r"(?m)^BECAUSE:\s*(.+)$", text or "")
    if not m:
        return False
    n = word_count(m.group(1))
    return lo <= n <= hi


def all_prompts() -> List[Dict[str, Any]]:
    return list(HARD_PROMPTS)


def prompts_by_category() -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for p in HARD_PROMPTS:
        out.setdefault(p["category"], []).append(p["key"])
    return out
