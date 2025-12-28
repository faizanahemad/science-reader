"""
Interface layer for PKB v0.

Provides high-level APIs for interacting with the knowledge base:
- StructuredAPI: Programmatic CRUD + search API
- TextOrchestrator: Natural language command parsing
- ConversationDistiller: Extract facts from chat conversations
- TextIngestionDistiller: Bulk text parsing and memory ingestion

Usage:
    from truth_management_system.interface import StructuredAPI, TextOrchestrator
    
    api = StructuredAPI(db, keys, config)
    result = api.add_claim(statement="I prefer morning workouts", claim_type="preference", context_domain="health")
    
    orchestrator = TextOrchestrator(api, keys)
    result = orchestrator.process("remember that I like coffee")
    
    # Bulk text ingestion
    from truth_management_system.interface import TextIngestionDistiller
    distiller = TextIngestionDistiller(api, keys)
    plan = distiller.ingest_and_propose("My notes...", use_llm_parsing=True)
"""

from .structured_api import StructuredAPI, ActionResult
from .text_orchestration import TextOrchestrator, OrchestrationResult
from .conversation_distillation import ConversationDistiller, MemoryUpdatePlan, DistillationResult, CandidateClaim
from .text_ingestion import (
    TextIngestionDistiller,
    TextIngestionPlan,
    IngestCandidate,
    IngestProposal,
    IngestExecutionResult,
)

__all__ = [
    'StructuredAPI',
    'ActionResult',
    'TextOrchestrator',
    'OrchestrationResult',
    'ConversationDistiller',
    'MemoryUpdatePlan',
    'DistillationResult',
    'CandidateClaim',
    'TextIngestionDistiller',
    'TextIngestionPlan',
    'IngestCandidate',
    'IngestProposal',
    'IngestExecutionResult',
]
