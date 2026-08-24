"""Where a converted file goes, and what happens if something is already there.

Two rules, both from the standing conventions:

* **Exports never silently clobber.** The default policy renames rather than
  overwrites, and overwriting happens only when it was chosen by name.
* **One entry point per data path.** Every output path in the program comes from
  :func:`output_path_for`; no caller assembles one from a stem and an extension
  of its own, which is how a naming rule ends up implemented twice and
  differently.
"""

from __future__ import annotations

import threading
from pathlib import Path

from imgconv.formats import ImageFormat
from imgconv.options import SUBFOLDER_NAME, CollisionPolicy, ConversionOptions, OutputLocation

MAX_SUFFIX_ATTEMPTS = 9999
"""How far :data:`~imgconv.options.CollisionPolicy.SUFFIX` will count before
giving up. A four-digit ceiling is far past any real batch; reaching it means
something is generating names in a loop, and failing that one file with a clear
reason beats spinning."""

_reservation_lock = threading.Lock()
"""Guards the whole choose-a-path-and-claim-it sequence in :func:`output_path_for`.

The batch runner converts files on several threads. Choosing a free path and
recording that it has been taken must happen as one indivisible step: if two
threads each look, each see ``IMG_2480.jpg`` free, and each claim it, the second
conversion silently destroys the first. Checking and claiming under one lock is
what makes that impossible rather than merely unlikely.

The critical section is microseconds of ``set`` and ``stat`` work, so it costs
nothing measurable against the decode it precedes.
"""


def destination_folder(source: Path, options: ConversionOptions) -> Path:
    """The folder ``source``'s output belongs in. Does not create it."""
    match options.output_location:
        case OutputLocation.SUBFOLDER:
            return source.parent / SUBFOLDER_NAME
        case OutputLocation.ALONGSIDE:
            return source.parent
        case OutputLocation.CHOSEN:
            if options.output_folder is None:  # pragma: no cover - validate() first
                raise ValueError("no output folder was set for a chosen-folder job.")
            return options.output_folder
    raise AssertionError(f"unhandled output location {options.output_location!r}")


def _candidate(folder: Path, stem: str, extension: str, attempt: int) -> Path:
    """``IMG_2480.jpg`` for attempt 0, then ``IMG_2480_1.jpg``, ``_2``, ...

    The counter goes on the stem rather than after the extension so the file
    keeps a name Windows, Word and CAD all still recognise as a JPEG.
    """
    if attempt == 0:
        return folder / f"{stem}{extension}"
    return folder / f"{stem}_{attempt}{extension}"


def output_path_for(
    source: Path,
    target_format: ImageFormat,
    options: ConversionOptions,
    reserved: set[Path] | None = None,
) -> Path | None:
    """The path to write, or ``None`` when the policy says to skip this file.

    ``reserved`` holds paths already promised to earlier files in the same batch
    but not yet written. Without it, flattening two folders that each contain an
    ``IMG_2480.HEIC`` into one chosen output folder would hand both files the
    same free path - neither exists on disk at the moment it is chosen, so both
    look available, and the second conversion silently destroys the first.

    **The chosen path is claimed here, inside the lock, not by the caller.** A
    caller that received a path and then recorded it would leave exactly the gap
    this set exists to close, since another thread can run in between. Handing
    out and claiming are one operation.

    Raises :class:`FileExistsError` only in the pathological case where the
    suffix counter is exhausted.
    """
    folder = destination_folder(source, options)
    stem = source.stem
    extension = target_format.default_extension

    with _reservation_lock:
        claimed: set[Path] = reserved if reserved is not None else set()

        def taken(path: Path) -> bool:
            return path in claimed or path.exists()

        def claim(path: Path) -> Path:
            claimed.add(path)
            return path

        first = _candidate(folder, stem, extension, 0)

        match options.collision:
            case CollisionPolicy.OVERWRITE:
                # Still respects `claimed`: overwriting a file the user already
                # had is what they asked for, but overwriting one this same batch
                # just produced is never what anybody meant.
                if first not in claimed:
                    return claim(first)
            case CollisionPolicy.SKIP:
                if taken(first):
                    return None
                return claim(first)
            case CollisionPolicy.SUFFIX:
                if not taken(first):
                    return claim(first)
            case _:  # pragma: no cover - the enum is closed
                raise AssertionError(f"unhandled collision policy {options.collision!r}")

        for attempt in range(1, MAX_SUFFIX_ATTEMPTS + 1):
            candidate = _candidate(folder, stem, extension, attempt)
            if not taken(candidate):
                return claim(candidate)

    raise FileExistsError(
        f"could not find a free name for {source.name} in {folder}: "
        f"{stem}{extension} and {MAX_SUFFIX_ATTEMPTS} numbered variants of it "
        f"are all taken."
    )


def would_convert_onto_itself(source: Path, target: Path) -> bool:
    """True when the output path is the input path.

    Reachable in one real configuration - a JPEG converted to JPEG, written
    alongside itself, with the overwrite policy - and reading a file while
    truncating it produces a zero-byte result. The caller refuses instead.
    """
    try:
        return source.resolve() == target.resolve()
    except OSError:  # pragma: no cover - resolve() on a vanished path
        return False
