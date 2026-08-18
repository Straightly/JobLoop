"""Orchestrates one federal-ai-roles fetch: search -> filter -> normalize ->
store -> ledger. Spec v4 §5 S1-S3, S5; build order step 7.

Scoring (LLM pass, §6.1), packet generation (§6.3), and scheduling (§7) are
later stages -- this module only gets postings discovered, normalized, and
into the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from jobloop.core.config import Config
from jobloop.core.ledger import Ledger, LedgerRow
from jobloop.core.posting import PostingStore

from . import client, filters
from .normalize import normalize
from .search_params import SearchParams

LANE = "federal-ai-roles"
LANE_TITLE = "Federal AI Roles"


@dataclass(frozen=True)
class RunResult:
    fetched: int
    kept: int
    excluded: int
    newly_discovered: int


def run(cfg: Config) -> RunResult:
    creds = client.UsajobsCredentials(
        api_key=cfg.secret("USAJOBS_API_KEY"),
        user_agent=cfg.secret("USAJOBS_USER_AGENT"),
    )
    params = SearchParams.load(cfg.lane_config(LANE) / "StartingUrls.md")

    raw_items = client.search(
        params.base_query,
        creds,
        results_per_page=params.results_per_page,
        max_pages=params.max_pages,
    )

    store = PostingStore(cfg.lane_data(LANE))
    ledger = Ledger.load(cfg.lane_config(LANE) / "Job-Consideration-Index.md", LANE_TITLE)

    kept = excluded = newly_discovered = 0
    for item in raw_items:
        descriptor = item["MatchedObjectDescriptor"]
        result = filters.apply_hard_filters(descriptor)
        if result.excluded:
            excluded += 1
            continue

        posting = normalize(descriptor)
        store.save(posting)
        kept += 1

        if ledger.get(posting.job_id) is None:
            newly_discovered += 1
            ledger.upsert(
                LedgerRow(
                    job_id=posting.job_id,
                    title=posting.title,
                    location=posting.location,
                    status="discovered",
                    status_date=date.today(),
                )
            )

    ledger.save()
    return RunResult(
        fetched=len(raw_items), kept=kept, excluded=excluded, newly_discovered=newly_discovered
    )
