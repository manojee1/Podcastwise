"""
Utility to extract summaries from existing markdown files and cache them.

This allows exporting to Google Sheets without re-processing episodes.
"""

import json
import re
from pathlib import Path

from rich.console import Console

from .state import get_state_manager
from .sheets import SUMMARY_CACHE_DIR, cache_summary
from .summarizer import PodcastSummary


console = Console()

OUTPUT_DIR = Path.home() / "Documents/PodcastNotes"


def parse_markdown_summary(filepath: Path) -> dict:
    """
    Parse a markdown summary file and extract structured data.

    Returns dict with summary fields or empty dict if parsing fails.
    """
    try:
        content = filepath.read_text(encoding='utf-8')
    except Exception as e:
        console.print(f"[red]Error reading {filepath}: {e}[/red]")
        return {}

    result = {
        "tldr": "",
        "who_should_listen": "",
        "key_insights": [],
        "frameworks": [],
        "soundbites": [],
        "takeaways": [],
        "references": {"books": [], "people": [], "tools": [], "links": []},
        "categories": [],
    }

    # Parse YAML frontmatter for categories
    frontmatter_match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL)
    if frontmatter_match:
        frontmatter = frontmatter_match.group(1)
        # Extract categories
        cat_match = re.search(r'categories:\s*\[(.*?)\]', frontmatter)
        if cat_match:
            cats = cat_match.group(1)
            result["categories"] = [c.strip().strip('"\'') for c in cats.split(',') if c.strip()]

    # Extract TL;DR
    tldr_match = re.search(r'## TL;DR\n(.*?)(?=\n## |\n---|\Z)', content, re.DOTALL)
    if tldr_match:
        result["tldr"] = tldr_match.group(1).strip()

    # Extract Who Should Listen
    who_match = re.search(r'## Who Should Listen\n(.*?)(?=\n## |\n---|\Z)', content, re.DOTALL)
    if who_match:
        result["who_should_listen"] = who_match.group(1).strip()

    # Extract Key Insights
    insights_match = re.search(r'## Key Insights\n(.*?)(?=\n## |\n---|\Z)', content, re.DOTALL)
    if insights_match:
        insights_text = insights_match.group(1)
        # Parse bullet points
        result["key_insights"] = [
            line.lstrip('- ').strip()
            for line in insights_text.strip().split('\n')
            if line.strip().startswith('-')
        ]

    # Extract Frameworks & Models
    frameworks_match = re.search(r'## Frameworks & Models\n(.*?)(?=\n## |\n---|\Z)', content, re.DOTALL)
    if frameworks_match:
        frameworks_text = frameworks_match.group(1)
        # Parse ### headers and their content
        framework_parts = re.split(r'\n### ', frameworks_text)
        for part in framework_parts[1:]:  # Skip first empty part
            lines = part.strip().split('\n', 1)
            if lines:
                name = lines[0].strip()
                description = lines[1].strip() if len(lines) > 1 else ""
                result["frameworks"].append({"name": name, "description": description})

    # Extract Soundbites
    soundbites_match = re.search(r'## Soundbites\n(.*?)(?=\n## |\n---|\Z)', content, re.DOTALL)
    if soundbites_match:
        soundbites_text = soundbites_match.group(1)
        # Parse blockquotes - look for > "quote" and > — speaker patterns
        quotes = re.findall(r'>\s*"([^"]+)"[^\n]*\n>\s*—\s*([^\n]+)', soundbites_text)
        for quote, speaker in quotes:
            result["soundbites"].append({"quote": quote.strip(), "speaker": speaker.strip()})

    # Extract Key Takeaways / Action Items
    takeaways_match = re.search(r'## Key Takeaways / Action Items\n(.*?)(?=\n## |\n---|\Z)', content, re.DOTALL)
    if takeaways_match:
        takeaways_text = takeaways_match.group(1)
        # Parse checkbox items
        result["takeaways"] = [
            re.sub(r'^\[[ x]\]\s*', '', line.lstrip('- ').strip())
            for line in takeaways_text.strip().split('\n')
            if line.strip().startswith('-')
        ]

    # Extract References
    refs_match = re.search(r'## References Mentioned\n(.*?)(?=\n## |\n---|\Z)', content, re.DOTALL)
    if refs_match:
        refs_text = refs_match.group(1)

        # Books
        books_match = re.search(r'### Books\n(.*?)(?=\n### |\n## |\n---|\Z)', refs_text, re.DOTALL)
        if books_match:
            result["references"]["books"] = [
                line.lstrip('- ').strip()
                for line in books_match.group(1).strip().split('\n')
                if line.strip().startswith('-')
            ]

        # People
        people_match = re.search(r'### People\n(.*?)(?=\n### |\n## |\n---|\Z)', refs_text, re.DOTALL)
        if people_match:
            result["references"]["people"] = [
                line.lstrip('- ').strip()
                for line in people_match.group(1).strip().split('\n')
                if line.strip().startswith('-')
            ]

        # Tools
        tools_match = re.search(r'### Tools / Products\n(.*?)(?=\n### |\n## |\n---|\Z)', refs_text, re.DOTALL)
        if tools_match:
            result["references"]["tools"] = [
                line.lstrip('- ').strip()
                for line in tools_match.group(1).strip().split('\n')
                if line.strip().startswith('-')
            ]

        # Links
        links_match = re.search(r'### Links\n(.*?)(?=\n### |\n## |\n---|\Z)', refs_text, re.DOTALL)
        if links_match:
            result["references"]["links"] = [
                line.lstrip('- ').strip()
                for line in links_match.group(1).strip().split('\n')
                if line.strip().startswith('-')
            ]

    return result


