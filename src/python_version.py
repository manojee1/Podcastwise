"""
Ensure Podcastwise runs on a supported Python.

macOS's built-in /usr/bin/python3 is 3.9, which yt-dlp and Google's auth
libraries have deprecated (they print warnings on every run). If an entry point
is started with an older Python and the project's .venv exists, re-launch the
same command under .venv/bin/python so plain `python3 -m src.cli ...` just works.

Stdlib only and Python 3.9-compatible: this runs *before* third-party imports.
"""

import os
import sys
from pathlib import Path
from typing import Optional

MIN_VERSION = (3, 10)
VENV_PYTHON = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python"


def ensure_supported_python(module: Optional[str] = None) -> None:
    """
    Re-exec under the project venv if the current Python is too old.

    Args:
        module: Module name when started with `python -m <module>` (e.g. "src.cli").
                None when started as a script (`python path/to/script.py`).
    """
    if sys.version_info >= MIN_VERSION:
        return

    if not VENV_PYTHON.exists():
        sys.stderr.write(
            f"Warning: running on Python {sys.version_info.major}.{sys.version_info.minor}; "
            f"Podcastwise needs {MIN_VERSION[0]}.{MIN_VERSION[1]}+.\n"
            "Set up the project venv (see README):\n"
            "  python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt\n\n"
        )
        return

    if module:
        args = [str(VENV_PYTHON), "-m", module, *sys.argv[1:]]
    else:
        args = [str(VENV_PYTHON), *sys.argv]
    os.execv(str(VENV_PYTHON), args)
