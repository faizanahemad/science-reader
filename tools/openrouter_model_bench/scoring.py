"""Deterministic scorers for hard-bench prompts."""

from __future__ import annotations

import ast
import json
import re
from typing import Any, Callable, Dict, Optional, Tuple


CheckFn = Callable[[str], bool]
Checks = Dict[str, CheckFn]


def strip_fences(text: str, lang: Optional[str] = None) -> str:
    s = (text or "").strip()
    if not s.startswith("```"):
        return s
    pat = r"^```(?:%s)?\s*(.*?)\s*```$" % (lang or r"[\w+-]*")
    m = re.search(pat, s, re.S | re.I)
    return m.group(1).strip() if m else s


def parse_json_loose(text: str) -> Tuple[bool, Any]:
    s = strip_fences(text or "", "json").strip()
    try:
        return True, json.loads(s)
    except Exception:
        pass
    # first object / array
    for pat in (r"\{.*\}", r"\[.*\]"):
        m = re.search(pat, s, re.S)
        if not m:
            continue
        try:
            return True, json.loads(m.group(0))
        except Exception:
            continue
    return False, None


def compiles_python(text: str) -> bool:
    code = strip_fences(text or "", "python")
    # drop leading prose lines until a def/class/import
    lines = code.splitlines()
    start = 0
    for i, ln in enumerate(lines):
        if re.match(r"\s*(def |class |import |from )", ln):
            start = i
            break
    code = "\n".join(lines[start:])
    try:
        compile(code, "<bench>", "exec")
        return True
    except Exception:
        return False


def extract_python(text: str) -> str:
    code = strip_fences(text or "", "python")
    lines = code.splitlines()
    start = 0
    for i, ln in enumerate(lines):
        if re.match(r"\s*(def |class |import |from )", ln):
            start = i
            break
    return "\n".join(lines[start:])


def run_python_fn(text: str, fn_name: str, *args):
    """Exec extracted code and call fn_name(*args). Returns (ok, result_or_err)."""
    code = extract_python(text)
    ns: Dict[str, Any] = {}
    try:
        exec(compile(code, "<bench>", "exec"), ns, ns)
        fn = ns.get(fn_name)
        if not callable(fn):
            return False, f"missing {fn_name}"
        return True, fn(*args)
    except Exception as e:
        return False, str(e)


def count_lines_matching(text: str, pat: str) -> int:
    return len(re.findall(pat, text or "", re.M))


def has_fence(text: str) -> bool:
    return "```" in (text or "")


def first_nonempty_line(text: str) -> str:
    for ln in (text or "").splitlines():
        if ln.strip():
            return ln.strip()
    return ""


def word_count(s: str) -> int:
    return len(re.findall(r"\b[\w']+\b", s or ""))


def csv_rows(text: str) -> list:
    rows = []
    for ln in (text or "").strip().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        # ignore pure markdown table junk
        if ln.startswith("|"):
            continue
        rows.append([c.strip() for c in ln.split(",")])
    return rows


def yaml_like_frontmatter(text: str) -> Tuple[bool, str, str]:
    """Return (ok, front, body) for --- yaml --- body."""
    s = (text or "").lstrip()
    if not s.startswith("---"):
        return False, "", ""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", s, re.S)
    if not m:
        return False, "", ""
    return True, m.group(1), m.group(2)


def score_checks(text: str, checks: Checks) -> Dict[str, bool]:
    out = {}
    for name, fn in checks.items():
        try:
            out[name] = bool(fn(text))
        except Exception:
            out[name] = False
    return out
