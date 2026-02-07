"""
Main processing pipeline for podcast summarization.

Orchestrates the full workflow: selection -> transcripts -> summarization -> markdown
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from .podcast_db import Episode, get_episodes_since
from .youtube import (
    fetch_transcript_for_episode,
    Transcript,
    is_not_found,
    mark_not_found,
    clear_not_found,
    CACHE_DIR,
)
from .summarizer import summarize_transcript, PodcastSummary
from .markdown import write_summary, OUTPUT_DIR
from .state import get_state_manager, StateManager
from .sheets import cache_summary


console = Console()


@dataclass
class PipelineResult:
    """Result of processing a single episode through the full pipeline."""
    episode: Episode
    status: str  # "success", "skipped", "no_transcript", "error"
    output_file: Optional[Path] = None
    error_message: Optional[str] = None
    transcript: Optional[Transcript] = None
    summary: Optional[PodcastSummary] = None


def run_pipeline(
    episodes: list[Episode],
    force: bool = False,
    dry_run: bool = False,
    retry_no_transcript: bool = False,
    rate_limit: bool = True,
    model: str = None,
    overwrite: bool = False,
) -> list[PipelineResult]:
    """
    Run the full summarization pipeline on selected episodes.

    Args:
        episodes: List of episodes to process
        force: Re-process even if already summarized
        dry_run: Preview what would be processed without actually doing it
        retry_no_transcript: Retry episodes previously marked as no transcript
        model: Model alias (e.g., 'sonnet', 'haiku', 'gpt-4o')
        overwrite: If True, overwrite existing markdown files. If False, skip if exists.

    Returns:
        List of PipelineResult objects
    """
    state = get_state_manager()
    results = []

    if dry_run:
        console.print("\n[yellow]DRY RUN MODE - No changes will be made[/yellow]\n")

    if rate_limit:
        console.print("[dim]Rate limiting enabled (staying under API limits)[/dim]")

    console.print(f"\n[bold]Processing {len(episodes)} episodes...[/bold]")

    # First pass: check what needs processing
    to_process = []
    for ep in episodes:
        # Check if already processed
        if not force and state.is_processed(ep.id):
            processed = state.get_processed(ep.id)
            if processed.status == "success":
                results.append(PipelineResult(
                    episode=ep,
                    status="skipped",
                    output_file=Path(processed.output_file) if processed.output_file else None,
                ))
                continue
            elif processed.status == "no_transcript" and not retry_no_transcript:
                results.append(PipelineResult(
                    episode=ep,
                    status="no_transcript",
                    error_message="Previously marked as no transcript available",
                ))
                continue

        to_process.append(ep)

    if not to_process:
        console.print("[yellow]All episodes already processed. Use --force to re-process.[/yellow]")
        return results

    skipped = len(episodes) - len(to_process)
    if skipped > 0:
        console.print(f"[dim]Skipping {skipped} already-processed episodes[/dim]")

    console.print(f"[cyan]Processing {len(to_process)} episodes...[/cyan]\n")

    if dry_run:
        # Just show what would be processed
        console.print("[bold]Would process:[/bold]")
        for ep in to_process:
            console.print(f"  - {ep.podcast_name}: {ep.title[:50]}...")
        return results

    # Process each episode
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Processing...", total=len(to_process))

        for ep in to_process:
            progress.update(task, description=f"[cyan]{ep.podcast_name[:25]}[/cyan]")

            result = _process_single_episode(ep, state, retry_no_transcript, rate_limit, model, overwrite)
            results.append(result)

            progress.advance(task)

    return results


def _process_single_episode(
    episode: Episode,
    state: StateManager,
    retry_no_transcript: bool,
    rate_limit: bool = True,
    model: str = None,
    overwrite: bool = False,
) -> PipelineResult:
    """Process a single episode through the full pipeline."""

    try:
        # Step 1: Fetch transcript
        if retry_no_transcript:
            clear_not_found(episode.id)

        transcript = fetch_transcript_for_episode(episode, use_cache=True)

        if not transcript:
            # Mark as no transcript
            state.mark_no_transcript(
                episode_id=episode.id,
                podcast_name=episode.podcast_name,
                episode_title=episode.title,
            )
            mark_not_found(episode.id)
            return PipelineResult(
                episode=episode,
                status="no_transcript",
                error_message="No YouTube transcript found",
            )

        # Step 2: Summarize with LLM
        summary = summarize_transcript(episode, transcript, model=model, rate_limit=rate_limit)

        # Step 2.5: Cache summary for later export
        cache_summary(episode.id, summary)

        # Step 3: Generate markdown
        output_file = write_summary(episode, summary, transcript, overwrite=overwrite)

        # Step 4: Update state
        state.mark_processed(
            episode_id=episode.id,
            podcast_name=episode.podcast_name,
            episode_title=episode.title,
            output_file=str(output_file),
            video_id=transcript.video_id,
            status="success",
        )

        return PipelineResult(
            episode=episode,
            status="success",
            output_file=output_file,
            transcript=transcript,
            summary=summary,
        )

    except Exception as e:
        # Mark as error
        state.mark_error(
            episode_id=episode.id,
            podcast_name=episode.podcast_name,
            episode_title=episode.title,
            error=str(e),
        )
        return PipelineResult(
            episode=episode,
            status="error",
            error_message=str(e),
        )


def print_pipeline_summary(results: list[PipelineResult]) -> None:
    """Print a summary of pipeline results."""

    success = [r for r in results if r.status == "success"]
    skipped = [r for r in results if r.status == "skipped"]
    no_transcript = [r for r in results if r.status == "no_transcript"]
    errors = [r for r in results if r.status == "error"]

    console.print("\n" + "=" * 60)
    console.print("[bold]Pipeline Summary[/bold]")
    console.print("=" * 60)

    # Stats table
    table = Table(show_header=False, box=None)
    table.add_column(style="bold")
    table.add_column(justify="right")

    table.add_row("[green]✓ Summarized[/green]", str(len(success)))
    table.add_row("[blue]⟳ Skipped (already done)[/blue]", str(len(skipped)))
    table.add_row("[yellow]✗ No transcript[/yellow]", str(len(no_transcript)))
    table.add_row("[red]⚠ Errors[/red]", str(len(errors)))
    table.add_row("", "")
    table.add_row("[bold]Total[/bold]", str(len(results)))

    console.print(table)

    # Show successful outputs
    if success:
        console.print("\n[green]Generated files:[/green]")
        for r in success:
            console.print(f"  {r.output_file}")

    # Show no transcript episodes
    if no_transcript:
        console.print("\n[yellow]No transcript available:[/yellow]")
        for r in no_transcript:
            console.print(f"  - {r.episode.podcast_name}: {r.episode.title[:40]}...")

    # Show errors
    if errors:
        console.print("\n[red]Errors:[/red]")
        for r in errors:
            console.print(f"  - {r.episode.title[:40]}: {r.error_message}")

    # Output directory
    console.print(f"\n[dim]Output directory: {OUTPUT_DIR}[/dim]")


def show_processing_status() -> None:
    """Show current processing status from state."""
    state = get_state_manager()
    stats = state.get_stats()

    console.print("\n[bold]Processing Status[/bold]")
    console.print("=" * 40)
    console.print(f"Total processed:    {stats['total']}")
    console.print(f"  Successful:       {stats['success']}")
    console.print(f"  No transcript:    {stats['no_transcript']}")
    console.print(f"  Errors:           {stats['errors']}")

    # Show recent
    recent = state.list_processed()[:5]
    if recent:
        console.print("\n[bold]Recent:[/bold]")
        for ep in recent:
            status_icon = "✓" if ep.status == "success" else "✗" if ep.status == "error" else "?"
            console.print(f"  {status_icon} {ep.podcast_name[:25]}: {ep.episode_title[:35]}...")


if __name__ == "__main__":
    # Test with a few episodes
    from .podcast_db import get_episodes_since

    episodes = get_episodes_since()[:3]

    console.print("[bold]Testing pipeline with 3 episodes...[/bold]")

    results = run_pipeline(episodes, force=False)
    print_pipeline_summary(results)
