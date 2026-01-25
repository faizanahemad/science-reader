## Public Interface: `fts_search.py`

### `FTSSearchStrategy`
- `__init__(db: PKBDatabase)`
  - Create a full-text search strategy bound to a PKB database.
- `name() -> str`
  - Returns the strategy name: `"fts"`.
- `search(query: str, k: int = 20, filters: SearchFilters | None = None) -> List[SearchResult]`
  - Execute FTS5/BM25 search with optional filters and returns ranked results.
- `search_exact_phrase(phrase: str, k: int = 20, filters: SearchFilters | None = None) -> List[SearchResult]`
  - Search for an exact phrase match (no token expansion).

### Notes
- Uses internal sanitization to produce safe FTS5 queries.
- Provides fallback behavior and logging for FTS5 syntax errors.
