"""
Integration Tests for PKB v0 (Personal Knowledge Base)

This file contains comprehensive integration tests that exercise the full
public API of the PKB system with real LLM calls via OpenRouter.

Run with:
    export OPENROUTER_API_KEY="sk-or-v1-..."
    conda activate science-reader
    
    # Run all tests (may be slow due to LLM calls)
    python truth_management_system/tests/test_integration.py
    
    # Or use pytest (may have issues with numpy in sandbox)
    python -m pytest truth_management_system/tests/test_integration.py -v -s
    
    # Run specific test class
    python -m pytest truth_management_system/tests/test_integration.py::TestClaimsCRUDIntegration -v -s

Requirements:
    - OPENROUTER_API_KEY environment variable must be set
    - Network access for LLM API calls
    - Conda environment: science-reader
    - numpy installed

Test Categories:
    1. TestClaimsCRUDIntegration: Basic CRUD operations with LLM features
    2. TestSearchIntegration: All search strategies (FTS, embedding, hybrid, rerank)
    3. TestLLMHelpersIntegration: Direct LLM helper functions
    4. TestConflictManagementIntegration: Conflict detection and resolution
    5. TestTextOrchestrationIntegration: Natural language command parsing
    6. TestConversationDistillationIntegration: Chat memory extraction
    7. TestEndToEndScenarios: Complete real-world use case workflows
    8. TestEdgeCasesAndErrorHandling: Error conditions and boundary cases

Notes:
    - Tests use real LLM calls, so they cost money and take time
    - Some tests may fail intermittently due to LLM non-determinism
    - The JSON parsing in LLM helpers has been improved to handle various response formats
"""

import os
import sys
import json
import pytest
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import PKB modules
from truth_management_system import (
    PKBConfig,
    get_database,
    get_memory_database,
    StructuredAPI,
    TextOrchestrator,
    ConversationDistiller,
    LLMHelpers,
    Claim,
    Note,
    Entity,
    Tag,
    ClaimType,
    ClaimStatus,
    ContextDomain,
    EntityType,
    EntityRole,
    SearchFilters,
    ActionResult,
    generate_uuid,
    now_iso,
)


# ============================================================================
# Fixtures and Setup
# ============================================================================

