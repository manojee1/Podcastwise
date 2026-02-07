"""
Apple Podcasts database extraction module.

Reads podcast listening history from the macOS Apple Podcasts SQLite database.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


# Apple Podcasts database location on macOS
DB_PATH = Path.home() / "Library/Group Containers/243LU875E5.groups.com.apple.podcasts/Documents/MTLibrary.sqlite"

# Core Data epoch: Jan 1, 2001 00:00:00 UTC
# To convert to Unix timestamp: core_data_ts + 978307200
CORE_DATA_EPOCH_OFFSET = 978307200

# Jan 1, 2025 in Core Data timestamp
JAN_1_2025_CORE_DATA = 757382400


@dataclass
class Episode:
    """Represents a podcast episode from Apple Podcasts."""
    id: int
    title: str
    podcast_name: str
    podcast_author: str
    duration_seconds: float
    playhead_seconds: float
    date_played: datetime
    date_published: Optional[datetime]
    feed_url: Optional[str]
    guid: Optional[str]
    description: Optional[str]

    @property
    def duration_minutes(self) -> int:
        """Duration in minutes, rounded."""
        return int(self.duration_seconds / 60) if self.duration_seconds > 0 else 0

    @property
    def played_minutes(self) -> int:
        """Playhead position in minutes, rounded."""
        return int(self.playhead_seconds / 60) if self.playhead_seconds > 0 else 0

    @property
    def progress_percent(self) -> Optional[int]:
        """Progress percentage (0-100), or None if unknown."""
        if self.duration_seconds <= 0:
            return None
        if self.playhead_seconds <= 0:
            # Playhead at 0 typically means fully played (reset)
            return 100
        return int((self.playhead_seconds / self.duration_seconds) * 100)

    @property
    def is_partial(self) -> bool:
        """Whether this is a partial listen (< 90% complete)."""
        progress = self.progress_percent
        if progress is None:
            return False  # Assume complete if unknown
        return progress < 90

    @property
    def duration_formatted(self) -> str:
        """Duration as 'Xh Ym' or 'Xm' format."""
        if self.duration_seconds <= 0:
            return "?"
        total_mins = int(self.duration_seconds / 60)
        hours = total_mins // 60
        mins = total_mins % 60
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{mins}m"

    @property
    def status_label(self) -> str:
        """Status label for display."""
        progress = self.progress_percent
        if progress is None:
            return "?"
        if progress >= 90:
            return "✓"
        return f"{progress}%"


def core_data_to_datetime(ts: Optional[float]) -> Optional[datetime]:
    """Convert Core Data timestamp to Python datetime."""
    if ts is None or ts <= 0:
        return None
    unix_ts = ts + CORE_DATA_EPOCH_OFFSET
    return datetime.fromtimestamp(unix_ts)


def get_episodes_since(
    since_date: datetime = datetime(2025, 1, 1),
    db_path: Path = DB_PATH
) -> list[Episode]:
    """
    Fetch all episodes played since the given date.

    Args:
        since_date: Earliest date to include (default: Jan 1, 2025)
        db_path: Path to Apple Podcasts database

    Returns:
        List of Episode objects, sorted by date played (most recent first)
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Apple Podcasts database not found at {db_path}")

    # Convert since_date to Core Data timestamp
    since_ts = since_date.timestamp() - CORE_DATA_EPOCH_OFFSET

    query = """
    SELECT
        e.Z_PK as id,
        e.ZTITLE as episode_title,
        p.ZTITLE as podcast_name,
        p.ZAUTHOR as podcast_author,
        COALESCE(e.ZDURATION, 0) as duration,
        COALESCE(e.ZPLAYHEAD, 0) as playhead,
        e.ZLASTDATEPLAYED as date_played,
        e.ZPUBDATE as date_published,
        p.ZFEEDURL as feed_url,
        e.ZGUID as guid,
        e.ZITEMDESCRIPTIONWITHOUTHTML as description
    FROM ZMTEPISODE e
    JOIN ZMTPODCAST p ON e.ZPODCAST = p.Z_PK
    WHERE e.ZLASTDATEPLAYED IS NOT NULL
      AND e.ZLASTDATEPLAYED >= ?
    ORDER BY e.ZLASTDATEPLAYED DESC
    """

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    episodes = []
    for row in cursor.execute(query, (since_ts,)):
        episode = Episode(
            id=row['id'],
            title=row['episode_title'] or "Untitled",
            podcast_name=row['podcast_name'] or "Unknown Podcast",
            podcast_author=row['podcast_author'] or "",
            duration_seconds=row['duration'] or 0,
            playhead_seconds=row['playhead'] or 0,
            date_played=core_data_to_datetime(row['date_played']),
            date_published=core_data_to_datetime(row['date_published']),
            feed_url=row['feed_url'],
            guid=row['guid'],
            description=row['description'],
        )
        episodes.append(episode)

    conn.close()
    return episodes


def get_episode_count_by_podcast(
    since_date: datetime = datetime(2025, 1, 1),
    db_path: Path = DB_PATH
) -> dict[str, int]:
    """Get count of episodes played per podcast since the given date."""
    if not db_path.exists():
        raise FileNotFoundError(f"Apple Podcasts database not found at {db_path}")

    since_ts = since_date.timestamp() - CORE_DATA_EPOCH_OFFSET

    query = """
    SELECT p.ZTITLE as podcast_name, COUNT(*) as count
    FROM ZMTEPISODE e
    JOIN ZMTPODCAST p ON e.ZPODCAST = p.Z_PK
    WHERE e.ZLASTDATEPLAYED IS NOT NULL
      AND e.ZLASTDATEPLAYED >= ?
    GROUP BY p.ZTITLE
    ORDER BY count DESC
    """

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    result = {row[0]: row[1] for row in cursor.execute(query, (since_ts,))}

    conn.close()
    return result


if __name__ == "__main__":
    # Quick test
    print(f"Database path: {DB_PATH}")
    print(f"Database exists: {DB_PATH.exists()}")

    if DB_PATH.exists():
        episodes = get_episodes_since()
        print(f"\nFound {len(episodes)} episodes since Jan 1, 2025\n")

        print("Most recent 10 episodes:")
        print("-" * 100)
        for ep in episodes[:10]:
            partial = " (partial)" if ep.is_partial else ""
            print(f"{ep.date_played.strftime('%Y-%m-%d')} | {ep.podcast_name[:30]:<30} | {ep.title[:40]:<40} | {ep.duration_formatted:>6} | {ep.status_label}{partial}")
