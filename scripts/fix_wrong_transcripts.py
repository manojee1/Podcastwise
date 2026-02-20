#!/usr/bin/env python3
"""
Fix wrong transcripts by clearing cache, state, and markdown for mismatched episodes.

Usage:
    python3 scripts/fix_wrong_transcripts.py [--dry-run] [--phase 1|2|3|all]

Phases:
    1 = Stratechery mismatches (8 episodes)
    2 = YouTube algorithm fix (already done in youtube.py)
    3 = YouTube mismatch episodes (3 episodes: Marc Andreessen, Liron Shapira, Michael Morton)
    all = All 11 episodes (default)
"""

import argparse
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.podcast_db import get_episodes_since
from src.state import get_state_manager
from src.youtube import get_cache_dir, clear_not_found, load_not_found, save_not_found


# ── Episode title patterns to match ────────────────────────────────────────

# Phase 1: Stratechery mismatches (wrong article fetched/cached)
STRATECHERY_MISMATCH_PATTERNS = [
    "Anduril Co-Founder",       # Brian Schimpf → got Kalshi/Tarek Mansour
    "Jon Yu About YouTube",      # Jon Yu → got Ryan Jones (Flighty)
    "Tailscale Co-Founder",      # Avery Pennarun → got Greg Peters Netflix
    "Checking In on AI and the Big Five",  # Got Apple Earnings article
    "Sierra Founder and CEO Bret Taylor",  # → got Greg Peters Netflix
    "Cloudflare Founder and CEO Matthew",  # → got Greg Peters Netflix
    "Dan Kim About Intel",       # → got Benedict Evans
    "Gracelin Baskaran",         # → got Kalshi/Tarek Mansour
]

# Phase 3: YouTube search mismatches (wrong video matched) — SPECIFIC titles only
YOUTUBE_MISMATCH_PATTERNS = [
    "Why Perfect Products Become Obsolete",  # a16z Marc Andreessen ep → got Mikey Shulman / Adam Neely
    "AI News Crossover",                     # Cognitive Revolution / Liron Shapira → got Amjad Msad / Peter Levels
    "Michael Morton About AI",               # Stratechery → got Daniel Gross (YouTube mismatch)
]


def get_output_dir() -> Path:
    return Path(os.getenv("PODCASTWISE_OUTPUT_DIR", "~/Documents/PodcastNotes")).expanduser()


def find_matching_episodes(patterns: list[str]) -> list:
    """Find episodes matching any of the given title patterns."""
    episodes = get_episodes_since()
    matched = []
    for ep in episodes:
        for pattern in patterns:
            if pattern.lower() in ep.title.lower():
                matched.append(ep)
                break
    return matched


def clear_episode(ep, dry_run: bool = False) -> dict:
    """
    Clear transcript cache, state, and markdown for a single episode.
    Returns a dict describing what was found/cleared.
    """
    cache_dir = get_cache_dir()
    output_dir = get_output_dir()
    state = get_state_manager()

    result = {
        "episode_id": ep.id,
        "title": ep.title,
        "podcast": ep.podcast_name,
        "cache_files_deleted": [],
        "state_cleared": False,
        "markdown_deleted": [],
        "not_found_cleared": False,
    }

    # 1. Delete transcript cache files (pattern: {episode_id}_*.json)
    for cache_file in sorted(cache_dir.glob(f"{ep.id}_*.json")):
        result["cache_files_deleted"].append(str(cache_file.name))
        if not dry_run:
            cache_file.unlink()

    # 2. Clear from state
    if state.is_processed(ep.id):
        result["state_cleared"] = True
        if not dry_run:
            state.clear(ep.id)

    # 3. Clear from not-found list (in case it was marked as no_transcript)
    not_found = load_not_found()
    if ep.id in not_found:
        result["not_found_cleared"] = True
        if not dry_run:
            not_found.discard(ep.id)
            save_not_found(not_found)

    # 4. Find and delete markdown files for this episode
    # Look for files matching the date_podcast_title pattern
    from src.markdown import generate_filename_base
    base_path = generate_filename_base(ep, output_dir)
    # Also check for variants (with _2, _3 suffix etc.)
    stem = base_path.stem
    for md_file in output_dir.glob(f"{stem}*.md"):
        result["markdown_deleted"].append(str(md_file.name))
        if not dry_run:
            md_file.unlink()

    return result


