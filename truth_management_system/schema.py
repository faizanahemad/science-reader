"""
SQLite schema definition for PKB v0.

Defines the complete database schema including:
- claims: Atomic memory units
- notes: Narrative content
- entities: Canonical references (people, places, topics)
- tags: Hierarchical labels
- claim_tags: Many-to-many claim-tag links
- claim_entities: Many-to-many claim-entity links with role
- conflict_sets: Groups of contradicting claims
- conflict_set_members: Conflict set membership
- claim_embeddings: Vector embeddings for similarity search
- claims_fts: FTS5 virtual table for full-text search on claims
- notes_fts: FTS5 virtual table for full-text search on notes

All tables use:
- TEXT primary keys (UUIDs)
- ISO 8601 timestamps as TEXT
- JSON stored as TEXT in meta_json columns
- Soft deletion via retracted_at timestamp
"""

SCHEMA_VERSION = 6  # v6: Added possible_questions column for QnA-style claims


# =============================================================================
# Core Tables DDL
# =============================================================================

TABLES_DDL = """
-- =============================================================================
-- Claims: Atomic memory units
-- =============================================================================
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    user_email TEXT,                    -- Owner email for multi-user support (NULL = global/system)
    claim_number INTEGER,               -- Per-user auto-incremented numeric ID (v5), referenceable as @claim_N
    friendly_id TEXT,                   -- User-facing alphanumeric ID (auto-generated or user-specified)
    claim_type TEXT NOT NULL,           -- fact|memory|decision|preference|task|reminder|habit|observation
    claim_types TEXT,                   -- JSON array of all types (e.g. '["preference","fact"]')
    statement TEXT NOT NULL,
    subject_text TEXT,                  -- SPO subject (optional extraction)
    predicate TEXT,                     -- SPO predicate (optional extraction)
    object_text TEXT,                   -- SPO object (optional extraction)
    context_domain TEXT NOT NULL,       -- personal|health|relationships|learning|life_ops|work|finance
    context_domains TEXT,               -- JSON array of all domains (e.g. '["health","personal"]')
    status TEXT NOT NULL DEFAULT 'active',  -- active|contested|historical|superseded|retracted|draft
    confidence REAL,                    -- Confidence score 0.0-1.0
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    valid_from TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z',
    valid_to TEXT,                      -- NULL means no end date
    meta_json TEXT,                     -- JSON: {keywords, source, visibility, llm}
    retracted_at TEXT,                  -- Soft delete timestamp
    possible_questions TEXT             -- JSON array of questions this claim answers (v6)
);

-- =============================================================================
-- Notes: Narrative storage
-- =============================================================================
CREATE TABLE IF NOT EXISTS notes (
    note_id TEXT PRIMARY KEY,
    user_email TEXT,                    -- Owner email for multi-user support
    title TEXT,
    body TEXT NOT NULL,
    context_domain TEXT,
    meta_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- =============================================================================
-- Entities: Canonical people/topics/projects
-- =============================================================================
CREATE TABLE IF NOT EXISTS entities (
    entity_id TEXT PRIMARY KEY,
    user_email TEXT,                    -- Owner email for multi-user support
    entity_type TEXT NOT NULL,          -- person|org|place|topic|project|system|other
    name TEXT NOT NULL,
    meta_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_email, entity_type, name)  -- Prevent duplicate entities per user
);

-- =============================================================================
-- Tags: Hierarchical labels
-- =============================================================================
CREATE TABLE IF NOT EXISTS tags (
    tag_id TEXT PRIMARY KEY,
    user_email TEXT,                    -- Owner email for multi-user support
    name TEXT NOT NULL,
    parent_tag_id TEXT REFERENCES tags(tag_id) ON DELETE SET NULL,
    meta_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_email, name, parent_tag_id)  -- Unique within same parent per user
);

-- =============================================================================
-- Join: claim_tags (many-to-many)
-- =============================================================================
CREATE TABLE IF NOT EXISTS claim_tags (
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
    PRIMARY KEY (claim_id, tag_id)
);

-- =============================================================================
-- Join: claim_entities (many-to-many with role)
-- =============================================================================
CREATE TABLE IF NOT EXISTS claim_entities (
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    role TEXT NOT NULL,                 -- subject|object|mentioned|about_person
    PRIMARY KEY (claim_id, entity_id, role)
);

-- =============================================================================
-- Conflict sets: Manual contradiction buckets
-- =============================================================================
CREATE TABLE IF NOT EXISTS conflict_sets (
    conflict_set_id TEXT PRIMARY KEY,
    user_email TEXT,                    -- Owner email for multi-user support
    status TEXT NOT NULL DEFAULT 'open', -- open|resolved|ignored
    resolution_notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- =============================================================================
-- Conflict set members
-- =============================================================================
CREATE TABLE IF NOT EXISTS conflict_set_members (
    conflict_set_id TEXT NOT NULL REFERENCES conflict_sets(conflict_set_id) ON DELETE CASCADE,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    PRIMARY KEY (conflict_set_id, claim_id)
);

-- =============================================================================
-- Embeddings storage (separate for efficient vector search)
-- =============================================================================
CREATE TABLE IF NOT EXISTS claim_embeddings (
    claim_id TEXT PRIMARY KEY REFERENCES claims(claim_id) ON DELETE CASCADE,
    embedding BLOB NOT NULL,            -- Numpy array serialized as bytes
    model_name TEXT NOT NULL,           -- Model used to generate embedding
    created_at TEXT NOT NULL
);

-- =============================================================================
-- Note embeddings storage
-- =============================================================================
CREATE TABLE IF NOT EXISTS note_embeddings (
    note_id TEXT PRIMARY KEY REFERENCES notes(note_id) ON DELETE CASCADE,
    embedding BLOB NOT NULL,
    model_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- =============================================================================
-- Contexts: Hierarchical grouping of claims (v3)
-- Contexts allow users to organize memories into named groups/collections.
-- A context can contain claims directly and/or child contexts, forming a tree.
-- Resolution: given a context_id, recursively collect all leaf claims.
-- =============================================================================
CREATE TABLE IF NOT EXISTS contexts (
    context_id TEXT PRIMARY KEY,
    user_email TEXT,
    friendly_id TEXT,                   -- User-facing alphanumeric ID
    name TEXT NOT NULL,                 -- Display name for the context
    description TEXT,                   -- Optional longer description
    parent_context_id TEXT REFERENCES contexts(context_id) ON DELETE SET NULL,
    meta_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_email, friendly_id)     -- Friendly IDs unique per user
);

-- =============================================================================
-- Context-Claims join: many-to-many linking contexts to claims (v3)
-- A claim can belong to multiple contexts.
-- =============================================================================
CREATE TABLE IF NOT EXISTS context_claims (
    context_id TEXT NOT NULL REFERENCES contexts(context_id) ON DELETE CASCADE,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    PRIMARY KEY (context_id, claim_id)
);

-- =============================================================================
-- Catalog tables for dynamic types and domains (v4)
-- These replace the hardcoded enums so users can add custom types/domains.
-- Rows with user_email IS NULL are system-provided defaults.
-- =============================================================================
CREATE TABLE IF NOT EXISTS claim_types_catalog (
    type_name TEXT NOT NULL,
    user_email TEXT DEFAULT '',
    display_name TEXT,
    description TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (type_name, user_email)
);

CREATE TABLE IF NOT EXISTS context_domains_catalog (
    domain_name TEXT NOT NULL,
    user_email TEXT DEFAULT '',
    display_name TEXT,
    description TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (domain_name, user_email)
);

-- =============================================================================
-- Schema version tracking
-- =============================================================================
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""


# =============================================================================
# Indexes DDL
# =============================================================================

INDEXES_DDL = """
-- Claims indexes (for common query patterns)
CREATE INDEX IF NOT EXISTS idx_claims_user_email ON claims(user_email);
CREATE INDEX IF NOT EXISTS idx_claims_user_status ON claims(user_email, status);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);
CREATE INDEX IF NOT EXISTS idx_claims_context_domain ON claims(context_domain);
CREATE INDEX IF NOT EXISTS idx_claims_claim_type ON claims(claim_type);
CREATE INDEX IF NOT EXISTS idx_claims_validity ON claims(valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_claims_predicate ON claims(predicate);
CREATE INDEX IF NOT EXISTS idx_claims_created_at ON claims(created_at);
CREATE INDEX IF NOT EXISTS idx_claims_updated_at ON claims(updated_at);

-- Notes indexes
CREATE INDEX IF NOT EXISTS idx_notes_user_email ON notes(user_email);
CREATE INDEX IF NOT EXISTS idx_notes_created_at ON notes(created_at);
CREATE INDEX IF NOT EXISTS idx_notes_context_domain ON notes(context_domain);

-- Entities indexes
CREATE INDEX IF NOT EXISTS idx_entities_user_email ON entities(user_email);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);

