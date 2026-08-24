"""One file in, one file out. The single conversion entry point.

Everything that converts an image goes through :func:`convert_one` - the batch
runner, the self-test, and any future command line. There is no second path that
opens an image and saves it, which is what keeps the sniffing, the refusals and
the atomic write from being implemented twice and differently.

**This function does not raise for ordinary trouble.** A corrupt file, a locked
file, a format with no pathway - all of them come back as a
:data:`~imgconv.result.Outcome.FAILED` record naming the reason. A batch of two
hundred photos is not abandoned because one of them is a text file someone
renamed. Programming errors still raise.
"""

from __future__ import annotations

from pathlib import Path

from imgconv import formats
from imgconv.naming import output_path_for, would_convert_onto_itself
from imgconv.options import ConversionOptions
from imgconv.pathways import PathwayError, pathway_for
from imgconv.result import ConversionResult, Outcome


def _failed(source: Path, reason: str, **extra: object) -> ConversionResult:
    return ConversionResult(source=source, outcome=Outcome.FAILED, reason=reason, **extra)  # type: ignore[arg-type]


def inspect(source: Path) -> tuple[formats.ImageFormat | None, tuple[str, ...]]:
    """What format ``source`` actually is, and any note about how it is named.

    Split out from :func:`convert_one` because the interface calls it when files
    are added to the queue - so a mislabelled file is visible in the Type column
    before anything is converted, not after it fails.
    """
    actual = formats.sniff(source)
    if actual is None:
        return None, ()
    if formats.extension_disagrees(source, actual):
        claimed = formats.format_claimed_by_extension(source)
        assert claimed is not None  # extension_disagrees said so
        return actual, (
            f"This file is named .{source.suffix.lstrip('.')} but its contents are "
            f"{actual.label}, not {claimed.label}. It was converted as "
            f"{actual.label}.",
        )
    return actual, ()


def convert_one(
    source: Path,
    options: ConversionOptions,
    reserved: set[Path] | None = None,
) -> ConversionResult:
    """Convert ``source`` according to ``options``.

    ``reserved`` is the batch runner's set of paths already handed out; see
    :func:`imgconv.naming.output_path_for` for why it exists.
    """
    try:
        if not source.is_file():
            return _failed(source, "The file no longer exists.")
        source_bytes = source.stat().st_size
    except OSError as error:
        return _failed(source, f"The file could not be read ({error.strerror or error}).")

    if source_bytes == 0:
        return _failed(source, "The file is empty.", source_bytes=0)

    try:
        source_format, notes = inspect(source)
    except OSError as error:
        return _failed(
            source,
            f"The file could not be read ({error.strerror or error}).",
            source_bytes=source_bytes,
        )

    if source_format is None:
        return _failed(
            source,
            "This is not an image file this program recognises.",
            source_bytes=source_bytes,
        )

    if source_format is options.target_format:
        return ConversionResult(
            source=source,
            outcome=Outcome.SKIPPED,
            source_format=source_format,
            target_format=options.target_format,
            reason=f"Already {options.target_format.label}.",
            notes=notes,
            source_bytes=source_bytes,
        )

    try:
        pathway = pathway_for(source_format, options.target_format)
    except PathwayError as error:
        return _failed(source, str(error), source_format=source_format, source_bytes=source_bytes)

    try:
        destination = output_path_for(source, options.target_format, options, reserved)
    except (OSError, FileExistsError) as error:
        return _failed(source, str(error), source_format=source_format, source_bytes=source_bytes)

    if destination is None:
        return ConversionResult(
            source=source,
            outcome=Outcome.SKIPPED,
            source_format=source_format,
            target_format=options.target_format,
            reason="A converted file of that name is already there.",
            notes=notes,
            source_bytes=source_bytes,
        )

    if would_convert_onto_itself(source, destination):
        return _failed(
            source,
            "The output would overwrite the file being read. Choose a different "
            "output folder.",
            source_format=source_format,
            source_bytes=source_bytes,
        )

    # `destination` was claimed inside output_path_for, under its lock; nothing
    # is recorded here, which is what keeps choosing and claiming indivisible.

    # Imported here, not at module scope: this is the first thing that needs
    # Pillow, and keeping it out of the import graph above means the queue can be
    # built, inspected and validated before a decoder is ever loaded. It also
    # keeps a decoder failure attributable to the file that triggered it.
    from imgconv.imaging import backend

    try:
        encoded = backend.convert_image(source, destination, pathway, options)
    except MemoryError:
        return _failed(
            source,
            "There was not enough memory to convert this image.",
            source_format=source_format,
            source_bytes=source_bytes,
        )
    except (OSError, ValueError) as error:
        return _failed(
            source,
            f"This file could not be converted ({error}).",
            source_format=source_format,
            source_bytes=source_bytes,
        )

    try:
        target_bytes = destination.stat().st_size
    except OSError:  # pragma: no cover - written a moment ago
        target_bytes = None

    return ConversionResult(
        source=source,
        outcome=Outcome.CONVERTED,
        target=encoded.path,
        source_format=source_format,
        target_format=options.target_format,
        notes=notes + encoded.notes,
        source_bytes=source_bytes,
        target_bytes=target_bytes,
    )
