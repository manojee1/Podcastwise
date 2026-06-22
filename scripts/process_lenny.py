#!/usr/bin/env python3
"""
Process all Lenny's Podcast transcripts from GitHub.

Fetches 303 transcripts from ChatPRD/lennys-podcast-transcripts, generates
AI summaries, writes markdown notes, and exports to a dedicated Google Sheet.
All output is isolated in ~/Documents/PodcastNotes/LennysPodcasts/ — the
main PodcastNotes directory and state are completely untouched.

Usage:
    python3 scripts/process_lenny.py [options]

Options:
    --model MODEL         LLM alias (default: gemini-flash-3)
    --limit N             Process only the first N episodes
    --dry-run             Print episode titles without writing any files
    --no-rate-limit       Disable API rate limiting
    --export-only         Skip summarization, export processed episodes to sheet
    --force               Re-summarize already processed episodes
"""

import argparse
import os
import sys
import traceback
from pathlib import Path

# ── Env vars MUST be set before any src.* imports ──────────────────────────
# All path-returning functions (get_output_dir, get_state_file, get_cache_dir,
# get_summary_cache_dir, get_sheet_id) call os.getenv() at call time, so
# setting env vars here routes everything to the Lenny-specific locations.
LENNY_DIR = Path("~/Documents/PodcastNotes/LennysPodcasts").expanduser()
os.environ["PODCASTWISE_OUTPUT_DIR"] = str(LENNY_DIR)
os.environ["GOOGLE_SHEET_ID"] = "14cYx9sHcvar77eT7gtriExaUEruaR-FCbJZxpxOtFu0"

# Add project root to sys.path so `src` is importable when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Now safe to import src modules ─────────────────────────────────────────
from rich.console import Console
from rich.progress import track

from src.lenny import (
    LENNY_SHEET_ID,
    build_episode,
    build_transcript,
    fetch_transcript_md,
    get_episode_slugs,
    parse_transcript_md,
)
from src.markdown import get_output_dir, write_summary
from src.sheets import cache_summary, export_to_sheets
from src.state import get_state_manager, reset_state_manager
from src.summarizer import DEFAULT_MODEL, summarize_transcript
from src.youtube import get_cache_dir


