"""
State management for tracking processed episodes.

Keeps track of which episodes have been summarized to avoid re-processing.
"""

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


def get_state_dir() -> Path:
    """Get state directory, evaluated at runtime."""
    base = Path(os.getenv("PODCASTWISE_OUTPUT_DIR", "~/Documents/PodcastNotes")).expanduser()
    return base / ".state"


def get_state_file() -> Path:
    """Get state file path, evaluated at runtime."""
    return get_state_dir() / "processed.json"


@dataclass
class ProcessedEpisode:
    """Record of a processed episode."""
    episode_id: int
    podcast_name: str
    episode_title: str
    date_processed: str
    output_file: str
    video_id: Optional[str] = None
    status: str = "success"  # success, error, no_transcript
    exported_to_sheets: bool = False


class StateManager:
    """Manages state of processed episodes."""

    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = state_file if state_file is not None else get_state_file()
        self._state: dict[int, ProcessedEpisode] = {}
        self._load()

    def _load(self) -> None:
        """Load state from disk."""
        if self.state_file.exists():
            with open(self.state_file, 'r') as f:
                data = json.load(f)
                for ep_id, ep_data in data.items():
                    self._state[int(ep_id)] = ProcessedEpisode(**ep_data)

    def _save(self) -> None:
        """Save state to disk."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {str(ep_id): asdict(ep) for ep_id, ep in self._state.items()}
        with open(self.state_file, 'w') as f:
            json.dump(data, f, indent=2)

    def is_processed(self, episode_id: int) -> bool:
        """Check if an episode has been processed."""
        return episode_id in self._state

    def get_processed(self, episode_id: int) -> Optional[ProcessedEpisode]:
        """Get processing record for an episode."""
        return self._state.get(episode_id)

    def mark_processed(
        self,
        episode_id: int,
        podcast_name: str,
        episode_title: str,
        output_file: str,
        video_id: Optional[str] = None,
        status: str = "success",
    ) -> None:
        """Mark an episode as processed."""
        self._state[episode_id] = ProcessedEpisode(
            episode_id=episode_id,
            podcast_name=podcast_name,
            episode_title=episode_title,
            date_processed=datetime.now().isoformat(),
            output_file=output_file,
            video_id=video_id,
            status=status,
        )
        self._save()

    def mark_no_transcript(
        self,
        episode_id: int,
        podcast_name: str,
        episode_title: str,
    ) -> None:
        """Mark an episode as having no transcript available."""
        self._state[episode_id] = ProcessedEpisode(
            episode_id=episode_id,
            podcast_name=podcast_name,
            episode_title=episode_title,
            date_processed=datetime.now().isoformat(),
            output_file="",
            status="no_transcript",
        )
        self._save()

    def mark_error(
        self,
        episode_id: int,
        podcast_name: str,
        episode_title: str,
        error: str,
    ) -> None:
        """Mark an episode as having an error during processing."""
        self._state[episode_id] = ProcessedEpisode(
            episode_id=episode_id,
            podcast_name=podcast_name,
            episode_title=episode_title,
            date_processed=datetime.now().isoformat(),
            output_file=error,  # Store error message
            status="error",
        )
        self._save()

    def clear(self, episode_id: int) -> None:
        """Remove an episode from processed state (for re-processing)."""
        if episode_id in self._state:
            del self._state[episode_id]
            self._save()

    def clear_all(self) -> None:
        """Clear all processed state."""
        self._state = {}
        self._save()

    def mark_exported(self, episode_id: int) -> None:
        """Mark an episode as exported to Google Sheets."""
        if episode_id in self._state:
            self._state[episode_id].exported_to_sheets = True
            self._save()

    def mark_not_exported(self, episode_id: int) -> None:
        """Reset export flag so the episode will be re-exported on next export run."""
        if episode_id in self._state:
            self._state[episode_id].exported_to_sheets = False
            self._save()

    def is_exported(self, episode_id: int) -> bool:
        """Check if episode has been exported to Google Sheets."""
        if episode_id in self._state:
            return self._state[episode_id].exported_to_sheets
        return False

    def get_stats(self) -> dict:
        """Get processing statistics."""
        total = len(self._state)
        success = sum(1 for ep in self._state.values() if ep.status == "success")
        no_transcript = sum(1 for ep in self._state.values() if ep.status == "no_transcript")
        errors = sum(1 for ep in self._state.values() if ep.status == "error")
        return {
            "total": total,
            "success": success,
            "no_transcript": no_transcript,
            "errors": errors,
        }

    def list_processed(self) -> list[ProcessedEpisode]:
        """List all processed episodes."""
        return sorted(
            self._state.values(),
            key=lambda x: x.date_processed,
            reverse=True
        )


# Global state manager instance
_state_manager: Optional[StateManager] = None
_state_manager_path: Optional[Path] = None


def get_state_manager() -> StateManager:
    """Get the global state manager instance.

    Creates a new instance if the state file path has changed (e.g., due to
    PODCASTWISE_OUTPUT_DIR environment variable being set).
    """
    global _state_manager, _state_manager_path
    current_path = get_state_file()

    # Reset if path changed (environment variable was set after import)
    if _state_manager is not None and _state_manager_path != current_path:
        _state_manager = None

    if _state_manager is None:
        _state_manager = StateManager()
        _state_manager_path = current_path

    return _state_manager


def reset_state_manager() -> None:
    """Reset the global state manager (for testing or when env changes)."""
    global _state_manager, _state_manager_path
    _state_manager = None
    _state_manager_path = None
