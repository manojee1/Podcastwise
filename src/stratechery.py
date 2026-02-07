"""
Stratechery blog transcript extraction module.

Fetches article content from stratechery.com as transcript for Stratechery podcast episodes.
Uses browser cookies for paywall authentication.
"""

import http.cookiejar
import re
import subprocess
import time
from pathlib import Path
from typing import Optional
from difflib import SequenceMatcher

import requests
from bs4 import BeautifulSoup

from .podcast_db import Episode
from .youtube import Transcript, CACHE_DIR


# Cookie file for Stratechery authentication
STRATECHERY_COOKIE_FILE = CACHE_DIR / "stratechery_cookies.txt"

# Default browser for cookie extraction
DEFAULT_BROWSER = "chrome"

# Stratechery daily email archive URL
STRATECHERY_ARCHIVE_URL = "https://stratechery.com/category/daily-email/"


def is_stratechery(episode: Episode) -> bool:
    """Check if episode is from Stratechery podcast."""
    return "stratechery" in episode.podcast_name.lower()


def extract_stratechery_cookies(browser: str = None) -> Path:
    """
    Extract Stratechery cookies from browser using yt-dlp.

    Args:
        browser: Browser to extract from (chrome, firefox, safari, edge, brave)

    Returns:
        Path to the cookie file
    """
    browser = browser or DEFAULT_BROWSER
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Use yt-dlp to extract cookies for stratechery.com
    cmd = [
        "yt-dlp",
        "--cookies-from-browser", browser,
        "--cookies", str(STRATECHERY_COOKIE_FILE),
        "--skip-download",
        "https://stratechery.com",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
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

    if not STRATECHERY_COOKIE_FILE.exists():
        raise RuntimeError(f"Cookie file not created at {STRATECHERY_COOKIE_FILE}")

    return STRATECHERY_COOKIE_FILE


def has_stratechery_cookies() -> bool:
    """Check if Stratechery cookie file exists."""
    return STRATECHERY_COOKIE_FILE.exists()


def load_stratechery_session() -> Optional[requests.Session]:
    """
    Load Stratechery cookies into a requests Session.

    Returns:
        requests.Session with cookies loaded, or None if no cookies available
    """
    if not STRATECHERY_COOKIE_FILE.exists():
        return None

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    })

    # Load Netscape format cookies
    cookie_jar = http.cookiejar.MozillaCookieJar(str(STRATECHERY_COOKIE_FILE))
    try:
        cookie_jar.load(ignore_discard=True, ignore_expires=True)
        session.cookies.update(cookie_jar)
    except Exception:
        return None

    return session


def normalize_title(title: str) -> str:
    """Normalize a title for comparison."""
    # Remove common prefixes/suffixes
    title = title.lower().strip()
    # Remove episode numbers like "#123 - " or "Ep. 45:"
    title = re.sub(r'^#?\d+\s*[-–:]\s*', '', title)
    title = re.sub(r'^ep\.?\s*\d+\s*[-–:]\s*', '', title)
    # Remove "| Podcast Name" suffixes
    title = re.sub(r'\s*\|.*$', '', title)
    # Remove common words that differ between podcast and blog
    title = re.sub(r'\b(episode|podcast|update|interview|special)\b', '', title)
    # Remove punctuation and extra whitespace
    title = re.sub(r'[^\w\s]', ' ', title)
    title = re.sub(r'\s+', ' ', title).strip()
    return title


def title_similarity(title1: str, title2: str) -> float:
    """Calculate similarity between two titles (0.0 to 1.0)."""
    norm1 = normalize_title(title1)
    norm2 = normalize_title(title2)
    return SequenceMatcher(None, norm1, norm2).ratio()


