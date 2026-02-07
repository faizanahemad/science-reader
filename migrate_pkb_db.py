#!/usr/bin/env python3
"""
PKB Database Migration Script
==============================

Standalone script to migrate an existing PKB SQLite database to the latest
schema version.  Run this on a server after deploying new code that introduces
schema changes (new columns, tables, indexes, FTS rebuilds, etc.).

The script is **idempotent** — safe to run multiple times.  It will:
1. Detect the current schema version of the database.
2. Run all necessary migrations to reach the latest version.
3. Ensure all columns, tables, indexes, FTS triggers, and catalog seeds exist.
4. Backfill any missing data (friendly_ids, claim_numbers, etc.).
5. Report what was done.

Schema version history:
    v1  Initial schema
    v2  Multi-user support (user_email columns)
    v3  Friendly IDs, multi-type/domain, contexts, FTS with friendly_id
    v4  Dynamic claim_types_catalog and context_domains_catalog tables
    v5  Per-user auto-incremented claim_number
    v6  possible_questions QnA field, FTS with possible_questions

Usage:
    # Migrate the default database (storage/users/pkb.sqlite)
    python migrate_pkb_db.py

    # Migrate a specific database file
    python migrate_pkb_db.py /path/to/pkb.sqlite

    # Dry run — show what would happen without changing anything
    python migrate_pkb_db.py --dry-run

    # Verbose output
    python migrate_pkb_db.py --verbose
"""

import os
import sys
import sqlite3
import argparse
import logging
import shutil
from datetime import datetime


