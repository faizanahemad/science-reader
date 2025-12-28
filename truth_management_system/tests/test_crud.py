"""
Tests for CRUD operations.

Run with: python -m pytest truth_management_system/tests/test_crud.py -v
"""

import pytest
from truth_management_system import (
    PKBConfig, get_memory_database,
    ClaimCRUD, NoteCRUD, EntityCRUD, TagCRUD, ConflictCRUD,
    Claim, Note, Entity, Tag,
    ClaimType, ClaimStatus, EntityType, ContextDomain,
)


@pytest.fixture(scope="function")
def db():
    """Create fresh in-memory database for each test."""
    # Each call creates a new in-memory database
    from truth_management_system.config import PKBConfig
    from truth_management_system.database import PKBDatabase
    
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return db


@pytest.fixture
def claim_crud(db):
    return ClaimCRUD(db)


@pytest.fixture
def note_crud(db):
    return NoteCRUD(db)


@pytest.fixture
def entity_crud(db):
    return EntityCRUD(db)


@pytest.fixture
def tag_crud(db):
    return TagCRUD(db)


@pytest.fixture
def conflict_crud(db):
    return ConflictCRUD(db)


class TestClaimCRUD:
    """Tests for ClaimCRUD."""
    
    def test_add_claim(self, claim_crud):
        """Test adding a claim."""
        claim = Claim.create(
            statement="I prefer morning workouts",
            claim_type=ClaimType.PREFERENCE.value,
            context_domain=ContextDomain.HEALTH.value
        )
        
        result = claim_crud.add(claim)
        
        assert result.claim_id == claim.claim_id
        assert result.statement == "I prefer morning workouts"
        assert result.claim_type == "preference"
    
    def test_get_claim(self, claim_crud):
        """Test getting a claim by ID."""
        claim = Claim.create(
            statement="Test claim",
            claim_type=ClaimType.FACT.value,
            context_domain=ContextDomain.PERSONAL.value
        )
        claim_crud.add(claim)
        
        result = claim_crud.get(claim.claim_id)
        
        assert result is not None
        assert result.claim_id == claim.claim_id
    
    def test_edit_claim(self, claim_crud):
        """Test editing a claim."""
        claim = Claim.create(
            statement="Original statement",
            claim_type=ClaimType.FACT.value,
            context_domain=ContextDomain.PERSONAL.value
        )
        claim_crud.add(claim)
        
        result = claim_crud.edit(claim.claim_id, {"statement": "Updated statement"})
        
        assert result.statement == "Updated statement"
    
    def test_delete_claim(self, claim_crud):
        """Test soft-deleting a claim."""
        claim = Claim.create(
            statement="To be deleted",
            claim_type=ClaimType.FACT.value,
            context_domain=ContextDomain.PERSONAL.value
        )
        claim_crud.add(claim)
        
        result = claim_crud.delete(claim.claim_id)
        
        assert result.status == ClaimStatus.RETRACTED.value
        assert result.retracted_at is not None
    
    def test_add_claim_with_tags(self, claim_crud):
        """Test adding claim with tags."""
        claim = Claim.create(
            statement="Tagged claim",
            claim_type=ClaimType.FACT.value,
            context_domain=ContextDomain.PERSONAL.value
        )
        
        result = claim_crud.add(claim, tags=["fitness", "health"])
        
        assert result is not None
    
    def test_list_claims(self, claim_crud):
        """Test listing claims with filters."""
        import uuid
        unique_prefix = f"ListTest_{uuid.uuid4().hex[:8]}"
        
        for i in range(5):
            claim = Claim.create(
                statement=f"{unique_prefix}_claim_{i}",
                claim_type=ClaimType.FACT.value,
                context_domain=ContextDomain.PERSONAL.value
            )
            claim_crud.add(claim)
        
        # Verify we can find our claims
        all_claims = claim_crud.list(limit=1000)
        our_claims = [c for c in all_claims if unique_prefix in c.statement]
        
        assert len(our_claims) == 5


class TestNoteCRUD:
    """Tests for NoteCRUD."""
    
    def test_add_note(self, note_crud):
        """Test adding a note."""
        note = Note.create(
            body="This is a test note",
            title="Test Note"
        )
        
        result = note_crud.add(note)
        
        assert result.note_id == note.note_id
        assert result.body == "This is a test note"
    
    def test_edit_note(self, note_crud):
        """Test editing a note."""
        note = Note.create(body="Original body", title="Title")
        note_crud.add(note)
        
        result = note_crud.edit(note.note_id, {"body": "Updated body"})
        
        assert result.body == "Updated body"
    
    def test_delete_note(self, note_crud):
        """Test deleting a note."""
        note = Note.create(body="To delete")
        note_crud.add(note)
        
        result = note_crud.delete(note.note_id)
        
        assert result is True
        assert note_crud.get(note.note_id) is None


