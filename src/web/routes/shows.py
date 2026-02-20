"""
Shows routes - manage followed podcasts.
"""

from flask import Blueprint, render_template, jsonify, request

bp = Blueprint('shows', __name__)


@bp.route('/shows')
def index():
    """Shows management page."""
    return render_template('shows.html')


@bp.route('/api/shows')
def list_shows():
    """
    List all shows from Apple Podcasts listening history.
    Returns shows with episode counts.
    """
    try:
        from ...podcast_db import get_episodes_since
        from datetime import datetime

        episodes = get_episodes_since(since_date=datetime(2025, 1, 1))

        # Aggregate by show
        shows = {}
        for ep in episodes:
            name = ep.podcast_name
            if name not in shows:
                shows[name] = {
                    'podcast_name': name,
                    'feed_url': ep.feed_url,
                    'episode_count': 0
                }
            shows[name]['episode_count'] += 1

        # Sort by episode count
        result = sorted(shows.values(), key=lambda x: x['episode_count'], reverse=True)
        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/shows/followed', methods=['GET'])
def list_followed():
    """List all followed shows."""
    try:
        from ..models.follows_db import get_followed_shows
        shows = get_followed_shows()
        return jsonify([s.to_dict() for s in shows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/shows/followed', methods=['POST'])
def follow_show():
    """Follow a new show."""
    try:
        from ..models.follows_db import add_followed_show

        data = request.get_json()
        podcast_name = data.get('podcast_name')
        feed_url = data.get('feed_url')

        if not podcast_name:
            return jsonify({'error': 'podcast_name required'}), 400

        show = add_followed_show(podcast_name, feed_url)
        return jsonify(show.to_dict())

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/shows/followed/<int:show_id>', methods=['DELETE'])
def unfollow_show(show_id):
    """Unfollow a show and remove its RSS episodes."""
    try:
        from ..models.follows_db import remove_followed_show
        remove_followed_show(show_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/shows/<int:show_id>/fetch-rss', methods=['POST'])
def fetch_rss(show_id):
    """Fetch new episodes from a show's RSS feed."""
    try:
        from ..services.rss_fetcher import fetch_episodes_for_show
        result = fetch_episodes_for_show(show_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/shows/sync-all', methods=['POST'])
def sync_all_feeds():
    """Sync all followed shows' RSS feeds."""
    try:
        from ..services.rss_fetcher import sync_all_feeds
        result = sync_all_feeds()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
