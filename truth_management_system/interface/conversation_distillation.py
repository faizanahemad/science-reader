"""
Conversation Distillation for PKB v0.

ConversationDistiller extracts memorable facts from chat conversations
and proposes memory updates for user confirmation.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any

from .structured_api import StructuredAPI, ActionResult
from ..config import PKBConfig
from ..models import Claim
from ..constants import ClaimType, ContextDomain

logger = logging.getLogger(__name__)


@dataclass
class CandidateClaim:
    """A candidate claim extracted from conversation."""
    statement: str
    claim_type: str
    context_domain: str
    confidence: float = 0.8
    source: str = "chat_distillation"
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    # W2: epistemic basis labeled by the extraction LLM.
    #   stated    -- user said it ~verbatim
    #   extracted -- rephrased from the user's own words (same content)
    #   inferred  -- a conclusion the user never explicitly stated
    derivation: str = "extracted"

@dataclass
class ProposedAction:
    """A proposed action for user confirmation."""
    action: str
    candidate: CandidateClaim
    existing_claim: Optional[Claim] = None
    relation: Optional[str] = None
    reason: str = ""


@dataclass
class MemoryUpdatePlan:
    """Plan of memory updates for user confirmation."""
    candidates: List[CandidateClaim] = field(default_factory=list)
    existing_matches: List[Tuple[CandidateClaim, Claim, str]] = field(default_factory=list)
    proposed_actions: List[ProposedAction] = field(default_factory=list)
    user_prompt: str = ""
    requires_user_confirmation: bool = True
    # Provenance (E1): the conversation/message this plan was distilled from,
    # threaded into add_claim so saved claims can answer "why do I know this?".
    source_conversation_id: Optional[str] = None
    source_message_id: Optional[str] = None


@dataclass
class DistillationResult:
    """Result of distillation execution."""
    plan: MemoryUpdatePlan
    executed: bool = False
    execution_results: List[ActionResult] = field(default_factory=list)


class ConversationDistiller:
    """Extract and manage claims from chat conversations."""
    
    def __init__(self, api: StructuredAPI, keys: Dict[str, str], config: PKBConfig = None,
                 extraction_mode: str = 'relaxed'):
        """
        Args:
            api: StructuredAPI instance for claim storage/retrieval.
            keys: LLM API keys dict.
            config: PKBConfig instance (uses defaults if None).
            extraction_mode: 'relaxed' (only clear concrete facts) or
                             'aggressive' (eager, wide net -- opinions, goals,
                             routines, preferences, anything personal).
        """
        self.api = api
        self.keys = keys
        self.config = config or PKBConfig()
        self.extraction_mode = extraction_mode
    
    def extract_and_propose(self, conversation_summary: str, user_message: str,
                            assistant_message: str,
                            recent_turns: list = None,
                            source_conversation_id: str = None,
                            source_message_id: str = None) -> MemoryUpdatePlan:
        """
        Extract claims from the current user utterance and propose memory updates.
        recent_turns: list of {"user": str, "assistant": str} dicts, most-recent last.
        source_conversation_id / source_message_id: provenance (E1) recorded on
        any claims saved from this plan, so they can answer "why do I know this?".
        """
        candidates = self._extract_claims_from_turn(
            conversation_summary, user_message, assistant_message,
            recent_turns=recent_turns or [],
        )
        
        if not candidates:
            return MemoryUpdatePlan(user_prompt="No memorable facts found.", requires_user_confirmation=False)
        
        matches = []
        for candidate in candidates:
            existing = self._find_existing_matches(candidate)
            matches.extend([(candidate, claim, relation) for claim, relation in existing])
        
        proposed_actions = self._propose_actions(candidates, matches)
        user_prompt = self._generate_confirmation_prompt(proposed_actions)
        
        return MemoryUpdatePlan(candidates=candidates, existing_matches=matches,
                               proposed_actions=proposed_actions, user_prompt=user_prompt,
                               requires_user_confirmation=len(proposed_actions) > 0,
                               source_conversation_id=source_conversation_id,
                               source_message_id=source_message_id)
    
    def execute_plan(self, plan: MemoryUpdatePlan, user_response: str,
                     approved_indices: List[int] = None) -> DistillationResult:
        """Execute approved actions from the plan."""
        if not plan.proposed_actions:
            return DistillationResult(plan=plan, executed=False)
        
        if approved_indices is None:
            approved_indices = self._parse_approval_response(user_response, len(plan.proposed_actions))
        
        # E1: make the plan's provenance available to _execute_action so saved
        # claims record their originating conversation/message.
        self._source_conversation_id = getattr(plan, "source_conversation_id", None)
        self._source_message_id = getattr(plan, "source_message_id", None)

        results = []
        for i in approved_indices:
            if 0 <= i < len(plan.proposed_actions):
                result = self._execute_action(plan.proposed_actions[i])
                results.append(result)
        
        return DistillationResult(plan=plan, executed=True, execution_results=results)
    
    def _extract_claims_from_turn(self, conversation_summary: str, user_message: str,
                                   assistant_message: str,
                                   recent_turns: list = None) -> List[CandidateClaim]:
        """
        Use LLM to extract memorable claims from the CURRENT USER UTTERANCE only.
        recent_turns provides context so the LLM understands what is being discussed,
        but extraction is scoped exclusively to user_message.
        Prompt strategy differs by extraction_mode:
          'relaxed'    -- 1 prior turn for context; explicit concrete facts only.
          'aggressive' -- up to 2 prior turns for context; wide net.
        """
        try:
            from code_common.call_llm import call_llm
        except ImportError:
            return []
        
        recent_turns = recent_turns or []
        
        # Build prior-context block from the ring buffer.
        # Relaxed uses the last 1 turn; aggressive uses up to 2.
        context_depth = 1 if self.extraction_mode != 'aggressive' else 2
        prior_turns = recent_turns[-context_depth:] if recent_turns else []
        
        prior_context_lines = []
        if conversation_summary:
            prior_context_lines.append(f"Conversation summary: {conversation_summary}")
        for i, turn in enumerate(prior_turns, 1):
            prior_context_lines.append(
                f"Prior turn {i}:\n"
                f"  User: {turn.get('user', '')[:500]}\n"
                f"  Assistant: {turn.get('assistant', '')[:800]}"
            )
        prior_context = "\n\n".join(prior_context_lines) if prior_context_lines else "(none)"
        if self.extraction_mode == 'aggressive':
            prompt = f"""You are a personal memory assistant. Extract EVERYTHING worth remembering about the user from their latest message.

