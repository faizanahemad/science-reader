"""Verify STM-silent precedent: short-term memories persist without user approval.

This test documents that short_term_candidates from the extraction pipeline
are saved to pkb_short_term_memory *without* going through the proposal/approval
flow. This is the existing precedent that tiered persistence (auto-save for
confident, safe long-term claims) extends.

References:
- endpoints/pkb.py:2117 — "# Silently store short-term memories (no user approval needed)"
- The STM candidates are in plan.short_term_candidates, NOT in plan.proposed_actions
- execute_plan only processes proposed_actions[approved_indices] — STM is separate
"""
import pytest
from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI


@pytest.fixture
def api():
    config = PKBConfig(db_path=":memory:", stm_enabled=True)
    db = PKBDatabase(config)
    db.initialize_schema()
    return StructuredAPI(db, {}, config, user_email="test@example.com")


class TestSTMSilentPrecedent:
    def test_add_short_term_memory_requires_no_approval(self, api):
        """add_short_term_memory saves directly — no approval gate."""
        result = api.add_short_term_memory(
            statement="User mentioned they have a meeting at 3pm",
            conversation_id="conv_123",
            importance="medium",
            ttl_class="day",
        )
        assert result.success is True
        # Verify it's persisted
        memories = api.get_active_short_term_memories()
        assert memories.success
        assert len(memories.data) == 1
        assert memories.data[0]["statement"] == "User mentioned they have a meeting at 3pm"

    def test_stm_not_in_proposed_actions(self):
        """MemoryUpdatePlan.short_term_candidates are separate from proposed_actions."""
        from truth_management_system.interface.conversation_distillation import MemoryUpdatePlan
        plan = MemoryUpdatePlan(proposed_actions=[], short_term_candidates=[])
        # The dataclass keeps them as independent fields — confirming the design
        assert hasattr(plan, "short_term_candidates")
        assert hasattr(plan, "proposed_actions")
        # proposed_actions go through execute_plan(approved_indices)
        # short_term_candidates are saved directly without that gate
