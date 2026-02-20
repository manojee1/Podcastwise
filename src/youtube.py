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
from datetime import datetime
from pathlib import Path
from typing import Optional
import warnings

# Suppress urllib3 SSL warnings
warnings.filterwarnings('ignore', category=Warning)

import requests
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi

from .podcast_db import Episode


def get_cache_dir() -> Path:
    """Get transcript cache directory, evaluated at runtime."""
    base = Path(os.getenv("PODCASTWISE_OUTPUT_DIR", "~/Documents/PodcastNotes")).expanduser()
    return base / ".cache/transcripts"


def get_cookie_file() -> Path:
    """Get cookie file path, evaluated at runtime."""
    return get_cache_dir() / "youtube_cookies.txt"

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
    cache_dir = get_cache_dir()
    cookie_file = get_cookie_file()
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Use yt-dlp to extract cookies
    cmd = [
        "yt-dlp",
        "--cookies-from-browser", browser,
        "--cookies", str(cookie_file),
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

    if not cookie_file.exists():
        raise RuntimeError(f"Cookie file not created at {cookie_file}")

    return cookie_file


def set_cookie_file(path: str) -> Path:
    """
    Set a manually exported cookie file.

    Args:
        path: Path to a Netscape-format cookie file

    Use this if automatic extraction doesn't work:
    1. Install a browser extension like "Get cookies.txt LOCALLY"
    2. Go to youtube.com and export cookies
    3. Run: podcastwise --set-cookies /path/to/cookies.txt

    Returns:
        Path to the copied cookie file
    """
    source = Path(path).expanduser()
    if not source.exists():
        raise FileNotFoundError(f"Cookie file not found: {source}")

    cache_dir = get_cache_dir()
    cookie_file = get_cookie_file()
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Copy to our cache location
    import shutil
    shutil.copy(source, cookie_file)
    return cookie_file


def has_cookies() -> bool:
    """Check if cookie file exists."""
    return get_cookie_file().exists()


def load_cookies_into_session() -> Optional[requests.Session]:
    """
    Load YouTube cookies into a requests Session.

    Returns:
        requests.Session with cookies loaded, or None if no cookies available
    """
    cookie_file = get_cookie_file()
    if not cookie_file.exists():
        return None

    session = requests.Session()

    # Load Netscape format cookies
    cookie_jar = http.cookiejar.MozillaCookieJar(str(cookie_file))
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
class MatchResult:
    """Result of matching a YouTube video to an episode."""
    match: Optional[YouTubeMatch]
    confidence: float  # 0.0 to 1.0
    reason: str
    guest_names_found: list[str]
    guest_names_missing: list[str]


@dataclass
class YouTubeVideo:
    """Metadata for a standalone YouTube video (not tied to Apple Podcasts)."""
    video_id: str
    title: str
    channel: str
    duration_seconds: int
    upload_date: Optional[datetime] = None
    url: str = ""

    @property
    def duration_formatted(self) -> str:
        """Format duration as 'Xh Ym' or 'Xm'."""
        hours, remainder = divmod(self.duration_seconds, 3600)
        mins = remainder // 60
        return f"{hours}h {mins}m" if hours else f"{mins}m"


@dataclass
class Transcript:
    """Represents a transcript for a podcast episode."""
    episode_id: int
    video_id: str
    video_url: str
    text: str
    segments: list[dict]  # [{text, start, duration}, ...]
    confidence: float = 1.0  # Match confidence score (0.0 to 1.0)
    match_reason: str = ""  # Explanation of why this match was selected

    def save_to_cache(self, cache_dir: Optional[Path] = None) -> Path:
        """Save transcript to cache file."""
        if cache_dir is None:
            cache_dir = get_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{self.episode_id}_{self.video_id}.json"

        data = {
            "episode_id": self.episode_id,
            "video_id": self.video_id,
            "video_url": self.video_url,
            "text": self.text,
            "segments": self.segments,
            "confidence": self.confidence,
            "match_reason": self.match_reason,
        }

        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return cache_file

    @classmethod
    def load_from_cache(cls, episode_id: int, cache_dir: Optional[Path] = None) -> Optional['Transcript']:
        """Load transcript from cache if exists."""
        if cache_dir is None:
            cache_dir = get_cache_dir()
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
                    # Backward compatibility: default values for new fields
                    confidence=data.get("confidence", 1.0),
                    match_reason=data.get("match_reason", ""),
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


def extract_guest_names(title: str) -> list[str]:
    """
    Extract guest names from episode title using common patterns.

    Patterns recognized:
    - "John Smith:" or "John Smith -" (name at start followed by delimiter)
    - "with John Smith"
    - "John Smith on Topic"
    - "John Smith & Jane Doe:" (multiple guests)

    Args:
        title: Episode title

    Returns:
        List of extracted guest names
    """
    guests = []

    # Common words that are NOT names (to filter false positives)
    non_name_words = {
        'weekly', 'daily', 'monthly', 'annual', 'special', 'bonus', 'live',
        'episode', 'update', 'news', 'market', 'breaking', 'exclusive',
        'part', 'volume', 'series', 'chapter', 'intro', 'outro', 'preview',
        'the', 'and', 'with', 'for', 'from', 'about', 'into', 'over',
    }

    def is_likely_name(text: str) -> bool:
        """Check if text looks like a person's name."""
        parts = text.split()
        if len(parts) < 2:
            return False
        # Check that first word isn't a common non-name word
        if parts[0].lower() in non_name_words:
            return False
        # All parts should be capitalized words
        return all(part[0].isupper() for part in parts)

    # Pattern 1: "Name Name:" or "Name Name -" at the start
    # e.g., "Christian Klein: SAP's Vision for AI"
    start_match = re.match(
        r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)(?:\s*[&,]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+))*\s*[:–\-]',
        title
    )
    if start_match:
        # Extract all names from the match
        full_match = start_match.group(0)
        # Remove the trailing delimiter
        names_part = re.sub(r'\s*[:–\-]$', '', full_match)
        # Split by & or , to get individual names
        for name in re.split(r'\s*[&,]\s*', names_part):
            name = name.strip()
            if name and is_likely_name(name):
                guests.append(name)
        if guests:  # Only return if we found valid names
            return guests

    # Pattern 2a: Name after a role title (CEO / Founder / President / etc.)
    # e.g., "An Interview with Sierra Founder and CEO Bret Taylor" → "Bret Taylor"
    # e.g., "An Interview with Cloudflare CEO Matthew Prince" → "Matthew Prince"
    # Limit to exactly 2 capitalized words (first + last name) so we don't
    # accidentally capture "Bret Taylor About AI" or similar phrases.
    role_match = re.search(
        r'\b(?:CEO|CTO|CFO|CPO|COO|CSO|President|Chairman|Co-Founder|Co-CEO)\s+'
        r'([A-Z][a-z]+\s+[A-Z][a-z]+)',
        title
    )
    if role_match:
        name = role_match.group(1).strip()
        if is_likely_name(name):
            guests.append(name)
            return guests

    # Pattern 2b: "with Guest Name" pattern (case-SENSITIVE — do NOT use
    # re.IGNORECASE here, it makes [A-Z][a-z]+ match any word, capturing the
    # entire remaining title instead of just the guest's name).
    # Capture exactly 2 words (first + last name) to avoid trailing words like
    # "About", "On", etc. being pulled in.
    # e.g., "The Future of AI with Sundar Pichai" → "Sundar Pichai"
    with_match = re.search(
        r'\bwith\s+([A-Z][a-z]+\s+[A-Z][a-z]+)',
        title,
    )
    if with_match:
        name = with_match.group(1).strip()
        if is_likely_name(name):
            guests.append(name)
        return guests

    # Pattern 3: "Guest Name on Topic" (name at start, followed by " on ")
    # e.g., "Sam Altman on the Future of OpenAI"
    on_match = re.match(
        r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+on\s+',
        title
    )
    if on_match:
        name = on_match.group(1).strip()
        if len(name.split()) >= 2:
            guests.append(name)
        return guests

    return guests


