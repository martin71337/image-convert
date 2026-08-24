"""The table of files waiting to be converted.

The model holds :class:`QueueEntry` records and nothing else - it does not
convert, and it does not decide what a file is. It asks
:func:`imgconv.convert.inspect` once, when a file is added, which is what puts
the *real* format in the Type column before anything runs. A file named
``.HEIC`` that is actually a JPEG says so in the queue, not in an error message
afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from imgconv.convert import inspect
from imgconv.formats import ImageFormat
from imgconv.result import ConversionResult, Outcome


class Status(Enum):
    """Where one queued file has got to.

    The first three are predictions, recomputed whenever the target format
    changes; the last three are what actually happened. Predicting is worth the
    extra members: without them the only way to learn that a file is already a
    JPEG, or that nothing can convert it, is to run the batch and read the
    failures afterwards.
    """

    QUEUED = "Will convert"
    WILL_SKIP = "Already that format"
    NO_PATHWAY = "Cannot convert"
    CONVERTING = "Converting..."
    DONE = "Done"
    SKIPPED = "Skipped"
    FAILED = "Failed"


_PREDICTIONS = frozenset({Status.QUEUED, Status.WILL_SKIP, Status.NO_PATHWAY})
"""Statuses that a change of target may overwrite. A row showing a real outcome
is left alone - a completed run's results must not be silently replaced by a
prediction about a run that has not happened."""


_STATUS_FOR_OUTCOME = {
    Outcome.CONVERTED: Status.DONE,
    Outcome.SKIPPED: Status.SKIPPED,
    Outcome.FAILED: Status.FAILED,
}


@dataclass
class QueueEntry:
    """One file in the queue, and whatever is known about it so far."""

    path: Path
    image_format: ImageFormat | None = None
    size_bytes: int | None = None
    status: Status = Status.QUEUED
    notes: tuple[str, ...] = ()
    result: ConversionResult | None = None
    unreadable: str | None = None
    """Set when the file could not even be examined - locked, or vanished
    between being dropped and being read."""

    @classmethod
    def examine(cls, path: Path) -> QueueEntry:
        """Build an entry, sniffing the file's real format.

        Never raises: a file that cannot be read becomes an entry that says so,
        because a folder drop that hits one locked file must still queue the
        other ninety-nine.
        """
        try:
            size = path.stat().st_size
        except OSError as error:
            return cls(path=path, unreadable=error.strerror or str(error))

        if size == 0:
            return cls(path=path, size_bytes=0, unreadable="empty file")

        try:
            image_format, notes = inspect(path)
        except OSError as error:
            return cls(path=path, size_bytes=size, unreadable=error.strerror or str(error))

        return cls(path=path, image_format=image_format, size_bytes=size, notes=notes)

    @property
    def type_text(self) -> str:
        if self.unreadable:
            return "Unreadable"
        if self.image_format is None:
            return "Not an image"
        return self.image_format.label

    @property
    def detail(self) -> str:
        """The line shown beneath the table when this row is selected."""
        pieces: list[str] = []
        if self.unreadable:
            pieces.append(f"This file could not be read ({self.unreadable}).")
        if self.result is not None and self.result.reason:
            pieces.append(self.result.reason)
        pieces.extend(self.notes)
        if self.result is not None:
            pieces.extend(n for n in self.result.notes if n not in self.notes)
        if self.result is not None and self.result.target is not None:
            pieces.append(f"Written to {self.result.target}")
        return "  ".join(pieces)


def format_bytes(count: int | None) -> str:
    """``1979299`` -> ``1.9 MB``. Blank for an unknown size."""
    if count is None:
        return ""
    if count < 1024:
        return f"{count} B"
    if count < 1024 * 1024:
        return f"{count / 1024:.0f} KB"
    return f"{count / (1024 * 1024):.1f} MB"


class QueueModel(QAbstractTableModel):
    """A table of :class:`QueueEntry` records."""

    COLUMNS = ("Name", "Folder", "Size", "Type", "Status")
    NAME, FOLDER, SIZE, TYPE, STATUS = range(5)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[QueueEntry] = []
        self._index_of: dict[Path, int] = {}

    # -- Qt model interface -------------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._entries)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return self.COLUMNS[section]

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry = self._entries[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            match index.column():
                case self.NAME:
                    return entry.path.name
                case self.FOLDER:
                    return str(entry.path.parent)
                case self.SIZE:
                    return format_bytes(entry.size_bytes)
                case self.TYPE:
                    return entry.type_text
                case self.STATUS:
                    return entry.status.value

        if role == Qt.ItemDataRole.ToolTipRole:
            return entry.detail or str(entry.path)

        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() == self.SIZE:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        return None

    # -- queue management ---------------------------------------------------

    def entries(self) -> tuple[QueueEntry, ...]:
        return tuple(self._entries)

    def entry_at(self, row: int) -> QueueEntry | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def add_paths(self, paths: list[Path]) -> int:
        """Add every path not already queued. Returns how many were added.

        De-duplication is by resolved path, so dropping a folder and then one of
        its files does not queue that file twice.
        """
        fresh = [p for p in (Path(p) for p in paths) if p not in self._index_of]
        if not fresh:
            return 0

        first = len(self._entries)
        self.beginInsertRows(QModelIndex(), first, first + len(fresh) - 1)
        for path in fresh:
            self._index_of[path] = len(self._entries)
            self._entries.append(QueueEntry.examine(path))
        self.endInsertRows()
        return len(fresh)

    def remove_rows(self, rows: list[int]) -> None:
        """Remove the given rows. Safe to call with an unsorted list."""
        for row in sorted(set(rows), reverse=True):
            if not (0 <= row < len(self._entries)):
                continue
            self.beginRemoveRows(QModelIndex(), row, row)
            del self._entries[row]
            self.endRemoveRows()
        self._reindex()

    def clear(self) -> None:
        self.beginResetModel()
        self._entries.clear()
        self._index_of.clear()
        self.endResetModel()

    def _reindex(self) -> None:
        self._index_of = {entry.path: i for i, entry in enumerate(self._entries)}

    # -- conversion feedback ------------------------------------------------

    def reset_statuses(self) -> None:
        """Back to Queued, dropping any previous run's results.

        Called when a conversion starts. Without it, a second run leaves the
        first run's Done rows on screen and the user cannot tell which results
        belong to what they just pressed.
        """
        for entry in self._entries:
            entry.status = Status.QUEUED
            entry.result = None
        self._emit_all_changed()

    def apply_result(self, result: ConversionResult) -> None:
        """Record one finished file against its row."""
        row = self._index_of.get(result.source)
        if row is None:
            return
        entry = self._entries[row]
        entry.result = result
        entry.status = _STATUS_FOR_OUTCOME.get(result.outcome, Status.FAILED)
        self.dataChanged.emit(
            self.index(row, 0),
            self.index(row, len(self.COLUMNS) - 1),
        )

    def plan_for_target(self, target: ImageFormat | None) -> None:
        """Recompute each row's prediction for ``target``.

        Reads the pathway registry rather than testing for particular formats,
        so a pathway added to the registry changes these predictions with no
        edit here.
        """
        from imgconv.pathways import targets_for

        for entry in self._entries:
            if entry.status not in _PREDICTIONS:
                continue
            if entry.unreadable is not None or entry.image_format is None:
                entry.status = Status.NO_PATHWAY
            elif target is None:
                entry.status = Status.QUEUED
            elif entry.image_format is target:
                entry.status = Status.WILL_SKIP
            elif target in targets_for(entry.image_format):
                entry.status = Status.QUEUED
            else:
                entry.status = Status.NO_PATHWAY
        self._emit_all_changed()

    def convertible_paths(self) -> list[Path]:
        """Every queued path worth handing to the engine.

        Files already known to be unreadable or unrecognised are left out: the
        engine would only rediscover that and report it a second time, and the
        queue already shows why they are not going.

        Files that are *already* the target format are deliberately still
        included. The engine records them as skipped with a reason, which is a
        result the user should see in the report - dropping them here would make
        a folder of thirty JPEGs and ten HEICs report "10 converted" with no
        account of the other thirty.
        """
        return [
            entry.path
            for entry in self._entries
            if entry.unreadable is None and entry.image_format is not None
        ]

    def queued_formats(self) -> tuple[ImageFormat, ...]:
        """The distinct formats present in the queue, in first-seen order.

        Drives the "Convert to" dropdown through
        :func:`imgconv.pathways.common_targets`.
        """
        seen: list[ImageFormat] = []
        for entry in self._entries:
            if entry.image_format is not None and entry.image_format not in seen:
                seen.append(entry.image_format)
        return tuple(seen)

    def _emit_all_changed(self) -> None:
        if not self._entries:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._entries) - 1, len(self.COLUMNS) - 1),
        )
