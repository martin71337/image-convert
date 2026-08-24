"""Reading one image and writing another. The only Pillow call sites.

The conversion is deliberately one linear function rather than a class: open,
orient, colour-correct, adapt the pixel mode to what the target can hold, encode.
Each step is delegated to a module that owns it, and each may add a note the user
sees. The order is load-bearing and is commented at the point it matters.

**Writes are atomic.** Every output is encoded to a ``.partial`` file in the
destination folder and then renamed over the target with ``os.replace``, which is
atomic on Windows for a same-directory rename. A conversion interrupted by a
crash, a full disk or a pulled USB stick leaves the previous file or nothing at
all - never a half-written JPEG that opens as grey mush and looks like a
successful conversion in a folder listing.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

import pillow_heif
from PIL import Image, ImageFile

from imgconv.formats import ImageFormat
from imgconv.imaging import color, metadata
from imgconv.options import ConversionOptions
from imgconv.pathways import Pathway

# Teaches Pillow to open .heic. Import-time and idempotent: every entry point
# that reaches a pixel comes through this module, so there is exactly one place
# this can be forgotten, and it is not a place anybody edits casually.
#
# AVIF is deliberately NOT registered here. pillow-heif dropped
# `register_avif_opener` at 1.x because Pillow gained native AVIF support, so
# calling it raises AttributeError on the version this program pins. AVIF has no
# registered pathway either (see imgconv.pathways), so an AVIF file is sniffed,
# named correctly in the queue, and refused by name rather than half-supported.
pillow_heif.register_heif_opener()

MAX_PIXELS = 400_000_000
"""Refuse absurd images rather than exhausting memory. 400 megapixels is roughly
twenty times a current phone sensor and well above any survey scan; Pillow's own
decompression-bomb guard warns at a lower threshold and this is the hard stop."""

SUBSAMPLING_THRESHOLD = 90
"""At and above this quality, chroma subsampling is switched off (4:4:4).

Subsampling halves the colour resolution, which is invisible on a landscape and
very visible on the thing field photos are most often taken *of*: a painted
number, a gauge face, a label, a crack against concrete. At high quality the size
saved is not worth the smearing."""

FLATTEN_BACKGROUND = (255, 255, 255)
"""What transparency becomes when the target cannot hold alpha. White, because a
transparent PNG placed in a document or a report is being composited onto a white
page anyway, and black would invert the user's expectation."""

ENCODER_BUFFER_CEILING = 128 * 1024 * 1024
"""The largest JPEG encoder buffer this program will ask for.

See :func:`_ensure_encoder_buffer`. Beyond this the buffer costs more memory
than the quality is worth, and the encoder falls back to subsampled chroma.
"""

_maxblock_lock = threading.Lock()


BROKEN_STREAM = "broken data stream"
"""The text of the error Pillow raises when the encoder buffer is too small.
Matched on because Pillow reports it as a plain ``OSError`` with no distinct
class, and treating every OSError as a buffer problem would swallow real ones
like a full disk."""


def _grow_encoder_buffer(pixels: int) -> bool:
    """Enlarge Pillow's JPEG encoder buffer. False once the ceiling is reached.

    **The defect this exists to survive, found on the owner's own files.**
    When ``optimize`` or ``progressive`` is set, libjpeg needs a buffer holding
    the entire encoded image at once, and Pillow guesses that size at ONE BYTE
    PER PIXEL - two, above quality 95 (``JpegImagePlugin._save``). Those guesses
    are calibrated for chroma-subsampled output. At ``subsampling=0`` there is
    twice the chroma data, and an image that does not compress - a screenshot
    full of text, a scanned drawing - exceeds them. Pillow then raises
    ``OSError: broken data stream when writing image file`` and the file fails.

    Measured at 4:4:4 on incompressible data: **1.67 bytes per pixel at quality
    90, 2.05 at 95, 2.97 at 100** - so Pillow's guess is short at both tiers.
    One real file in 649 hit this in the owner's Downloads folder.

    **Grown on demand rather than pre-sized.** Sizing every save for the worst
    case would mean a 48 MB buffer for an ordinary 12-megapixel photograph that
    encodes to two, on every thread at once. Growing only when the encoder
    actually complains costs a re-encode in the rare case and nothing at all in
    the common one.

    ``ImageFile.MAXBLOCK`` is a module-level global and this program converts on
    several threads, so it is only ever RAISED, never lowered, and always under
    a lock. A larger buffer is safe for every caller; a smaller one silently
    breaks whichever thread needed the bigger size. That monotonicity is what
    makes mutating another library's global acceptable here.
    """
    with _maxblock_lock:
        current = ImageFile.MAXBLOCK
        if current >= ENCODER_BUFFER_CEILING:
            return False
        # Start from a size the image plausibly needs rather than creeping up
        # from 64 KB, then double on each subsequent attempt.
        wanted = max(current * 2, 3 * pixels + 65536)
        ImageFile.MAXBLOCK = min(wanted, ENCODER_BUFFER_CEILING)
        return True


