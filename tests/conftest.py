"""Shared fixtures.

``QT_QPA_PLATFORM`` is set before anything can import Qt. Without it a test that
touches a widget tries to open a real window, which fails on a machine with no
session attached and succeeds distractingly on one that has.

**Note the trap it brings with it, recorded rather than discovered twice:** the
offscreen platform has no fonts on this machine, so every string renders as
tofu and font metrics do not match the real Windows plugin. Nothing here may
assert on a rendered pixel size or a text width - those assertions pass or fail
for reasons that have nothing to do with the program.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from icc import build_profile  # noqa: E402

# Registers the HEIF opener as a side effect, which every fixture writing a
# .heic depends on.
from imgconv.imaging import backend  # noqa: E402,F401
from imgconv.imaging.metadata import (  # noqa: E402
    DATE_TIME_ORIGINAL_TAG,
    EXIF_IFD_TAG,
    ORIENTATION_TAG,
)

SAMPLE_DATE = "2026:03:23 10:53:30"


def _quadrant_image(width: int = 40, height: int = 24) -> Image.Image:
    """An image whose four quadrants differ, so a rotation is detectable.

    A flat colour would survive being rotated, mirrored or replaced by a blank
    of the same size without any assertion noticing.
    """
    image = Image.new("RGB", (width, height), (20, 20, 20))
    colours = ((220, 40, 30), (30, 200, 90), (40, 70, 220), (230, 210, 40))
    half_w, half_h = width // 2, height // 2
    for index, (x0, y0) in enumerate(
        ((0, 0), (half_w, 0), (0, half_h), (half_w, half_h))
    ):
        for x in range(x0, x0 + half_w):
            for y in range(y0, y0 + half_h):
                image.putpixel((x, y), colours[index])
    return image


@pytest.fixture
def quadrants() -> Image.Image:
    return _quadrant_image()


@pytest.fixture
def wide_gamut_profile() -> bytes:
    """A valid ICC profile that is emphatically not sRGB. See ``tests/icc.py``."""
    return build_profile()


@pytest.fixture
def make_image(tmp_path: Path):
    """Write a test image of a given format, with optional EXIF and ICC.

    Returns the path. Every format goes through Pillow's own writer, so the
    fixtures are real files of the type they claim - which is the whole point,
    given that the code under test identifies files by their contents.
    """

    def _make(
        name: str,
        image_format: str = "JPEG",
        image: Image.Image | None = None,
        orientation: int | None = None,
        date: str | None = None,
        icc_profile: bytes | None = None,
        **save_arguments,
    ) -> Path:
        source = image if image is not None else _quadrant_image()
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)

        if orientation is not None or date is not None:
            exif = source.getexif()
            if orientation is not None:
                exif[ORIENTATION_TAG] = orientation
            if date is not None:
                exif.get_ifd(EXIF_IFD_TAG)[DATE_TIME_ORIGINAL_TAG] = date
            save_arguments["exif"] = exif.tobytes()

        if icc_profile is not None:
            save_arguments["icc_profile"] = icc_profile

        source.save(path, format=image_format, **save_arguments)
        return path

    return _make


@pytest.fixture
def real_photo() -> Path:
    """A genuine iPhone HEIC, if one is on this machine. Skips if not.

    Deliberately not committed: the owner's photographs carry GPS coordinates,
    and the suite must not publish them. Everything load-bearing is proven
    against generated fixtures; this exists so that the real article gets
    exercised too when it happens to be available.
    """
    candidate = Path.home() / "Downloads" / "IMG_2480.HEIC"
    if not candidate.is_file():
        pytest.skip("no real iPhone photo on this machine")
    return candidate


@pytest.fixture(scope="session")
def qt_application():
    """One QApplication for the whole session; Qt permits no more."""
    from imgconv.gui.app import build_application

    return build_application([])
