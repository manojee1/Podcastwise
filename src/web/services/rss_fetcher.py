"""
RSS feed fetcher using feedparser.

Fetches new episodes from followed podcast RSS feeds.
"""

import hashlib
from datetime import datetime
from time import mktime
from typing import Optional

try:
    import feedparser
except ImportError:
    feedparser = None


def fetch_episodes_for_show(show_id: int) -> dict:
    """
    Fetch new episodes from a show's RSS feed.

    Returns:
        Dict with 'new_episodes' count and any errors
    """
    if feedparser is None:
        return {'error': 'feedparser not installed. Run: pip install feedparser'}

    from ..models.follows_db import (
        get_followed_show, update_last_fetch, add_rss_episode,
        episode_exists, RSSEpisode
    )

    show = get_followed_show(show_id)
    if not show:
        return {'error': 'Show not found'}

    if not show.feed_url:
        return {'error': 'No feed URL configured for this show', 'new_episodes': 0}

    try:
        feed = feedparser.parse(show.feed_url)

        if feed.bozo and not feed.entries:
            return {'error': f'Failed to parse feed: {feed.bozo_exception}', 'new_episodes': 0}

        new_count = 0
        for entry in feed.entries:
            guid = entry.get('id') or entry.get('link') or entry.get('title')
            if not guid:
                continue

            # Skip if already exists
            if episode_exists(guid, show_id):
                continue

            # Parse duration
            duration = None
            if 'itunes_duration' in entry:
                duration = parse_duration(entry.itunes_duration)

            # Parse publish date
            date_published = None
            if 'published_parsed' in entry and entry.published_parsed:
                date_published = datetime.fromtimestamp(mktime(entry.published_parsed))

            # Get audio URL
            audio_url = None
            for link in entry.get('links', []):
                if link.get('type', '').startswith('audio/'):
                    audio_url = link.get('href')
                    break
            if not audio_url:
                for enc in entry.get('enclosures', []):
                    if enc.get('type', '').startswith('audio/'):
                        audio_url = enc.get('href')
                        break

            # Generate unique ID
            ep_id = f"rss_{hashlib.md5(f'{show_id}:{guid}'.encode()).hexdigest()[:12]}"

            episode = RSSEpisode(
                id=ep_id,
                show_id=show_id,
                guid=guid,
                title=entry.get('title', 'Untitled'),
                description=entry.get('summary', ''),
                duration_seconds=duration,
                date_published=date_published,
                audio_url=audio_url
            )

            add_rss_episode(episode)
            new_count += 1

        # Update last fetch timestamp
        update_last_fetch(show_id)

        return {'new_episodes': new_count}

    except Exception as e:
        return {'error': str(e), 'new_episodes': 0}


def parse_duration(duration_str: str) -> Optional[int]:
    """Parse iTunes duration string to seconds."""
    if not duration_str:
        return None

    try:
        # Try as seconds
        if duration_str.isdigit():
            return int(duration_str)

        # Try as HH:MM:SS or MM:SS
        parts = duration_str.split(':')
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, TypeError):
        pass

    return None


def sync_all_feeds() -> dict:
    """Sync all followed shows' RSS feeds."""
    from ..models.follows_db import get_followed_shows

    shows = get_followed_shows()
    total_new = 0
    errors = []

    for show in shows:
        if show.feed_url:
            result = fetch_episodes_for_show(show.id)
            total_new += result.get('new_episodes', 0)
            if 'error' in result:
                errors.append({'show': show.podcast_name, 'error': result['error']})

    return {
        'total_new': total_new,
        'shows_synced': len([s for s in shows if s.feed_url]),
        'errors': errors
    }
