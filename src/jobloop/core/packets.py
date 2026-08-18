"""Packet generation: `Job-Post.md` and `Gap-Assessment.md`. Spec v4 §6.3
B7, B8, B12.

B10 (tailored resume/cover letter, pandoc rendering) is deliberately not
built here -- Zhi An held it off explicitly (2026-08-17): "Hold off on the
'tailoring' part as I am sure that is something I had in mind." B9 (base
resume selection) *is* built, folded into the same LLM call as the gap
assessment: it's a selection among Zhi An's existing resume files, not
generation of new tailored content, so B11's fabrication constraint doesn't
bind it the way it binds B10.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .gap_assessment import PacketAnalysis, PacketAnalyzer
from .posting import NormalizedPosting

RESUME_DIR_RELATIVE = Path("JobHunting") / "Resume"

GAP_SYSTEM_PROMPT = """You are assessing a job posting's requirements against a real candidate's \
actual, verified background for a job search agent. This is a hard-fabrication-safety task: you \
may NEVER claim the candidate has experience, skills, or evidence that is not explicitly present \
in the "Candidate profile" section provided to you. If you are not sure evidence exists, mark the \
requirement "missing", not "have" or "partial".

For each distinct requirement you can identify in the posting (break the qualification/requirement \
text into discrete, individually-assessable requirements):
- status: "have" (clearly evidenced), "partial" (some evidence, not a full match), or "missing" \
  (no real evidence)
- evidence: for "have"/"partial", cite the SPECIFIC fact from the candidate profile that supports \
  this (verbatim or close paraphrase) -- never leave this blank for have/partial, and never invent \
  a citation. For "missing", leave this empty.
- gap_type: "narrative" (has it, described wrong), "evidence" (plausible but no strong example), \
  "depth" (touched it, not deeply enough), "credibility" (has it, market won't believe it without \
  proof), or "none" (no gap)
- mitigation: "reframe", "reorder", "add_proof", "downscope_target", "ignore", or "none"

Also recommend which ONE existing resume file (from the provided list of filenames and their \
headlines) is the closest starting point for this role, with a one-sentence justification. Only \
choose a filename that appears in the provided list -- never invent one.
"""


def _resume_candidates(resume_dir: Path) -> list[tuple[str, str]]:
    """(filename, first non-empty line) for each loose `.md` resume in the
    inventory. Skips `00-`/`01-`/`02-`/`03-`/`99-` subfolders -- per
    `README-ResumeSystem.md` those are structural (master inventory, role
    targets, past applications, gap tracking, templates), not resumes
    themselves.
    """
    if not resume_dir.is_dir():
        return []
    candidates = []
    for path in sorted(resume_dir.glob("*.md")):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        headline = next((line.strip() for line in lines if line.strip()), "")
        candidates.append((path.name, headline))
    return candidates


def build_job_post_md(posting: NormalizedPosting) -> str:
    """B7: full JD, canonical URL, ID, location, posting date."""
    quals = "\n".join(f"- {q}" for q in posting.required_qualifications) or "(not captured)"
    requirements = "\n".join(f"- {r}" for r in posting.hard_requirements) or "(not captured)"
    return f"""# {posting.title}

- Source: {posting.source}
- Job ID: {posting.job_id}
- URL: {posting.url}
- Organization: {posting.company} / {posting.team_org}
- Location: {posting.location}
- Work model: {posting.work_model}
- Seniority: {posting.seniority_guess or "unknown"}
- Captured: {posting.date_captured.isoformat()}

## Qualifications

{quals}

## Requirements

{requirements}
"""


def build_gap_user_prompt(
    posting: NormalizedPosting, profile_yaml: str, resume_candidates: list[tuple[str, str]]
) -> str:
    resume_list = (
        "\n".join(f"- {name}: {headline}" for name, headline in resume_candidates)
        or "(none available)"
    )
    return f"""## Candidate profile

{profile_yaml}

## Job posting

{build_job_post_md(posting)}

## Available resume files (pick exactly one)

{resume_list}
"""


@dataclass(frozen=True)
class Packet:
    job_id: str
    job_post_md: str
    analysis: PacketAnalysis


def build_packet(
    posting: NormalizedPosting,
    profile_yaml: str,
    analyzer: PacketAnalyzer,
    resume_dir: Path,
) -> Packet:
    candidates = _resume_candidates(resume_dir)
    prompt = build_gap_user_prompt(posting, profile_yaml, candidates)
    analysis = analyzer.analyze(
        job_id=posting.job_id, system_prompt=GAP_SYSTEM_PROMPT, user_prompt=prompt
    )
    return Packet(job_id=posting.job_id, job_post_md=build_job_post_md(posting), analysis=analysis)


def render_gap_assessment_md(analysis: PacketAnalysis) -> str:
    def esc(s: str) -> str:
        return s.replace("|", "\\|").replace("\n", " ")

    lines = [
        "# Gap Assessment",
        "",
        f"**Recommended base resume:** `{analysis.resume_recommendation.filename}`",
        f"**Why:** {analysis.resume_recommendation.justification}",
        "",
        "| Requirement | Status | Evidence | Gap type | Mitigation |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {esc(g.requirement)} | {g.status} | {esc(g.evidence)} | {g.gap_type} | {g.mitigation} |"
        for g in analysis.gaps
    ]
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    """Temp file then rename (spec v4 §9)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def save_packet(packet: Packet, packet_dir: Path) -> None:
    packet_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(packet_dir / "Job-Post.md", packet.job_post_md)
    _atomic_write(packet_dir / "Gap-Assessment.md", render_gap_assessment_md(packet.analysis))
