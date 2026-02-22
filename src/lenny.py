"""
Lenny's Podcast transcript source module.

Fetches and parses transcripts from the ChatPRD/lennys-podcast-transcripts
GitHub repository. Builds Episode and Transcript objects compatible with
the existing summarizer and markdown writer.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

import hashlib

import requests
import yaml

from .podcast_db import Episode
from .youtube import Transcript


GITHUB_API = "https://api.github.com/repos/ChatPRD/lennys-podcast-transcripts/contents/episodes"
RAW_BASE = "https://raw.githubusercontent.com/ChatPRD/lennys-podcast-transcripts/main/episodes"
LENNY_SHEET_ID = "14cYx9sHcvar77eT7gtriExaUEruaR-FCbJZxpxOtFu0"


def get_episode_slugs() -> list[str]:
    """
    Fetch the list of episode directory names from the GitHub API.

    Returns:
        Sorted list of slug strings (e.g. ['a-b-test', 'acme-corp', ...])
    """
    resp = requests.get(GITHUB_API, timeout=30)
    resp.raise_for_status()
    items = resp.json()
    slugs = [item["name"] for item in items if item.get("type") == "dir"]
    return sorted(slugs)


def fetch_transcript_md(slug: str, local_cache_dir: Path) -> Optional[str]:
    """
    Fetch the raw transcript.md for a given episode slug.

    Checks local cache first; falls back to GitHub raw content URL.

    Args:
        slug: Episode directory name (e.g. 'kevin-systrom-instagram')
        local_cache_dir: Directory to cache raw .md files

    Returns:
        Raw markdown text, or None if the fetch failed
    """
    local_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = local_cache_dir / f"{slug}.md"

    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    url = f"{RAW_BASE}/{slug}/transcript.md"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        text = resp.text
        cache_path.write_text(text, encoding="utf-8")
        return text
    except Exception:
        return None


def parse_transcript_md(raw: str, slug: str) -> dict:
    """
    Parse a Lenny transcript.md file into a structured dict.

    Splits on the first two '---' delimiters to separate YAML frontmatter
    from transcript body.

    Args:
        raw: Raw markdown text (may be empty string)
        slug: Episode slug (used as title fallback)

    Returns:
        Dict with keys: title, guest, youtube_url, video_id, publish_date,
        duration_seconds, duration, keywords, description, body
    """
    if not raw or not raw.strip():
        return {
            "title": slug,
            "guest": None,
            "youtube_url": "",
            "video_id": slug,
            "publish_date": None,
            "duration_seconds": 0,
            "duration": None,
            "keywords": [],
            "description": None,
            "body": "",
        }

    # Split on first two '---' separators
    parts = raw.split("---", 2)
    if len(parts) >= 3:
        fm_text = parts[1].strip()
        body = parts[2].strip()
    else:
        # No frontmatter found — treat entire content as body
        fm_text = ""
        body = raw.strip()

    # Parse frontmatter
    try:
        fm = yaml.safe_load(fm_text) if fm_text else {}
        if not isinstance(fm, dict):
            fm = {}
    except Exception:
        fm = {}

    # Resolve publish_date
    publish_date = fm.get("publish_date")
    if publish_date and not isinstance(publish_date, datetime):
        try:
            publish_date = datetime.fromisoformat(str(publish_date))
        except (ValueError, TypeError):
            publish_date = None

    # Resolve duration_seconds
    duration_seconds = fm.get("duration_seconds", 0)
    try:
        duration_seconds = int(duration_seconds) if duration_seconds else 0
    except (ValueError, TypeError):
        duration_seconds = 0

    return {
        "title": fm.get("title") or slug,
        "guest": fm.get("guest"),
        "youtube_url": fm.get("youtube_url") or "",
        "video_id": fm.get("video_id") or slug,
        "publish_date": publish_date,
        "duration_seconds": duration_seconds,
        "duration": fm.get("duration"),
        "keywords": fm.get("keywords") or [],
        "description": fm.get("description"),
        "body": body,
    }


def _make_episode_id(slug: str) -> int:
    """
    Generate a stable integer episode ID from a slug.

    Uses SHA-256 to place IDs in the range [2B, 3B), well above Apple
    Podcasts IDs (≤ ~100k currently). SHA-256 is deterministic regardless
    of PYTHONHASHSEED, unlike Python's built-in hash().

    Args:
        slug: Episode slug string

    Returns:
        Stable integer ID in range [2_000_000_000, 3_000_000_000)
    """
    h = int(hashlib.sha256(slug.encode()).hexdigest()[:16], 16)
    return h % 10**9 + 2_000_000_000


def build_episode(slug: str, data: dict) -> Episode:
    """
    Build an Episode object from parsed transcript data.

    When called before parsing (lightweight probe for state check), pass
    an empty dict — only the slug-derived ID and fallback title will be set.

    Args:
        slug: Episode directory name
        data: Parsed transcript dict from parse_transcript_md(), or {}

    Returns:
        Episode compatible with the summarizer and markdown writer
    """
    duration_seconds = data.get("duration_seconds", 0) or 0
    publish_date = data.get("publish_date")
    now = datetime.now()

    return Episode(
        id=_make_episode_id(slug),
        title=data.get("title") or slug,
        podcast_name="Lenny's Podcast",
        podcast_author="Lenny Rachitsky",
        duration_seconds=float(duration_seconds),
        playhead_seconds=float(duration_seconds),  # treat as fully listened
        date_played=publish_date or now,
        date_published=publish_date,
        feed_url=None,
        guid=slug,
        description=data.get("description"),
    )


def build_transcript(ep: Episode, data: dict) -> Transcript:
    """
    Build a Transcript object from parsed transcript data.

    Args:
        ep: Episode built by build_episode()
        data: Parsed transcript dict from parse_transcript_md()

    Returns:
        Transcript compatible with the summarizer and markdown writer
    """
    body = data.get("body", "")
    duration = ep.duration_seconds

    return Transcript(
        episode_id=ep.id,
        video_id=data.get("video_id") or ep.guid or str(ep.id),
        video_url=data.get("youtube_url") or "",
        text=body,
        segments=[{"text": body, "start": 0.0, "duration": duration}],
        confidence=1.0,
        match_reason="GitHub transcript (ChatPRD/lennys-podcast-transcripts)",
    )
