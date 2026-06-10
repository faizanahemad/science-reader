"""
Maintenance Script: Backfill entity links for existing PKB claims.

Links entities for existing *active* claims that have NO entity links yet —
claims that predate entity extraction, or were added with ``auto_extract=False``.
This is corpus-parity tooling for the entity-linked retrieval strategy: it is
idempotent, user-scoped, off the retrieval hot path, and NOT required for
correctness (FTS/embedding still retrieve unlinked claims). It only raises
entity-path recall on the pre-existing corpus.

Usage:
    python -m truth_management_system.backfill_entities [options]

Options:
    --pkb-db PATH         Path to PKB SQLite file (default: PKBConfig default,
                          ~/.pkb/kb.sqlite). Use the same DB the server uses.
    --user EMAIL          Scope to a single tenant's claims (recommended on a
                          multi-user DB). Omit for the NULL-user / single-tenant
                          scope.
    --context-domain D    Optional domain filter (e.g. work, health). Default: all.
    --dry-run             Preview what WOULD be linked without writing rows.
    --limit N             Cap claims processed this run (resumable: re-run to
                          continue; already-linked claims are skipped).
    --verbose, -v         Enable verbose logging.

Requires OPENROUTER_API_KEY in the environment (the LLM extracts entities).
Without it the script exits with a clear message and makes no changes.
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from truth_management_system import PKBConfig, get_database, StructuredAPI

logger = logging.getLogger(__name__)


def run_backfill(
    pkb_db_path=None,
    user_email=None,
    context_domain=None,
    dry_run=False,
    limit=None,
):
    """
    Run the entity-link backfill. Returns the counts dict from
    ``StructuredAPI.backfill_entities`` (``{scanned, linked, links, skipped}``).
    """
    keys = {}
    if os.environ.get("OPENROUTER_API_KEY"):
        keys["OPENROUTER_API_KEY"] = os.environ["OPENROUTER_API_KEY"]

    config = PKBConfig(db_path=pkb_db_path) if pkb_db_path else PKBConfig()
    db = get_database(config)
    api = StructuredAPI(db, keys, config, user_email=user_email)

    if api.llm is None:
        logger.error(
            "OPENROUTER_API_KEY is not set; entity extraction is unavailable. "
            "No changes made."
        )
        return {"scanned": 0, "linked": 0, "links": 0, "skipped": 0}

    return api.backfill_entities(
        context_domain=context_domain, dry_run=dry_run, limit=limit
    )


def main():
    parser = argparse.ArgumentParser(
        description="Backfill entity links for existing PKB claims",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--pkb-db", default=None, help="Path to PKB SQLite file")
    parser.add_argument("--user", default=None, help="Scope to a single user email")
    parser.add_argument(
        "--context-domain", default=None, help="Optional domain filter"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without writing"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Cap claims processed this run"
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    print("=" * 60)
    print("PKB Entity-Link Backfill")
    print("=" * 60)
    print(f"PKB DB:        {args.pkb_db or '(config default)'}")
    print(f"User:          {args.user or '(default scope)'}")
    print(f"Domain:        {args.context_domain or '(all)'}")
    print(f"Dry Run:       {args.dry_run}")
    print(f"Limit:         {args.limit if args.limit is not None else '(none)'}")
    print("=" * 60)

    result = run_backfill(
        pkb_db_path=args.pkb_db,
        user_email=args.user,
        context_domain=args.context_domain,
        dry_run=args.dry_run,
        limit=args.limit,
    )

    print("\n" + "=" * 60)
    print("Backfill Summary")
    print("=" * 60)
    print(f"Claims scanned (needed work): {result['scanned']}")
    print(f"Claims linked:                {result['linked']}")
    print(f"Entity links created:         {result['links']}")
    print(f"Skipped (no entities/error):  {result['skipped']}")
    print("=" * 60)
    if args.dry_run:
        print("\n[DRY RUN] No changes were made. Remove --dry-run to apply.")


if __name__ == "__main__":
    main()
