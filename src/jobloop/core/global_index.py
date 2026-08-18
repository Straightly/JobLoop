"""Cross-lane index: merges every canonical-format lane ledger with
`career/JobHunting/00-Tracker/Application-Index.md`.

Spec v4 §6.2: "global-index.json is rebuilt in DATA each run by merging
every lane ledger with Application-Index.md. It is what S2 and S6 query,
because quotas and applied-status are cross-lane facts that no single lane
can see."

Only lanes using the canonical ledger schema (`core.ledger`) are merged.
G1-format lanes (`amazon-ai-applied`, `amazon-devex`, `anthropic`) are
skipped and reported, not force-parsed -- migrating their ledgers to the
canonical schema is separate, deferred work (spec v4 §12 step 3).

`Application-Index.md`'s Job ID column is free text (backtick-quoted IDs,
sometimes several per row, sometimes agency-prefixed, sometimes empty) and
its Status column has no controlled vocabulary. This module extracts
backtick-quoted tokens as candidate IDs and classifies status via a
conservative heuristic: only a small allowlist of clearly-not-yet-submitted
statuses (scaffolded, drafting, planning) are treated as *not* applied --
everything else (applied, rejected, ineligible, closed, interview, ...) is
treated as applied, because under-excluding a job Zhi An already has a real
outcome for is worse than over-excluding a stale draft.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Config
from .ledger import Ledger

_ID_TOKEN = re.compile(r"`([^`]+)`")

#: Statuses that clearly mean nothing has been submitted yet. Everything
#: else is conservatively treated as "applied" -- see module docstring.
_NOT_YET_APPLIED_MARKERS = ("scaffolded", "drafting", "planning")

#: G1-format lanes not yet migrated to the canonical ledger schema (spec v4
#: §12 step 3, deferred). Listed explicitly so a lane that *is* canonical
#: doesn't silently start getting skipped too if this list goes stale.
LEGACY_UNMIGRATED_LANES = ("amazon-ai-applied", "amazon-devex", "anthropic")

TRACKER_RELATIVE_PATH = Path("JobHunting") / "00-Tracker" / "Application-Index.md"


@dataclass(frozen=True)
class TrackerRow:
    date: str
    company: str
    role: str
    job_ids: tuple[str, ...]
    status: str
    folder: str

    @property
    def applied(self) -> bool:
        lowered = self.status.lower()
        return not any(marker in lowered for marker in _NOT_YET_APPLIED_MARKERS)


def _parse_tracker_row(line: str) -> TrackerRow | None:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) != 8:
        return None
    date, company, role, job_id_cell, status, _resume, folder, _next_action = cells
    return TrackerRow(
        date=date,
        company=company,
        role=role,
        job_ids=tuple(_ID_TOKEN.findall(job_id_cell)),
        status=status,
        folder=folder,
    )


def load_tracker(path: Path) -> list[TrackerRow]:
    if not path.is_file():
        return []
    rows: list[TrackerRow] = []
    in_table = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("| Date"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---"):
            continue
        if not line.strip():
            break
        row = _parse_tracker_row(line)
        if row is not None:
            rows.append(row)
    return rows


@dataclass(frozen=True)
class LaneEntry:
    lane: str
    job_id: str
    status: str
    status_date: str


@dataclass(frozen=True)
class GlobalIndex:
    lane_entries: tuple[LaneEntry, ...]
    tracker_rows: tuple[TrackerRow, ...]
    skipped_lanes: tuple[str, ...]

    def is_applied(self, job_id: str) -> bool:
        """S2: the only thing that excludes a job from the un-applied selection."""
        for entry in self.lane_entries:
            if entry.job_id == job_id and entry.status == "applied":
                return True
        for row in self.tracker_rows:
            if job_id in row.job_ids and row.applied:
                return True
        return False

    def applications_for_company(self, company: str, *, since: str | None = None) -> int:
        """S6 quota check. `since` is an inclusive ISO date string."""
        count = 0
        for row in self.tracker_rows:
            if row.company.strip().lower() != company.strip().lower():
                continue
            if not row.applied:
                continue
            if since and row.date < since:
                continue
            count += 1
        return count

    def to_dict(self) -> dict:
        return {
            "lane_entries": [asdict(e) for e in self.lane_entries],
            "tracker_rows": [asdict(r) for r in self.tracker_rows],
            "skipped_lanes": list(self.skipped_lanes),
        }

    def save(self, path: Path) -> None:
        """Atomic write: temp file then rename (spec v4 §9)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)


def build(cfg: Config) -> GlobalIndex:
    """Rebuild from every canonical-format lane ledger plus the tracker.

    Spec v4 §6.2: rebuilt fresh each run, never hand-edited.
    """
    lane_entries: list[LaneEntry] = []
    skipped: list[str] = []

    if cfg.lanes_dir.is_dir():
        for lane_dir in sorted(cfg.lanes_dir.iterdir()):
            if not lane_dir.is_dir():
                continue
            lane = lane_dir.name
            if lane in LEGACY_UNMIGRATED_LANES:
                skipped.append(lane)
                continue
            ledger_path = lane_dir / "Job-Consideration-Index.md"
            if not ledger_path.is_file():
                continue
            ledger = Ledger.load(ledger_path, lane)
            for row in ledger.rows():
                lane_entries.append(
                    LaneEntry(
                        lane=lane,
                        job_id=row.job_id,
                        status=row.status,
                        status_date=row.status_date.isoformat(),
                    )
                )

    tracker_rows = tuple(load_tracker(cfg.career_root / TRACKER_RELATIVE_PATH))

    return GlobalIndex(
        lane_entries=tuple(lane_entries), tracker_rows=tracker_rows, skipped_lanes=tuple(skipped)
    )