@dataclass(frozen=True)
class EncodeResult:
    """What was written, and anything worth telling the user about it."""

    path: Path
    notes: tuple[str, ...] = ()


def open_image(path: Path) -> Image.Image:
    """Open ``path`` and read its pixels.

    ``load()`` is called here on purpose. Pillow decodes lazily, so without it a
    truncated or corrupt file opens without complaint and fails much later,
    during the save, where the error reads as a *writing* problem. Failing at the
    point of reading is what lets the result name the actual cause.

    A HEIC holding several images - a burst, or a Live Photo - yields its primary
    image, which is the one the phone shows and the one the user means.
    """
    image = Image.open(path)

    pixels = image.size[0] * image.size[1]
    if pixels > MAX_PIXELS:
        raise ValueError(
            f"the image is {image.size[0]} x {image.size[1]} "
            f"({pixels / 1_000_000:.0f} megapixels), beyond the "
            f"{MAX_PIXELS // 1_000_000} megapixel limit this program will decode."
        )

    image.load()
    return image


def adapt_mode(image: Image.Image, target: ImageFormat) -> tuple[Image.Image, tuple[str, ...]]:
    """Coerce the pixel mode into something ``target`` can actually store.

    Asks the format record what it supports rather than testing for "JPEG", so a
    seventh target format added to the registry gets correct behaviour here
    without this function being edited.
    """
    notes: list[str] = []

    if image.mode in ("RGBA", "LA", "PA", "P") and not target.supports_alpha:
        # Composite onto a flat background rather than dropping the alpha
        # channel: discarding it reveals whatever colour happens to sit in the
        # fully transparent pixels, which is usually black and occasionally
        # garbage.
        rgba = image.convert("RGBA")
        if rgba.getchannel("A").getextrema()[0] < 255:
            notes.append("Transparency was flattened onto a white background.")
        flattened = Image.new("RGB", rgba.size, FLATTEN_BACKGROUND)
        flattened.paste(rgba, mask=rgba.getchannel("A"))
        return flattened, tuple(notes)

    if target.supports_alpha:
        if image.mode in ("RGBA", "RGB", "L", "LA"):
            return image, ()
        return image.convert("RGBA" if "A" in image.mode else "RGB"), ()

    if image.mode != "RGB":
        # 16-bit greyscale, CMYK, palette: all real inputs, none storable in a
        # JPEG as they stand.
        if image.mode in ("I", "I;16", "I;16B", "F"):
            notes.append("High bit-depth pixels were reduced to 8 bits per channel.")
        if image.mode == "CMYK":
            notes.append("CMYK pixels were converted to RGB.")
        return image.convert("RGB"), tuple(notes)

    return image, ()


def _save_arguments(target: ImageFormat, options: ConversionOptions) -> dict[str, object]:
    """Encoder settings for one target format."""
    if target.key == "JPEG":
        return {
            "quality": options.quality,
            "subsampling": 0 if options.quality >= SUBSAMPLING_THRESHOLD else 2,
            "optimize": True,
            "progressive": True,
        }
    if target.key == "PNG":
        # 6 is Pillow's default and the point past which compression time grows
        # much faster than the file shrinks.
        return {"compress_level": 6}
    return {}


