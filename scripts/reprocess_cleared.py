#!/usr/bin/env python3
"""
Re-process only the 11 episodes cleared by fix_wrong_transcripts.py.

Usage:
    python3 scripts/reprocess_cleared.py [--dry-run] [--phase 1|3|all]
    python3 scripts/reprocess_cleared.py --model haiku
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.podcast_db import get_episodes_since
from src.pipeline import run_pipeline, print_pipeline_summary
from src.summarizer import DEFAULT_MODEL


# Episode IDs for each phase
PHASE1_IDS = {
    48836,  # Anduril / Brian Schimpf
    49095,  # Jon Yu
    51177,  # Tailscale / Avery Pennarun
    55677,  # Checking In on AI and the Big Five
    55739,  # Sierra / Bret Taylor
    57845,  # Cloudflare / Matthew Prince
    58006,  # Dan Kim (Intel/Nvidia)
    63903,  # Gracelin Baskaran (Rare Earths)
}

PHASE3_IDS = {
    57361,  # a16z / Marc Andreessen: Why Perfect Products Become Obsolete
    54126,  # Cognitive Revolution / AI News Crossover / Liron Shapira
    67210,  # Stratechery / Michael Morton (YouTube mismatch)
}

# Phase 4: Feb 2026 batch — extract_guest_names bugs fixed (5 episodes)
PHASE4_IDS = {
    57009,  # The Daily: Modern Love, With Rob Delaney (bug: capital With)
    57008,  # Lenny's: Anthropic co-founder | Ben Mann (bug: pipe-end + co-founder)
    57128,  # Decoder: Can we ever trust an AI lawyer? (no guest → low-bar match)
    57359,  # a16z: Steven Sinofsky & Balaji Srinivasan on... (bug: & before on)
    58111,  # Stratechery: YouTube CEO Neal Mohan (bug: short last-name false pos)
}


def main():
    parser = argparse.ArgumentParser(
        description="Re-process the 11 cleared mismatched episodes"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without processing")
    parser.add_argument("--phase", choices=["1", "3", "4", "all"], default="all",
                        help="Which phase to process (1=Stratechery, 3=YouTube, 4=Feb2026, all=all)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--no-rate-limit", action="store_true",
                        help="Disable rate limiting")
    args = parser.parse_args()

    # Build target ID set
    target_ids = set()
    if args.phase in ("1", "all"):
        target_ids |= PHASE1_IDS
    if args.phase in ("3", "all"):
        target_ids |= PHASE3_IDS
    if args.phase in ("4", "all"):
        target_ids |= PHASE4_IDS

    # Fetch episodes from Apple Podcasts DB
    all_episodes = get_episodes_since()
    episodes = [ep for ep in all_episodes if ep.id in target_ids]

    print(f"Found {len(episodes)} of {len(target_ids)} target episodes")
    print(f"Model: {args.model}")
    print(f"Rate limit: {'disabled' if args.no_rate_limit else 'enabled'}")
    print()

    for ep in episodes:
        print(f"  - [{ep.podcast_name[:25]}] {ep.title[:55]}")

    if not episodes:
        print("No matching episodes found in Apple Podcasts DB.")
        sys.exit(1)

    # Run pipeline with force=False (cache was cleared, so they'll re-fetch),
    # overwrite=True (delete and recreate the markdown files)
    results = run_pipeline(
        episodes=episodes,
        force=False,      # Not needed: state was cleared so they're unprocessed
        dry_run=args.dry_run,
        overwrite=True,   # Overwrite existing markdown if somehow still there
        rate_limit=not args.no_rate_limit,
        model=args.model,
    )

    print_pipeline_summary(results)


if __name__ == "__main__":
    main()