def print_result(result: dict, dry_run: bool) -> None:
    """Print what was (or would be) cleared for an episode."""
    prefix = "[DRY RUN] Would clear" if dry_run else "Cleared"
    print(f"\n  {prefix}: {result['podcast'][:35]}: {result['title'][:55]}")
    print(f"    Episode ID: {result['episode_id']}")

    if result["cache_files_deleted"]:
        for f in result["cache_files_deleted"]:
            print(f"    ✓ Cache: {f}")
    else:
        print(f"    - No cache files found")

    if result["state_cleared"]:
        print(f"    ✓ State: cleared from processed.json")
    else:
        print(f"    - No state entry found")

    if result["not_found_cleared"]:
        print(f"    ✓ Not-found: removed from _not_found.json")

    if result["markdown_deleted"]:
        for f in result["markdown_deleted"]:
            print(f"    ✓ Markdown: {f}")
    else:
        print(f"    - No markdown files found")


def main():
    parser = argparse.ArgumentParser(
        description="Fix wrong transcripts by clearing cache, state, and markdown for mismatched episodes"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be cleared without actually clearing anything"
    )
    parser.add_argument(
        "--phase", choices=["1", "2", "3", "all"], default="all",
        help="Which phase to fix (1=Stratechery, 3=YouTube, all=both)"
    )
    args = parser.parse_args()

    dry_run = args.dry_run
    phase = args.phase

    if dry_run:
        print("=== DRY RUN MODE - No changes will be made ===\n")

    total_cleared = 0
    total_not_found = 0

    # ── Phase 1: Stratechery mismatches ────────────────────────────────────
    if phase in ("1", "all"):
        print("=" * 60)
        print("PHASE 1: Stratechery Mismatches (8 episodes)")
        print("=" * 60)

        episodes = find_matching_episodes(STRATECHERY_MISMATCH_PATTERNS)

        if not episodes:
            print("  No matching episodes found!")
        else:
            print(f"  Found {len(episodes)} matching episodes:")
            for ep in episodes:
                result = clear_episode(ep, dry_run=dry_run)
                print_result(result, dry_run)
                total_cleared += 1

    # ── Phase 2: Already implemented ───────────────────────────────────────
    if phase == "2":
        print("=" * 60)
        print("PHASE 2: YouTube Algorithm Fix")
        print("=" * 60)
        print("  ✓ Already implemented in src/youtube.py")
        print("  The following are in place:")
        print("  - MatchResult dataclass with confidence scoring")
        print("  - extract_guest_names() to identify expected guests")
        print("  - find_best_match() with guest name scoring (+20/-25)")
        print("  - validate_match() to reject low-confidence matches")
        print("  - fetch_transcript_for_episode() validates before saving")

    # ── Phase 3: YouTube mismatch episodes ─────────────────────────────────
    if phase in ("3", "all"):
        print("\n" + "=" * 60)
        print("PHASE 3: YouTube Search Mismatches (3 episodes)")
        print("=" * 60)

        episodes = find_matching_episodes(YOUTUBE_MISMATCH_PATTERNS)

        if not episodes:
            print("  No matching episodes found!")
        else:
            print(f"  Found {len(episodes)} matching episodes:")
            for ep in episodes:
                result = clear_episode(ep, dry_run=dry_run)
                print_result(result, dry_run)
                total_cleared += 1

    # ── Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if dry_run:
        print(f"DRY RUN COMPLETE: Would clear {total_cleared} episodes")
    else:
        print(f"DONE: Cleared {total_cleared} episodes")

    print("\nNext steps:")
    if phase in ("1", "all"):
        print("  1. Re-process Stratechery episodes (Phase 1):")
        print("     podcastwise -p 'stratechery' --batch --no-rate-limit")
    if phase in ("3", "all"):
        print("  2. Re-process YouTube mismatch episodes (Phase 3):")
        print("     podcastwise --batch --no-rate-limit")
    print("  3. Re-export to Google Sheets:")
    print("     podcastwise --export-sheets")


if __name__ == "__main__":
    main()
