"""
Agentic Natural Language processor for PKB operations.

Accepts natural language commands and performs multi-step CRUD operations
on claims, entities, tags, and contexts using an internal LLM reasoning loop.

Architecture: Structured JSON output (not native tool-calling API) for
maximum model compatibility across OpenRouter providers.

Exposed as:
- MCP tool: pkb_nl_command
- LLM tool: pkb_nl_command
- REST endpoint: POST /pkb/nl_command
"""

import json
import re
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class PKBToolResult:
    """Result from executing a single internal PKB tool."""

    success: bool
    data: Any = None
    error: str = ""

    def to_observation(self) -> str:
        """Format as observation string for the LLM context."""
        if not self.success:
            return f"ERROR: {self.error}"
        return json.dumps(self.data, default=str)[:4000]


@dataclass
class NLCommandResult:
    """Result of a complete NL command processing run."""

    success: bool
    message: str
    actions_taken: List[Dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    needs_user_input: bool = False
    proposed_claims: List[Dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# System prompt template - inject today_date and current_year at runtime
PKB_AGENT_SYSTEM_PROMPT = """You are a Personal Knowledge Base (PKB) assistant. You manage a user's memories, facts, preferences, decisions, tasks, reminders, and observations.

Today's date: {today_date}
Current year: {current_year}

## Instructions
You MUST respond with ONLY a JSON object — no extra text, no markdown, no explanation outside the JSON. Choose ONE action per response.

## Available Actions

### Data Actions
- **search_claims**: Search the knowledge base. HIGH RECALL IS CRITICAL — always use multiple queries with synonyms, alternative phrasings, and cross-domain terms to avoid missing relevant memories. For example, if the user asks about "exercise", also search for "fitness", "gym", "workout", "health", "running". If searching for "food preferences", also try "diet", "eating", "nutrition", "meal", "cooking". Use a higher k (20-30) for broad queries. When results seem sparse, issue additional search_claims calls with rephrased queries before concluding.
  Input: {{"query": str, "k": int (default 20), "filters": {{"claim_type": str, "context_domain": str}} (optional)}}
- **add_claim**: Add a new memory/fact/preference/task/reminder.
  Input: {{"statement": str, "claim_type": str, "context_domain": str, "tags": [str] (optional), "entities": [{{"name": str, "type": str}}] (optional), "valid_from": "YYYY-MM-DD" (optional), "valid_to": "YYYY-MM-DD" (required for task/reminder), "confidence": float (optional)}}
- **edit_claim**: Edit existing claim fields. Input: {{"claim_id": str, "statement": str (optional), "tags": [str] (optional)}}
- **delete_claim**: Soft-delete a claim. Input: {{"claim_id": str}}
- **get_claim**: Get a claim by ID. Input: {{"claim_id": str}}
- **pin_claim**: Pin/unpin a claim. Input: {{"claim_id": str, "pin": bool}}
- **resolve_reference**: Resolve @reference. Input: {{"reference_id": str}}

### Metadata Actions
- **add_entity**: Create entity. Input: {{"name": str, "entity_type": "person|place|org|topic|project|system|other"}}
- **add_tag**: Create tag. Input: {{"name": str}}
- **list_tags**: List all tags. Input: {{}}
- **list_entities**: List all entities. Input: {{}}

### Completion
- **final_response**: Return your answer to the user. Input: {{"message": str}}
- **ask_clarification**: Ask the user for more details before proceeding. Input: {{"question": str}}
  Use this when the command is ambiguous or missing key details (e.g. missing date for a reminder, unclear which claim to edit).

## Conversation Context
You may receive conversation context alongside the command. This context is provided for reference only — focus on the explicit command. The context helps you understand pronouns, recent topics, and implicit references the user might make.

## Claim Types
fact, memory, decision, preference, task, reminder, habit, observation

## Context Domains
personal, health, relationships, learning, life_ops, work, finance

## Date Extraction Rules
- "next Monday" → compute the actual date from today
- "on July 20th" → {current_year}-07-20 (use next year if date has already passed this year)
- "in 3 days" → compute from today
- "tomorrow" → compute from today
- Reminders: MUST set valid_to to the reminder date
- Tasks: set valid_from to today, valid_to to deadline if given
- task and reminder claims REQUIRE valid_to — always extract or infer a date for these types

## Search Strategy for High Recall
- ALWAYS search with synonyms and alternative phrasings — the knowledge base uses semantic similarity, not exact match, but different phrasings still yield different results.
- For any retrieval query, issue at least 2-3 search_claims calls with varied queries: original phrasing, synonyms, broader terms, and related domain terms.
- Example: user asks "what do I like to eat?" → search "food preferences", then "dietary habits", then "favorite meals cooking nutrition".
- Example: user asks "my work tasks" → search "work tasks", then "project deadlines assignments", then "professional todos".
- Use k=20 or higher for broad queries where completeness matters.
- When first search returns few results, try broader or alternative terms before giving up.
- Combine results from multiple searches and deduplicate by claim_id before presenting to user.
- Cross-domain searching helps: "health" memories might be stored under personal, health, or life_ops domains.

## Multi-Step Operations
For "delete all claims about X": first search_claims with multiple phrasings (synonyms, related terms), then delete_claim for each, then final_response.
For "update my preference about X to Y": first search_claims with varied queries to find it, then edit_claim, then final_response.
For queries like "what are my reminders": search_claims with claim_type filter AND also try without filter using broader terms, then final_response with a comprehensive summary.

## Response Format
ALWAYS respond with ONLY a JSON object:
{{"thought": "your reasoning", "action": "action_name", "action_input": {{...}}}}
"""


class PKBNLAgent:
    """
    Agentic NL processor for PKB operations.

    Uses a structured JSON output loop (not native tool-calling) to perform
    multi-step PKB operations from natural language commands.

    Args:
        api: StructuredAPI instance (already user-scoped via .for_user()).
        keys: API keys dict with OPENROUTER_API_KEY.
        model: OpenRouter model name. Defaults to openai/gpt-4o-mini.
    """

    MAX_ITERATIONS = 5
    PROCESS_TIMEOUT = 30  # seconds

    def __init__(self, api, keys: dict, model: str = None):
        self.api = api
        self.keys = keys
        self.model = model or "openai/gpt-4o-mini"

        # Simple dispatch table — maps action names to handler methods
        self._tools: Dict[str, Any] = {
            "search_claims": self._tool_search,
            "add_claim": self._tool_add_claim,
            "edit_claim": self._tool_edit_claim,
            "delete_claim": self._tool_delete_claim,
            "get_claim": self._tool_get_claim,
            "pin_claim": self._tool_pin_claim,
            "resolve_reference": self._tool_resolve_reference,
            "add_entity": self._tool_add_entity,
            "add_tag": self._tool_add_tag,
            "list_tags": self._tool_list_tags,
            "list_entities": self._tool_list_entities,
        }

    # -----------------------------------------------------------------
    # Internal tool handlers (thin wrappers around StructuredAPI)
    # -----------------------------------------------------------------

    def _tool_search(self, params: dict) -> PKBToolResult:
        filters = {}
        if params.get("filters"):
            filters = params["filters"]
        elif params.get("claim_type"):
            filters = {"claim_type": params["claim_type"]}
        result = self.api.search(
            query=params.get("query", ""),
            k=params.get("k", 20),
            filters=filters if filters else None,
        )
        if not result.success:
            return PKBToolResult(False, error="; ".join(result.errors))
        claims = []
        for sr in result.data or []:
            c = sr.claim if hasattr(sr, "claim") else sr
            claim_dict = c.to_dict() if hasattr(c, "to_dict") else {"statement": str(c)}
            claims.append(
                {
                    "claim_id": claim_dict.get("claim_id", ""),
                    "statement": claim_dict.get("statement", ""),
                    "claim_type": claim_dict.get("claim_type", ""),
                    "context_domain": claim_dict.get("context_domain", ""),
                    "status": claim_dict.get("status", ""),
                    "valid_to": claim_dict.get("valid_to", ""),
                    "score": round(getattr(sr, "score", 0.0), 3),
                }
            )
        return PKBToolResult(True, data={"count": len(claims), "claims": claims})

    def _tool_add_claim(self, params: dict) -> PKBToolResult:
        kwargs = {}
        for key in (
            "statement",
            "claim_type",
            "context_domain",
            "tags",
            "entities",
            "valid_from",
            "valid_to",
            "confidence",
        ):
            if params.get(key) is not None:
                kwargs[key] = params[key]
        result = self.api.add_claim(**kwargs)
        if not result.success:
            return PKBToolResult(False, error="; ".join(result.errors))
        return PKBToolResult(
            True,
            data={
                "claim_id": result.object_id,
                "message": "Claim added successfully",
                "warnings": result.warnings or [],
            },
        )

    def _tool_edit_claim(self, params: dict) -> PKBToolResult:
        params = dict(params)  # copy to avoid mutating LLM-provided dict
        claim_id = params.pop("claim_id", "")
        if not claim_id:
            return PKBToolResult(False, error="claim_id is required")
        result = self.api.edit_claim(claim_id=claim_id, **params)
        if not result.success:
            return PKBToolResult(False, error="; ".join(result.errors))
        return PKBToolResult(
            True, data={"claim_id": claim_id, "message": "Claim updated"}
        )

    def _tool_delete_claim(self, params: dict) -> PKBToolResult:
        claim_id = params.get("claim_id", "")
        if not claim_id:
            return PKBToolResult(False, error="claim_id is required")
        result = self.api.delete_claim(claim_id=claim_id)
        if not result.success:
            return PKBToolResult(False, error="; ".join(result.errors))
        return PKBToolResult(
            True, data={"claim_id": claim_id, "message": "Claim deleted"}
        )

    def _tool_get_claim(self, params: dict) -> PKBToolResult:
        claim_id = params.get("claim_id", "")
        if not claim_id:
            return PKBToolResult(False, error="claim_id is required")
        result = self.api.get_claim(claim_id=claim_id)
        if not result.success:
            return PKBToolResult(False, error="; ".join(result.errors))
        claim = result.data
        claim_dict = (
            claim.to_dict() if hasattr(claim, "to_dict") else {"claim_id": claim_id}
        )
        return PKBToolResult(True, data=claim_dict)

    def _tool_pin_claim(self, params: dict) -> PKBToolResult:
        claim_id = params.get("claim_id", "")
        pin = params.get("pin", True)
        result = self.api.pin_claim(claim_id=claim_id, pin=pin)
        if not result.success:
            return PKBToolResult(False, error="; ".join(result.errors))
        return PKBToolResult(True, data={"claim_id": claim_id, "pinned": pin})

    def _tool_resolve_reference(self, params: dict) -> PKBToolResult:
        ref = params.get("reference_id", "").lstrip("@")
        if not ref:
            return PKBToolResult(False, error="reference_id is required")
        result = self.api.resolve_reference(reference_id=ref)
        if not result.success:
            return PKBToolResult(False, error="; ".join(result.errors))
        data = result.data
        if hasattr(data, "to_dict"):
            data = data.to_dict()
        return PKBToolResult(True, data=data)

    def _tool_add_entity(self, params: dict) -> PKBToolResult:
        name = params.get("name", "")
        entity_type = params.get("entity_type", "other")
        if not name:
            return PKBToolResult(False, error="name is required")
        result = self.api.add_entity(name=name, entity_type=entity_type)
        if not result.success:
            return PKBToolResult(False, error="; ".join(result.errors))
        return PKBToolResult(True, data={"entity_id": result.object_id, "name": name})

    def _tool_add_tag(self, params: dict) -> PKBToolResult:
        name = params.get("name", "")
        if not name:
            return PKBToolResult(False, error="name is required")
        result = self.api.add_tag(name=name)
        if not result.success:
            return PKBToolResult(False, error="; ".join(result.errors))
        return PKBToolResult(True, data={"tag_id": result.object_id, "name": name})

    def _tool_list_tags(self, params: dict) -> PKBToolResult:
        try:
            tags = self.api.tags.list(limit=100, order_by="name")
            tag_list = [{"tag_id": t.tag_id, "name": t.name} for t in tags]
            return PKBToolResult(True, data=tag_list)
        except Exception as e:
            return PKBToolResult(False, error=str(e))

    def _tool_list_entities(self, params: dict) -> PKBToolResult:
        try:
            entities = self.api.entities.list(limit=100, order_by="name")
            entity_list = [
                {"entity_id": e.entity_id, "name": e.name, "type": e.entity_type}
                for e in entities
            ]
            return PKBToolResult(True, data=entity_list)
        except Exception as e:
            return PKBToolResult(False, error=str(e))

    # -----------------------------------------------------------------
    # JSON parsing with fallback chain
    # -----------------------------------------------------------------

    def _parse_agent_response(self, response: str) -> Optional[dict]:
        """Extract JSON from LLM response, tolerating markdown fences."""
        text = response.strip()

        # Tier 1: Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Tier 2: Extract from ```json ... ``` blocks
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Tier 3: Find any JSON object (outermost braces)
        match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None

    # -----------------------------------------------------------------
    # Summarize actions taken for timeout/cap responses
    # -----------------------------------------------------------------

    def _summarize_actions(self, actions_taken: list) -> str:
        if not actions_taken:
            return ""
        parts = []
        for a in actions_taken:
            status = "\u2713" if a.get("success") else "\u2717"
            parts.append(f"{status} {a['action']}")
        return "Actions: " + ", ".join(parts)

    def _extract_proposals_from_context(self, messages: list, action_input: dict) -> List[Dict]:
        """Extract proposed claims from the conversation context when the NL agent
        wants clarification before committing any claims.

        Tries to infer what claims the user might want from:
        1. The action_input of the ask_clarification action (may have hints)
        2. The user's original command text
        """
        # Try to extract from the original user message (second message = user command)
        user_text = ""
        for msg in messages:
            if msg.get("role") == "user" and not msg.get("content", "").startswith("Observation:"):
                user_text = msg["content"]
                break

        if not user_text:
            return []

        # Return a single proposal with the user's text as-is
        # The user can refine it in the modal
        return [{
            "text": user_text[:500],
            "claim_type": "note",
            "valid_from": None,
            "valid_to": None,
            "tags": [],
            "entities": [],
            "context": "",
        }]

    # -----------------------------------------------------------------
    # Main processing loop
    # -----------------------------------------------------------------

    def process(self, user_text: str, context: dict = None) -> NLCommandResult:
        """
        Process a natural language command against the PKB.

        Runs an iterative LLM loop where the model decides which PKB
        operations to perform, executes them, and returns a natural
        language summary.

        Args:
            user_text: The natural language command from the user.
            context: Optional additional context dict.

        Returns:
            NLCommandResult with response message and audit trail.
        """
        from code_common.call_llm import call_llm

        today = date.today()
        system_prompt = PKB_AGENT_SYSTEM_PROMPT.format(
            today_date=today.isoformat(),
            current_year=today.year,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]

        actions_taken = []
        start_time = time.time()

        for iteration in range(self.MAX_ITERATIONS):
            # Check timeout
            if time.time() - start_time > self.PROCESS_TIMEOUT:
                return NLCommandResult(
                    success=True,
                    message="I ran out of time. "
                    + self._summarize_actions(actions_taken),
                    actions_taken=actions_taken,
                    warnings=["Processing timeout reached"],
                )

            # Call LLM (non-streaming for agent loop)
            try:
                response = call_llm(
                    keys=self.keys,
                    model_name=self.model,
                    messages=messages,
                    temperature=0.0,
                    stream=False,
                )
            except Exception as e:
                logger.exception("NL agent LLM call failed: %s", e)
                return NLCommandResult(
                    success=False,
                    message="I encountered an error processing your request.",
                    actions_taken=actions_taken,
                    errors=[str(e)],
                )

            # Parse JSON from response
            parsed = self._parse_agent_response(response)
            if parsed is None:
                logger.warning(
                    "NL agent: failed to parse JSON from response: %s", response[:200]
                )
                # Give the LLM one chance to correct
                messages.append({"role": "assistant", "content": response})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your response was not valid JSON. You MUST respond with ONLY a JSON object: "
                            '{"thought": "...", "action": "...", "action_input": {...}}'
                        ),
                    }
                )
                continue

            action = parsed.get("action", "")
            action_input = parsed.get("action_input", {})

            # Terminal action: final_response
            if action == "final_response":
                msg = action_input.get("message", "Done.")
                return NLCommandResult(
                    success=True,
                    message=msg,
                    actions_taken=actions_taken,
                )

            # Terminal action: ask_clarification — agent needs more info from user
            if action == "ask_clarification":
                question = action_input.get("question", "Could you please provide more details?")
                # Check if we've already taken add_claim actions — if so,
                # this is a post-add clarification where the user should review
                # the proposed claims in a modal.
                add_actions = [a for a in actions_taken if a.get("action") == "add_claim" and a.get("success")]
                if add_actions:
                    # Convert committed claims into proposals for user review
                    proposed = []
                    for a in add_actions:
                        inp = a.get("input", {})
                        proposed.append({
                            "text": inp.get("statement", ""),
                            "claim_type": inp.get("claim_type", "note"),
                            "valid_from": inp.get("valid_from"),
                            "valid_to": inp.get("valid_to"),
                            "tags": inp.get("tags", []),
                            "entities": [e.get("name", "") for e in inp.get("entities", [])] if isinstance(inp.get("entities"), list) else [],
                            "context": inp.get("context_domain", ""),
                        })
                    return NLCommandResult(
                        success=True,
                        message=f"\u2753 {question}",
                        actions_taken=actions_taken,
                        needs_user_input=True,
                        proposed_claims=proposed,
                    )
                else:
                    # No claims added yet — agent is uncertain before doing anything.
                    # Build proposals from any search results or context clues
                    # and return interactive result.
                    return NLCommandResult(
                        success=True,
                        message=f"\u2753 {question}",
                        actions_taken=actions_taken,
                        needs_user_input=True,
                        proposed_claims=self._extract_proposals_from_context(messages, action_input),
                        warnings=["Clarification requested — review proposed memories"],
                    )

            # Unknown action — tell LLM to retry
            if action not in self._tools:
                messages.append({"role": "assistant", "content": response})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Unknown action '{action}'. Available actions: "
                            f"{list(self._tools.keys())} or 'final_response' or 'ask_clarification'."
                        ),
                    }
                )
                continue

            # Execute tool
            try:
                tool_result = self._tools[action](action_input)
            except Exception as e:
                logger.exception("NL agent tool execution error: %s", e)
                tool_result = PKBToolResult(False, error=str(e))

            actions_taken.append(
                {
                    "action": action,
                    "input": action_input,
                    "success": tool_result.success,
                }
            )

            # Feed observation back to LLM
            messages.append({"role": "assistant", "content": response})
            messages.append(
                {
                    "role": "user",
                    "content": f"Observation: {tool_result.to_observation()}",
                }
            )

        # Max iterations reached — force a summary response
        return NLCommandResult(
            success=True,
            message="I completed the operations I could. "
            + self._summarize_actions(actions_taken),
            actions_taken=actions_taken,
            warnings=["Maximum iterations reached"],
        )

    # -----------------------------------------------------------------
    # Streaming processing loop
    # -----------------------------------------------------------------

    def process_streaming(self, user_text: str, context: dict = None):
        """
        Streaming version of process() — yields events as the agent works.

        Same logic as process() but yields intermediate events so callers
        can stream progress to the user in real-time.

        Args:
            user_text: The natural language command from the user.
            context: Optional additional context dict.

        Yields:
            dict: Event dicts with a 'type' field. Types:
                - 'thinking': Agent is reasoning (thought text from LLM)
                - 'action_start': About to execute a tool action
                - 'action_result': Tool execution completed
                - 'parse_error': LLM returned non-JSON, retrying
                - 'final_response': Terminal response from agent
                - 'ask_clarification': Agent needs user input
                - 'timeout': Processing timed out
                - 'error': An error occurred
                - 'max_iterations': Hit iteration cap
        """
        from code_common.call_llm import call_llm

        today = date.today()
        system_prompt = PKB_AGENT_SYSTEM_PROMPT.format(
            today_date=today.isoformat(),
            current_year=today.year,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]

        actions_taken = []
        start_time = time.time()

        for iteration in range(self.MAX_ITERATIONS):
            # Check timeout
            if time.time() - start_time > self.PROCESS_TIMEOUT:
                result = NLCommandResult(
                    success=True,
                    message="I ran out of time. "
                    + self._summarize_actions(actions_taken),
                    actions_taken=actions_taken,
                    warnings=["Processing timeout reached"],
                )
                yield {"type": "timeout", "result": result}
                return

            # Call LLM (non-streaming for agent loop — responses are JSON actions)
            yield {
                "type": "llm_call_start",
                "iteration": iteration,
                "message": f"Thinking... (step {iteration + 1})",
            }
            try:
                response = call_llm(
                    keys=self.keys,
                    model_name=self.model,
                    messages=messages,
                    temperature=0.0,
                    stream=False,
                )
            except Exception as e:
                logger.exception("NL agent LLM call failed: %s", e)
                result = NLCommandResult(
                    success=False,
                    message="I encountered an error processing your request.",
                    actions_taken=actions_taken,
                    errors=[str(e)],
                )
                yield {"type": "error", "result": result, "error": str(e)}
                return

            # Parse JSON from response
            parsed = self._parse_agent_response(response)
            if parsed is None:
                logger.warning(
                    "NL agent: failed to parse JSON from response: %s", response[:200]
                )
                yield {
                    "type": "parse_error",
                    "iteration": iteration,
                    "message": "Retrying — LLM response was not valid JSON.",
                }
                # Give the LLM one chance to correct
                messages.append({"role": "assistant", "content": response})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your response was not valid JSON. You MUST respond with ONLY a JSON object: "
                            '{"thought": "...", "action": "...", "action_input": {...}}'
                        ),
                    }
                )
                continue

            action = parsed.get("action", "")
            action_input = parsed.get("action_input", {})
            thought = parsed.get("thought", "")

            # Yield the agent's reasoning
            if thought:
                yield {
                    "type": "thinking",
                    "iteration": iteration,
                    "thought": thought,
                    "action": action,
                }

            # Terminal action: final_response
            if action == "final_response":
                msg = action_input.get("message", "Done.")
                result = NLCommandResult(
                    success=True,
                    message=msg,
                    actions_taken=actions_taken,
                )
                yield {"type": "final_response", "result": result}
                return

            # Terminal action: ask_clarification
            if action == "ask_clarification":
                question = action_input.get("question", "Could you please provide more details?")
                add_actions = [a for a in actions_taken if a.get("action") == "add_claim" and a.get("success")]
                if add_actions:
                    proposed = []
                    for a in add_actions:
                        inp = a.get("input", {})
                        proposed.append({
                            "text": inp.get("statement", ""),
                            "claim_type": inp.get("claim_type", "note"),
                            "valid_from": inp.get("valid_from"),
                            "valid_to": inp.get("valid_to"),
                            "tags": inp.get("tags", []),
                            "entities": [e.get("name", "") for e in inp.get("entities", [])] if isinstance(inp.get("entities"), list) else [],
                            "context": inp.get("context_domain", ""),
                        })
                    result = NLCommandResult(
                        success=True,
                        message=f"\u2753 {question}",
                        actions_taken=actions_taken,
                        needs_user_input=True,
                        proposed_claims=proposed,
                    )
                else:
                    result = NLCommandResult(
                        success=True,
                        message=f"\u2753 {question}",
                        actions_taken=actions_taken,
                        needs_user_input=True,
                        proposed_claims=self._extract_proposals_from_context(messages, action_input),
                        warnings=["Clarification requested \u2014 review proposed memories"],
                    )
                yield {"type": "ask_clarification", "result": result}
                return

            # Unknown action — tell LLM to retry
            if action not in self._tools:
                yield {
                    "type": "unknown_action",
                    "iteration": iteration,
                    "action": action,
                    "message": f"Unknown action '{action}', retrying.",
                }
                messages.append({"role": "assistant", "content": response})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Unknown action '{action}'. Available actions: "
                            f"{list(self._tools.keys())} or 'final_response' or 'ask_clarification'."
                        ),
                    }
                )
                continue

            # Execute tool — yield start event
            yield {
                "type": "action_start",
                "iteration": iteration,
                "action": action,
                "action_input": action_input,
            }

            try:
                tool_result = self._tools[action](action_input)
            except Exception as e:
                logger.exception("NL agent tool execution error: %s", e)
                tool_result = PKBToolResult(False, error=str(e))

            actions_taken.append(
                {
                    "action": action,
                    "input": action_input,
                    "success": tool_result.success,
                }
            )

            # Yield action result event
            yield {
                "type": "action_result",
                "iteration": iteration,
                "action": action,
                "success": tool_result.success,
                "data": tool_result.data,
                "error": tool_result.error,
            }

            # Feed observation back to LLM
            messages.append({"role": "assistant", "content": response})
            messages.append(
                {
                    "role": "user",
                    "content": f"Observation: {tool_result.to_observation()}",
                }
            )

        # Max iterations reached
        result = NLCommandResult(
            success=True,
            message="I completed the operations I could. "
            + self._summarize_actions(actions_taken),
            actions_taken=actions_taken,
            warnings=["Maximum iterations reached"],
        )
        yield {"type": "max_iterations", "result": result}
