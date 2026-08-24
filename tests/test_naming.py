"""Output paths, and the rule that nothing is ever silently overwritten."""

from __future__ import annotations

from pathlib import Path

import pytest

from imgconv import formats
from imgconv.naming import destination_folder, output_path_for, would_convert_onto_itself
from imgconv.options import SUBFOLDER_NAME, CollisionPolicy, ConversionOptions, OutputLocation


def make_options(**overrides) -> ConversionOptions:
    defaults = dict(target_format=formats.JPEG)
    defaults.update(overrides)
    return ConversionOptions(**defaults)


class TestDestinationFolder:
    def test_subfolder_sits_beside_the_source(self, tmp_path: Path):
        source = tmp_path / "photos" / "IMG_2480.HEIC"
        folder = destination_folder(source, make_options())
        assert folder == tmp_path / "photos" / SUBFOLDER_NAME

    def test_a_queue_spanning_folders_keeps_outputs_with_their_origins(self, tmp_path: Path):
        """The reason the subfolder default is per-source rather than one folder."""
        options = make_options()
        first = destination_folder(tmp_path / "march" / "a.heic", options)
        second = destination_folder(tmp_path / "may" / "b.heic", options)
        assert first != second

    def test_alongside_is_the_source_folder(self, tmp_path: Path):
        source = tmp_path / "photos" / "IMG_2480.HEIC"
        assert destination_folder(source, make_options(
            output_location=OutputLocation.ALONGSIDE
        )) == tmp_path / "photos"

    def test_a_chosen_folder_flattens_everything_into_it(self, tmp_path: Path):
        chosen = tmp_path / "out"
        options = make_options(output_location=OutputLocation.CHOSEN, output_folder=chosen)
        assert destination_folder(tmp_path / "march" / "a.heic", options) == chosen
        assert destination_folder(tmp_path / "may" / "b.heic", options) == chosen


class TestNaming:
    def test_the_extension_comes_from_the_target_format(self, tmp_path: Path):
        source = tmp_path / "IMG_2480.HEIC"
        assert output_path_for(source, formats.JPEG, make_options()).name == "IMG_2480.jpg"
        assert output_path_for(source, formats.PNG, make_options()).name == "IMG_2480.png"

    def test_a_name_with_dots_keeps_all_but_the_last(self, tmp_path: Path):
        source = tmp_path / "site.survey.2026.heic"
        assert output_path_for(source, formats.JPEG, make_options()).name == (
            "site.survey.2026.jpg"
        )


class TestCollisionPolicies:
    def _existing(self, tmp_path: Path) -> Path:
        source = tmp_path / "IMG_2480.HEIC"
        source.write_bytes(b"x")
        taken = tmp_path / SUBFOLDER_NAME / "IMG_2480.jpg"
        taken.parent.mkdir(parents=True, exist_ok=True)
        taken.write_bytes(b"already here")
        return source

    def test_suffix_counts_up_and_never_overwrites(self, tmp_path: Path):
        source = self._existing(tmp_path)
        chosen = output_path_for(source, formats.JPEG, make_options())
        assert chosen.name == "IMG_2480_1.jpg"
        assert (tmp_path / SUBFOLDER_NAME / "IMG_2480.jpg").read_bytes() == b"already here"

    def test_suffix_keeps_counting_past_the_first(self, tmp_path: Path):
        source = self._existing(tmp_path)
        (tmp_path / SUBFOLDER_NAME / "IMG_2480_1.jpg").write_bytes(b"also here")
        chosen = output_path_for(source, formats.JPEG, make_options())
        assert chosen.name == "IMG_2480_2.jpg"

    def test_the_counter_goes_on_the_stem_not_after_the_extension(self, tmp_path: Path):
        """``IMG_2480_1.jpg``, never ``IMG_2480.jpg_1`` - the file has to stay
        recognisable as a JPEG to Windows, Word and CAD."""
        source = self._existing(tmp_path)
        assert output_path_for(source, formats.JPEG, make_options()).suffix == ".jpg"

    def test_skip_returns_nothing(self, tmp_path: Path):
        source = self._existing(tmp_path)
        options = make_options(collision=CollisionPolicy.SKIP)
        assert output_path_for(source, formats.JPEG, options) is None

    def test_overwrite_returns_the_original_name(self, tmp_path: Path):
        source = self._existing(tmp_path)
        options = make_options(collision=CollisionPolicy.OVERWRITE)
        assert output_path_for(source, formats.JPEG, options).name == "IMG_2480.jpg"

    def test_no_collision_uses_the_plain_name_under_every_policy(self, tmp_path: Path):
        source = tmp_path / "IMG_9999.HEIC"
        source.write_bytes(b"x")
        for policy in CollisionPolicy:
            chosen = output_path_for(source, formats.JPEG, make_options(collision=policy))
            assert chosen is not None and chosen.name == "IMG_9999.jpg", policy


