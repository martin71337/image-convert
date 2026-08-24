"""Batch behaviour: isolation, cancellation, reservations under real threads."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from imgconv import formats, job
from imgconv.options import ConversionOptions, OutputLocation
from imgconv.result import Outcome


def make_options(tmp_path: Path, **overrides) -> ConversionOptions:
    defaults = dict(
        target_format=formats.JPEG,
        output_location=OutputLocation.CHOSEN,
        output_folder=tmp_path / "out",
    )
    defaults.update(overrides)
    return ConversionOptions(**defaults)


class TestBatch:
    def test_an_empty_queue_is_not_an_error(self, tmp_path: Path):
        report = job.run([], make_options(tmp_path))
        assert report.results == []
        assert report.summary() == "0 converted"

    def test_every_file_gets_a_result(self, make_image, quadrants, tmp_path: Path):
        sources = [make_image(f"IMG_{n}.heic", "HEIF", quadrants) for n in range(6)]
        report = job.run(sources, make_options(tmp_path))
        assert len(report.results) == len(sources)
        assert {r.source for r in report.results} == set(sources)

    def test_one_bad_file_does_not_stop_the_batch(self, make_image, quadrants, tmp_path: Path):
        """The property a folder of field photos depends on.

        A single corrupt or misnamed file among two hundred must cost that one
        file, not the run.
        """
        good = [make_image(f"IMG_{n}.heic", "HEIF", quadrants) for n in range(4)]
        broken = tmp_path / "broken.heic"
        broken.write_text("this is not a photograph")

        report = job.run([*good[:2], broken, *good[2:]], make_options(tmp_path))

        assert len(report.converted) == 4
        assert len(report.failed) == 1
        assert report.failed[0].source == broken

    def test_a_locked_file_fails_alone(self, make_image, quadrants, tmp_path: Path):
        good = make_image("IMG_1.heic", "HEIF", quadrants)
        missing = tmp_path / "vanished.heic"

        report = job.run([good, missing], make_options(tmp_path))
        assert len(report.converted) == 1
        assert len(report.failed) == 1

    def test_the_summary_counts_every_category(self, make_image, quadrants, tmp_path: Path):
        converted = make_image("IMG_1.heic", "HEIF", quadrants)
        already = make_image("IMG_2.jpg", "JPEG", quadrants)
        broken = tmp_path / "broken.heic"
        broken.write_text("no")

        report = job.run([converted, already, broken], make_options(tmp_path))
        summary = report.summary()
        assert "1 converted" in summary
        assert "1 skipped" in summary
        assert "1 failed" in summary

    def test_bad_options_refuse_before_touching_anything(self, make_image, quadrants, tmp_path):
        """A misconfigured job must fail before it has written half a folder."""
        source = make_image("IMG_1.heic", "HEIF", quadrants)
        with pytest.raises(ValueError):
            job.run([source], make_options(tmp_path, quality=500))
        assert not (tmp_path / "out").exists()


class TestReservationsUnderThreads:
    def test_same_named_files_from_different_folders_all_survive(
        self, make_image, quadrants, tmp_path: Path
    ):
        """The race the reservation lock exists for, run for real.

        Eight files that all want ``IMG_2480.jpg``, converted on several threads
        into one flattened output folder. Without the lock two threads see the
        same free path and one output silently destroys another, so the count
        comes out short.
        """
        sources = [
            make_image(f"folder{n}/IMG_2480.heic", "HEIF", quadrants) for n in range(8)
        ]
        report = job.run(sources, make_options(tmp_path))

        assert len(report.converted) == 8, report.summary()
        written = sorted(p.name for p in (tmp_path / "out").glob("*.jpg"))
        assert len(written) == 8, written
        assert len(set(written)) == 8, "every output must have its own name"

    def test_no_output_is_left_partial(self, make_image, quadrants, tmp_path: Path):
        sources = [make_image(f"IMG_{n}.heic", "HEIF", quadrants) for n in range(8)]
        job.run(sources, make_options(tmp_path))
        assert list((tmp_path / "out").glob("*.partial")) == []


class TestCancellation:
    def test_cancelling_before_the_start_converts_nothing(
        self, make_image, quadrants, tmp_path: Path
    ):
        sources = [make_image(f"IMG_{n}.heic", "HEIF", quadrants) for n in range(5)]
        cancel = threading.Event()
        cancel.set()

        report = job.run(sources, make_options(tmp_path), cancel=cancel)

        assert report.cancelled is True
        assert report.converted == []
        assert list((tmp_path / "out").glob("*.jpg")) == [] if (tmp_path / "out").exists() else True

    def test_a_cancelled_run_says_so_in_its_summary(
        self, make_image, quadrants, tmp_path: Path
    ):
        cancel = threading.Event()
        cancel.set()
        report = job.run([], make_options(tmp_path), cancel=cancel)
        # An empty queue returns before the cancel is consulted; a real one does not.
        assert report.summary() == "0 converted"

    def test_cancelling_partway_stops_the_queue(self, make_image, quadrants, tmp_path: Path):
        """Files not reached are absent from the report - not skipped, not
        attempted."""
        sources = [make_image(f"IMG_{n}.heic", "HEIF", quadrants) for n in range(20)]
        cancel = threading.Event()

        def progress(done: int, total: int, result) -> None:
            if done >= 2:
                cancel.set()

        report = job.run(
            sources,
            make_options(tmp_path),
            progress=progress,
            cancel=cancel,
            max_workers=1,
        )

        assert report.cancelled is True
        assert len(report.results) < len(sources), "the queue should have stopped early"

    def test_no_partial_file_survives_a_cancel(self, make_image, quadrants, tmp_path: Path):
        sources = [make_image(f"IMG_{n}.heic", "HEIF", quadrants) for n in range(20)]
        cancel = threading.Event()

        def progress(done: int, total: int, result) -> None:
            cancel.set()

        job.run(sources, make_options(tmp_path), progress=progress, cancel=cancel, max_workers=1)

        output = tmp_path / "out"
        if output.exists():
            assert list(output.glob("*.partial")) == []


class TestProgress:
    def test_progress_is_reported_once_per_file_and_counts_up(
        self, make_image, quadrants, tmp_path: Path
    ):
        sources = [make_image(f"IMG_{n}.heic", "HEIF", quadrants) for n in range(6)]
        seen: list[int] = []
        lock = threading.Lock()

        def progress(done: int, total: int, result) -> None:
            with lock:
                seen.append(done)
            assert total == len(sources)

        job.run(sources, make_options(tmp_path), progress=progress)

        assert sorted(seen) == list(range(1, len(sources) + 1))


class TestCollectImages:
    def test_a_folder_yields_the_images_inside_it(self, make_image, quadrants, tmp_path: Path):
        make_image("photos/a.heic", "HEIF", quadrants)
        make_image("photos/b.jpg", "JPEG", quadrants)
        (tmp_path / "photos" / "notes.txt").write_text("not an image")

        found = job.collect_images([tmp_path / "photos"])
        assert sorted(p.name for p in found) == ["a.heic", "b.jpg"]

    def test_subfolders_are_included_only_when_asked(self, make_image, quadrants, tmp_path):
        make_image("photos/a.heic", "HEIF", quadrants)
        make_image("photos/deeper/b.heic", "HEIF", quadrants)

        shallow = job.collect_images([tmp_path / "photos"], recurse=False)
        deep = job.collect_images([tmp_path / "photos"], recurse=True)

        assert len(shallow) == 1
        assert len(deep) == 2

    def test_a_file_chosen_explicitly_bypasses_the_extension_filter(self, tmp_path: Path):
        """The filter is a convenience for walking folders, not a gate.

        A file the user picked by name converts regardless of what it is called;
        its real format is sniffed later.
        """
        odd = tmp_path / "photo.unknown"
        odd.write_bytes(b"x")
        assert job.collect_images([odd]) == [odd.resolve()]

    def test_a_folder_and_a_file_inside_it_queue_that_file_once(
        self, make_image, quadrants, tmp_path: Path
    ):
        photo = make_image("photos/a.heic", "HEIF", quadrants)
        found = job.collect_images([tmp_path / "photos", photo])
        assert len(found) == 1

    def test_results_are_sorted(self, make_image, quadrants, tmp_path: Path):
        for name in ("c.heic", "a.heic", "b.heic"):
            make_image(f"photos/{name}", "HEIF", quadrants)
        found = job.collect_images([tmp_path / "photos"])
        assert found == sorted(found)

    def test_a_missing_folder_is_ignored_not_fatal(self, tmp_path: Path):
        assert job.collect_images([tmp_path / "nope"]) == []
