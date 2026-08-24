"""Starting the interface.

Kept separate from the window so that ``launch.py``, the self-test and any test
that wants a window can each take what they need without one of them starting an
event loop as a side effect of an import.
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from imgconv import APP_NAME, APP_PUBLISHER, __version__
from imgconv.gui.icon import icon_path


def build_application(argv: list[str] | None = None) -> QApplication:
    """A configured ``QApplication``, or the one already running.

    Reuses an existing instance because Qt permits only one per process, and a
    test that builds a window twice must not be the thing that crashes.
    """
    existing = QApplication.instance()
    if existing is not None:
        return existing  # type: ignore[return-value]

    application = QApplication(argv if argv is not None else sys.argv)
    application.setApplicationName(APP_NAME)
    application.setApplicationDisplayName(APP_NAME)
    application.setApplicationVersion(__version__)
    application.setOrganizationName(APP_PUBLISHER)

    found = icon_path()
    if found is not None:
        application.setWindowIcon(QIcon(str(found)))

    return application


def run(argv: list[str] | None = None) -> int:
    """Show the window and run until it closes. Returns the process exit code."""
    application = build_application(argv)

    # Imported here so that building a QApplication does not require the whole
    # widget stack, which matters to the self-test.
    from imgconv.gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return application.exec()
