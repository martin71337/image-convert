"""Image formats, and how to tell which one a file actually is.

**Nothing here trusts a filename.** A real file in the owner's Downloads folder,
``page2.HEIC``, begins ``FF D8 FF E0 ... JFIF`` - it is an ordinary JPEG wearing a
``.HEIC`` extension, and a converter that dispatches on the extension fails on it
with a message about HEIC decoding that has nothing to do with what went wrong.
:func:`sniff` reads the leading bytes and answers what the file *is*; the
extension is compared against that answer only so the mismatch can be reported
(:func:`extension_disagrees`), never so it can decide anything.

Formats are records, not string constants, so a format carries its own
capabilities. ``JPEG.supports_alpha`` is False in one authoritative place, and
the conversion layer asks the record rather than re-deciding at each call site.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

HEADER_BYTES = 64
"""How much of a file :func:`sniff` needs.

The longest discriminator is the ISO base media ``ftyp`` box, which carries a
major brand and a list of compatible brands. Real HEIC and AVIF files keep that
box well inside 64 bytes; ``IMG_2480.HEIC`` uses 40.
"""


@dataclass(frozen=True)
class ImageFormat:
    """One image format, and what can be done with it.

    ``pillow_id`` is the name Pillow knows the format by - what it puts in
    ``Image.format`` and accepts in ``Image.save(format=...)``. ``None`` would
    mean Pillow has no such format, which no record uses today but a future
    non-Pillow pathway (a PDF writer, say) would.
    """

    key: str
    """Stable identifier. Used in records, tests and saved settings; never shown
    to a user."""

    label: str
    """What the interface calls it."""

    extensions: tuple[str, ...]
    """Every extension that customarily names this format, lowercase, with the
    dot. Used to recognise a *claimed* format, never an actual one."""

    default_extension: str
    """The extension this program writes when it produces this format."""

    pillow_id: str | None
    supports_alpha: bool
    supports_exif: bool

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.label


# ---------------------------------------------------------------------------
# The formats. Declaration order is the order any interface lists them in.
# ---------------------------------------------------------------------------

HEIC = ImageFormat(
    key="HEIC",
    label="HEIC / HEIF",
    extensions=(".heic", ".heif", ".hif"),
    default_extension=".heic",
    pillow_id="HEIF",
    supports_alpha=True,
    supports_exif=True,
)

AVIF = ImageFormat(
    key="AVIF",
    label="AVIF",
    extensions=(".avif",),
    default_extension=".avif",
    pillow_id="AVIF",
    supports_alpha=True,
    supports_exif=True,
)

JPEG = ImageFormat(
    key="JPEG",
    label="JPEG",
    extensions=(".jpg", ".jpeg", ".jpe"),
    default_extension=".jpg",
    pillow_id="JPEG",
    supports_alpha=False,
    supports_exif=True,
)

PNG = ImageFormat(
    key="PNG",
    label="PNG",
    extensions=(".png",),
    default_extension=".png",
    pillow_id="PNG",
    supports_alpha=True,
    supports_exif=True,
)

TIFF = ImageFormat(
    key="TIFF",
    label="TIFF",
    extensions=(".tif", ".tiff"),
    default_extension=".tif",
    pillow_id="TIFF",
    supports_alpha=True,
    supports_exif=True,
)

WEBP = ImageFormat(
    key="WEBP",
    label="WebP",
    extensions=(".webp",),
    default_extension=".webp",
    pillow_id="WEBP",
    supports_alpha=True,
    supports_exif=True,
)

BMP = ImageFormat(
    key="BMP",
    label="BMP",
    extensions=(".bmp", ".dib"),
    default_extension=".bmp",
    pillow_id="BMP",
    supports_alpha=False,
    supports_exif=False,
)

GIF = ImageFormat(
    key="GIF",
    label="GIF",
    extensions=(".gif",),
    default_extension=".gif",
    pillow_id="GIF",
    supports_alpha=True,
    supports_exif=False,
)

ALL_FORMATS: tuple[ImageFormat, ...] = (HEIC, AVIF, JPEG, PNG, TIFF, WEBP, BMP, GIF)

_BY_KEY = {fmt.key: fmt for fmt in ALL_FORMATS}

_BY_EXTENSION = {ext: fmt for fmt in ALL_FORMATS for ext in fmt.extensions}


def format_by_key(key: str) -> ImageFormat:
    """The record for ``key``, or ``KeyError`` naming what was asked for."""
    try:
        return _BY_KEY[key]
    except KeyError:
        raise KeyError(
            f"no image format is registered under {key!r}; "
            f"registered keys are {', '.join(sorted(_BY_KEY))}."
        ) from None


def format_claimed_by_extension(path: Path) -> ImageFormat | None:
    """What the *filename* claims. Never used to decide how to read a file."""
    return _BY_EXTENSION.get(path.suffix.lower())


def readable_extensions() -> tuple[str, ...]:
    """Every extension any known format uses, for the file dialog's filter.

    A filter is a convenience, not a gate: a file that gets past it is still
    sniffed, and a file the filter would have hidden still converts if the user
    types its name.
    """
    return tuple(sorted(_BY_EXTENSION))


# ---------------------------------------------------------------------------
# Sniffing
# ---------------------------------------------------------------------------

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_HEIF_BRANDS = frozenset(
    {
        b"heic",  # HEVC, single image - what an iPhone writes
        b"heix",  # HEVC, 10-bit
        b"heim",  # HEVC multiview
        b"heis",
        b"hevc",  # HEVC image sequence
        b"hevx",
        b"hevm",
        b"hevs",
        b"mif1",  # generic MIAF still image
        b"msf1",  # generic MIAF image sequence
    }
)

_AVIF_BRANDS = frozenset({b"avif", b"avis"})


def _brands(head: bytes) -> tuple[bytes, ...]:
    """Major brand plus compatible brands from an ISO base media ``ftyp`` box.

    Returns an empty tuple when ``head`` is not an ISO-BMFF file at all.

    The compatible-brand list is what settles HEIC against AVIF. Both are ISO
    base media files and both routinely declare the *same* major brand ``mif1``
    - only the compatible list says which codec is inside. Deciding on the major
    brand alone would classify a good share of real AVIF files as HEIC.
    """
    if len(head) < 12 or head[4:8] != b"ftyp":
        return ()

    box_size = int.from_bytes(head[0:4], "big")
    # A malformed or oversized declared size must not read past what we have.
    end = min(box_size, len(head)) if box_size >= 16 else len(head)

    brands = [head[8:12]]
    # Compatible brands follow the major brand (4 bytes) and minor version (4).
    position = 16
    while position + 4 <= end:
        brands.append(head[position : position + 4])
        position += 4
    return tuple(brands)


def sniff_bytes(head: bytes) -> ImageFormat | None:
    """Identify a format from its leading bytes. ``None`` if unrecognised.

    ``head`` should be the first :data:`HEADER_BYTES` bytes of the file; a
    shorter buffer is accepted and simply identifies fewer formats. An empty or
    truncated file returns ``None`` rather than raising - "I do not recognise
    this" is a result the caller reports, not an error.
    """
    if not head:
        return None

    if head.startswith(_PNG_SIGNATURE):
        return PNG
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    if head.startswith(b"II\x2a\x00") or head.startswith(b"MM\x00\x2a"):
        return TIFF
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return WEBP
    if head.startswith(b"BM"):
        return BMP
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return GIF

    brands = _brands(head)
    if brands:
        # AVIF is checked first: an AVIF file may declare mif1 as its major
        # brand and name avif only in the compatible list, so a HEIF-first test
        # would claim it.
        if any(brand in _AVIF_BRANDS for brand in brands):
            return AVIF
        if any(brand in _HEIF_BRANDS for brand in brands):
            return HEIC

    return None


def sniff(path: Path) -> ImageFormat | None:
    """Identify the format of the file at ``path`` by reading its leading bytes.

    Returns ``None`` for a file this program does not recognise, including an
    empty one. An unreadable file raises ``OSError``, which the caller reports
    against that file and continues - a directory of photos is not abandoned
    because one file in it is locked.
    """
    with open(path, "rb") as handle:
        return sniff_bytes(handle.read(HEADER_BYTES))


def extension_disagrees(path: Path, actual: ImageFormat) -> bool:
    """True when ``path``'s extension names a different format than ``actual``.

    An unrecognised extension is not a disagreement - the file may have none at
    all, and that is not a mislabelling. This drives a note on the result row and
    nothing more; the conversion has already been routed by ``actual``.
    """
    claimed = format_claimed_by_extension(path)
    return claimed is not None and claimed is not actual
