"""
Unified episode model that works with both Apple Podcasts and RSS episodes.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Literal


@dataclass
class UnifiedEpisode:
    """
    A unified episode representation that works for both Apple Podcasts
    and RSS feed episodes.
    """
    id: str  # Apple: int as string, RSS: "rss_{hash}"
    title: str
    podcast_name: str
    source: Literal['apple', 'rss']
    status: str  # 'new', 'processed', 'no_transcript', 'error'

    # Optional fields
    description: Optional[str] = None
    duration_seconds: Optional[float] = None
    date_published: Optional[datetime] = None
    date_played: Optional[datetime] = None
    feed_url: Optional[str] = None
    audio_url: Optional[str] = None
    guid: Optional[str] = None

    @property
    def duration_formatted(self) -> str:
        """Duration as 'Xh Ym' or 'Xm' format."""
        if not self.duration_seconds or self.duration_seconds <= 0:
            return "-"
        total_mins = int(self.duration_seconds / 60)
        hours = total_mins // 60
        mins = total_mins % 60
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{mins}m"

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'title': self.title,
            'podcast_name': self.podcast_name,
            'source': self.source,
            'status': self.status,
            'description': self.description,
            'duration_seconds': self.duration_seconds,
            'duration_formatted': self.duration_formatted,
            'date_published': self.date_published.isoformat() if self.date_published else None,
            'date_played': self.date_played.isoformat() if self.date_played else None,
            'feed_url': self.feed_url,
            'audio_url': self.audio_url,
            'guid': self.guid,
        }


def get_unified_episodes(
    show: Optional[str] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    limit: Optional[int] = None,
    episode_ids: Optional[list[str]] = None,
) -> list[UnifiedEpisode]:
    """
    Get unified episodes from both Apple Podcasts and RSS sources.

    Args:
        show: Filter by podcast name
        status: 'new', 'processed', 'no_transcript'
        source: 'apple', 'rss'
        limit: Maximum number of episodes
        episode_ids: Specific episode IDs to fetch

    Returns:
        List of UnifiedEpisode objects
    """
    from ...state import get_state_manager
    from ...podcast_db import get_episodes_since
    from .follows_db import get_rss_episodes, get_followed_shows

    state = get_state_manager()
    episodes = []

    # Get processed episode IDs for status filtering
    processed_map = {}
    for pe in state.list_processed():
        processed_map[str(pe.episode_id)] = pe.status

    # Fetch specific episodes by ID
    if episode_ids:
        apple_ids = [int(id) for id in episode_ids if not id.startswith('rss_')]
        rss_ids = [id for id in episode_ids if id.startswith('rss_')]

        # Fetch Apple episodes
        if apple_ids:
            all_apple = get_episodes_since()
            for ep in all_apple:
                if ep.id in apple_ids:
                    ep_status = processed_map.get(str(ep.id), 'new')
                    episodes.append(UnifiedEpisode(
                        id=str(ep.id),
                        title=ep.title,
                        podcast_name=ep.podcast_name,
                        source='apple',
                        status=ep_status,
                        description=ep.description,
                        duration_seconds=ep.duration_seconds,
                        date_published=ep.date_published,
                        date_played=ep.date_played,
                        feed_url=ep.feed_url,
                        guid=ep.guid,
                    ))

        # TODO: Fetch specific RSS episodes by ID
        return episodes

    # Fetch from Apple Podcasts if not filtering to RSS only
    if source != 'rss':
        try:
            apple_episodes = get_episodes_since()
            for ep in apple_episodes:
                ep_status = processed_map.get(str(ep.id), 'new')

                # Apply status filter
                if status and ep_status != status:
                    continue

                # Apply show filter
                if show and ep.podcast_name != show:
                    continue

                episodes.append(UnifiedEpisode(
                    id=str(ep.id),
                    title=ep.title,
                    podcast_name=ep.podcast_name,
                    source='apple',
                    status=ep_status,
                    description=ep.description,
                    duration_seconds=ep.duration_seconds,
                    date_published=ep.date_published,
                    date_played=ep.date_played,
                    feed_url=ep.feed_url,
                    guid=ep.guid,
                ))
        except Exception as e:
            print(f"Error fetching Apple Podcasts episodes: {e}")

    # Fetch from RSS if not filtering to Apple only
    if source != 'apple':
        try:
            # Get show name to ID mapping
            followed = {s.podcast_name: s for s in get_followed_shows()}

            rss_episodes = get_rss_episodes()
            for re in rss_episodes:
                # Get podcast name from followed shows
                show_info = None
                for s in followed.values():
                    if s.id == re.show_id:
                        show_info = s
                        break

                if not show_info:
                    continue

                ep_status = processed_map.get(re.id, 'new')

                # Apply status filter
                if status and ep_status != status:
                    continue

                # Apply show filter
                if show and show_info.podcast_name != show:
                    continue

                episodes.append(UnifiedEpisode(
                    id=re.id,
                    title=re.title,
                    podcast_name=show_info.podcast_name,
                    source='rss',
                    status=ep_status,
                    description=re.description,
                    duration_seconds=re.duration_seconds,
                    date_published=re.date_published,
                    feed_url=show_info.feed_url,
                    audio_url=re.audio_url,
                    guid=re.guid,
                ))
        except Exception as e:
            print(f"Error fetching RSS episodes: {e}")

    # Sort by date (most recent first)
    episodes.sort(
        key=lambda e: e.date_played or e.date_published or datetime.min,
        reverse=True
    )

    # Apply limit
    if limit:
        episodes = episodes[:limit]

    return episodes
