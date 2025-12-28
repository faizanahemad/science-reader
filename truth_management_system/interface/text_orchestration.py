"""
Text Orchestration for PKB v0.

TextOrchestrator parses natural language commands and routes them
to the appropriate StructuredAPI methods.

Supports commands like:
- "add this fact: I prefer morning workouts"
- "find what I said about mom's health"
- "update my preference about coffee"
- "delete the reminder about dentist"
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from .structured_api import StructuredAPI, ActionResult
from ..config import PKBConfig

logger = logging.getLogger(__name__)


@dataclass
class OrchestrationResult:
    """
    Result of text orchestration.
    
    Attributes:
        action_taken: Description of action taken.
        action_result: ActionResult from StructuredAPI.
        clarifying_questions: Questions to ask user if intent unclear.
        affected_objects: List of affected objects.
        raw_intent: Parsed intent from LLM.
    """
    action_taken: str
    action_result: Optional[ActionResult] = None
    clarifying_questions: List[str] = field(default_factory=list)
    affected_objects: List[Dict] = field(default_factory=list)
    raw_intent: Dict = field(default_factory=dict)


class TextOrchestrator:
    """
    Natural language command parser and router.
    
    Parses user text commands and routes them to the appropriate
    StructuredAPI methods. Uses LLM for intent parsing.
    
    Attributes:
        api: StructuredAPI instance.
        keys: API keys for LLM calls.
        config: PKBConfig with settings.
    """
    
    def __init__(
        self,
        api: StructuredAPI,
        keys: Dict[str, str],
        config: PKBConfig = None
    ):
        """
        Initialize text orchestrator.
        
        Args:
            api: StructuredAPI instance.
            keys: Dict with OPENROUTER_API_KEY.
            config: Optional PKBConfig.
        """
        self.api = api
        self.keys = keys
        self.config = config or PKBConfig()
    
    def process(
        self,
        user_text: str,
        context: Optional[Dict] = None
    ) -> OrchestrationResult:
        """
        Process natural language command.
        
        Args:
            user_text: User's natural language command.
            context: Optional context (previous commands, user info, etc.).
            
        Returns:
            OrchestrationResult with action taken and results.
        """
        context = context or {}
        
        # Parse intent using LLM
        intent = self._parse_intent(user_text, context)
        
        if not intent:
            return OrchestrationResult(
                action_taken="parse_failed",
                clarifying_questions=["I couldn't understand that command. Could you rephrase?"],
                raw_intent={}
            )
        
        # Log the parsed intent
        if self.config.log_llm_calls:
            logger.info(f"Parsed intent: {intent}")
        
        # Route to appropriate action
        return self._route_to_action(intent, user_text)
    
    def _parse_intent(
        self,
        user_text: str,
        context: Dict
    ) -> Optional[Dict]:
        """
        Use LLM to parse user intent.
        
        Args:
            user_text: User's command.
            context: Additional context.
            
        Returns:
            Parsed intent dict or None if failed.
        """
        try:
            from code_common.call_llm import call_llm
        except ImportError:
            logger.error("code_common.call_llm not available")
            return self._fallback_parse(user_text)
        
        prompt = f"""Parse this command for a personal knowledge base system.

Actions:
- add_claim: Add a fact, preference, decision, memory ("remember that...", "I prefer...", "save...")
- search: Find/query claims ("find...", "what do I know about...", "show...")
- edit_claim: Update a claim ("update...", "change...")
- delete_claim: Remove/retract a claim ("delete...", "remove...", "forget...")
- add_note: Add a longer note
- list_conflicts: Show conflicts

Claim types: fact, memory, decision, preference, task, reminder, habit, observation
Context domains: personal, health, relationships, learning, life_ops, work, finance

User command: "{user_text}"

IMPORTANT: Return ONLY valid JSON with NO additional text. Example:
{{"action": "add_claim", "claim_type": "fact", "context_domain": "health", "statement": "I am allergic to shellfish", "confidence": 0.9}}

For search: {{"action": "search", "search_query": "allergies", "confidence": 0.8}}

