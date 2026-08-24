"""Build ``ImageConvert.exe``, refusing to publish one that does not work.

Run it from the project's own virtual environment::

    .venv\\Scripts\\python.exe tools/build_exe.py

**Gates, in order.** Each one refuses rather than warning, because a build that
skipped a gate is not a release:

1. The suite passes, in both normal and ``-O`` mode.
2. The version literal carries no pre-release marker.
3. The icon builds from its drawing code.
4. PyInstaller produces an executable.
5. **The built executable passes its own ``--selftest``.** This is the gate that
   matters: it runs the real converter inside the real bundle and proves libheif
   was actually collected. Nothing run against the source tree can prove that,
   because the source tree has a working decoder either way.
6. A SHA-256 is written beside the executable, so what was handed over can be
   checked against what was built.

``--skip-tests`` exists for iterating on packaging alone. It prints a warning and
is not a way to cut a release.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC = REPO_ROOT / "imageconvert.spec"
DIST = REPO_ROOT / "dist"
EXECUTABLE = DIST / "ImageConvert.exe"

SELFTEST_TIMEOUT = 300
"""Seconds. A one-file bundle unpacks itself before it runs, which on a cold
cache and an aggressive virus scanner is slow but not broken."""


class BuildRefused(Exception):
    """A gate said no."""


def announce(step: str, message: str) -> None:
    print(f"[{step}] {message}", flush=True)


def gate_tests(python: Path, skip: bool) -> None:
    if skip:
        print("!! tests skipped - this build is not a release", flush=True)
        return

    for label, arguments in (
        ("pytest", [str(python), "-m", "pytest", "-q"]),
        ("pytest -O", [str(python), "-O", "-m", "pytest", "-q"]),
    ):
        announce("1/6", f"running the suite ({label})")
        # Run unpiped and read the exit code directly: a suite whose output is
        # captured and whose status is inferred from its text is a suite that
        # can pass by accident.
        finished = subprocess.run(arguments, cwd=REPO_ROOT)
        if finished.returncode != 0:
            raise BuildRefused(f"the suite failed under {label}.")


def gate_version() -> str:
    announce("2/6", "checking the version literal")
    sys.path.insert(0, str(REPO_ROOT))
    from imgconv import __version__

    if "-" in __version__ or "dev" in __version__:
        raise BuildRefused(
            f"the version literal is {__version__!r}, which carries a "
            f"pre-release marker. Set it to a release number before building."
        )
    print(f"       version {__version__}")
    return __version__


def gate_icon() -> Path:
    announce("3/6", "building the icon")
    from tools import make_icon

    icon = make_icon.generate()
    print(f"       {icon} ({icon.stat().st_size:,} bytes)")
    return icon


def gate_pyinstaller(python: Path) -> Path:
    announce("4/6", "running PyInstaller (this takes a minute)")

    # A stale dist or build directory is how an old executable gets shipped
    # under a new version number.
    for stale in (DIST, REPO_ROOT / "build" / "ImageConvert"):
        if stale.exists():
            shutil.rmtree(stale)

    started = time.time()
    finished = subprocess.run(
        [str(python), "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)],
        cwd=REPO_ROOT,
    )
    if finished.returncode != 0:
        raise BuildRefused("PyInstaller failed.")
    if not EXECUTABLE.is_file():
        raise BuildRefused(f"PyInstaller reported success but {EXECUTABLE} is not there.")

    size = EXECUTABLE.stat().st_size
    print(f"       {EXECUTABLE} ({size / 1_048_576:.1f} MB, {time.time() - started:.0f}s)")
    return EXECUTABLE


def gate_selftest() -> None:
    """Run the built executable's own self-test. The load-bearing gate."""
    announce("5/6", "running the built executable's self-test")
    try:
        finished = subprocess.run(
            [str(EXECUTABLE), "--selftest"],
            capture_output=True,
            text=True,
            timeout=SELFTEST_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise BuildRefused(
            f"the built executable did not finish its self-test within "
            f"{SELFTEST_TIMEOUT} seconds."
        ) from None

    for line in (finished.stdout or "").splitlines():
        print(f"       {line}")
    if finished.returncode != 0:
        print(finished.stderr or "", file=sys.stderr)
        raise BuildRefused(
            "the built executable failed its own self-test. It would have "
            "started, shown its window, and then failed on the first real image."
        )


def gate_checksum() -> Path:
    announce("6/6", "writing the checksum")
    digest = hashlib.sha256(EXECUTABLE.read_bytes()).hexdigest()
    checksum_file = EXECUTABLE.with_suffix(".exe.sha256")
    checksum_file.write_text(f"{digest} *{EXECUTABLE.name}\n", encoding="utf-8")
    print(f"       {digest}")
    return checksum_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="iterate on packaging only; the result is not a release",
    )
    arguments = parser.parse_args(argv)

    python = Path(sys.executable)
    print(f"Building with {python}\n")

    try:
        gate_tests(python, arguments.skip_tests)
        version = gate_version()
        gate_icon()
        gate_pyinstaller(python)
        gate_selftest()
        checksum = gate_checksum()
    except BuildRefused as refusal:
        print(f"\nBUILD REFUSED: {refusal}", file=sys.stderr)
        return 1

    print(
        f"\nBuilt Image Convert {version}\n"
        f"  {EXECUTABLE}\n"
        f"  {checksum}\n"
        f"\nCopy the .exe anywhere and double-click it. Nothing to install."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
