"""
Podcastwise CLI - Main entry point.

Usage:
    podcastwise                    # Interactive mode: select and summarize
    podcastwise --list             # List all episodes
    podcastwise --stats            # Show listening statistics
    podcastwise --status           # Show processing status
    podcastwise -n 20              # Limit to 20 most recent episodes
    podcastwise -p "stratechery"   # Filter by podcast name
    podcastwise --dry-run          # Preview without processing
    podcastwise --force            # Re-process already summarized episodes
"""

import argparse
from datetime import datetime

from rich.console import Console

from .podcast_db import get_episodes_since, get_episode_count_by_podcast, Episode
from .state import get_state_manager
from .sheets import export_to_sheets
from .summarizer import get_available_models, DEFAULT_MODEL, MODEL_CONFIG
from .youtube import extract_cookies, has_cookies, set_cookie_file, DEFAULT_BROWSER, COOKIE_FILE
from .stratechery import extract_stratechery_cookies, has_stratechery_cookies


def parse_date(date_str: str) -> datetime:
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date format: {date_str}. Use YYYY-MM-DD")


console = Console()


def format_episode_row(ep: Episode, index: int, is_summarized: bool = False) -> str:
    """Format a single episode for display."""
    date_str = ep.date_played.strftime('%Y-%m-%d') if ep.date_played else "?"
    podcast = ep.podcast_name[:28].ljust(28)
    title = ep.title[:42].ljust(42)
    duration = ep.duration_formatted.rjust(6)
    status = ep.status_label

    partial_marker = " *" if ep.is_partial else "  "
    done_marker = " [done]" if is_summarized else "       "

    return f"{index:>4}. {date_str} | {podcast} | {title} | {duration} | {status}{partial_marker}{done_marker}"


def filter_episodes(episodes: list[Episode], args) -> list[Episode]:
    """Apply filters from command line arguments."""
    filtered = episodes

    # Filter by date range
    if hasattr(args, 'from_date') and args.from_date:
        filtered = [ep for ep in filtered if ep.date_played and ep.date_played >= args.from_date]

    if hasattr(args, 'to_date') and args.to_date:
        # Include the entire 'to' day by comparing with the next day
        to_end = datetime(args.to_date.year, args.to_date.month, args.to_date.day, 23, 59, 59)
        filtered = [ep for ep in filtered if ep.date_played and ep.date_played <= to_end]

    # Filter by podcast name
    if args.podcast:
        search = args.podcast.lower()
        filtered = [ep for ep in filtered if search in ep.podcast_name.lower()]

    # Filter by completion status
    if args.complete_only:
        filtered = [ep for ep in filtered if not ep.is_partial]

    # Apply limit (after other filters)
    if args.limit:
        filtered = filtered[:args.limit]

    return filtered


def cmd_list(args):
    """List all episodes since Jan 1, 2025."""
    console.print("[dim]Fetching episodes from Apple Podcasts database...[/dim]\n")

    episodes = get_episodes_since()
    filtered = filter_episodes(episodes, args)

    if not filtered:
        console.print("[yellow]No episodes found matching filters.[/yellow]")
        return

    # Get state manager to check processed status
    state = get_state_manager()

    # Count stats
    total = len(filtered)
    partial = sum(1 for ep in filtered if ep.is_partial)
    complete = total - partial
    # Only count successfully summarized episodes
    summarized = sum(
        1 for ep in filtered
        if (rec := state.get_processed(ep.id)) and rec.status == "success"
    )

    console.print(f"Found {total} episodes ({complete} complete, {partial} partial, {summarized} summarized)")
    console.print("=" * 120)
    console.print(f"{'#':>4}  {'Date':<10} | {'Podcast':<28} | {'Episode':<42} | {'Dur':>6} | Status")
    console.print("-" * 120)

    for i, ep in enumerate(filtered, 1):
        rec = state.get_processed(ep.id)
        is_summarized = rec is not None and rec.status == "success"
        print(format_episode_row(ep, i, is_summarized))

        if i % 50 == 0 and i < total:
            print(f"\n... showing {i} of {total} episodes ...\n")

    console.print("-" * 120)
    console.print(f"Total: {total} episodes | * = partial listen (< 90% complete) | [done] = already summarized")


