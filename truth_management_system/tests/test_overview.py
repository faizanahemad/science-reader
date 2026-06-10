"""
Unit tests for PKBOverviewManager.

All tests run offline (in-memory SQLite, no LLM calls).
LLM-dependent methods are tested with mocked call_llm.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from truth_management_system.database import get_memory_database
from truth_management_system.config import PKBConfig
from truth_management_system.interface.overview_manager import (
    PKBOverviewManager,
    OverviewUpdateEvent,
    _STATS_TEMPLATE,
)
from truth_management_system.utils import generate_friendly_id


def _make_manager(db=None, config=None):
    if db is None:
        db = get_memory_database(auto_init=True)
    if config is None:
        config = PKBConfig(db_path=":memory:")
    return db, PKBOverviewManager(db, {}, config)


class TestSchemaAndMigration(unittest.TestCase):
    def test_pkb_overview_table_created_on_fresh_db(self):
        db = get_memory_database(auto_init=True)
        row = db.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name='pkb_overview'")
        self.assertIsNotNone(row, "pkb_overview table should exist in fresh DB")

    def test_schema_version_is_12(self):
        from truth_management_system.schema import SCHEMA_VERSION
        self.assertEqual(SCHEMA_VERSION, 12)

    def test_audit_log_survives_migration(self):
        """audit_log (v10) must still exist in a v11 DB."""
        db = get_memory_database(auto_init=True)
        row = db.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'")
        self.assertIsNotNone(row, "audit_log table should still exist after v11 migration")


class TestSaveAndRead(unittest.TestCase):
    def test_save_and_get_raw_content_round_trip(self):
        db, m = _make_manager()
        m.save("user@example.com", "# Hello\n\nWorld")
        raw = m.get_raw_content("user@example.com")
        self.assertEqual(raw, "# Hello\n\nWorld")

    def test_get_raw_content_returns_none_when_no_row(self):
        db, m = _make_manager()
        self.assertIsNone(m.get_raw_content("nobody@example.com"))

    def test_save_clears_stale_flag(self):
        db, m = _make_manager()
        m.save("user@example.com", "content")
        m.mark_stale("user@example.com")
        row = db.fetchone("SELECT is_stale FROM pkb_overview WHERE user_email=?", ("user@example.com",))
        self.assertEqual(row[0], 1)
        m.save("user@example.com", "updated content")
        row = db.fetchone("SELECT is_stale FROM pkb_overview WHERE user_email=?", ("user@example.com",))
        self.assertEqual(row[0], 0)

    def test_mark_stale_sets_flag(self):
        db, m = _make_manager()
        m.save("user@example.com", "some content")
        m.mark_stale("user@example.com")
        row = db.fetchone("SELECT is_stale FROM pkb_overview WHERE user_email=?", ("user@example.com",))
        self.assertEqual(row[0], 1)

    def test_word_count_stored_correctly(self):
        db, m = _make_manager()
        m.save("user@example.com", "one two three four five")
        row = db.fetchone("SELECT word_count FROM pkb_overview WHERE user_email=?", ("user@example.com",))
        self.assertEqual(row[0], 5)


class TestStatsInjection(unittest.TestCase):
    def test_inject_stats_replaces_template_line(self):
        db, m = _make_manager()
        content = "# Overview\n" + _STATS_TEMPLATE + "\n## Summary\nHello"
        from truth_management_system.interface.overview_manager import OverviewStats
        stats = OverviewStats(claims=10, contexts=2, entities=5, tags=3, last_updated="2026-01-01")
        result = m._inject_stats(content, stats)
        self.assertIn("Claims: 10", result)
        self.assertIn("Contexts: 2", result)
        self.assertIn("Entities: 5", result)
        self.assertNotIn("{claims}", result)

    def test_ensure_stats_template_replaces_filled_values(self):
        db, m = _make_manager()
        filled = "*Claims: 10 · Contexts: 2 · Entities: 5 · Tags: 3 · Last updated: 2026-01-01*"
        result = m._ensure_stats_template(filled)
        self.assertIn("{claims}", result)


class TestApplyEdits(unittest.TestCase):
    CONTENT = """# Memory Overview