console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process all Lenny's Podcast transcripts from GitHub"
    )
    parser.add_argument(
        "--model",
        default="gemini-flash-3",
        help="LLM model alias to use for summarization (default: gemini-flash-3)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process only the first N episodes",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print episode titles without writing any files",
    )
    parser.add_argument(
        "--no-rate-limit",
        action="store_true",
        help="Disable API rate limiting between LLM calls",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Skip summarization; only export already-processed episodes to sheet",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-summarize episodes that were already processed",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Ensure the state manager picks up the env var we set above.
    # (Singleton may have been created before env var was set in edge cases.)
    reset_state_manager()

    output_dir = get_output_dir()   # → LennysPodcasts/
    state = get_state_manager()     # → LennysPodcasts/.state/processed.json
    cache_dir = get_cache_dir()     # → LennysPodcasts/.cache/transcripts/

    output_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[bold]Lenny's Podcast Processor[/bold]")
    console.print(f"  Output dir : {output_dir}")
    console.print(f"  State file : {state.state_file}")
    console.print(f"  Cache dir  : {cache_dir}")
    console.print(f"  Model      : {args.model}")
    if args.dry_run:
        console.print("  [yellow]DRY RUN — no files will be written[/yellow]")
    console.print()

    # ── Fetch episode list ────────────────────────────────────────────────
    console.print("[cyan]Fetching episode list from GitHub...[/cyan]")
    try:
        slugs = get_episode_slugs()
    except Exception as e:
        console.print(f"[red]Failed to fetch episode list: {e}[/red]")
        sys.exit(1)

    console.print(f"Found [bold]{len(slugs)}[/bold] episodes on GitHub")

    if args.limit:
        slugs = slugs[: args.limit]
        console.print(f"[dim]Limiting to first {args.limit} episodes[/dim]")

    # ── Export-only mode ─────────────────────────────────────────────────
    if args.export_only:
        console.print("\n[bold]Export-only mode — loading episode metadata...[/bold]")
        all_episodes = []
        for slug in track(slugs, description="Loading metadata..."):
            raw = fetch_transcript_md(slug, cache_dir)
            data = parse_transcript_md(raw or "", slug)
            all_episodes.append(build_episode(slug, data))

        console.print(f"\n[cyan]Exporting {len(all_episodes)} episodes to Google Sheets...[/cyan]")
        try:
            result = export_to_sheets(episodes=all_episodes)
        except Exception as e:
            console.print(f"[red]Export failed ({type(e).__name__}): {e}[/red]")
            console.print(traceback.format_exc())
            return
        console.print(
            f"\n[green]Export complete[/green]: "
            f"{result['exported']} exported, "
            f"{result.get('duplicates', 0)} duplicates, "
            f"{result['skipped']} skipped, "
            f"{result['errors']} errors"
        )
        return

    # ── Main processing loop ─────────────────────────────────────────────
    counts = {"summarized": 0, "skipped": 0, "errors": 0, "no_transcript": 0}

    for slug in track(slugs, description="Processing Lenny episodes..."):
        # Lightweight probe: just build with empty data to get the stable ID
        probe_ep = build_episode(slug, {})

        if not args.force and state.is_processed(probe_ep.id):
            proc = state.get_processed(probe_ep.id)
            if proc and proc.status == "success":
                counts["skipped"] += 1
                continue

        # Fetch transcript (from local cache or GitHub)
        raw = fetch_transcript_md(slug, cache_dir)
        if not raw or not raw.strip():
            state.mark_no_transcript(
                episode_id=probe_ep.id,
                podcast_name="Lenny's Podcast",
                episode_title=slug,
            )
            counts["no_transcript"] += 1
            console.print(f"[yellow]⊘ No transcript[/yellow]: {slug}")
            continue

        data = parse_transcript_md(raw, slug)
        ep = build_episode(slug, data)
        tr = build_transcript(ep, data)

        if args.dry_run:
            console.print(f"[dim][DRY RUN][/dim] Would summarize: {ep.title}")
            continue

        try:
            summary = summarize_transcript(
                ep, tr,
                model=args.model,
                rate_limit=not args.no_rate_limit,
            )
            cache_summary(ep.id, summary)
            output_file = write_summary(ep, summary, tr, output_dir=output_dir, overwrite=args.force)
            state.mark_processed(
                episode_id=ep.id,
                podcast_name=ep.podcast_name,
                episode_title=ep.title,
                output_file=str(output_file),
                video_id=tr.video_id,
                status="success",
            )
            counts["summarized"] += 1
            console.print(f"[green]✓[/green] {ep.title[:65]}")
        except Exception as e:
            state.mark_error(
                episode_id=ep.id,
                podcast_name=ep.podcast_name,
                episode_title=ep.title,
                error=str(e),
            )
            counts["errors"] += 1
            console.print(f"[red]✗ {slug}[/red]: {e}")

    # ── Summary ──────────────────────────────────────────────────────────
    console.print("\n" + "=" * 60)
    console.print("[bold]Processing Summary[/bold]")
    console.print("=" * 60)
    console.print(f"  [green]✓ Summarized[/green]   : {counts['summarized']}")
    console.print(f"  [blue]⟳ Skipped[/blue]       : {counts['skipped']}")
    console.print(f"  [yellow]⊘ No transcript[/yellow]: {counts['no_transcript']}")
    console.print(f"  [red]✗ Errors[/red]        : {counts['errors']}")

    # ── Auto-export to Google Sheets if anything was summarized ──────────
    if not args.dry_run and counts["summarized"] > 0:
        console.print("\n[cyan]Exporting new summaries to Google Sheets...[/cyan]")
        all_episodes = []
        for slug in slugs:
            raw = fetch_transcript_md(slug, cache_dir)
            data = parse_transcript_md(raw or "", slug)
            all_episodes.append(build_episode(slug, data))

        try:
            result = export_to_sheets(episodes=all_episodes)
        except Exception as e:
            console.print(f"[red]Export failed ({type(e).__name__}): {e}[/red]")
            console.print(traceback.format_exc())
            return
        console.print(
            f"[green]Export complete[/green]: "
            f"{result['exported']} exported, "
            f"{result.get('duplicates', 0)} duplicates, "
            f"{result['skipped']} skipped, "
            f"{result['errors']} errors"
        )


if __name__ == "__main__":
    main()
