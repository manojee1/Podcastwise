"""
Batch processor for podcast episodes.

Handles fetching transcripts for multiple episodes with progress tracking.
"""

from dataclasses import dataclass
from typing import Optional
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .podcast_db import Episode
from .youtube import (
    fetch_transcript_for_episode,
    Transcript,
    is_not_found,
    mark_not_found,
    clear_not_found,
    CACHE_DIR,
)


console = Console()


@dataclass
class ProcessingResult:
    """Result of processing a single episode."""
    episode: Episode
    transcript: Optional[Transcript]
    status: str  # "success", "cached", "not_found", "error"
    error_message: Optional[str] = None


def process_episodes(
    episodes: list[Episode],
    use_cache: bool = True,
    retry_not_found: bool = False,
) -> list[ProcessingResult]:
    """
    Process multiple episodes to fetch transcripts.

    Args:
        episodes: List of episodes to process
        use_cache: Whether to use cached transcripts
        retry_not_found: Whether to retry episodes previously marked as not found

    Returns:
        List of ProcessingResult objects
    """
    results = []

    console.print(f"\n[bold]Processing {len(episodes)} episodes...[/bold]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching transcripts...", total=len(episodes))

        for episode in episodes:
            progress.update(task, description=f"[cyan]{episode.podcast_name[:25]}[/cyan]")

            # Check if previously marked as not found
            if not retry_not_found and is_not_found(episode.id):
                results.append(ProcessingResult(
                    episode=episode,
                    transcript=None,
                    status="not_found",
                    error_message="Previously marked as not found",
                ))
                progress.advance(task)
                continue

            # Clear not_found status if retrying
            if retry_not_found:
                clear_not_found(episode.id)

            try:
                # Check cache first
                if use_cache:
                    cached = Transcript.load_from_cache(episode.id)
                    if cached:
                        results.append(ProcessingResult(
                            episode=episode,
                            transcript=cached,
                            status="cached",
                        ))
                        progress.advance(task)
                        continue

                # Fetch from YouTube
                transcript = fetch_transcript_for_episode(episode, use_cache=use_cache)

                if transcript:
                    results.append(ProcessingResult(
                        episode=episode,
                        transcript=transcript,
                        status="success",
                    ))
                else:
                    # Mark as not found for future runs
                    mark_not_found(episode.id)
                    results.append(ProcessingResult(
                        episode=episode,
                        transcript=None,
                        status="not_found",
                    ))

            except Exception as e:
                results.append(ProcessingResult(
                    episode=episode,
                    transcript=None,
                    status="error",
                    error_message=str(e),
                ))

            progress.advance(task)

    return results


def print_processing_summary(results: list[ProcessingResult]) -> None:
    """Print a summary of processing results."""
    success = sum(1 for r in results if r.status == "success")
    cached = sum(1 for r in results if r.status == "cached")
    not_found = sum(1 for r in results if r.status == "not_found")
    errors = sum(1 for r in results if r.status == "error")

    console.print("\n[bold]Processing Summary[/bold]")
    console.print("=" * 40)
    console.print(f"[green]✓ Success:[/green]     {success}")
    console.print(f"[blue]⟳ Cached:[/blue]      {cached}")
    console.print(f"[yellow]✗ Not found:[/yellow]  {not_found}")
    console.print(f"[red]⚠ Errors:[/red]     {errors}")
    console.print("=" * 40)
    console.print(f"[bold]Total:[/bold]         {len(results)}")

    # Show not found episodes
    if not_found > 0:
        console.print("\n[yellow]Episodes without transcripts:[/yellow]")
        for r in results:
            if r.status == "not_found":
                console.print(f"  - {r.episode.podcast_name}: {r.episode.title[:50]}...")

    # Show errors
    if errors > 0:
        console.print("\n[red]Errors:[/red]")
        for r in results:
            if r.status == "error":
                console.print(f"  - {r.episode.title[:40]}: {r.error_message}")

    # Show cache location
    console.print(f"\n[dim]Transcripts cached in: {CACHE_DIR}[/dim]")


def get_successful_transcripts(results: list[ProcessingResult]) -> list[tuple[Episode, Transcript]]:
    """Extract successful transcripts from results."""
    return [
        (r.episode, r.transcript)
        for r in results
        if r.transcript is not None
    ]


if __name__ == "__main__":
    from .podcast_db import get_episodes_since

    # Test with a few episodes
    episodes = get_episodes_since()[:5]

    results = process_episodes(episodes)
    print_processing_summary(results)
