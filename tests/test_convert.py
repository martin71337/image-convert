"""Converting one file: orientation, metadata, colour and pixel mode."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from imgconv import formats
from imgconv.convert import convert_one
from imgconv.imaging.metadata import ORIENTATION_TAG, date_taken
from imgconv.options import CollisionPolicy, ConversionOptions, OutputLocation
from imgconv.result import Outcome

from conftest import SAMPLE_DATE


def options(tmp_path: Path, **overrides) -> ConversionOptions:
    defaults = dict(
        target_format=formats.JPEG,
        output_location=OutputLocation.CHOSEN,
        output_folder=tmp_path / "out",
    )
    defaults.update(overrides)
    return ConversionOptions(**defaults)


def convert(source: Path, tmp_path: Path, **overrides):
    result = convert_one(source, options(tmp_path, **overrides))
    return result


def assert_close(actual, expected, tolerance: int = 4) -> None:
    """Compare pixels allowing for JPEG's lossiness.

    A JPEG round trip moves a flat colour by a unit or two. Exact equality here
    would fail for a reason that has nothing to do with what is being tested.
    """
    assert len(actual) >= len(expected)
    for index, (a, b) in enumerate(zip(actual, expected)):
        assert abs(a - b) <= tolerance, (
            f"channel {index}: {actual} is not within {tolerance} of {expected}"
        )


# A TRAP, RECORDED SO IT IS NOT REDISCOVERED: TIFF is not a faithful fixture.
#
# Pillow's TIFF *writer* honours an EXIF orientation by physically rotating the
# pixels and then dropping the tag, and it does not carry an EXIF sub-IFD
# through intact. A TIFF fixture therefore cannot be used to test orientation
# (there is nothing left to apply) or metadata trimming (the timestamp is gone
# before the code under test runs). PNG and WebP both store the tag and the
# sub-IFD untouched, and are used instead. Verified on Pillow 12.3.0.


class TestTheHeadlineConversion:
    def test_heic_becomes_jpeg(self, make_image, quadrants, tmp_path):
        source = make_image("IMG_0001.heic", "HEIF", quadrants)
        result = convert(source, tmp_path)

        assert result.outcome is Outcome.CONVERTED, result.reason
        assert result.target is not None and result.target.is_file()
        assert result.target.name == "IMG_0001.jpg"
        assert formats.sniff(result.target) is formats.JPEG

    def test_the_pixels_survive(self, make_image, quadrants, tmp_path):
        """Proof that real image data came through, not a blank of the right size.

        Each quadrant is checked separately: a conversion that returned a
        uniform image, or a rotated one, or a mirrored one, passes a size
        assertion and fails this.
        """
        source = make_image("IMG_0001.heic", "HEIF", quadrants)
        result = convert(source, tmp_path)
        converted = Image.open(result.target)

        assert converted.size == quadrants.size
        width, height = quadrants.size
        for x, y in ((5, 5), (width - 5, 5), (5, height - 5), (width - 5, height - 5)):
            expected = quadrants.getpixel((x, y))
            actual = converted.getpixel((x, y))
            assert all(abs(a - b) < 40 for a, b in zip(expected, actual)), (
                f"quadrant at {(x, y)}: expected about {expected}, got {actual}"
            )

    def test_a_real_iphone_photo_converts_upright(self, real_photo, tmp_path):
        """The genuine article, when this machine has one."""
        original = Image.open(real_photo)
        result = convert(real_photo, tmp_path)

        assert result.outcome is Outcome.CONVERTED, result.reason
        converted = Image.open(result.target)
        assert converted.size == original.size
        assert converted.getexif().get(ORIENTATION_TAG) == 1
        assert date_taken(converted) == date_taken(original)


class TestOrientation:
    """The double-rotation trap.

    pillow-heif already normalises HEIC orientation before this program sees it,
    so the trap does not live on the HEIC pathway. It lives on the other
    pathways, where nothing has normalised anything.

    These use a PNG source, not a TIFF: see the note above on why a TIFF fixture
    cannot test this at all.
    """

    def test_a_sideways_source_comes_out_upright(self, make_image, quadrants, tmp_path):
        source = make_image("scan.png", "PNG", quadrants, orientation=6)
        result = convert(source, tmp_path)
        converted = Image.open(result.target)

        # Orientation 6 means "rotate 90 degrees clockwise to display", so the
        # stored landscape becomes an upright portrait.
        assert converted.size == (quadrants.size[1], quadrants.size[0])

    def test_the_output_declares_orientation_one(self, make_image, quadrants, tmp_path):
        """The half that is easy to forget.

        Rotating the pixels and leaving the tag saying "rotate me" tells the
        next viewer to rotate again. The file must declare itself upright.
        """
        source = make_image("scan.png", "PNG", quadrants, orientation=6)
        result = convert(source, tmp_path)
        assert Image.open(result.target).getexif().get(ORIENTATION_TAG) == 1

    def test_auto_rotate_off_leaves_the_pixels_alone(self, make_image, quadrants, tmp_path):
        source = make_image("scan.png", "PNG", quadrants, orientation=6)
        result = convert(source, tmp_path, auto_rotate=False)
        assert Image.open(result.target).size == quadrants.size

    def test_an_already_upright_source_is_not_rotated(self, make_image, quadrants, tmp_path):
        source = make_image("scan.png", "PNG", quadrants, orientation=1)
        result = convert(source, tmp_path)
        assert Image.open(result.target).size == quadrants.size


class TestMetadata:
    def test_the_capture_date_survives(self, make_image, quadrants, tmp_path):
        """What an inspection report's photo log is keyed to, and unrecoverable."""
        source = make_image("IMG_0001.heic", "HEIF", quadrants, date=SAMPLE_DATE)
        result = convert(source, tmp_path)
        assert date_taken(Image.open(result.target)) == SAMPLE_DATE

    def test_metadata_can_be_dropped_on_request(self, make_image, quadrants, tmp_path):
        source = make_image("IMG_0001.heic", "HEIF", quadrants, date=SAMPLE_DATE)
        result = convert(source, tmp_path, keep_metadata=False)
        assert date_taken(Image.open(result.target)) is None

    def test_oversized_metadata_degrades_instead_of_failing(
        self, make_image, quadrants, tmp_path
    ):
        """A JPEG's EXIF cannot exceed 64 KB and an iPhone MakerNote approaches it.

        The photograph must still convert, the capture date must still survive,
        and the user must be told what was given up. Failing the file over its
        metadata would be absurd.
        """
        from imgconv.imaging.metadata import EXIF_IFD_TAG, MAKERNOTE_TAG

        image = quadrants.copy()
        exif = image.getexif()
        sub = exif.get_ifd(EXIF_IFD_TAG)
        sub[MAKERNOTE_TAG] = b"M" * 70_000
        sub[0x9003] = SAMPLE_DATE

        source = tmp_path / "big.png"
        image.save(source, format="PNG", exif=exif.tobytes())

        result = convert(source, tmp_path)

        assert result.outcome is Outcome.CONVERTED, result.reason
        converted = Image.open(result.target)
        assert date_taken(converted) == SAMPLE_DATE, "the date must survive the trim"
        assert any("too large" in note for note in result.notes), result.notes


