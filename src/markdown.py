"""
Markdown file generation for podcast summaries.

Generates formatted markdown files with YAML frontmatter.
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from .podcast_db import Episode
from .summarizer import PodcastSummary
from .youtube import Transcript


def get_output_dir() -> Path:
    """Get output directory, evaluated at runtime."""
    return Path(os.getenv("PODCASTWISE_OUTPUT_DIR", "~/Documents/PodcastNotes")).expanduser()


def slugify(text: str, max_length: int = 50) -> str:
    """Convert text to a URL-friendly slug."""
    # Lowercase and replace spaces with hyphens
    slug = text.lower().strip()
    # Remove special characters
    slug = re.sub(r'[^\w\s-]', '', slug)
    # Replace spaces and multiple hyphens with single hyphen
    slug = re.sub(r'[-\s]+', '-', slug)
    # Truncate
    slug = slug[:max_length].rstrip('-')
    return slug


def generate_filename_base(episode: Episode, output_dir: Optional[Path] = None) -> Path:
    """
    Generate the base filename for the episode summary.

    Format: {YYYY-MM-DD}_{podcast-slug}_{episode-slug}.md
    Does NOT check for existing files or add suffixes.
    """
    if output_dir is None:
        output_dir = get_output_dir()
    date_str = episode.date_played.strftime('%Y-%m-%d') if episode.date_played else 'unknown'
    podcast_slug = slugify(episode.podcast_name, max_length=30)
    episode_slug = slugify(episode.title, max_length=40)

    filename = f"{date_str}_{podcast_slug}_{episode_slug}.md"
    return output_dir / filename


def format_frontmatter(
    episode: Episode,
    summary: PodcastSummary,
    transcript: Optional[Transcript] = None,
) -> str:
    """Generate YAML frontmatter for the markdown file."""

    date_listened = episode.date_played.strftime('%Y-%m-%d') if episode.date_played else ''
    date_published = episode.date_published.strftime('%Y-%m-%d') if episode.date_published else ''

    # Extract guest from title if possible (common patterns)
    guest = ""
    title = episode.title
    if " with " in title.lower():
        parts = re.split(r'\s+with\s+', title, flags=re.IGNORECASE)
        if len(parts) > 1:
            guest = parts[-1].split('|')[0].split(',')[0].strip()
    elif " - " in title and "interview" in title.lower():
        parts = title.split(" - ")
        guest = parts[0].strip()

    youtube_url = transcript.video_url if transcript else ""

    categories_str = ", ".join(summary.categories)

    lines = [
        "---",
        f'podcast: "{episode.podcast_name}"',
        f'episode: "{episode.title}"',
    ]

    if guest:
        lines.append(f'guest: "{guest}"')

    lines.extend([
        f'host: "{episode.podcast_author or "Unknown"}"',
        f'date_listened: {date_listened}',
        f'date_published: {date_published}',
        f'duration: "{episode.duration_formatted}"',
        f'categories: [{categories_str}]',
    ])

    if youtube_url:
        lines.append(f'youtube_url: "{youtube_url}"')

    lines.append("---")

    return "\n".join(lines)


def format_summary_markdown(
    episode: Episode,
    summary: PodcastSummary,
    transcript: Optional[Transcript] = None,
) -> str:
    """Generate full markdown content for a podcast summary."""

    sections = []

    # Frontmatter
    sections.append(format_frontmatter(episode, summary, transcript))

    # Title
    sections.append(f"\n# {episode.title}\n")

    # TL;DR
    sections.append("## TL;DR")
    sections.append(f"{summary.tldr}\n")

    # Who Should Listen
    sections.append("## Who Should Listen")
    sections.append(f"{summary.who_should_listen}\n")

    # Key Insights
    sections.append("## Key Insights")
    for insight in summary.key_insights:
        sections.append(f"- {insight}")
    sections.append("")

    # Frameworks & Models
    if summary.frameworks:
        sections.append("## Frameworks & Models")
        for fw in summary.frameworks:
            sections.append(f"### {fw['name']}")
            sections.append(f"{fw['description']}\n")

    # Soundbites
    if summary.soundbites:
        sections.append("## Soundbites")
        for sb in summary.soundbites:
            quote = sb['quote'].replace('\n', ' ')
            sections.append(f'> "{quote}"')
            sections.append(f"> — {sb['speaker']}\n")

    # Key Takeaways
    sections.append("## Key Takeaways / Action Items")
    for takeaway in summary.takeaways:
        sections.append(f"- [ ] {takeaway}")
    sections.append("")

    # References
    refs = summary.references
    has_refs = any([
        refs.get("books"),
        refs.get("people"),
        refs.get("tools"),
        refs.get("links"),
    ])

    if has_refs:
        sections.append("## References Mentioned")

        if refs.get("books"):
            sections.append("\n### Books")
            for book in refs["books"]:
                sections.append(f"- {book}")

        if refs.get("people"):
            sections.append("\n### People")
            for person in refs["people"]:
                sections.append(f"- {person}")

        if refs.get("tools"):
            sections.append("\n### Tools / Products")
            for tool in refs["tools"]:
                sections.append(f"- {tool}")

        if refs.get("links"):
            sections.append("\n### Links")
            for link in refs["links"]:
                # Make URLs clickable
                if link.startswith("http"):
                    sections.append(f"- [{link}]({link})")
                else:
                    sections.append(f"- {link}")

        sections.append("")

    # Personal Notes (empty section for user)
    sections.append("## Personal Notes")
    sections.append("*Add your own thoughts, connections, and follow-up items here.*\n")

    # Full Transcript (if available)
    if transcript and transcript.text:
        sections.append("---\n")
        sections.append("## Full Transcript")
        sections.append("")
        sections.append("<details>")
        sections.append("<summary>Click to expand transcript</summary>")
        sections.append("")
        sections.append(transcript.text)
        sections.append("")
        sections.append("</details>")
        sections.append("")

    return "\n".join(sections)


def write_summary(
    episode: Episode,
    summary: PodcastSummary,
    transcript: Optional[Transcript] = None,
    output_dir: Optional[Path] = None,
    overwrite: bool = False,
) -> Path:
    """
    Write a podcast summary to a markdown file.

    Args:
        episode: Episode metadata
        summary: Generated summary
        transcript: Optional transcript (for YouTube URL)
        output_dir: Directory to write files to
        overwrite: If True, overwrite existing file. If False, skip if exists.

    Returns:
        Path to the file (existing or newly written)
    """
    if output_dir is None:
        output_dir = get_output_dir()
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename (without suffix logic)
    filepath = generate_filename_base(episode, output_dir)

    # If file exists and not overwriting, return existing path
    if filepath.exists() and not overwrite:
        return filepath

    # Generate markdown content
    content = format_summary_markdown(episode, summary, transcript)

    # Write file
    filepath.write_text(content, encoding='utf-8')

    return filepath


def write_summaries_batch(
    items: list[tuple[Episode, PodcastSummary, Optional[Transcript]]],
    output_dir: Optional[Path] = None,
    overwrite: bool = False,
) -> list[Path]:
    """
    Write multiple summaries to markdown files.

    Args:
        items: List of (episode, summary, transcript) tuples
        output_dir: Directory to write files to
        overwrite: If True, overwrite existing files. If False, skip if exists.

    Returns:
        List of paths to written files
    """
    if output_dir is None:
        output_dir = get_output_dir()
    paths = []
    for episode, summary, transcript in items:
        path = write_summary(episode, summary, transcript, output_dir, overwrite)
        paths.append(path)
    return paths


# --- Standalone YouTube Video Summary ---

def format_youtube_frontmatter(
    video: 'YouTubeVideo',
    summary: PodcastSummary,
) -> str:
    """Generate YAML frontmatter for a YouTube video summary."""
    from .youtube import YouTubeVideo  # Import here to avoid circular import

    date_listened = datetime.now().strftime('%Y-%m-%d')
    date_published = video.upload_date.strftime('%Y-%m-%d') if video.upload_date else ''

    categories_str = ", ".join(summary.categories)

    lines = [
        "---",
        f'podcast: "{video.channel}"',
        f'episode: "{video.title}"',
        f'host: "{video.channel}"',
        f'date_listened: {date_listened}',
        f'date_published: {date_published}',
        f'duration: "{video.duration_formatted}"',
        f'categories: [{categories_str}]',
        f'youtube_url: "{video.url}"',
        "---",
    ]

    return "\n".join(lines)


def format_youtube_summary_markdown(
    video: 'YouTubeVideo',
    summary: PodcastSummary,
    transcript_text: Optional[str] = None,
) -> str:
    """Generate full markdown content for a YouTube video summary."""
    from .youtube import YouTubeVideo  # Import here to avoid circular import

    sections = []

    # Frontmatter
    sections.append(format_youtube_frontmatter(video, summary))

    # Title
    sections.append(f"\n# {video.title}\n")

    # TL;DR
    sections.append("## TL;DR")
    sections.append(f"{summary.tldr}\n")

    # Who Should Listen
    sections.append("## Who Should Listen")
    sections.append(f"{summary.who_should_listen}\n")

    # Key Insights
    sections.append("## Key Insights")
    for insight in summary.key_insights:
        sections.append(f"- {insight}")
    sections.append("")

    # Frameworks & Models
    if summary.frameworks:
        sections.append("## Frameworks & Models")
        for fw in summary.frameworks:
            sections.append(f"### {fw['name']}")
            sections.append(f"{fw['description']}\n")

    # Soundbites
    if summary.soundbites:
        sections.append("## Soundbites")
        for sb in summary.soundbites:
            quote = sb['quote'].replace('\n', ' ')
            sections.append(f'> "{quote}"')
            sections.append(f"> — {sb['speaker']}\n")

    # Key Takeaways
    sections.append("## Key Takeaways / Action Items")
    for takeaway in summary.takeaways:
        sections.append(f"- [ ] {takeaway}")
    sections.append("")

    # References
    refs = summary.references
    has_refs = any([
        refs.get("books"),
        refs.get("people"),
        refs.get("tools"),
        refs.get("links"),
    ])

    if has_refs:
        sections.append("## References Mentioned")

        if refs.get("books"):
            sections.append("\n### Books")
            for book in refs["books"]:
                sections.append(f"- {book}")

        if refs.get("people"):
            sections.append("\n### People")
            for person in refs["people"]:
                sections.append(f"- {person}")

        if refs.get("tools"):
            sections.append("\n### Tools / Products")
            for tool in refs["tools"]:
                sections.append(f"- {tool}")

        if refs.get("links"):
            sections.append("\n### Links")
            for link in refs["links"]:
                # Make URLs clickable
                if link.startswith("http"):
                    sections.append(f"- [{link}]({link})")
                else:
                    sections.append(f"- {link}")

        sections.append("")

    # Personal Notes (empty section for user)
    sections.append("## Personal Notes")
    sections.append("*Add your own thoughts, connections, and follow-up items here.*\n")

    # Full Transcript (if available)
    if transcript_text:
        sections.append("---\n")
        sections.append("## Full Transcript")
        sections.append("")
        sections.append("<details>")
        sections.append("<summary>Click to expand transcript</summary>")
        sections.append("")
        sections.append(transcript_text)
        sections.append("")
        sections.append("</details>")
        sections.append("")

    return "\n".join(sections)


def write_youtube_summary(
    video: 'YouTubeVideo',
    summary: PodcastSummary,
    transcript_text: Optional[str] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    """
    Write a YouTube video summary to a markdown file.

    Args:
        video: YouTubeVideo object with video metadata
        summary: Generated summary
        transcript_text: Optional full transcript text
        output_dir: Directory to write files to

    Returns:
        Path to the written file
    """
    from .youtube import YouTubeVideo  # Import here to avoid circular import

    if output_dir is None:
        output_dir = get_output_dir()
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename
    date_str = datetime.now().strftime('%Y-%m-%d')
    channel_slug = slugify(video.channel, max_length=30)
    title_slug = slugify(video.title, max_length=40)
    filename = f"{date_str}_{channel_slug}_{title_slug}.md"
    filepath = output_dir / filename

    # Generate markdown content
    content = format_youtube_summary_markdown(video, summary, transcript_text)

    # Write file
    filepath.write_text(content, encoding='utf-8')

    return filepath


if __name__ == "__main__":
    # Test with a sample
    import json
    from dotenv import load_dotenv
    load_dotenv("/Users/manojaggarwal/Documents/Podcastwise/.env")

    from .podcast_db import get_episodes_since
    from .youtube import Transcript, get_cache_dir
    from .summarizer import summarize_transcript

    print("Testing markdown generation...")

    # Find a cached transcript
    cache_files = list(get_cache_dir().glob("*.json"))
    if not cache_files:
        print("No cached transcripts found.")
        exit(1)

    with open(cache_files[0]) as f:
        data = json.load(f)

    episode_id = data["episode_id"]
    episodes = get_episodes_since()
    episode = next((ep for ep in episodes if ep.id == episode_id), None)

    if not episode:
        print(f"Episode {episode_id} not found.")
        exit(1)

    transcript = Transcript(
        episode_id=data["episode_id"],
        video_id=data["video_id"],
        video_url=data["video_url"],
        text=data["text"],
        segments=data["segments"],
    )

    print(f"Summarizing: {episode.title[:50]}...")
    summary = summarize_transcript(episode, transcript)

    print("Generating markdown...")
    filepath = write_summary(episode, summary, transcript)

    print(f"\n✓ Written to: {filepath}")
    print(f"\nFile contents:")
    print("=" * 60)
    print(filepath.read_text()[:2000])
    print("...")