=== CONTEXT (for understanding only -- do NOT extract claims from here) ===
{prior_context}

=== CURRENT USER MESSAGE (extract claims FROM HERE ONLY) ===
{user_message}

What the assistant said this turn (may clarify meaning, do not extract from it):
{assistant_message or '(none)'}"""
            prompt += """

Your task: extract any of the following about the USER from the CURRENT USER MESSAGE above:
- Stated facts (job, location, age, health, diet, etc.)
- Preferences and opinions (likes, dislikes, tastes)
- Goals, plans, aspirations
- Habits and routines
- Decisions made
- Tasks or reminders mentioned
- Observations the user makes about themselves
- Relationships mentioned
Only extract facts FROM THE CURRENT USER MESSAGE -- not from prior turns or context.

Valid claim_type values: fact, preference, decision, task, reminder, habit, memory, observation
Valid context_domain values: personal, health, work, relationships, learning, life_ops, finance

For each claim, also include a "derivation" field describing its epistemic basis:
- "stated": the user explicitly said this, ~verbatim.
- "extracted": rephrased/normalized from the user's own words (same meaning, no new conclusion).
- "inferred": a conclusion you drew that the user did NOT explicitly state (e.g. generalizing "I ran 5k today" + "I cycle daily" into "User is health-conscious"). Use sparingly.

