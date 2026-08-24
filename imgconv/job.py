"""Running a batch: many files in, one report out.

Qt-free on purpose. The whole engine can be driven from a test, a script or a
future command line with no display attached, and the interface is a thin thing
that builds options and renders results.

**Files are converted on several threads.** Decoding a 12-megapixel HEIC and
encoding the JPEG are both done inside libheif and libjpeg, which release the
GIL, so the work genuinely overlaps - a folder of a hundred field photos
finishes in roughly a quarter of the time. The parts that are *not* thread-safe
by construction - choosing an output path, appending to the report - are each
guarded at their own root rather than by making the whole loop serial.

**One bad file never stops a batch.** Every failure mode that is about a file
becomes a record; see :func:`imgconv.convert.convert_one`.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from imgconv.convert import convert_one
from imgconv.options import ConversionOptions
from imgconv.result import ConversionResult, JobReport

MAX_WORKERS = min(8, (os.cpu_count() or 4))
"""Conversion threads.

Capped at 8 because the work is memory-bandwidth bound well before it is core
bound - each in-flight 12-megapixel image is around 36 MB of RGB - and because a
tool that saturates every core makes the machine it runs on feel broken.
"""

ProgressCallback = Callable[[int, int, ConversionResult], None]
"""``(completed, total, result)``, called once per finished file.

Called from a worker thread. The Qt layer forwards it as a signal rather than
touching a widget, which is the only safe thing to do with it.
"""


def run(
    sources: Sequence[Path],
    options: ConversionOptions,
    progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
    max_workers: int | None = None,
) -> JobReport:
    """Convert every path in ``sources``. Returns the report.

    ``cancel`` is checked before each file is started, so cancelling stops the
    queue promptly but never abandons a conversion mid-write - the file being
    encoded when Cancel is pressed either completes or leaves nothing behind.
    Files not reached are simply absent from the report; they were not skipped,
    they were not attempted.

    Raises ``ValueError`` from :meth:`ConversionOptions.validate` before touching
    anything, so a misconfigured job fails before it has written half a folder.
    """
    options.validate()

    report = JobReport()
    total = len(sources)
    if total == 0:
        return report

    reserved: set[Path] = set()
    report_lock = threading.Lock()
    completed = 0

    def convert(source: Path) -> ConversionResult | None:
        if cancel is not None and cancel.is_set():
            return None
        return convert_one(source, options, reserved)

    def record(result: ConversionResult) -> None:
        nonlocal completed
        with report_lock:
            report.add(result)
            completed += 1
            position = completed
        if progress is not None:
            progress(position, total, result)

    workers = max_workers if max_workers is not None else MAX_WORKERS
    workers = max(1, min(workers, total))

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="convert") as pool:
        futures: list[Future[ConversionResult | None]] = [
            pool.submit(convert, source) for source in sources
        ]
        for future in futures:
            result = future.result()
            if result is None:
                continue
            record(result)

    if cancel is not None and cancel.is_set():
        report.cancelled = True

    return report


def collect_images(
    roots: Iterable[Path],
    recurse: bool = True,
    known_extensions: Iterable[str] | None = None,
) -> list[Path]:
    """Expand a mixed list of files and folders into a list of candidate files.

    What the interface calls when files or folders are dropped on the window.

    **Extensions are used here and nowhere else.** This is a queue-building
    convenience - walking a photo folder should not mean reading the first bytes
    of every ``.docx`` in it - and it decides only what is *offered*. Once a file
    is in the queue its real format is sniffed, so a file that gets in past a
    wrong extension still converts correctly, and a file explicitly chosen in the
    file dialog is never filtered out at all.

    Results are de-duplicated and sorted, so dropping a folder and one file
    inside it queues that file once, and the order is what the user sees in
    Explorer rather than whatever order the filesystem walked.
    """
    from imgconv.formats import readable_extensions

    allowed = {e.lower() for e in (known_extensions or readable_extensions())}
    found: set[Path] = set()

    for root in roots:
        try:
            if root.is_file():
                # Chosen explicitly: no extension filter.
                found.add(root.resolve())
            elif root.is_dir():
                pattern = "**/*" if recurse else "*"
                for entry in root.glob(pattern):
                    try:
                        if entry.is_file() and entry.suffix.lower() in allowed:
                            found.add(entry.resolve())
                    except OSError:
                        continue  # a locked or vanished entry is not a reason to stop
        except OSError:
            continue

    return sorted(found)
