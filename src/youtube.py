"""
YouTube transcript extraction module.

Searches YouTube for podcast episodes and extracts transcripts.
Supports cookie authentication to avoid IP blocks.
"""

import json
import os
import re
import hashlib
import subprocess
import http.cookiejar
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import warnings

# Suppress urllib3 SSL warnings
warnings.filterwarnings('ignore', category=Warning)

import requests
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi

from .podcast_db import Episode


# Cache directory for transcripts
CACHE_DIR = Path.home() / "Documents/PodcastNotes/.cache/transcripts"

# Cookie file for YouTube authentication
COOKIE_FILE = CACHE_DIR / "youtube_cookies.txt"

# Default browser for cookie extraction
DEFAULT_BROWSER = os.getenv("YOUTUBE_COOKIE_BROWSER", "chrome")


# --- Cookie Management ---

def extract_cookies(browser: str = None) -> Path:
    """
    Extract YouTube cookies from browser using yt-dlp.

    Args:
        browser: Browser to extract from (chrome, firefox, safari, edge, brave)
                 Defaults to YOUTUBE_COOKIE_BROWSER env var or 'chrome'

    Returns:
        Path to the cookie file

    Note:
        On macOS, you may need to grant Full Disk Access to Terminal in
        System Preferences > Security & Privacy > Privacy > Full Disk Access.
        Alternatively, use a browser extension to export cookies manually.
    """
    browser = browser or DEFAULT_BROWSER
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Use yt-dlp to extract cookies
    cmd = [
        "yt-dlp",
        "--cookies-from-browser", browser,
        "--cookies", str(COOKIE_FILE),
        "--skip-download",
        "https://www.youtube.com",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,  # Increased timeout for Keychain prompts
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip()
            if "Operation not permitted" in error_msg:
                raise RuntimeError(
                    f"Permission denied accessing {browser} cookies.\n"
                    "On macOS, grant Full Disk Access to Terminal:\n"
                    "  System Settings > Privacy & Security > Full Disk Access\n"
                    "Or manually export cookies using a browser extension."
                )
            raise RuntimeError(f"Failed to extract cookies: {error_msg}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            "Cookie extraction timed out.\n"
            "This may happen if a Keychain prompt is waiting. "
            "Try running again and check for any permission dialogs."
        )
    except FileNotFoundError:
        raise RuntimeError("yt-dlp not found. Install with: pip install yt-dlp")

    if not COOKIE_FILE.exists():
        raise RuntimeError(f"Cookie file not created at {COOKIE_FILE}")

    return COOKIE_FILE


def set_cookie_file(path: str) -> None:
    """
    Set a manually exported cookie file.

    Args:
        path: Path to a Netscape-format cookie file

    Use this if automatic extraction doesn't work:
    1. Install a browser extension like "Get cookies.txt LOCALLY"
    2. Go to youtube.com and export cookies
    3. Run: podcastwise --set-cookies /path/to/cookies.txt
    """
    global COOKIE_FILE
    source = Path(path).expanduser()
    if not source.exists():
        raise FileNotFoundError(f"Cookie file not found: {source}")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Copy to our cache location
    import shutil
    shutil.copy(source, COOKIE_FILE)
    return COOKIE_FILE


def has_cookies() -> bool:
    """Check if cookie file exists."""
    return COOKIE_FILE.exists()


def load_cookies_into_session() -> Optional[requests.Session]:
    """
    Load YouTube cookies into a requests Session.

    Returns:
        requests.Session with cookies loaded, or None if no cookies available
    """
    if not COOKIE_FILE.exists():
        return None

    session = requests.Session()

    # Load Netscape format cookies
    cookie_jar = http.cookiejar.MozillaCookieJar(str(COOKIE_FILE))
    try:
        cookie_jar.load(ignore_discard=True, ignore_expires=True)
        session.cookies.update(cookie_jar)
    except Exception:
        return None

    return session


@dataclass
class YouTubeMatch:
    """Represents a YouTube video match for a podcast episode."""
    video_id: str
    title: str
    url: str
    channel: Optional[str] = None
    duration: Optional[int] = None  # seconds


@dataclass
class Transcript:
    """Represents a transcript for a podcast episode."""
    episode_id: int
    video_id: str
    video_url: str
    text: str
    segments: list[dict]  # [{text, start, duration}, ...]

    def save_to_cache(self, cache_dir: Path = CACHE_DIR) -> Path:
        """Save transcript to cache file."""
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{self.episode_id}_{self.video_id}.json"

        data = {
            "episode_id": self.episode_id,
            "video_id": self.video_id,
            "video_url": self.video_url,
            "text": self.text,
            "segments": self.segments,
        }

        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return cache_file

    @classmethod
    def load_from_cache(cls, episode_id: int, cache_dir: Path = CACHE_DIR) -> Optional['Transcript']:
        """Load transcript from cache if exists."""
        if not cache_dir.exists():
            return None

        # Find matching cache file
        for cache_file in cache_dir.glob(f"{episode_id}_*.json"):
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return cls(
                    episode_id=data["episode_id"],
                    video_id=data["video_id"],
                    video_url=data["video_url"],
                    text=data["text"],
                    segments=data["segments"],
                )
        return None


def extract_video_id(url: str) -> Optional[str]:
    """
    Extract video ID from a YouTube URL.

    Supports:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://youtu.be/VIDEO_ID?si=... (with tracking params)

    Args:
        url: YouTube URL

    Returns:
        Video ID or None if URL format is invalid
    """
    # Match youtube.com/watch?v=VIDEO_ID
    match = re.match(r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]+)', url)
    if match:
        return match.group(1)

    # Match youtu.be/VIDEO_ID (with optional query params)
    match = re.match(r'(?:https?://)?youtu\.be/([a-zA-Z0-9_-]+)', url)
    if match:
        return match.group(1)

    return None


