## Implementation Details: `fts_search.py`

### Sanitization Strategy
- `_sanitize_query()`:
  - Strips column scoping (`foo:bar`) and hyphens.
  - Removes non-word characters.
  - Builds an FTS query as: `"full phrase" OR token* OR token* ...`.
  - Reserved keywords (`AND`, `OR`, `NOT`, `NEAR`) are quoted to avoid FTS operator parsing.

- `_sanitize_query_strict()`:
  - Fallback sanitizer used when FTS5 reports syntax errors.
  - Drops reserved keywords entirely and rebuilds a minimal OR query.
  - Returns empty string if no usable tokens remain.

### Error Handling
- Catches `sqlite3.OperationalError`.
- If the error indicates a syntax error, logs:
  - Original query, sanitized query, strict query, sanitizer version.
  - Retries with strict query (if it differs and is not empty).
- Existing retry path for `"no such column"` is retained.

### Logging
- Uses `time_logger` for guaranteed visibility.
- Logs execution parameters (`fts_query`, `k`, filters) and failure diagnostics.
