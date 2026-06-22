"""
YouTube "Podcasts Watched" source module.

Fetches the user's curated "Podcasts" YouTube playlist and builds Episode
objects compatible with the existing pipeline, markdown writer, and Google
Sheets exporter.
"""

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import yt_dlp

from .podcast_db import Episode
from .youtube import get_cookie_file, has_cookies


DEFAULT_PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLX-OwCwXqUc4"

ID_RANGE_START = 3_000_000_000
ID_RANGE_SIZE = 1_000_000_000  # [3B, 4B) -- distinct from Apple (<100k) and Lenny ([2B,3B))


def get_playlist_url() -> str:
    """Get the YouTube-watched playlist URL, evaluated at runtime."""
    return os.getenv("YOUTUBE_WATCHED_PLAYLIST_URL", DEFAULT_PLAYLIST_URL)


def get_cache_file() -> Path:
    """Get path to the YouTube-watched episode metadata cache, evaluated at runtime."""
    base = Path(os.getenv("PODCASTWISE_OUTPUT_DIR", "~/Documents/PodcastNotes")).expanduser()
    return base / ".cache" / "youtube_watched_episodes.json"


def get_playlist_entries(playlist_url: Optional[str] = None) -> list[dict]:
    """
    Fetch flat playlist entries via yt_dlp.

    Args:
        playlist_url: Playlist URL. Defaults to get_playlist_url().

    Returns:
        List of dicts with keys: id (video_id), title, duration (seconds,
        may be None), uploader. Order matches playlist order.
    """
    playlist_url = playlist_url or get_playlist_url()

    ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True}
    if has_cookies():
        ydl_opts['cookiefile'] = str(get_cookie_file())

    entries = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(playlist_url, download=False)
        for entry in (result or {}).get('entries', []):
            if not entry or not entry.get("id"):
                continue
            entries.append({
                "id": entry["id"],
                "title": entry.get("title", "Unknown"),
                "duration": entry.get("duration"),
                "uploader": entry.get("uploader") or entry.get("channel") or "Unknown",
            })
    return entries


def _make_episode_id(video_id: str) -> int:
    """
    Generate a stable integer episode ID from a YouTube video ID.

    Uses SHA-256 to place IDs in range [3B, 4B) -- distinct from Apple
    Podcasts (<= ~100k) and Lenny's Podcast ([2B, 3B)), so all sources can
    coexist in the same state file / output directory without collision.
    """
    h = int(hashlib.sha256(video_id.encode()).hexdigest()[:16], 16)
    return h % ID_RANGE_SIZE + ID_RANGE_START


def video_url(entry: dict) -> str:
    """Build the canonical watch URL for a playlist entry."""
    return f"https://www.youtube.com/watch?v={entry['id']}"


def build_episode(entry: dict) -> Episode:
    """
    Build an Episode object from a playlist entry dict.

    date_played defaults to now() (the playlist gives no add-date);
    date_published is always None (flat-playlist mode doesn't return upload
    dates, and per-video lookups are intentionally skipped for v1).
    """
    duration_seconds = entry.get("duration") or 0
    uploader = entry.get("uploader") or "Unknown"

    return Episode(
        id=_make_episode_id(entry["id"]),
        title=entry.get("title") or entry["id"],
        podcast_name=uploader,
        podcast_author=uploader,
        duration_seconds=float(duration_seconds),
        playhead_seconds=float(duration_seconds),  # treat as fully watched
        date_played=datetime.now(),
        date_published=None,
        feed_url=None,
        guid=entry["id"],
        description=None,
        youtube_url=video_url(entry),
    )


def cache_episode_metadata(episodes: list[Episode]) -> None:
    """
    Persist Episode metadata to a local JSON cache.

    Used so that --export-sheets and auto-sync can populate the Duration
    column for YouTube-watched episodes without re-fetching the playlist.
    Overwrites the cache wholesale with the given episode list.
    """
    cache_file = get_cache_file()
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    data = [{
        "id": ep.id,
        "title": ep.title,
        "podcast_name": ep.podcast_name,
        "podcast_author": ep.podcast_author,
        "duration_seconds": ep.duration_seconds,
        "playhead_seconds": ep.playhead_seconds,
        "date_played": ep.date_played.isoformat() if ep.date_played else None,
        "date_published": ep.date_published.isoformat() if ep.date_published else None,
        "feed_url": ep.feed_url,
        "guid": ep.guid,
        "description": ep.description,
    } for ep in episodes]

    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_cached_episodes() -> list[Episode]:
    """
    Load previously cached YouTube-watched Episode objects.

    Returns:
        List of Episode objects, or [] if no cache file exists.
    """
    cache_file = get_cache_file()
    if not cache_file.exists():
        return []

    with open(cache_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    return [Episode(
        id=item["id"],
        title=item["title"],
        podcast_name=item["podcast_name"],
        podcast_author=item["podcast_author"],
        duration_seconds=item["duration_seconds"],
        playhead_seconds=item["playhead_seconds"],
        date_played=datetime.fromisoformat(item["date_played"]) if item["date_played"] else datetime.now(),
        date_published=datetime.fromisoformat(item["date_published"]) if item["date_published"] else None,
        feed_url=item.get("feed_url"),
        guid=item.get("guid"),
        description=item.get("description"),
        youtube_url=(f"https://www.youtube.com/watch?v={item['guid']}"
                     if item.get("guid") else None),
    ) for item in data]


def get_merged_episodes(playlist_url: Optional[str] = None) -> tuple[list[Episode], bool]:
    """
    Fetch playlist, merge date_played from cache for known videos, update cache.
    Returns (episodes, fetch_succeeded). Falls back to cache on network failure.
    Each Episode has youtube_url set to bypass search in the pipeline.
    """
    cached_by_guid = {ep.guid: ep for ep in load_cached_episodes()}
    try:
        entries = get_playlist_entries(playlist_url)
    except Exception:
        return list(cached_by_guid.values()), False
    episodes = [cached_by_guid.get(e["id"]) or build_episode(e) for e in entries]
    cache_episode_metadata(episodes)
    return episodes, True