-- Tags indexes
CREATE INDEX IF NOT EXISTS idx_tags_user_email ON tags(user_email);
CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);
CREATE INDEX IF NOT EXISTS idx_tags_parent ON tags(parent_tag_id);

-- Join table indexes (for reverse lookup)
CREATE INDEX IF NOT EXISTS idx_claim_tags_tag_id ON claim_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_claim_entities_entity_id ON claim_entities(entity_id);
CREATE INDEX IF NOT EXISTS idx_claim_entities_role ON claim_entities(role);

-- Conflict set indexes
CREATE INDEX IF NOT EXISTS idx_conflict_sets_user_email ON conflict_sets(user_email);
CREATE INDEX IF NOT EXISTS idx_conflict_sets_status ON conflict_sets(status);
CREATE INDEX IF NOT EXISTS idx_conflict_set_members_claim_id ON conflict_set_members(claim_id);

-- v3 indexes for claims.friendly_id and contexts are created by the migration
-- or by _ensure_v3_indexes() during initialization. They are NOT included here
-- because for a v2 database, claims.friendly_id doesn't exist yet, and
-- executescript() would fail with "no such column: friendly_id".
"""


# =============================================================================
# FTS5 Virtual Tables DDL
# =============================================================================

FTS_DDL = """
-- FTS5 for claims (indexes: statement, predicate, object_text, subject_text, context_domain)
-- NOTE: For v3 databases, the migration adds the friendly_id column by
-- dropping and recreating this table. The DDL here uses the v2 column set
-- so that IF NOT EXISTS safely skips for existing v2 databases.
-- For fresh databases, the migration post-fixup upgrades the FTS table.
CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
    claim_id UNINDEXED,
    statement,
    predicate,
    object_text,
    subject_text,
    context_domain,
    content='claims',
    content_rowid='rowid'
);