class TestEntityCRUD:
    """Tests for EntityCRUD."""
    
    def test_add_entity(self, entity_crud):
        """Test adding an entity."""
        import uuid
        unique_name = f"TestPerson_{uuid.uuid4().hex[:8]}"
        entity = Entity.create(
            name=unique_name,
            entity_type=EntityType.PERSON.value
        )
        
        result = entity_crud.add(entity)
        
        assert result.name == unique_name
        assert result.entity_type == "person"
    
    def test_get_or_create_entity(self, entity_crud):
        """Test get_or_create."""
        import uuid
        unique_name = f"TestOrg_{uuid.uuid4().hex[:8]}"
        
        # First call creates
        entity1, created1 = entity_crud.get_or_create(unique_name, EntityType.ORG.value)
        assert created1 is True
        
        # Second call gets
        entity2, created2 = entity_crud.get_or_create(unique_name, EntityType.ORG.value)
        assert created2 is False
        assert entity1.entity_id == entity2.entity_id


class TestTagCRUD:
    """Tests for TagCRUD."""
    
    def test_add_tag(self, tag_crud):
        """Test adding a tag."""
        tag = Tag.create(name="fitness")
        
        result = tag_crud.add(tag)
        
        assert result.name == "fitness"
    
    def test_tag_hierarchy(self, tag_crud):
        """Test tag hierarchy."""
        parent = Tag.create(name="health")
        tag_crud.add(parent)
        
        child = Tag.create(name="fitness", parent_tag_id=parent.tag_id)
        tag_crud.add(child)
        
        hierarchy = tag_crud.get_hierarchy(child.tag_id)
        
        assert len(hierarchy) == 2
        assert hierarchy[0].name == "health"
        assert hierarchy[1].name == "fitness"
    
    def test_cycle_detection(self, tag_crud):
        """Test that cycles are detected."""
        tag1 = Tag.create(name="tag1")
        tag_crud.add(tag1)
        
        tag2 = Tag.create(name="tag2", parent_tag_id=tag1.tag_id)
        tag_crud.add(tag2)
        
        # Try to make tag1 a child of tag2 (would create cycle)
        with pytest.raises(ValueError, match="[Cc]ycle"):
            tag_crud.edit(tag1.tag_id, {"parent_tag_id": tag2.tag_id})


class TestConflictCRUD:
    """Tests for ConflictCRUD."""
    
    def test_create_conflict(self, claim_crud, conflict_crud):
        """Test creating a conflict set."""
        claim1 = Claim.create(
            statement="I like coffee",
            claim_type=ClaimType.PREFERENCE.value,
            context_domain=ContextDomain.PERSONAL.value
        )
        claim2 = Claim.create(
            statement="I don't like coffee",
            claim_type=ClaimType.PREFERENCE.value,
            context_domain=ContextDomain.PERSONAL.value
        )
        
        claim_crud.add(claim1)
        claim_crud.add(claim2)
        
        conflict = conflict_crud.create([claim1.claim_id, claim2.claim_id])
        
        assert len(conflict.member_claim_ids) == 2
        
        # Claims should now be contested
        c1 = claim_crud.get(claim1.claim_id)
        c2 = claim_crud.get(claim2.claim_id)
        assert c1.status == ClaimStatus.CONTESTED.value
        assert c2.status == ClaimStatus.CONTESTED.value
    
    def test_resolve_conflict(self, claim_crud, conflict_crud):
        """Test resolving a conflict set."""
        claim1 = Claim.create(
            statement="Claim 1",
            claim_type=ClaimType.FACT.value,
            context_domain=ContextDomain.PERSONAL.value
        )
        claim2 = Claim.create(
            statement="Claim 2",
            claim_type=ClaimType.FACT.value,
            context_domain=ContextDomain.PERSONAL.value
        )
        
        claim_crud.add(claim1)
        claim_crud.add(claim2)
        
        conflict = conflict_crud.create([claim1.claim_id, claim2.claim_id])
        
        result = conflict_crud.resolve(
            conflict.conflict_set_id,
            "Claim 1 is correct",
            winning_claim_id=claim1.claim_id
        )
        
        assert result.status == "resolved"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
