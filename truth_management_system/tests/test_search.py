"""
Tests for search strategies.

Run with: python -m pytest truth_management_system/tests/test_search.py -v
"""

import pytest
from truth_management_system import (
    PKBConfig, get_memory_database,
    ClaimCRUD, Claim,
    ClaimType, ContextDomain,
    FTSSearchStrategy, SearchFilters,
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
def populated_db(db):
    """Create database with sample claims."""
    crud = ClaimCRUD(db)
    
    claims = [
        ("I prefer morning workouts", "preference", "health"),
        ("My favorite color is blue", "preference", "personal"),
        ("I decided to learn Python", "decision", "learning"),
        ("Mom's birthday is March 15", "fact", "relationships"),
        ("Buy groceries this weekend", "task", "life_ops"),
        ("I enjoy running in the park", "memory", "health"),
    ]
    
    for statement, claim_type, domain in claims:
        claim = Claim.create(
            statement=statement,
            claim_type=claim_type,
            context_domain=domain
        )
        crud.add(claim)
    
    return db


class TestFTSSearch:
    """Tests for FTS search strategy."""
    
    def test_basic_search(self, populated_db):
        """Test basic FTS search."""
        fts = FTSSearchStrategy(populated_db)
        
        results = fts.search("workout", k=5)
        
        assert len(results) > 0
        assert "workout" in results[0].claim.statement.lower()
    
    def test_search_with_filters(self, populated_db):
        """Test search with domain filter."""
        fts = FTSSearchStrategy(populated_db)
        
        filters = SearchFilters(context_domains=["health"])
        results = fts.search("morning running", k=10, filters=filters)
        
        for result in results:
            assert result.claim.context_domain == "health"
    
    def test_empty_results(self, populated_db):
        """Test search returning no results."""
        fts = FTSSearchStrategy(populated_db)
        
        results = fts.search("xyznonexistent123", k=5)
        
        assert len(results) == 0
    
    def test_multi_word_search(self, populated_db):
        """Test multi-word search query."""
        fts = FTSSearchStrategy(populated_db)
        
        results = fts.search("favorite color blue", k=5)
        
        assert len(results) > 0


class TestSearchFilters:
    """Tests for SearchFilters."""
    
    def test_default_filters(self):
        """Test default filter values."""
        filters = SearchFilters()
        
        assert "active" in filters.statuses
        assert "contested" in filters.statuses
        assert filters.include_contested is True
    
    def test_custom_filters(self):
        """Test custom filter values."""
        filters = SearchFilters(
            context_domains=["health", "fitness"],
            claim_types=["preference"],
            include_contested=False
        )
        
        assert filters.context_domains == ["health", "fitness"]
        assert filters.claim_types == ["preference"]
    
    def test_to_sql_conditions(self):
        """Test SQL condition generation."""
        filters = SearchFilters(
            context_domains=["health"],
            statuses=["active"]
        )
        
        conditions, params = filters.to_sql_conditions()
        
        assert len(conditions) > 0
        assert len(params) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