-- FTS5 for notes (indexes: title, body, context_domain)
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    note_id UNINDEXED,
    title,
    body,
    context_domain,
    content='notes',
    content_rowid='rowid'
);
"""


# =============================================================================
# Triggers DDL (optional - for automatic FTS sync)
# These can be enabled if we want automatic sync instead of manual
# =============================================================================

FTS_TRIGGERS_DDL = """
-- Trigger: sync claims to FTS on insert (v2 column set - safe for both v2 and v3)
CREATE TRIGGER IF NOT EXISTS claims_ai AFTER INSERT ON claims BEGIN
    INSERT INTO claims_fts(rowid, claim_id, statement, predicate, object_text, subject_text, context_domain)
    VALUES (new.rowid, new.claim_id, new.statement, new.predicate, new.object_text, new.subject_text, new.context_domain);
END;

-- Trigger: sync claims to FTS on update
CREATE TRIGGER IF NOT EXISTS claims_au AFTER UPDATE ON claims BEGIN
    INSERT INTO claims_fts(claims_fts, rowid, claim_id, statement, predicate, object_text, subject_text, context_domain)
    VALUES ('delete', old.rowid, old.claim_id, old.statement, old.predicate, old.object_text, old.subject_text, old.context_domain);
    INSERT INTO claims_fts(rowid, claim_id, statement, predicate, object_text, subject_text, context_domain)
    VALUES (new.rowid, new.claim_id, new.statement, new.predicate, new.object_text, new.subject_text, new.context_domain);
END;

-- Trigger: sync claims to FTS on delete
CREATE TRIGGER IF NOT EXISTS claims_ad AFTER DELETE ON claims BEGIN
    INSERT INTO claims_fts(claims_fts, rowid, claim_id, statement, predicate, object_text, subject_text, context_domain)
    VALUES ('delete', old.rowid, old.claim_id, old.statement, old.predicate, old.object_text, old.subject_text, old.context_domain);
END;

-- Trigger: sync notes to FTS on insert
CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, note_id, title, body, context_domain)
    VALUES (new.rowid, new.note_id, new.title, new.body, new.context_domain);
END;

-- Trigger: sync notes to FTS on update
CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, note_id, title, body, context_domain)
    VALUES ('delete', old.rowid, old.note_id, old.title, old.body, old.context_domain);
    INSERT INTO notes_fts(rowid, note_id, title, body, context_domain)
    VALUES (new.rowid, new.note_id, new.title, new.body, new.context_domain);
END;

-- Trigger: sync notes to FTS on delete
CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, note_id, title, body, context_domain)
    VALUES ('delete', old.rowid, old.note_id, old.title, old.body, old.context_domain);
END;
"""


def get_all_ddl(include_triggers: bool = True) -> str:
    """
    Get complete DDL for database initialization.
    
    Args:
        include_triggers: Whether to include FTS sync triggers.
        
    Returns:
        Complete SQL DDL string.
    """
    ddl = TABLES_DDL + INDEXES_DDL + FTS_DDL
    if include_triggers:
        ddl += FTS_TRIGGERS_DDL
    return ddl


def get_tables_list() -> list:
    """
    Get list of all table names in schema.
    
    Returns:
        List of table names.
    """
    return [
        'claims', 'notes', 'entities', 'tags',
        'claim_tags', 'claim_entities',
        'conflict_sets', 'conflict_set_members',
        'claim_embeddings', 'note_embeddings',
        'contexts', 'context_claims',
        'schema_version'
    ]


def get_fts_tables_list() -> list:
    """
    Get list of FTS virtual table names.
    
    Returns:
        List of FTS table names.
    """
    return ['claims_fts', 'notes_fts']
