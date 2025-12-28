"""
Text Ingestion for PKB v0.

TextIngestionDistiller parses bulk text into claims, analyzes against existing
memory, and proposes comprehensive actions (add, edit, skip) for user approval.

This module enables:
- Importing memories from text files
- Bulk paste of freeform text with intelligent extraction
- Comparison with existing memories to avoid duplicates
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any

from .structured_api import StructuredAPI, ActionResult
from ..config import PKBConfig
from ..models import Claim
from ..constants import ClaimType, ContextDomain

logger = logging.getLogger(__name__)


@dataclass
class IngestCandidate:
    """
    A candidate claim extracted from text ingestion.
    
    Attributes:
        statement: The extracted claim text.
        claim_type: Type of claim (fact, preference, etc.).
        context_domain: Domain (personal, health, work, etc.).
        confidence: Confidence score from extraction (0.0-1.0).
        line_number: Original line number in input text.
        original_text: Original text fragment before cleaning.
    """
    statement: str
    claim_type: str
    context_domain: str
    confidence: float = 0.8
    line_number: Optional[int] = None
    original_text: Optional[str] = None


@dataclass
class IngestProposal:
    """
    Proposed action for a candidate claim.
    
    Attributes:
        action: Action type ('add', 'edit', 'skip').
        candidate: The candidate claim being processed.
        existing_claim: If editing/skipping, the existing claim.
        similarity_score: Similarity score to existing claim (0.0-1.0).
        reason: Human-readable reason for the proposed action.
        editable: Whether user can edit statement before saving.
    """
    action: str  # 'add', 'edit', 'skip'
    candidate: IngestCandidate
    existing_claim: Optional[Claim] = None
    similarity_score: Optional[float] = None
    reason: str = ""
    editable: bool = True


@dataclass
class TextIngestionPlan:
    """
    Complete plan for text ingestion.
    
    Attributes:
        plan_id: Unique identifier for this plan.
        raw_text: Original input text.
        candidates: List of extracted candidate claims.
        proposals: List of proposed actions for each candidate.
        summary: Human-readable summary of the plan.
        total_lines_parsed: Number of lines/items parsed from input.
        add_count: Number of proposed additions.
        edit_count: Number of proposed edits.
        skip_count: Number of proposed skips.
    """
    plan_id: str = ""
    raw_text: str = ""
    candidates: List[IngestCandidate] = field(default_factory=list)
    proposals: List[IngestProposal] = field(default_factory=list)
    summary: str = ""
    total_lines_parsed: int = 0
    add_count: int = 0
    edit_count: int = 0
    skip_count: int = 0


@dataclass
class IngestExecutionResult:
    """
    Result of executing an ingestion plan.
    
    Attributes:
        plan: The executed plan.
        executed: Whether execution occurred.
        execution_results: Results for each executed action.
        added_count: Number of claims actually added.
        edited_count: Number of claims actually edited.
        failed_count: Number of failed operations.
    """
    plan: TextIngestionPlan
    executed: bool = False
    execution_results: List[ActionResult] = field(default_factory=list)
    added_count: int = 0
    edited_count: int = 0
    failed_count: int = 0


class TextIngestionDistiller:
    """
    Parses bulk text into claims, analyzes against existing memory,
    and proposes comprehensive actions.
    
    This class handles the full workflow:
    1. Parse input text into candidate claims (LLM or rule-based)
    2. Search for existing similar/duplicate claims
    3. Determine appropriate action for each candidate
    4. Generate a plan for user approval
    5. Execute approved actions
    
    Attributes:
        api: StructuredAPI instance for PKB operations.
        keys: API keys dict with OPENROUTER_API_KEY.
        config: PKBConfig with settings.
    """
    
    # Thresholds for similarity matching
    DUPLICATE_THRESHOLD = 0.92  # score > this = exact duplicate, skip
    EDIT_THRESHOLD = 0.75       # score > this = similar, suggest edit
    RELATED_THRESHOLD = 0.55    # score > this = related, add with warning
    
    def __init__(self, api: StructuredAPI, keys: Dict[str, str], config: PKBConfig = None):
        """
        Initialize TextIngestionDistiller.
        
        Args:
            api: StructuredAPI instance (should be user-scoped).
            keys: Dict with OPENROUTER_API_KEY for LLM operations.
            config: Optional PKBConfig with settings.
        """
        self.api = api
        self.keys = keys
        self.config = config or PKBConfig()
    
    def ingest_and_propose(
        self,
        text: str,
        default_claim_type: str = 'fact',
        default_domain: str = 'personal',
        use_llm_parsing: bool = True
    ) -> TextIngestionPlan:
        """
        Main entry point. Parse text, find matches, propose actions.
        
        Args:
            text: Raw text to parse (can be multi-line, bullet points, etc.).
            default_claim_type: Default claim type if not inferred.
            default_domain: Default context domain if not inferred.
            use_llm_parsing: If True, use LLM for intelligent parsing.
                           If False, use simple rule-based parsing.
        
        Returns:
            TextIngestionPlan with candidates and proposed actions.
        """
        import uuid
        plan_id = str(uuid.uuid4())
        
        # Parse text into candidates
        if use_llm_parsing and self.keys.get("OPENROUTER_API_KEY"):
            candidates = self._parse_text_with_llm(text, default_claim_type, default_domain)
        else:
            candidates = self._parse_text_simple(text, default_claim_type, default_domain)
        
        if not candidates:
            return TextIngestionPlan(
                plan_id=plan_id,
                raw_text=text,
                summary="No extractable facts found in the text.",
                total_lines_parsed=text.count('\n') + 1
            )
        
        # Find matches and determine actions for each candidate
        proposals = []
        add_count = 0
        edit_count = 0
        skip_count = 0
        
        for candidate in candidates:
            matches = self._find_matches_for_candidate(candidate)
            proposal = self._determine_action(candidate, matches)
            proposals.append(proposal)
            
            if proposal.action == 'add':
                add_count += 1
            elif proposal.action == 'edit':
                edit_count += 1
            elif proposal.action == 'skip':
                skip_count += 1
        
        # Generate summary
        summary = self._generate_summary(len(candidates), add_count, edit_count, skip_count)
        
        return TextIngestionPlan(
            plan_id=plan_id,
            raw_text=text,
            candidates=candidates,
            proposals=proposals,
            summary=summary,
            total_lines_parsed=text.count('\n') + 1,
            add_count=add_count,
            edit_count=edit_count,
            skip_count=skip_count
        )
    
    def execute_plan(
        self,
        plan: TextIngestionPlan,
        approved_proposals: List[Dict]
    ) -> IngestExecutionResult:
        """
        Execute approved proposals from the plan.
        
        Args:
            plan: The TextIngestionPlan to execute.
            approved_proposals: List of approved proposals with potential edits.
                Each dict should have:
                - index: Index in plan.proposals
                - statement (optional): Edited statement
                - claim_type (optional): Edited claim type
                - context_domain (optional): Edited context domain
        
        Returns:
            IngestExecutionResult with execution status and results.
        """
        if not plan.proposals:
            return IngestExecutionResult(plan=plan, executed=False)
        
        results = []
        added_count = 0
        edited_count = 0
        failed_count = 0
        
        for approved in approved_proposals:
            idx = approved.get('index')
            if idx is None or idx < 0 or idx >= len(plan.proposals):
                continue
            
            proposal = plan.proposals[idx]
            
            # Apply any edits from user
            statement = approved.get('statement', proposal.candidate.statement)
            claim_type = approved.get('claim_type', proposal.candidate.claim_type)
            context_domain = approved.get('context_domain', proposal.candidate.context_domain)
            
            result = self._execute_proposal(proposal, statement, claim_type, context_domain)
            results.append(result)
            
            if result.success:
                if proposal.action == 'add':
                    added_count += 1
                elif proposal.action == 'edit':
                    edited_count += 1
            else:
                failed_count += 1
        
        return IngestExecutionResult(
            plan=plan,
            executed=True,
            execution_results=results,
            added_count=added_count,
            edited_count=edited_count,
            failed_count=failed_count
        )
    
    def _parse_text_with_llm(
        self,
        text: str,
        default_type: str,
        default_domain: str
    ) -> List[IngestCandidate]:
        """
        Use LLM to intelligently parse freeform text into structured claims.
        
        The LLM will:
        - Split compound sentences into individual facts
        - Infer claim types and domains from content
        - Clean and normalize statements
        - Filter out non-memorable content
        """
        try:
            from code_common.call_llm import call_llm
        except ImportError:
            logger.warning("call_llm not available, falling back to simple parsing")
            return self._parse_text_simple(text, default_type, default_domain)
        
        # Truncate very long text to avoid token limits
        max_chars = 15000
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... (truncated)"
        
        prompt = f"""Parse this text and extract individual personal facts/memories that should be stored.