def search_stratechery_posts(session: requests.Session, max_pages: int = 3) -> list[dict]:
    """
    Fetch recent posts from Stratechery daily email archive.

    Args:
        session: Authenticated requests session
        max_pages: Maximum number of archive pages to fetch

    Returns:
        List of dicts with 'title' and 'url' keys
    """
    posts = []

    for page in range(1, max_pages + 1):
        if page == 1:
            url = STRATECHERY_ARCHIVE_URL
        else:
            url = f"{STRATECHERY_ARCHIVE_URL}page/{page}/"

        try:
            response = session.get(url, timeout=30)
            # Handle rate limiting
            if response.status_code == 429:
                time.sleep(2)  # Wait and retry once
                response = session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException:
            break

        soup = BeautifulSoup(response.text, 'html.parser')

        # Find article links - h2 a captures the main blog post titles
        articles = soup.select('h2 a')

        for article in articles:
            title = article.get_text(strip=True)
            href = article.get('href')
            # Only include links to stratechery.com (filter out other podcast sites)
            if title and href and 'stratechery.com' in href:
                posts.append({
                    'title': title,
                    'url': href,
                })

        # If we found posts, continue; otherwise stop
        if not articles:
            break

    return posts


def find_matching_post(episode: Episode, posts: list[dict], min_similarity: float = 0.4) -> Optional[dict]:
    """
    Find the best matching blog post for an episode.

    Args:
        episode: Episode to match
        posts: List of posts with 'title' and 'url'
        min_similarity: Minimum similarity score to consider a match

    Returns:
        Best matching post dict, or None if no good match found
    """
    if not posts:
        return None

    best_match = None
    best_score = 0.0

    for post in posts:
        score = title_similarity(episode.title, post['title'])
        if score > best_score:
            best_score = score
            best_match = post

    if best_score >= min_similarity:
        return best_match

    return None


def extract_article_text(session: requests.Session, url: str) -> Optional[str]:
    """
    Extract article text from a Stratechery blog post.

    Args:
        session: Authenticated requests session
        url: URL of the blog post

    Returns:
        Article text, or None if extraction failed
    """
    try:
        response = session.get(url, timeout=30)
        # Handle rate limiting with retry
        if response.status_code == 429:
            time.sleep(2)
            response = session.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(response.text, 'html.parser')

    # Find the main article content - adjust selectors based on actual site structure
    content = None

    # Try various common content selectors
    for selector in [
        'article .entry-content',
        '.entry-content',
        'article .post-content',
        '.post-content',
        'article .content',
        '.article-content',
        'article',
    ]:
        content = soup.select_one(selector)
        if content:
            break

    if not content:
        return None

    # Remove unwanted elements
    for unwanted in content.select('script, style, nav, aside, .share-buttons, .related-posts, .comments, .sidebar'):
        unwanted.decompose()

    # Extract text with paragraph separation
    paragraphs = []
    for p in content.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'blockquote']):
        text = p.get_text(strip=True)
        if text:
            paragraphs.append(text)

    if not paragraphs:
        # Fallback to all text
        text = content.get_text(separator='\n', strip=True)
        return text if text else None

    return '\n\n'.join(paragraphs)


def fetch_stratechery_transcript(episode: Episode) -> Optional[Transcript]:
    """
    Fetch transcript from Stratechery blog post.

    Args:
        episode: Episode to fetch transcript for

    Returns:
        Transcript object or None if not found/failed
    """
    session = load_stratechery_session()
    if not session:
        return None

    # Search for matching posts (use more pages to find older episodes)
    posts = search_stratechery_posts(session, max_pages=15)
    if not posts:
        return None

    # Find best matching post
    match = find_matching_post(episode, posts)
    if not match:
        return None

    # Small delay to avoid rate limiting
    time.sleep(0.5)

    # Extract article text
    text = extract_article_text(session, match['url'])
    if not text:
        return None

    # Create transcript object
    # For blog posts, we create a single segment with the entire text
    segments = [{
        "text": text,
        "start": 0.0,
        "duration": 0.0,
    }]

    transcript = Transcript(
        episode_id=episode.id,
        video_id=f"stratechery_{match['url'].split('/')[-2]}",  # Use slug as ID
        video_url=match['url'],
        text=text,
        segments=segments,
    )

    return transcript


if __name__ == "__main__":
    # Test with sample data
    print("Testing Stratechery module...")

    if has_stratechery_cookies():
        print("✓ Stratechery cookies found")
        session = load_stratechery_session()
        if session:
            posts = search_stratechery_posts(session, max_pages=1)
            print(f"Found {len(posts)} recent posts")
            for post in posts[:5]:
                print(f"  - {post['title'][:60]}...")
    else:
        print("✗ No Stratechery cookies - run --refresh-stratechery-cookies first")
