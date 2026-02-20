"""
Processing routes - handle episode processing with SSE progress.
"""

import json
import uuid
import queue
import threading
from flask import Blueprint, render_template, jsonify, request, Response

bp = Blueprint('processing', __name__)

# Store active jobs
_jobs = {}


@bp.route('/processing')
def index():
    """Processing page."""
    return render_template('processing.html')


@bp.route('/api/process', methods=['POST'])
def start_processing():
    """
    Start processing selected episodes.

    Request body:
    {
        "episode_ids": ["id1", "id2", ...],
        "force": false,
        "retry_no_transcript": false
    }
    """
    try:
        from ..services.job_manager import start_processing_job

        data = request.get_json()
        episode_ids = data.get('episode_ids', [])
        force = data.get('force', False)
        retry_no_transcript = data.get('retry_no_transcript', False)

        if not episode_ids:
            return jsonify({'error': 'No episodes selected'}), 400

        # Create job
        job_id = str(uuid.uuid4())
        progress_queue = queue.Queue()

        # Start processing in background
        job = start_processing_job(
            job_id=job_id,
            episode_ids=episode_ids,
            force=force,
            retry_no_transcript=retry_no_transcript,
            progress_queue=progress_queue
        )

        _jobs[job_id] = {
            'job': job,
            'queue': progress_queue,
            'cancelled': False
        }

        return jsonify({'job_id': job_id})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/process/stream/<job_id>')
def stream_progress(job_id):
    """
    Server-Sent Events endpoint for processing progress.

    Yields events:
    - start: {type: "start", total: N}
    - episode_start: {type: "episode_start", episode_id, podcast_name, title}
    - progress: {type: "progress", step, percent, message}
    - episode_complete: {type: "episode_complete", episode_id, status, completed, total}
    - complete: {type: "complete", results: [...]}
    - error: {type: "error", message}
    """
    if job_id not in _jobs:
        return jsonify({'error': 'Job not found'}), 404

    def generate():
        job_info = _jobs[job_id]
        progress_queue = job_info['queue']

        while True:
            try:
                # Wait for next progress update
                event = progress_queue.get(timeout=30)

                if event is None:
                    # Job complete signal
                    break

                yield f"data: {json.dumps(event)}\n\n"

                if event.get('type') == 'complete':
                    break

            except queue.Empty:
                # Send keepalive
                yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


@bp.route('/api/process/<job_id>/cancel', methods=['POST'])
def cancel_processing(job_id):
    """Cancel a running processing job."""
    if job_id not in _jobs:
        return jsonify({'error': 'Job not found'}), 404

    _jobs[job_id]['cancelled'] = True
    return jsonify({'success': True})
