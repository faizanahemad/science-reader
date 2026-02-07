"""
Database connection and management for PKB v0.

Provides PKBDatabase class with:
- SQLite connection management with WAL mode
- Schema initialization (creates tables if missing)
- Transaction context manager for atomic operations
- Connection lifecycle management

Usage:
    config = PKBConfig(db_path="./my_kb.sqlite")
    db = get_database(config)
    
    with db.transaction() as conn:
        conn.execute("INSERT INTO claims ...")
"""

import os
import sqlite3
import logging
from contextlib import contextmanager
from typing import Optional, Generator

from .config import PKBConfig
from .schema import get_all_ddl, SCHEMA_VERSION
from .utils import now_iso

logger = logging.getLogger(__name__)


class PKBDatabase:
    """
    SQLite database manager with WAL mode and transaction support.
    
    Features:
    - Automatic schema initialization on first connect
    - WAL mode for better concurrent read performance
    - Foreign key enforcement
    - Row factory for dict-like row access
    - Transaction context manager for atomicity
    
    Attributes:
        config: PKBConfig instance with database settings.
        db_path: Fully expanded path to SQLite file.
    """
    
    def __init__(self, config: PKBConfig):
        """
        Initialize database manager.
        
        Args:
            config: PKBConfig with db_path and settings.
        """
        self.config = config
        self.db_path = config.expand_db_path()
        self._conn: Optional[sqlite3.Connection] = None
        self._initialized = False
    
    def connect(self) -> sqlite3.Connection:
        """
        Get or create database connection.
        
        Creates the database file and parent directories if they don't exist.
        Enables WAL mode and foreign keys on first connection.
        
        Returns:
            Active SQLite connection.
        """
        if self._conn is None:
            # Ensure parent directory exists
            db_dir = os.path.dirname(self.db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
            
            # Connect with row factory for dict-like access
            # Enable SQLite URI mode when db_path is a URI (e.g. file::memory:?cache=shared)
            use_uri = bool(self.db_path.startswith("file:"))
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,  # Allow multi-threaded access
                timeout=30.0,  # Wait up to 30s for locks
                uri=use_uri
            )
            self._conn.row_factory = sqlite3.Row
            
            # Enable WAL mode for better concurrent reads
            self._conn.execute("PRAGMA journal_mode=WAL")
            
            # Enable foreign key constraints
            self._conn.execute("PRAGMA foreign_keys=ON")
            
            # Optimize for single-user personal use
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            
            logger.info(f"Connected to database: {self.db_path}")
        
        return self._conn
    
    def initialize_schema(self, include_triggers: bool = True) -> None:
        """
        Initialize database schema if not already done.
        
        Creates all tables, indexes, FTS tables, and optionally triggers.
        Safe to call multiple times (uses IF NOT EXISTS).
        Handles migrations from older schema versions.
        
        Args:
            include_triggers: Include FTS sync triggers (recommended).
        """
        conn = self.connect()
        current_version = self.get_schema_version()

        # IMPORTANT:
        # `self._initialized` only reflects whether this *process* has run schema init,
        # not whether the on-disk DB is up-to-date with the current code's schema.
        # If the code is updated while the server keeps running, a previously
        # initialized v2 database must still be migrated to v3.
        if self._initialized and current_version is not None and current_version >= SCHEMA_VERSION:
            # Already initialized and DB version matches code version.
            # Skip full DDL/migration but do lightweight idempotent fixups.
            return
        
        try:
            # Execute all DDL statements (IF NOT EXISTS makes this safe)
            ddl = get_all_ddl(include_triggers=include_triggers)
            conn.executescript(ddl)

            # Ensure all claim columns exist even if schema_version is already current.
            # This guards against partially-upgraded databases and makes schema
            # initialization more resilient.
            try:
                cursor = conn.execute("PRAGMA table_info(claims)")
                existing_columns = [row[1] for row in cursor.fetchall()]
                for col_name, col_type in {
                    "friendly_id": "TEXT",
                    "claim_types": "TEXT",
                    "context_domains": "TEXT",
                    "claim_number": "INTEGER",
                    "possible_questions": "TEXT",
                }.items():
                    if col_name not in existing_columns:
                        conn.execute(f"ALTER TABLE claims ADD COLUMN {col_name} {col_type}")
                        logger.info(f"Added missing {col_name} column to claims")
            except Exception as e:
                logger.warning(f"Could not ensure claim columns: {e}")
            
            # Run migrations if upgrading from older version
            if current_version is not None and current_version < SCHEMA_VERSION:
                self._run_migrations(conn, current_version, SCHEMA_VERSION)
                # Reset column cache since migration may have added new columns
                try:
                    from .crud.claims import reset_claim_columns_cache
                    reset_claim_columns_cache()
                except ImportError:
                    pass
            
            # Ensure FTS table and triggers are at v3 level (handles both
            # fresh databases and databases that just went through migration).
            # This is idempotent - it checks before modifying.
            self._ensure_fts_v3(conn)
            
            # Ensure catalog tables are seeded with system defaults (idempotent).
            # Handles both fresh databases and databases upgraded from v3.
            self._ensure_catalog_seeded(conn)
            
            # Record schema version
            conn.execute("""
                INSERT OR REPLACE INTO schema_version (version, applied_at)
                VALUES (?, ?)
            """, (SCHEMA_VERSION, now_iso()))
            
            conn.commit()
            self._initialized = True
            logger.info(f"Initialized schema version {SCHEMA_VERSION}")
            
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Schema initialization failed: {e}")
            raise
    
    def _run_migrations(self, conn: sqlite3.Connection, from_version: int, to_version: int) -> None:
        """
        Run schema migrations from one version to another.
        
        Args:
            conn: Active database connection.
            from_version: Current schema version.
            to_version: Target schema version.
        """
        logger.info(f"Running migrations from v{from_version} to v{to_version}")
        
        # Migration from v1 to v2: Add user_email column
        if from_version < 2 <= to_version:
            self._migrate_v1_to_v2(conn)
        
        # Migration from v2 to v3: Add friendly_id, multi-type/domain, contexts
        if from_version < 3 <= to_version:
            self._migrate_v2_to_v3(conn)
        
        # Migration from v3 to v4: Add catalog tables for dynamic types/domains
        if from_version < 4 <= to_version:
            self._migrate_v3_to_v4(conn)
        
        # Migration from v4 to v5: Add claim_number column
        if from_version < 5 <= to_version:
            self._migrate_v4_to_v5(conn)
        
        # Migration from v5 to v6: Add possible_questions column
        if from_version < 6 <= to_version:
            self._migrate_v5_to_v6(conn)
    
    def _migrate_v1_to_v2(self, conn: sqlite3.Connection) -> None:
        """
        Migrate from schema v1 to v2: Add user_email column for multi-user support.
        
        Args:
            conn: Active database connection.
        """
        logger.info("Migrating to v2: Adding user_email columns")
        
        # Add user_email column to all tables that don't have it
        tables_to_migrate = ['claims', 'notes', 'entities', 'tags', 'conflict_sets']
        
        for table in tables_to_migrate:
            # Check if column exists
            cursor = conn.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'user_email' not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN user_email TEXT")
                logger.info(f"Added user_email column to {table}")
        
        # Create indexes for user_email if they don't exist
        conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_user_email ON claims(user_email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_user_status ON claims(user_email, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_user_email ON notes(user_email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_user_email ON entities(user_email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tags_user_email ON tags(user_email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conflict_sets_user_email ON conflict_sets(user_email)")
        
        logger.info("Migration to v2 complete")
    
    def _migrate_v2_to_v3(self, conn: sqlite3.Connection) -> None:
        """
        Migrate from schema v2 to v3: Add friendly_id, multi-type/domain, contexts.
        
        Changes:
        - Add friendly_id, claim_types, context_domains columns to claims
        - Create contexts and context_claims tables
        - Create new indexes
        - Backfill friendly_id for existing claims
        - Rebuild FTS index to include friendly_id column
        
        Args:
            conn: Active database connection.
        """
        logger.info("Migrating to v3: Adding friendly_id, multi-type/domain, contexts")
        
        # 1. Add new columns to claims if they don't exist
        cursor = conn.execute("PRAGMA table_info(claims)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        
        new_claim_columns = {
            'friendly_id': 'TEXT',
            'claim_types': 'TEXT',
            'context_domains': 'TEXT',
        }
        
        for col_name, col_type in new_claim_columns.items():
            if col_name not in existing_columns:
                conn.execute(f"ALTER TABLE claims ADD COLUMN {col_name} {col_type}")
                logger.info(f"Added {col_name} column to claims")
        
        # 2. Create contexts table if not exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contexts (
                context_id TEXT PRIMARY KEY,
                user_email TEXT,
                friendly_id TEXT,
                name TEXT NOT NULL,
                description TEXT,
                parent_context_id TEXT REFERENCES contexts(context_id) ON DELETE SET NULL,
                meta_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_email, friendly_id)
            )
        """)
        
        # 3. Create context_claims junction table if not exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS context_claims (
                context_id TEXT NOT NULL REFERENCES contexts(context_id) ON DELETE CASCADE,
                claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
                PRIMARY KEY (context_id, claim_id)
            )
        """)
        
        # 4. Create indexes
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_claims_user_friendly_id ON claims(user_email, friendly_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_friendly_id ON claims(friendly_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_contexts_user_email ON contexts(user_email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_contexts_friendly_id ON contexts(friendly_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_contexts_parent ON contexts(parent_context_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_context_claims_claim_id ON context_claims(claim_id)")
        
        # 5. Backfill friendly_id for existing claims that don't have one
        import json as _json
        from .utils import generate_friendly_id
        
        claims_without_fid = conn.execute(
            "SELECT claim_id, statement, claim_type, context_domain FROM claims WHERE friendly_id IS NULL"
        ).fetchall()
        
        if claims_without_fid:
            logger.info(f"Backfilling friendly_id for {len(claims_without_fid)} existing claims")
            for row in claims_without_fid:
                claim_id = row[0]
                statement = row[1]
                claim_type = row[2]
                context_domain = row[3]
                
                fid = generate_friendly_id(statement)
                types_json = _json.dumps([claim_type]) if claim_type else None
                domains_json = _json.dumps([context_domain]) if context_domain else None
                
                conn.execute(
                    "UPDATE claims SET friendly_id = ?, claim_types = ?, context_domains = ? WHERE claim_id = ?",
                    (fid, types_json, domains_json, claim_id)
                )
            logger.info(f"Backfilled friendly_id for {len(claims_without_fid)} claims")
        
        # 6. Rebuild FTS index to include friendly_id column
        # Drop old FTS triggers first
        for trigger_name in ['claims_ai', 'claims_au', 'claims_ad']:
            conn.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
        
        # Drop and recreate FTS table with friendly_id
        conn.execute("DROP TABLE IF EXISTS claims_fts")
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
                claim_id UNINDEXED,
                statement,
                predicate,
                object_text,
                subject_text,
                context_domain,
                friendly_id,
                content='claims',
                content_rowid='rowid'
            )
        """)
        
        # Recreate triggers with friendly_id
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS claims_ai AFTER INSERT ON claims BEGIN
                INSERT INTO claims_fts(rowid, claim_id, statement, predicate, object_text, subject_text, context_domain, friendly_id)
                VALUES (new.rowid, new.claim_id, new.statement, new.predicate, new.object_text, new.subject_text, new.context_domain, new.friendly_id);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS claims_au AFTER UPDATE ON claims BEGIN
                INSERT INTO claims_fts(claims_fts, rowid, claim_id, statement, predicate, object_text, subject_text, context_domain, friendly_id)
                VALUES ('delete', old.rowid, old.claim_id, old.statement, old.predicate, old.object_text, old.subject_text, old.context_domain, old.friendly_id);
                INSERT INTO claims_fts(rowid, claim_id, statement, predicate, object_text, subject_text, context_domain, friendly_id)
                VALUES (new.rowid, new.claim_id, new.statement, new.predicate, new.object_text, new.subject_text, new.context_domain, new.friendly_id);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS claims_ad AFTER DELETE ON claims BEGIN
                INSERT INTO claims_fts(claims_fts, rowid, claim_id, statement, predicate, object_text, subject_text, context_domain, friendly_id)
                VALUES ('delete', old.rowid, old.claim_id, old.statement, old.predicate, old.object_text, old.subject_text, old.context_domain, old.friendly_id);
            END
        """)
        
        # Rebuild FTS index from existing claims data
        conn.execute("""
            INSERT INTO claims_fts(rowid, claim_id, statement, predicate, object_text, subject_text, context_domain, friendly_id)
            SELECT rowid, claim_id, statement, predicate, object_text, subject_text, context_domain, friendly_id
            FROM claims
        """)
        
        logger.info("Migration to v3 complete")
    
    def _migrate_v3_to_v4(self, conn: sqlite3.Connection) -> None:
        """
        Migrate from schema v3 to v4: Add catalog tables for dynamic types and domains.
        
        Creates claim_types_catalog and context_domains_catalog tables and seeds
        them with the default system types/domains from the constants module.
        
        Args:
            conn: Active database connection.
        """
        logger.info("Migrating to v4: Adding claim_types_catalog and context_domains_catalog")
        
        # Create catalog tables (IF NOT EXISTS for safety)
        # user_email = '' means system-provided; non-empty = user-created
        conn.execute("""
            CREATE TABLE IF NOT EXISTS claim_types_catalog (
                type_name TEXT NOT NULL,
                user_email TEXT DEFAULT '',
                display_name TEXT,
                description TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (type_name, user_email)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS context_domains_catalog (
                domain_name TEXT NOT NULL,
                user_email TEXT DEFAULT '',
                display_name TEXT,
                description TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (domain_name, user_email)
            )
        """)
        
        # Seed with system defaults from constants
        from .constants import ClaimType, ContextDomain
        
        ts = now_iso()
        for ct in ClaimType:
            conn.execute(
                "INSERT OR IGNORE INTO claim_types_catalog (type_name, user_email, display_name, created_at) VALUES (?, '', ?, ?)",
                (ct.value, ct.value.capitalize(), ts)
            )
        
        for cd in ContextDomain:
            display = cd.value.replace('_', ' ').title()
            conn.execute(
                "INSERT OR IGNORE INTO context_domains_catalog (domain_name, user_email, display_name, created_at) VALUES (?, '', ?, ?)",
                (cd.value, display, ts)
            )
        
        logger.info("Migration to v4 complete")
    
    def _migrate_v4_to_v5(self, conn: sqlite3.Connection) -> None:
        """
        Migrate from schema v4 to v5: Add claim_number column.
        
        claim_number is a per-user auto-incremented numeric ID that provides
        a short, human-friendly way to reference claims (e.g., @claim_42).
        
        Args:
            conn: Active database connection.
        """
        logger.info("Migrating to v5: Adding claim_number column")
        
        # Add column if it doesn't exist
        cursor = conn.execute("PRAGMA table_info(claims)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        
        if 'claim_number' not in existing_columns:
            conn.execute("ALTER TABLE claims ADD COLUMN claim_number INTEGER")
            logger.info("Added claim_number column to claims")
        
        # Backfill: assign sequential numbers per user, ordered by created_at
        rows = conn.execute("""
            SELECT claim_id, user_email, created_at
            FROM claims
            WHERE claim_number IS NULL
            ORDER BY user_email, created_at
        """).fetchall()
        
        if rows:
            logger.info(f"Backfilling claim_number for {len(rows)} claims")
            # Group by user and assign sequential numbers
            user_counters = {}
            for row in rows:
                user = row[0 + 1] or ''  # user_email
                if user not in user_counters:
                    # Get max existing claim_number for this user
                    max_row = conn.execute(
                        "SELECT COALESCE(MAX(claim_number), 0) FROM claims WHERE COALESCE(user_email, '') = ?",
                        (user,)
                    ).fetchone()
                    user_counters[user] = max_row[0] if max_row else 0
                user_counters[user] += 1
                conn.execute(
                    "UPDATE claims SET claim_number = ? WHERE claim_id = ?",
                    (user_counters[user], row[0])
                )
            logger.info(f"Backfilled claim_number for {len(rows)} claims")
        
        # Create index for claim_number lookups
        conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_user_claim_number ON claims(user_email, claim_number)")
        
        logger.info("Migration to v5 complete")
    
    def _migrate_v5_to_v6(self, conn: sqlite3.Connection) -> None:
        """
        Migrate from schema v5 to v6: Add possible_questions column to claims.
        
        possible_questions stores a JSON array of questions that this claim
        answers, enabling QnA-style search and retrieval. Also updates the
        FTS index to include possible_questions for full-text searchability.
        
        Args:
            conn: Active database connection.
        """
        logger.info("Migrating to v6: Adding possible_questions column")
        
        cursor = conn.execute("PRAGMA table_info(claims)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        
        if 'possible_questions' not in existing_columns:
            conn.execute("ALTER TABLE claims ADD COLUMN possible_questions TEXT")
            logger.info("Added possible_questions column to claims")
        
        # Rebuild FTS to include possible_questions
        for trigger_name in ['claims_ai', 'claims_au', 'claims_ad']:
            conn.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
        
        conn.execute("DROP TABLE IF EXISTS claims_fts")
        conn.execute("""
            CREATE VIRTUAL TABLE claims_fts USING fts5(
                claim_id UNINDEXED,
                statement,
                predicate,
                object_text,
                subject_text,
                context_domain,
                friendly_id,
                possible_questions,
                content='claims',
                content_rowid='rowid'
            )
        """)
        
        # Recreate triggers with possible_questions
        conn.execute("""
            CREATE TRIGGER claims_ai AFTER INSERT ON claims BEGIN
                INSERT INTO claims_fts(rowid, claim_id, statement, predicate, object_text, subject_text, context_domain, friendly_id, possible_questions)
                VALUES (new.rowid, new.claim_id, new.statement, new.predicate, new.object_text, new.subject_text, new.context_domain, new.friendly_id, new.possible_questions);
            END
        """)
        conn.execute("""
            CREATE TRIGGER claims_au AFTER UPDATE ON claims BEGIN
                INSERT INTO claims_fts(claims_fts, rowid, claim_id, statement, predicate, object_text, subject_text, context_domain, friendly_id, possible_questions)
                VALUES ('delete', old.rowid, old.claim_id, old.statement, old.predicate, old.object_text, old.subject_text, old.context_domain, old.friendly_id, old.possible_questions);
                INSERT INTO claims_fts(rowid, claim_id, statement, predicate, object_text, subject_text, context_domain, friendly_id, possible_questions)
                VALUES (new.rowid, new.claim_id, new.statement, new.predicate, new.object_text, new.subject_text, new.context_domain, new.friendly_id, new.possible_questions);
            END
        """)
        conn.execute("""
            CREATE TRIGGER claims_ad AFTER DELETE ON claims BEGIN
                INSERT INTO claims_fts(claims_fts, rowid, claim_id, statement, predicate, object_text, subject_text, context_domain, friendly_id, possible_questions)
                VALUES ('delete', old.rowid, old.claim_id, old.statement, old.predicate, old.object_text, old.subject_text, old.context_domain, old.friendly_id, old.possible_questions);
            END
        """)
        
        # Rebuild FTS index
        conn.execute("""
            INSERT INTO claims_fts(rowid, claim_id, statement, predicate, object_text, subject_text, context_domain, friendly_id, possible_questions)
            SELECT rowid, claim_id, statement, predicate, object_text, subject_text, context_domain, friendly_id, possible_questions
            FROM claims
        """)
        
        logger.info("Migration to v6 complete")
    
    def _ensure_catalog_seeded(self, conn: sqlite3.Connection) -> None:
        """
        Ensure claim_types_catalog and context_domains_catalog are seeded
        with system defaults.  Idempotent — safe to call on every startup.
        Only runs if the catalog tables exist.
        """
        try:
            # Check if tables exist
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='claim_types_catalog'"
            ).fetchone()
            if not row:
                return  # Tables not created yet
            
            from .constants import ClaimType, ContextDomain
            ts = now_iso()
            
            for ct in ClaimType:
                conn.execute(
                    "INSERT OR IGNORE INTO claim_types_catalog (type_name, user_email, display_name, created_at) VALUES (?, '', ?, ?)",
                    (ct.value, ct.value.capitalize(), ts)
                )
            
            for cd in ContextDomain:
                display = cd.value.replace('_', ' ').title()
                conn.execute(
                    "INSERT OR IGNORE INTO context_domains_catalog (domain_name, user_email, display_name, created_at) VALUES (?, '', ?, ?)",
                    (cd.value, display, ts)
                )
        except Exception as e:
            logger.warning(f"Could not seed catalog tables: {e}")
    
    def _ensure_fts_v3(self, conn: sqlite3.Connection) -> None:
        """
        Ensure the claims_fts table and triggers include the friendly_id column.
        
        This is an idempotent fixup that runs after both DDL and migrations.
        It handles:
        - Fresh v3 databases (DDL created FTS without friendly_id for safety)
        - Migrated databases (migration should have done this, but we verify)
        - Partially-migrated databases (where FTS was not properly upgraded)
        
        The method checks if the FTS table already has friendly_id and skips
        if it does. This makes it safe to call on every startup.
        """
        try:
            # Check if claims table has friendly_id (prerequisite)
            cursor = conn.execute("PRAGMA table_info(claims)")
            claim_columns = [row[1] for row in cursor.fetchall()]
            if 'friendly_id' not in claim_columns:
                # Claims table doesn't have friendly_id yet - can't upgrade FTS
                return
            
            # Check if FTS table already has friendly_id
            try:
                fts_cursor = conn.execute("SELECT * FROM claims_fts LIMIT 0")
                fts_cols = [desc[0] for desc in fts_cursor.description] if fts_cursor.description else []
            except Exception:
                fts_cols = []
            
            # Check if FTS is fully up-to-date (has all expected columns)
            expected_fts_cols = {'friendly_id', 'possible_questions'}
            has_all = expected_fts_cols.issubset(set(fts_cols))
            if has_all:
                # Already current - nothing to do
                return
            
            logger.info("[FTS] Upgrading FTS table and triggers to current schema")
            
            # Determine which columns are available in claims table
            has_pq = 'possible_questions' in claim_columns
            
            # Build column lists dynamically based on what exists
            fts_data_cols = ['statement', 'predicate', 'object_text', 'subject_text', 'context_domain', 'friendly_id']
            if has_pq:
                fts_data_cols.append('possible_questions')
            
            all_fts_cols = ['claim_id UNINDEXED'] + fts_data_cols
            col_names = ['claim_id'] + fts_data_cols
            new_prefixed = ', '.join(['new.' + c for c in col_names])
            old_prefixed = ', '.join(['old.' + c for c in col_names])
            col_list = ', '.join(col_names)
            
            # Drop old triggers
            for trigger_name in ['claims_ai', 'claims_au', 'claims_ad']:
                conn.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
            
            conn.execute("DROP TABLE IF EXISTS claims_fts")
            conn.execute(f"""
                CREATE VIRTUAL TABLE claims_fts USING fts5(
                    {', '.join(all_fts_cols)},
                    content='claims',
                    content_rowid='rowid'
                )
            """)
            
            conn.execute(f"""
                CREATE TRIGGER claims_ai AFTER INSERT ON claims BEGIN
                    INSERT INTO claims_fts(rowid, {col_list})
                    VALUES (new.rowid, {new_prefixed});
                END
            """)
            conn.execute(f"""
                CREATE TRIGGER claims_au AFTER UPDATE ON claims BEGIN
                    INSERT INTO claims_fts(claims_fts, rowid, {col_list})
                    VALUES ('delete', old.rowid, {old_prefixed});
                    INSERT INTO claims_fts(rowid, {col_list})
                    VALUES (new.rowid, {new_prefixed});
                END
            """)
            conn.execute(f"""
                CREATE TRIGGER claims_ad AFTER DELETE ON claims BEGIN
                    INSERT INTO claims_fts(claims_fts, rowid, {col_list})
                    VALUES ('delete', old.rowid, {old_prefixed});
                END
            """)
            
            conn.execute(f"""
                INSERT INTO claims_fts(rowid, {col_list})
                SELECT rowid, {col_list}
                FROM claims
            """)
            
            logger.info("[FTS] FTS table and triggers upgraded successfully")
            
        except Exception as e:
            logger.error(f"[FTS-V3] Failed to ensure FTS v3: {e}")
            # Don't raise - FTS upgrade failure shouldn't prevent startup
            # The system can still work with the v2 FTS (just without friendly_id indexing)
        
        # Ensure v3 indexes exist (idempotent - IF NOT EXISTS)
        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_claims_user_friendly_id ON claims(user_email, friendly_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_friendly_id ON claims(friendly_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_contexts_user_email ON contexts(user_email)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_contexts_friendly_id ON contexts(friendly_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_contexts_parent ON contexts(parent_context_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_context_claims_claim_id ON context_claims(claim_id)")
        except Exception as e:
            logger.warning(f"[FTS-V3] Could not create some v3 indexes: {e}")
    
    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for atomic transactions.
        
        Usage:
            with db.transaction() as conn:
                conn.execute("INSERT ...")
                conn.execute("UPDATE ...")
            # Automatically committed on success, rolled back on exception
        
        Yields:
            Active connection within transaction.
            
        Raises:
            Any exception from transaction body (after rollback).
        """
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    
    def execute(
        self,
        sql: str,
        params: tuple = ()
    ) -> sqlite3.Cursor:
        """
        Execute SQL with parameters (convenience method).
        
        Args:
            sql: SQL statement with ? placeholders.
            params: Parameter values.
            
        Returns:
            Cursor with results.
        """
        conn = self.connect()
        return conn.execute(sql, params)
    
    def executemany(
        self,
        sql: str,
        params_list: list
    ) -> sqlite3.Cursor:
        """
        Execute SQL for multiple parameter sets.
        
        Args:
            sql: SQL statement with ? placeholders.
            params_list: List of parameter tuples.
            
        Returns:
            Cursor with results.
        """
        conn = self.connect()
        return conn.executemany(sql, params_list)
    
    def fetchone(
        self,
        sql: str,
        params: tuple = ()
    ) -> Optional[sqlite3.Row]:
        """
        Execute and fetch one row.
        
        Args:
            sql: SQL SELECT statement.
            params: Parameter values.
            
        Returns:
            Row or None if no results.
        """
        cursor = self.execute(sql, params)
        return cursor.fetchone()
    
    def fetchall(
        self,
        sql: str,
        params: tuple = ()
    ) -> list:
        """
        Execute and fetch all rows.
        
        Args:
            sql: SQL SELECT statement.
            params: Parameter values.
            
        Returns:
            List of Row objects.
        """
        cursor = self.execute(sql, params)
        return cursor.fetchall()
    
    def get_schema_version(self) -> Optional[int]:
        """
        Get current schema version.
        
        Returns:
            Schema version number or None if not initialized.
        """
        try:
            row = self.fetchone("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
            return row['version'] if row else None
        except sqlite3.OperationalError:
            return None
    
    def table_exists(self, table_name: str) -> bool:
        """
        Check if a table exists in the database.
        
        Args:
            table_name: Name of table to check.
            
        Returns:
            True if table exists.
        """
        row = self.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        return row is not None
    
    def close(self) -> None:
        """
        Close database connection.
        
        Safe to call multiple times.
        """
        if self._conn:
            self._conn.close()
            self._conn = None
            self._initialized = False
            logger.info("Database connection closed")
    
    def vacuum(self) -> None:
        """
        Run VACUUM to reclaim space and optimize database.
        
        Note: This locks the database and can be slow for large databases.
        """
        conn = self.connect()
        conn.execute("VACUUM")
        logger.info("Database vacuumed")
    
    def __enter__(self) -> 'PKBDatabase':
        """Context manager entry."""
        self.connect()
        self.initialize_schema()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()


def get_database(config: PKBConfig, auto_init: bool = True) -> PKBDatabase:
    """
    Factory function to create and initialize database.
    
    Args:
        config: PKBConfig with database settings.
        auto_init: Automatically initialize schema (default: True).
        
    Returns:
        Initialized PKBDatabase instance.
        
    Example:
        config = PKBConfig(db_path="./my_kb.sqlite")
        db = get_database(config)
    """
    db = PKBDatabase(config)
    if auto_init:
        db.connect()
        db.initialize_schema()
    return db


def get_memory_database(auto_init: bool = True) -> PKBDatabase:
    """
    Create an in-memory database for testing.
    
    Args:
        auto_init: Automatically initialize schema.
        
    Returns:
        PKBDatabase with :memory: path.
    """
    config = PKBConfig(db_path=":memory:")
    return get_database(config, auto_init=auto_init)
