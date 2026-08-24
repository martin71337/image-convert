"""The interface: that it derives from the engine rather than restating it.

Nothing here asserts on a rendered size or a text width. The offscreen platform
has no fonts on this machine, so its font metrics are not the real Windows
plugin's - an assertion about a pixel would pass or fail for reasons unrelated
to the program. Behaviour and wiring only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from imgconv import formats, pathways
from imgconv.gui.queue_model import QueueEntry, QueueModel, Status, format_bytes
from imgconv.options import CollisionPolicy, OutputLocation
from imgconv.result import ConversionResult, Outcome


@pytest.fixture
def window(qt_application):
    from imgconv.gui.main_window import MainWindow

    made = MainWindow()
    yield made
    made.close()


class TestQueueModel:
    def test_a_file_is_examined_when_it_is_added(self, make_image, quadrants, tmp_path):
        """The Type column must show the real format before anything is run."""
        source = make_image("IMG_1.heic", "HEIF", quadrants)
        model = QueueModel()
        model.add_paths([source])

        entry = model.entry_at(0)
        assert entry.image_format is formats.HEIC
        assert entry.type_text == formats.HEIC.label

    def test_a_mislabelled_file_shows_its_real_type_in_the_queue(
        self, make_image, quadrants, tmp_path
    ):
        """``page2.HEIC``: visible as a JPEG before conversion, not after a failure."""
        source = make_image("page2.HEIC", "JPEG", quadrants)
        model = QueueModel()
        model.add_paths([source])

        entry = model.entry_at(0)
        assert entry.image_format is formats.JPEG
        assert entry.type_text == formats.JPEG.label
        assert any("named" in note for note in entry.notes)

    def test_an_unreadable_file_becomes_an_entry_not_an_exception(self, tmp_path: Path):
        """One locked file in a folder drop must not cost the other ninety-nine."""
        model = QueueModel()
        model.add_paths([tmp_path / "gone.heic"])
        assert model.rowCount() == 1
        assert model.entry_at(0).unreadable is not None

    def test_an_empty_file_is_marked_unreadable(self, tmp_path: Path):
        path = tmp_path / "empty.heic"
        path.write_bytes(b"")
        model = QueueModel()
        model.add_paths([path])
        assert model.entry_at(0).unreadable == "empty file"

    def test_the_same_file_is_not_queued_twice(self, make_image, quadrants, tmp_path):
        source = make_image("IMG_1.heic", "HEIF", quadrants)
        model = QueueModel()
        assert model.add_paths([source]) == 1
        assert model.add_paths([source]) == 0
        assert model.rowCount() == 1

    def test_removing_rows_reindexes(self, make_image, quadrants, tmp_path):
        sources = [make_image(f"IMG_{n}.heic", "HEIF", quadrants) for n in range(3)]
        model = QueueModel()
        model.add_paths(sources)
        model.remove_rows([0])

        assert model.rowCount() == 2
        # A result for the surviving file must still find its row.
        model.apply_result(
            ConversionResult(source=sources[2], outcome=Outcome.CONVERTED)
        )
        assert model.entry_at(1).status is Status.DONE

    def test_a_result_lands_on_the_right_row(self, make_image, quadrants, tmp_path):
        sources = [make_image(f"IMG_{n}.heic", "HEIF", quadrants) for n in range(3)]
        model = QueueModel()
        model.add_paths(sources)
        model.apply_result(ConversionResult(source=sources[1], outcome=Outcome.FAILED))

        assert model.entry_at(0).status is Status.QUEUED
        assert model.entry_at(1).status is Status.FAILED
        assert model.entry_at(2).status is Status.QUEUED

    def test_starting_again_clears_the_previous_run(self, make_image, quadrants, tmp_path):
        """Otherwise a second run shows the first run's Done rows and the user
        cannot tell which results belong to what they just pressed."""
        source = make_image("IMG_1.heic", "HEIF", quadrants)
        model = QueueModel()
        model.add_paths([source])
        model.apply_result(ConversionResult(source=source, outcome=Outcome.CONVERTED))
        model.reset_statuses()

        assert model.entry_at(0).status is Status.QUEUED
        assert model.entry_at(0).result is None


class TestPrediction:
    def test_a_convertible_file_is_predicted_to_convert(self, make_image, quadrants, tmp_path):
        model = QueueModel()
        model.add_paths([make_image("IMG_1.heic", "HEIF", quadrants)])
        model.plan_for_target(formats.JPEG)
        assert model.entry_at(0).status is Status.QUEUED

    def test_a_file_already_the_target_is_predicted_as_such(
        self, make_image, quadrants, tmp_path
    ):
        model = QueueModel()
        model.add_paths([make_image("IMG_1.jpg", "JPEG", quadrants)])
        model.plan_for_target(formats.JPEG)
        assert model.entry_at(0).status is Status.WILL_SKIP

    def test_a_file_with_no_pathway_is_predicted_as_such(
        self, make_image, quadrants, tmp_path
    ):
        model = QueueModel()
        model.add_paths([make_image("a.gif", "GIF", quadrants)])
        model.plan_for_target(formats.JPEG)
        assert model.entry_at(0).status is Status.NO_PATHWAY

    def test_a_prediction_never_overwrites_a_real_outcome(
        self, make_image, quadrants, tmp_path
    ):
        """A completed run's results must survive the user changing the target."""
        source = make_image("IMG_1.heic", "HEIF", quadrants)
        model = QueueModel()
        model.add_paths([source])
        model.apply_result(ConversionResult(source=source, outcome=Outcome.CONVERTED))

        model.plan_for_target(formats.PNG)
        assert model.entry_at(0).status is Status.DONE

    def test_predictions_follow_the_registry(self, make_image, quadrants, tmp_path):
        """Derived, not restated: the prediction consults the pathway registry."""
        model = QueueModel()
        model.add_paths([make_image("IMG_1.heic", "HEIF", quadrants)])
        for target in pathways.targets_for(formats.HEIC):
            model.plan_for_target(target)
            assert model.entry_at(0).status is Status.QUEUED, target


