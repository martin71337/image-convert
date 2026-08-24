"""Finding the application icon, frozen or from source.

A frozen bundle carries the ``.ico`` as a data file under ``sys._MEIPASS``; a
source run reads it out of ``build/icon/``, where ``tools/make_icon.py`` puts it.
Both locations are searched, in that order, and a missing icon is not an error -
the program runs with Qt's default window icon rather than refusing to start over
its own decoration.
"""

from __future__ import annotations

import sys
from pathlib import Path

ICON_FILENAME = "imageconvert.ico"

BUNDLE_SUBDIRECTORY = "assets/icon"
"""Where ``imageconvert.spec`` places the icon inside the bundle. The spec and
this constant are pinned to each other by the suite, so a change to one without
the other fails a test rather than shipping a program with no icon."""


def icon_candidates() -> tuple[Path, ...]:
    """Every place the icon might be, most authoritative first."""
    candidates: list[Path] = []

    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.append(Path(bundle) / BUNDLE_SUBDIRECTORY / ICON_FILENAME)

    repo_root = Path(__file__).resolve().parent.parent.parent
    candidates.append(repo_root / "build" / "icon" / ICON_FILENAME)

    return tuple(candidates)


def icon_path() -> Path | None:
    """The first candidate that exists, or ``None``."""
    for candidate in icon_candidates():
        if candidate.is_file():
            return candidate
    return None
