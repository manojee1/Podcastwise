"""
Episodes routes - browse and filter episodes.
"""

from flask import Blueprint, render_template, jsonify, request

bp = Blueprint('episodes', __name__)


@bp.route('/episodes')
def index():
    """Episodes browser page."""
    return render_template('episodes.html')


@bp.route('/api/episodes')
def list_episodes():
    """
    List episodes with filtering.

    Query params:
    - show: Filter by podcast name
    - status: 'new', 'processed', 'no_transcript'
    - source: 'apple', 'rss'
    - limit: Number of episodes to return
    - ids: Comma-separated list of episode IDs to fetch
    """
    try:
        from ..models.unified import get_unified_episodes

        # Parse filters
        show = request.args.get('show')
        status = request.args.get('status')
        source = request.args.get('source')
        limit = request.args.get('limit', type=int)
        episode_ids = request.args.get('ids')

        if episode_ids:
            # Fetch specific episodes by ID
            ids = [id.strip() for id in episode_ids.split(',')]
            episodes = get_unified_episodes(episode_ids=ids)
        else:
            episodes = get_unified_episodes(
                show=show,
                status=status,
                source=source,
                limit=limit
            )

        return jsonify([ep.to_dict() for ep in episodes])

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/episodes/<episode_id>/summary')
def get_summary(episode_id):
    """Get the cached summary for an episode."""
    try:
        from ...sheets import load_cached_summary

        # Handle both int and string IDs
        try:
            ep_id = int(episode_id)
        except ValueError:
            ep_id = episode_id

        summary = load_cached_summary(ep_id)
        if not summary:
            return jsonify({'error': 'Summary not found'}), 404

        return jsonify(summary.to_dict())

    except Exception as e:
        return jsonify({'error': str(e)}), 500