IMPORTANT: Return ONLY a valid JSON array with NO additional text before or after.
For task/reminder types, include a "valid_to" field with the deadline in YYYY-MM-DD format if mentioned.
Include a "tags" array with relevant short keyword tags.
Example format:
[{"statement": "User prefers dark roast coffee", "claim_type": "preference", "context_domain": "personal", "confidence": 0.85, "derivation": "stated", "tags": ["coffee"]}, {"statement": "User needs to submit report by Friday", "claim_type": "task", "context_domain": "work", "confidence": 0.9, "valid_to": "2025-07-18", "derivation": "stated", "tags": ["report", "deadline"]}]

If nothing at all is worth remembering from the current message, return exactly: []

Response:"""
        else:  # relaxed (default)
            prompt = f"""Extract clearly stated, concrete personal facts from the user's latest message.

=== CONTEXT (for understanding only -- do NOT extract claims from here) ===
{prior_context}

=== CURRENT USER MESSAGE (extract claims FROM HERE ONLY) ===
{user_message}

What the assistant said this turn (may clarify meaning, do not extract from it):
{assistant_message or '(none)'}"""
            prompt += """
Rules:
- Only extract facts the user EXPLICITLY states about themselves in the CURRENT USER MESSAGE.
- Use the context only to understand what topic is being discussed -- never extract from it.
- Skip vague, generic, or conversational remarks.
- Skip questions the user asks (unless the asking itself reveals a personal fact).
- Only include high-confidence, specific, actionable memories.
Valid claim_type values: fact, preference, decision, task, reminder, habit, memory, observation
Valid context_domain values: personal, health, work, relationships, learning, life_ops, finance

For each claim, also include a "derivation" field describing its epistemic basis:
- "stated": the user explicitly said this, ~verbatim.
- "extracted": rephrased/normalized from the user's own words (same meaning, no new conclusion).
- "inferred": a conclusion you drew that the user did NOT explicitly state (e.g. generalizing "I ran 5k today" + "I cycle daily" into "User is health-conscious"). Use sparingly.

IMPORTANT: Return ONLY a valid JSON array with NO additional text before or after.
For task/reminder types, include a "valid_to" field with the deadline in YYYY-MM-DD format if mentioned.
Include a "tags" array with relevant short keyword tags.
Example format:
[{"statement": "User is vegetarian", "claim_type": "fact", "context_domain": "health", "confidence": 0.9, "derivation": "stated", "tags": ["diet"]}, {"statement": "User has dentist appointment next Monday", "claim_type": "reminder", "context_domain": "health", "confidence": 0.9, "valid_to": "2025-07-21", "derivation": "stated", "tags": ["dentist", "appointment"]}]

If no clear personal facts to remember from the current message, return exactly: []

