"""Per-lane consideration ledger.

Spec v4 §6.2. G1's lanes disagreed on status vocabulary — `amazon-ai-applied`
used bare `discovered` for every one of its 85 rows, `anthropic` embedded
dates in free text (`applied 2026-07-19`, `closed 2026-07-18 (pre-submission;
posting removed same day packet was drafted)`). That makes the ledger
unqueryable: nothing can ask "what's un-applied as of when" without parsing
prose.

The fix: one canonical status enum, `status_date` as its own field, and every
other detail confined to free-text `notes`.

Ported G1 lanes (`amazon-ai-applied`, `amazon-devex`, `anthropic`) keep their
original-format `Job-Consideration-Index.md` untouched for now — migrating
their history to this schema is separate, later work (spec v4 §12 step 3).
This module is what a lane built against this schema from day one — starting
with `federal-ai-roles` — reads and writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .errors import DeterministicError

# Canonical status vocabulary. Spec v4 §6.2.
STATUSES = (
    "discovered",
    "reviewed",
    "shortlisted",
    "scaffolded",
    "applied",
    "not-pursuing",
    "expired",
    "duplicate",
    "closed",
)

#: Statuses that exclude a job from the "top un-applied" selection (S2).
#: Everything else -- including previously `discovered`/`reviewed` -- stays
#: eligible; only having actually applied takes a job out of rotation.
APPLIED_STATUSES = frozenset({"applied"})

COLUMNS = (
    "Job ID",
    "Title",
    "Location",
    "Status",
    "Status Date",
    "Recommendation",
    "Notes",
    "Folder",
)

_HEADER = "| " + " | ".join(COLUMNS) + " |"
_DIVIDER = "|" + "|".join("---" for _ in COLUMNS) + "|"

#: Splits a table row on unescaped `|`, leaving `\|` inside a cell alone.
_CELL_SPLIT = re.compile(r"(?<!\\)\|")


class LedgerError(DeterministicError):
    """A ledger row or file does not conform to the canonical schema."""


def _escape(cell: str) -> str:
    return str(cell).replace("|", "\\|").replace("\n", " ").strip()


def _unescape(cell: str) -> str:
    return cell.strip().replace("\\|", "|")


@dataclass(frozen=True)
class LedgerRow:
    job_id: str
    title: str
    location: str
    status: str
    status_date: date
    recommendation: str = ""
    notes: str = ""
    folder: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise LedgerError(
                f"{self.job_id!r}: status {self.status!r} not in canonical "
                f"vocabulary {STATUSES}"
            )
        if not self.job_id:
            raise LedgerError("job_id is required")

    def to_line(self) -> str:
        cells = (
            self.job_id,
            self.title,
            self.location,
            self.status,
            self.status_date.isoformat(),
            self.recommendation,
            self.notes,
            self.folder,
        )
        return "| " + " | ".join(_escape(c) for c in cells) + " |"


def _parse_line(line: str) -> LedgerRow | None:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells = [_unescape(c) for c in _CELL_SPLIT.split(body)]
    if len(cells) != len(COLUMNS):
        return None
    job_id, title, location, status, status_date_str, recommendation, notes, folder = cells
    try:
        status_date = date.fromisoformat(status_date_str)
    except ValueError:
        return None
    return LedgerRow(
        job_id=job_id,
        title=title,
        location=location,
        status=status,
        status_date=status_date,
        recommendation=recommendation,
        notes=notes,
        folder=folder,
    )


class Ledger:
    """A single lane's `Job-Consideration-Index.md`, in the canonical schema."""

    def __init__(self, path: Path, lane_title: str):
        self.path = path
        self.lane_title = lane_title
        self._rows: dict[str, LedgerRow] = {}

    @classmethod
    def load(cls, path: Path, lane_title: str) -> "Ledger":
        """Load an existing ledger, or start an empty one if the file is new."""
        ledger = cls(path, lane_title)
        if not path.is_file():
            return ledger
        in_table = False
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("| Job ID"):
                in_table = True
                continue
            if not in_table:
                continue
            if line.startswith("|---"):
                continue
            if not line.strip():
                break
            row = _parse_line(line)
            if row is None:
                raise LedgerError(f"{path}: unparseable row: {line!r}")
            ledger._rows[row.job_id] = row
        return ledger

    def upsert(self, row: LedgerRow) -> None:
        """Insert a row, or replace the existing one for the same job id."""
        self._rows[row.job_id] = row

    def get(self, job_id: str) -> LedgerRow | None:
        return self._rows.get(job_id)

    def rows(self) -> list[LedgerRow]:
        """All rows, oldest status change first."""
        return sorted(self._rows.values(), key=lambda r: (r.status_date, r.job_id))

    def unapplied(self) -> list[LedgerRow]:
        """Rows eligible for the top-N selection (S2) -- everything not `applied`."""
        return [r for r in self.rows() if r.status not in APPLIED_STATUSES]

    def save(self) -> None:
        """Write atomically: temp file then rename (spec v4 §9)."""
        lines = [f"# Job Consideration Index — {self.lane_title}", "", _HEADER, _DIVIDER]
        lines += [row.to_line() for row in self.rows()]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(self.path)
