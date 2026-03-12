"""
PKB Natural Language Conversation Agent.

Wraps the PKB NL agent (truth_management_system/interface/nl_agent.py)
as a Conversation.reply-compatible agent, enabling /pkb and /memory slash
commands to route through the normal conversation streaming pipeline while
bypassing heavy context modules (web search, preamble enhancers, document
reading).

The agent:
- Receives the full prompt (with short conversation history + summary)
- Extracts or uses the pre-set NL command text
- Calls PKBNLAgent.process_streaming() for multi-step PKB operations
- Streams intermediate status events (thinking, tool actions, results) in real-time
- Yields the final NL response as streaming text

Triggered by: /pkb <text> or /memory <text> slash commands
Agent field name: PKBNLConversationAgent
"""

import logging
import time
from typing import Optional

from agents.base_agent import Agent
from loggers import getLoggers

logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(
    __name__, logging.WARNING, logging.INFO, logging.ERROR, logging.INFO
)


class PKBNLConversationAgent(Agent):
    """
    Conversation-compatible wrapper for PKB NL operations.

    Integrates with the existing agent dispatch in Conversation.reply
    (get_preamble → agent dispatch → streaming yield).

    Attributes:
        model_name: LLM model for the inner NL agent.
        user_email: User email for PKB scoping.
        nl_command_text: The extracted NL command (set before __call__).
        detail_level: Response detail level (unused, for interface compat).
        timeout: Max execution time in seconds.
    """

    def __init__(
        self,
        keys: dict,
        model_name: str = "openai/gpt-4o-mini",
        user_email: str = "",
        detail_level: int = 1,
        timeout: int = 60,
    ):
        super().__init__(keys)
        self.model_name = model_name
        self.user_email = user_email
        self.detail_level = detail_level
        self.timeout = timeout

        # Set by Conversation.reply before __call__ — the raw NL command text
        # from checkboxes["pkb_nl_command"], e.g. "add a reminder to buy gift on July 20th"
        self.nl_command_text: Optional[str] = None

        # Set by Conversation.reply before __call__ — callable to wait for
        # user tool responses (for interactive pkb_propose_memory modal).
        # Signature: tool_response_waiter(tool_id: str, timeout: int) -> dict | None
        self.tool_response_waiter = None

    def __call__(
        self,
        text,
        images=None,
        temperature=0.7,
        stream=False,
        max_tokens=None,
        system=None,
        web_search=False,
    ):
        """
        Execute the PKB NL agent and yield streaming text.

        Parameters
        ----------
        text : str
            The assembled prompt from Conversation.reply (includes query,
            summary, short history).  Used as conversation context.
        images : list
            Unused — PKB operations don't need images.
        temperature : float
            Unused — inner agent uses temperature=0.0.
        stream : bool
            Should always be True from Conversation.reply dispatch.
        max_tokens : int | None
            Unused.
        system : str | None
            System preamble from get_preamble (minimal for PKB agent).
        web_search : bool
            Unused.

        Yields
        ------
        str
            Text chunks for streaming to the UI.
        """
        if images is None:
            images = []

        st = time.time()

        # Determine the NL command: prefer pre-set nl_command_text, fall back
        # to extracting from the prompt text.
        nl_command = self.nl_command_text or ""
        if not nl_command.strip():
            # Fallback: use the full prompt text (shouldn't happen if
            # reply() sets nl_command_text properly).
            nl_command = text.strip()
            logger.warning(
                "[PKBNLConversationAgent] nl_command_text not set, using full prompt text (%d chars)",
                len(nl_command),
            )

        if not nl_command.strip():
            yield "No command text provided for /pkb or /memory. Please type a command after the slash, e.g. `/pkb what are my reminders?`"
            return

        yield "Processing your memory command...\n\n"

        # Build conversation context from the prompt text for the NL agent
        # (gives the inner agent awareness of recent conversation history).
        conversation_context = self._extract_conversation_context(text)

        # Action descriptions for user-facing status messages
        ACTION_LABELS = {
            "search_claims": ("🔍", "Searching memories"),
            "add_claim": ("➕", "Adding memory"),
            "edit_claim": ("✏️", "Editing memory"),
            "delete_claim": ("🗑️", "Deleting memory"),
            "get_claim": ("📋", "Retrieving memory"),
            "pin_claim": ("📌", "Pinning memory"),
            "resolve_reference": ("🔗", "Resolving reference"),
            "add_entity": ("👤", "Adding entity"),
            "add_tag": ("🏷️", "Adding tag"),
            "list_tags": ("🏷️", "Listing tags"),
            "list_entities": ("👤", "Listing entities"),
        }

        result = None  # Will hold the final NLCommandResult
        try:
            for event in self._run_nl_agent_streaming(nl_command, conversation_context):
                etype = event.get("type", "")

                if etype == "llm_call_start":
                    # Agent is making an LLM call (thinking step)
                    iteration = event.get("iteration", 0)
                    if iteration > 0:
                        yield f"\n\n---\n\n"

                elif etype == "thinking":
                    thought = event.get("thought", "")
                    action = event.get("action", "")
                    if thought:
                        yield f"💭 *{thought}*\n\n"

                elif etype == "action_start":
                    action = event.get("action", "")
                    action_input = event.get("action_input", {})
                    icon, label = ACTION_LABELS.get(action, ("⚙️", action))
                    # Build a concise description of the action
                    detail = ""
                    if action == "search_claims":
                        query = action_input.get("query", "")
                        detail = f' for "{query}"' if query else ""
                    elif action == "add_claim":
                        stmt = action_input.get("statement", "")
                        detail = f': {stmt[:80]}' if stmt else ""
                    elif action in ("edit_claim", "delete_claim", "get_claim", "pin_claim"):
                        cid = action_input.get("claim_id", "")
                        detail = f' (claim {cid[:12]})' if cid else ""
                    yield f"{icon} {label}{detail}...\n"

                elif etype == "action_result":
                    action = event.get("action", "")
                    success = event.get("success", False)
                    data = event.get("data")
                    error = event.get("error", "")
                    if success:
                        # Concise success summary
                        if action == "search_claims" and isinstance(data, dict):
                            count = data.get("count", 0)
                            yield f"  ✅ Found {count} result{'s' if count != 1 else ''}\n"
                        elif action == "add_claim" and isinstance(data, dict):
                            yield f"  ✅ Added (ID: {data.get('claim_id', '?')[:12]})\n"
                        elif action == "delete_claim":
                            yield f"  ✅ Deleted\n"
                        elif action == "edit_claim":
                            yield f"  ✅ Updated\n"
                        else:
                            yield f"  ✅ Done\n"
                    else:
                        yield f"  ❌ Failed: {error[:100]}\n"

                elif etype == "parse_error":
                    yield f"⚠️ {event.get('message', 'Parse error, retrying...')}\n"

                elif etype == "unknown_action":
                    yield f"⚠️ {event.get('message', 'Unknown action, retrying...')}\n"

                elif etype in ("final_response", "timeout", "max_iterations"):
                    result = event.get("result")
                    break

                elif etype == "ask_clarification":
                    result = event.get("result")
                    break

                elif etype == "error":
                    result = event.get("result")
                    break

        except Exception as e:
            logger.exception("[PKBNLConversationAgent] NL agent streaming error: %s", e)
            yield f"\n\n**Error:** {str(e)}"
            return

        if result is None:
            yield "\n\nNo response received from memory agent."
            return

        elapsed = time.time() - st
        time_logger.info(
            "[PKBNLConversationAgent] completed in %.2fs | success=%s | actions=%d | needs_input=%s",
            elapsed,
            result.success,
            len(result.actions_taken),
            result.needs_user_input,
        )

        # Handle interactive clarification: NL agent is uncertain and wants user review
        if result.needs_user_input and result.proposed_claims and self.tool_response_waiter:
            import uuid
            tool_id = f"pkb_propose_{uuid.uuid4().hex[:8]}"

            # Yield the question/message text first
            yield "\n\n" + result.message
            yield "\n\n"

            # Yield tool_input_request event — the streaming loop (line 10398-10405
            # in Conversation.py) passes dicts with type='tool_input_request' through
            # directly to the frontend, which shows the modal.
            yield {
                "type": "tool_input_request",
                "text": "",
                "status": "Waiting for your review of proposed memories",
                "tool_id": tool_id,
                "tool_name": "pkb_propose_memory",
                "ui_schema": {
                    "claims": result.proposed_claims,
                    "message": result.message,
                },
            }

            # Wait for user response from the modal
            user_response = self.tool_response_waiter(tool_id, timeout=120)

            if user_response and not user_response.get("skipped"):
                # User confirmed/edited claims — add them to PKB
                confirmed_claims = user_response.get("claims", [])
                if confirmed_claims:
                    yield "\n\nSaving confirmed memories...\n\n"
                    yield from self._add_confirmed_claims(confirmed_claims)
                else:
                    yield "\n\nNo memories confirmed."
            elif user_response and user_response.get("skipped"):
                yield "\n\nMemory proposal skipped."
            else:
                yield "\n\n⚠️ No response received (timed out). Memories were not saved."
            return

        # Standard path: yield the final response message
        if result.message:
            yield "\n\n" + result.message

        # Yield warnings if any
        if result.warnings:
            yield "\n\n" + "\n".join(f"⚠️ {w}" for w in result.warnings)

    def _run_nl_agent_streaming(self, nl_command: str, conversation_context: str):
        """
        Instantiate the PKB NL agent and run it in streaming mode.

        Yields event dicts from PKBNLAgent.process_streaming().
        If PKB is unavailable, yields a single error event.
        """
        from truth_management_system.interface.nl_agent import PKBNLAgent, NLCommandResult
        from endpoints.pkb import get_pkb_api_for_user

        api = get_pkb_api_for_user(self.user_email, keys=self.keys)
        if api is None:
            yield {
                "type": "error",
                "result": NLCommandResult(
                    success=False,
                    message="Unable to access your personal knowledge base. PKB may not be available.",
                    errors=["get_pkb_api_for_user returned None"],
                ),
                "error": "PKB not available",
            }
            return

        agent = PKBNLAgent(api=api, keys=self.keys, model=self.model_name)

        # Build the command text with conversation context if available
        if conversation_context:
            enriched_command = (
                f"{nl_command}\n\n"
                f"[Conversation context for reference \u2014 use only if relevant to the command above]\n"
                f"{conversation_context}"
            )
        else:
            enriched_command = nl_command

        yield from agent.process_streaming(enriched_command)


    def _add_confirmed_claims(self, claims: list):
        """
        Add user-confirmed claims to PKB and yield status per claim.

        Parameters
        ----------
        claims : list
            List of claim dicts from the modal: {text, claim_type, valid_from, valid_to, tags, entities, context}

        Yields
        ------
        str
            Status messages for each claim added.
        """
        from endpoints.pkb import get_pkb_api_for_user

        api = get_pkb_api_for_user(self.user_email, keys=self.keys)
        if api is None:
            yield "❌ Unable to access PKB to save memories."
            return

        for i, claim in enumerate(claims):
            text = (claim.get("text") or "").strip()
            if not text:
                continue

            try:
                kwargs = {
                    "statement": text,
                    "claim_type": claim.get("claim_type", "note"),
                }
                if claim.get("valid_from"):
                    kwargs["valid_from"] = claim["valid_from"]
                if claim.get("valid_to"):
                    kwargs["valid_to"] = claim["valid_to"]
                if claim.get("tags"):
                    kwargs["tags"] = claim["tags"]
                if claim.get("entities"):
                    kwargs["entities"] = [
                        {"name": e, "type": "topic"} if isinstance(e, str) else e
                        for e in claim["entities"]
                    ]
                if claim.get("context"):
                    kwargs["context_domain"] = claim["context"]

                result = api.add_claim(**kwargs)
                if result.success:
                    yield f"✅ Saved: {text[:80]}{'...' if len(text) > 80 else ''}\n"
                else:
                    errors = '; '.join(result.errors) if result.errors else 'Unknown error'
                    yield f"❌ Failed to save: {text[:60]}... — {errors}\n"
            except Exception as e:
                logger.exception("[PKBNLConversationAgent] Failed to add claim: %s", e)
                yield f"❌ Error saving: {text[:60]}... — {str(e)}\n"

    @staticmethod
    def _extract_conversation_context(prompt_text: str) -> str:
        """
        Extract conversation history/summary from the assembled prompt.

        The prompt template (prompts.chat_slow_reply_prompt) embeds
        previous_messages and summary_text.  We extract a compact version
        for passing as context to the NL agent.

        Returns empty string if no useful context is found.
        """
        # Simple extraction: look for known section markers in the prompt.
        # The prompt is formatted by chat_slow_reply_prompt which uses
        # {summary_text}, {previous_messages}, {query} placeholders.
        # We don't need the full prompt — just the conversation context parts.
        context_parts = []

        # Try to find conversation summary
        for marker in ["<conversation_summary>", "<summary>", "Conversation Summary:"]:
            if marker in prompt_text:
                start = prompt_text.index(marker)
                # Take up to 2000 chars from the marker
                snippet = prompt_text[start : start + 2000]
                context_parts.append(snippet.strip())
                break

        # Try to find previous messages
        for marker in [
            "<previous_messages>",
            "<conversation_history>",
            "Previous Messages:",
        ]:
            if marker in prompt_text:
                start = prompt_text.index(marker)
                snippet = prompt_text[start : start + 3000]
                context_parts.append(snippet.strip())
                break

        if not context_parts:
            return ""

        return "\n\n".join(context_parts)[:4000]  # Cap total context
