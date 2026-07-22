"""Regression coverage for CKT Duckie round-admission policy."""

from code_common.ckt_internal_tools import CKT_INTERNAL_TOOL_NAMES
from code_common.tools import build_ckt_tool_workflow_hint


def test_ckt_policy_prohibits_duckie_in_round_one_except_explicit_need():
    hint = build_ckt_tool_workflow_hint(CKT_INTERNAL_TOOL_NAMES)

    assert "Do not call `duckie_search` or `ckt_duckie_retrieval` in ROUND 1" in hint
    assert "explicitly asks for Duckie" in hint
    assert "clearly requires Duckie-specific evidence" in hint
    assert "ROUND 2+ for further investigation" in hint


def test_round_one_duckie_calls_are_deferred_without_execution():
    from Conversation import Conversation

    result = Conversation._defer_round_one_ckt_duckie_call(
        iteration=0,
        tool_name="duckie_search",
        tool_args={"query": "How does this system work?"},
        prompt="How does this system work?",
    )

    assert result is not None
    assert result.error is None
    assert "Duckie call deferred by retrieval policy." in result.result
    assert "ROUND 2+" in result.result
    assert "for further investigation" in result.result


def test_explicit_duckie_request_is_not_deferred():
    from Conversation import Conversation

    assert Conversation._defer_round_one_ckt_duckie_call(
        iteration=0,
        tool_name="duckie_search",
        tool_args={"query": "Ask Duckie how this system works"},
        prompt="Please ask Duckie how this system works.",
    ) is None


def test_non_duckie_and_later_round_calls_are_not_deferred():
    from Conversation import Conversation

    assert Conversation._defer_round_one_ckt_duckie_call(
        iteration=0,
        tool_name="moma_search",
        tool_args={"query": "system"},
        prompt="How does this system work?",
    ) is None
    assert Conversation._defer_round_one_ckt_duckie_call(
        iteration=1,
        tool_name="ckt_duckie_retrieval",
        tool_args={"query": "system"},
        prompt="How does this system work?",
    ) is None
