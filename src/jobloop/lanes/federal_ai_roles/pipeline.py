"""Full weekly pipeline for federal-ai-roles: fetch -> global index -> score
-> gap-assess every scored candidate -> select top N -> `LAST-RUN-STATUS.md`.

Spec v4 §7 (per-lane portion) and build order steps 4/8/9 wired together as
one run. Gap assessment runs for *every* scored candidate, not just the
selected pick(s) -- spec v4 B8: "Produced every week regardless of pick
count, because it is what surfaces long-horizon skill gaps."

No tuned weight profiles exist for this lane yet (spec v4 §2's four named
profiles are real config Zhi An hasn't set -- not something to invent
numbers for). Ranking uses a single unweighted default so it stays honest
about that rather than faking precision; tuning weight profiles is a later,
separate step.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from jobloop.core.config import Config
from jobloop.core.cost_guard import CostGuard, CostTripwireExceeded
from jobloop.core.gap_assessment import PacketAnalyzer
from jobloop.core.global_index import GlobalIndex
from jobloop.core.global_index import build as build_global_index
from jobloop.core.ledger import Ledger
from jobloop.core.llm import Scorer
from jobloop.core.packets import Packet, build_packet, save_packet
from jobloop.core.posting import NormalizedPosting, PostingStore
from jobloop.core.scoring import ScoringRun, score_candidates

from . import run as fetch_stage
from .run import LANE, LANE_TITLE

#: No tuned weight profiles exist for this lane yet -- equal weighting.
DEFAULT_WEIGHTS = {
    "background_fit": 1.0,
    "story_fit": 1.0,
    "energy_interest": 1.0,
    "access_network_path": 1.0,
    "gap_risk": 1.0,
}

#: B4: default top-N picks per week; configurable 0-3.
DEFAULT_PICKS = 1


def _default_llm(cfg: Config):
    from jobloop.providers.openai import OpenAiScorer

    return OpenAiScorer(api_key=cfg.secret("OPENAI_API_KEY"))


@dataclass(frozen=True)
class PipelineResult:
    fetch: fetch_stage.RunResult
    scoring: ScoringRun
    packets: tuple[Packet, ...]
    selected_job_ids: tuple[str, ...]
    global_index: GlobalIndex
    total_cost_usd: float
    packets_skipped_over_tripwire: int


def run(
    cfg: Config,
    *,
    picks: int = DEFAULT_PICKS,
    llm: Scorer | PacketAnalyzer | None = None,
) -> PipelineResult:
    llm = llm or _default_llm(cfg)
    # Shared across scoring AND gap assessment: B2's $2 tripwire is a
    # per-run limit, not a per-phase one.
    cost_guard = CostGuard()

    fetch_result = fetch_stage.run(cfg)

    global_index = build_global_index(cfg)
    global_index.save(cfg.global_index_path)

    ledger = Ledger.load(cfg.lane_config(LANE) / "Job-Consideration-Index.md", LANE_TITLE)
    store = PostingStore(cfg.lane_data(LANE))

    # S2: un-applied per the lane ledger AND per the global index -- the
    # lane's own ledger alone can't see applications made outside any lane
    # (spec v4 §6.2's global-index rationale).
    candidate_ids = [
        row.job_id for row in ledger.unapplied() if not global_index.is_applied(row.job_id)
    ]
    candidates: list[NormalizedPosting] = [
        p for p in (store.load(job_id) for job_id in candidate_ids) if p is not None
    ]

    profile_yaml = (cfg.career_root / "JobLoopDev" / "profile.yaml").read_text()
    scoring_run = score_candidates(candidates, profile_yaml, llm, cost_guard=cost_guard)

    ranked = sorted(
        scoring_run.results, key=lambda r: r.weighted_score(DEFAULT_WEIGHTS), reverse=True
    )
    selected_job_ids = tuple(r.job_id for r in ranked[:picks])

    posting_by_id = {p.job_id: p for p in candidates}
    resume_dir = cfg.career_root / "JobHunting" / "Resume"
    packets: list[Packet] = []
    packets_skipped_over_tripwire = 0
    # B8: every scored candidate gets a packet, not just the pick(s).
    for index, result in enumerate(scoring_run.results):
        posting = posting_by_id[result.job_id]
        try:
            packet = build_packet(posting, profile_yaml, llm, resume_dir, cost_guard=cost_guard)
        except CostTripwireExceeded:
            # Spend only grows -- every remaining candidate would fail the
            # same check. Scoring already succeeded and is worth keeping,
            # so stop making further packets rather than losing that work
            # to a crash.
            packets_skipped_over_tripwire = len(scoring_run.results) - index
            break
        save_packet(packet, cfg.lane_data(LANE) / "packets" / result.job_id)
        packets.append(packet)

    result = PipelineResult(
        fetch=fetch_result,
        scoring=scoring_run,
        packets=tuple(packets),
        selected_job_ids=selected_job_ids,
        global_index=global_index,
        total_cost_usd=cost_guard.spent_usd,
        packets_skipped_over_tripwire=packets_skipped_over_tripwire,
    )
    cfg.status_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(cfg.status_path, render_status_md(result))
    return result


def _atomic_write(path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def render_status_md(result: PipelineResult) -> str:
    lines = [
        f"# Last Run Status — {LANE_TITLE}",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "## Fetch",
        f"- fetched: {result.fetch.fetched}",
        f"- kept (passed hard filters): {result.fetch.kept}",
        f"- excluded: {result.fetch.excluded}",
        f"- newly discovered: {result.fetch.newly_discovered}",
        "",
        "## Global index",
        f"- skipped (unmigrated) lanes: {', '.join(result.global_index.skipped_lanes) or 'none'}",
        "",
        "## Scoring",
        f"- candidates scored: {len(result.scoring.results)}",
        f"- skipped (over the 5-candidate cap): {result.scoring.skipped_over_cap}",
        f"- scoring cost: ${result.scoring.total_cost_usd:.4f}",
        "- **note:** no tuned weight profiles exist for this lane yet -- ranked with equal "
        "weights (1.0 each). Treat rankings as provisional until real weights are set.",
        "",
        "## Selected",
    ]
    if result.selected_job_ids:
        lines += [f"- {job_id}" for job_id in result.selected_job_ids]
    else:
        lines.append("- (none selected)")
    lines += ["", "## Packets"]
    lines += [f"- {p.job_id}: `packets/{p.job_id}/`" for p in result.packets] or ["- (none)"]
    if result.packets_skipped_over_tripwire:
        lines.append(
            f"- {result.packets_skipped_over_tripwire} skipped: the $2 tripwire was hit "
            "(alertable -- spec v4 B2 says this shouldn't happen in normal operation)"
        )
    lines += ["", f"## Total run cost: ${result.total_cost_usd:.4f}"]
    return "\n".join(lines) + "\n"
