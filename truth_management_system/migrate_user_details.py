#!/usr/bin/env python3
"""
Migration Script: UserDetails to PKB Claims

This script migrates existing user_memory and user_preferences data from the
UserDetails SQLite table to the new Personal Knowledge Base (PKB) system.

Usage:
    python -m truth_management_system.migrate_user_details [options]
    
Options:
    --users-db PATH       Path to users.db SQLite file (default: ./users/users.db)
    --pkb-db PATH         Path to PKB SQLite file (default: ./users/pkb.sqlite)
    --dry-run             Preview migration without making changes
    --user EMAIL          Migrate only a specific user by email
    --verbose             Enable verbose logging

The migration:
1. Reads user_memory and user_preferences from UserDetails table
2. Parses the text into individual facts/preferences
3. Creates PKB claims with appropriate types and domains
4. Sets meta_json.source = "migration" for tracking
"""

import argparse
import sqlite3
import os
import sys
import logging
import json
from typing import List, Dict, Optional, Tuple

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from truth_management_system import (
    PKBConfig, get_database, StructuredAPI,
    ClaimType, ContextDomain
)

logger = logging.getLogger(__name__)


def get_user_details_connection(db_path: str) -> Optional[sqlite3.Connection]:
    """
    Connect to the UserDetails database.
    
    Args:
        db_path: Path to users.db file.
        
    Returns:
        SQLite connection or None if file doesn't exist.
    """
    if not os.path.exists(db_path):
        logger.error(f"UserDetails database not found: {db_path}")
        return None
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_all_users(conn: sqlite3.Connection) -> List[Dict]:
    """
    Get all users with their user_memory and user_preferences.
    
    Args:
        conn: SQLite connection to users.db.
        
    Returns:
        List of user dicts with email, user_memory, user_preferences.
    """
    cursor = conn.execute("""
        SELECT user_email, user_memory, user_preferences
        FROM UserDetails
        WHERE user_memory IS NOT NULL OR user_preferences IS NOT NULL
    """)
    
    users = []
    for row in cursor:
        users.append({
            'email': row['user_email'],
            'user_memory': row['user_memory'] or '',
            'user_preferences': row['user_preferences'] or ''
        })
    
    return users


def parse_text_to_claims(
    text: str,
    default_claim_type: str,
    default_domain: str
) -> List[Dict]:
    """
    Parse freeform text into individual claim candidates.
    
    The text is typically a list of facts/preferences, one per line or
    separated by bullet points.
    
    Args:
        text: Freeform text to parse.
        default_claim_type: Default claim type for extracted claims.
        default_domain: Default domain for extracted claims.
        
    Returns:
        List of claim dicts with statement, claim_type, context_domain.
    """
    if not text or not text.strip():
        return []
    
    claims = []
    
    # Split by common delimiters
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    
    for line in lines:
        # Clean up the line
        line = line.strip()
        
        # Skip empty lines and common headers
        if not line:
            continue
        if line.lower() in ['user memory:', 'user preferences:', 'facts:', 'preferences:']:
            continue
        
        # Remove bullet points and numbering
        for prefix in ['- ', '* ', '• ', '· ']:
            if line.startswith(prefix):
                line = line[len(prefix):].strip()
                break
        
        # Remove numbered lists (1. 2. etc.)
        if len(line) > 2 and line[0].isdigit() and line[1] in '.):':
            line = line[2:].strip()
        
        # Skip if too short after cleaning
        if len(line) < 3:
            continue
        
        # Detect claim type from keywords
        claim_type = default_claim_type
        lower_line = line.lower()
        
        if any(kw in lower_line for kw in ['prefer', 'like', 'want', 'love', 'enjoy', 'hate', 'dislike']):
            claim_type = 'preference'
        elif any(kw in lower_line for kw in ['decided', 'will', 'going to', 'plan to']):
            claim_type = 'decision'
        elif any(kw in lower_line for kw in ['remember', 'remind', 'don\'t forget']):
            claim_type = 'reminder'
        elif any(kw in lower_line for kw in ['habit', 'usually', 'always', 'every day', 'every week']):
            claim_type = 'habit'
        elif any(kw in lower_line for kw in ['task', 'todo', 'need to', 'should']):
            claim_type = 'task'
        
        # Detect domain from keywords
        domain = default_domain
        if any(kw in lower_line for kw in ['health', 'workout', 'exercise', 'diet', 'sleep', 'medical', 'doctor']):
            domain = 'health'
        elif any(kw in lower_line for kw in ['work', 'job', 'career', 'office', 'meeting', 'project', 'colleague']):
            domain = 'work'
        elif any(kw in lower_line for kw in ['family', 'friend', 'relationship', 'partner', 'spouse', 'kid', 'parent']):
            domain = 'relationships'
        elif any(kw in lower_line for kw in ['learn', 'study', 'course', 'book', 'read', 'education']):
            domain = 'learning'
        elif any(kw in lower_line for kw in ['money', 'finance', 'budget', 'invest', 'save', 'expense', 'income']):
            domain = 'finance'
        elif any(kw in lower_line for kw in ['schedule', 'routine', 'organize', 'plan', 'calendar']):
            domain = 'life_ops'
        
        claims.append({
            'statement': line,
            'claim_type': claim_type,
            'context_domain': domain
        })
    
    return claims