def build_search_query(episode: Episode, variant: str = "primary") -> str:
    """
    Build a YouTube search query from episode metadata.

    Args:
        episode: The podcast episode
        variant: Query variant to build:
            - "primary": Full cleaned query (default)
            - "short_title": Podcast name + truncated title (40 chars)
            - "title_only": Just the title (for clip-sharing podcasts)
            - "guest_focused": Podcast name + extracted guest names

    Returns:
        Search query string
    """
    # 1. Clean podcast name - extract core name before parentheses/pipes
    podcast_name = episode.podcast_name
    podcast_name = re.sub(r'\s*\([^)]*\).*$', '', podcast_name)  # Remove (...) and everything after
    podcast_name = re.sub(r'\s*\|.*$', '', podcast_name)         # Remove | suffix
    podcast_name = podcast_name.strip()

    # 2. Clean title - remove episode numbers and pipe suffixes
    title = episode.title
    title = re.sub(r'^#?\d+\s*[-–:]\s*', '', title)              # Episode numbers like "#123 - "
    title = re.sub(r'^Ep\.?\s*\d+\s*[-–:]\s*', '', title, flags=re.IGNORECASE)  # "Ep. 45:"
    title = re.sub(r'\s*\|.*$', '', title)                        # Pipe suffixes
    title = title.strip()

    # 3. Extract guest names from title patterns
    # Patterns: "John Smith & Jane Doe:" or "with John Smith" or "John Smith on Topic"
    guest_names = ""
    guest_match = re.search(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:\s*[&,]\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)*)\s*[:\-–]', title)
    if guest_match:
        guest_names = guest_match.group(1)
    else:
        # Try "with Guest Name" pattern
        with_match = re.search(r'\bwith\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', title, re.IGNORECASE)
        if with_match:
            guest_names = with_match.group(1)

    # 4. Build query based on variant
    if variant == "title_only":
        # Just the title - useful for clip-sharing podcasts where the podcast name
        # doesn't match the original source
        if len(title) > 60:
            title = title[:60]
        return title

    if variant == "short_title":
        # Podcast name + short title
        short_title = title[:40] if len(title) > 40 else title
        return f"{podcast_name} {short_title}".strip()

    if variant == "guest_focused" and guest_names:
        # Podcast name + guest names (if extracted)
        return f"{podcast_name} {guest_names}".strip()

    # Primary variant (default)
    if guest_names:
        # If we have guest names, use them as they're often more specific
        query = f"{podcast_name} {guest_names}"
    else:
        # Truncate title to 60 chars for better matching
        if len(title) > 60:
            title = title[:60]
        query = f"{podcast_name} {title}"

    return query.strip()


