"""
LLM Helper functions for PKB v0.

Provides LLM-powered extraction and analysis:
- generate_tags(): Suggest relevant tags for a claim
- extract_entities(): Extract entities from statement
- extract_spo(): Extract subject/predicate/object structure
- classify_claim_type(): Classify into fact/memory/decision/etc.
- check_similarity(): Find similar existing claims
- batch_extract_all(): Parallel extraction for multiple statements

All functions use code_common/call_llm.py for LLM calls.
"""

import json
import logging
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Any

import numpy as np

from .config import PKBConfig
from .models import Claim
from .constants import ClaimType, EntityType, EntityRole
from .utils import get_parallel_executor

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """
    Result of LLM extraction for a statement.

    Attributes:
        tags: Suggested tags.
        entities: Extracted entities with type and role.
        spo: Subject/predicate/object structure.
        claim_type: Classified claim type.
        keywords: Extracted keywords.
    """

    tags: List[str]
    entities: List[Dict[str, str]]
    spo: Dict[str, Optional[str]]
    claim_type: str
    keywords: List[str]


class LLMHelpers:
    """
    LLM-powered extraction with parallelization support.

    Provides methods for extracting structured information from
    claim statements using LLM calls.

    Attributes:
        keys: API keys for LLM calls.
        config: PKBConfig with settings.
        executor: ParallelExecutor for batch operations.
    """

    def __init__(self, keys: Dict[str, str], config: PKBConfig):
        """
        Initialize LLM helpers.

        Args:
            keys: Dict with OPENROUTER_API_KEY.
            config: PKBConfig with LLM settings.
        """
        self.keys = keys
        self.config = config
        self.executor = get_parallel_executor(config.max_parallel_llm_calls)

    def _call_llm(self, prompt: str, temperature: float = None) -> str:
        """
        Call LLM with error handling.

        Args:
            prompt: Prompt text.
            temperature: Override temperature (default: config value).

        Returns:
            LLM response text.
        """
        try:
            from code_common.call_llm import call_llm
        except ImportError:
            raise ImportError("code_common.call_llm is required")

        return call_llm(
            self.keys,
            self.config.llm_model,
            prompt,
            temperature=temperature or self.config.llm_temperature,
        )

    def generate_tags(
        self, statement: str, context_domain: str, existing_tags: List[str] = None
    ) -> List[str]:
        """
        Use LLM to suggest relevant tags for a claim.

        Args:
            statement: The claim statement.
            context_domain: Life domain for context.
            existing_tags: Tags already in the system (for reuse).

        Returns:
            List of suggested tag names.
        """
        existing_tags = existing_tags or []

        # Also get keywords using the existing function
        try:
            from code_common.call_llm import getKeywordsFromText

            keywords = getKeywordsFromText(statement, self.keys)
        except ImportError:
            keywords = []

        prompt = f"""Suggest 3-5 short tags for this personal knowledge claim.

Tags should be:
- 1-2 words each
- Lowercase, no spaces (use underscores)
- Specific but reusable

Context domain: {context_domain}
Existing tags to reuse if relevant: {existing_tags[:20] if existing_tags else "none"}
Extracted keywords: {keywords[:10] if keywords else "none"}

Claim: "{statement}"

Return JSON array only: ["tag1", "tag2", "tag3"]

Tags:"""

        try:
            response = self._call_llm(prompt)
            tags = json.loads(response.strip())

            if isinstance(tags, list):
                return [str(t).lower().replace(" ", "_") for t in tags[:5]]
            return []

        except Exception as e:
            logger.error(f"Tag generation failed: {e}")
            # Fall back to keywords
            return [k.lower().replace(" ", "_") for k in keywords[:3]]

    def extract_entities(self, statement: str) -> List[Dict[str, str]]:
        """
        Extract entities from a statement.

        Args:
            statement: The claim statement.

        Returns:
            List of dicts with type, name, role.
        """
        entity_types = ", ".join([e.value for e in EntityType])
        entity_roles = ", ".join([e.value for e in EntityRole])

        prompt = f"""Extract entities from this personal knowledge claim.

Entity types: {entity_types}
Entity roles: {entity_roles}

Claim: "{statement}"

Valid entity types: person, org, place, topic, project, system, other
Valid roles: subject, object, mentioned, about_person

IMPORTANT: Return ONLY a valid JSON array with NO additional text. Example:
[{{"type": "person", "name": "Mom", "role": "subject"}}]

If no entities found, return exactly: []

Response:"""

        try:
            response = self._call_llm(prompt)
            response_text = response.strip()

            # Try direct parse first
            try:
                entities = json.loads(response_text)
            except json.JSONDecodeError:
                # Try to find JSON array in response
                import re

                array_match = re.search(r"\[.*\]", response_text, re.DOTALL)
                if array_match:
                    entities = json.loads(array_match.group())
                else:
                    logger.warning(
                        f"No JSON array found in entity response: {response_text[:100]}"
                    )
                    return []

            if isinstance(entities, list):
                return [
                    {
                        "type": e.get("type", "other"),
                        "name": e.get("name", ""),
                        "role": e.get("role", "mentioned"),
                    }
                    for e in entities
                    if isinstance(e, dict) and e.get("name")
                ]
            return []

        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            return []

    def extract_spo(self, statement: str) -> Dict[str, Optional[str]]:
        """
        Extract subject/predicate/object structure from statement.

        Args:
            statement: The claim statement.

        Returns:
            Dict with subject, predicate, object (any can be None).
        """
        prompt = f"""Extract subject-predicate-object structure from this claim.

Claim: "{statement}"

IMPORTANT: Return ONLY valid JSON with NO additional text. Example:
{{"subject": "I", "predicate": "prefer", "object": "morning workouts"}}

If structure is unclear, use null for missing parts.

Response:"""

        try:
            response = self._call_llm(prompt)
            response_text = response.strip()

            # Try direct parse first
            try:
                spo = json.loads(response_text)
            except json.JSONDecodeError:
                # Try to find JSON object in response
                import re

                json_match = re.search(r"\{[^{}]*\}", response_text)
                if json_match:
                    spo = json.loads(json_match.group())
                else:
                    logger.warning(
                        f"No JSON found in SPO response: {response_text[:100]}"
                    )
                    return {"subject": None, "predicate": None, "object": None}

            return {
                "subject": spo.get("subject"),
                "predicate": spo.get("predicate"),
                "object": spo.get("object"),
            }

        except Exception as e:
            logger.error(f"SPO extraction failed: {e}")
            return {"subject": None, "predicate": None, "object": None}

    def classify_claim_type(self, statement: str) -> str:
        """
        Classify claim into one of the defined types.

        Args:
            statement: The claim statement.

        Returns:
            Claim type (fact, memory, decision, etc.).
        """
        claim_types = {
            "fact": 'stable assertions ("My home city is Bengaluru")',
            "memory": 'episodic experiences ("I enjoyed that restaurant")',
            "decision": 'commitments ("I decided to avoid X")',
            "preference": 'likes/dislikes ("I prefer morning workouts")',
            "task": 'actionable items ("Buy medication")',
            "reminder": 'future prompts ("Remind me to call mom Friday")',
            "habit": 'recurring targets ("Sleep by 11pm")',
            "observation": 'low-commitment notes ("Noticed knee pain")',
        }

        types_text = "\n".join([f"- {k}: {v}" for k, v in claim_types.items()])

        prompt = f"""Classify this claim into one type:
{types_text}

Claim: "{statement}"

IMPORTANT: Return ONLY valid JSON with NO additional text. Example: {{"type": "preference"}}

Response:"""

        try:
            response = self._call_llm(prompt)
            response_text = response.strip()

            # Try direct parse first
            try:
                result = json.loads(response_text)
                claim_type = result.get("type", "observation")
            except json.JSONDecodeError:
                # Try to extract JSON from response
                import re

                json_match = re.search(r"\{[^{}]*\}", response_text)
                if json_match:
                    result = json.loads(json_match.group())
                    claim_type = result.get("type", "observation")
                else:
                    # Try to find type keyword directly
                    for t in claim_types.keys():
                        if t.lower() in response_text.lower():
                            claim_type = t
                            break
                    else:
                        claim_type = "observation"

            # Validate type
            if claim_type not in claim_types:
                claim_type = "observation"

            return claim_type

        except Exception as e:
            logger.error(f"Claim type classification failed: {e}")
            return "observation"

    def check_similarity(
        self, new_claim: str, existing_claims: List[Claim], threshold: float = 0.85
    ) -> List[Tuple[Claim, float, str]]:
        """
        Find similar existing claims.

        Uses embedding similarity to find near-duplicates.

        Args:
            new_claim: Statement of new claim.
            existing_claims: Claims to compare against.
            threshold: Minimum similarity to include.

        Returns:
            List of (claim, similarity, relation) tuples.
            Relation: 'duplicate', 'related', 'contradicts'
        """
        if not existing_claims:
            return []

        try:
            from code_common.call_llm import get_query_embedding, get_document_embedding
        except ImportError:
            logger.error("code_common.call_llm not available for similarity check")
            return []

        # Get embedding for new claim
        new_emb = get_query_embedding(new_claim, self.keys)

        results = []
        for claim in existing_claims:
            # Get embedding for existing claim
            claim_emb = get_document_embedding(claim.statement, self.keys)

            # Compute cosine similarity
            dot = np.dot(new_emb, claim_emb)
            norm1 = np.linalg.norm(new_emb)
            norm2 = np.linalg.norm(claim_emb)

            if norm1 > 0 and norm2 > 0:
                sim = float(dot / (norm1 * norm2))

                if sim >= threshold:
                    relation = self._classify_relation(new_claim, claim.statement, sim)
                    results.append((claim, sim, relation))

        # Sort by similarity
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def _classify_relation(
        self, new_claim: str, existing_claim: str, similarity: float
    ) -> str:
        """
        Classify relationship between two claims.

        Args:
            new_claim: New claim statement.
            existing_claim: Existing claim statement.
            similarity: Cosine similarity score.

        Returns:
            Relation type: 'duplicate', 'related', 'contradicts'
        """
        if similarity > 0.95:
            return "duplicate"

        if similarity > 0.85:
            # Check for contradiction using LLM
            prompt = f"""Do these two claims contradict each other?

Claim 1: "{existing_claim}"
Claim 2: "{new_claim}"

Return JSON: {{"contradicts": true/false, "reason": "brief explanation"}}

Result:"""

            try:
                response = self._call_llm(prompt)
                result = json.loads(response.strip())

                if result.get("contradicts", False):
                    return "contradicts"

            except Exception as e:
                logger.error(f"Contradiction check failed: {e}")

        return "related"

    def batch_extract_all(
        self, statements: List[str], context_domain: str = "personal"
    ) -> List[ExtractionResult]:
        """
        Extract all information for multiple statements in parallel.

        Args:
            statements: List of claim statements.
            context_domain: Domain for context.

        Returns:
            List of ExtractionResult objects.
        """

        def extract_one(stmt: str) -> ExtractionResult:
            return ExtractionResult(
                tags=self.generate_tags(stmt, context_domain),
                entities=self.extract_entities(stmt),
                spo=self.extract_spo(stmt),
                claim_type=self.classify_claim_type(stmt),
                keywords=self._get_keywords(stmt),
            )

        return self.executor.map_parallel(extract_one, statements, timeout=120.0)

    def _get_keywords(self, text: str) -> List[str]:
        """Get keywords using call_llm helper."""
        try:
            from code_common.call_llm import getKeywordsFromText

            return getKeywordsFromText(text, self.keys)
        except ImportError:
            return []

    def generate_possible_questions(
        self, statement: str, claim_type: str = "fact"
    ) -> List[str]:
        """
        Generate self-sufficient questions that this claim/memory could answer.

        Given a factual statement, generates 2-4 natural questions a user
        might ask that this memory would be relevant to. This enables
        QnA-style search where a user's question can be matched against
        the possible_questions field for better retrieval.

        IMPORTANT: Each question must be fully self-sufficient — it must contain
        enough specific detail (names, topics, entities) that the question is
        understandable and searchable on its own, without needing to read the
        original claim. This is critical because these questions are stored in
        the FTS index and used for semantic search matching.

        Args:
            statement: The claim statement text.
            claim_type: Type of claim for context.

        Returns:
            List of 2-4 question strings, each self-sufficient.

        Examples:
            "I am allergic to peanuts" ->
            ["Do I have a peanut allergy?", "What are my specific food allergies?",
             "Can I eat peanuts safely?", "Should I avoid peanut-containing foods?"]

            (NOT: "Am I allergic to anything?" — too vague, not self-sufficient)
        """
        prompt = f"""Given this personal memory/fact, generate 2-4 natural questions that a person might ask which this memory would help answer.

Memory ({claim_type}): "{statement}"

Requirements:
- Each question MUST be fully self-sufficient: it must include the specific subjects, names, topics, or entities from the memory so that the question is completely understandable on its own without reading the memory itself.
- BAD example for "I am allergic to peanuts": "Am I allergic to anything?" (too vague, does not mention peanuts)
- GOOD example for "I am allergic to peanuts": "Do I have a peanut allergy?" (self-sufficient, mentions peanuts specifically)
- Questions should be from the perspective of someone asking about themselves or their life
- Questions should be natural and conversational
- Each question should be a different angle or phrasing
- Keep questions concise (under 15 words each)

IMPORTANT: Return ONLY a valid JSON array of strings. Example:
["Do I have a peanut allergy?", "Should I avoid peanut-containing foods?"]

Questions:"""

        try:
            response = self._call_llm(prompt)
            response_text = response.strip()

            import re

            # Try to parse JSON
            try:
                questions = json.loads(response_text)
            except json.JSONDecodeError:
                # Try to find JSON array in response
                array_match = re.search(r"\[.*\]", response_text, re.DOTALL)
                if array_match:
                    questions = json.loads(array_match.group())
                else:
                    return []

            if isinstance(questions, list):
                return [str(q).strip() for q in questions[:4] if q and str(q).strip()]
            return []

        except Exception as e:
            logger.error(f"Question generation failed: {e}")
            return []

    def extract_single(
        self, statement: str, context_domain: str = "personal"
    ) -> ExtractionResult:
        """
        Extract all information for a single statement.

        Args:
            statement: Claim statement.
            context_domain: Domain for context.

        Returns:
            ExtractionResult with all extracted information.
        """
        return ExtractionResult(
            tags=self.generate_tags(statement, context_domain),
            entities=self.extract_entities(statement),
            spo=self.extract_spo(statement),
            claim_type=self.classify_claim_type(statement),
            keywords=self._get_keywords(statement),
        )
