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


@dataclass
class DistillationResult:
    """Result of distillation execution."""
    plan: MemoryUpdatePlan
    executed: bool = False
    execution_results: List[ActionResult] = field(default_factory=list)


class ConversationDistiller:
    """Extract and manage claims from chat conversations."""
    
    def __init__(self, api: StructuredAPI, keys: Dict[str, str], config: PKBConfig = None):
        self.api = api
        self.keys = keys
        self.config = config or PKBConfig()
    
    def extract_and_propose(self, conversation_summary: str, user_message: str, 
                            assistant_message: str) -> MemoryUpdatePlan:
        """Extract claims from conversation and propose updates."""
        candidates = self._extract_claims_from_turn(conversation_summary, user_message, assistant_message)
        
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
                               requires_user_confirmation=len(proposed_actions) > 0)
    
    def execute_plan(self, plan: MemoryUpdatePlan, user_response: str,
                     approved_indices: List[int] = None) -> DistillationResult:
        """Execute approved actions from the plan."""
        if not plan.proposed_actions:
            return DistillationResult(plan=plan, executed=False)
        
        if approved_indices is None:
            approved_indices = self._parse_approval_response(user_response, len(plan.proposed_actions))
        
        results = []
        for i in approved_indices:
            if 0 <= i < len(plan.proposed_actions):
                result = self._execute_action(plan.proposed_actions[i])
                results.append(result)
        
        return DistillationResult(plan=plan, executed=True, execution_results=results)
    
    def _extract_claims_from_turn(self, conversation_summary: str, user_message: str,
                                   assistant_message: str) -> List[CandidateClaim]:
        """Use LLM to extract memorable claims from conversation."""
        try:
            from code_common.call_llm import call_llm
        except ImportError:
            return []
        
        prompt = f"""Extract memorable personal facts from this conversation that should be remembered.

User message: {user_message}
Assistant response: {assistant_message}

Your task: Extract facts about the USER (not general knowledge) that should be stored in a personal memory system.

Valid claim_type values: fact, preference, decision, task, reminder, habit, memory, observation
Valid context_domain values: personal, health, work, relationships, learning, life_ops, finance

IMPORTANT: Return ONLY a valid JSON array with NO additional text before or after.
Example format:
[{{"statement": "User is vegetarian", "claim_type": "fact", "context_domain": "health", "confidence": 0.9}}]

If no personal facts to remember, return exactly: []

Response:"""
        
        try:
            response = call_llm(self.keys, self.config.llm_model, prompt, temperature=0.0)
            response_text = response.strip()
            
            # Try direct parse first
            try:
                parsed = json.loads(response_text)
            except json.JSONDecodeError:
                # Try to find JSON array in response
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
                        candidates.append(CandidateClaim(
                            statement=item.get('statement'),
                            claim_type=item.get('claim_type', 'fact'),
                            context_domain=item.get('context_domain', 'personal'),
                            confidence=float(item.get('confidence', 0.8))
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
        
        return matches
    
    def _propose_actions(self, candidates: List[CandidateClaim],
                         matches: List[Tuple[CandidateClaim, Claim, str]]) -> List[ProposedAction]:
        """Determine actions for each candidate."""
        actions = []
        matched_candidates = {m[0].statement for m in matches if m[2] == "duplicate"}
        
        for candidate in candidates:
            if candidate.statement in matched_candidates:
                actions.append(ProposedAction(action="skip", candidate=candidate,
                                             reason="Already exists in memory"))
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
            return self.api.add_claim(
                statement=action.candidate.statement,
                claim_type=action.candidate.claim_type,
                context_domain=action.candidate.context_domain,
                auto_extract=True
            )
        elif action.action == "update" and action.existing_claim:
            return self.api.edit_claim(
                action.existing_claim.claim_id,
                statement=action.candidate.statement
            )
        elif action.action == "retract" and action.existing_claim:
            return self.api.delete_claim(action.existing_claim.claim_id)
        
        return ActionResult(success=False, action=action.action, object_type="claim",
                           errors=[f"Unknown action: {action.action}"])
