"""
Interactive episode selector using InquirerPy.

Provides a checkbox interface for selecting episodes to summarize.
"""

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator
from rich.console import Console
from rich.table import Table

from .podcast_db import Episode, get_episodes_since
from .state import get_state_manager


console = Console()


def format_choice_name(ep: Episode, index: int, is_summarized: bool = False) -> str:
    """Format episode for checkbox display."""
    date_str = ep.date_played.strftime('%m/%d') if ep.date_played else "??/??"
    podcast = ep.podcast_name[:25].ljust(25)
    title = ep.title[:38].ljust(38)
    duration = ep.duration_formatted.rjust(6)

    # Status indicator
    if ep.is_partial:
        status = f"({ep.progress_percent}%)"
    else:
        status = "✓"

    # Summarized indicator - only shows for episodes with successful summaries
    done_indicator = "[done]" if is_summarized else "      "

    return f"{date_str} | {podcast} | {title} | {duration} | {status:>6} | {done_indicator}"


def select_episodes(episodes: list[Episode]) -> list[Episode]:
    """
    Display interactive checkbox selector for episodes.

    Args:
        episodes: List of episodes to choose from

    Returns:
        List of selected episodes
    """
    if not episodes:
        console.print("[yellow]No episodes to select.[/yellow]")
        return []

    # Get state manager to check processed status
    state = get_state_manager()

    # Build choices list
    choices = []

    # Group by date for better organization
    current_date = None

    # Count processed episodes
    processed_count = 0

    for i, ep in enumerate(episodes):
        ep_date = ep.date_played.strftime('%Y-%m-%d') if ep.date_played else "Unknown"

        # Check if already successfully summarized
        processed_record = state.get_processed(ep.id)
        is_summarized = processed_record is not None and processed_record.status == "success"
        if is_summarized:
            processed_count += 1

        # Add date separator when date changes
        if ep_date != current_date:
            if current_date is not None:
                choices.append(Separator())  # Add spacing between dates
            choices.append(Separator(f"─── {ep_date} ───"))
            current_date = ep_date

        choices.append(
            Choice(
                value=i,  # Store index to retrieve episode later
                name=format_choice_name(ep, i, is_summarized),
                enabled=False  # Default unchecked
            )
        )

    console.print("\n[bold cyan]Select episodes to summarize[/bold cyan]")
    console.print("[dim]Use ↑/↓ to navigate, Space to select, Enter to confirm[/dim]")
    console.print("[dim]Ctrl+A to select all, Ctrl+R to clear all[/dim]\n")

    # Show episode count
    partial_count = sum(1 for ep in episodes if ep.is_partial)
    console.print(f"[dim]Showing {len(episodes)} episodes ({len(episodes) - partial_count} complete, {partial_count} partial, {processed_count} already summarized)[/dim]")
    console.print("[dim]Episodes marked [done] have already been processed[/dim]\n")

    selected_indices = inquirer.checkbox(
        message="Episodes:",
        choices=choices,
        cycle=True,
        transformer=lambda result: f"{len(result)} selected",
        instruction="(Space to select, Enter to confirm)",
        long_instruction="Ctrl+A: select all | Ctrl+R: clear all",
    ).execute()

    if selected_indices is None:
        return []

    # Return selected episodes
    return [episodes[i] for i in selected_indices]


def display_selection_summary(selected: list[Episode]) -> None:
    """Display a summary table of selected episodes."""
    if not selected:
        console.print("\n[yellow]No episodes selected.[/yellow]")
        return

    table = Table(title=f"\nSelected {len(selected)} episodes for summarization")
    table.add_column("#", style="dim", width=4)
    table.add_column("Date", style="cyan", width=10)
    table.add_column("Podcast", style="green", width=30)
    table.add_column("Episode", width=45)
    table.add_column("Duration", justify="right", width=8)
    table.add_column("Status", justify="center", width=8)

    for i, ep in enumerate(selected, 1):
        date_str = ep.date_played.strftime('%Y-%m-%d') if ep.date_played else "?"
        status = f"{ep.progress_percent}%" if ep.is_partial else "✓"

        table.add_row(
            str(i),
            date_str,
            ep.podcast_name[:30],
            ep.title[:45],
            ep.duration_formatted,
            status
        )

    console.print(table)


def confirm_selection(selected: list[Episode]) -> bool:
    """Ask user to confirm their selection."""
    if not selected:
        return False

    return inquirer.confirm(
        message=f"Proceed with summarizing {len(selected)} episodes?",
        default=True
    ).execute()


def run_interactive_selector() -> list[Episode]:
    """
    Main entry point for interactive episode selection.

    Returns:
        List of confirmed selected episodes
    """
    console.print("\n[bold]Podcastwise - Episode Selector[/bold]")
    console.print("[dim]Fetching episodes from Apple Podcasts...[/dim]\n")

    episodes = get_episodes_since()

    if not episodes:
        console.print("[red]No episodes found since Jan 1, 2025.[/red]")
        return []

    console.print(f"[green]Found {len(episodes)} episodes[/green]\n")

    # Run selection
    selected = select_episodes(episodes)

    if not selected:
        console.print("\n[yellow]No episodes selected. Exiting.[/yellow]")
        return []

    # Show summary
    display_selection_summary(selected)

    # Confirm
    if confirm_selection(selected):
        console.print("\n[green]Selection confirmed![/green]")
        return selected
    else:
        console.print("\n[yellow]Selection cancelled.[/yellow]")
        return []


if __name__ == "__main__":
    selected = run_interactive_selector()
    if selected:
        print(f"\nWould process {len(selected)} episodes")