def cmd_stats(args):
    """Show listening statistics."""
    console.print("[dim]Fetching statistics from Apple Podcasts database...[/dim]\n")

    episodes = get_episodes_since()
    podcast_counts = get_episode_count_by_podcast()

    if not episodes:
        console.print("[yellow]No episodes found since Jan 1, 2025.[/yellow]")
        return

    total = len(episodes)
    partial = sum(1 for ep in episodes if ep.is_partial)
    complete = total - partial

    total_duration_hrs = sum(ep.duration_seconds for ep in episodes) / 3600
    total_listened_hrs = sum(ep.playhead_seconds for ep in episodes) / 3600

    console.print("[bold]Listening Statistics (since Jan 1, 2025)[/bold]\n")
    console.print(f"Total episodes:     {total}")
    console.print(f"Complete listens:   {complete}")
    console.print(f"Partial listens:    {partial}")
    console.print(f"Total duration:     {total_duration_hrs:.1f} hours")
    console.print(f"Time listened:      {total_listened_hrs:.1f} hours")

    console.print("\n[bold]Top 15 Podcasts by Episode Count[/bold]\n")
    for i, (podcast, count) in enumerate(list(podcast_counts.items())[:15], 1):
        console.print(f"{i:>2}. {podcast:<50} {count:>4} episodes")


def cmd_status(args):
    """Show processing status."""
    from .pipeline import show_processing_status
    show_processing_status()


def cmd_export_sheets(args):
    """Export summaries to Google Sheets."""
    console.print("[bold]Exporting to Google Sheets...[/bold]\n")

    # Get episodes for duration info
    episodes = get_episodes_since()

    result = export_to_sheets(
        episodes=episodes,
        from_date=args.from_date if hasattr(args, 'from_date') else None,
        to_date=args.to_date if hasattr(args, 'to_date') else None,
    )

    console.print("\n" + "=" * 50)
    console.print("[bold]Export Summary[/bold]")
    console.print("=" * 50)
    console.print(f"[green]Exported:[/green]   {result['exported']}")
    console.print(f"[blue]Duplicates:[/blue] {result['duplicates']}")
    console.print(f"[yellow]Skipped:[/yellow]   {result['skipped']} (no cached summary)")
    console.print(f"[red]Errors:[/red]     {result['errors']}")


def cmd_run(args):
    """Main interactive mode: select episodes and run pipeline."""
    from .selector import select_episodes, display_selection_summary, confirm_selection
    from .pipeline import run_pipeline, print_pipeline_summary

    console.print("\n[bold]Podcastwise - Podcast Summarizer[/bold]")
    console.print("[dim]Fetching episodes from Apple Podcasts...[/dim]\n")

    episodes = get_episodes_since()

    if not episodes:
        console.print("[red]No episodes found since Jan 1, 2025.[/red]")
        return

    # Apply filters
    filtered = filter_episodes(episodes, args)

    if not filtered:
        console.print("[yellow]No episodes match the filters.[/yellow]")
        return

    # Show filter info
    if args.podcast or args.complete_only or args.limit or args.from_date or args.to_date:
        filters = []
        if args.from_date:
            filters.append(f"from {args.from_date.strftime('%Y-%m-%d')}")
        if args.to_date:
            filters.append(f"to {args.to_date.strftime('%Y-%m-%d')}")
        if args.podcast:
            filters.append(f"podcast contains '{args.podcast}'")
        if args.complete_only:
            filters.append("complete only")
        if args.limit:
            filters.append(f"limit {args.limit}")
        console.print(f"[dim]Filters: {', '.join(filters)}[/dim]")
        console.print(f"[green]Showing {len(filtered)} of {len(episodes)} episodes[/green]\n")
    else:
        console.print(f"[green]Found {len(filtered)} episodes[/green]\n")

    # Batch mode or interactive mode
    if args.batch:
        # Batch mode: process all filtered episodes
        selected = filtered
        console.print(f"[cyan]Batch mode: processing all {len(selected)} episodes[/cyan]")
        display_selection_summary(selected)
    else:
        # Interactive mode: let user select
        selected = select_episodes(filtered)

        if not selected:
            console.print("\n[yellow]No episodes selected. Exiting.[/yellow]")
            return

        display_selection_summary(selected)

    # Add dry-run, force, and auto-sync info
    if args.dry_run:
        console.print("\n[yellow]DRY RUN MODE - Will preview only, no changes made[/yellow]")
    if args.force:
        console.print("\n[cyan]FORCE MODE - Will re-process already summarized episodes[/cyan]")
    if args.overwrite:
        console.print("\n[cyan]OVERWRITE MODE - Will overwrite existing markdown files[/cyan]")
    if args.auto_sync:
        console.print("\n[cyan]AUTO-SYNC - Will export to Google Sheets after processing[/cyan]")

    # Show model being used
    model = args.model or DEFAULT_MODEL
    console.print(f"\n[dim]Model: {model}[/dim]")

    # Show cookie status
    if has_cookies():
        console.print("[dim]YouTube cookies: ✓ active[/dim]")
    else:
        console.print("[dim]YouTube cookies: not set (run --refresh-cookies if transcripts fail)[/dim]")
    if has_stratechery_cookies():
        console.print("[dim]Stratechery cookies: ✓ active[/dim]")
    else:
        console.print("[dim]Stratechery cookies: not set (run --refresh-stratechery-cookies for Stratechery episodes)[/dim]")

    # Skip confirmation in batch mode
    if not args.batch:
        if not confirm_selection(selected):
            console.print("\n[yellow]Selection cancelled.[/yellow]")
            return

    console.print("\n[green]Starting pipeline...[/green]")

    # Run the full pipeline
    results = run_pipeline(
        episodes=selected,
        force=args.force,
        dry_run=args.dry_run,
        retry_no_transcript=args.retry,
        rate_limit=not args.no_rate_limit,
        model=model,
        overwrite=args.overwrite,
    )

    print_pipeline_summary(results)

    # Auto-sync to Google Sheets if enabled
    if args.auto_sync and not args.dry_run:
        successful = [r for r in results if r.status == "success"]
        if successful:
            console.print("\n[cyan]Auto-syncing to Google Sheets...[/cyan]")
            episodes_for_export = get_episodes_since()
            export_result = export_to_sheets(episodes=episodes_for_export)
            console.print(f"[green]Exported {export_result['exported']} episodes to Google Sheets[/green]")


