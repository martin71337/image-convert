"""Proving a frozen bundle actually works, from inside the frozen bundle.

**The failure this exists to catch.** PyInstaller analyses imports statically.
``pillow_heif`` is a compiled extension that loads libheif's DLLs at runtime, and
a bundle can build perfectly, start perfectly, show its window perfectly, and
then fail the instant a user opens their first HEIC - because the decoder was
never collected. No unit test run against the source tree can catch that; the
source tree has a working decoder. Only running the real converter inside the
real bundle can.

So ``tools/build_exe.py`` runs ``ImageConvert.exe --selftest`` as a build gate,
and refuses to publish an executable that cannot convert an image.

**The fixture is synthetic.** It is drawn here, encoded to HEIC in memory, and
converted - rather than shipping one of the owner's photographs, which would
publish its GPS coordinates along with the program.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

LAZY_IMPORTS = (
    "imgconv.imaging.backend",
    "imgconv.imaging.color",
    "imgconv.imaging.metadata",
    "pillow_heif",
    "PIL.Image",
    "PIL.ImageCms",
    "PIL.ImageOps",
)
"""Modules reached only from inside a function body.

PyInstaller does follow imports inside functions, but every one of these is
behind a deferred import, so a change in its analyser would drop them silently.
``imageconvert.spec`` declares this same tuple as ``hiddenimports``, and the
check below proves the bundle can actually import each one - the declaration and
the proof are the same list.
"""

SAMPLE_SIZE = (64, 48)
SAMPLE_DATE = "2026:03:23 10:53:30"


def _check_imports() -> list[str]:
    import importlib

    problems = []
    for name in LAZY_IMPORTS:
        try:
            importlib.import_module(name)
        except Exception as error:
            problems.append(f"cannot import {name}: {type(error).__name__}: {error}")
    return problems


def _build_sample(path: Path) -> None:
    """Write a small HEIC carrying a known colour and a known capture date."""
    from PIL import Image

    from imgconv.imaging import backend  # registers the HEIF opener
    from imgconv.imaging.metadata import DATE_TIME_ORIGINAL_TAG, EXIF_IFD_TAG

    assert backend is not None  # the import is the point

    image = Image.new("RGB", SAMPLE_SIZE, (18, 140, 96))
    # A second block, so a conversion that returned a blank image of the right
    # size would still be caught.
    for x in range(SAMPLE_SIZE[0] // 2):
        for y in range(SAMPLE_SIZE[1] // 2):
            image.putpixel((x, y), (240, 150, 30))

    exif = image.getexif()
    exif.get_ifd(EXIF_IFD_TAG)[DATE_TIME_ORIGINAL_TAG] = SAMPLE_DATE
    image.save(path, format="HEIF", exif=exif.tobytes())


def run(verbose: bool = True) -> int:
    """Run every check. Returns 0 when all of them pass, 1 otherwise."""
    failures: list[str] = []

    def say(message: str) -> None:
        if verbose:
            print(message)

    from imgconv import APP_NAME, __version__

    say(f"{APP_NAME} {__version__} self-test")
    say(f"  frozen: {getattr(sys, 'frozen', False)}")

    failures.extend(_check_imports())
    say(f"  imports: {len(LAZY_IMPORTS) - len(failures)}/{len(LAZY_IMPORTS)} ok")

    if failures:
        for problem in failures:
            print(f"  FAIL {problem}")
        print("SELF-TEST FAILED")
        return 1

    from PIL import Image

    from imgconv import formats
    from imgconv.convert import convert_one
    from imgconv.imaging.backend import decoder_versions
    from imgconv.imaging.metadata import date_taken
    from imgconv.options import ConversionOptions, OutputLocation
    from imgconv.result import Outcome

    for name, version in decoder_versions().items():
        say(f"  {name}: {version}")

    with tempfile.TemporaryDirectory() as workspace:
        folder = Path(workspace)
        sample = folder / "selftest.heic"

        try:
            _build_sample(sample)
        except Exception as error:
            print(f"  FAIL could not encode a HEIC sample: {type(error).__name__}: {error}")
            print("SELF-TEST FAILED")
            return 1

        # The sniffer must recognise what the encoder just wrote. If this fails,
        # the two disagree about what a HEIC is.
        sniffed = formats.sniff(sample)
        if sniffed is not formats.HEIC:
            failures.append(f"a written HEIC sniffs as {sniffed}, not HEIC")

        output = folder / "out"
        result = convert_one(
            sample,
            ConversionOptions(
                target_format=formats.JPEG,
                output_location=OutputLocation.CHOSEN,
                output_folder=output,
            ),
        )

        if result.outcome is not Outcome.CONVERTED:
            failures.append(f"conversion did not succeed: {result.reason}")
        elif result.target is None or not result.target.is_file():
            failures.append("conversion reported success but wrote no file")
        else:
            converted = Image.open(result.target)
            converted.load()

            if converted.size != SAMPLE_SIZE:
                failures.append(f"converted image is {converted.size}, expected {SAMPLE_SIZE}")

            # The two blocks must still be distinguishable and roughly the right
            # colours - proof that real pixels came through the decoder, not a
            # blank of the right dimensions.
            corner = converted.getpixel((4, 4))
            far = converted.getpixel((SAMPLE_SIZE[0] - 4, SAMPLE_SIZE[1] - 4))
            if not (corner[0] > corner[2] + 40):
                failures.append(f"top-left block is {corner}, expected a warm orange")
            if not (far[1] > far[0] + 40):
                failures.append(f"bottom-right block is {far}, expected a green")

            if date_taken(converted) != SAMPLE_DATE:
                failures.append(
                    f"capture date is {date_taken(converted)!r}, expected {SAMPLE_DATE!r}"
                )

            if converted.getexif().get(0x0112) != 1:
                failures.append("converted image does not declare orientation 1")

    if failures:
        for problem in failures:
            print(f"  FAIL {problem}")
        print("SELF-TEST FAILED")
        return 1

    say("  HEIC -> JPEG conversion, pixels, capture date and orientation: ok")
    print("SELF-TEST PASSED")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
