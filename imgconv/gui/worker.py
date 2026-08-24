"""Running a conversion without freezing the window.

:class:`ConversionWorker` is a ``QThread`` that calls :func:`imgconv.job.run` and
forwards its progress as Qt signals. It contains no conversion logic of its own -
if this class were deleted the engine would still convert, it would just do it on
the interface's thread and lock the window while it did.

**Why signals rather than direct widget calls.** ``job.run`` invokes its progress
callback from its own pool threads, and touching a widget from a thread that is
not the GUI thread is undefined behaviour in Qt. Emitting a signal is safe from
any thread: Qt sees that sender and receiver live in different threads, queues
the call, and delivers it on the GUI thread's event loop.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from imgconv import job
from imgconv.options import ConversionOptions
from imgconv.result import ConversionResult, JobReport


class ConversionWorker(QThread):
    """Converts ``sources`` in the background, reporting as it goes."""

    progressed = Signal(int, int, object)
    """``(completed, total, ConversionResult)`` - one per finished file."""

    completed = Signal(object)
    """``(JobReport)`` - the run finished, was cancelled, or refused to start."""

    failed = Signal(str)
    """The job could not start at all: options that do not make sense, or an
    unforeseen error escaping the runner. Distinct from a file failing, which is
    an ordinary result."""

    def __init__(
        self,
        sources: Sequence[Path],
        options: ConversionOptions,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._sources = list(sources)
        self._options = options
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Ask the run to stop after the files already in flight.

        Deliberately not a kill. A conversion interrupted mid-encode is exactly
        the case the atomic write exists for, and stopping between files means no
        partial output can survive at all.
        """
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> None:  # noqa: D102 - QThread's own contract
        def progress(done: int, total: int, result: ConversionResult) -> None:
            self.progressed.emit(done, total, result)

        try:
            report = job.run(
                self._sources,
                self._options,
                progress=progress,
                cancel=self._cancel,
            )
        except ValueError as error:
            # Options that do not make sense - validate() refused before any
            # file was touched.
            self.failed.emit(str(error))
            return
        except Exception as error:  # pragma: no cover - the runner catches its own
            self.failed.emit(f"The conversion stopped unexpectedly: {error}")
            return

        self.completed.emit(report)


class JobReportBuilder:
    """Assembles a partial report while a run is in progress.

    The window needs a summary line the moment Cancel is pressed, before the
    worker's own report arrives. Rather than have the window count outcomes
    itself - a second implementation of something :class:`JobReport` already
    does - it accumulates results here and reads the same properties.
    """

    def __init__(self) -> None:
        self.report = JobReport()

    def add(self, result: ConversionResult) -> None:
        self.report.add(result)

    def summary(self, cancelled: bool = False) -> str:
        self.report.cancelled = cancelled
        return self.report.summary()