class TestBatchReservations:
    """Two sources that would land on the same output path.

    Reachable whenever a chosen output folder flattens two source folders that
    each hold an ``IMG_2480.HEIC``. Neither output exists at the moment its path
    is chosen, so without reservations both look free and the second conversion
    silently destroys the first.
    """

    def test_two_sources_with_the_same_name_get_different_outputs(self, tmp_path: Path):
        out = tmp_path / "out"
        options = make_options(output_location=OutputLocation.CHOSEN, output_folder=out)
        reserved: set[Path] = set()

        first = output_path_for(tmp_path / "march" / "IMG_2480.HEIC", formats.JPEG, options, reserved)
        second = output_path_for(tmp_path / "may" / "IMG_2480.HEIC", formats.JPEG, options, reserved)

        assert first is not None and second is not None
        assert first != second
        assert first.name == "IMG_2480.jpg"
        assert second.name == "IMG_2480_1.jpg"

    def test_the_path_is_claimed_by_the_function_that_hands_it_out(self, tmp_path: Path):
        """Choosing and claiming must be indivisible.

        If the caller recorded the path instead, another thread could run in
        between and be handed the same one - which is the whole race the
        reservation set exists to prevent.
        """
        out = tmp_path / "out"
        options = make_options(output_location=OutputLocation.CHOSEN, output_folder=out)
        reserved: set[Path] = set()

        chosen = output_path_for(tmp_path / "a" / "x.heic", formats.JPEG, options, reserved)
        assert chosen in reserved

    def test_overwrite_still_will_not_clobber_this_batch_s_own_output(self, tmp_path: Path):
        """Overwriting a file the user already had is what they asked for.
        Overwriting one this same run produced a second ago is not."""
        out = tmp_path / "out"
        options = make_options(
            output_location=OutputLocation.CHOSEN,
            output_folder=out,
            collision=CollisionPolicy.OVERWRITE,
        )
        reserved: set[Path] = set()

        first = output_path_for(tmp_path / "march" / "IMG_2480.HEIC", formats.JPEG, options, reserved)
        second = output_path_for(tmp_path / "may" / "IMG_2480.HEIC", formats.JPEG, options, reserved)
        assert first != second

    def test_skip_respects_reservations_too(self, tmp_path: Path):
        out = tmp_path / "out"
        options = make_options(
            output_location=OutputLocation.CHOSEN,
            output_folder=out,
            collision=CollisionPolicy.SKIP,
        )
        reserved: set[Path] = set()
        assert output_path_for(tmp_path / "a" / "x.heic", formats.JPEG, options, reserved)
        assert output_path_for(tmp_path / "b" / "x.heic", formats.JPEG, options, reserved) is None


class TestSelfOverwrite:
    def test_a_path_is_recognised_as_itself(self, tmp_path: Path):
        source = tmp_path / "photo.jpg"
        source.write_bytes(b"x")
        assert would_convert_onto_itself(source, tmp_path / "photo.jpg") is True

    def test_different_paths_are_not(self, tmp_path: Path):
        source = tmp_path / "photo.heic"
        source.write_bytes(b"x")
        assert would_convert_onto_itself(source, tmp_path / "photo.jpg") is False


class TestOptionValidation:
    def test_a_chosen_location_without_a_folder_refuses(self):
        options = make_options(output_location=OutputLocation.CHOSEN)
        with pytest.raises(ValueError, match="no folder"):
            options.validate()

    def test_a_folder_with_a_derived_location_refuses(self, tmp_path: Path):
        """Two contradictory instructions; guessing which was meant is worse
        than saying so."""
        options = make_options(output_location=OutputLocation.SUBFOLDER, output_folder=tmp_path)
        with pytest.raises(ValueError, match="not what was meant"):
            options.validate()

    @pytest.mark.parametrize("quality", [0, 39, 101, 200, -5])
    def test_quality_outside_the_range_refuses(self, quality: int):
        with pytest.raises(ValueError, match="quality"):
            make_options(quality=quality).validate()

    @pytest.mark.parametrize("quality", [40, 90, 100])
    def test_quality_inside_the_range_is_accepted(self, quality: int):
        make_options(quality=quality).validate()