def _encode_resiliently(
    image: Image.Image,
    staged: Path,
    target: ImageFormat,
    arguments: dict[str, object],
    exif: bytes | None,
) -> tuple[str, ...]:
    """Encode, enlarging the buffer or giving up chroma rather than the file.

    Two degradations, in order of preference, both reported:

    1. Grow the encoder buffer and try again. Costs a re-encode, changes nothing
       about the output.
    2. Only if the buffer cannot grow any further: fall back to subsampled
       chroma, which does change the output and so is said out loud.

    Anything else - a full disk, a permission error - is re-raised untouched.
    Each attempt rewrites the staging file from the beginning, so a failed one
    leaves nothing behind.
    """
    pixels = image.size[0] * image.size[1]

    while True:
        try:
            _encode(image, staged, target, arguments, exif)
            return ()
        except OSError as error:
            if BROKEN_STREAM not in str(error).lower():
                raise
            if _grow_encoder_buffer(pixels):
                continue
            if arguments.get("subsampling") == 0:
                arguments["subsampling"] = 2
                _encode(image, staged, target, arguments, exif)
                return (
                    "This image needed more colour data than the encoder can "
                    "buffer, so standard chroma subsampling was used.",
                )
            raise


def convert_image(
    source: Path,
    destination: Path,
    pathway: Pathway,
    options: ConversionOptions,
) -> EncodeResult:
    """Read ``source``, convert it along ``pathway``, write ``destination``.

    The destination folder is created if it does not exist. The caller has
    already decided the path, checked for collisions and confirmed the pathway
    exists; this function does the work and reports what it had to compromise on.
    """
    notes: list[str] = []
    target = pathway.target

    with open_image(source) as opened:
        # Orientation first. Everything downstream - the colour transform, the
        # flattening, the encoder - works on the pixels as they will actually be
        # seen, and the EXIF block is built from an image that is already upright.
        prepared = metadata.prepare(
            opened,
            keep_metadata=options.keep_metadata,
            auto_rotate=options.auto_rotate,
        )
        notes.extend(prepared.notes)

        # Colour before mode adaptation: the transform needs the real channels,
        # and flattening transparency onto white in the wrong colour space would
        # bake in a background that is subtly the wrong white.
        coloured = color.to_srgb(prepared.image, enabled=options.convert_to_srgb)
        notes.extend(coloured.notes)

        adapted, mode_notes = adapt_mode(coloured.image, target)
        notes.extend(mode_notes)

        arguments = _save_arguments(target, options)
        if coloured.icc_profile:
            arguments["icc_profile"] = coloured.icc_profile

        destination.parent.mkdir(parents=True, exist_ok=True)
        staged = destination.with_name(destination.name + ".partial")

        try:
            exif = prepared.exif if target.supports_exif else None
            try:
                notes.extend(_encode_resiliently(adapted, staged, target, arguments, exif))
            except ValueError as error:
                # Almost certainly the JPEG APP1 ceiling. Trim the metadata and
                # try again rather than failing a photo over its MakerNote.
                if exif is None or "too long" not in str(error).lower():
                    raise
                reduced, note = metadata.without_bulky_tags(
                    prepared.image, auto_rotate=options.auto_rotate
                )
                notes.append(note)
                notes.extend(_encode_resiliently(adapted, staged, target, arguments, reduced))

            os.replace(staged, destination)
        except BaseException:
            # Includes the cancel path: a partial file must never be left behind
            # looking like output.
            staged.unlink(missing_ok=True)
            raise

    return EncodeResult(path=destination, notes=tuple(notes))


def _encode(
    image: Image.Image,
    staged: Path,
    target: ImageFormat,
    arguments: dict[str, object],
    exif: bytes | None,
) -> None:
    """One encode attempt into the staging file."""
    keywords = dict(arguments)
    if exif is not None:
        keywords["exif"] = exif
    image.save(staged, format=target.pillow_id, **keywords)


def decoder_versions() -> dict[str, str]:
    """Versions of the libraries doing the work, for the About box and selftest."""
    import PIL

    return {
        "Pillow": PIL.__version__,
        "pillow-heif": pillow_heif.__version__,
        "libheif": pillow_heif.libheif_version(),
    }
