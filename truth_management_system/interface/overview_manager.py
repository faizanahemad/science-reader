"""
PKBOverviewManager — per-user maintained markdown summary of the knowledge base.

Maintains a single markdown document per user that summarises domains, key entities,
context TOC, and recently modified claims. Updated incrementally via cheap LLM calls
on each write operation; can be fully regenerated or gap-scanned on demand.

Storage: pkb_overview table (schema v11), same SQLite file as the rest of PKB.
The stored content contains a stats-line template that is replaced with live DB
counts at read time — counts are never persisted.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# Stats line template stored in DB content. Replaced with live counts on read.
_STATS_TEMPLATE = "*Claims: {claims} · Contexts: {contexts} · Entities: {entities} · Tags: {tags} · Last updated: {date}*"
_STATS_PATTERN = re.compile(r"\*Claims: .+? · Last updated: .+?\*")

CONSOLIDATION_WORD_THRESHOLD = 8000
FIRST_TIME_CLAIM_CAP = 200  # max claims sent to LLM on first-time generation
KEY_AREAS_WORD_CAP = 200    # max words in the NL-agent Key Areas snippet


@dataclass
class OverviewStats:
    claims: int
    contexts: int
    entities: int
    tags: int
    last_updated: str


@dataclass
class OverviewResult:
    content: str          # markdown with stats injected
    stats: OverviewStats
    is_stale: bool
    last_updated: str


@dataclass
class OverviewUpdateEvent:
    trigger: str                          # "add"|"edit"|"delete"|"bulk"|"link"
    claims: List                          # list of Claim objects (may be empty for link events)
    current_content: str                  # existing raw stored markdown (may be "")
    link_metadata: Optional[dict] = None
    # For link events: {"object_type": "tag"|"entity"|"context",
    #                   "object_name": str, "claim_statement": str}


class PKBOverviewManager:
    """
    Manages the per-user PKB overview document.

    All public methods that return content inject live DB stats into the
    stats template line before returning — the stored markdown never has
    accurate counts baked in.
    """

    def __init__(self, db, keys: dict, config):
        self.db = db
        self.keys = keys
        self.config = config

    # -----------------------------------------------------------------------
    # Public read/write API
    # -----------------------------------------------------------------------

    def get_overview(self, user_email: str) -> OverviewResult:
        """
        Returns the overview for user. Triggers lazy full generation on first call.
        Always injects live stats before returning.
        """
        row = self._fetch_row(user_email)
        if row is None or not row["content"]:
            return self.generate_full(user_email)
        stats = self._get_live_stats(user_email)
        content = self._inject_stats(row["content"], stats)
        return OverviewResult(
            content=content,
            stats=stats,
            is_stale=bool(row["is_stale"]),
            last_updated=row["last_updated"] or "",
        )

    def get_raw_content(self, user_email: str) -> Optional[str]:
        """Raw stored markdown WITHOUT stats injection. Returns None if no row exists."""
        row = self._fetch_row(user_email)
        return row["content"] if row else None

    def save(self, user_email: str, content: str) -> None:
        """
        Direct save — used for manual edits and for persisting generate_full /
        scan_for_gaps output. Clears is_stale. Updates word_count and topics_json.
        Does NOT trigger an LLM call.
        """
        from ..utils import now_iso
        word_count = len(content.split())
        topics_json = json.dumps(self._extract_topics(content))
        self.db.execute(
            """
            INSERT INTO pkb_overview (user_email, content, word_count, last_updated, is_stale, topics_json)
            VALUES (?, ?, ?, ?, 0, ?)
            ON CONFLICT(user_email) DO UPDATE SET
                content=excluded.content,
                word_count=excluded.word_count,
                last_updated=excluded.last_updated,
                is_stale=0,
                topics_json=excluded.topics_json
            """,
            (user_email, content, word_count, now_iso(), topics_json),
        )

    def mark_stale(self, user_email: str) -> None:
        """Sets is_stale=1. Called when an LLM update fails."""
        self.db.execute(
            "UPDATE pkb_overview SET is_stale=1 WHERE user_email=?",
            (user_email,),
        )

    def generate_full(self, user_email: str, progress_cb=None) -> OverviewResult:
        """
        Full regeneration from scratch via one cheap LLM call.
        Claims are capped at FIRST_TIME_CLAIM_CAP only on the very first generation
        (when no overview exists yet). Subsequent regenerations are uncapped.
        Use scan_for_gaps() to patch the existing overview rather than rewrite it.
        """
        prompt = self._build_generate_prompt(user_email, progress_cb=progress_cb)
        if progress_cb:
            progress_cb("Generating overview with LLM...")
        content = self._call_llm(prompt)
        content = self._ensure_stats_template(content)
        self.save(user_email, content)
        stats = self._get_live_stats(user_email)
        if progress_cb:
            progress_cb("Done.")
        return OverviewResult(
            content=self._inject_stats(content, stats),
            stats=stats,
            is_stale=False,
            last_updated=stats.last_updated,
        )

    def scan_for_gaps(self, user_email: str, progress_cb=None) -> OverviewResult:
        """
        Gap-scan: passes full raw claim list (no cap) + current overview to LLM.
        More thorough than incremental update; user-triggered only.
        """
        current = self.get_raw_content(user_email) or ""
        if progress_cb:
            progress_cb("Building scan prompt...")
        prompt = self._build_scan_prompt(user_email, current)
        if progress_cb:
            progress_cb("Scanning for gaps with LLM...")
        content = self._call_llm(prompt)
        content = self._ensure_stats_template(content)
        self.save(user_email, content)
        stats = self._get_live_stats(user_email)
        if progress_cb:
            progress_cb("Done.")
        return OverviewResult(
            content=self._inject_stats(content, stats),
            stats=stats,
            is_stale=False,
            last_updated=stats.last_updated,
        )

    def update_from_event(self, user_email: str, event: OverviewUpdateEvent) -> OverviewResult:
        """
        Incremental update triggered by a write operation.
        LLM outputs a JSON array of edit ops; _apply_edits applies them.
        If word_count > CONSOLIDATION_WORD_THRESHOLD after update, triggers
        consolidation asynchronously.
        On any exception: marks stale, re-raises.
        """
        current = event.current_content or self.get_raw_content(user_email) or ""
        if not current:
            return self.generate_full(user_email)

        prompt = self._build_update_prompt(event, current, user_email)
        try:
            raw = self._call_llm(prompt)
            ops = self._parse_ops(raw)
            updated = self._apply_edits(current, ops)
        except Exception:
            self.mark_stale(user_email)
            raise

        self.save(user_email, updated)

        # Async consolidation if over threshold
        word_count = len(updated.split())
        if word_count > CONSOLIDATION_WORD_THRESHOLD:
            try:
                from very_common import get_async_future
                get_async_future(self._consolidate, user_email, updated)
            except Exception as e:
                logger.warning(f"[PKB Overview] consolidation dispatch failed: {e}")

        stats = self._get_live_stats(user_email)
        return OverviewResult(
            content=self._inject_stats(updated, stats),
            stats=stats,
            is_stale=False,
            last_updated=stats.last_updated,
        )

    def get_key_areas_snippet(self, user_email: str) -> Optional[str]:
        """
        Returns Key Areas + Table of Contents sections only, truncated to
        KEY_AREAS_WORD_CAP words. Used by PKBNLAgent system prompt.
        Returns None if no overview exists yet.
        """
        raw = self.get_raw_content(user_email)
        if not raw:
            return None
        sections = self._split_sections(raw)
        parts = []
        for header, body in sections:
            if header in ("## Key Areas", "## Table of Contents"):
                parts.append(f"{header}\n{body.strip()}")
        if not parts:
            return None
        snippet = "\n\n".join(parts)
        words = snippet.split()
        if len(words) > KEY_AREAS_WORD_CAP:
            snippet = " ".join(words[:KEY_AREAS_WORD_CAP]) + "..."
        return snippet

    def get_topics(self, user_email: str) -> list:
        """
        Return the structured topics list from the stored topics_json sidecar.
        Each entry: {"name": str, "claim_count": int, "description": str}.
        Returns [] if no overview or no topics parsed.
        """
        row = self._fetch_row(user_email)
        if not row or not row.get("topics_json"):
            return []
        try:
            return json.loads(row["topics_json"])
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def _extract_topics(content: str) -> list:
        """
        Parse the Key Areas section of the overview markdown into structured topics.
        Expected format: - **TopicName** (N claims): description text
        Returns list of {"name": str, "claim_count": int, "description": str}.
        """
        topics = []
        in_key_areas = False
        for line in content.split("\n"):
            if line.strip() == "## Key Areas":
                in_key_areas = True
                continue
            if in_key_areas and line.startswith("## "):
                break
            if in_key_areas and line.strip().startswith("- **"):
                m = re.match(
                    r"- \*\*(.+?)\*\*\s*\((\d+)\s*claims?\)(?:\s*:\s*(.*))?",
                    line.strip(),
                )
                if m:
                    topics.append({
                        "name": m.group(1).strip(),
                        "claim_count": int(m.group(2)),
                        "description": (m.group(3) or "").strip(),
                    })
        return topics

    # -----------------------------------------------------------------------
    # Edit-ops application (pure Python, no LLM)
    # -----------------------------------------------------------------------

    def _apply_edits(self, content: str, ops: list) -> str:
        """
        Apply a list of JSON edit operations to the markdown content.
        Splits on '\n## ' section boundaries. Preserves all untouched sections.
        Unmatched sections are skipped with a warning (never error).
        """
        if not ops:
            return content

        sections = self._split_sections(content)
        # header → index in sections list (for mutations)
        header_index = {h: i for i, (h, _) in enumerate(sections)}

        for op in ops:
            op_type = op.get("op")
            if op_type == "no_change":
                continue

            section = op.get("section", "")

            if op_type == "replace_section":
                if section not in header_index:
                    logger.warning(f"[PKB Overview] replace_section: section not found: {section!r}")
                    continue
                idx = header_index[section]
                sections[idx] = (section, op.get("new_content", "") + "\n")

            elif op_type == "append_to_section":
                if section not in header_index:
                    logger.warning(f"[PKB Overview] append_to_section: section not found: {section!r}")
                    continue
                idx = header_index[section]
                header, body = sections[idx]
                line = op.get("content", "")
                sections[idx] = (header, body.rstrip("\n") + "\n" + line + "\n")

            elif op_type == "insert_section":
                anchor = op.get("after_section", "")
                new_header = op.get("new_section", "")
                new_body = op.get("content", "")
                if anchor and anchor not in header_index:
                    logger.warning(f"[PKB Overview] insert_section: anchor not found: {anchor!r}")
                    # Append at end
                    sections.append((new_header, new_body + "\n"))
                    header_index[new_header] = len(sections) - 1
                else:
                    insert_at = (header_index[anchor] + 1) if anchor else len(sections)
                    sections.insert(insert_at, (new_header, new_body + "\n"))
                    # Rebuild index after insertion
                    header_index = {h: i for i, (h, _) in enumerate(sections)}

            elif op_type == "delete_from_section":
                if section not in header_index:
                    logger.warning(f"[PKB Overview] delete_from_section: section not found: {section!r}")
                    continue
                idx = header_index[section]
                header, body = sections[idx]
                match_text = op.get("match", "")
                lines = body.split("\n")
                lines = [l for l in lines if match_text not in l]
                sections[idx] = (header, "\n".join(lines))

            else:
                logger.warning(f"[PKB Overview] unknown op type: {op_type!r}")

        return self._assemble_sections(sections)

    # -----------------------------------------------------------------------
    # Prompt builders
    # -----------------------------------------------------------------------

    def _build_generate_prompt(self, user_email: str, progress_cb=None) -> str:
        from ..utils import now_iso
        # Cap only on first-time generation; uncapped on regenerate (overview already exists)
        existing = self.get_raw_content(user_email)
        cap = None if existing else FIRST_TIME_CLAIM_CAP
        claims = self._get_claims_for_generation(user_email, cap=cap)
        if progress_cb:
            progress_cb(f"Processing {len(claims)} claims...")
        entities = self._get_top_entities(user_email)
        contexts = self._get_contexts_summary(user_email)
        recent = self._get_recently_modified(user_email)
        today = now_iso()[:10]

        claims_text = "\n".join(
            f"  [{c['claim_type']}][{c['context_domain']}] {c['statement']}"
            for c in claims
        )
        return f"""Generate a markdown overview document for a personal knowledge base.