def main():
    parser = argparse.ArgumentParser(
        description="Podcastwise - Track and summarize your podcast listening",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  podcastwise                     Interactive mode (default)
  podcastwise -n 20               Select from 20 most recent episodes
  podcastwise -p "stratechery"    Filter by podcast name
  podcastwise --list              List all episodes
  podcastwise --stats             Show listening statistics
  podcastwise --status            Show processing status
  podcastwise --dry-run           Preview without processing
  podcastwise --force             Re-process already summarized
        """
    )

    # Mode flags
    parser.add_argument(
        '--list', '-l',
        action='store_true',
        help='List all episodes since Jan 1, 2025'
    )
    parser.add_argument(
        '--stats', '-s',
        action='store_true',
        help='Show listening statistics'
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='Show processing status'
    )
    parser.add_argument(
        '--export-sheets',
        action='store_true',
        help='Export summaries to Google Sheets'
    )

    # Filters
    parser.add_argument(
        '--limit', '-n',
        type=int,
        default=None,
        help='Limit number of episodes shown (most recent first)'
    )
    parser.add_argument(
        '--podcast', '-p',
        type=str,
        default=None,
        help='Filter by podcast name (case-insensitive substring match)'
    )
    parser.add_argument(
        '--complete-only',
        action='store_true',
        help='Only show completed episodes (>= 90%% listened)'
    )
    parser.add_argument(
        '--from',
        dest='from_date',
        type=parse_date,
        default=None,
        metavar='YYYY-MM-DD',
        help='Only include episodes listened on or after this date'
    )
    parser.add_argument(
        '--to',
        dest='to_date',
        type=parse_date,
        default=None,
        metavar='YYYY-MM-DD',
        help='Only include episodes listened on or before this date'
    )

    # Pipeline options
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview what would be processed without making changes'
    )
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Re-process episodes that have already been summarized'
    )
    parser.add_argument(
        '--retry',
        action='store_true',
        help='Retry episodes previously marked as "no transcript"'
    )
    parser.add_argument(
        '--batch',
        action='store_true',
        help='Batch mode: process all filtered episodes without interactive selection'
    )
    parser.add_argument(
        '--no-rate-limit',
        action='store_true',
        help='Disable rate limiting (faster but may hit API limits)'
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Overwrite existing markdown files (default: skip if exists)'
    )
    parser.add_argument(
        '--auto-sync',
        action='store_true',
        help='Automatically export to Google Sheets after summarizing'
    )
    parser.add_argument(
        '--model', '-m',
        type=str,
        default=None,
        help='Model to use for summarization (e.g., sonnet, haiku, gpt-4o, or-sonnet). Run --list-models to see all options.'
    )
    parser.add_argument(
        '--list-models',
        action='store_true',
        help='List available models and exit'
    )
    parser.add_argument(
        '--refresh-cookies',
        action='store_true',
        help='Extract YouTube cookies from browser (fixes IP blocks)'
    )
    parser.add_argument(
        '--refresh-stratechery-cookies',
        action='store_true',
        help='Extract Stratechery cookies from browser (for paywall access)'
    )
    parser.add_argument(
        '--set-cookies',
        type=str,
        default=None,
        metavar='FILE',
        help='Import cookies from a manually exported file (Netscape format)'
    )
    parser.add_argument(
        '--browser',
        type=str,
        default=None,
        help=f'Browser to extract cookies from (chrome, firefox, safari, edge, brave). Default: {DEFAULT_BROWSER}'
    )

    args = parser.parse_args()

    # Route to appropriate command
    if args.refresh_cookies:
        browser = args.browser or DEFAULT_BROWSER
        console.print(f"\n[bold]Extracting YouTube cookies from {browser}...[/bold]")
        try:
            cookie_file = extract_cookies(browser)
            console.print(f"[green]✓ Cookies saved to {cookie_file}[/green]")
            console.print("\n[dim]YouTube transcript requests will now use these cookies to avoid IP blocks.[/dim]")
        except Exception as e:
            console.print(f"[red]✗ Failed: {e}[/red]")
            console.print("\n[bold]Alternative: Manual cookie export[/bold]")
            console.print("1. Install browser extension: 'Get cookies.txt LOCALLY'")
            console.print("2. Go to youtube.com while logged in")
            console.print("3. Click extension and export cookies")
            console.print(f"4. Run: podcastwise --set-cookies /path/to/cookies.txt")
    elif args.set_cookies:
        console.print(f"\n[bold]Importing cookies from {args.set_cookies}...[/bold]")
        try:
            cookie_file = set_cookie_file(args.set_cookies)
            console.print(f"[green]✓ Cookies imported to {cookie_file}[/green]")
            console.print("\n[dim]YouTube transcript requests will now use these cookies.[/dim]")
        except Exception as e:
            console.print(f"[red]✗ Failed to import cookies: {e}[/red]")
    elif args.refresh_stratechery_cookies:
        browser = args.browser or DEFAULT_BROWSER
        console.print(f"\n[bold]Extracting Stratechery cookies from {browser}...[/bold]")
        try:
            cookie_file = extract_stratechery_cookies(browser)
            console.print(f"[green]✓ Cookies saved to {cookie_file}[/green]")
            console.print("\n[dim]Stratechery blog requests will now use these cookies for paywall access.[/dim]")
        except Exception as e:
            console.print(f"[red]✗ Failed: {e}[/red]")
            console.print("\n[bold]Alternative: Manual cookie export[/bold]")
            console.print("1. Install browser extension: 'Get cookies.txt LOCALLY'")
            console.print("2. Go to stratechery.com while logged in")
            console.print("3. Click extension and export cookies")
            console.print("4. Copy the file to: ~/Documents/PodcastNotes/.cache/transcripts/stratechery_cookies.txt")
    elif args.list_models:
        console.print("\n[bold]Available Models[/bold]\n")
        console.print(f"[dim]Default: {DEFAULT_MODEL}[/dim]\n")
        console.print("[bold]Anthropic (direct API):[/bold]")
        for alias, (provider, model_id) in MODEL_CONFIG.items():
            if provider == "anthropic":
                console.print(f"  {alias:<12} → {model_id}")
        console.print("\n[bold]OpenRouter:[/bold]")
        for alias, (provider, model_id) in MODEL_CONFIG.items():
            if provider == "openrouter":
                console.print(f"  {alias:<12} → {model_id}")
        console.print("\n[dim]Set default in .env: DEFAULT_MODEL=haiku[/dim]")
    elif args.list:
        cmd_list(args)
    elif args.stats:
        cmd_stats(args)
    elif args.status:
        cmd_status(args)
    elif args.export_sheets:
        cmd_export_sheets(args)
    else:
        cmd_run(args)


if __name__ == "__main__":
    main()
