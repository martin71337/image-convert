"""Colour profiles: getting an iPhone's Display P3 pixels into sRGB.

**Why this is not optional.** An iPhone photo carries a Display P3 ICC profile.
Its pixel values are only meaningful *with* that profile - the same numbers read
as sRGB are noticeably oversaturated, reds especially. Two ways to be correct:
carry the profile through and hope every downstream consumer honours it, or
convert the numbers into sRGB so they are right even where the profile is
ignored. Word's image placement, several PDF pipelines and a good deal of print
software ignore it, so this program converts.

**A missing profile is not a licence to convert.** An untagged image is sRGB by
universal convention; running a P3-to-sRGB transform over it would desaturate
pixels that were already correct. Untagged input is left alone.

Failure here is never fatal to a conversion. A Pillow built without littleCMS,
or a corrupt embedded profile, produces a note on the result and unconverted
pixels - the photo still converts, and the user is told what did not happen.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image

try:
    from PIL import ImageCms

    CMS_AVAILABLE = True
except ImportError:  # pragma: no cover - littleCMS is in every standard wheel
    ImageCms = None  # type: ignore[assignment]
    CMS_AVAILABLE = False


@dataclass(frozen=True)
class ColourResult:
    """The image after colour handling, the profile to embed, and what to say."""

    image: Image.Image
    icc_profile: bytes | None
    notes: tuple[str, ...] = ()


_srgb_cache: bytes | None = None


def srgb_profile_bytes() -> bytes:
    """The sRGB profile this program embeds, built once and reused.

    Embedding it rather than writing an untagged file is deliberate: an untagged
    JPEG is *assumed* sRGB by convention, but an explicitly tagged one is
    correct by declaration, and colour-managed viewers stop guessing.
    """
    global _srgb_cache
    if _srgb_cache is None:
        if not CMS_AVAILABLE:  # pragma: no cover - guarded by callers
            raise RuntimeError("littleCMS is unavailable; no sRGB profile to build.")
        _srgb_cache = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    return _srgb_cache


def _describes_srgb(profile_bytes: bytes) -> bool:
    """True when an embedded profile is already some flavour of sRGB.

    Matched on the profile's description string. That is a heuristic - a profile
    could describe itself as anything - but the cost of being wrong is one
    redundant identity transform, not a wrong colour, so a heuristic is the
    right tool. It saves a full-image transform on every already-sRGB photo.
    """
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(profile_bytes))
        description = ImageCms.getProfileDescription(profile) or ""
    except Exception:
        return False
    return "srgb" in description.replace(" ", "").lower()


def to_srgb(image: Image.Image, *, enabled: bool) -> ColourResult:
    """Convert ``image`` into sRGB if it carries some other profile.

    Alpha is carried around the transform rather than through it: littleCMS
    transforms colour channels, and handing it an RGBA image either fails or
    silently drops the alpha depending on the build. The alpha channel is split
    off, the colour converted, and the two recombined - which is why a
    transparent PNG survives this with its transparency intact.
    """
    embedded = image.info.get("icc_profile")

    if not enabled:
        # Not converting means the pixels stay in whatever space they are in, so
        # the profile that describes them must travel with them.
        return ColourResult(image=image, icc_profile=embedded)

    if not embedded:
        # Untagged input is sRGB by convention. Say so explicitly on the way out.
        return ColourResult(
            image=image,
            icc_profile=srgb_profile_bytes() if CMS_AVAILABLE else None,
        )

    if not CMS_AVAILABLE:
        return ColourResult(
            image=image,
            icc_profile=embedded,
            notes=(
                "Colour could not be converted to sRGB (littleCMS unavailable); "
                "the original profile was kept instead.",
            ),
        )

    if _describes_srgb(embedded):
        return ColourResult(image=image, icc_profile=srgb_profile_bytes())

    alpha = None
    working = image
    if image.mode in ("RGBA", "LA", "PA"):
        alpha = image.getchannel("A")
        working = image.convert("RGB")
    elif image.mode not in ("RGB", "L"):
        working = image.convert("RGB")

    try:
        source = ImageCms.ImageCmsProfile(io.BytesIO(embedded))
        converted = ImageCms.profileToProfile(
            working,
            source,
            ImageCms.createProfile("sRGB"),
            outputMode="RGB",
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
        )
    except Exception as error:
        return ColourResult(
            image=image,
            icc_profile=embedded,
            notes=(
                f"Colour could not be converted to sRGB ({type(error).__name__}); "
                f"the original profile was kept instead.",
            ),
        )

    if converted is None:  # pragma: no cover - defensive; the API can return None
        return ColourResult(
            image=image,
            icc_profile=embedded,
            notes=("Colour could not be converted to sRGB; the original profile was kept.",),
        )

    if alpha is not None:
        converted.putalpha(alpha)

    return ColourResult(image=converted, icc_profile=srgb_profile_bytes())
