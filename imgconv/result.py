"""What happened to each file, and to the batch.

Every conversion produces a record, including the ones that failed. A batch is
never abandoned because one file in it was corrupt, locked or not an image at
all - that file gets an :data:`Outcome.FAILED` record naming the reason, and the
run continues. The report is what the interface displays and what a future log
or CSV export would be written from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from imgconv.formats import ImageFormat


class Outcome(Enum):
    """How one file ended."""

    CONVERTED = "converted"
    SKIPPED = "skipped"
    """Deliberately not written - the output existed and the policy was
    :data:`~imgconv.options.CollisionPolicy.SKIP`. Not an error."""

    FAILED = "failed"
    """Nothing was written and the reason is on the record."""


@dataclass(frozen=True)
class ConversionResult:
    """One source file's fate.

    ``notes`` carries things worth telling the user that are not failures: that
    the extension disagreed with the content, that an oversized EXIF block had
    to be trimmed, that a colour profile could not be applied. They are shown
    beside the row and never silently dropped - a conversion that quietly did
    something other than what was asked is the failure mode this program is most
    concerned with.
    """

    source: Path
    outcome: Outcome
    target: Path | None = None
    source_format: ImageFormat | None = None
    target_format: ImageFormat | None = None
    reason: str | None = None
    """Why it failed or was skipped. ``None`` on a clean conversion."""

    notes: tuple[str, ...] = ()
    source_bytes: int | None = None
    target_bytes: int | None = None

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.CONVERTED


@dataclass
class JobReport:
    """Every result from one run, plus whether the run finished.

    Mutable and appended to as the job proceeds, so the interface can display
    partial progress; :attr:`cancelled` distinguishes "the user stopped it" from
    "it ran out of files", which matters to the summary line.
    """

    results: list[ConversionResult] = field(default_factory=list)
    cancelled: bool = False

    def add(self, result: ConversionResult) -> None:
        self.results.append(result)

    @property
    def converted(self) -> list[ConversionResult]:
        return [r for r in self.results if r.outcome is Outcome.CONVERTED]

    @property
    def skipped(self) -> list[ConversionResult]:
        return [r for r in self.results if r.outcome is Outcome.SKIPPED]

    @property
    def failed(self) -> list[ConversionResult]:
        return [r for r in self.results if r.outcome is Outcome.FAILED]

    def summary(self) -> str:
        """One line for the status bar, naming only what actually happened."""
        parts = [f"{len(self.converted)} converted"]
        if self.skipped:
            parts.append(f"{len(self.skipped)} skipped")
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        line = ", ".join(parts)
        return f"Cancelled - {line}" if self.cancelled else line
