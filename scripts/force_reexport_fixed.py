#!/usr/bin/env python3
"""
Force re-export the 11 fixed episodes to Google Sheets.

The normal export skips episodes whose title already exists in the sheet.
This script:
1. Deletes the old (wrong-content) rows from Google Sheets for the 11 fixed episodes
2. Runs the normal export to add the new correct rows

Usage:
    python3 scripts/force_reexport_fixed.py [--dry-run]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.sheets import get_sheets_client, get_sheet_id, export_to_sheets
from src.state import get_state_manager
from src.podcast_db import get_episodes_since

# Episode titles of the 11 fixed episodes (matched against sheet column B)
FIXED_TITLES = [
    "An Interview with Anduril Co-Founder and CEO Brian Schimpf About Paradigm Shifts",
    "An Interview with Jon Yu About YouTube and Making Semiconductors",
    "An Interview with Tailscale Co-Founder and CEO Avery Pennarun",
    "Checking In on AI and the Big Five",
    "An Interview with Sierra Founder and CEO Bret Taylor About AI Agents and Tech History Lessons",
    "An Interview with Cloudflare Founder and CEO Matthew Prince About Internet History and Pay-per-crawl",
    "An Interview with Dan Kim About Intel, Nvidia, and the U.S. Government",
    "An Interview with Gracelin Baskaran About Rare Earths",
    "An Interview with Michael Morton About AI E-Commerce",
    "Marc Andreessen: Why Perfect Products Become Obsolete",
    "AI News Crossover: A Candid Chat with Liron Shapira of Doom Debates",
]


def delete_rows_by_title(worksheet, titles_to_delete: set[str], dry_run: bool = False) -> list[str]:
    """
    Delete rows matching any of the given titles from the worksheet.

    Returns list of deleted titles.
    """
    all_rows = worksheet.get_all_values()
    if len(all_rows) <= 1:
        return []

    # Find rows to delete (matching titles), collect from bottom to top
    rows_to_delete = []
    deleted_titles = []

    for row_num, row in enumerate(all_rows[1:], start=2):
        if len(row) > 1 and row[1] in titles_to_delete:
            rows_to_delete.append(row_num)
            deleted_titles.append(row[1])

    if not rows_to_delete:
        return []

    print(f"  Found {len(rows_to_delete)} rows to delete in tab '{worksheet.title}':")
    for title in deleted_titles:
        print(f"    - {title[:70]}")

    if not dry_run:
        # Delete from bottom to top (so row numbers don't shift)
        for row_num in sorted(rows_to_delete, reverse=True):
            worksheet.delete_rows(row_num)
        print(f"  Deleted {len(rows_to_delete)} rows.")

    return deleted_titles


def main():
    parser = argparse.ArgumentParser(
        description="Force re-export the 11 fixed episodes to Google Sheets"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be deleted/exported without making changes")
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN MODE ===\n")

    print("Connecting to Google Sheets...")
    client = get_sheets_client()
    sheet_id = get_sheet_id()
    spreadsheet = client.open_by_key(sheet_id)

    titles_to_delete = set(FIXED_TITLES)
    all_deleted = []

    print(f"\nStep 1: Delete old rows for {len(FIXED_TITLES)} fixed episodes\n")

    for worksheet in spreadsheet.worksheets():
        deleted = delete_rows_by_title(worksheet, titles_to_delete, dry_run=args.dry_run)
        all_deleted.extend(deleted)

    if not all_deleted:
        print("No matching rows found in any sheet tab.")
    else:
        print(f"\nTotal rows deleted: {len(all_deleted)}")

    if args.dry_run:
        print("\n=== DRY RUN - Skipping re-export ===")
        return

    # Reset the exported_to_sheets flag in local state for these 11 episodes
    # (the previous export may have set this to True when it detected them "in sheet")
    print("\nStep 1b: Reset local export flags for fixed episodes\n")
    state = get_state_manager()
    ep_ids_to_reset = []
    for ep in get_episodes_since():
        if ep.title in set(FIXED_TITLES):
            ep_ids_to_reset.append(ep.id)
            if state.is_exported(ep.id):
                state.mark_not_exported(ep.id)
                print(f"  Reset: {ep.title[:60]}")

    print("\nStep 2: Re-export fixed episodes to Google Sheets\n")

    episodes = get_episodes_since()
    result = export_to_sheets(episodes=episodes)

    print(f"\nExport Summary:")
    print(f"  Exported:   {result['exported']}")
    print(f"  Duplicates: {result['duplicates']}")
    print(f"  Skipped:    {result['skipped']}")
    print(f"  Errors:     {result['errors']}")


if __name__ == "__main__":
    main()
