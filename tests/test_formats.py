"""Identifying a file by its contents rather than its name."""

from __future__ import annotations

from pathlib import Path

import pytest

from imgconv import formats


class TestSniffing:
    def test_recognises_a_real_heic(self, make_image, quadrants):
        path = make_image("photo.heic", "HEIF", quadrants)
        assert formats.sniff(path) is formats.HEIC

    def test_recognises_each_written_format(self, make_image, quadrants):
        """Whatever Pillow writes, the sniffer must recognise.

        A disagreement here means the program cannot identify its own output,
        which would break the "already that format" skip and the round trip.
        """
        for name, pillow_id, expected in (
            ("a.jpg", "JPEG", formats.JPEG),
            ("a.png", "PNG", formats.PNG),
            ("a.tif", "TIFF", formats.TIFF),
            ("a.webp", "WEBP", formats.WEBP),
            ("a.bmp", "BMP", formats.BMP),
            ("a.gif", "GIF", formats.GIF),
            ("a.heic", "HEIF", formats.HEIC),
        ):
            path = make_image(name, pillow_id, quadrants)
            assert formats.sniff(path) is expected, name

    def test_a_jpeg_named_heic_is_a_jpeg(self, make_image, quadrants):
        """The ``page2.HEIC`` case, from the owner's own Downloads folder.

        The file really is a JPEG. Believing the extension means routing it to a
        HEIC decoder and failing with a message about HEIC, which tells the user
        nothing about what is actually wrong.
        """
        path = make_image("page2.HEIC", "JPEG", quadrants)
        assert formats.sniff(path) is formats.JPEG
        assert formats.extension_disagrees(path, formats.JPEG) is True

    def test_a_correctly_named_file_does_not_disagree(self, make_image, quadrants):
        path = make_image("photo.jpg", "JPEG", quadrants)
        assert formats.extension_disagrees(path, formats.JPEG) is False

    def test_no_extension_is_not_a_disagreement(self, tmp_path, make_image, quadrants):
        """A file with no extension is not mislabelled; it is unlabelled."""
        source = make_image("photo.jpg", "JPEG", quadrants)
        bare = tmp_path / "photo"
        bare.write_bytes(source.read_bytes())
        assert formats.sniff(bare) is formats.JPEG
        assert formats.extension_disagrees(bare, formats.JPEG) is False

    def test_empty_file_is_unrecognised_not_an_error(self, tmp_path: Path):
        path = tmp_path / "empty.heic"
        path.write_bytes(b"")
        assert formats.sniff(path) is None

    def test_truncated_file_is_unrecognised(self, tmp_path: Path):
        path = tmp_path / "cut.heic"
        path.write_bytes(b"\x00\x00\x00")
        assert formats.sniff(path) is None

    def test_text_file_is_unrecognised(self, tmp_path: Path):
        path = tmp_path / "notes.heic"
        path.write_text("this is not a photograph")
        assert formats.sniff(path) is None

    def test_unreadable_file_raises_rather_than_lying(self, tmp_path: Path):
        with pytest.raises(OSError):
            formats.sniff(tmp_path / "does-not-exist.heic")


class TestBrandDiscrimination:
    """HEIC and AVIF are both ISO base media files; only the brands separate them."""

    @staticmethod
    def _ftyp(major: bytes, *compatible: bytes) -> bytes:
        size = 16 + 4 * len(compatible)
        return (
            size.to_bytes(4, "big")
            + b"ftyp"
            + major
            + b"\x00" * 4
            + b"".join(compatible)
        )

    def test_apple_brands_are_heic(self):
        # The exact brand list from the owner's IMG_2480.HEIC.
        head = self._ftyp(b"heic", b"mif1", b"MiHE", b"MiPr", b"miaf")
        assert formats.sniff_bytes(head) is formats.HEIC

    def test_avif_declared_only_in_the_compatible_list_is_avif(self):
        """The case a major-brand-only test gets wrong.

        A real AVIF commonly declares ``mif1`` as its major brand and names
        ``avif`` only among the compatible brands. Checking the major brand
        alone classifies it as HEIC and hands it to the wrong decoder.
        """
        head = self._ftyp(b"mif1", b"mif1", b"avif")
        assert formats.sniff_bytes(head) is formats.AVIF

    def test_plain_avif_is_avif(self):
        assert formats.sniff_bytes(self._ftyp(b"avif", b"mif1")) is formats.AVIF

    def test_an_unknown_brand_is_not_claimed(self):
        assert formats.sniff_bytes(self._ftyp(b"qt  ", b"isom")) is None

    def test_a_declared_size_beyond_the_buffer_does_not_over_read(self):
        """A malformed box must not walk off the end of what was read."""
        head = b"\xff\xff\xff\xff" + b"ftyp" + b"heic" + b"\x00" * 4
        assert formats.sniff_bytes(head) is formats.HEIC

    def test_short_buffer_is_unrecognised(self):
        assert formats.sniff_bytes(b"\x00\x00\x00\x18ftyp") is None


class TestRegistry:
    def test_every_format_has_a_unique_key(self):
        keys = [f.key for f in formats.ALL_FORMATS]
        assert len(keys) == len(set(keys))

    def test_no_extension_is_claimed_by_two_formats(self):
        """Two formats claiming ``.tif`` would make the claimed-format lookup
        depend on declaration order, which is not a decision anyone made."""
        seen: dict[str, str] = {}
        for image_format in formats.ALL_FORMATS:
            for extension in image_format.extensions:
                assert extension not in seen, f"{extension} claimed twice"
                seen[extension] = image_format.key

    def test_every_default_extension_is_among_its_own_extensions(self):
        for image_format in formats.ALL_FORMATS:
            assert image_format.default_extension in image_format.extensions

    def test_extensions_are_lowercase_with_a_dot(self):
        for image_format in formats.ALL_FORMATS:
            for extension in image_format.extensions:
                assert extension.startswith(".") and extension == extension.lower()

    def test_unknown_key_refuses_by_name(self):
        with pytest.raises(KeyError, match="NONSENSE"):
            formats.format_by_key("NONSENSE")

    def test_jpeg_cannot_hold_alpha(self):
        """Load-bearing: the mode adaptation asks the record, not a format name."""
        assert formats.JPEG.supports_alpha is False
        assert formats.PNG.supports_alpha is True

    def test_extension_lookup_is_case_insensitive(self, tmp_path: Path):
        assert formats.format_claimed_by_extension(tmp_path / "A.HEIC") is formats.HEIC
        assert formats.format_claimed_by_extension(tmp_path / "a.JpG") is formats.JPEG
