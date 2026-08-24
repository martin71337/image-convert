# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for Image Convert.

Committed, not generated. ``pyinstaller`` will write a spec for you, but a
written one drifts from the program the moment anything moves, and this file
carries four decisions that ought to be reviewable rather than rediscovered.

Build it through the gated script, never by hand for a release::

    .venv\\Scripts\\python.exe tools/build_exe.py

**One file, not one folder.** The opposite of what a program shipping auditable
data files should do - but this one ships no data. The deliverable is a single
``ImageConvert.exe`` that can be copied to a USB stick, a network share or
another machine and double-clicked, with nothing to install and no Inno Setup in
the toolchain. The cost is real and worth stating: a one-file build unpacks
itself to a temporary folder on every launch, so the first window takes a couple
of seconds to appear.

**libheif is collected explicitly.** ``pillow_heif`` is a compiled extension that
loads libheif's DLLs at runtime. PyInstaller's static analysis sees the Python
module and can miss the binaries beside it, which produces a bundle that builds,
starts and shows its window perfectly, then fails the instant a user opens their
first HEIC - the only thing the program is for. ``collect_dynamic_libs`` and
``collect_submodules`` below are what prevent that, and ``--selftest`` is what
proves it.

**The version is read, never restated.** ``imgconv/__init__.py`` holds the only
version literal; this file imports it and builds the Windows version resource
from it, so the properties Explorer shows cannot disagree with the number the
build gate checked.

**The icon is derived here, from the drawing code.** ``tools/make_icon.py`` runs
as part of the build rather than a hand-made ``.ico`` being committed, so the
artwork has exactly one authoritative representation.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

REPO_ROOT = Path(SPECPATH).resolve()  # noqa: F821 - PyInstaller injects SPECPATH

# The spec runs in PyInstaller's interpreter, whose sys.path does not
# necessarily include the project.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from imgconv import APP_DESCRIPTION, APP_NAME, APP_PUBLISHER, __version__  # noqa: E402
from imgconv.gui.icon import BUNDLE_SUBDIRECTORY, ICON_FILENAME  # noqa: E402
from imgconv.selftest import LAZY_IMPORTS  # noqa: E402
from tools import make_icon  # noqa: E402

EXECUTABLE_NAME = "ImageConvert"

# Derived here so a bundle can never ship yesterday's artwork.
ICON_FILE = make_icon.generate()

# The destination is the program's own constant, not a string repeated here, so
# the bundle cannot put the icon somewhere the program does not look.
datas = [(str(ICON_FILE), BUNDLE_SUBDIRECTORY)]
assert ICON_FILE.name == ICON_FILENAME, "the icon builder and the finder disagree"

# ---------------------------------------------------------------------------
# Deferred imports and native libraries.
# ---------------------------------------------------------------------------

hiddenimports = list(LAZY_IMPORTS) + collect_submodules("pillow_heif")

binaries = collect_dynamic_libs("pillow_heif")

# ---------------------------------------------------------------------------
# Windows version resource, built from the one version literal.
# ---------------------------------------------------------------------------


def _version_tuple(text):
    """``"1.2.3"`` -> ``(1, 2, 3, 0)``. A Windows version is four integers.

    A pre-release marker (``0.1.0-dev``) is stripped for the numeric tuple,
    which has nowhere to put it; the full string still goes into the text
    fields, so a developer build says what it is. The release gate refuses to
    build while the marker is present, so a shipped executable never relies on
    this.
    """
    numbers = []
    for part in text.split("-")[0].split(".")[:4]:
        numbers.append(int(part) if part.isdigit() else 0)
    while len(numbers) < 4:
        numbers.append(0)
    return tuple(numbers)


from PyInstaller.utils.win32.versioninfo import (  # noqa: E402
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

_numeric = _version_tuple(__version__)

version_resource = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=_numeric,
        prodvers=_numeric,
        mask=0x3F,
        flags=0x0,
        OS=0x40004,  # VOS_NT_WINDOWS32
        fileType=0x1,  # VFT_APP
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",  # US English, Unicode
                    [
                        StringStruct("CompanyName", APP_PUBLISHER),
                        StringStruct("FileDescription", f"{APP_NAME} - {APP_DESCRIPTION}"),
                        StringStruct("FileVersion", __version__),
                        StringStruct("InternalName", EXECUTABLE_NAME),
                        StringStruct("OriginalFilename", f"{EXECUTABLE_NAME}.exe"),
                        StringStruct("ProductName", APP_NAME),
                        StringStruct("ProductVersion", __version__),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)


# ---------------------------------------------------------------------------
# The bundle. launch.py is a SCRIPT: PyInstaller cannot freeze `-m package`, and
# the same script is what a source run executes.
# ---------------------------------------------------------------------------

a = Analysis(  # noqa: F821
    [str(REPO_ROOT / "launch.py")],
    pathex=[str(REPO_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Qt modules this program does not use. Excluding them is safe here in a way
    # that excluding a dependency's lazy import is not: these are named Qt
    # libraries, nothing in imgconv imports them, and each is tens of megabytes.
    # The self-test is what proves the bundle is still complete.
    excludes=[
        "PySide6.QtNetwork",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtPdf",
        "PySide6.QtOpenGL",
        "PySide6.QtDBus",
        "tkinter",
        "numpy",
        "scipy",
        "matplotlib",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=EXECUTABLE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-packed executables trip antivirus heuristics; not worth it
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_FILE),
    version=version_resource,
)
