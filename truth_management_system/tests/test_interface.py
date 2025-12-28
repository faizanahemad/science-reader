"""
Tests for interface layer.

Run with: python -m pytest truth_management_system/tests/test_interface.py -v
"""

import pytest
from truth_management_system import (
    PKBConfig, get_memory_database,
    StructuredAPI, ActionResult,
)


@pytest.fixture(scope="function")
def db():
    """Create fresh in-memory database for each test."""
    from truth_management_system.config import PKBConfig
    from truth_management_system.database import PKBDatabase
    
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return db


@pytest.fixture
def api(db):
    """Create StructuredAPI without LLM keys."""
    config = PKBConfig()
    keys = {}  # No API key for testing
    return StructuredAPI(db, keys, config)


class TestStructuredAPI:
    """Tests for StructuredAPI."""
    
    def test_add_claim(self, api):
        """Test adding a claim via API."""
        result = api.add_claim(
            statement="Test claim",
            claim_type="fact",
            context_domain="personal",
            auto_extract=False  # Disable LLM extraction for tests
        )
        
        assert result.success is True
        assert result.object_id is not None
        assert result.data is not None
    
    def test_get_claim(self, api):
        """Test getting a claim via API."""
        # First add
        add_result = api.add_claim(
            statement="Get test",
            claim_type="fact",
            context_domain="personal",
            auto_extract=False
        )
        
        # Then get
        get_result = api.get_claim(add_result.object_id)
        
        assert get_result.success is True
        assert get_result.data.statement == "Get test"
    
    def test_edit_claim(self, api):
        """Test editing a claim via API."""
        add_result = api.add_claim(
            statement="Original",
            claim_type="fact",
            context_domain="personal",
            auto_extract=False
        )
        
        edit_result = api.edit_claim(
            add_result.object_id,
            statement="Updated"
        )
        
        assert edit_result.success is True
        assert edit_result.data.statement == "Updated"
    
    def test_delete_claim(self, api):
        """Test deleting a claim via API."""
        add_result = api.add_claim(
            statement="To delete",
            claim_type="fact",
            context_domain="personal",
            auto_extract=False
        )
        
        delete_result = api.delete_claim(add_result.object_id)
        
        assert delete_result.success is True
        assert delete_result.data.status == "retracted"
    
    def test_search_claims(self, api):
        """Test searching claims via API."""
        # Add some claims
        for statement in ["I like coffee", "I prefer tea", "Coffee is great"]:
            api.add_claim(
                statement=statement,
                claim_type="preference",
                context_domain="personal",
                auto_extract=False
            )
        
        # Search
        result = api.search("coffee", k=10)
        
        assert result.success is True
        assert len(result.data) > 0
    
    def test_add_note(self, api):
        """Test adding a note via API."""
        result = api.add_note(
            body="This is a test note",
            title="Test"
        )
        
        assert result.success is True
        assert result.object_id is not None
    
    def test_add_entity(self, api):
        """Test adding an entity via API."""
        import uuid
        unique_name = f"TestPerson_{uuid.uuid4().hex[:8]}"
        result = api.add_entity(
            name=unique_name,
            entity_type="person"
        )
        
        assert result.success is True
        assert result.data.name == unique_name
    
    def test_add_tag(self, api):
        """Test adding a tag via API."""
        result = api.add_tag(name="test_tag")
        
        assert result.success is True
        assert result.data.name == "test_tag"
    
    def test_create_conflict_set(self, api):
        """Test creating a conflict set via API."""
        # Add two conflicting claims
        claim1 = api.add_claim(
            statement="I like X",
            claim_type="preference",
            context_domain="personal",
            auto_extract=False
        )
        claim2 = api.add_claim(
            statement="I don't like X",
            claim_type="preference",
            context_domain="personal",
            auto_extract=False
        )
        
        # Create conflict
        result = api.create_conflict_set([claim1.object_id, claim2.object_id])
        
        assert result.success is True
        assert len(result.data.member_claim_ids) == 2


class TestActionResult:
    """Tests for ActionResult dataclass."""
    
    def test_success_result(self):
        """Test successful action result."""
        result = ActionResult(
            success=True,
            action="add",
            object_type="claim",
            object_id="123",
            data={"test": "data"}
        )
        
        assert result.success is True
        assert result.errors == []
    
    def test_failure_result(self):
        """Test failed action result."""
        result = ActionResult(
            success=False,
            action="add",
            object_type="claim",
            errors=["Something went wrong"]
        )
        
        assert result.success is False
        assert len(result.errors) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
