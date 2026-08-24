"""The pathway registry: which conversions this program knows how to do.

**This module is the scalability seam.** A pathway is a record keyed by
``(source format, target format)``, and :data:`ALL_PATHWAYS` is a declared
tuple. Adding HEIC -> PDF, or a resized-copy pathway, or a watermarked one, is a
new record here plus whatever function it names - not a change to the job
runner, not a change to the interface, and not a new branch in a conversion
function that grows a new ``if`` per format pair.

Two properties are load-bearing and are pinned by the suite:

* **The interface is derived from this table.** ``gui`` builds its "Convert to"
  dropdown from :func:`targets_for`, so a seventh record appears on screen with
  no GUI edit. Nothing restates the list of pathways.
* **An unregistered pair refuses by name.** :func:`pathway_for` raises rather
  than falling back to "just open it and save it", because a silent pass-through
  is how a program ends up writing a file that is not what its extension says.
"""

from __future__ import annotations

from dataclasses import dataclass

from imgconv.formats import BMP, HEIC, JPEG, PNG, TIFF, WEBP, ImageFormat


class PathwayError(Exception):
    """No registered pathway converts the requested pair of formats."""


@dataclass(frozen=True)
class Pathway:
    """One conversion this program supports.

    ``lossy`` decides whether the quality setting means anything for this
    pathway; the interface greys the slider when it does not, rather than
    offering a control that does nothing.
    """

    source: ImageFormat
    target: ImageFormat
    lossy: bool

    @property
    def label(self) -> str:
        """Derived, never stored - a stored label drifts from the pair it
        names the moment a format is relabelled."""
        return f"{self.source.label} to {self.target.label}"

    @property
    def key(self) -> tuple[str, str]:
        return (self.source.key, self.target.key)


# ---------------------------------------------------------------------------
# The registry. Declaration order is the order the interface offers targets in,
# so the first target registered for a source format is the one it preselects.
# ---------------------------------------------------------------------------

ALL_PATHWAYS: tuple[Pathway, ...] = (
    # The reason the program exists: iPhone field photos into something a
    # report, a browser and Word can all actually place.
    Pathway(source=HEIC, target=JPEG, lossy=True),
    Pathway(source=HEIC, target=PNG, lossy=False),
    # Scanned and downloaded material, which arrives as TIFF far more often
    # than anyone would like.
    Pathway(source=TIFF, target=JPEG, lossy=True),
    Pathway(source=TIFF, target=PNG, lossy=False),
    Pathway(source=PNG, target=JPEG, lossy=True),
    Pathway(source=JPEG, target=PNG, lossy=False),
    Pathway(source=WEBP, target=JPEG, lossy=True),
    Pathway(source=WEBP, target=PNG, lossy=False),
    Pathway(source=BMP, target=JPEG, lossy=True),
    Pathway(source=BMP, target=PNG, lossy=False),
)
"""The matrix is deliberately complete rather than minimal: every format this
program reads can become either JPEG or PNG. A half-filled matrix is what makes
a mixed folder - which is what a Downloads folder always is - offer the user
nothing at all, because the targets on offer are the ones EVERY queued file can
reach (see :func:`common_targets`)."""

_BY_KEY = {pathway.key: pathway for pathway in ALL_PATHWAYS}

_TARGET_FORMATS = tuple(dict.fromkeys(p.target for p in ALL_PATHWAYS))
"""Every format that appears as a target. A format not in here cannot be
produced at all, so it can never be offered."""


def pathway_for(source: ImageFormat, target: ImageFormat) -> Pathway:
    """The registered pathway for this pair, or :class:`PathwayError`.

    The refusal names both formats and lists what the source format *can* be
    converted to, because the common case for reaching it is a queue holding one
    file of an unexpected type, and the useful answer is what to do with it.
    """
    try:
        return _BY_KEY[(source.key, target.key)]
    except KeyError:
        available = targets_for(source)
        if available:
            offer = "can be converted to " + ", ".join(f.label for f in available)
        else:
            offer = "cannot be converted by this program"
        raise PathwayError(
            f"there is no pathway from {source.label} to {target.label}. "
            f"{source.label} {offer}."
        ) from None


def targets_for(source: ImageFormat) -> tuple[ImageFormat, ...]:
    """Every format ``source`` can become, in registry order.

    THE source of the interface's target list. Returns an empty tuple for a
    format with no pathways, which is a real answer and not an error.
    """
    return tuple(p.target for p in ALL_PATHWAYS if p.source is source)


def reachable_targets(source: ImageFormat) -> tuple[ImageFormat, ...]:
    """Every format a file of type ``source`` can END UP as.

    Wider than :func:`targets_for` by exactly one case: a format is reachable
    from itself. Asking a queue of JPEGs to produce JPEGs is not an error and
    not a missing pathway - those files are already what was asked for, and the
    conversion records them as skipped. Leaving that case out is what made a
    folder holding both HEICs and JPEGs offer no targets at all, since no single
    format could be reached by every file in it.
    """
    targets = list(targets_for(source))
    if source in _TARGET_FORMATS and source not in targets:
        targets.append(source)
    # Registry order, so the interface is stable from run to run.
    return tuple(fmt for fmt in _TARGET_FORMATS if fmt in targets)


def common_targets(sources: object) -> tuple[ImageFormat, ...]:
    """Targets reachable from *every* one of ``sources``, in registry order.

    What the interface offers for a mixed queue. The intersection rather than
    the union is the honest answer: offering a target that only some of the
    queued files can reach means offering a conversion that is guaranteed to
    produce failures, and the dropdown gives the user no way to see that coming.

    An empty ``sources`` yields an empty tuple - nothing is selected, so nothing
    is offered.
    """
    formats = list(dict.fromkeys(sources))  # de-duplicated, order preserved
    if not formats:
        return ()

    shared = set.intersection(*(set(reachable_targets(fmt)) for fmt in formats))
    return tuple(fmt for fmt in _TARGET_FORMATS if fmt in shared)


def source_formats() -> tuple[ImageFormat, ...]:
    """Every format this program can read, in registry order, de-duplicated.

    Used for the file dialog's "images this program converts" filter.
    """
    seen: list[ImageFormat] = []
    for pathway in ALL_PATHWAYS:
        if pathway.source not in seen:
            seen.append(pathway.source)
    return tuple(seen)