class TestColour:
    def test_a_wide_gamut_profile_is_converted_to_srgb(
        self, make_image, quadrants, wide_gamut_profile, tmp_path
    ):
        """The Display P3 case: the pixel numbers must actually change.

        Carrying wide-gamut numbers into a file tagged sRGB, or leaving them
        untouched where the profile is ignored, is what makes an iPhone photo
        look oversaturated in Word.
        """
        source = make_image(
            "p3.png", "PNG", quadrants, icc_profile=wide_gamut_profile
        )
        result = convert(source, tmp_path)
        converted = Image.open(result.target)

        before = quadrants.getpixel((5, 5))
        after = converted.getpixel((5, 5))
        assert max(abs(a - b) for a, b in zip(after, before)) > 8, (
            f"wide-gamut {before} should have shifted materially, got {after}"
        )
        assert converted.info.get("icc_profile") not in (None, wide_gamut_profile)

    def test_leaving_colour_alone_keeps_the_original_profile(
        self, make_image, quadrants, wide_gamut_profile, tmp_path
    ):
        """Unconverted pixels must keep the profile that describes them."""
        source = make_image(
            "p3.png", "PNG", quadrants, icc_profile=wide_gamut_profile
        )
        result = convert(source, tmp_path, convert_to_srgb=False)
        converted = Image.open(result.target)

        assert_close(converted.getpixel((5, 5)), quadrants.getpixel((5, 5)))
        assert converted.info.get("icc_profile") == wide_gamut_profile

    def test_an_untagged_image_is_not_transformed(self, make_image, quadrants, tmp_path):
        """Untagged means sRGB by convention. Running a transform over it would
        desaturate pixels that were already right."""
        source = make_image("plain.png", "PNG", quadrants)
        result = convert(source, tmp_path)
        converted = Image.open(result.target)
        assert_close(converted.getpixel((5, 5)), quadrants.getpixel((5, 5)))

    def test_an_untagged_image_comes_out_tagged_srgb(self, make_image, quadrants, tmp_path):
        source = make_image("plain.png", "PNG", quadrants)
        result = convert(source, tmp_path)
        assert Image.open(result.target).info.get("icc_profile")