def find_default_db_path():
    """Find the default PKB database path.

    Checks common locations in order:
    1. storage/users/pkb.sqlite (relative to script dir — typical server layout)
    2. users/pkb.sqlite (alternate layout)
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(script_dir, "storage", "users", "pkb.sqlite"),
        os.path.join(script_dir, "users", "pkb.sqlite"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    # Default to the first candidate even if it doesn't exist yet
    return candidates[0]


def get_db_info(db_path):
    """Get current database info without modifying it."""
    if not os.path.exists(db_path):
        return {"exists": False}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    info = {"exists": True, "path": db_path, "size_mb": os.path.getsize(db_path) / (1024 * 1024)}

    # Schema version
    try:
        row = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        info["schema_version"] = row["version"] if row else None
    except sqlite3.OperationalError:
        info["schema_version"] = None

    # Table list
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    info["tables"] = [r["name"] for r in tables]

    # Claims count
    try:
        row = conn.execute("SELECT COUNT(*) as c FROM claims").fetchone()
        info["claims_count"] = row["c"]
    except sqlite3.OperationalError:
        info["claims_count"] = 0

    # Claims columns
    try:
        cols = conn.execute("PRAGMA table_info(claims)").fetchall()
        info["claims_columns"] = [r[1] for r in cols]
    except Exception:
        info["claims_columns"] = []

    # FTS columns
    try:
        cur = conn.execute("SELECT * FROM claims_fts LIMIT 0")
        info["fts_columns"] = [d[0] for d in cur.description] if cur.description else []
    except Exception:
        info["fts_columns"] = []

    # Claims without friendly_id
    try:
        row = conn.execute("SELECT COUNT(*) as c FROM claims WHERE friendly_id IS NULL").fetchone()
        info["claims_without_friendly_id"] = row["c"]
    except Exception:
        info["claims_without_friendly_id"] = 0

    # Claims without claim_number
    try:
        row = conn.execute("SELECT COUNT(*) as c FROM claims WHERE claim_number IS NULL").fetchone()
        info["claims_without_claim_number"] = row["c"]
    except Exception:
        info["claims_without_claim_number"] = 0

    # Contexts count
    try:
        row = conn.execute("SELECT COUNT(*) as c FROM contexts").fetchone()
        info["contexts_count"] = row["c"]
    except Exception:
        info["contexts_count"] = 0

    conn.close()
    return info


def run_migration(db_path, verbose=False):
    """Run the full migration using the PKB database module.

    Returns:
        Tuple of (before_info, after_info, success, error_message)
    """
    # Get state before migration
    before = get_db_info(db_path)

    # Import PKB modules
    try:
        from truth_management_system.config import PKBConfig
        from truth_management_system.database import get_database
        from truth_management_system.schema import SCHEMA_VERSION
    except ImportError as e:
        return before, None, False, f"Failed to import PKB modules: {e}\nMake sure you're running from the project root directory."

    print(f"Target schema version: {SCHEMA_VERSION}")
    print(f"Current schema version: {before.get('schema_version', 'None (new DB)')}")
    print()

    if before.get("schema_version") == SCHEMA_VERSION:
        print("Database is already at the latest schema version.")
        print("Running idempotent fixups anyway (column checks, FTS, catalog seeding)...")
        print()

    # Set up logging
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Run the migration via PKBDatabase.initialize_schema()
    # This handles: DDL creation, column addition, migrations, FTS rebuild, catalog seeding
    try:
        config = PKBConfig(db_path=db_path)
        db = get_database(config, auto_init=True)
        # Force re-initialization to ensure all fixups run
        db._initialized = False
        db.initialize_schema()
        db.close()
    except Exception as e:
        return before, None, False, f"Migration failed: {e}"

    # Get state after migration
    after = get_db_info(db_path)

    return before, after, True, None


def main():
    parser = argparse.ArgumentParser(
        description="Migrate PKB SQLite database to the latest schema version.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "db_path",
        nargs="?",
        default=None,
        help="Path to pkb.sqlite file (default: auto-detect in storage/users/ or users/)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show current state without making changes"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed migration logs"
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating a backup before migration"
    )

    args = parser.parse_args()

    # Determine database path
    db_path = args.db_path or find_default_db_path()
    db_path = os.path.abspath(db_path)

    print("=" * 60)
    print("PKB Database Migration Tool")
    print("=" * 60)
    print(f"Database: {db_path}")
    print()

    # Show current state
    info = get_db_info(db_path)
    if not info["exists"]:
        print(f"Database does not exist at: {db_path}")
        if args.dry_run:
            print("(dry run) Would create a new database with latest schema.")
            return 0
        print("A new database will be created with the latest schema.")
        print()
    else:
        print(f"Current state:")
        print(f"  Schema version:  {info.get('schema_version', 'unknown')}")
        print(f"  Database size:   {info.get('size_mb', 0):.2f} MB")
        print(f"  Tables:          {len(info.get('tables', []))}")
        print(f"  Claims:          {info.get('claims_count', 0)}")
        print(f"  Contexts:        {info.get('contexts_count', 0)}")
        print(f"  Claims columns:  {info.get('claims_columns', [])}")
        print(f"  FTS columns:     {info.get('fts_columns', [])}")
        print(f"  Missing friendly_id:  {info.get('claims_without_friendly_id', 0)}")
        print(f"  Missing claim_number: {info.get('claims_without_claim_number', 0)}")
        print()

    if args.dry_run:
        from truth_management_system.schema import SCHEMA_VERSION
        current = info.get("schema_version")
        if current is None:
            print(f"(dry run) Would initialize schema to v{SCHEMA_VERSION}")
        elif current < SCHEMA_VERSION:
            print(f"(dry run) Would migrate from v{current} to v{SCHEMA_VERSION}")
            for v in range(current + 1, SCHEMA_VERSION + 1):
                desc = {
                    2: "Add user_email columns for multi-user support",
                    3: "Add friendly_id, multi-type/domain, contexts, FTS with friendly_id",
                    4: "Add claim_types_catalog and context_domains_catalog tables",
                    5: "Add claim_number column with per-user auto-increment and backfill",
                    6: "Add possible_questions column, rebuild FTS with possible_questions",
                }
                print(f"  v{v-1} -> v{v}: {desc.get(v, 'Unknown')}")
        else:
            print(f"(dry run) Database is at v{current}, target is v{SCHEMA_VERSION}. Would run idempotent fixups.")
        return 0

    # Create backup
    if info["exists"] and not args.no_backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{db_path}.backup_{timestamp}"
        print(f"Creating backup: {backup_path}")
        shutil.copy2(db_path, backup_path)
        print("Backup created.")
        print()

    # Run migration
    print("Running migration...")
    print("-" * 40)
    before, after, success, error = run_migration(db_path, verbose=args.verbose)
    print("-" * 40)
    print()

    if not success:
        print(f"MIGRATION FAILED: {error}")
        return 1

    # Show results
    print("Migration completed successfully!")
    print()
    print(f"After migration:")
    print(f"  Schema version:  {after.get('schema_version', 'unknown')}")
    print(f"  Database size:   {after.get('size_mb', 0):.2f} MB")
    print(f"  Tables:          {len(after.get('tables', []))}")
    print(f"  Claims:          {after.get('claims_count', 0)}")
    print(f"  Contexts:        {after.get('contexts_count', 0)}")
    print(f"  Claims columns:  {after.get('claims_columns', [])}")
    print(f"  FTS columns:     {after.get('fts_columns', [])}")
    print(f"  Missing friendly_id:  {after.get('claims_without_friendly_id', 0)}")
    print(f"  Missing claim_number: {after.get('claims_without_claim_number', 0)}")
    print()

    # Show what changed
    if before.get("exists"):
        changes = []
        bv = before.get("schema_version")
        av = after.get("schema_version")
        if bv != av:
            changes.append(f"Schema version: {bv} -> {av}")

        new_cols = set(after.get("claims_columns", [])) - set(before.get("claims_columns", []))
        if new_cols:
            changes.append(f"New claims columns: {sorted(new_cols)}")

        new_fts = set(after.get("fts_columns", [])) - set(before.get("fts_columns", []))
        if new_fts:
            changes.append(f"New FTS columns: {sorted(new_fts)}")

        new_tables = set(after.get("tables", [])) - set(before.get("tables", []))
        if new_tables:
            changes.append(f"New tables: {sorted(new_tables)}")

        fid_fixed = before.get("claims_without_friendly_id", 0) - after.get("claims_without_friendly_id", 0)
        if fid_fixed > 0:
            changes.append(f"Backfilled friendly_id for {fid_fixed} claims")

        num_fixed = before.get("claims_without_claim_number", 0) - after.get("claims_without_claim_number", 0)
        if num_fixed > 0:
            changes.append(f"Backfilled claim_number for {num_fixed} claims")

        if changes:
            print("Changes applied:")
            for c in changes:
                print(f"  - {c}")
        else:
            print("No changes needed — database was already up to date.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
