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
def db(tmp_path):
    """Create fresh database for each test."""
    from truth_management_system.config import PKBConfig
    from truth_management_system.database import PKBDatabase

    # Use a unique on-disk path to avoid SQLite ':memory:' special-case pitfalls
    # and potential cross-test contamination.
    config = PKBConfig(db_path=str(tmp_path / "pkb_test.sqlite"))
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

    def test_colon_token_does_not_break_fts(self, populated_db):
        """
        Regression: user queries sometimes contain trailing colon tokens (e.g. 'Opus: ...').
        SQLite FTS5 can interpret `token:` as a column scope and error if token isn't a real
        FTS column. We sanitize colons away and should never raise.
        """
        fts = FTSSearchStrategy(populated_db)
        results = fts.search("opus: hello world", k=5)
        assert isinstance(results, list)

    def test_hyphenated_token_does_not_break_fts(self, populated_db):
        """
        Regression: model names often include hyphens (e.g. 'claude-opus-4.5').
        SQLite FTS5 can interpret '-' as an operator; we sanitize hyphens to spaces
        so MATCH never raises OperationalError like 'no such column: opus'.
        """
        fts = FTSSearchStrategy(populated_db)
        results = fts.search("claude-opus-4.5", k=5)
        assert isinstance(results, list)

    def test_search_by_column_rejects_unknown_column(self, populated_db):
        """Regression: search_by_column should validate column names."""
        fts = FTSSearchStrategy(populated_db)
        with pytest.raises(ValueError):
            fts.search_by_column("opus", "hello", k=5)


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
