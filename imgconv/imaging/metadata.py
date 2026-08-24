"""EXIF: keeping the capture time, and not rotating the photo twice.

**Why the metadata is kept by default.** A field photo's value in an inspection
report is partly its timestamp. *Date taken* is not recoverable once dropped -
the file's modification time is the time it was converted, not the time it was
shot - so this program carries EXIF forward unless told not to.

**The double-rotation trap.** EXIF orientation says "the pixels are stored
sideways; rotate before display". Applying the rotation to the pixels while
leaving the tag in place tells the next viewer to rotate again, and the photo
lands on its side in half the applications that open it. :func:`prepare` applies
the rotation and then *states* orientation 1 rather than leaving the tag absent,
so the file declares its own uprightness instead of relying on a default.

For HEIC specifically this is already handled upstream: pillow-heif applies the
container's rotation and hands over an image tagged orientation 1, verified
against the owner's own photos. The transpose below is therefore a no-op on that
pathway and load-bearing on the TIFF, JPEG and PNG ones, where nothing has
normalised anything.

**Metadata never fails a conversion.** JPEG stores EXIF in an APP1 segment that
cannot exceed 64 KB, and an iPhone MakerNote can approach that on its own. When
the block will not fit, the bulky proprietary tags are dropped and the timestamp
kept - and if even that will not fit, the image is written without EXIF and the
result says so. Losing a photo because of its metadata would be absurd.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageOps

ORIENTATION_TAG = 0x0112
"""EXIF Orientation, TIFF IFD0. 1 means "stored upright"."""

EXIF_IFD_TAG = 0x8769
"""Pointer to the Exif sub-IFD, where the timestamps and MakerNote live."""

MAKERNOTE_TAG = 0x927C
"""Manufacturer-defined blob. Undocumented, unreadable by anything but the
vendor's own software, and routinely tens of kilobytes on an iPhone - the first
thing to go when the EXIF block will not fit."""

USER_COMMENT_TAG = 0x9286

DATE_TIME_ORIGINAL_TAG = 0x9003
"""The one field this module exists to protect."""

JPEG_EXIF_LIMIT = 65533
"""Maximum EXIF payload in a JPEG APP1 segment: 65535 minus the two length
bytes. Pillow refuses a longer block with ``ValueError``."""


@dataclass(frozen=True)
class MetadataResult:
    """The upright image and the EXIF block to write beside it."""

    image: Image.Image
    exif: bytes | None
    notes: tuple[str, ...] = ()


def prepare(image: Image.Image, *, keep_metadata: bool, auto_rotate: bool) -> MetadataResult:
    """Apply the orientation, then produce the EXIF block for the output."""
    notes: list[str] = []
    working = image

    if auto_rotate:
        rotated = ImageOps.exif_transpose(image)
        if rotated is not None:
            if rotated.size != image.size:
                notes.append("Rotated to upright using the camera's orientation tag.")
            working = rotated

    if not keep_metadata:
        return MetadataResult(image=working, exif=None, notes=tuple(notes))

    exif = working.getexif()

    # Pillow's exif_transpose REMOVES the orientation tag rather than setting it
    # to 1. State it explicitly, so the file declares itself upright instead of
    # relying on every reader's default for an absent tag.
    #
    # This must happen BEFORE the "nothing to carry" check below, not after. A
    # photo whose only EXIF was its orientation - which is the commonest case
    # there is - has an empty block at this point precisely because the rotation
    # was just applied. Checking first meant returning no EXIF at all and never
    # declaring the uprightness this function exists to declare.
    if auto_rotate:
        exif[ORIENTATION_TAG] = 1

    if not exif and not exif.get_ifd(EXIF_IFD_TAG):
        # Nothing to carry. An empty EXIF block is worse than none: it is bytes
        # in the file that say nothing.
        return MetadataResult(image=working, exif=None, notes=tuple(notes))

    try:
        blob = exif.tobytes()
    except Exception as error:  # pragma: no cover - malformed source EXIF
        return MetadataResult(
            image=working,
            exif=None,
            notes=(*notes, f"Metadata could not be read ({type(error).__name__}) and was dropped."),
        )

    return MetadataResult(image=working, exif=blob, notes=tuple(notes))


def without_bulky_tags(image: Image.Image, *, auto_rotate: bool) -> tuple[bytes | None, str]:
    """A smaller EXIF block for when the full one will not fit in a JPEG.

    Returns the reduced block and a note describing what was given up. The
    timestamp, camera, lens and GPS fields all survive; what goes is the
    MakerNote and any user comment, which together are essentially always the
    reason the block was oversized.
    """
    exif = image.getexif()
    if auto_rotate:
        exif[ORIENTATION_TAG] = 1

    sub_ifd = exif.get_ifd(EXIF_IFD_TAG)
    dropped = []
    for tag, name in ((MAKERNOTE_TAG, "camera maker notes"), (USER_COMMENT_TAG, "user comment")):
        if tag in sub_ifd:
            del sub_ifd[tag]
            dropped.append(name)

    try:
        blob = exif.tobytes()
    except Exception:  # pragma: no cover - defensive
        return None, "Metadata was too large for a JPEG and was dropped."

    if len(blob) > JPEG_EXIF_LIMIT:
        return None, (
            "Metadata was too large for a JPEG even after trimming, so it was "
            "dropped. The image itself is unaffected."
        )

    what = " and ".join(dropped) if dropped else "some fields"
    return blob, (
        f"Metadata was too large for a JPEG; the {what} were dropped. "
        f"Date taken, camera and GPS were kept."
    )


def date_taken(image: Image.Image) -> str | None:
    """``DateTimeOriginal`` as EXIF stores it, or ``None``.

    Read by the self-test to prove the timestamp survived a round trip through
    the frozen bundle.
    """
    try:
        return image.getexif().get_ifd(EXIF_IFD_TAG).get(DATE_TIME_ORIGINAL_TAG)
    except Exception:  # pragma: no cover - defensive
        return None
