"""
JP Morgan Eye on the Market transcript extraction module.

Fetches article content from am.jpmorgan.com for Eye on the Market podcast episodes.
"""

import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .podcast_db import Episode
from .youtube import Transcript


# Base URL for Eye on the Market articles
JPMORGAN_EOTM_BASE_URL = "https://am.jpmorgan.com/us/en/asset-management/institutional/insights/market-insights/eye-on-the-market/"


def is_eye_on_the_market(episode: Episode) -> bool:
    """Check if episode is from Eye on the Market podcast."""
    return "eye on the market" in episode.podcast_name.lower()


def build_article_url(episode: Episode) -> str:
    """
    Build JP Morgan article URL from episode title.

    Converts episode title to URL slug:
    - "Supply and The Mam" -> "supply-and-the-mam"

    Args:
        episode: Episode to build URL for

    Returns:
        Full article URL
    """
    title = episode.title

    # Remove common prefixes like episode numbers
    title = re.sub(r'^#?\d+\s*[-–:]\s*', '', title)
    title = re.sub(r'^ep\.?\s*\d+\s*[-–:]\s*', '', title, flags=re.IGNORECASE)

    # Convert to lowercase
    title = title.lower().strip()

    # Remove special characters except spaces and hyphens
    title = re.sub(r'[^\w\s-]', '', title)

    # Replace spaces with hyphens
    title = re.sub(r'\s+', '-', title)

    # Remove multiple consecutive hyphens
    title = re.sub(r'-+', '-', title)

    # Remove leading/trailing hyphens
    title = title.strip('-')

    return f"{JPMORGAN_EOTM_BASE_URL}{title}/"


def create_session() -> requests.Session:
    """Create a requests session with appropriate headers."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    })
    return session


def extract_article_text(url: str) -> Optional[str]:
    """
    Extract article text from a JP Morgan Eye on the Market page.

    Args:
        url: URL of the article

    Returns:
        Article text, or None if extraction failed
    """
    session = create_session()

    try:
        response = session.get(url, timeout=30)
        # Handle rate limiting with retry
        if response.status_code == 429:
            time.sleep(2)
            response = session.get(url, timeout=30)

        # If page not found, return None (will fall back to YouTube)
        if response.status_code == 404:
            return None

        response.raise_for_status()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(response.text, 'html.parser')

    # Find the main article content
    # Try various common content selectors for JP Morgan site
    content = None

    for selector in [
        '.article-body',
        '.article-content',
        '.content-body',
        'article .content',
        '.main-content',
        'main article',
        'article',
        '.post-content',
        '.entry-content',
    ]:
        content = soup.select_one(selector)
        if content:
            break

    if not content:
        # Try to find any large text block
        # Sometimes JP Morgan uses custom class names
        for div in soup.find_all('div'):
            text = div.get_text(strip=True)
            if len(text) > 1000:  # Likely article content
                content = div
                break

    if not content:
        return None

    # Remove unwanted elements
    for unwanted in content.select('script, style, nav, aside, .share-buttons, .related-posts, .comments, .sidebar, header, footer'):
        unwanted.decompose()

    # Extract text with paragraph separation
    paragraphs = []
    for p in content.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'blockquote']):
        text = p.get_text(strip=True)
        if text and len(text) > 10:  # Filter out very short fragments
            paragraphs.append(text)

    if not paragraphs:
        # Fallback to all text
        text = content.get_text(separator='\n', strip=True)
        return text if text and len(text) > 100 else None

    return '\n\n'.join(paragraphs)


def fetch_jpmorgan_transcript(episode: Episode) -> Optional[Transcript]:
    """
    Fetch transcript from JP Morgan Eye on the Market article.

    Args:
        episode: Episode to fetch transcript for

    Returns:
        Transcript object or None if not found/failed
    """
    # Build the article URL from the episode title
    url = build_article_url(episode)

    # Extract article text
    text = extract_article_text(url)
    if not text:
        return None

    # Create transcript object
    # For articles, we create a single segment with the entire text
    segments = [{
        "text": text,
        "start": 0.0,
        "duration": 0.0,
    }]

    # Use URL slug as video ID
    slug = url.rstrip('/').split('/')[-1]

    transcript = Transcript(
        episode_id=episode.id,
        video_id=f"jpmorgan_{slug}",
        video_url=url,
        text=text,
        segments=segments,
    )

    return transcript


if __name__ == "__main__":
    # Test with sample data
    print("Testing JP Morgan module...")

    # Test URL building
    class MockEpisode:
        def __init__(self, title, podcast_name):
            self.title = title
            self.podcast_name = podcast_name
            self.id = 1

    test_episode = MockEpisode("Supply and The Mam", "Eye on the Market")

    print(f"Episode: {test_episode.title}")
    print(f"Is Eye on the Market: {is_eye_on_the_market(test_episode)}")

    url = build_article_url(test_episode)
    print(f"Built URL: {url}")

    print("\nAttempting to fetch article...")
    text = extract_article_text(url)
    if text:
        print(f"Article text: {len(text)} characters")
        print(f"Preview: {text[:200]}...")
    else:
        print("Could not fetch article")
