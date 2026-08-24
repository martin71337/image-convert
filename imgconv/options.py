"""What the user asked for, as one record.

:class:`ConversionOptions` is the whole of the interface's decision. The GUI
builds one and hands it to :func:`imgconv.job.run`; nothing below the GUI reads
a widget, and nothing in the GUI decides how a pixel is written. That split is
what lets the engine be driven from a test, a script or a future command line
without any of them re-implementing a policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from imgconv.formats import ImageFormat


class OutputLocation(Enum):
    """Where converted files are written."""

    SUBFOLDER = "subfolder"
    """A ``converted`` folder beside each source file. The default: originals
    stay untouched, and a queue spanning several source folders keeps its
    outputs sorted by where they came from."""

    ALONGSIDE = "alongside"
    """The source file's own folder."""

    CHOSEN = "chosen"
    """One folder the user picked. Every output lands there, flattened, which is
    the only mode in which two sources can collide on a basename."""


class CollisionPolicy(Enum):
    """What to do when the output path already exists.

    There is deliberately no "ask me" member. A batch of two hundred photos that
    stops on the eleventh to raise a dialog is worse than either answer, and the
    per-file result records what happened either way.
    """

    SUFFIX = "suffix"
    """Write ``IMG_2480_1.jpg``. The default: nothing is lost and nothing is
    silently overwritten."""

    SKIP = "skip"
    """Leave the existing file alone and record the source as skipped."""

    OVERWRITE = "overwrite"
    """Replace it. Chosen explicitly, never assumed."""


SUBFOLDER_NAME = "converted"
"""The folder :data:`OutputLocation.SUBFOLDER` creates. One authoritative
spelling: the naming layer creates it and the GUI's "open output folder" button
resolves it through the same constant."""

DEFAULT_QUALITY = 90
"""JPEG quality. 90 is visually indistinguishable from the HEIC source at normal
viewing sizes while producing files a report can carry; it is also the threshold
at and above which chroma subsampling is disabled (see the imaging backend), so
fine detail and text in a field photo stay sharp."""

MIN_QUALITY = 40
MAX_QUALITY = 100


@dataclass(frozen=True)
class ConversionOptions:
    """One conversion job's settings.

    Frozen: a job that is running cannot have its settings changed underneath
    it, so the report it produces describes the settings it actually ran with.
    """

    target_format: ImageFormat
    """What to produce. The interface offers only targets the pathway registry
    actually carries for the selected sources."""

    quality: int = DEFAULT_QUALITY
    """For lossy targets. Ignored by PNG, which is lossless."""

    output_location: OutputLocation = OutputLocation.SUBFOLDER
    output_folder: Path | None = None
    """Required when, and only when, ``output_location`` is
    :data:`OutputLocation.CHOSEN`. Validated by :meth:`validate` rather than
    assumed, because an interface that forgets to set it would otherwise write
    every file to the current working directory."""

    collision: CollisionPolicy = CollisionPolicy.SUFFIX

    keep_metadata: bool = True
    """Carry EXIF forward - date taken, camera, GPS. On by default because a
    field photo's capture time is what an inspection report's photo log is keyed
    to, and it cannot be recovered once dropped."""

    convert_to_srgb: bool = True
    """Transform pixels into sRGB when the source carries a different profile.
    An iPhone writes Display P3; left untagged-but-unconverted, those pixels
    render oversaturated in every application that ignores an embedded
    profile."""

    auto_rotate: bool = True
    """Apply the EXIF orientation to the pixels and reset the tag to 1."""

    def validate(self) -> None:
        """Refuse an internally inconsistent set of options, naming the problem.

        Called by :func:`imgconv.job.run` before any file is touched, so a
        misconfigured job fails before it has written half a folder.
        """
        if not (MIN_QUALITY <= self.quality <= MAX_QUALITY):
            raise ValueError(
                f"quality is {self.quality}; it must be between {MIN_QUALITY} "
                f"and {MAX_QUALITY}."
            )
        if self.output_location is OutputLocation.CHOSEN:
            if self.output_folder is None:
                raise ValueError(
                    "the output location is a chosen folder, but no folder was "
                    "given. Pick one, or use the 'converted' subfolder instead."
                )
        elif self.output_folder is not None:
            raise ValueError(
                f"an output folder was given ({self.output_folder}) but the "
                f"output location is {self.output_location.value}, which "
                f"derives the folder from each source file. One of the two is "
                f"not what was meant."
            )
