"""Unit tests for code_common.doubt_context packing helpers (no DB / LLM)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Allow importing repo root modules when pytest cwd is repo root or tests/.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from code_common.doubt_context import (  # noqa: E402
    DOUBT_FULL_REPLAY_CHAR_BUDGET,
    DOUBT_OLDER_TURN_TRUNC_CHARS,
    DOUBT_RECENT_VERBATIM_TURNS,
    DOUBT_SUMMARY_MIN_TURNS,
    build_doubt_history_context_section,
    format_full_or_truncated_history,
    format_recent_turns,
    is_system_thread_summary_node,
    needs_sync_bootstrap,
    pack_history_for_bootstrap,
    select_path_summary,
    should_generate_summary_for_path,
)


def _node(
    i: int,
    *,
    summary: str | None = None,
    status: str | None = None,
    text: str | None = None,
    answer: str | None = None,
    answer_len: int | None = None,
) -> dict:
    ans = answer
    if ans is None and answer_len is not None:
        ans = ("A" * answer_len)
    elif ans is None:
        ans = f"answer-{i}"
    return {
        "doubt_id": f"d{i}",
        "doubt_text": text if text is not None else f"question-{i}",
        "doubt_answer": ans,
        "parent_doubt_id": f"d{i-1}" if i > 1 else None,
        "thread_summary_upto_here": summary,
        "summary_status": status,
    }


class TestSystemNodeFilter:
    def test_thread_summary_detected(self):
        assert is_system_thread_summary_node({"doubt_text": "Thread Summary"})
        assert is_system_thread_summary_node({"doubt_text": "  Thread Summary  "})

    def test_normal_node_not_system(self):
        assert not is_system_thread_summary_node({"doubt_text": "what is X?"})
        assert not is_system_thread_summary_node({})
        assert not is_system_thread_summary_node(None)


class TestSelectPathSummary:
    def test_empty(self):
        assert select_path_summary([]) is None
        assert select_path_summary(None) is None

    def test_prefers_tip_ready(self):
        hist = [
            _node(1, summary="old", status="ready"),
            _node(2, summary="tip summary", status="ready"),
        ]
        assert select_path_summary(hist) == "tip summary"

    def test_walks_to_ancestor_when_tip_not_ready(self):
        hist = [
            _node(1, summary="ancestor", status="ready"),
            _node(2, summary="stale", status="dirty"),
            _node(3, summary=None, status="pending"),
        ]
        assert select_path_summary(hist) == "ancestor"

    def test_ignores_empty_ready_text(self):
        hist = [_node(1, summary="   ", status="ready"), _node(2, summary=None, status=None)]
        assert select_path_summary(hist) is None

    def test_ignores_error_status(self):
        hist = [_node(1, summary="bad", status="error")]
        assert select_path_summary(hist) is None


class TestBootstrapGates:
    def test_min_turns_constant(self):
        assert DOUBT_SUMMARY_MIN_TURNS == 2
        assert DOUBT_RECENT_VERBATIM_TURNS == 3

    def test_should_generate(self):
        assert not should_generate_summary_for_path(0)
        assert not should_generate_summary_for_path(1)
        assert should_generate_summary_for_path(2)
        assert should_generate_summary_for_path(5)

    def test_needs_sync_bootstrap_true_when_long_and_no_summary(self):
        hist = [_node(1), _node(2), _node(3)]
        assert needs_sync_bootstrap(hist) is True

    def test_needs_sync_bootstrap_false_when_short(self):
        assert needs_sync_bootstrap([_node(1)]) is False
        assert needs_sync_bootstrap([]) is False

    def test_needs_sync_bootstrap_false_when_ready(self):
        hist = [
            _node(1, summary="s", status="ready"),
            _node(2, summary="s2", status="ready"),
        ]
        assert needs_sync_bootstrap(hist) is False


class TestFormatRecentTurns:
    def test_empty(self):
        assert format_recent_turns([]) == ""
        assert format_recent_turns(None) == ""

    def test_last_three_of_four(self):
        hist = [_node(i) for i in range(1, 5)]
        text = format_recent_turns(hist, k=3)
        assert "question-1" not in text
        assert "question-2" in text
        assert "question-3" in text
        assert "question-4" in text
        # Index labels continue from full chain (not restart at 1)
        assert "**Previous Doubt 2:**" in text
        assert "**Previous Doubt 4:**" in text
        assert "**Previous Doubt 1:**" not in text

    def test_filters_system_thread_summary(self):
        hist = [
            _node(1),
            _node(2, text="Thread Summary", answer="human visible dump"),
            _node(3),
        ]
        text = format_recent_turns(hist, k=3)
        assert "Thread Summary" not in text
        assert "human visible dump" not in text
        assert "question-1" in text
        assert "question-3" in text


class TestFullOrTruncated:
    def test_short_full_replay(self):
        hist = [_node(1), _node(2)]
        text = format_full_or_truncated_history(hist)
        assert "question-1" in text
        assert "question-2" in text
        assert "…" not in text

    def test_over_budget_truncates_older(self):
        # Make older answers huge so full dump exceeds budget.
        huge = DOUBT_FULL_REPLAY_CHAR_BUDGET // 2 + 500
        hist = [
            _node(1, answer_len=huge),
            _node(2, answer_len=huge),
            _node(3, answer="recent-a"),
            _node(4, answer="recent-b"),
            _node(5, answer="recent-c"),
        ]
        text = format_full_or_truncated_history(hist)
        assert len(text) < DOUBT_FULL_REPLAY_CHAR_BUDGET * 1.2  # soft bound
        assert "recent-a" in text
        assert "recent-b" in text
        assert "recent-c" in text
        # Older answers truncated with ellipsis
        assert "…" in text
        # verification that older answers are not fully present
        assert ("A" * huge) not in text
        assert DOUBT_OLDER_TURN_TRUNC_CHARS < huge

    def test_bootstrap_pack_matches_fallback(self):
        hist = [_node(i, answer_len=100) for i in range(1, 6)]
        assert pack_history_for_bootstrap(hist) == format_full_or_truncated_history(hist)


class TestBuildSection:
    def test_empty_history(self):
        assert build_doubt_history_context_section([]) == ""
        assert build_doubt_history_context_section(None) == ""

    def test_with_ready_summary_uses_summary_and_last_three(self):
        hist = [
            _node(1, summary="s1", status="ready"),
            _node(2),
            _node(3),
            _node(4, summary="tip mem", status="ready"),
        ]
        section = build_doubt_history_context_section(hist)
        assert section.startswith("# Doubt Thread Running Summary")
        assert "tip mem" in section
        assert "# Recent Doubt Turns" in section
        assert "question-1" not in section  # only last 3
        assert "question-2" in section
        assert "question-4" in section
        # No full-history header and no current-follow-up leak
        assert "# Previous Doubt History" not in section
        assert "Current Follow-up Question" not in section

    def test_without_summary_uses_previous_history_header(self):
        hist = [_node(1), _node(2)]
        section = build_doubt_history_context_section(hist)
        assert section.startswith("# Previous Doubt History")
        assert "question-1" in section
        assert "question-2" in section
        assert "Current Follow-up Question" not in section

    def test_ignores_current_doubt_text_arg(self):
        hist = [_node(1)]
        section = build_doubt_history_context_section(hist, current_doubt_text="SHOULD NOT APPEAR")
        assert "SHOULD NOT APPEAR" not in section

    def test_system_only_history_empty_section(self):
        hist = [_node(1, text="Thread Summary", answer="note")]
        assert build_doubt_history_context_section(hist) == ""