Response:"""

        try:
            response = call_llm(
                self.keys,
                self.config.llm_model,
                prompt,
                temperature=0.0
            )
            
            # Try to extract JSON from response
            response_text = response.strip()
            
            # Try direct parse first
            try:
                return json.loads(response_text)
            except json.JSONDecodeError:
                pass
            
            # Try to find JSON object in response
            import re
            json_match = re.search(r'\{[^{}]*\}', response_text)
            if json_match:
                return json.loads(json_match.group())
            
            logger.error(f"No valid JSON found in response: {response_text[:100]}")
            return self._fallback_parse(user_text)
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return self._fallback_parse(user_text)
        except Exception as e:
            logger.error(f"Intent parsing failed: {e}")
            return self._fallback_parse(user_text)
    
    def _fallback_parse(self, user_text: str) -> Dict:
        """
        Simple rule-based fallback parser.
        
        Args:
            user_text: User's command.
            
        Returns:
            Basic intent dict.
        """
        text_lower = user_text.lower()
        
        # Simple keyword matching
        if any(w in text_lower for w in ['add', 'remember', 'save', 'store', 'note that']):
            return {
                'action': 'add_claim',
                'claim_type': 'observation',
                'context_domain': 'personal',
                'statement': user_text,
                'confidence': 0.5
            }
        
        if any(w in text_lower for w in ['find', 'search', 'what', 'show', 'list', 'get']):
            return {
                'action': 'search',
                'search_query': user_text,
                'confidence': 0.5
            }
        
        if any(w in text_lower for w in ['delete', 'remove', 'retract']):
            return {
                'action': 'delete_claim',
                'search_query': user_text,
                'requires_search_first': True,
                'confidence': 0.5
            }
        
        if any(w in text_lower for w in ['update', 'change', 'edit', 'modify']):
            return {
                'action': 'edit_claim',
                'search_query': user_text,
                'requires_search_first': True,
                'confidence': 0.5
            }
        
        # Default: treat as a search
        return {
            'action': 'search',
            'search_query': user_text,
            'confidence': 0.3
        }
    
    def _route_to_action(
        self,
        intent: Dict,
        original_text: str
    ) -> OrchestrationResult:
        """
        Route parsed intent to appropriate API method.
        
        Args:
            intent: Parsed intent dict.
            original_text: Original user text.
            
        Returns:
            OrchestrationResult with action results.
        """
        action = intent.get('action', 'unknown')
        
        # Check if clarification needed
        clarification = intent.get('clarification_needed')
        if clarification:
            return OrchestrationResult(
                action_taken="needs_clarification",
                clarifying_questions=[clarification],
                raw_intent=intent
            )
        
        # Route to action
        if action == 'add_claim':
            return self._handle_add_claim(intent)
        
        elif action == 'search':
            return self._handle_search(intent)
        
        elif action == 'edit_claim':
            return self._handle_edit_claim(intent)
        
        elif action == 'delete_claim':
            return self._handle_delete_claim(intent)
        
        elif action == 'add_note':
            return self._handle_add_note(intent)
        
        elif action == 'list_conflicts':
            return self._handle_list_conflicts()
        
        else:
            return OrchestrationResult(
                action_taken="unknown_action",
                clarifying_questions=[
                    "I'm not sure what you want to do. Try:\n"
                    "- 'remember that...' to add a fact\n"
                    "- 'find...' to search\n"
                    "- 'delete...' to remove something"
                ],
                raw_intent=intent
            )
    
    def _handle_add_claim(self, intent: Dict) -> OrchestrationResult:
        """Handle add_claim action."""
        statement = intent.get('statement', '')
        
        if not statement:
            return OrchestrationResult(
                action_taken="needs_statement",
                clarifying_questions=["What would you like me to remember?"],
                raw_intent=intent
            )
        
        result = self.api.add_claim(
            statement=statement,
            claim_type=intent.get('claim_type', 'observation'),
            context_domain=intent.get('context_domain', 'personal'),
            auto_extract=True
        )
        
        return OrchestrationResult(
            action_taken=f"Added {intent.get('claim_type', 'claim')}: {statement[:50]}...",
            action_result=result,
            affected_objects=[{'type': 'claim', 'id': result.object_id}] if result.success else [],
            raw_intent=intent
        )
    
    def _handle_search(self, intent: Dict) -> OrchestrationResult:
        """Handle search action."""
        query = intent.get('search_query', '')
        
        if not query:
            return OrchestrationResult(
                action_taken="needs_query",
                clarifying_questions=["What would you like to search for?"],
                raw_intent=intent
            )
        
        result = self.api.search(query, k=10)
        
        count = len(result.data) if result.success and result.data else 0
        
        return OrchestrationResult(
            action_taken=f"Found {count} results for: {query[:50]}...",
            action_result=result,
            raw_intent=intent
        )
    
    def _handle_edit_claim(self, intent: Dict) -> OrchestrationResult:
        """Handle edit_claim action."""
        # First search for the claim
        query = intent.get('search_query', '')
        
        if not query:
            return OrchestrationResult(
                action_taken="needs_query",
                clarifying_questions=["Which claim would you like to edit?"],
                raw_intent=intent
            )
        
        # Search for claims
        search_result = self.api.search(query, k=5)
        
        if not search_result.success or not search_result.data:
            return OrchestrationResult(
                action_taken="no_claims_found",
                clarifying_questions=["I couldn't find any matching claims. Could you be more specific?"],
                raw_intent=intent
            )
        
        # Return search results for user to choose
        return OrchestrationResult(
            action_taken="found_claims_to_edit",
            action_result=search_result,
            clarifying_questions=["Which claim would you like to edit? Please specify by number or ID."],
            affected_objects=[{'type': 'claim', 'id': r.claim.claim_id} for r in search_result.data],
            raw_intent=intent
        )
    
    def _handle_delete_claim(self, intent: Dict) -> OrchestrationResult:
        """Handle delete_claim action."""
        query = intent.get('search_query', '')
        
        if not query:
            return OrchestrationResult(
                action_taken="needs_query",
                clarifying_questions=["Which claim would you like to delete?"],
                raw_intent=intent
            )
        
        # Search for claims
        search_result = self.api.search(query, k=5)
        
        if not search_result.success or not search_result.data:
            return OrchestrationResult(
                action_taken="no_claims_found",
                clarifying_questions=["I couldn't find any matching claims to delete."],
                raw_intent=intent
            )
        
        # Return search results for user to confirm
        return OrchestrationResult(
            action_taken="found_claims_to_delete",
            action_result=search_result,
            clarifying_questions=["Which claim would you like to delete? Please confirm by ID."],
            affected_objects=[{'type': 'claim', 'id': r.claim.claim_id} for r in search_result.data],
            raw_intent=intent
        )
    
    def _handle_add_note(self, intent: Dict) -> OrchestrationResult:
        """Handle add_note action."""
        body = intent.get('statement', '')
        
        if not body:
            return OrchestrationResult(
                action_taken="needs_content",
                clarifying_questions=["What would you like the note to say?"],
                raw_intent=intent
            )
        
        result = self.api.add_note(
            body=body,
            context_domain=intent.get('context_domain')
        )
        
        return OrchestrationResult(
            action_taken=f"Added note: {body[:50]}...",
            action_result=result,
            affected_objects=[{'type': 'note', 'id': result.object_id}] if result.success else [],
            raw_intent=intent
        )
    
    def _handle_list_conflicts(self) -> OrchestrationResult:
        """Handle list_conflicts action."""
        result = self.api.get_open_conflicts()
        
        count = len(result.data) if result.success and result.data else 0
        
        return OrchestrationResult(
            action_taken=f"Found {count} open conflicts",
            action_result=result,
            raw_intent={'action': 'list_conflicts'}
        )
    
    def execute_confirmed_action(
        self,
        action: str,
        target_id: str,
        **kwargs
    ) -> OrchestrationResult:
        """
        Execute a confirmed action after user selection.
        
        Args:
            action: Action to execute (edit_claim, delete_claim).
            target_id: ID of target object.
            **kwargs: Additional action parameters.
            
        Returns:
            OrchestrationResult with action results.
        """
        if action == 'delete_claim':
            result = self.api.delete_claim(target_id)
            return OrchestrationResult(
                action_taken=f"Deleted claim: {target_id}",
                action_result=result,
                affected_objects=[{'type': 'claim', 'id': target_id}]
            )
        
        elif action == 'edit_claim':
            result = self.api.edit_claim(target_id, **kwargs)
            return OrchestrationResult(
                action_taken=f"Updated claim: {target_id}",
                action_result=result,
                affected_objects=[{'type': 'claim', 'id': target_id}]
            )
        
        else:
            return OrchestrationResult(
                action_taken="unknown_confirmed_action",
                clarifying_questions=[f"Unknown action: {action}"]
            )
