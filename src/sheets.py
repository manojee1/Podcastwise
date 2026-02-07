"""
Google Sheets export for podcast summaries.

Exports successfully summarized episodes to a Google Sheet organized by year.
"""

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from rich.console import Console

from .podcast_db import Episode
from .summarizer import PodcastSummary
from .state import get_state_manager, ProcessedEpisode


# Load environment variables
load_dotenv()

console = Console()

# Summary cache location (alongside transcripts)
SUMMARY_CACHE_DIR = Path.home() / "Documents/PodcastNotes/.cache/summaries"


def get_sheets_client():
    """
    Initialize and return a gspread client using service account credentials.

    Requires GOOGLE_SHEETS_CREDENTIALS env var pointing to the service account JSON file.
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise ImportError(
            "Google Sheets dependencies not installed. Run:\n"
            "pip install gspread google-auth"
        )

    creds_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
    if not creds_path:
        raise ValueError(
            "GOOGLE_SHEETS_CREDENTIALS not set in .env file.\n"
            "Add: GOOGLE_SHEETS_CREDENTIALS=/path/to/your/credentials.json"
        )

    creds_path = Path(creds_path).expanduser()
    if not creds_path.exists():
        raise FileNotFoundError(f"Credentials file not found: {creds_path}")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = Credentials.from_service_account_file(str(creds_path), scopes=scopes)
    return gspread.authorize(credentials)


def get_sheet_id() -> str:
    """Get the Google Sheet ID from environment."""
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise ValueError(
            "GOOGLE_SHEET_ID not set in .env file.\n"
            "Add: GOOGLE_SHEET_ID=your-spreadsheet-id"
        )
    return sheet_id


# --- Summary Cache Functions ---

def cache_summary(episode_id: int, summary: PodcastSummary) -> Path:
    """
    Cache a summary to disk for later export.

    Args:
        episode_id: Episode ID
        summary: PodcastSummary object

    Returns:
        Path to cached file
    """
    SUMMARY_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    cache_file = SUMMARY_CACHE_DIR / f"{episode_id}.json"

    with open(cache_file, 'w') as f:
        json.dump(summary.to_dict(), f, indent=2)

    return cache_file


def load_cached_summary(episode_id: int) -> Optional[PodcastSummary]:
    """
    Load a cached summary from disk.

    Args:
        episode_id: Episode ID

    Returns:
        PodcastSummary object or None if not cached
    """
    cache_file = SUMMARY_CACHE_DIR / f"{episode_id}.json"

    if not cache_file.exists():
        return None

    with open(cache_file) as f:
        data = json.load(f)

    return PodcastSummary(
        tldr=data.get("tldr", ""),
        who_should_listen=data.get("who_should_listen", ""),
        key_insights=data.get("key_insights", []),
        frameworks=data.get("frameworks", []),
        soundbites=data.get("soundbites", []),
        takeaways=data.get("takeaways", []),
        references=data.get("references", {"books": [], "people": [], "tools": [], "links": []}),
        categories=data.get("categories", []),
    )


def is_summary_cached(episode_id: int) -> bool:
    """Check if a summary is cached."""
    return (SUMMARY_CACHE_DIR / f"{episode_id}.json").exists()


# --- Category Mapping ---

ALLOWED_CATEGORIES = [
    "Tech",
    "Entertainment",
    "News/Politics",
    "Finance/Economics/Investing",
    "Health",
    "Humor",
    "History",
    "Other",
]

# Map existing categories to new allowed list
CATEGORY_MAP = {
    # Tech
    "tech": "Tech",
    "technology": "Tech",
    "science": "Tech",
    "ai": "Tech",
    # Entertainment
    "entertainment": "Entertainment",
    "humor": "Entertainment",
    "comedy": "Entertainment",
    # News/Politics
    "news": "News/Politics",
    "politics": "News/Politics",
    # Finance/Economics/Investing
    "finance": "Finance/Economics/Investing",
    "economics": "Finance/Economics/Investing",
    "investing": "Finance/Economics/Investing",
    "business": "Finance/Economics/Investing",
    # Health
    "health": "Health",
    # Humor (maps to Entertainment)
    # History
    "history": "History",
    # Relationships -> Other
    "relationships": "Other",
}


def map_category(categories: list[str]) -> str:
    """
    Map a list of categories to a single allowed category.

    Args:
        categories: List of category strings from the summary

    Returns:
        Single category from ALLOWED_CATEGORIES
    """
    if not categories:
        return "Other"

    # Try to map the first category
    for cat in categories:
        cat_lower = cat.lower().strip()
        if cat_lower in CATEGORY_MAP:
            return CATEGORY_MAP[cat_lower]
        # Check if it's already an allowed category
        for allowed in ALLOWED_CATEGORIES:
            if cat_lower == allowed.lower():
                return allowed

    return "Other"


# --- Row Formatting ---

def format_row(episode: ProcessedEpisode, summary: PodcastSummary) -> list:
    """
    Format an episode and summary into a row for Google Sheets.

    Columns:
    1. Podcast Name
    2. Episode Title
    3. Date Listened
    4. Duration (not available from ProcessedEpisode, will be empty)
    5. TL;DR
    6. Category (single)
    7. Key Insights
    8. Frameworks
    9. Soundbites (top 3)

    Returns:
        List of cell values for the row
    """
    # Format date
    try:
        date_obj = datetime.fromisoformat(episode.date_processed)
        date_str = date_obj.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        date_str = ""

    # Map to single category
    category = map_category(summary.categories)

    # Format key insights as bullet list
    insights = "\n".join(f"• {insight}" for insight in summary.key_insights) if summary.key_insights else ""

    # Format frameworks as bullet list
    frameworks = "\n".join(
        f"• {fw.get('name', '')}: {fw.get('description', '')}"
        for fw in summary.frameworks[:5]  # Limit to 5
    ) if summary.frameworks else ""

    # Format soundbites as bullet list (top 3, full quotes)
    soundbites = "\n".join(
        f'• "{sb.get("quote", "")}" —{sb.get("speaker", "Unknown")}'
        for sb in summary.soundbites[:3]
    ) if summary.soundbites else ""

    return [
        episode.podcast_name,
        episode.episode_title,
        date_str,
        "",  # Duration placeholder - would need Episode object
        summary.tldr or "",
        category,
        insights,
        frameworks,
        soundbites,
    ]


def format_row_with_episode(episode: Episode, summary: PodcastSummary) -> list:
    """
    Format an episode and summary into a row for Google Sheets.
    Uses full Episode object so we have duration.
    """
    # Format date
    date_str = episode.date_played.strftime("%Y-%m-%d") if episode.date_played else ""

    # Map to single category
    category = map_category(summary.categories)

    # Format key insights as bullet list
    insights = "\n".join(f"• {insight}" for insight in summary.key_insights) if summary.key_insights else ""

    # Format frameworks as bullet list
    frameworks = "\n".join(
        f"• {fw.get('name', '')}: {fw.get('description', '')}"
        for fw in summary.frameworks[:5]  # Limit to 5
    ) if summary.frameworks else ""

    # Format soundbites as bullet list (top 3, full quotes)
    soundbites = "\n".join(
        f'• "{sb.get("quote", "")}" —{sb.get("speaker", "Unknown")}'
        for sb in summary.soundbites[:3]
    ) if summary.soundbites else ""

    return [
        episode.podcast_name,
        episode.title,
        date_str,
        episode.duration_formatted,
        summary.tldr or "",
        category,
        insights,
        frameworks,
        soundbites,
    ]


# --- Sheet Header ---

SHEET_HEADERS = [
    "Podcast Name",
    "Episode Title",
    "Date Listened",
    "Duration",
    "TL;DR",
    "Category",
    "Key Insights",
    "Frameworks",
    "Soundbites",
]


# --- Year Tab and Duplicate Detection ---

def get_or_create_year_tab(spreadsheet, year: int):
    """
    Get or create a worksheet tab for a specific year.

    Args:
        spreadsheet: gspread Spreadsheet object
        year: Year (e.g., 2025)

    Returns:
        Worksheet for the year
    """
    tab_name = "Summary"

    # Try to get existing tab
    try:
        worksheet = spreadsheet.worksheet(tab_name)
        return worksheet
    except Exception:
        pass  # Tab doesn't exist, create it

    # Create new tab
    worksheet = spreadsheet.add_worksheet(tab_name, rows=1000, cols=10)

    # Add headers
    worksheet.insert_row(SHEET_HEADERS, 1)

    return worksheet


def get_existing_episode_ids(worksheet) -> set[str]:
    """
    Get all episode IDs already in a worksheet.

    Checks column B (Episode Title) - we'll add episode_id as a hidden column.
    For now, returns episode titles to check for duplicates.

    Returns:
        Set of episode titles already in the sheet
    """
    try:
        # Get all values in column B (Episode Title)
        titles = worksheet.col_values(2)
        # Skip header row
        return set(titles[1:]) if len(titles) > 1 else set()
    except Exception:
        return set()


def is_duplicate(worksheet, episode_title: str) -> bool:
    """
    Check if an episode is already in the worksheet.

    Args:
        worksheet: gspread Worksheet object
        episode_title: Episode title to check

    Returns:
        True if episode already exists
    """
    existing = get_existing_episode_ids(worksheet)
    return episode_title in existing


# --- Export Functions ---

def export_to_sheets(
    episodes: Optional[list[Episode]] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
) -> dict:
    """
    Export successfully summarized episodes to Google Sheets.

    Episodes are organized by year into separate tabs.
    Duplicates are automatically skipped.

    Args:
        episodes: Optional list of Episode objects (for duration info).
                  If None, reads from state manager.
        from_date: Optional start date filter
        to_date: Optional end date filter

    Returns:
        Dict with export statistics
    """
    state = get_state_manager()

    # Get all successfully processed episodes
    processed = [
        ep for ep in state.list_processed()
        if ep.status == "success"
    ]

    if not processed:
        console.print("[yellow]No successfully summarized episodes found.[/yellow]")
        return {"exported": 0, "skipped": 0, "duplicates": 0, "errors": 0}

    # Build episode lookup for duration info
    episode_lookup = {}
    if episodes:
        episode_lookup = {ep.id: ep for ep in episodes}

    # Filter by date if specified
    if from_date or to_date:
        filtered = []
        for ep in processed:
            try:
                ep_date = datetime.fromisoformat(ep.date_processed)
                if from_date and ep_date < from_date:
                    continue
                if to_date and ep_date > to_date:
                    continue
                filtered.append(ep)
            except (ValueError, TypeError):
                filtered.append(ep)  # Include if date parsing fails
        processed = filtered

    console.print(f"[cyan]Exporting {len(processed)} episodes to Google Sheets...[/cyan]")

    # Connect to Google Sheets
    try:
        client = get_sheets_client()
        sheet_id = get_sheet_id()
        spreadsheet = client.open_by_key(sheet_id)
    except Exception as e:
        console.print(f"[red]Failed to connect to Google Sheets: {e}[/red]")
        return {"exported": 0, "skipped": 0, "duplicates": 0, "errors": 1, "error": str(e)}

    # Group episodes by year
    episodes_by_year: dict[int, list] = {}
    for ep in processed:
        try:
            ep_date = datetime.fromisoformat(ep.date_processed)
            year = ep_date.year
        except (ValueError, TypeError):
            year = datetime.now().year  # Default to current year

        if year not in episodes_by_year:
            episodes_by_year[year] = []
        episodes_by_year[year].append(ep)

    # Export each year
    exported = 0
    skipped = 0
    duplicates = 0
    errors = 0

    # Cache worksheets and their existing episodes
    worksheet_cache: dict[int, tuple] = {}

    for year in sorted(episodes_by_year.keys(), reverse=True):
        year_episodes = episodes_by_year[year]
        console.print(f"\n[bold]Year {year}[/bold] ({len(year_episodes)} episodes)")

        # Get or create worksheet for this year
        worksheet = get_or_create_year_tab(spreadsheet, year)
        existing_titles = get_existing_episode_ids(worksheet)

        # Collect rows to batch insert
        rows_to_add = []

        for proc_ep in year_episodes:
            # Check for duplicate
            if proc_ep.episode_title in existing_titles:
                console.print(f"[dim]↷ {proc_ep.episode_title[:45]}... (already exists)[/dim]")
                duplicates += 1
                continue

            # Load cached summary
            summary = load_cached_summary(proc_ep.episode_id)

            if not summary:
                console.print(f"[yellow]⊘[/yellow] {proc_ep.episode_title[:45]}... (no cached summary)")
                skipped += 1
                continue

            # Use full Episode object if available for duration
            if proc_ep.episode_id in episode_lookup:
                row = format_row_with_episode(episode_lookup[proc_ep.episode_id], summary)
            else:
                row = format_row(proc_ep, summary)

            rows_to_add.append((proc_ep, row))
            existing_titles.add(proc_ep.episode_title)  # Track for subsequent duplicates

        # Batch insert all rows for this year
        if rows_to_add:
            try:
                worksheet.append_rows(
                    [row for _, row in rows_to_add],
                    value_input_option="RAW"
                )
                for proc_ep, _ in rows_to_add:
                    console.print(f"[green]✓[/green] {proc_ep.podcast_name[:25]}: {proc_ep.episode_title[:35]}...")
                    exported += 1
            except Exception as e:
                console.print(f"[red]✗[/red] Batch insert failed: {e}")
                errors += len(rows_to_add)

    return {
        "exported": exported,
        "skipped": skipped,
        "duplicates": duplicates,
        "errors": errors,
    }


if __name__ == "__main__":
    # Test export
    print("Testing Google Sheets export...")

    result = export_to_sheets()

    print(f"\nExport complete:")
    print(f"  Exported: {result['exported']}")
    print(f"  Skipped:  {result['skipped']}")
    print(f"  Errors:   {result['errors']}")