def search_youtube(query: str, max_results: int = 5) -> list[YouTubeMatch]:
    """
    Search YouTube for videos matching the query.

    Args:
        query: Search query string
        max_results: Maximum number of results to return

    Returns:
        List of YouTubeMatch objects
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'default_search': f'ytsearch{max_results}',
    }

    matches = []

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(f'ytsearch{max_results}:{query}', download=False)

        if result and 'entries' in result:
            for entry in result['entries']:
                if entry:
                    matches.append(YouTubeMatch(
                        video_id=entry.get('id', ''),
                        title=entry.get('title', ''),
                        url=entry.get('url', f"https://www.youtube.com/watch?v={entry.get('id', '')}"),
                        channel=entry.get('channel'),
                        duration=entry.get('duration'),
                    ))

    return matches


def search_youtube_with_fallback(episode: Episode, max_results: int = 5) -> list[YouTubeMatch]:
    """
    Search YouTube for videos matching a podcast episode, trying multiple strategies.

    Tries different query variants to improve matching for podcasts that:
    - Have complex names with subtitles (e.g., "20VC: Venture Capital | Funding")
    - Share clips from other shows (e.g., "Cheeky Pint" sharing Nadella interview)
    - Have guest names in titles

    Args:
        episode: The podcast episode to search for
        max_results: Maximum results per search query

    Returns:
        List of YouTubeMatch objects from the first successful search
    """
    # Build query variants to try
    variants = ["primary", "guest_focused", "short_title", "title_only"]

    for variant in variants:
        query = build_search_query(episode, variant=variant)
        if not query:
            continue

        matches = search_youtube(query, max_results)
        if matches:
            return matches

    return []


def get_transcript(video_id: str) -> Optional[tuple[str, list[dict]]]:
    """
    Get transcript for a YouTube video.

    Uses cookie authentication if available to avoid IP blocks.

    Args:
        video_id: YouTube video ID

    Returns:
        Tuple of (full_text, segments) or None if no transcript available
    """
    try:
        # Try with cookies if available
        session = load_cookies_into_session()
        if session:
            api = YouTubeTranscriptApi(http_client=session)
        else:
            api = YouTubeTranscriptApi()

        transcript = api.fetch(video_id)

        segments = []
        for seg in transcript:
            segments.append({
                "text": seg.text,
                "start": seg.start,
                "duration": seg.duration,
            })

        full_text = ' '.join(seg['text'] for seg in segments)
        # Clean up newlines within text
        full_text = full_text.replace('\n', ' ')

        return full_text, segments

    except Exception as e:
        # Transcript not available (disabled, private, IP blocked, etc.)
        return None


def find_best_match(episode: Episode, matches: list[YouTubeMatch]) -> Optional[YouTubeMatch]:
    """
    Find the best YouTube match for an episode.

    Uses simple heuristics:
    - Prefer videos with similar duration to the episode
    - Prefer videos from channels matching the podcast name
    """
    if not matches:
        return None

    # If only one match, use it
    if len(matches) == 1:
        return matches[0]

    # Score each match
    scored = []
    episode_duration = episode.duration_seconds

    for match in matches:
        score = 0

        # Channel name matches podcast name (case insensitive)
        if match.channel and episode.podcast_name.lower() in match.channel.lower():
            score += 10

        # Duration is within 20% of episode duration
        if match.duration and episode_duration > 0:
            duration_diff = abs(match.duration - episode_duration)
            if duration_diff / episode_duration < 0.2:
                score += 5
            elif duration_diff / episode_duration < 0.5:
                score += 2

        # Title contains key words from episode title
        episode_words = set(episode.title.lower().split())
        match_words = set(match.title.lower().split())
        common_words = episode_words & match_words
        score += len(common_words)

        scored.append((score, match))

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    return scored[0][1]


def fetch_transcript_for_episode(
    episode: Episode,
    use_cache: bool = True,
    youtube_url: Optional[str] = None,
) -> Optional[Transcript]:
    """
    Fetch transcript for a podcast episode.

    1. Check cache first (if use_cache=True)
    2. If youtube_url provided, use that directly
    3. For Stratechery episodes, try blog first
    4. Fall back to YouTube search
    5. Cache the result

    Args:
        episode: Episode to fetch transcript for
        use_cache: Whether to check/use cached transcripts
        youtube_url: Optional YouTube URL to use instead of searching

    Returns:
        Transcript object or None if not found
    """
    # Check cache first
    if use_cache:
        cached = Transcript.load_from_cache(episode.id)
        if cached:
            return cached

    # If a YouTube URL is provided, use it directly
    if youtube_url:
        video_id = extract_video_id(youtube_url)
        if not video_id:
            raise ValueError(f"Invalid YouTube URL format: {youtube_url}")

        result = get_transcript(video_id)
        if not result:
            return None

        full_text, segments = result
        transcript = Transcript(
            episode_id=episode.id,
            video_id=video_id,
            video_url=youtube_url,
            text=full_text,
            segments=segments,
        )

        if use_cache:
            transcript.save_to_cache()

        return transcript

    # Try Stratechery blog first for Stratechery episodes
    from .stratechery import is_stratechery, fetch_stratechery_transcript
    if is_stratechery(episode):
        transcript = fetch_stratechery_transcript(episode)
        if transcript:
            if use_cache:
                transcript.save_to_cache()
            return transcript

    # Try JP Morgan website for Eye on the Market episodes
    from .jpmorgan import is_eye_on_the_market, fetch_jpmorgan_transcript
    if is_eye_on_the_market(episode):
        transcript = fetch_jpmorgan_transcript(episode)
        if transcript:
            if use_cache:
                transcript.save_to_cache()
            return transcript
        # Fall through to YouTube search if JP Morgan fetch fails

    # Search YouTube with fallback strategy (tries multiple query variants)
    matches = search_youtube_with_fallback(episode)

    if not matches:
        return None

    # Find best match
    best_match = find_best_match(episode, matches)
    if not best_match:
        return None

    # Get transcript
    result = get_transcript(best_match.video_id)
    if not result:
        return None

    full_text, segments = result

    # Create transcript object
    transcript = Transcript(
        episode_id=episode.id,
        video_id=best_match.video_id,
        video_url=best_match.url,
        text=full_text,
        segments=segments,
    )

    # Cache it
    if use_cache:
        transcript.save_to_cache()

    return transcript


# Status tracking for episodes that couldn't find transcripts
NOT_FOUND_FILE = CACHE_DIR / "_not_found.json"


def load_not_found() -> set[int]:
    """Load set of episode IDs that have no transcript available."""
    if NOT_FOUND_FILE.exists():
        with open(NOT_FOUND_FILE, 'r') as f:
            return set(json.load(f))
    return set()


def save_not_found(episode_ids: set[int]) -> None:
    """Save set of episode IDs with no transcript."""
    NOT_FOUND_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(NOT_FOUND_FILE, 'w') as f:
        json.dump(list(episode_ids), f)


def mark_not_found(episode_id: int) -> None:
    """Mark an episode as having no transcript available."""
    not_found = load_not_found()
    not_found.add(episode_id)
    save_not_found(not_found)


def is_not_found(episode_id: int) -> bool:
    """Check if an episode was previously marked as not found."""
    return episode_id in load_not_found()


def clear_not_found(episode_id: int) -> None:
    """Remove an episode from the not-found list (for retry)."""
    not_found = load_not_found()
    not_found.discard(episode_id)
    save_not_found(not_found)


def clear_not_found_matching(episode_ids: list[int]) -> int:
    """
    Clear multiple episodes from the not-found list.

    Args:
        episode_ids: List of episode IDs to clear

    Returns:
        Number of episodes actually cleared (were in the list)
    """
    not_found = load_not_found()
    cleared = 0
    for ep_id in episode_ids:
        if ep_id in not_found:
            not_found.discard(ep_id)
            cleared += 1
    save_not_found(not_found)
    return cleared


def get_not_found_count() -> int:
    """Get the count of episodes in the not-found list."""
    return len(load_not_found())


if __name__ == "__main__":
    # Test with a sample episode
    from .podcast_db import get_episodes_since

    episodes = get_episodes_since()

    print("Testing YouTube transcript pipeline...")
    print("=" * 60)

    # Test with first few episodes
    for ep in episodes[:3]:
        print(f"\nEpisode: {ep.title[:50]}...")
        print(f"Podcast: {ep.podcast_name}")

        query = build_search_query(ep)
        print(f"Search query: {query[:60]}...")

        matches = search_youtube(query, max_results=3)
        print(f"YouTube matches: {len(matches)}")

        if matches:
            best = find_best_match(ep, matches)
            print(f"Best match: {best.title[:50]}...")
            print(f"Video ID: {best.video_id}")

            result = get_transcript(best.video_id)
            if result:
                text, segments = result
                print(f"Transcript: {len(text)} chars, {len(segments)} segments")
            else:
                print("Transcript: NOT AVAILABLE")
        else:
            print("No YouTube matches found")

        print("-" * 60)
