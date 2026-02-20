"""
Background job manager for episode processing.

Handles running processing jobs in background threads with progress reporting.
"""

import queue
import threading
from typing import Optional


def start_processing_job(
    job_id: str,
    episode_ids: list[str],
    force: bool,
    retry_no_transcript: bool,
    progress_queue: queue.Queue
) -> threading.Thread:
    """
    Start a background processing job.

    Args:
        job_id: Unique job identifier
        episode_ids: List of episode IDs to process
        force: Force reprocessing of already-processed episodes
        retry_no_transcript: Retry episodes marked as no transcript
        progress_queue: Queue for sending progress updates

    Returns:
        The background thread
    """
    thread = threading.Thread(
        target=_run_processing,
        args=(job_id, episode_ids, force, retry_no_transcript, progress_queue),
        daemon=True
    )
    thread.start()
    return thread


def _run_processing(
    job_id: str,
    episode_ids: list[str],
    force: bool,
    retry_no_transcript: bool,
    progress_queue: queue.Queue
):
    """Run the processing job."""
    try:
        from ..models.unified import get_unified_episodes
        from ...pipeline import run_pipeline_with_progress
        from ...podcast_db import get_episodes_since

        # Send start event
        progress_queue.put({
            'type': 'start',
            'total': len(episode_ids)
        })

        # Get unified episodes
        unified = get_unified_episodes(episode_ids=episode_ids)

        # Map unified episodes back to Apple Podcast Episode objects for pipeline
        apple_episodes = get_episodes_since()
        apple_map = {str(ep.id): ep for ep in apple_episodes}

        episodes_to_process = []
        for ue in unified:
            if ue.source == 'apple' and ue.id in apple_map:
                episodes_to_process.append(apple_map[ue.id])
            # TODO: Handle RSS episodes

        if not episodes_to_process:
            progress_queue.put({
                'type': 'complete',
                'results': []
            })
            return

        # Create progress callback
        def on_progress(event):
            progress_queue.put(event)

        # Run pipeline with progress callback
        results = run_pipeline_with_progress(
            episodes=episodes_to_process,
            force=force,
            retry_no_transcript=retry_no_transcript,
            progress_callback=on_progress
        )

        # Send completion event
        progress_queue.put({
            'type': 'complete',
            'results': [
                {
                    'episode_id': str(r.episode.id),
                    'title': r.episode.title,
                    'status': r.status,
                    'output_file': str(r.output_file) if r.output_file else None,
                    'error': r.error_message
                }
                for r in results
            ]
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        progress_queue.put({
            'type': 'error',
            'message': str(e)
        })
        progress_queue.put({
            'type': 'complete',
            'results': []
        })
