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
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,  # Allow multi-threaded access
                timeout=30.0  # Wait up to 30s for locks
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
        if self._initialized:
            return
        
        conn = self.connect()
        
        try:
            # Check current schema version
            current_version = self.get_schema_version()
            
            # Execute all DDL statements (IF NOT EXISTS makes this safe)
            ddl = get_all_ddl(include_triggers=include_triggers)
            conn.executescript(ddl)
            
            # Run migrations if upgrading from older version
            if current_version is not None and current_version < SCHEMA_VERSION:
                self._run_migrations(conn, current_version, SCHEMA_VERSION)
            
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