Response:"""
        
        try:
            response = call_llm(self.keys, self.config.llm_model, prompt, temperature=0.0)
            response_text = response.strip()
            try:
                parsed = json.loads(response_text)
            except json.JSONDecodeError:
                import re
                array_match = re.search(r'\[.*\]', response_text, re.DOTALL)
                if array_match:
                    parsed = json.loads(array_match.group())
                else:
                    logger.warning(f"No JSON array found in response: {response_text[:100]}")
                    return []
            if isinstance(parsed, list):
                candidates = []
                for item in parsed:
                    if isinstance(item, dict) and item.get('statement'):
                        from ..constants import Derivation
                        _deriv = item.get('derivation')
                        if not Derivation.is_valid(_deriv or ''):
                            _deriv = Derivation.EXTRACTED.value
                        candidates.append(CandidateClaim(
                            statement=item.get('statement'),
                            claim_type=item.get('claim_type', 'fact'),
                            context_domain=item.get('context_domain', 'personal'),
                            confidence=float(item.get('confidence', 0.8)),
                            valid_from=item.get('valid_from'),
                            valid_to=item.get('valid_to'),
                            tags=item.get('tags', []) if isinstance(item.get('tags'), list) else [],
                            derivation=_deriv,
                        ))
                return candidates
            return []
        except Exception as e:
            logger.error(f"Claim extraction failed: {e}")
            return []
    
    def _find_existing_matches(self, candidate: CandidateClaim) -> List[Tuple[Claim, str]]:
        """Search for existing claims that match the candidate."""
        result = self.api.search(candidate.statement, k=5)
        if not result.success or not result.data:
            return []
        
        matches = []
        for search_result in result.data:
            claim = search_result.claim
            if search_result.score > 0.9:
                matches.append((claim, "duplicate"))
            elif search_result.score > 0.7:
                matches.append((claim, "related"))
        
        # D1 follow-up: upgrade close matches that the new claim actually
        # contradicts/replaces to a "contradicts" relation, so the planner can
        # propose a supersede rather than a parallel conflicting claim.
        matches = self._detect_contradictions(candidate, matches)
        return matches

    def _detect_contradictions(self, candidate: "CandidateClaim",
                               matches: List[Tuple[Claim, str]]) -> List[Tuple[Claim, str]]:
        """
        Re-classify close matches that the candidate contradicts/replaces.

        For each matched existing claim (capped to the top few to bound LLM
        cost), ask the LLM whether the candidate updates/replaces it; if so, mark
        the relation as "contradicts". Gated by config
        ``distiller_detect_contradictions`` and LLM availability — a no-op
        otherwise, preserving the prior duplicate/related behavior.
        """
        if not matches:
            return matches
        if not getattr(self.config, "distiller_detect_contradictions", True):
            return matches
        llm = getattr(self.api, "llm", None)
        if llm is None:
            return matches

        upgraded = []
        # Only check the top matches (already similarity-ranked by search).
        check_cap = 3
        for idx, (claim, rel) in enumerate(matches):
            if idx < check_cap:
                try:
                    if llm.detect_contradiction(candidate.statement, claim.statement):
                        upgraded.append((claim, "contradicts"))
                        continue
                except Exception as e:
                    logger.warning(f"Contradiction detection failed: {e}")
            upgraded.append((claim, rel))
        return upgraded
    
    def _propose_actions(self, candidates: List[CandidateClaim],
                         matches: List[Tuple[CandidateClaim, Claim, str]]) -> List[ProposedAction]:
        """Determine actions for each candidate."""
        actions = []
        # Map a duplicate candidate's statement -> the existing claim it
        # duplicates, so we can reinforce that specific claim (H3).
        duplicate_of: Dict[str, Claim] = {}
        # Map a contradicting candidate's statement -> the existing claim it
        # replaces, so we can propose a supersede (D1 follow-up).
        contradicts_of: Dict[str, Claim] = {}
        for cand, claim, rel in matches:
            if rel == "contradicts" and cand.statement not in contradicts_of:
                contradicts_of[cand.statement] = claim
            elif rel == "duplicate" and cand.statement not in duplicate_of:
                duplicate_of[cand.statement] = claim

        for candidate in candidates:
            contradicted = contradicts_of.get(candidate.statement)
            existing = duplicate_of.get(candidate.statement)
            if contradicted is not None:
                # D1 follow-up: the new claim replaces a conflicting existing
                # one. Propose a user-confirmed supersede: save the new claim and
                # link it as superseding (retiring) the old one.
                actions.append(ProposedAction(
                    action="supersede", candidate=candidate,
                    existing_claim=contradicted, relation="contradicts",
                    reason=f"Updates/replaces existing claim {contradicted.claim_id[:8]} "
                           f"(\"{contradicted.statement[:40]}\")"))
            elif existing is not None:
                # H3 distiller hook: an extracted restatement of an existing
                # claim is a reinforcement signal, not a silent skip. Propose a
                # user-confirmable "reinforce" action carrying the matched claim.
                actions.append(ProposedAction(
                    action="reinforce", candidate=candidate,
                    existing_claim=existing, relation="duplicate",
                    reason=f"Restates existing claim {existing.claim_id[:8]} — reinforce it"))
            else:
                related = [(c, r) for c, cl, r in matches if c.statement == candidate.statement and r == "related"]
                if related:
                    actions.append(ProposedAction(action="add", candidate=candidate,
                                                 reason="New but related to existing claims"))
                else:
                    actions.append(ProposedAction(action="add", candidate=candidate,
                                                 reason="New fact to remember"))

        return [a for a in actions if a.action != "skip"]
    
    def _generate_confirmation_prompt(self, actions: List[ProposedAction]) -> str:
        """Generate user-facing confirmation prompt."""
        if not actions:
            return "No new facts to add."
        
        lines = ["I found these facts to remember:\n"]
        for i, action in enumerate(actions):
            lines.append(f"{i+1}. [{action.candidate.claim_type}] {action.candidate.statement}")
            lines.append(f"   ({action.reason})")
        
        lines.append("\nReply with numbers to save (e.g., '1,2') or 'all' to save all, 'none' to skip.")
        return "\n".join(lines)
    
    def _parse_approval_response(self, response: str, total: int) -> List[int]:
        """Parse user response to determine approved actions."""
        response = response.lower().strip()
        
        if response in ["all", "yes", "y", "save all"]:
            return list(range(total))
        if response in ["none", "no", "n", "skip"]:
            return []
        
        indices = []
        for part in response.replace(",", " ").split():
            try:
                idx = int(part) - 1
                if 0 <= idx < total:
                    indices.append(idx)
            except ValueError:
                continue
        
        return indices
    
    def _execute_action(self, action: ProposedAction) -> ActionResult:
        """Execute a single proposed action."""
        if action.action == "add":
            kwargs = {
                "statement": action.candidate.statement,
                "claim_type": action.candidate.claim_type,
                "context_domain": action.candidate.context_domain,
                "auto_extract": True,
                "tags": action.candidate.tags or [],
                "channel": "chat",
                "derivation": getattr(action.candidate, "derivation", "extracted"),
            }
            if action.candidate.valid_from:
                kwargs["valid_from"] = action.candidate.valid_from
            if action.candidate.valid_to:
                kwargs["valid_to"] = action.candidate.valid_to
            # E1/E2: stamp provenance so the saved claim can answer
            # "why do I know this?" and is tagged source:conversation.
            if getattr(self, "_source_conversation_id", None):
                kwargs["source_conversation_id"] = self._source_conversation_id
            if getattr(self, "_source_message_id", None):
                kwargs["source_message_id"] = self._source_message_id
            return self.api.add_claim(**kwargs)
        elif action.action == "update" and action.existing_claim:
            return self.api.edit_claim(
                action.existing_claim.claim_id,
                statement=action.candidate.statement
            )
        elif action.action == "supersede" and action.existing_claim:
            # D1 follow-up: save the new claim AND link it as superseding the
            # contradicted existing claim (add_claim's `supersedes` handling
            # creates the claim_link and retires the old claim).
            kwargs = {
                "statement": action.candidate.statement,
                "claim_type": action.candidate.claim_type,
                "context_domain": action.candidate.context_domain,
                "auto_extract": True,
                "tags": action.candidate.tags or [],
                "supersedes": action.existing_claim.claim_id,
                "channel": "chat",
                "derivation": getattr(action.candidate, "derivation", "extracted"),
            }
            if action.candidate.valid_from:
                kwargs["valid_from"] = action.candidate.valid_from
            if action.candidate.valid_to:
                kwargs["valid_to"] = action.candidate.valid_to
            if getattr(self, "_source_conversation_id", None):
                kwargs["source_conversation_id"] = self._source_conversation_id
            if getattr(self, "_source_message_id", None):
                kwargs["source_message_id"] = self._source_message_id
            return self.api.add_claim(**kwargs)
        elif action.action == "reinforce" and action.existing_claim:
            # H3: user confirmed a restatement -> reinforce the existing claim.
            return self.api.reinforce_claim(action.existing_claim.claim_id)
        elif action.action == "retract" and action.existing_claim:
            return self.api.delete_claim(action.existing_claim.claim_id)
        
        return ActionResult(success=False, action=action.action, object_type="claim",
                           errors=[f"Unknown action: {action.action}"])