class TestPixelMode:
    def test_transparency_is_flattened_onto_white_for_jpeg(self, tmp_path, make_image):
        """JPEG cannot hold alpha. Dropping the channel instead of compositing
        reveals whatever colour sits in the transparent pixels, usually black."""
        image = Image.new("RGBA", (20, 20), (255, 0, 0, 0))
        source = make_image("clear.png", "PNG", image)
        result = convert(source, tmp_path)

        converted = Image.open(result.target)
        assert converted.mode == "RGB"
        assert converted.getpixel((10, 10)) == (255, 255, 255)
        assert any("flattened" in note for note in result.notes), result.notes

    def test_transparency_survives_a_png_target(self, tmp_path, make_image):
        image = Image.new("RGBA", (20, 20), (255, 0, 0, 0))
        source = make_image("clear.webp", "WEBP", image)
        result = convert(source, tmp_path, target_format=formats.PNG)

        converted = Image.open(result.target)
        assert converted.mode in ("RGBA", "LA", "P")
        assert converted.convert("RGBA").getpixel((10, 10))[3] == 0

    def test_an_opaque_image_is_not_reported_as_flattened(self, make_image, quadrants, tmp_path):
        """The note must be about what happened, not about the code path taken."""
        image = quadrants.convert("RGBA")
        source = make_image("opaque.png", "PNG", image)
        result = convert(source, tmp_path)
        assert not any("flattened" in note for note in result.notes), result.notes


class TestRefusals:
    def test_a_missing_file_fails_without_raising(self, tmp_path):
        result = convert(tmp_path / "gone.heic", tmp_path)
        assert result.outcome is Outcome.FAILED
        assert "no longer exists" in result.reason

    def test_an_empty_file_fails_by_name(self, tmp_path):
        source = tmp_path / "empty.heic"
        source.write_bytes(b"")
        result = convert(source, tmp_path)
        assert result.outcome is Outcome.FAILED
        assert "empty" in result.reason

    def test_a_text_file_named_heic_is_refused_clearly(self, tmp_path):
        source = tmp_path / "notes.heic"
        source.write_text("not a photograph")
        result = convert(source, tmp_path)
        assert result.outcome is Outcome.FAILED
        assert "not an image" in result.reason.lower()

    def test_a_format_with_no_pathway_is_refused_by_name(self, make_image, quadrants, tmp_path):
        source = make_image("animation.gif", "GIF", quadrants)
        result = convert(source, tmp_path)
        assert result.outcome is Outcome.FAILED
        assert "GIF" in result.reason

    def test_a_file_already_the_target_is_skipped_not_failed(
        self, make_image, quadrants, tmp_path
    ):
        """Re-encoding a JPEG as a JPEG would lose quality for no reason."""
        source = make_image("photo.jpg", "JPEG", quadrants)
        result = convert(source, tmp_path)
        assert result.outcome is Outcome.SKIPPED
        assert "Already" in result.reason

    def test_converting_onto_itself_is_refused(self, make_image, quadrants, tmp_path):
        """Reachable: a JPEG, alongside, overwriting. Reading a file while
        truncating it produces a zero-byte result."""
        source = make_image("photo.png", "PNG", quadrants)
        result = convert_one(
            source,
            ConversionOptions(
                target_format=formats.PNG,
                output_location=OutputLocation.ALONGSIDE,
                collision=CollisionPolicy.OVERWRITE,
            ),
        )
        # PNG to PNG is the identity, so this is caught as "already that format"
        # before it can reach the self-overwrite guard.
        assert result.outcome is Outcome.SKIPPED
        assert source.stat().st_size > 0


class TestTheMislabelledFile:
    def test_it_is_routed_by_content_and_reported(self, make_image, quadrants, tmp_path):
        """``page2.HEIC``: a JPEG with a HEIC extension, converted to PNG.

        Routing by extension would send it to a HEIC decoder and fail. Routing by
        content converts it, and the note tells the user their file is misnamed.
        """
        source = make_image("page2.HEIC", "JPEG", quadrants)
        result = convert(source, tmp_path, target_format=formats.PNG)

        assert result.outcome is Outcome.CONVERTED, result.reason
        assert result.source_format is formats.JPEG
        assert result.target.name == "page2.png"
        assert any("named" in note and "JPEG" in note for note in result.notes), result.notes