def name_appears_in_text(name: str, text: str) -> bool:
    """
    Check if a guest name appears in text (handles variations).

    Handles:
    - Exact match (case-insensitive)
    - First name + last initial (e.g., "Christian K" for "Christian Klein")
    - Last name only for unique names

    Args:
        name: Guest name to search for (e.g., "Christian Klein")
        text: Text to search in (e.g., video title)

    Returns:
        True if name appears in text
    """
    text_lower = text.lower()
    name_lower = name.lower()

    # Exact match
    if name_lower in text_lower:
        return True

    # Split into parts
    parts = name.split()
    if len(parts) < 2:
        return False

    first_name = parts[0].lower()
    last_name = parts[-1].lower()

    # Check if both first and last name appear (not necessarily adjacent)
    if first_name in text_lower and last_name in text_lower:
        return True

    # Check for "First L." or "First L" pattern
    last_initial = last_name[0]
    pattern = rf'\b{re.escape(first_name)}\s+{re.escape(last_initial)}\.?\b'
    if re.search(pattern, text_lower):
        return True

    # Check if last name appears (for distinctive last names)
    # Only match if it's a word boundary match
    if re.search(rf'\b{re.escape(last_name)}\b', text_lower):
        return True

    return False


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


def find_best_match(episode: Episode, matches: list[YouTubeMatch]) -> MatchResult:
    """
    Find the best YouTube match for an episode with confidence scoring.

    Scoring system:
    - Guest name found in video title: +20 per name
    - Guest name MISSING (expected but not found): -25 per name
    - Channel matches podcast name: +15
    - Duration within 10%: +10
    - Per overlapping title word: +1

    Args:
        episode: The podcast episode to match
        matches: List of candidate YouTube matches

    Returns:
        MatchResult with match, confidence, and guest name analysis
    """
    if not matches:
        return MatchResult(
            match=None,
            confidence=0.0,
            reason="No YouTube matches found",
            guest_names_found=[],
            guest_names_missing=[],
        )

    # Extract expected guest names from episode title
    expected_guests = extract_guest_names(episode.title)

    # Score each match
    scored = []
    episode_duration = episode.duration_seconds

    for match in matches:
        score = 0
        reasons = []
        guests_found = []
        guests_missing = []

        # Check guest names in video title
        for guest in expected_guests:
            if name_appears_in_text(guest, match.title):
                score += 20
                guests_found.append(guest)
                reasons.append(f"Guest '{guest}' found in title")
            else:
                score -= 25
                guests_missing.append(guest)
                reasons.append(f"Guest '{guest}' NOT in title")

        # Channel name matches podcast name (case insensitive)
        if match.channel:
            podcast_name_clean = re.sub(r'\s*\([^)]*\).*$', '', episode.podcast_name)
            podcast_name_clean = re.sub(r'\s*\|.*$', '', podcast_name_clean).strip().lower()
            if podcast_name_clean in match.channel.lower() or match.channel.lower() in podcast_name_clean:
                score += 15
                reasons.append("Channel matches podcast")

        # Duration is within 10% of episode duration
        if match.duration and episode_duration > 0:
            duration_diff = abs(match.duration - episode_duration)
            if duration_diff / episode_duration < 0.1:
                score += 10
                reasons.append("Duration within 10%")
            elif duration_diff / episode_duration < 0.2:
                score += 5
                reasons.append("Duration within 20%")

        # Title contains key words from episode title (excluding common words)
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'it', '|', '-', '–'}
        episode_words = set(episode.title.lower().split()) - stop_words
        match_words = set(match.title.lower().split()) - stop_words
        common_words = episode_words & match_words
        if common_words:
            score += len(common_words)
            reasons.append(f"{len(common_words)} common words")

        scored.append({
            'score': score,
            'match': match,
            'guests_found': guests_found,
            'guests_missing': guests_missing,
            'reasons': reasons,
        })

    # Sort by score descending
    scored.sort(key=lambda x: x['score'], reverse=True)
    best = scored[0]

    # Calculate confidence (normalize score to 0-1 range)
    # Base confidence calculation:
    # - Max positive score ~= 20*guests + 15 + 10 + 10 words = ~55-75 for good match
    # - Negative scores indicate bad match
    raw_score = best['score']

    if raw_score <= 0:
        confidence = 0.0
    elif raw_score >= 50:
        confidence = 1.0
    else:
        confidence = raw_score / 50.0

    # Penalty if expected guests but none found
    if expected_guests and not best['guests_found']:
        confidence = min(confidence, 0.3)  # Cap at 0.3 if no expected guests found

    reason = "; ".join(best['reasons']) if best['reasons'] else "Basic match"

    return MatchResult(
        match=best['match'],
        confidence=round(confidence, 2),
        reason=reason,
        guest_names_found=best['guests_found'],
        guest_names_missing=best['guests_missing'],
    )