Write in third person ("The user prefers..." not "I prefer...").

Today: {today}

Claims ({len(claims)} shown, may be capped):
{claims_text}

Top entities (by claim-link count):
{entities}

Contexts:
{contexts}

Top 5 recently modified:
{recent}

Use this structure:
# Memory Overview
{_STATS_TEMPLATE}

## Summary
(2-4 sentences: what domains, what kind of person, what's most prominent)

## Key Areas
(one bullet per domain: **Domain** (N claims): keyword1, keyword2, ...)

## Important People & Entities
(top entities comma-separated with type in parens)

## Table of Contents
(contexts with claim counts and @friendly_id references)

## Recently Modified
(top 5 claims by recency: - [type] statement — date)

Return ONLY the markdown. No explanation."""

    def _build_scan_prompt(self, user_email: str, current: str) -> str:
        from ..utils import now_iso
        claims = self._get_claims_for_generation(user_email, cap=None)  # no cap
        claims_text = "\n".join(
            f"  [{c['claim_type']}][{c['context_domain']}] {c['statement']}"
            for c in claims
        )
        today = now_iso()[:10]
        return f"""You are reviewing a PKB overview document for gaps and outdated information.
Today: {today}

Current overview:
{current}

Full current knowledge base ({len(claims)} claims):
{claims_text}

Produce an updated overview that fills any gaps and corrects outdated information.
Use the same section structure. Write in third person.
Return ONLY the updated markdown. No explanation."""

    def _build_update_prompt(self, event: OverviewUpdateEvent, current: str, user_email: str) -> str:
        from ..utils import now_iso
        today = now_iso()[:10]
        recent = self._get_recently_modified(user_email)

        if event.trigger == "link" and event.link_metadata:
            m = event.link_metadata
            event_desc = f"Link event: {m.get('object_type','object')} \"{m.get('object_name','')}\" linked to claim: \"{m.get('claim_statement','')}\""
            focus_note = "For link events: only update Table of Contents (context links) or Important People & Entities if the link adds new information."
        else:
            claim_lines = "\n".join(
                f"  [claim: type={getattr(c,'claim_type','?')}, domain={getattr(c,'context_domain','?')}, statement=\"{getattr(c,'statement','')}\"]"
                for c in event.claims
            ) or "  (no claim details)"
            event_desc = f"Event: {event.trigger}\nChanged item(s):\n{claim_lines}"
            focus_note = "Update Key Areas if the domain's keyword list needs updating. Update Summary only if a new dominant theme emerges. For delete: update Key Areas count if significant."

        return f"""You are editing a markdown overview document about a person's knowledge base.
Make ONLY the minimal targeted edits required by the event below.
Do NOT rewrite sections unrelated to this event.
Output ONLY a JSON array of edit operations — not the full document.

Today: {today}

{event_desc}

Current overview:
{current}

Top 5 recently modified claims (always update Recently Modified section):
{recent}

Available operations:
  replace_section     — {{"op":"replace_section","section":"## Header","new_content":"..."}}
  append_to_section   — {{"op":"append_to_section","section":"## Header","content":"- new line"}}
  insert_section      — {{"op":"insert_section","after_section":"## Header","new_section":"## New","content":"..."}}
  delete_from_section — {{"op":"delete_from_section","section":"## Header","match":"text to remove"}}
  no_change           — {{"op":"no_change","reason":"..."}}

Rules:
- The stats line (*Claims: ... Last updated: ...*) is managed by the system — never touch it.
- Write in third person.
- {focus_note}
- Always update Recently Modified using the provided list.
- If nothing needs changing, output: [{{"op":"no_change","reason":"..."}}]

Output ONLY the JSON array. No explanation outside the JSON."""

    # -----------------------------------------------------------------------
    # Stats injection
    # -----------------------------------------------------------------------

    def _get_live_stats(self, user_email: str) -> OverviewStats:
        from ..utils import now_iso
        claims = self.db.fetchone(
            "SELECT COUNT(*) FROM claims WHERE user_email=? AND status NOT IN ('retracted','superseded')",
            (user_email,),
        )[0]
        contexts = self.db.fetchone(
            "SELECT COUNT(*) FROM contexts WHERE user_email=?",
            (user_email,),
        )[0]
        entities = self.db.fetchone(
            "SELECT COUNT(*) FROM entities WHERE user_email=?",
            (user_email,),
        )[0]
        tags = self.db.fetchone(
            "SELECT COUNT(*) FROM tags WHERE user_email=?",
            (user_email,),
        )[0]
        return OverviewStats(
            claims=claims, contexts=contexts, entities=entities,
            tags=tags, last_updated=now_iso()[:10],
        )

    def _inject_stats(self, content: str, stats: OverviewStats) -> str:
        line = _STATS_TEMPLATE.format(
            claims=stats.claims, contexts=stats.contexts,
            entities=stats.entities, tags=stats.tags,
            date=stats.last_updated,
        )
        replaced = _STATS_PATTERN.sub(line, content)
        if replaced == content and _STATS_TEMPLATE.split("{")[0] not in content:
            # Stats line not present — insert after first heading line
            lines = content.split("\n", 2)
            if len(lines) >= 2:
                replaced = lines[0] + "\n" + line + "\n" + "\n".join(lines[1:])
        return replaced

    def _ensure_stats_template(self, content: str) -> str:
        """Replace any filled-in stats with the template placeholder."""
        return _STATS_PATTERN.sub(_STATS_TEMPLATE, content)

    # -----------------------------------------------------------------------
    # Data helpers
    # -----------------------------------------------------------------------

    def _get_claims_for_generation(self, user_email: str, cap: Optional[int]) -> list:
        sql = (
            "SELECT statement, claim_type, context_domain "
            "FROM claims WHERE user_email=? AND status NOT IN ('retracted','superseded') "
            "ORDER BY COALESCE(last_reinforced_at, updated_at) DESC"
        )
        params = [user_email]
        if cap:
            sql += " LIMIT ?"
            params.append(cap)
        rows = self.db.fetchall(sql, tuple(params))
        return [{"statement": r[0], "claim_type": r[1], "context_domain": r[2]} for r in rows]

    def _get_top_entities(self, user_email: str) -> str:
        rows = self.db.fetchall(
            """
            SELECT e.name, e.entity_type, COUNT(ce.claim_id) as cnt
            FROM entities e
            LEFT JOIN claim_entities ce ON e.entity_id = ce.entity_id
            WHERE e.user_email=?
            GROUP BY e.entity_id
            ORDER BY cnt DESC
            LIMIT 20
            """,
            (user_email,),
        )
        if not rows:
            return "  (none)"
        return "\n".join(f"  {r[0]} ({r[1]}, {r[2]} claims)" for r in rows)

    def _get_contexts_summary(self, user_email: str) -> str:
        rows = self.db.fetchall(
            """
            SELECT c.name, c.friendly_id, COUNT(cc.claim_id) as cnt
            FROM contexts c
            LEFT JOIN context_claims cc ON c.context_id = cc.context_id
            WHERE c.user_email=?
            GROUP BY c.context_id
            ORDER BY cnt DESC
            """,
            (user_email,),
        )
        if not rows:
            return "  (none)"
        return "\n".join(
            f"  {r[0]} (@{r[1]}, {r[2]} claims)" if r[1] else f"  {r[0]} ({r[2]} claims)"
            for r in rows
        )

    def _get_recently_modified(self, user_email: str) -> str:
        rows = self.db.fetchall(
            """
            SELECT statement, claim_type, COALESCE(last_reinforced_at, updated_at) as ts
            FROM claims
            WHERE user_email=? AND status NOT IN ('retracted','superseded')
            ORDER BY ts DESC
            LIMIT 5
            """,
            (user_email,),
        )
        if not rows:
            return "  (none)"
        return "\n".join(f"  [{r[1]}] {r[0]} — {str(r[2])[:10]}" for r in rows)

    # -----------------------------------------------------------------------
    # LLM call
    # -----------------------------------------------------------------------

    def _call_llm(self, prompt: str) -> str:
        from code_common.call_llm import call_llm
        try:
            from common import CHEAP_LLM
            model = CHEAP_LLM[0]
        except ImportError:
            model = self.config.llm_model
        return call_llm(self.keys, model, prompt, temperature=0.2)

    def _parse_ops(self, raw: str) -> list:
        """Parse LLM output as a JSON array of edit ops. Returns [] on failure."""
        raw = raw.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```\s*$", "", raw, flags=re.MULTILINE)
        # Find first '[' to last ']'
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            raise ValueError(f"LLM output is not a JSON array: {raw[:200]!r}")
        return json.loads(raw[start:end + 1])

    # -----------------------------------------------------------------------
    # Consolidation
    # -----------------------------------------------------------------------

    def _consolidate(self, user_email: str, content: str) -> str:
        prompt = (
            "The following PKB overview has grown too long. Condense it to under 600 words "
            "while preserving ALL section headers, the Table of Contents in full, all named "
            "entities in Important People & Entities, and domain names with claim counts in "
            "Key Areas. Prose in Summary and Key Areas descriptions may be shortened.\n"
            "Return ONLY the condensed markdown.\n\n" + content
        )
        condensed = self._call_llm(prompt)
        condensed = self._ensure_stats_template(condensed)
        self.save(user_email, condensed)
        return condensed

    # -----------------------------------------------------------------------
    # Internal section parsing
    # -----------------------------------------------------------------------

    def _split_sections(self, content: str) -> list:
        """
        Split markdown content into (header, body) tuples.
        The leading content before any ## header is stored as ("", body).
        """
        sections = []
        # Split on '\n## ' boundaries
        parts = re.split(r"(?=\n## )", content)
        for part in parts:
            if part.startswith("\n## ") or part.startswith("## "):
                stripped = part.lstrip("\n")
                newline_pos = stripped.find("\n")
                if newline_pos == -1:
                    sections.append((stripped.strip(), ""))
                else:
                    header = stripped[:newline_pos].strip()
                    body = stripped[newline_pos + 1:]
                    sections.append((header, body))
            else:
                sections.append(("", part))
        return sections

    def _assemble_sections(self, sections: list) -> str:
        parts = []
        for i, (header, body) in enumerate(sections):
            if header:
                parts.append(header + "\n" + body)
            else:
                parts.append(body)
        return "\n".join(parts)

    # -----------------------------------------------------------------------
    # DB access
    # -----------------------------------------------------------------------

    def _fetch_row(self, user_email: str) -> Optional[dict]:
        row = self.db.fetchone(
            "SELECT content, word_count, last_updated, is_stale, topics_json FROM pkb_overview WHERE user_email=?",
            (user_email,),
        )
        if row is None:
            return None
        return {"content": row[0], "word_count": row[1], "last_updated": row[2], "is_stale": row[3], "topics_json": row[4]}
