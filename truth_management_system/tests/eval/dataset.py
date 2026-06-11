"""
Dataset model + loader for the PKB eval harness.

A dataset is a set of *keyed* claims (seeded into a throwaway PKB) plus a list
of query cases whose ``expected`` lists reference those keys. Keys are mapped
to the auto-generated ``claim_id`` values at seed time by the runner, so the
dataset stays stable regardless of how IDs are generated.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class EvalClaim:
    """
    A claim to seed, identified by a stable ``key`` within the dataset.

    Optional lifecycle fields let a dataset express conflict/recency/expiry/
    confidence scenarios. They are applied by the runner after ``Claim.create``
    and before insert:
      - ``status``: ClaimStatus value (default 'active'). Use 'superseded' /
        'historical' to verify they are excluded from default search.
      - ``confidence``: 0..1 (for confidence-weighted ranking, Workstream C).
      - ``created_at`` / ``updated_at``: ISO timestamps OR a relative shorthand
        like ``"-400d"`` / ``"-2h"`` (resolved to now-delta at seed time) to
        build recency pairs.
      - ``valid_to``: ISO/relative end of validity; a past value + the runner's
        expiry sweep marks the claim 'expired'.
      - ``pinned``: stored in meta_json (Workstream C/H pin override).
      - ``meta``: extra meta_json keys.
      - ``entities``: names of entities to create and link to this claim
        (role 'subject'); enables the entity-linked retrieval cases (W-C).
      - ``tags``: names of tags to create and link to this claim; enables the
        tag-linked retrieval cases (W-D). Flat names (no hierarchy needed).
    """
    key: str
    statement: str
    claim_type: str
    context_domain: str
    status: Optional[str] = None
    confidence: Optional[float] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    valid_to: Optional[str] = None
    pinned: bool = False
    meta: Optional[dict] = None
    entities: Optional[List[str]] = None
    tags: Optional[List[str]] = None


@dataclass
class EvalCase:
    """
    A query and the set of claim keys that *should* be retrieved for it.

    Optional fields:
      - ``category``: signal bucket (lexical/semantic/multi/temporal/recency/
        conflict/hard_negative/scoped/lifecycle).
      - ``not_expected``: keys that should NOT rank in the top-k (hard
        negatives / superseded / expired); used for diagnostics.
      - ``filters``: per-case search filters, e.g.
        ``{"context_domains": ["work"], "claim_types": ["task"]}`` — exercises
        SearchFilters scoping.
    """
    query: str
    expected: List[str]
    category: str = "lexical"
    not_expected: List[str] = field(default_factory=list)
    filters: Optional[dict] = None
    notes: Optional[str] = None


@dataclass
class EvalDataset:
    """A named collection of keyed claims and query cases."""
    name: str
    claims: List[EvalClaim]
    cases: List[EvalCase]
    description: str = ""

    def claim_keys(self) -> List[str]:
        return [c.key for c in self.claims]

    def validate(self) -> None:
        """Raise ValueError if any case references an unknown claim key."""
        known = set(self.claim_keys())
        if len(known) != len(self.claims):
            raise ValueError(f"Dataset '{self.name}' has duplicate claim keys")
        for i, case in enumerate(self.cases):
            unknown = [k for k in (case.expected + case.not_expected) if k not in known]
            if unknown:
                raise ValueError(
                    f"Dataset '{self.name}' case #{i} ({case.query!r}) "
                    f"references unknown claim keys: {unknown}"
                )


def default_dataset_path() -> str:
    """Absolute path to the bundled seed dataset JSON."""
    return os.path.join(os.path.dirname(__file__), "seed_dataset.json")


def load_dataset(path: Optional[str] = None) -> EvalDataset:
    """
    Load and validate an EvalDataset from JSON (defaults to the seed dataset).
    """
    path = path or default_dataset_path()
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    claims = [
        EvalClaim(
            key=c["key"],
            statement=c["statement"],
            claim_type=c["claim_type"],
            context_domain=c["context_domain"],
            status=c.get("status"),
            confidence=c.get("confidence"),
            created_at=c.get("created_at"),
            updated_at=c.get("updated_at"),
            valid_to=c.get("valid_to"),
            pinned=c.get("pinned", False),
            meta=c.get("meta"),
            entities=c.get("entities"),
            tags=c.get("tags"),
        )
        for c in raw.get("claims", [])
    ]
    cases = [
        EvalCase(
            query=c["query"],
            expected=list(c.get("expected", [])),
            category=c.get("category", "lexical"),
            not_expected=list(c.get("not_expected", [])),
            filters=c.get("filters"),
            notes=c.get("notes"),
        )
        for c in raw.get("cases", [])
    ]
    dataset = EvalDataset(
        name=raw.get("name", os.path.basename(path)),
        claims=claims,
        cases=cases,
        description=raw.get("description", ""),
    )
    dataset.validate()
    return dataset