def validate_match(
    episode: Episode,
    match_result: MatchResult,
    strict: bool = False
) -> tuple[bool, str]:
    """
    Validate a match before saving transcript.

    Args:
        episode: The podcast episode
        match_result: Result from find_best_match()
        strict: If True, require higher confidence (0.7 vs 0.5)

    Returns:
        Tuple of (is_valid, rejection_reason)
    """
    if match_result.match is None:
        return False, "No match found"

    threshold = 0.7 if strict else 0.5

    # Check confidence threshold
    if match_result.confidence < threshold:
        return False, f"Low confidence ({match_result.confidence:.2f} < {threshold})"

    # Special check: if episode has expected guests but NONE found in video title
    expected_guests = extract_guest_names(episode.title)
    if expected_guests and not match_result.guest_names_found:
        return False, f"Expected guests {expected_guests} not found in video title"

    return True, ""


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

    # Find best match with confidence scoring
    match_result = find_best_match(episode, matches)

    # Validate the match before proceeding
    is_valid, rejection_reason = validate_match(episode, match_result)

    if not is_valid:
        # Log warning for rejected matches
        import sys
        print(
            f"[WARN] Rejected YouTube match for '{episode.title[:50]}...': {rejection_reason}",
            file=sys.stderr
        )
        if match_result.match:
            print(
                f"       Video was: '{match_result.match.title}' (confidence: {match_result.confidence})",
                file=sys.stderr
            )
            if match_result.guest_names_missing:
                print(
                    f"       Missing guests: {match_result.guest_names_missing}",
                    file=sys.stderr
                )
        return None

    best_match = match_result.match

    # Get transcript
    result = get_transcript(best_match.video_id)
    if not result:
        return None

    full_text, segments = result

    # Create transcript object with confidence metadata
    transcript = Transcript(
        episode_id=episode.id,
        video_id=best_match.video_id,
        video_url=best_match.url,
        text=full_text,
        segments=segments,
        confidence=match_result.confidence,
        match_reason=match_result.reason,
    )

    # Cache it
    if use_cache:
        transcript.save_to_cache()

    return transcript


