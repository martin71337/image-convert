"""Start Image Convert.

A script, not ``python -m imgconv``: PyInstaller freezes a script and cannot
freeze a module invocation, and using the same file for both means the frozen
program and a source run start along identical paths rather than merely similar
ones.

    py launch.py              # the window
    py launch.py --selftest   # the build gate; prints PASS or FAIL, sets the code
    py launch.py --version
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)

    if "--version" in arguments:
        from imgconv import APP_NAME, __version__

        print(f"{APP_NAME} {__version__}")
        return 0

    if "--selftest" in arguments:
        from imgconv.selftest import run

        return run()

    from imgconv.gui.app import run as run_gui

    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
