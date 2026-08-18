"""Normalized posting record and storage.

Spec v4 §5 S3: "Normalize into `Job-Posting-Schema`. Store once, reference by
ID." This module covers that normalization/storage step only.

It deliberately stops short of `schemas/Job-Posting-Schema.md`'s "Fit
Assessment" and "Notes" sections (`background_fit`, `story_fit`,
`overall_recommendation`, ...). Those are scores, produced per weight profile
and re-derivable on replay (spec v4 §6.1, §8) -- they don't belong baked into
the one-per-posting record, or every profile change would mean re-normalizing
postings that haven't actually changed. Scoring lives alongside this, not
inside it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from .errors import DeterministicError

WorkModel = Literal["remote", "hybrid", "onsite", "unknown"]

#: spec schema's `role_family_guess` options, plus "unclear" as the honest default.
RoleFamily = Literal[
    "applied-scientist-research-heavy",
    "applied-ai-solutions",
    "agentic-ai-llm-applications",
    "ml-platform-evaluation-infrastructure",
    "unclear",
]


class PostingError(DeterministicError):
    """A posting record does not conform to the normalized schema."""


@dataclass(frozen=True)
class NormalizedPosting:
    # -- core -----------------------------------------------------------
    source: str
    job_id: str
    title: str
    company: str
    location: str
    url: str
    date_captured: date
    team_org: str = ""
    work_model: WorkModel = "unknown"

    # -- qualifications ---------------------------------------------------
    required_qualifications: tuple[str, ...] = ()
    preferred_qualifications: tuple[str, ...] = ()
    hard_requirements: tuple[str, ...] = ()
    soft_preferences: tuple[str, ...] = ()

    # -- role classification ----------------------------------------------
    role_family_guess: RoleFamily = "unclear"
    seniority_guess: str = ""
    customer_facing_signal: bool = False
    research_signal: bool = False
    model_training_signal: bool = False
    orchestration_signal: bool = False
    evaluation_signal: bool = False

    def __post_init__(self) -> None:
        if not self.job_id:
            raise PostingError("job_id is required")
        if not self.source:
            raise PostingError("source is required")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date_captured"] = self.date_captured.isoformat()
        for key in (
            "required_qualifications",
            "preferred_qualifications",
            "hard_requirements",
            "soft_preferences",
        ):
            d[key] = list(d[key])
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "NormalizedPosting":
        d = dict(d)
        d["date_captured"] = date.fromisoformat(d["date_captured"])
        for key in (
            "required_qualifications",
            "preferred_qualifications",
            "hard_requirements",
            "soft_preferences",
        ):
            if key in d:
                d[key] = tuple(d[key])
        return cls(**d)


class PostingStore:
    """Normalized postings for one lane: `<lane_data>/normalized-postings/`.

    One JSON file per job id -- "store once, reference by ID" (S3). Re-fetching
    a previously-seen job overwrites its file rather than duplicating it (S2:
    previously-seen jobs are not excluded, only *applied* status excludes).
    """

    def __init__(self, lane_data_dir: Path):
        self.dir = lane_data_dir / "normalized-postings"

    def _path(self, job_id: str) -> Path:
        return self.dir / f"{job_id}.json"

    def save(self, posting: NormalizedPosting) -> None:
        """Atomic write: temp file then rename (spec v4 §9)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._path(posting.job_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(posting.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)

    def load(self, job_id: str) -> NormalizedPosting | None:
        path = self._path(job_id)
        if not path.is_file():
            return None
        return NormalizedPosting.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def has(self, job_id: str) -> bool:
        return self._path(job_id).is_file()

    def all_ids(self) -> list[str]:
        if not self.dir.is_dir():
            return []
        return sorted(p.stem for p in self.dir.glob("*.json"))

    def load_all(self) -> list[NormalizedPosting]:
        return [self.load(job_id) for job_id in self.all_ids()]