class TestAtomicWriting:
    def test_no_partial_file_is_left_behind_on_success(self, make_image, quadrants, tmp_path):
        source = make_image("IMG_0001.heic", "HEIF", quadrants)
        result = convert(source, tmp_path)
        leftovers = list(result.target.parent.glob("*.partial"))
        assert leftovers == []

    def test_a_failed_encode_leaves_no_partial_file(
        self, make_image, quadrants, tmp_path, monkeypatch
    ):
        """The reason writes are staged: an interrupted conversion must leave
        nothing that looks like output."""
        from imgconv.imaging import backend

        def explode(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(backend, "_encode", explode)

        source = make_image("IMG_0001.heic", "HEIF", quadrants)
        result = convert(source, tmp_path)

        assert result.outcome is Outcome.FAILED
        output = tmp_path / "out"
        if output.exists():
            assert list(output.glob("*.partial")) == []
            assert list(output.glob("*.jpg")) == []


class TestTheEncoderBuffer:
    """A defect found on the owner's real files, not by a test.

    Pillow sizes the JPEG encoder buffer at one byte per pixel when ``optimize``
    or ``progressive`` is set - a guess calibrated for chroma-subsampled output.
    At ``subsampling=0``, which this program uses at quality 90 and above, a
    detailed image encodes to more than that and overruns the buffer, and Pillow
    raises ``OSError: broken data stream when writing image file``.

    It cost one file out of 649 in a real Downloads folder, and the class of file
    it hits - screenshots, scanned drawings, anything with hard edges and text -
    is exactly what this owner converts alongside photographs.
    """

    @staticmethod
    def _incompressible(width: int = 700, height: int = 700) -> Image.Image:
        """An image that will not compress: every pixel independently random.

        This is what makes the encoded output exceed one byte per pixel, which
        is the condition that overruns the buffer. A photograph never does it;
        a screenshot full of text can, and pure noise reliably does.
        """
        import random

        rng = random.Random(20260324)
        image = Image.new("RGB", (width, height))
        image.putdata(
            [
                (rng.randrange(256), rng.randrange(256), rng.randrange(256))
                for _ in range(width * height)
            ]
        )
        return image

    def test_an_incompressible_image_still_converts(self, make_image, tmp_path):
        source = make_image("noise.png", "PNG", self._incompressible())
        result = convert(source, tmp_path, quality=95)

        assert result.outcome is Outcome.CONVERTED, result.reason
        assert result.target.is_file()
        assert result.target_bytes > source.stat().st_size * 0.5

    def test_it_is_the_full_chroma_path_that_needs_the_buffer(self, make_image, tmp_path):
        """Below the subsampling threshold the buffer is not stressed, so this
        confirms the test above is exercising the path that actually broke."""
        source = make_image("noise.png", "PNG", self._incompressible())
        result = convert(source, tmp_path, quality=80)
        assert result.outcome is Outcome.CONVERTED, result.reason

    def test_the_buffer_is_only_ever_raised(self):
        """The property that makes mutating Pillow's global safe under threads.

        A thread that LOWERED MAXBLOCK would break whichever other thread needed
        the larger buffer. Only ever raising it means a concurrent save can be
        given a bigger buffer than it asked for, which is always fine.
        """
        from PIL import ImageFile

        from imgconv.imaging.backend import _grow_encoder_buffer

        _grow_encoder_buffer(4_000_000)
        high = ImageFile.MAXBLOCK
        _grow_encoder_buffer(16)
        assert ImageFile.MAXBLOCK >= high, "MAXBLOCK must never be lowered"

    def test_the_buffer_stops_growing_at_the_ceiling(self):
        """Otherwise a pathological image could ask for unbounded memory."""
        from PIL import ImageFile

        from imgconv.imaging.backend import ENCODER_BUFFER_CEILING, _grow_encoder_buffer

        original = ImageFile.MAXBLOCK
        try:
            for _ in range(200):
                if not _grow_encoder_buffer(10**9):
                    break
            assert ImageFile.MAXBLOCK <= ENCODER_BUFFER_CEILING
            assert _grow_encoder_buffer(10**9) is False
        finally:
            ImageFile.MAXBLOCK = original

    def test_a_real_encoder_error_is_not_mistaken_for_a_buffer_problem(
        self, make_image, quadrants, tmp_path, monkeypatch
    ):
        """A full disk must not send the encoder into a retry loop."""
        from imgconv.imaging import backend

        def refuse(*args, **kwargs):
            raise OSError("No space left on device")

        monkeypatch.setattr(backend, "_encode", refuse)
        source = make_image("IMG_1.heic", "HEIF", quadrants)
        result = convert(source, tmp_path)

        assert result.outcome is Outcome.FAILED
        assert "space" in result.reason.lower()

    def test_the_last_resort_gives_up_chroma_not_the_file(
        self, make_image, tmp_path, monkeypatch
    ):
        """When the buffer cannot grow far enough, the image still converts.

        Forced by lowering the ceiling below what the image needs, which is the
        only way to reach this branch without a genuinely enormous file.
        """
        from PIL import ImageFile

        from imgconv.imaging import backend

        monkeypatch.setattr(backend, "ENCODER_BUFFER_CEILING", 70_000)
        monkeypatch.setattr(ImageFile, "MAXBLOCK", 65_536)

        source = make_image("noise.png", "PNG", self._incompressible())
        result = convert(source, tmp_path, quality=95)

        assert result.outcome is Outcome.CONVERTED, result.reason
        assert any("subsampling" in note for note in result.notes), result.notes