def cache_existing_summaries() -> dict:
    """
    Parse all existing markdown summaries and cache them.

    Matches markdown files to episode IDs via the state manager.

    Returns:
        Dict with statistics
    """
    state = get_state_manager()

    # Get all successfully processed episodes
    processed = [
        ep for ep in state.list_processed()
        if ep.status == "success" and ep.output_file
    ]

    if not processed:
        console.print("[yellow]No successfully processed episodes found in state.[/yellow]")
        return {"cached": 0, "skipped": 0, "errors": 0}

    console.print(f"[cyan]Found {len(processed)} processed episodes in state[/cyan]")

    # Ensure cache directory exists
    SUMMARY_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    cached = 0
    skipped = 0
    errors = 0

    for proc_ep in processed:
        # Check if already cached
        cache_file = SUMMARY_CACHE_DIR / f"{proc_ep.episode_id}.json"
        if cache_file.exists():
            skipped += 1
            continue

        # Find the markdown file
        md_path = Path(proc_ep.output_file)
        if not md_path.exists():
            console.print(f"[yellow]⊘[/yellow] {proc_ep.episode_title[:45]}... (file not found)")
            errors += 1
            continue

        # Parse the markdown
        summary_data = parse_markdown_summary(md_path)

        if not summary_data.get("who_should_listen"):
            console.print(f"[yellow]⊘[/yellow] {proc_ep.episode_title[:45]}... (parse failed)")
            errors += 1
            continue

        # Create PodcastSummary and cache it
        try:
            summary = PodcastSummary(
                tldr=summary_data["tldr"],
                who_should_listen=summary_data["who_should_listen"],
                key_insights=summary_data["key_insights"],
                frameworks=summary_data["frameworks"],
                soundbites=summary_data["soundbites"],
                takeaways=summary_data["takeaways"],
                references=summary_data["references"],
                categories=summary_data["categories"],
            )

            cache_summary(proc_ep.episode_id, summary)
            cached += 1
            console.print(f"[green]✓[/green] {proc_ep.podcast_name[:25]}: {proc_ep.episode_title[:35]}...")

        except Exception as e:
            console.print(f"[red]✗[/red] {proc_ep.episode_title[:40]}: {e}")
            errors += 1

    return {
        "cached": cached,
        "skipped": skipped,
        "errors": errors,
    }


if __name__ == "__main__":
    console.print("[bold]Caching existing summaries from markdown files...[/bold]\n")

    result = cache_existing_summaries()

    console.print("\n" + "=" * 50)
    console.print("[bold]Cache Summary[/bold]")
    console.print("=" * 50)
    console.print(f"[green]Cached:[/green]  {result['cached']}")
    console.print(f"[blue]Skipped:[/blue] {result['skipped']} (already cached)")
    console.print(f"[red]Errors:[/red]  {result['errors']}")