def get_not_found_file() -> Path:
    """Get not-found file path, evaluated at runtime."""
    return get_cache_dir() / "_not_found.json"


def load_not_found() -> set[int]:
    """Load set of episode IDs that have no transcript available."""
    not_found_file = get_not_found_file()
    if not_found_file.exists():
        with open(not_found_file, 'r') as f:
            return set(json.load(f))
    return set()


def save_not_found(episode_ids: set[int]) -> None:
    """Save set of episode IDs with no transcript."""
    not_found_file = get_not_found_file()
    not_found_file.parent.mkdir(parents=True, exist_ok=True)
    with open(not_found_file, 'w') as f:
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


# --- Standalone YouTube Video Functions ---

def fetch_youtube_metadata(url: str) -> YouTubeVideo:
    """
    Fetch metadata for a YouTube video using yt-dlp.

    Args:
        url: YouTube video URL

    Returns:
        YouTubeVideo object with video metadata

    Raises:
        ValueError: If URL is invalid or video not found
    """
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError(f"Invalid YouTube URL: {url}")

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise ValueError(f"Failed to fetch video metadata: {e}")

    # Parse upload date if available
    upload_date = None
    if info.get('upload_date'):
        try:
            upload_date = datetime.strptime(info['upload_date'], '%Y%m%d')
        except ValueError:
            pass

    return YouTubeVideo(
        video_id=video_id,
        title=info.get('title', 'Unknown'),
        channel=info.get('channel', info.get('uploader', 'Unknown')),
        duration_seconds=info.get('duration', 0) or 0,
        upload_date=upload_date,
        url=url,
    )


def fetch_transcript_for_url(url: str) -> Optional[tuple[YouTubeVideo, str, list[dict]]]:
    """
    Fetch transcript for a YouTube URL directly.

    This is for standalone YouTube videos not tied to Apple Podcasts.

    Args:
        url: YouTube video URL

    Returns:
        Tuple of (video_metadata, full_text, segments) or None if no transcript available
    """
    video = fetch_youtube_metadata(url)
    result = get_transcript(video.video_id)
    if not result:
        return None
    full_text, segments = result
    return video, full_text, segments


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