class TestDerivedInterface:
    def test_the_target_list_comes_from_the_registry(self, window, make_image, quadrants, tmp_path):
        """THE property that makes a new pathway free.

        The dropdown's contents are the registry's answer, not a list typed into
        the window. If this fails, something has started restating the registry.
        """
        window._add([make_image("IMG_1.heic", "HEIF", quadrants)])

        offered = [window.target_combo.itemData(i) for i in range(window.target_combo.count())]
        assert tuple(offered) == pathways.common_targets((formats.HEIC,))

    def test_a_mixed_real_world_folder_offers_targets(
        self, window, make_image, quadrants, tmp_path
    ):
        """The regression that made a Downloads folder unusable.

        A folder holding HEICs, JPEGs, PNGs and TIFFs together must still offer
        somewhere to convert to; when it offered nothing, Convert stayed greyed
        out and the program did nothing at all for its main use case.
        """
        for name, pillow_id in (
            ("a.heic", "HEIF"),
            ("b.jpg", "JPEG"),
            ("c.png", "PNG"),
            ("d.tif", "TIFF"),
        ):
            make_image(f"mixed/{name}", pillow_id, quadrants)

        window._add([tmp_path / "mixed"])

        offered = [window.target_combo.itemData(i) for i in range(window.target_combo.count())]
        assert formats.JPEG in offered
        assert window.convert_button.isEnabled()

    def test_one_unconvertible_file_disables_conversion(
        self, window, make_image, quadrants, tmp_path
    ):
        make_image("mixed/a.heic", "HEIF", quadrants)
        make_image("mixed/b.gif", "GIF", quadrants)
        window._add([tmp_path / "mixed"])

        assert window.target_combo.count() == 0
        assert not window.convert_button.isEnabled()

    def test_the_quality_slider_is_greyed_for_a_lossless_target(
        self, window, make_image, quadrants, tmp_path
    ):
        """A control that does nothing is worse than no control."""
        window._add([make_image("IMG_1.heic", "HEIF", quadrants)])

        window.target_combo.setCurrentIndex(window.target_combo.findData(formats.JPEG))
        assert window.quality_slider.isEnabled()

        window.target_combo.setCurrentIndex(window.target_combo.findData(formats.PNG))
        assert not window.quality_slider.isEnabled()

    def test_the_collision_dropdown_carries_the_policies_themselves(self, window):
        """The enum member is what is stored, so relabelling cannot change
        behaviour."""
        carried = {
            window.collision_combo.itemData(i)
            for i in range(window.collision_combo.count())
        }
        assert carried == set(CollisionPolicy)


class TestOptionsFromTheWindow:
    def test_the_defaults_match_the_engine_s_defaults(self, window, make_image, quadrants, tmp_path):
        window._add([make_image("IMG_1.heic", "HEIF", quadrants)])
        options = window.current_options()

        assert options.output_location is OutputLocation.SUBFOLDER
        assert options.collision is CollisionPolicy.SUFFIX
        assert options.keep_metadata is True
        assert options.convert_to_srgb is True
        assert options.auto_rotate is True
        assert options.quality == window.quality_slider.value()

    def test_choosing_a_folder_is_carried_through(self, window, make_image, quadrants, tmp_path):
        window._add([make_image("IMG_1.heic", "HEIF", quadrants)])
        window.chosen_radio.setChecked(True)
        window.folder_edit.setText(str(tmp_path / "elsewhere"))

        options = window.current_options()
        assert options.output_location is OutputLocation.CHOSEN
        assert options.output_folder == tmp_path / "elsewhere"

    def test_a_chosen_location_with_no_folder_is_caught_by_validate(
        self, window, make_image, quadrants, tmp_path
    ):
        window._add([make_image("IMG_1.heic", "HEIF", quadrants)])
        window.chosen_radio.setChecked(True)
        window.folder_edit.setText("")

        with pytest.raises(ValueError):
            window.current_options().validate()

    def test_unchecking_the_boxes_reaches_the_options(
        self, window, make_image, quadrants, tmp_path
    ):
        window._add([make_image("IMG_1.heic", "HEIF", quadrants)])
        window.metadata_check.setChecked(False)
        window.srgb_check.setChecked(False)
        window.rotate_check.setChecked(False)

        options = window.current_options()
        assert options.keep_metadata is False
        assert options.convert_to_srgb is False
        assert options.auto_rotate is False


class TestEndToEndThroughTheWindow:
    def test_the_window_converts_the_same_way_the_engine_does(
        self, window, make_image, quadrants, tmp_path
    ):
        """The interface must not be able to produce a different conversion.

        It builds options and calls the same engine a script would; this runs
        the window's own options through that engine and checks a real file
        comes out.
        """
        from imgconv import job

        source = make_image("IMG_1.heic", "HEIF", quadrants)
        window._add([source])
        window.chosen_radio.setChecked(True)
        window.folder_edit.setText(str(tmp_path / "out"))

        report = job.run(window.model.convertible_paths(), window.current_options())

        assert len(report.converted) == 1
        assert (tmp_path / "out" / "IMG_1.jpg").is_file()


class TestFormatting:
    @pytest.mark.parametrize(
        "count,expected",
        [(None, ""), (0, "0 B"), (512, "512 B"), (2048, "2 KB"), (1_979_299, "1.9 MB")],
    )
    def test_sizes_read_the_way_a_person_expects(self, count, expected):
        assert format_bytes(count) == expected