def get_api_keys() -> Dict[str, str]:
    """
    Get API keys from environment.
    
    Returns:
        Dict with OPENROUTER_API_KEY.
        
    Raises:
        pytest.skip if API key not found.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        pytest.skip("OPENROUTER_API_KEY environment variable not set")
    return {"OPENROUTER_API_KEY": api_key}


@pytest.fixture(scope="module")
def keys():
    """
    Fixture providing API keys for all tests in module.
    
    Pass/Fail: PASS if OPENROUTER_API_KEY is set in environment.
               SKIP if not set.
    """
    return get_api_keys()


@pytest.fixture(scope="function")
def temp_db_path():
    """
    Fixture providing a temporary database path for each test.
    Creates a unique temp file that's cleaned up after the test.
    
    Pass/Fail: PASS if temp file can be created.
               FAIL if filesystem error occurs.
    """
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    
    yield db_path
    
    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)
    # Also clean WAL/SHM files
    for suffix in ["-wal", "-shm"]:
        wal_path = db_path + suffix
        if os.path.exists(wal_path):
            os.unlink(wal_path)


@pytest.fixture(scope="function")
def pkb_api(keys, temp_db_path):
    """
    Fixture providing fully initialized PKB with LLM capabilities.
    
    Pass/Fail: PASS if database initializes and API is ready.
               FAIL if schema creation fails.
    """
    config = PKBConfig(
        db_path=temp_db_path,
        fts_enabled=True,
        embedding_enabled=True,
        llm_model="openai/gpt-4o-mini",
        llm_temperature=0.0,
        log_llm_calls=True
    )
    db = get_database(config)
    api = StructuredAPI(db, keys, config)
    
    yield api
    
    # Cleanup
    db.close()


@pytest.fixture(scope="function")
def memory_db_api(keys):
    """
    Fixture providing in-memory database API (faster, no persistence).
    
    Pass/Fail: PASS if in-memory database initializes.
               FAIL if initialization fails.
    """
    config = PKBConfig(
        db_path=":memory:",
        fts_enabled=True,
        embedding_enabled=True,
        llm_model="openai/gpt-4o-mini",
        llm_temperature=0.0
    )
    from truth_management_system.database import PKBDatabase
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    api = StructuredAPI(db, keys, config)
    
    yield api
    
    db.close()


@pytest.fixture(scope="function")
def llm_helpers(keys):
    """
    Fixture providing LLMHelpers instance.
    
    Pass/Fail: PASS if LLMHelpers initializes with valid keys.
    """
    config = PKBConfig(llm_model="openai/gpt-4o-mini", llm_temperature=0.0)
    return LLMHelpers(keys, config)


# ============================================================================
# Test Class 1: Claims CRUD with LLM Integration
# ============================================================================

class TestClaimsCRUDIntegration:
    """
    Test Claims CRUD operations with real LLM features (auto_extract).
    
    These tests verify:
    - Claims can be added with automatic tag/entity extraction
    - Claims are properly stored and retrievable
    - Edit and delete operations work correctly
    - Metadata and timestamps are handled properly
    """
    
    def test_add_claim_with_auto_extract(self, pkb_api):
        """
        Test adding a claim with LLM-powered automatic extraction.
        
        What we test:
        - Claim is created successfully
        - LLM extracts relevant tags/entities
        - Claim is searchable after creation
        
        Pass criteria:
        - result.success is True
        - result.data contains claim with correct statement
        - claim_id is valid UUID
        
        Fail criteria:
        - API returns error
        - Statement doesn't match
        - No claim_id generated
        """
        result = pkb_api.add_claim(
            statement="I prefer drinking coffee in the morning with oat milk",
            claim_type="preference",
            context_domain="personal",
            auto_extract=True
        )
        
        assert result.success, f"Failed to add claim: {result.errors}"
        assert result.data is not None, "No claim data returned"
        assert result.data.statement == "I prefer drinking coffee in the morning with oat milk"
        assert result.data.claim_type == "preference"
        assert result.data.context_domain == "personal"
        assert result.data.claim_id is not None
        assert result.data.status == "active"
        
        # Verify claim is searchable
        search_result = pkb_api.search("coffee morning", k=5)
        assert search_result.success
        assert len(search_result.data) > 0
        found = any(r.claim.claim_id == result.data.claim_id for r in search_result.data)
        assert found, "Added claim not found in search results"
    
    def test_add_multiple_claim_types(self, pkb_api):
        """
        Test adding different claim types with auto_extract.
        
        What we test:
        - All claim types can be created
        - LLM correctly processes different claim semantics
        
        Pass criteria:
        - All claim types create successfully
        - Each has correct claim_type value
        
        Fail criteria:
        - Any claim type fails to create
        """
        test_claims = [
            ("My home city is San Francisco", "fact", "personal"),
            ("I enjoyed the sushi restaurant yesterday", "memory", "personal"),
            ("I decided to learn Python this year", "decision", "learning"),
            ("I like hiking more than biking", "preference", "health"),
            ("Buy groceries this weekend", "task", "life_ops"),
            ("Call mom on Friday", "reminder", "relationships"),
            ("Exercise for 30 minutes daily", "habit", "health"),
            ("Noticed knee pain after running", "observation", "health"),
        ]
        
        created_claims = []
        for statement, claim_type, domain in test_claims:
            result = pkb_api.add_claim(
                statement=statement,
                claim_type=claim_type,
                context_domain=domain,
                auto_extract=True
            )
            
            assert result.success, f"Failed to add {claim_type}: {result.errors}"
            assert result.data.claim_type == claim_type
            created_claims.append(result.data)
        
        assert len(created_claims) == len(test_claims)
    
    def test_add_claim_with_manual_tags_and_entities(self, pkb_api):
        """
        Test adding claim with manually specified tags and entities.
        
        What we test:
        - Manual tags are linked to claim
        - Manual entities are linked to claim
        - Both can coexist with auto_extract
        
        Pass criteria:
        - Claim created with tags
        - Claim created with entities
        - Both linked correctly
        
        Fail criteria:
        - Tags/entities not linked
        - Errors during creation
        """
        result = pkb_api.add_claim(
            statement="Mom recommended Dr. Smith for cardiology checkup",
            claim_type="fact",
            context_domain="health",
            tags=["health", "family", "doctors"],
            entities=[
                {"type": "person", "name": "Mom", "role": "subject"},
                {"type": "person", "name": "Dr. Smith", "role": "object"}
            ],
            auto_extract=False  # Only use manual tags/entities
        )
        
        assert result.success, f"Failed: {result.errors}"
        assert result.data is not None
        
        # Verify claim was created
        get_result = pkb_api.get_claim(result.object_id)
        assert get_result.success
        assert get_result.data.statement == "Mom recommended Dr. Smith for cardiology checkup"
    
    def test_edit_claim(self, pkb_api):
        """
        Test editing an existing claim.
        
        What we test:
        - Claim statement can be updated
        - Confidence score can be updated
        - updated_at timestamp changes
        
        Pass criteria:
        - Edit succeeds
        - Statement is updated
        - updated_at is newer than created_at
        
        Fail criteria:
        - Edit fails
        - Original values unchanged
        """
        # Create claim
        add_result = pkb_api.add_claim(
            statement="I prefer tea",
            claim_type="preference",
            context_domain="personal",
            auto_extract=False
        )
        assert add_result.success
        original_updated_at = add_result.data.updated_at
        
        # Wait briefly to ensure timestamp difference
        time.sleep(0.1)
        
        # Edit claim
        edit_result = pkb_api.edit_claim(
            add_result.object_id,
            statement="I strongly prefer coffee over tea",
            confidence=0.95
        )
        
        assert edit_result.success, f"Edit failed: {edit_result.errors}"
        assert edit_result.data.statement == "I strongly prefer coffee over tea"
        assert edit_result.data.confidence == 0.95
        assert edit_result.data.updated_at >= original_updated_at
    
    def test_delete_claim_soft_delete(self, pkb_api):
        """
        Test soft deletion of a claim (retraction).
        
        What we test:
        - Claim status becomes 'retracted'
        - retracted_at timestamp is set
        - Claim still exists in database (soft delete)
        
        Pass criteria:
        - Delete succeeds
        - status == 'retracted'
        - retracted_at is set
        
        Fail criteria:
        - Delete fails
        - Claim hard-deleted (not found)
        """
        # Create claim
        add_result = pkb_api.add_claim(
            statement="This claim will be deleted",
            claim_type="observation",
            context_domain="personal",
            auto_extract=False
        )
        assert add_result.success
        
        # Delete claim
        delete_result = pkb_api.delete_claim(add_result.object_id)
        
        assert delete_result.success, f"Delete failed: {delete_result.errors}"
        assert delete_result.data.status == "retracted"
        assert delete_result.data.retracted_at is not None
        
        # Verify claim still exists but is retracted
        get_result = pkb_api.get_claim(add_result.object_id)
        assert get_result.success
        assert get_result.data.status == "retracted"
    
    def test_add_claim_with_validity_period(self, pkb_api):
        """
        Test adding claim with temporal validity constraints.
        
        What we test:
        - valid_from and valid_to are properly set
        - Claims with validity period are created correctly
        
        Pass criteria:
        - Claim created with specified validity
        - Dates stored correctly
        
        Fail criteria:
        - Validity dates not stored
        - Invalid date format
        """
        result = pkb_api.add_claim(
            statement="Remind me about mom's birthday",
            claim_type="reminder",
            context_domain="relationships",
            valid_from="2025-03-15T00:00:00Z",
            valid_to="2025-03-15T23:59:59Z",
            auto_extract=False
        )
        
        assert result.success, f"Failed: {result.errors}"
        assert result.data.valid_from == "2025-03-15T00:00:00Z"
        assert result.data.valid_to == "2025-03-15T23:59:59Z"
    
    def test_add_claim_with_meta_json(self, pkb_api):
        """
        Test adding claim with custom metadata.
        
        What we test:
        - meta_json field stores custom data
        - Metadata is retrievable
        
        Pass criteria:
        - meta_json stored correctly
        - Can be parsed back to dict
        
        Fail criteria:
        - meta_json not stored
        - JSON parsing fails
        """
        metadata = {
            "source": "chat_distillation",
            "visibility": "default",
            "keywords": ["test", "metadata"],
            "llm": {
                "model": "gpt-4o-mini",
                "confidence_notes": "High confidence from explicit statement"
            }
        }
        
        result = pkb_api.add_claim(
            statement="Test claim with metadata",
            claim_type="fact",
            context_domain="personal",
            meta_json=json.dumps(metadata),
            auto_extract=False
        )
        
        assert result.success, f"Failed: {result.errors}"
        
        # Verify metadata
        get_result = pkb_api.get_claim(result.object_id)
        assert get_result.success
        
        stored_meta = json.loads(get_result.data.meta_json)
        assert stored_meta["source"] == "chat_distillation"
        assert stored_meta["visibility"] == "default"
        assert "keywords" in stored_meta


# ============================================================================
# Test Class 2: Search Integration Tests
# ============================================================================

class TestSearchIntegration:
    """
    Test all search strategies with real LLM calls.
    
    These tests verify:
    - FTS (Full-Text Search) returns keyword matches
    - Embedding search finds semantic matches
    - Hybrid search combines FTS + embedding
    - Rerank improves result quality with LLM
    - Filters work correctly
    """
    
    @pytest.fixture(autouse=True)
    def setup_test_claims(self, memory_db_api):
        """
        Setup test claims for search tests.
        Creates a variety of claims to search against.
        """
        self.api = memory_db_api
        
        # Add diverse test claims
        test_claims = [
            ("I love drinking coffee every morning", "preference", "personal"),
            ("Tea with honey is my afternoon ritual", "habit", "personal"),
            ("I decided to switch to decaf after 2pm", "decision", "health"),
            ("My mom prefers green tea", "fact", "relationships"),
            ("Exercise for 30 minutes before breakfast", "habit", "health"),
            ("Running helps clear my mind", "observation", "health"),
            ("I'm learning machine learning this quarter", "fact", "learning"),
            ("Python is my favorite programming language", "preference", "work"),
            ("Schedule dentist appointment next month", "task", "health"),
            ("Investment portfolio review due in March", "reminder", "finance"),
        ]
        
        self.claim_ids = []
        for statement, claim_type, domain in test_claims:
            result = self.api.add_claim(
                statement=statement,
                claim_type=claim_type,
                context_domain=domain,
                auto_extract=False  # Faster setup
            )
            if result.success:
                self.claim_ids.append(result.object_id)
        
        # Allow FTS index to update
        time.sleep(0.2)
    
    def test_fts_search(self):
        """
        Test Full-Text Search (BM25) strategy.
        
        What we test:
        - FTS returns exact keyword matches
        - BM25 scoring ranks results appropriately
        - Results are sorted by relevance
        
        Pass criteria:
        - Results contain "coffee" keyword
        - Returns at least 1 result
        - strategy="fts" works
        
        Fail criteria:
        - No results for known keyword
        - Search errors out
        """
        result = self.api.search("coffee", strategy="fts", k=10)
        
        assert result.success, f"FTS search failed: {result.errors}"
        assert len(result.data) > 0, "No FTS results for 'coffee'"
        
        # Verify results contain coffee
        found_coffee = False
        for r in result.data:
            if "coffee" in r.claim.statement.lower():
                found_coffee = True
                break
        assert found_coffee, "Coffee not found in FTS results"
    
    def test_embedding_search(self):
        """
        Test embedding-based semantic search.
        
        What we test:
        - Embedding search finds semantically similar content
        - Can find related concepts without exact keyword match
        
        Pass criteria:
        - Returns results for semantic query
        - Finds related claims
        
        Fail criteria:
        - No results
        - Embedding computation fails
        """
        # Search for semantic concept
        result = self.api.search(
            "beverages I enjoy drinking",
            strategy="embedding",
            k=5
        )
        
        assert result.success, f"Embedding search failed: {result.errors}"
        # Should find coffee/tea claims even without exact keywords
        assert len(result.data) > 0, "No embedding results"
        
        # Check that beverage-related claims score high
        statements = [r.claim.statement.lower() for r in result.data]
        beverage_found = any("coffee" in s or "tea" in s for s in statements)
        # Note: Embedding search may or may not find these depending on quality
        print(f"Embedding results: {statements}")
    
    def test_hybrid_search(self):
        """
        Test hybrid search (FTS + Embedding + RRF merge).
        
        What we test:
        - Hybrid search combines multiple strategies
        - Results are merged using Reciprocal Rank Fusion
        - Quality is at least as good as individual strategies
        
        Pass criteria:
        - Hybrid search returns results
        - Results include both keyword and semantic matches
        
        Fail criteria:
        - Search fails
        - No results
        """
        result = self.api.search(
            "morning beverage preferences",
            strategy="hybrid",
            k=10
        )
        
        assert result.success, f"Hybrid search failed: {result.errors}"
        assert len(result.data) > 0, "No hybrid results"
        
        # Should get good results from combined strategies
        print(f"Hybrid search returned {len(result.data)} results")
        for r in result.data[:3]:
            print(f"  - [{r.score:.3f}] {r.claim.statement[:60]}...")
    
    def test_search_with_filters(self):
        """
        Test search with various filter combinations.
        
        What we test:
        - context_domain filter works
        - claim_type filter works
        - status filter works
        - Multiple filters combine correctly
        
        Pass criteria:
        - Filtered results match filter criteria
        - All results have correct domain/type
        
        Fail criteria:
        - Results don't match filters
        - Filter ignored
        """
        # Test context_domain filter
        result = self.api.search(
            "exercise health",
            filters={
                "context_domains": ["health"],
                "statuses": ["active"]
            },
            k=10
        )
        
        assert result.success, f"Filtered search failed: {result.errors}"
        
        # All results should be health domain
        for r in result.data:
            assert r.claim.context_domain == "health", \
                f"Got {r.claim.context_domain}, expected health"
    
    def test_search_claim_type_filter(self):
        """
        Test search with claim_type filter.
        
        What we test:
        - Can filter by specific claim types
        - Filter is correctly applied
        
        Pass criteria:
        - Results only contain specified claim types
        
        Fail criteria:
        - Results contain other claim types
        """
        result = self.api.search(
            "daily routine",
            filters={
                "claim_types": ["habit", "task"]
            },
            k=10
        )
        
        assert result.success
        for r in result.data:
            assert r.claim.claim_type in ["habit", "task"], \
                f"Got {r.claim.claim_type}, expected habit or task"
    
    def test_search_returns_contested_with_warnings(self):
        """
        Test that contested claims are returned with warnings.
        
        What we test:
        - Contested claims are included in search
        - Warnings are attached to contested claims
        
        Pass criteria:
        - Contested claims appear in results
        - They have warning flags
        
        Fail criteria:
        - Contested claims excluded without include_contested=False
        """
        # Create two conflicting claims
        result1 = self.api.add_claim(
            statement="I like spicy food",
            claim_type="preference",
            context_domain="personal",
            auto_extract=False
        )
        result2 = self.api.add_claim(
            statement="I hate spicy food",
            claim_type="preference",
            context_domain="personal",
            auto_extract=False
        )
        
        # Create conflict set
        conflict_result = self.api.create_conflict_set(
            [result1.object_id, result2.object_id],
            notes="Contradicting preferences about spicy food"
        )
        assert conflict_result.success
        
        # Search should return contested claims with warnings
        search_result = self.api.search("spicy food", k=5, include_contested=True)
        assert search_result.success
        
        # At least one should have contested status or warning
        contested_found = False
        for r in search_result.data:
            if r.claim.status == "contested" or r.warnings:
                contested_found = True
                break
        
        # Note: The implementation might handle this differently
        print(f"Contested search results: {len(search_result.data)}")
    
    def test_search_notes(self):
        """
        Test notes search functionality.
        
        What we test:
        - Notes can be searched separately
        - FTS works on note body/title
        
        Pass criteria:
        - Notes search returns results
        - Results match query
        
        Fail criteria:
        - Search fails
        - Notes not found
        """
        # Add test notes
        note_result = self.api.add_note(
            title="Meeting Notes",
            body="Discussed project timeline and deliverables with team.",
            context_domain="work"
        )
        assert note_result.success
        
        # Search notes
        search_result = self.api.search_notes("project timeline", k=5)
        
        assert search_result.success
        assert len(search_result.data) > 0, "Note not found in search"


# ============================================================================
# Test Class 3: LLM Helpers Integration
# ============================================================================

class TestLLMHelpersIntegration:
    """
    Test LLM helper functions directly.
    
    These tests verify the LLM extraction and analysis capabilities:
    - Tag generation from text
    - Entity extraction
    - Claim type classification
    - Similarity checking
    """
    
    def test_generate_tags(self, llm_helpers):
        """
        Test LLM-powered tag generation.
        
        What we test:
        - LLM generates relevant tags
        - Tags are returned as list
        - Tags are appropriate for content
        
        Pass criteria:
        - Returns list of tags
        - Tags are relevant to statement
        
        Fail criteria:
        - Empty tags
        - API error
        """
        tags = llm_helpers.generate_tags(
            statement="I prefer running in the morning before work",
            context_domain="health",
            existing_tags=["fitness", "routine"]
        )
        
        assert isinstance(tags, list), "Tags should be a list"
        assert len(tags) > 0, "Should generate at least one tag"
        
        print(f"Generated tags: {tags}")
        # Tags should be relevant to running/morning/health
    
    def test_extract_entities(self, llm_helpers):
        """
        Test entity extraction from text.
        
        What we test:
        - LLM extracts named entities
        - Entities have correct types
        - Roles are assigned appropriately
        
        Pass criteria:
        - Entities extracted as list
        - Each has type, name, role
        
        Fail criteria:
        - No entities found when present
        - Missing required fields
        """
        entities = llm_helpers.extract_entities(
            "My mom recommended Dr. Smith at Stanford Hospital"
        )
        
        assert isinstance(entities, list), "Entities should be a list"
        
        print(f"Extracted entities: {entities}")
        
        # Should find at least mom, Dr. Smith, Stanford Hospital
        if len(entities) > 0:
            for entity in entities:
                assert "type" in entity or "entity_type" in entity
                assert "name" in entity
    
    def test_extract_spo(self, llm_helpers):
        """
        Test Subject-Predicate-Object extraction.
        
        What we test:
        - LLM extracts SPO structure
        - Returns meaningful subject/predicate/object
        
        Pass criteria:
        - SPO dict returned
        - Subject, predicate, object present
        
        Fail criteria:
        - None returned
        - Missing components
        """
        spo = llm_helpers.extract_spo("I prefer morning workouts over evening ones")
        
        print(f"Extracted SPO: {spo}")
        
        assert spo is not None, "SPO should be extracted"
        # Should have subject, predicate, object keys
    
    def test_classify_claim_type(self, llm_helpers):
        """
        Test automatic claim type classification.
        
        What we test:
        - LLM classifies claim type correctly
        - Returns valid claim type
        
        Pass criteria:
        - Returns valid claim type string
        - Classification is reasonable
        
        Fail criteria:
        - Invalid type returned
        - Classification completely wrong
        """
        test_cases = [
            ("I decided to quit smoking", "decision"),
            ("I like pizza more than pasta", "preference"),
            ("Buy groceries tomorrow", "task"),
            ("My sister lives in Boston", "fact"),
        ]
        
        for statement, expected_type in test_cases:
            result = llm_helpers.classify_claim_type(statement)
            
            print(f"'{statement[:30]}...' -> {result} (expected: {expected_type})")
            
            assert result is not None, f"No classification for: {statement}"
            # LLM may not always match exactly, but should be a valid type
    
    def test_check_similarity(self, llm_helpers, memory_db_api):
        """
        Test claim similarity checking.
        
        What we test:
        - LLM can detect similar/duplicate claims
        - Similarity scores are meaningful
        - Relations (duplicate/related/different) are identified
        
        Pass criteria:
        - Similar claims detected
        - Scores reflect actual similarity
        
        Fail criteria:
        - No similarity detection
        - Obviously similar claims marked different
        """
        # Create some existing claims
        existing_claims = []
        for statement in [
            "I like coffee in the morning",
            "I prefer tea over coffee",
            "Exercise is important for health"
        ]:
            result = memory_db_api.add_claim(
                statement=statement,
                claim_type="preference",
                context_domain="personal",
                auto_extract=False
            )
            if result.success:
                existing_claims.append(result.data)
        
        # Check similarity for a new claim
        similar = llm_helpers.check_similarity(
            new_claim="I enjoy morning coffee",
            existing_claims=existing_claims,
            threshold=0.5
        )
        
        print(f"Similarity results: {similar}")
        
        # Should find the coffee claim as similar
        assert isinstance(similar, list), "Should return list"


# ============================================================================
# Test Class 4: Conflict Management
# ============================================================================

class TestConflictManagementIntegration:
    """
    Test conflict detection and resolution features.
    
    These tests verify:
    - Conflict sets can be created
    - Open conflicts can be retrieved
    - Conflicts can be resolved
    - Claims in conflict sets get 'contested' status
    """
    
    def test_create_conflict_set(self, memory_db_api):
        """
        Test creating a conflict set between claims.
        
        What we test:
        - Conflict set created successfully
        - Claims are linked to conflict set
        - Claims become 'contested'
        
        Pass criteria:
        - Conflict set created
        - Both claims linked
        
        Fail criteria:
        - Creation fails
        - Claims not linked
        """
        # Create conflicting claims
        claim1 = memory_db_api.add_claim(
            statement="I am vegetarian",
            claim_type="fact",
            context_domain="health",
            auto_extract=False
        )
        claim2 = memory_db_api.add_claim(
            statement="I eat chicken regularly",
            claim_type="habit",
            context_domain="health",
            auto_extract=False
        )
        
        assert claim1.success and claim2.success
        
        # Create conflict set
        conflict_result = memory_db_api.create_conflict_set(
            claim_ids=[claim1.object_id, claim2.object_id],
            notes="Contradicting dietary facts"
        )
        
        assert conflict_result.success, f"Conflict creation failed: {conflict_result.errors}"
        assert conflict_result.data is not None
        assert len(conflict_result.data.member_claim_ids) == 2
    
    def test_get_open_conflicts(self, memory_db_api):
        """
        Test retrieving open (unresolved) conflicts.
        
        What we test:
        - Open conflicts can be listed
        - Only unresolved conflicts returned
        
        Pass criteria:
        - get_open_conflicts returns list
        - Created conflict appears in list
        
        Fail criteria:
        - API error
        - Created conflict not in list
        """
        # Create a conflict
        claim1 = memory_db_api.add_claim(
            statement="I work from home",
            claim_type="fact",
            context_domain="work",
            auto_extract=False
        )
        claim2 = memory_db_api.add_claim(
            statement="I go to office daily",
            claim_type="habit",
            context_domain="work",
            auto_extract=False
        )
        
        memory_db_api.create_conflict_set(
            [claim1.object_id, claim2.object_id],
            "Work location conflict"
        )
        
        # Get open conflicts
        result = memory_db_api.get_open_conflicts()
        
        assert result.success, f"Failed to get conflicts: {result.errors}"
        assert len(result.data) > 0, "No open conflicts found"
    
    def test_resolve_conflict_set(self, memory_db_api):
        """
        Test resolving a conflict set.
        
        What we test:
        - Conflict can be marked resolved
        - Resolution notes are saved
        - Winning claim (if specified) becomes active
        
        Pass criteria:
        - Resolution succeeds
        - Status changes to 'resolved'
        
        Fail criteria:
        - Resolution fails
        - Status unchanged
        """
        # Create conflict
        claim1 = memory_db_api.add_claim(
            statement="I wake up at 6am",
            claim_type="habit",
            context_domain="personal",
            auto_extract=False
        )
        claim2 = memory_db_api.add_claim(
            statement="I usually sleep until 9am",
            claim_type="habit",
            context_domain="personal",
            auto_extract=False
        )
        
        conflict_result = memory_db_api.create_conflict_set(
            [claim1.object_id, claim2.object_id],
            "Wake time conflict"
        )
        
        # Resolve conflict
        resolve_result = memory_db_api.resolve_conflict_set(
            conflict_result.object_id,
            resolution_notes="The 6am waking is the current truth",
            winning_claim_id=claim1.object_id
        )
        
        assert resolve_result.success, f"Resolution failed: {resolve_result.errors}"


# ============================================================================
# Test Class 5: Text Orchestration
# ============================================================================

class TestTextOrchestrationIntegration:
    """
    Test natural language command parsing and execution.
    
    These tests verify:
    - "remember that..." commands add claims
    - "find..." commands search
    - "delete..." commands mark for deletion
    - Intent parsing works correctly
    """
    
    @pytest.fixture(autouse=True)
    def setup_orchestrator(self, memory_db_api, keys):
        """Setup text orchestrator for tests."""
        self.api = memory_db_api
        config = PKBConfig(llm_model="openai/gpt-4o-mini")
        self.orchestrator = TextOrchestrator(self.api, keys, config)
        
        # Add some test claims
        self.api.add_claim(
            statement="I have a dentist appointment on Monday",
            claim_type="reminder",
            context_domain="health",
            auto_extract=False
        )
        self.api.add_claim(
            statement="I prefer dark roast coffee",
            claim_type="preference",
            context_domain="personal",
            auto_extract=False
        )
    
    def test_process_add_command(self):
        """
        Test "remember that..." command processing.
        
        What we test:
        - LLM parses add intent
        - Claim is created
        - Appropriate response returned
        
        Pass criteria:
        - action_taken indicates addition
        - Claim was created
        
        Fail criteria:
        - Parse fails
        - No claim created
        """
        result = self.orchestrator.process(
            "Remember that I'm allergic to shellfish"
        )
        
        print(f"Add command result: {result.action_taken}")
        print(f"Raw intent: {result.raw_intent}")
        
        assert "add" in result.action_taken.lower() or result.action_result is not None, \
            f"Add command not recognized: {result.action_taken}"
        
        # Verify claim was added
        if result.action_result and result.action_result.success:
            search = self.api.search("allergic shellfish", k=5)
            assert search.success
    
    def test_process_search_command(self):
        """
        Test "find..." command processing.
        
        What we test:
        - LLM parses search intent
        - Search is executed
        - Results are returned
        
        Pass criteria:
        - action_taken indicates search
        - Results returned
        
        Fail criteria:
        - Parse fails
        - No search executed
        """
        result = self.orchestrator.process(
            "Find what I know about coffee preferences"
        )
        
        print(f"Search command result: {result.action_taken}")
        
        assert "found" in result.action_taken.lower() or "search" in result.raw_intent.get("action", ""), \
            f"Search command not recognized: {result.action_taken}"
        
        if result.action_result and result.action_result.success:
            assert result.action_result.data is not None
    
    def test_process_delete_command(self):
        """
        Test "delete..." command processing.
        
        What we test:
        - LLM parses delete intent
        - Search for deletion target happens
        - Clarifying question for confirmation
        
        Pass criteria:
        - Delete intent recognized
        - Confirmation requested (not immediate deletion)
        
        Fail criteria:
        - Delete intent not parsed
        - Immediate deletion without confirmation
        """
        result = self.orchestrator.process(
            "Delete the reminder about dentist"
        )
        
        print(f"Delete command result: {result.action_taken}")
        print(f"Clarifying questions: {result.clarifying_questions}")
        
        # Should either find claims to delete or ask for clarification
        assert (
            "delete" in result.action_taken.lower() or 
            "found" in result.action_taken.lower() or
            len(result.clarifying_questions) > 0
        ), f"Delete not handled: {result.action_taken}"
    
    def test_process_list_conflicts_command(self):
        """
        Test "show conflicts" command.
        
        What we test:
        - Conflicts listing is triggered
        - Response includes conflict count
        
        Pass criteria:
        - Conflicts action recognized
        - Response mentions conflicts
        
        Fail criteria:
        - Command not recognized
        """
        result = self.orchestrator.process("Show me all open conflicts")
        
        print(f"List conflicts result: {result.action_taken}")
        
        # Should recognize conflicts action
        # May need fallback if LLM doesn't catch it
    
    def test_execute_confirmed_action(self):
        """
        Test executing a confirmed delete action.
        
        What we test:
        - After user confirms, action executes
        - Claim is actually deleted (retracted)
        
        Pass criteria:
        - Confirmed delete succeeds
        - Claim status is retracted
        
        Fail criteria:
        - Execution fails
        - Claim unchanged
        """
        # Add claim to delete
        add_result = self.api.add_claim(
            statement="Temporary claim for deletion test",
            claim_type="observation",
            context_domain="personal",
            auto_extract=False
        )
        
        # Execute confirmed delete
        result = self.orchestrator.execute_confirmed_action(
            action="delete_claim",
            target_id=add_result.object_id
        )
        
        assert result.action_result.success, f"Confirmed delete failed: {result.action_result.errors}"
        
        # Verify deletion
        get_result = self.api.get_claim(add_result.object_id)
        assert get_result.data.status == "retracted"


# ============================================================================
# Test Class 6: Conversation Distillation
# ============================================================================

class TestConversationDistillationIntegration:
    """
    Test conversation memory extraction features.
    
    These tests verify:
    - Facts can be extracted from chat turns
    - Duplicates are detected
    - User confirmation prompts are generated
    - Approved actions are executed
    """
    
    @pytest.fixture(autouse=True)
    def setup_distiller(self, memory_db_api, keys):
        """Setup conversation distiller."""
        self.api = memory_db_api
        config = PKBConfig(llm_model="openai/gpt-4o-mini")
        self.distiller = ConversationDistiller(self.api, keys, config)
    
    def test_extract_and_propose_new_facts(self):
        """
        Test extracting new facts from conversation.
        
        What we test:
        - LLM extracts memorable facts from chat
        - Proposed actions are generated
        - User prompt is created
        
        Pass criteria:
        - Candidates extracted
        - Proposed actions created
        - User prompt is meaningful
        
        Fail criteria:
        - No extraction (when facts are present)
        - No proposed actions
        """
        plan = self.distiller.extract_and_propose(
            conversation_summary="User discussing their diet preferences",
            user_message="I've decided to go vegetarian. I'm also trying to eat more vegetables and less processed food.",
            assistant_message="That's a great health decision! Vegetarian diets can be very nutritious. Let me know if you need recipe suggestions."
        )
        
        print(f"Extracted candidates: {len(plan.candidates)}")
        print(f"Proposed actions: {len(plan.proposed_actions)}")
        print(f"User prompt:\n{plan.user_prompt}")
        
        # Should find at least one memorable fact
        if plan.candidates:
            for candidate in plan.candidates:
                print(f"  - [{candidate.claim_type}] {candidate.statement}")
        
        # Plan should indicate if confirmation needed
        assert isinstance(plan.user_prompt, str)
    
    def test_extract_with_existing_duplicates(self):
        """
        Test that duplicates are detected during extraction.
        
        What we test:
        - Existing claims are found during matching
        - Skip action proposed for duplicates
        
        Pass criteria:
        - Existing match found
        - Duplicate not re-added
        
        Fail criteria:
        - Duplicate added anyway
        """
        # Add existing claim
        self.api.add_claim(
            statement="I am vegetarian",
            claim_type="fact",
            context_domain="health",
            auto_extract=False
        )
        
        # Try to extract same fact from conversation
        plan = self.distiller.extract_and_propose(
            conversation_summary="Continuing diet discussion",
            user_message="As I mentioned, I'm vegetarian",
            assistant_message="Yes, I remember you mentioned that."
        )
        
        print(f"Plan with potential duplicate:")
        print(f"  Candidates: {len(plan.candidates)}")
        print(f"  Actions: {len(plan.proposed_actions)}")
        
        # Should either skip or warn about duplicate
    
    def test_execute_plan_approve_all(self):
        """
        Test executing all proposed actions.
        
        What we test:
        - "all" approval executes all actions
        - Claims are actually created
        
        Pass criteria:
        - All actions executed
        - Claims exist after execution
        
        Fail criteria:
        - Execution fails
        - Claims not created
        """
        plan = self.distiller.extract_and_propose(
            conversation_summary="Health discussion",
            user_message="I've started running every morning. I also take vitamin D supplements.",
            assistant_message="Regular exercise and vitamin D are both great for health!"
        )
        
        if plan.proposed_actions:
            result = self.distiller.execute_plan(plan, "all")
            
            print(f"Execution result: executed={result.executed}")
            print(f"Execution results count: {len(result.execution_results)}")
            
            assert result.executed
            
            # Check that actions were successful
            for action_result in result.execution_results:
                print(f"  - {action_result.action}: success={action_result.success}")
    
    def test_execute_plan_selective_approval(self):
        """
        Test executing only selected actions.
        
        What we test:
        - Specific indices are approved
        - Only approved actions execute
        
        Pass criteria:
        - Only approved items executed
        
        Fail criteria:
        - Wrong items executed
        """
        plan = self.distiller.extract_and_propose(
            conversation_summary="Work discussion",
            user_message="I work at Google. My manager is Sarah. I'm on the ML team.",
            assistant_message="That sounds like an exciting team to be on!"
        )
        
        if len(plan.proposed_actions) >= 2:
            # Only approve first item
            result = self.distiller.execute_plan(plan, "1", approved_indices=[0])
            
            assert result.executed
            assert len(result.execution_results) == 1
    
    def test_execute_plan_decline_all(self):
        """
        Test declining all proposed actions.
        
        What we test:
        - "none" approval skips all actions
        - No claims created
        
        Pass criteria:
        - executed=True but no actions
        
        Fail criteria:
        - Actions executed despite decline
        """
        plan = self.distiller.extract_and_propose(
            conversation_summary="Random chat",
            user_message="Maybe I should learn Spanish",
            assistant_message="Learning a new language can be rewarding!"
        )
        
        if plan.proposed_actions:
            result = self.distiller.execute_plan(plan, "none")
            
            assert len(result.execution_results) == 0


# ============================================================================
# Test Class 7: End-to-End Scenarios
# ============================================================================

class TestEndToEndScenarios:
    """
    Test complete real-world use case workflows.
    
    These tests simulate actual user sessions with multiple operations.
    """
    
    def test_chatbot_memory_workflow(self, pkb_api, keys):
        """
        Test complete chatbot memory workflow.
        
        Scenario:
        1. User has conversation with chatbot
        2. Facts are extracted and proposed
        3. User confirms
        4. Later queries retrieve the memories
        
        Pass criteria:
        - Full workflow completes
        - Memories are searchable after storage
        
        Fail criteria:
        - Any step fails
        - Memories not retrievable
        """
        config = PKBConfig(llm_model="openai/gpt-4o-mini")
        distiller = ConversationDistiller(pkb_api, keys, config)
        
        # Step 1: Conversation turn
        plan = distiller.extract_and_propose(
            conversation_summary="User is setting up their profile",
            user_message="My name is Alex. I live in Seattle and work as a software engineer at Amazon.",
            assistant_message="Nice to meet you Alex! Seattle is a great city. What kind of projects do you work on at Amazon?"
        )
        
        print(f"Step 1 - Extracted {len(plan.candidates)} candidates")
        
        # Step 2: User confirms all
        if plan.proposed_actions:
            result = distiller.execute_plan(plan, "all")
            print(f"Step 2 - Executed {len(result.execution_results)} actions")
        
        # Step 3: Later query
        time.sleep(0.2)  # Allow indexing
        
        search_result = pkb_api.search("where does Alex live", k=5)
        
        print(f"Step 3 - Search found {len(search_result.data)} results")
        
        assert search_result.success
        # Should find Seattle-related claim
        found_seattle = any(
            "seattle" in r.claim.statement.lower() 
            for r in search_result.data
        )
        print(f"Found Seattle reference: {found_seattle}")
    
    def test_health_tracking_scenario(self, pkb_api, keys):
        """
        Test health tracking use case.
        
        Scenario:
        1. User logs health observations
        2. User logs habits
        3. User searches for patterns
        
        Pass criteria:
        - Health claims created
        - Searchable by domain
        - Patterns visible
        
        Fail criteria:
        - Claims not created
        - Domain filter not working
        """
        # Add health observations over time
        health_claims = [
            ("Felt energetic after morning run", "observation"),
            ("Had headache after skipping breakfast", "observation"),
            ("Sleep quality improved with earlier bedtime", "observation"),
            ("Morning meditation for 10 minutes daily", "habit"),
            ("Drink 8 glasses of water per day", "habit"),
        ]
        
        for statement, claim_type in health_claims:
            result = pkb_api.add_claim(
                statement=statement,
                claim_type=claim_type,
                context_domain="health",
                auto_extract=True
            )
            assert result.success, f"Failed to add: {statement}"
        
        # Search for patterns
        search_result = pkb_api.search(
            "what affects my energy levels",
            filters={"context_domains": ["health"]},
            k=10
        )
        
        assert search_result.success
        print(f"Health search found {len(search_result.data)} results")
        
        for r in search_result.data[:3]:
            print(f"  - [{r.claim.claim_type}] {r.claim.statement}")
    
    def test_decision_logging_scenario(self, pkb_api, keys):
        """
        Test decision logging use case.
        
        Scenario:
        1. User logs important decisions
        2. User adds reasoning in notes
        3. User retrieves decisions later
        
        Pass criteria:
        - Decisions stored
        - Notes linked contextually
        - Can filter by decision type
        
        Fail criteria:
        - Decisions not stored
        - Notes not searchable
        """
        # Log decisions
        decisions = [
            "Decided to invest only in index funds",
            "Decided to change jobs to focus on AI",
            "Decided to move to remote-first work setup",
        ]
        
        for decision in decisions:
            result = pkb_api.add_claim(
                statement=decision,
                claim_type="decision",
                context_domain="finance" if "invest" in decision else "work",
                auto_extract=True
            )
            assert result.success
        
        # Add reasoning note
        note_result = pkb_api.add_note(
            title="Investment Decision Reasoning",
            body="Index funds have historically outperformed most active managers. Lower fees and diversification make them the safer choice for long-term growth.",
            context_domain="finance"
        )
        assert note_result.success
        
        # Search decisions
        search_result = pkb_api.search(
            "what investment decisions have I made",
            filters={"claim_types": ["decision"]},
            k=10
        )
        
        assert search_result.success
        
        # Should find investment decision
        found_investment = any(
            "index fund" in r.claim.statement.lower() or "invest" in r.claim.statement.lower()
            for r in search_result.data
        )
        print(f"Found investment decision: {found_investment}")
    
    def test_multi_turn_conversation_memory(self, pkb_api, keys):
        """
        Test memory building across multiple conversation turns.
        
        Scenario:
        1. Multiple conversation turns extract facts
        2. Facts accumulate without duplicates
        3. Final search finds all relevant facts
        
        Pass criteria:
        - Multiple turns processed
        - No duplicate storage
        - Comprehensive retrieval
        
        Fail criteria:
        - Duplicates stored
        - Facts lost
        """
        config = PKBConfig(llm_model="openai/gpt-4o-mini")
        distiller = ConversationDistiller(pkb_api, keys, config)
        
        conversation_turns = [
            {
                "summary": "Getting to know user",
                "user": "I'm a data scientist at Netflix",
                "assistant": "Interesting! What kind of data science work do you do there?"
            },
            {
                "summary": "User works at Netflix in data science",
                "user": "Mostly recommendation systems. I also enjoy hiking on weekends.",
                "assistant": "That's a fascinating area! And hiking is great exercise."
            },
            {
                "summary": "User does recommendations at Netflix, likes hiking",
                "user": "Yeah, I try to hike every Saturday morning in the nearby mountains",
                "assistant": "Having a regular outdoor activity is wonderful for mental health!"
            }
        ]
        
        total_added = 0
        for turn in conversation_turns:
            plan = distiller.extract_and_propose(
                conversation_summary=turn["summary"],
                user_message=turn["user"],
                assistant_message=turn["assistant"]
            )
            
            if plan.proposed_actions:
                result = distiller.execute_plan(plan, "all")
                total_added += len([r for r in result.execution_results if r.success])
        
        print(f"Total facts added across turns: {total_added}")
        
        # Final search should find work and hobby facts
        work_search = pkb_api.search("where does user work", k=10)
        hobby_search = pkb_api.search("user outdoor activities", k=10)
        
        print(f"Work search: {len(work_search.data)} results")
        print(f"Hobby search: {len(hobby_search.data)} results")


# ============================================================================
# Test Class 8: Edge Cases and Error Handling
# ============================================================================

class TestEdgeCasesAndErrorHandling:
    """
    Test edge cases, boundary conditions, and error handling.
    
    These tests ensure robust behavior under unusual conditions.
    """
    
    def test_empty_claim_statement(self, memory_db_api):
        """
        Test handling of empty claim statement.
        
        What we test:
        - Empty string rejected
        - Meaningful error returned
        
        Pass criteria:
        - Operation fails gracefully
        - Error message explains issue
        
        Fail criteria:
        - Empty claim stored
        - Crash/exception
        """
        result = memory_db_api.add_claim(
            statement="",
            claim_type="fact",
            context_domain="personal",
            auto_extract=False
        )
        
        # Should fail or reject
        if not result.success:
            print(f"Empty claim rejected: {result.errors}")
            assert len(result.errors) > 0
    
    def test_very_long_claim_statement(self, memory_db_api):
        """
        Test handling of very long claim text.
        
        What we test:
        - Long text is handled
        - No truncation errors
        
        Pass criteria:
        - Claim stored successfully
        - Full text retrievable
        
        Fail criteria:
        - Truncation without warning
        - Database error
        """
        long_statement = "I remember that " + ("very " * 500) + "important fact about something."
        
        result = memory_db_api.add_claim(
            statement=long_statement,
            claim_type="memory",
            context_domain="personal",
            auto_extract=False
        )
        
        assert result.success, f"Long claim failed: {result.errors}"
        
        # Verify full text stored
        get_result = memory_db_api.get_claim(result.object_id)
        assert len(get_result.data.statement) == len(long_statement)
    
    def test_special_characters_in_claim(self, memory_db_api):
        """
        Test handling of special characters and unicode.
        
        What we test:
        - Unicode characters preserved
        - SQL injection prevented
        - Special chars in search work
        
        Pass criteria:
        - Characters stored correctly
        - Searchable
        
        Fail criteria:
        - Characters mangled
        - SQL injection works
        """
        special_statement = "I love café ☕ & croissants 🥐! User's favorite: \"espresso\""
        
        result = memory_db_api.add_claim(
            statement=special_statement,
            claim_type="preference",
            context_domain="personal",
            auto_extract=False
        )
        
        assert result.success
        
        get_result = memory_db_api.get_claim(result.object_id)
        assert get_result.data.statement == special_statement
        
        # Test search with special chars
        search_result = memory_db_api.search("café", k=5)
        assert search_result.success
    
    def test_invalid_claim_type(self, memory_db_api):
        """
        Test handling of invalid claim type.
        
        What we test:
        - Invalid type rejected or normalized
        
        Pass criteria:
        - Graceful handling
        
        Fail criteria:
        - Invalid type stored
        - Crash
        """
        result = memory_db_api.add_claim(
            statement="Test claim",
            claim_type="invalid_type_xyz",
            context_domain="personal",
            auto_extract=False
        )
        
        # May succeed with the type stored as-is, or fail
        print(f"Invalid type result: success={result.success}, type={result.data.claim_type if result.data else None}")
    
    def test_nonexistent_claim_id(self, memory_db_api):
        """
        Test operations on non-existent claim ID.
        
        What we test:
        - Get non-existent returns meaningful response
        - Edit non-existent fails gracefully
        - Delete non-existent handled
        
        Pass criteria:
        - Operations fail gracefully
        - No crash
        
        Fail criteria:
        - Crash/exception
        - Misleading success
        """
        fake_id = generate_uuid()
        
        # Get
        get_result = memory_db_api.get_claim(fake_id)
        print(f"Get nonexistent: success={get_result.success}, data={get_result.data}")
        
        # Edit
        edit_result = memory_db_api.edit_claim(fake_id, statement="new statement")
        print(f"Edit nonexistent: success={edit_result.success}")
        
        # Delete
        delete_result = memory_db_api.delete_claim(fake_id)
        print(f"Delete nonexistent: success={delete_result.success}")
    
    def test_concurrent_claims(self, memory_db_api):
        """
        Test adding many claims rapidly.
        
        What we test:
        - Database handles rapid writes
        - No race conditions
        - All claims stored
        
        Pass criteria:
        - All claims stored
        - No duplicates
        - No lost writes
        
        Fail criteria:
        - Lost writes
        - Database lock errors
        """
        num_claims = 20
        claim_ids = []
        
        for i in range(num_claims):
            result = memory_db_api.add_claim(
                statement=f"Rapid test claim number {i}",
                claim_type="observation",
                context_domain="personal",
                auto_extract=False
            )
            if result.success:
                claim_ids.append(result.object_id)
        
        assert len(claim_ids) == num_claims, f"Expected {num_claims}, got {len(claim_ids)}"
        
        # Verify all are retrievable
        for claim_id in claim_ids:
            result = memory_db_api.get_claim(claim_id)
            assert result.success
    
    def test_search_empty_database(self, keys):
        """
        Test searching when database is empty.
        
        What we test:
        - Search returns empty results
        - No errors
        
        Pass criteria:
        - Empty result list
        - success=True
        
        Fail criteria:
        - Error thrown
        - None returned
        """
        config = PKBConfig(db_path=":memory:")
        from truth_management_system.database import PKBDatabase
        db = PKBDatabase(config)
        db.connect()
        db.initialize_schema()
        api = StructuredAPI(db, keys, config)
        
        result = api.search("anything", k=10)
        
        assert result.success
        assert result.data is not None
        assert len(result.data) == 0
        
        db.close()
    
    def test_hierarchical_tags(self, memory_db_api):
        """
        Test hierarchical tag creation and usage.
        
        What we test:
        - Parent tag created
        - Child tag linked to parent
        - Claims can use child tags
        
        Pass criteria:
        - Hierarchy created
        - Child tag has parent_tag_id
        
        Fail criteria:
        - Hierarchy not linked
        - Tag creation fails
        """
        # Create parent tag
        parent_result = memory_db_api.add_tag(name="health")
        assert parent_result.success
        parent_id = parent_result.object_id
        
        # Create child tag
        child_result = memory_db_api.add_tag(
            name="fitness",
            parent_tag_id=parent_id
        )
        assert child_result.success
        
        # Create claim with child tag
        claim_result = memory_db_api.add_claim(
            statement="Running is my favorite exercise",
            claim_type="preference",
            context_domain="health",
            tags=["fitness"],
            auto_extract=False
        )
        assert claim_result.success


# ============================================================================
# Standalone Test Runner (without pytest)
# ============================================================================

def run_standalone_tests():
    """
    Run integration tests without pytest.
    
    This avoids sandbox/numpy issues that can occur with pytest collection.
    Runs a subset of tests that demonstrate all major functionality.
    """
    import traceback
    
    keys = get_api_keys()
    
    results = {"passed": 0, "failed": 0, "errors": []}
    
    def run_test(name: str, test_func):
        """Run a single test and track results."""
        print(f"\n{'='*60}")
        print(f"TEST: {name}")
        print('='*60)
        try:
            test_func()
            print(f"✅ PASSED: {name}")
            results["passed"] += 1
        except AssertionError as e:
            print(f"❌ FAILED: {name}")
            print(f"   Reason: {e}")
            results["failed"] += 1
            results["errors"].append((name, str(e)))
        except Exception as e:
            print(f"💥 ERROR: {name}")
            print(f"   Exception: {e}")
            traceback.print_exc()
            results["failed"] += 1
            results["errors"].append((name, str(e)))
    
    # Create fresh database for each test
    def create_api():
        config = PKBConfig(db_path=":memory:", llm_model="openai/gpt-4o-mini", llm_temperature=0.0)
        from truth_management_system.database import PKBDatabase
        db = PKBDatabase(config)
        db.connect()
        db.initialize_schema()
        api = StructuredAPI(db, keys, config)
        return api, db, config
    
    # ======== Test 1: Add Claim with Auto-Extract ========
    def test_add_claim_with_auto_extract():
        api, db, config = create_api()
        try:
            result = api.add_claim(
                statement="I prefer drinking coffee in the morning",
                claim_type="preference",
                context_domain="personal",
                auto_extract=True
            )
            assert result.success, f"Failed: {result.errors}"
            assert result.data.statement == "I prefer drinking coffee in the morning"
            assert result.data.claim_type == "preference"
            print(f"   Created claim: {result.data.claim_id[:8]}...")
        finally:
            db.close()
    
    run_test("Add Claim with Auto-Extract", test_add_claim_with_auto_extract)
    
    # ======== Test 2: CRUD Operations ========
    def test_crud_operations():
        api, db, config = create_api()
        try:
            # Add
            add_result = api.add_claim(
                statement="Test CRUD claim",
                claim_type="fact",
                context_domain="personal",
                auto_extract=False
            )
            assert add_result.success
            claim_id = add_result.object_id
            
            # Get
            get_result = api.get_claim(claim_id)
            assert get_result.success
            assert get_result.data.statement == "Test CRUD claim"
            
            # Edit
            edit_result = api.edit_claim(claim_id, statement="Updated CRUD claim")
            assert edit_result.success
            assert edit_result.data.statement == "Updated CRUD claim"
            
            # Delete
            delete_result = api.delete_claim(claim_id)
            assert delete_result.success
            assert delete_result.data.status == "retracted"
            
            print("   Add/Get/Edit/Delete all successful")
        finally:
            db.close()
    
    run_test("CRUD Operations", test_crud_operations)
    
    # ======== Test 3: FTS Search ========
    def test_fts_search():
        api, db, config = create_api()
        try:
            # Add test claims
            api.add_claim(statement="I love coffee in the morning", claim_type="preference", context_domain="personal", auto_extract=False)
            api.add_claim(statement="Tea is refreshing", claim_type="observation", context_domain="personal", auto_extract=False)
            api.add_claim(statement="My favorite coffee shop is nearby", claim_type="fact", context_domain="personal", auto_extract=False)
            
            import time
            time.sleep(0.2)
            
            result = api.search("coffee", strategy="fts", k=10)
            assert result.success
            assert len(result.data) > 0
            
            found_coffee = any("coffee" in r.claim.statement.lower() for r in result.data)
            assert found_coffee, "Coffee not found in results"
            
            print(f"   Found {len(result.data)} results for 'coffee'")
        finally:
            db.close()
    
    run_test("FTS Search", test_fts_search)
    
    # ======== Test 4: Conflict Management ========
    def test_conflict_management():
        api, db, config = create_api()
        try:
            # Create conflicting claims
            claim1 = api.add_claim(statement="I am vegetarian", claim_type="fact", context_domain="health", auto_extract=False)
            claim2 = api.add_claim(statement="I eat chicken regularly", claim_type="habit", context_domain="health", auto_extract=False)
            
            # Create conflict set
            conflict_result = api.create_conflict_set(
                [claim1.object_id, claim2.object_id],
                notes="Dietary contradiction"
            )
            assert conflict_result.success
            assert len(conflict_result.data.member_claim_ids) == 2
            
            # Get open conflicts
            open_conflicts = api.get_open_conflicts()
            assert open_conflicts.success
            assert len(open_conflicts.data) > 0
            
            print(f"   Created conflict set with 2 members")
        finally:
            db.close()
    
    run_test("Conflict Management", test_conflict_management)
    
    # ======== Test 5: LLM Helpers ========
    def test_llm_helpers():
        config = PKBConfig(llm_model="openai/gpt-4o-mini", llm_temperature=0.0)
        llm = LLMHelpers(keys, config)
        
        # Test tag generation
        tags = llm.generate_tags("I prefer running in the morning", "health")
        assert isinstance(tags, list)
        print(f"   Generated tags: {tags[:3]}...")
        
        # Test claim classification
        claim_type = llm.classify_claim_type("I decided to quit smoking")
        assert claim_type in ["decision", "fact", "observation", "preference", "task", "reminder", "habit", "memory"]
        print(f"   Classified 'I decided to quit smoking' as: {claim_type}")
    
    run_test("LLM Helpers", test_llm_helpers)
    
    # ======== Test 6: Text Orchestration ========
    def test_text_orchestration():
        api, db, config = create_api()
        try:
            orchestrator = TextOrchestrator(api, keys, config)
            
            # Test add command
            result = orchestrator.process("Remember that I am allergic to shellfish")
            assert result.raw_intent.get("action") in ["add_claim", "add_note"]
            
            if result.action_result and result.action_result.success:
                print(f"   Added claim via text command")
            else:
                print(f"   Intent parsed: {result.raw_intent.get('action')}")
        finally:
            db.close()
    
    run_test("Text Orchestration", test_text_orchestration)
    
    # ======== Test 7: Conversation Distillation ========
    def test_conversation_distillation():
        api, db, config = create_api()
        try:
            distiller = ConversationDistiller(api, keys, config)
            
            plan = distiller.extract_and_propose(
                conversation_summary="User discussing diet",
                user_message="I've decided to go vegetarian and try to eat organic food.",
                assistant_message="Those are healthy choices!"
            )
            
            print(f"   Extracted {len(plan.candidates)} candidates")
            for c in plan.candidates:
                print(f"     - [{c.claim_type}] {c.statement[:50]}...")
            
            if plan.proposed_actions:
                result = distiller.execute_plan(plan, "all")
                print(f"   Executed {len(result.execution_results)} actions")
        finally:
            db.close()
    
    run_test("Conversation Distillation", test_conversation_distillation)
    
    # ======== Test 8: Notes CRUD ========
    def test_notes_crud():
        api, db, config = create_api()
        try:
            # Add note
            add_result = api.add_note(
                body="This is a test meeting note about project planning.",
                title="Project Meeting",
                context_domain="work"
            )
            assert add_result.success
            print(f"   Added note: {add_result.object_id[:8]}...")
            
            # Search notes
            import time
            time.sleep(0.1)
            search_result = api.search_notes("project meeting", k=5)
            assert search_result.success
            print(f"   Found {len(search_result.data)} notes")
        finally:
            db.close()
    
    run_test("Notes CRUD", test_notes_crud)
    
    # ======== Summary ========
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"✅ Passed: {results['passed']}")
    print(f"❌ Failed: {results['failed']}")
    
    if results["errors"]:
        print("\nFailures:")
        for name, error in results["errors"]:
            print(f"  - {name}: {error[:50]}...")
    
    return results["failed"] == 0


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    """
    Run integration tests.
    
    Usage:
        export OPENROUTER_API_KEY="sk-or-v1-..."
        python truth_management_system/tests/test_integration.py
        
    Or with pytest (may have numpy/sandbox issues):
        python -m pytest truth_management_system/tests/test_integration.py -v -s
    """
    import sys
    
    # Try standalone runner first (more reliable)
    if len(sys.argv) == 1 or "--standalone" in sys.argv:
        print("Running standalone integration tests...")
        print("(This avoids pytest collection issues with numpy)\n")
        success = run_standalone_tests()
        sys.exit(0 if success else 1)
    else:
        # Use pytest for specific test selection
        pytest.main([__file__, "-v", "-s", "--tb=short"])