INPUT TEXT:
{text}

TASK:
1. Split into individual, atomic facts (one idea per item)
2. Clean up formatting, fix grammar if needed
3. Infer the appropriate claim_type and context_domain for each
4. Assign a confidence score (0.0-1.0) based on clarity

CLAIM TYPES: fact, preference, decision, task, reminder, habit, memory, observation
CONTEXT DOMAINS: personal, health, work, relationships, learning, life_ops, finance

DEFAULT claim_type if unsure: {default_type}
DEFAULT context_domain if unsure: {default_domain}

IMPORTANT: Return ONLY a valid JSON array with NO additional text.
Example format:
[
  {{"statement": "I prefer working in the morning", "claim_type": "preference", "context_domain": "work", "confidence": 0.9, "line_hint": 1}},
  {{"statement": "I am allergic to peanuts", "claim_type": "fact", "context_domain": "health", "confidence": 0.95, "line_hint": 3}}
]

If no extractable facts, return exactly: []

Response:"""
        
        try:
            response = call_llm(self.keys, self.config.llm_model, prompt, temperature=0.0)
            response_text = response.strip()
            
            # Parse JSON response
            try:
                parsed = json.loads(response_text)
            except json.JSONDecodeError:
                # Try to find JSON array in response
                array_match = re.search(r'\[.*\]', response_text, re.DOTALL)
                if array_match:
                    parsed = json.loads(array_match.group())
                else:
                    logger.warning(f"No JSON array found in LLM response, falling back to simple parsing")
                    return self._parse_text_simple(text, default_type, default_domain)
            
            if not isinstance(parsed, list):
                return self._parse_text_simple(text, default_type, default_domain)
            
            candidates = []
            for item in parsed:
                if isinstance(item, dict) and item.get('statement'):
                    statement = item.get('statement', '').strip()
                    if len(statement) < 3:
                        continue
                    
                    candidates.append(IngestCandidate(
                        statement=statement,
                        claim_type=item.get('claim_type', default_type),
                        context_domain=item.get('context_domain', default_domain),
                        confidence=float(item.get('confidence', 0.8)),
                        line_number=item.get('line_hint'),
                        original_text=statement
                    ))
            
            return candidates
            
        except Exception as e:
            logger.error(f"LLM parsing failed: {e}, falling back to simple parsing")
            return self._parse_text_simple(text, default_type, default_domain)
    
    def _parse_text_simple(
        self,
        text: str,
        default_type: str,
        default_domain: str
    ) -> List[IngestCandidate]:
        """
        Rule-based parsing similar to migrate_user_details.py.
        
        Handles:
        - Line-by-line splitting
        - Bullet point removal
        - Numbered list handling
        - Basic type/domain inference from keywords
        """
        if not text or not text.strip():
            return []
        
        candidates = []
        lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        
        for line_num, line in enumerate(lines, 1):
            # Clean up the line
            line = line.strip()
            
            # Skip empty lines and common headers
            if not line:
                continue
            if line.lower() in ['user memory:', 'user preferences:', 'facts:', 'preferences:', 
                               'memories:', 'notes:', '---', '***']:
                continue
            
            original_text = line
            
            # Remove bullet points and numbering
            for prefix in ['- ', '* ', '• ', '· ', '→ ', '> ']:
                if line.startswith(prefix):
                    line = line[len(prefix):].strip()
                    break
            
            # Remove numbered lists (1. 2. 1) 2) etc.)
            numbered_match = re.match(r'^(\d+)[\.\)\-:]\s*', line)
            if numbered_match:
                line = line[numbered_match.end():].strip()
            
            # Skip if too short after cleaning
            if len(line) < 5:
                continue
            
            # Skip obvious headers or section titles
            if line.endswith(':') and len(line) < 50:
                continue
            
            # Infer claim type from keywords
            claim_type = self._infer_claim_type(line, default_type)
            
            # Infer domain from keywords
            domain = self._infer_domain(line, default_domain)
            
            candidates.append(IngestCandidate(
                statement=line,
                claim_type=claim_type,
                context_domain=domain,
                confidence=0.7,  # Lower confidence for rule-based
                line_number=line_num,
                original_text=original_text
            ))
        
        return candidates
    
    def _infer_claim_type(self, text: str, default: str) -> str:
        """Infer claim type from keywords in text."""
        lower = text.lower()
        
        if any(kw in lower for kw in ['prefer', 'like', 'want', 'love', 'enjoy', 'favorite', 'hate', 'dislike']):
            return 'preference'
        elif any(kw in lower for kw in ['decided', 'will', 'going to', 'plan to', 'chose', 'selected']):
            return 'decision'
        elif any(kw in lower for kw in ['remember', 'remind', "don't forget", 'appointment', 'deadline']):
            return 'reminder'
        elif any(kw in lower for kw in ['habit', 'usually', 'always', 'every day', 'every week', 'routine']):
            return 'habit'
        elif any(kw in lower for kw in ['task', 'todo', 'need to', 'should', 'must', 'have to']):
            return 'task'
        elif any(kw in lower for kw in ['noticed', 'observed', 'seems', 'appears', 'realized']):
            return 'observation'
        elif any(kw in lower for kw in ['remember when', 'back in', 'years ago', 'used to']):
            return 'memory'
        
        return default
    
    def _infer_domain(self, text: str, default: str) -> str:
        """Infer context domain from keywords in text."""
        lower = text.lower()
        
        if any(kw in lower for kw in ['health', 'workout', 'exercise', 'diet', 'sleep', 'medical', 
                                       'doctor', 'gym', 'fitness', 'weight', 'allergy', 'allergic']):
            return 'health'
        elif any(kw in lower for kw in ['work', 'job', 'career', 'office', 'meeting', 'project', 
                                        'colleague', 'boss', 'client', 'deadline', 'salary']):
            return 'work'
        elif any(kw in lower for kw in ['family', 'friend', 'relationship', 'partner', 'spouse', 
                                        'kid', 'parent', 'wife', 'husband', 'dating', 'marriage']):
            return 'relationships'
        elif any(kw in lower for kw in ['learn', 'study', 'course', 'book', 'read', 'education',
                                        'class', 'skill', 'tutorial', 'practice']):
            return 'learning'
        elif any(kw in lower for kw in ['money', 'finance', 'budget', 'invest', 'save', 'expense', 
                                        'income', 'bank', 'stock', 'crypto', 'debt']):
            return 'finance'
        elif any(kw in lower for kw in ['schedule', 'routine', 'organize', 'plan', 'calendar',
                                        'appointment', 'chore', 'errand', 'household']):
            return 'life_ops'
        
        return default
    
    def _find_matches_for_candidate(self, candidate: IngestCandidate) -> List[Tuple[Claim, float]]:
        """
        Search for existing claims that match or conflict with the candidate.
        
        Returns:
            List of (claim, similarity_score) tuples, sorted by score descending.
        """
        result = self.api.search(candidate.statement, k=5)
        if not result.success or not result.data:
            return []
        
        matches = []
        for search_result in result.data:
            if hasattr(search_result, 'score') and hasattr(search_result, 'claim'):
                matches.append((search_result.claim, search_result.score))
        
        # Sort by score descending
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches
    
    def _determine_action(
        self,
        candidate: IngestCandidate,
        matches: List[Tuple[Claim, float]]
    ) -> IngestProposal:
        """
        Determine what action to take for a candidate based on existing matches.
        
        Decision logic:
        - score > 0.92: skip (exact duplicate)
        - score > 0.75: edit (update existing claim)
        - score > 0.55: add with warning (related exists)
        - score <= 0.55: add (new)
        """
        if not matches:
            return IngestProposal(
                action='add',
                candidate=candidate,
                reason="New fact to add"
            )
        
        best_match, best_score = matches[0]
        
        if best_score > self.DUPLICATE_THRESHOLD:
            return IngestProposal(
                action='skip',
                candidate=candidate,
                existing_claim=best_match,
                similarity_score=best_score,
                reason=f"Duplicate of existing memory (similarity: {best_score:.0%})"
            )
        elif best_score > self.EDIT_THRESHOLD:
            return IngestProposal(
                action='edit',
                candidate=candidate,
                existing_claim=best_match,
                similarity_score=best_score,
                reason=f"Similar to existing memory - will update (similarity: {best_score:.0%})"
            )
        elif best_score > self.RELATED_THRESHOLD:
            return IngestProposal(
                action='add',
                candidate=candidate,
                existing_claim=best_match,
                similarity_score=best_score,
                reason=f"New fact (related memory exists with {best_score:.0%} similarity)"
            )
        else:
            return IngestProposal(
                action='add',
                candidate=candidate,
                reason="New fact to add"
            )
    
    def _generate_summary(
        self,
        total: int,
        add_count: int,
        edit_count: int,
        skip_count: int
    ) -> str:
        """Generate a human-readable summary of the plan."""
        parts = []
        parts.append(f"Extracted {total} memories from text.")
        
        if add_count > 0:
            parts.append(f"{add_count} new to add.")
        if edit_count > 0:
            parts.append(f"{edit_count} existing to update.")
        if skip_count > 0:
            parts.append(f"{skip_count} duplicates skipped.")
        
        return " ".join(parts)
    
    def _execute_proposal(
        self,
        proposal: IngestProposal,
        statement: str,
        claim_type: str,
        context_domain: str
    ) -> ActionResult:
        """Execute a single proposal."""
        if proposal.action == 'add':
            return self.api.add_claim(
                statement=statement,
                claim_type=claim_type,
                context_domain=context_domain,
                auto_extract=True,
                meta_json=json.dumps({"source": "text_ingestion"})
            )
        elif proposal.action == 'edit' and proposal.existing_claim:
            return self.api.edit_claim(
                proposal.existing_claim.claim_id,
                statement=statement,
                claim_type=claim_type,
                context_domain=context_domain
            )
        elif proposal.action == 'skip':
            # Skip actions don't need execution, return success
            return ActionResult(
                success=True,
                action='skip',
                object_type='claim',
                object_id=proposal.existing_claim.claim_id if proposal.existing_claim else None,
                data=proposal.existing_claim
            )
        
        return ActionResult(
            success=False,
            action=proposal.action,
            object_type='claim',
            errors=[f"Unknown action: {proposal.action}"]
        )