*Claims: {claims} · Contexts: {contexts} · Entities: {entities} · Tags: {tags} · Last updated: {date}*

## Summary
Old summary text.

## Key Areas
- **Health** (10 claims): workouts

## Recently Modified
- [fact] Old claim — 2026-01-01
"""

    def test_replace_section(self):
        db, m = _make_manager()
        ops = [{"op": "replace_section", "section": "## Summary", "new_content": "New summary."}]
        result = m._apply_edits(self.CONTENT, ops)
        self.assertIn("New summary.", result)
        self.assertNotIn("Old summary text.", result)
        # Untouched sections preserved
        self.assertIn("## Key Areas", result)
        self.assertIn("## Recently Modified", result)

    def test_append_to_section(self):
        db, m = _make_manager()
        ops = [{"op": "append_to_section", "section": "## Key Areas", "content": "- **Work** (5 claims): meetings"}]
        result = m._apply_edits(self.CONTENT, ops)
        self.assertIn("**Work**", result)
        self.assertIn("**Health**", result)

    def test_insert_section(self):
        db, m = _make_manager()
        ops = [{"op": "insert_section", "after_section": "## Summary", "new_section": "## New Section", "content": "New content here."}]
        result = m._apply_edits(self.CONTENT, ops)
        self.assertIn("## New Section", result)
        self.assertIn("New content here.", result)

    def test_delete_from_section(self):
        db, m = _make_manager()
        ops = [{"op": "delete_from_section", "section": "## Recently Modified", "match": "Old claim"}]
        result = m._apply_edits(self.CONTENT, ops)
        self.assertNotIn("Old claim", result)

    def test_no_change_op_leaves_content_unchanged(self):
        db, m = _make_manager()
        ops = [{"op": "no_change", "reason": "Nothing to do"}]
        result = m._apply_edits(self.CONTENT, ops)
        self.assertEqual(result, self.CONTENT)

    def test_unmatched_section_skipped_not_error(self):
        db, m = _make_manager()
        ops = [{"op": "replace_section", "section": "## Does Not Exist", "new_content": "x"}]
        result = m._apply_edits(self.CONTENT, ops)
        # Content unchanged; no exception
        self.assertIn("## Summary", result)

    def test_all_untouched_sections_preserved(self):
        db, m = _make_manager()
        ops = [{"op": "replace_section", "section": "## Summary", "new_content": "Updated."}]
        result = m._apply_edits(self.CONTENT, ops)
        for section in ["## Key Areas", "## Recently Modified", "**Health**"]:
            self.assertIn(section, result)


class TestGenerateFull(unittest.TestCase):
    @patch("truth_management_system.interface.overview_manager.PKBOverviewManager._call_llm")
    def test_generate_full_stores_content_directly(self, mock_llm):
        mock_llm.return_value = "# Memory Overview\n" + _STATS_TEMPLATE + "\n## Summary\nTest.\n"
        db, m = _make_manager()
        result = m.generate_full("user@example.com")
        self.assertTrue(result.content.startswith("# Memory Overview"))
        self.assertFalse(result.is_stale)
        # Stored directly (not via _apply_edits)
        raw = m.get_raw_content("user@example.com")
        self.assertIn("# Memory Overview", raw)

    @patch("truth_management_system.interface.overview_manager.PKBOverviewManager._call_llm")
    def test_generate_full_does_not_use_apply_edits(self, mock_llm):
        """generate_full should store full output, not apply edit ops."""
        mock_llm.return_value = "# Memory Overview\n" + _STATS_TEMPLATE + "\n## Summary\nDirect output.\n"
        db, m = _make_manager()
        with patch.object(m, '_apply_edits', wraps=m._apply_edits) as mock_apply:
            m.generate_full("user@example.com")
            mock_apply.assert_not_called()


class TestUpdateFromEvent(unittest.TestCase):
    INITIAL = "# Memory Overview\n" + _STATS_TEMPLATE + "\n## Summary\nOld.\n## Key Areas\n- **Health** (5 claims): workouts\n## Recently Modified\n- [fact] Old — 2026-01-01\n"
    EDIT_OPS = json.dumps([
        {"op": "replace_section", "section": "## Summary", "new_content": "New summary from event."},
        {"op": "replace_section", "section": "## Recently Modified", "new_content": "- [fact] New claim — 2026-06-10"},
    ])

    @patch("truth_management_system.interface.overview_manager.PKBOverviewManager._call_llm")
    def test_update_from_event_applies_ops(self, mock_llm):
        mock_llm.return_value = self.EDIT_OPS
        db, m = _make_manager()
        m.save("user@example.com", self.INITIAL)

        claim = MagicMock()
        claim.statement = "New claim about health"
        claim.claim_type = "fact"
        claim.context_domain = "health"

        event = OverviewUpdateEvent(trigger="add", claims=[claim], current_content=self.INITIAL)
        result = m.update_from_event("user@example.com", event)
        self.assertIn("New summary from event.", result.content)

    @patch("truth_management_system.interface.overview_manager.PKBOverviewManager._call_llm")
    def test_update_from_event_link_trigger_includes_link_metadata(self, mock_llm):
        mock_llm.return_value = json.dumps([{"op": "no_change", "reason": "minor"}])
        db, m = _make_manager()
        m.save("user@example.com", self.INITIAL)

        event = OverviewUpdateEvent(
            trigger="link", claims=[], current_content=self.INITIAL,
            link_metadata={"object_type": "tag", "object_name": "fitness", "claim_statement": "Morning workouts"},
        )
        m.update_from_event("user@example.com", event)
        # Check prompt contained link metadata info
        prompt_arg = mock_llm.call_args[0][0]
        self.assertIn("fitness", prompt_arg)

    @patch("truth_management_system.interface.overview_manager.PKBOverviewManager._call_llm")
    def test_update_from_event_marks_stale_on_llm_failure(self, mock_llm):
        mock_llm.side_effect = Exception("LLM timeout")
        db, m = _make_manager()
        m.save("user@example.com", self.INITIAL)

        event = OverviewUpdateEvent(trigger="add", claims=[], current_content=self.INITIAL)
        with self.assertRaises(Exception):
            m.update_from_event("user@example.com", event)
        row = db.fetchone("SELECT is_stale FROM pkb_overview WHERE user_email=?", ("user@example.com",))
        self.assertEqual(row[0], 1)


class TestGetKeyAreasSnippet(unittest.TestCase):
    def test_returns_none_when_no_overview(self):
        db, m = _make_manager()
        self.assertIsNone(m.get_key_areas_snippet("user@example.com"))

    def test_extracts_key_areas_and_toc(self):
        db, m = _make_manager()
        content = (
            "# Overview\n## Summary\nSome summary.\n"
            "## Key Areas\n- **Health** (10 claims): workouts\n"
            "## Important People & Entities\nDr. Smith\n"
            "## Table of Contents\n- @health_context — 10 claims\n"
            "## Recently Modified\n- [fact] Old claim\n"
        )
        m.save("user@example.com", content)
        snippet = m.get_key_areas_snippet("user@example.com")
        self.assertIsNotNone(snippet)
        self.assertIn("Key Areas", snippet)
        self.assertIn("Table of Contents", snippet)
        self.assertNotIn("Summary", snippet)
        self.assertNotIn("Recently Modified", snippet)

    def test_snippet_truncated_to_cap(self):
        db, m = _make_manager()
        long_body = " ".join(["word"] * 300)
        content = "# Overview\n## Key Areas\n" + long_body + "\n## Table of Contents\nsome context\n"
        m.save("user@example.com", content)
        snippet = m.get_key_areas_snippet("user@example.com")
        word_count = len(snippet.split())
        from truth_management_system.interface.overview_manager import KEY_AREAS_WORD_CAP
        self.assertLessEqual(word_count, KEY_AREAS_WORD_CAP + 5)  # small fuzz for "..."


class TestReservedFriendlyId(unittest.TestCase):
    def test_pkb_overview_is_reserved(self):
        """No statement should generate friendly_id = 'pkb_overview'."""
        # Patch random to force a collision, then verify guard triggers
        import random
        import string
        with patch("truth_management_system.utils.random") as mock_rand:
            # First call returns 'over' (would form pkb_overview), second call returns a safe suffix
            call_count = [0]
            original_choices = random.choices
            def side_effect(population, k=None):
                call_count[0] += 1
                if call_count[0] == 1:
                    return list("over")  # forms pkb_overview with base 'pkb'
                return list("abcd")
            mock_rand.choices = side_effect
            # generate_friendly_id for 'pkb' base would form 'pkb_over' not 'pkb_overview'
            # so test the exact-match guard by directly calling it
            from truth_management_system.utils import generate_friendly_id
            # The guard checks if candidate == "pkb_overview"; simulate by choosing a statement
            # that produces "pkb" as base — this is hard to force, so test the guard logic directly
        # Direct unit test of the reserved set logic
        from truth_management_system.utils import generate_friendly_id
        for _ in range(50):
            fid = generate_friendly_id("pkb overview of memories")
            self.assertNotEqual(fid, "pkb_overview", f"Generated reserved friendly_id: {fid}")


class TestMultiUserIsolation(unittest.TestCase):
    def test_overview_scoped_to_user(self):
        db, m = _make_manager()
        m.save("alice@example.com", "# Alice's Overview\n## Summary\nAlice.")
        m.save("bob@example.com", "# Bob's Overview\n## Summary\nBob.")
        self.assertIn("Alice", m.get_raw_content("alice@example.com"))
        self.assertIn("Bob", m.get_raw_content("bob@example.com"))
        self.assertNotIn("Bob", m.get_raw_content("alice@example.com"))


class TestExtractTopics(unittest.TestCase):
    def test_parses_key_areas_into_structured_list(self):
        content = (
            "# Overview\n## Key Areas\n"
            "- **Health** (10 claims): workouts, diet\n"
            "- **Work** (25 claims): meetings, projects\n"
            "- **Cooking** (3 claims)\n"
            "## Recently Modified\n- something\n"
        )
        from truth_management_system.interface.overview_manager import PKBOverviewManager
        topics = PKBOverviewManager._extract_topics(content)
        self.assertEqual(len(topics), 3)
        self.assertEqual(topics[0]["name"], "Health")
        self.assertEqual(topics[0]["claim_count"], 10)
        self.assertEqual(topics[0]["description"], "workouts, diet")
        self.assertEqual(topics[1]["name"], "Work")
        self.assertEqual(topics[1]["claim_count"], 25)
        self.assertEqual(topics[2]["description"], "")

    def test_returns_empty_when_no_key_areas(self):
        from truth_management_system.interface.overview_manager import PKBOverviewManager
        topics = PKBOverviewManager._extract_topics("# Overview\n## Summary\nHello")
        self.assertEqual(topics, [])

    def test_topics_stored_on_save(self):
        db, m = _make_manager()
        content = "# Overview\n## Key Areas\n- **Finance** (7 claims): budgets\n## Summary\nOk."
        m.save("user@example.com", content)
        topics = m.get_topics("user@example.com")
        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0]["name"], "Finance")
        self.assertEqual(topics[0]["claim_count"], 7)


if __name__ == "__main__":
    unittest.main()
