"""
SQLite database for followed shows and RSS episodes.

Database location: ~/Documents/PodcastNotes/.state/podcastwise.db
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


# Database location
DB_DIR = Path.home() / "Documents/PodcastNotes/.state"
DB_PATH = DB_DIR / "podcastwise.db"


def get_connection() -> sqlite3.Connection:
    """Get a database connection, creating the database if needed."""
    DB_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Initialize schema if needed
    _init_schema(conn)

    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS followed_shows (
            id INTEGER PRIMARY KEY,
            podcast_name TEXT NOT NULL UNIQUE,
            feed_url TEXT,
            last_rss_fetch TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS rss_episodes (
            id TEXT PRIMARY KEY,
            show_id INTEGER REFERENCES followed_shows(id) ON DELETE CASCADE,
            guid TEXT NOT NULL,
            title TEXT,
            description TEXT,
            duration_seconds INTEGER,
            date_published TIMESTAMP,
            audio_url TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_rss_episodes_show ON rss_episodes(show_id);
    """)
    conn.commit()


@dataclass
class FollowedShow:
    """A followed podcast show."""
    id: int
    podcast_name: str
    feed_url: Optional[str]
    last_rss_fetch: Optional[datetime]
    rss_episode_count: int = 0

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'podcast_name': self.podcast_name,
            'feed_url': self.feed_url,
            'last_rss_fetch': self.last_rss_fetch.isoformat() if self.last_rss_fetch else None,
            'rss_episode_count': self.rss_episode_count
        }


@dataclass
class RSSEpisode:
    """An episode fetched from RSS feed."""
    id: str  # Format: "rss_{hash}"
    show_id: int
    guid: str
    title: str
    description: Optional[str]
    duration_seconds: Optional[int]
    date_published: Optional[datetime]
    audio_url: Optional[str]

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'show_id': self.show_id,
            'guid': self.guid,
            'title': self.title,
            'description': self.description,
            'duration_seconds': self.duration_seconds,
            'date_published': self.date_published.isoformat() if self.date_published else None,
            'audio_url': self.audio_url
        }


def get_followed_shows() -> list[FollowedShow]:
    """Get all followed shows with RSS episode counts."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            fs.id, fs.podcast_name, fs.feed_url, fs.last_rss_fetch,
            COUNT(re.id) as rss_count
        FROM followed_shows fs
        LEFT JOIN rss_episodes re ON re.show_id = fs.id
        GROUP BY fs.id
        ORDER BY fs.podcast_name
    """)

    shows = []
    for row in cursor.fetchall():
        last_fetch = None
        if row['last_rss_fetch']:
            try:
                last_fetch = datetime.fromisoformat(row['last_rss_fetch'])
            except (ValueError, TypeError):
                pass

        shows.append(FollowedShow(
            id=row['id'],
            podcast_name=row['podcast_name'],
            feed_url=row['feed_url'],
            last_rss_fetch=last_fetch,
            rss_episode_count=row['rss_count']
        ))

    conn.close()
    return shows


def get_followed_show(show_id: int) -> Optional[FollowedShow]:
    """Get a specific followed show by ID."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, podcast_name, feed_url, last_rss_fetch
        FROM followed_shows WHERE id = ?
    """, (show_id,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    last_fetch = None
    if row['last_rss_fetch']:
        try:
            last_fetch = datetime.fromisoformat(row['last_rss_fetch'])
        except (ValueError, TypeError):
            pass

    return FollowedShow(
        id=row['id'],
        podcast_name=row['podcast_name'],
        feed_url=row['feed_url'],
        last_rss_fetch=last_fetch
    )


def add_followed_show(podcast_name: str, feed_url: Optional[str] = None) -> FollowedShow:
    """Add a show to followed list."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO followed_shows (podcast_name, feed_url)
        VALUES (?, ?)
    """, (podcast_name, feed_url))
    conn.commit()

    # Get the show (whether just inserted or already existed)
    cursor.execute("""
        SELECT id, podcast_name, feed_url, last_rss_fetch
        FROM followed_shows WHERE podcast_name = ?
    """, (podcast_name,))

    row = cursor.fetchone()
    conn.close()

    return FollowedShow(
        id=row['id'],
        podcast_name=row['podcast_name'],
        feed_url=row['feed_url'],
        last_rss_fetch=None
    )


def remove_followed_show(show_id: int) -> None:
    """Remove a show from followed list (also removes its RSS episodes)."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM followed_shows WHERE id = ?", (show_id,))
    conn.commit()
    conn.close()


def update_feed_url(show_id: int, feed_url: str) -> None:
    """Update the feed URL for a followed show."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE followed_shows SET feed_url = ? WHERE id = ?
    """, (feed_url, show_id))
    conn.commit()
    conn.close()


def update_last_fetch(show_id: int) -> None:
    """Update the last RSS fetch timestamp."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE followed_shows SET last_rss_fetch = ? WHERE id = ?
    """, (datetime.now().isoformat(), show_id))
    conn.commit()
    conn.close()


def add_rss_episode(episode: RSSEpisode) -> None:
    """Add an RSS episode to the database."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO rss_episodes
        (id, show_id, guid, title, description, duration_seconds, date_published, audio_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        episode.id,
        episode.show_id,
        episode.guid,
        episode.title,
        episode.description,
        episode.duration_seconds,
        episode.date_published.isoformat() if episode.date_published else None,
        episode.audio_url
    ))
    conn.commit()
    conn.close()


def get_rss_episodes(show_id: Optional[int] = None) -> list[RSSEpisode]:
    """Get RSS episodes, optionally filtered by show."""
    conn = get_connection()
    cursor = conn.cursor()

    if show_id:
        cursor.execute("""
            SELECT * FROM rss_episodes WHERE show_id = ?
            ORDER BY date_published DESC
        """, (show_id,))
    else:
        cursor.execute("""
            SELECT * FROM rss_episodes ORDER BY date_published DESC
        """)

    episodes = []
    for row in cursor.fetchall():
        date_pub = None
        if row['date_published']:
            try:
                date_pub = datetime.fromisoformat(row['date_published'])
            except (ValueError, TypeError):
                pass

        episodes.append(RSSEpisode(
            id=row['id'],
            show_id=row['show_id'],
            guid=row['guid'],
            title=row['title'],
            description=row['description'],
            duration_seconds=row['duration_seconds'],
            date_published=date_pub,
            audio_url=row['audio_url']
        ))

    conn.close()
    return episodes


def episode_exists(guid: str, show_id: int) -> bool:
    """Check if an RSS episode already exists."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 1 FROM rss_episodes WHERE guid = ? AND show_id = ?
    """, (guid, show_id))

    exists = cursor.fetchone() is not None
    conn.close()
    return exists