def migrate_user(
    api: StructuredAPI,
    user_data: Dict,
    dry_run: bool = False,
    verbose: bool = False
) -> Tuple[int, int]:
    """
    Migrate a single user's data to PKB.
    
    Args:
        api: StructuredAPI instance scoped to the user.
        user_data: Dict with email, user_memory, user_preferences.
        dry_run: If True, don't actually create claims.
        verbose: If True, print details.
        
    Returns:
        Tuple of (memory_count, preference_count) of claims created.
    """
    email = user_data['email']
    memory_count = 0
    preference_count = 0
    
    # Parse user_memory into claims
    memory_claims = parse_text_to_claims(
        user_data['user_memory'],
        default_claim_type='memory',
        default_domain='personal'
    )
    
    # Parse user_preferences into claims
    preference_claims = parse_text_to_claims(
        user_data['user_preferences'],
        default_claim_type='preference',
        default_domain='personal'
    )
    
    # Create metadata for tracking migration source
    meta_json = json.dumps({
        'source': 'migration',
        'migrated_from': 'UserDetails',
        'migration_version': '1.0'
    })
    
    # Add memory claims
    for claim in memory_claims:
        if verbose:
            print(f"  [memory] {claim['statement'][:50]}...")
        
        if not dry_run:
            result = api.add_claim(
                statement=claim['statement'],
                claim_type=claim['claim_type'],
                context_domain=claim['context_domain'],
                auto_extract=False,
                meta_json=meta_json
            )
            
            if result.success:
                memory_count += 1
            else:
                logger.warning(f"Failed to create memory claim: {result.errors}")
        else:
            memory_count += 1
    
    # Add preference claims
    for claim in preference_claims:
        if verbose:
            print(f"  [preference] {claim['statement'][:50]}...")
        
        if not dry_run:
            result = api.add_claim(
                statement=claim['statement'],
                claim_type=claim['claim_type'],
                context_domain=claim['context_domain'],
                auto_extract=False,
                meta_json=meta_json
            )
            
            if result.success:
                preference_count += 1
            else:
                logger.warning(f"Failed to create preference claim: {result.errors}")
        else:
            preference_count += 1
    
    return memory_count, preference_count


def run_migration(
    users_db_path: str,
    pkb_db_path: str,
    dry_run: bool = False,
    user_email: Optional[str] = None,
    verbose: bool = False
) -> Dict:
    """
    Run the migration for all users or a specific user.
    
    Args:
        users_db_path: Path to users.db.
        pkb_db_path: Path to pkb.sqlite.
        dry_run: If True, don't make changes.
        user_email: If provided, only migrate this user.
        verbose: If True, print verbose output.
        
    Returns:
        Dict with migration statistics.
    """
    results = {
        'users_processed': 0,
        'total_memory_claims': 0,
        'total_preference_claims': 0,
        'errors': []
    }
    
    # Connect to UserDetails DB
    users_conn = get_user_details_connection(users_db_path)
    if users_conn is None:
        results['errors'].append(f"Could not connect to users database: {users_db_path}")
        return results
    
    # Initialize PKB
    pkb_config = PKBConfig(db_path=pkb_db_path)
    pkb_db = get_database(pkb_config)
    
    try:
        # Get users to migrate
        all_users = get_all_users(users_conn)
        
        if user_email:
            all_users = [u for u in all_users if u['email'] == user_email]
        
        print(f"{'[DRY RUN] ' if dry_run else ''}Found {len(all_users)} users to migrate")
        
        for user in all_users:
            email = user['email']
            print(f"\nMigrating user: {email}")
            
            # Create API scoped to user
            api = StructuredAPI(pkb_db, {}, pkb_config, user_email=email)
            
            try:
                mem_count, pref_count = migrate_user(api, user, dry_run, verbose)
                
                results['users_processed'] += 1
                results['total_memory_claims'] += mem_count
                results['total_preference_claims'] += pref_count
                
                print(f"  Created: {mem_count} memory claims, {pref_count} preference claims")
                
            except Exception as e:
                error_msg = f"Error migrating {email}: {str(e)}"
                logger.error(error_msg)
                results['errors'].append(error_msg)
        
    finally:
        users_conn.close()
    
    return results


def main():
    """Main entry point for the migration script."""
    parser = argparse.ArgumentParser(
        description='Migrate UserDetails data to PKB claims',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--users-db',
        default='./users/users.db',
        help='Path to users.db SQLite file (default: ./users/users.db)'
    )
    
    parser.add_argument(
        '--pkb-db',
        default='./users/pkb.sqlite',
        help='Path to PKB SQLite file (default: ./users/pkb.sqlite)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview migration without making changes'
    )
    
    parser.add_argument(
        '--user',
        help='Migrate only a specific user by email'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 60)
    print("UserDetails to PKB Migration")
    print("=" * 60)
    print(f"Users DB: {args.users_db}")
    print(f"PKB DB:   {args.pkb_db}")
    print(f"Dry Run:  {args.dry_run}")
    if args.user:
        print(f"User:     {args.user}")
    print("=" * 60)
    
    results = run_migration(
        users_db_path=args.users_db,
        pkb_db_path=args.pkb_db,
        dry_run=args.dry_run,
        user_email=args.user,
        verbose=args.verbose
    )
    
    print("\n" + "=" * 60)
    print("Migration Summary")
    print("=" * 60)
    print(f"Users processed:       {results['users_processed']}")
    print(f"Memory claims created: {results['total_memory_claims']}")
    print(f"Pref. claims created:  {results['total_preference_claims']}")
    
    if results['errors']:
        print(f"\nErrors ({len(results['errors'])}):")
        for err in results['errors']:
            print(f"  - {err}")
    
    print("=" * 60)
    
    if args.dry_run:
        print("\n[DRY RUN] No changes were made. Remove --dry-run to perform migration.")
    
    return 0 if not results['errors'] else 1


if __name__ == '__main__':
    sys.exit(main())
