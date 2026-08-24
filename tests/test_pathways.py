"""The registry, and the properties that make it the scalability seam."""

from __future__ import annotations

import pytest

from imgconv import formats, pathways
from imgconv.pathways import PathwayError


class TestLookup:
    def test_the_headline_pathway_exists(self):
        pathway = pathways.pathway_for(formats.HEIC, formats.JPEG)
        assert pathway.source is formats.HEIC
        assert pathway.target is formats.JPEG
        assert pathway.lossy is True

    def test_an_unregistered_pair_refuses_by_name(self):
        """Never a silent pass-through.

        A conversion the program cannot do must say so, naming both formats -
        falling back to "open it and save it anyway" is how a file ends up being
        something other than what its extension claims.
        """
        with pytest.raises(PathwayError) as raised:
            pathways.pathway_for(formats.AVIF, formats.JPEG)
        message = str(raised.value)
        assert "AVIF" in message
        assert "JPEG" in message

    def test_the_refusal_says_what_is_possible_instead(self):
        with pytest.raises(PathwayError) as raised:
            pathways.pathway_for(formats.HEIC, formats.TIFF)
        assert "JPEG" in str(raised.value), "should offer the targets that do exist"

    def test_a_format_with_no_pathways_says_so(self):
        with pytest.raises(PathwayError, match="cannot be converted"):
            pathways.pathway_for(formats.GIF, formats.JPEG)

    def test_lossless_targets_are_marked_lossless(self):
        """Drives whether the quality slider means anything."""
        assert pathways.pathway_for(formats.HEIC, formats.PNG).lossy is False


class TestReachability:
    def test_a_format_is_reachable_from_itself(self):
        """The case whose absence made a mixed folder offer nothing.

        A queue holding JPEGs can target JPEG: those files are already what was
        asked for and the run records them as skipped. Excluding this made the
        intersection across a real Downloads folder - which always holds a mix -
        come out empty, so the dropdown offered no target at all and Convert
        stayed greyed out.
        """
        assert formats.JPEG in pathways.reachable_targets(formats.JPEG)
        assert formats.PNG in pathways.reachable_targets(formats.PNG)

    def test_a_format_that_cannot_be_produced_is_not_reachable_from_itself(self):
        """HEIC is readable but never written, so it is not a target."""
        assert formats.HEIC not in pathways.reachable_targets(formats.HEIC)

    def test_targets_for_excludes_the_identity(self):
        """``targets_for`` is about pathways; ``reachable_targets`` is about
        outcomes. Conflating them would register a HEIC-to-HEIC conversion that
        does not exist."""
        assert formats.JPEG not in pathways.targets_for(formats.JPEG)


class TestCommonTargets:
    def test_a_mixed_real_world_folder_offers_jpeg_and_png(self):
        """The exact format mix found in the owner's Downloads folder."""
        queued = (formats.PNG, formats.TIFF, formats.JPEG, formats.WEBP, formats.HEIC)
        assert pathways.common_targets(queued) == (formats.JPEG, formats.PNG)

    def test_a_pure_heic_queue_offers_both(self):
        assert pathways.common_targets((formats.HEIC,)) == (formats.JPEG, formats.PNG)

    def test_one_unconvertible_file_removes_every_target(self):
        """Intersection, not union: offering a target only some files can reach
        would guarantee failures the dropdown gives no warning of."""
        assert pathways.common_targets((formats.HEIC, formats.GIF)) == ()

    def test_an_empty_queue_offers_nothing(self):
        assert pathways.common_targets(()) == ()

    def test_duplicates_do_not_change_the_answer(self):
        once = pathways.common_targets((formats.HEIC,))
        twice = pathways.common_targets((formats.HEIC, formats.HEIC))
        assert once == twice

    def test_order_is_registry_order_not_queue_order(self):
        """The dropdown must not reorder itself because files arrived differently."""
        forwards = pathways.common_targets((formats.HEIC, formats.TIFF))
        backwards = pathways.common_targets((formats.TIFF, formats.HEIC))
        assert forwards == backwards


class TestRegistryShape:
    def test_no_pair_is_registered_twice(self):
        keys = [p.key for p in pathways.ALL_PATHWAYS]
        assert len(keys) == len(set(keys))

    def test_no_pathway_converts_a_format_to_itself(self):
        """An identity pathway would make the "already that format" skip
        unreachable and re-encode a JPEG as a JPEG, losing quality for nothing."""
        for pathway in pathways.ALL_PATHWAYS:
            assert pathway.source is not pathway.target

    def test_every_target_can_actually_be_written(self):
        for pathway in pathways.ALL_PATHWAYS:
            assert pathway.target.pillow_id is not None

    def test_every_readable_format_reaches_both_targets(self):
        """The matrix is complete on purpose.

        A half-filled matrix is what makes a mixed folder offer nothing, since
        the offered targets are the ones every queued file can reach.
        """
        for source in pathways.source_formats():
            reachable = set(pathways.reachable_targets(source))
            assert {formats.JPEG, formats.PNG} <= reachable, source.key

    def test_the_label_is_derived_from_the_formats(self):
        """A stored label would drift from the pair it names."""
        pathway = pathways.pathway_for(formats.HEIC, formats.JPEG)
        assert pathway.label == f"{formats.HEIC.label} to {formats.JPEG.label}"


class TestExtensibility:
    """The property the whole module exists for: a new pathway needs no other edit."""

    def test_adding_a_pathway_makes_it_offered(self, monkeypatch):
        """Register a seventh pathway and confirm the derived views follow.

        This is the seam's contract. If this test needs editing to accommodate a
        new pathway, the registry has stopped being the single source and
        something else has started restating it.
        """
        invented = pathways.Pathway(source=formats.GIF, target=formats.PNG, lossy=False)
        extended = pathways.ALL_PATHWAYS + (invented,)

        monkeypatch.setattr(pathways, "ALL_PATHWAYS", extended)
        monkeypatch.setattr(
            pathways, "_BY_KEY", {p.key: p for p in extended}
        )
        monkeypatch.setattr(
            pathways,
            "_TARGET_FORMATS",
            tuple(dict.fromkeys(p.target for p in extended)),
        )

        assert formats.PNG in pathways.targets_for(formats.GIF)
        assert pathways.pathway_for(formats.GIF, formats.PNG) is invented
        assert formats.GIF in pathways.source_formats()
        # And a queue of GIFs now offers a target where before it offered none.
        assert pathways.common_targets((formats.GIF,)) == (formats.PNG,)
