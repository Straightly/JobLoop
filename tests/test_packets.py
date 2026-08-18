from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from jobloop.core.gap_assessment import GapItem, PacketAnalysis, ResumeRecommendation
from jobloop.core.packets import (
    build_gap_user_prompt,
    build_job_post_md,
    build_packet,
    render_gap_assessment_md,
    save_packet,
)
from jobloop.core.posting import NormalizedPosting


def make_posting(**overrides):
    kwargs = dict(
        source="USAJOBS",
        job_id="1",
        title="IT Specialist (AI)",
        company="Dept of Example",
        team_org="Example Bureau",
        location="Remote",
        url="https://example.com/1",
        date_captured=date(2026, 8, 17),
        required_qualifications=("5 years AI experience",),
        hard_requirements=("US citizen",),
    )
    kwargs.update(overrides)
    return NormalizedPosting(**kwargs)


@dataclass
class FakeAnalyzer:
    price_per_input_token_usd: float = 0.0
    price_per_output_token_usd: float = 0.0

    def analyze(self, *, job_id, system_prompt, user_prompt):
        self.last_call = dict(job_id=job_id, system_prompt=system_prompt, user_prompt=user_prompt)
        gaps = (
            GapItem(
                requirement="5 years AI experience",
                status="have",
                evidence="production LLM workflows at AthenaHealth",
                gap_type="none",
                mitigation="none",
            ),
        )
        return PacketAnalysis(
            job_id=job_id,
            gaps=gaps,
            resume_recommendation=ResumeRecommendation(
                filename="zhian-federal-resume.md", justification="already federal-shaped"
            ),
            input_tokens=100,
            output_tokens=100,
            estimated_cost_usd=0.001,
        )


def test_build_job_post_md_includes_key_fields():
    md = build_job_post_md(make_posting())
    assert "IT Specialist (AI)" in md
    assert "Job ID: 1" in md
    assert "https://example.com/1" in md
    assert "5 years AI experience" in md
    assert "US citizen" in md


def test_build_job_post_md_handles_empty_qualifications():
    posting = make_posting(required_qualifications=(), hard_requirements=())
    md = build_job_post_md(posting)
    assert "(not captured)" in md


def test_build_gap_user_prompt_includes_resume_candidates():
    prompt = build_gap_user_prompt(
        make_posting(), "profile text", [("zhian-federal-resume.md", "Zhi An -- Federal Resume")]
    )
    assert "zhian-federal-resume.md: Zhi An -- Federal Resume" in prompt
    assert "profile text" in prompt


def test_build_gap_user_prompt_handles_no_candidates():
    prompt = build_gap_user_prompt(make_posting(), "profile", [])
    assert "(none available)" in prompt


def test_build_packet_calls_analyzer_with_job_id():
    analyzer = FakeAnalyzer()
    packet = build_packet(make_posting(), "profile", analyzer, resume_dir=Path("/nonexistent"))
    assert packet.job_id == "1"
    assert analyzer.last_call["job_id"] == "1"
    assert packet.analysis.resume_recommendation.filename == "zhian-federal-resume.md"


def test_render_gap_assessment_md_includes_table_and_recommendation():
    analysis = FakeAnalyzer().analyze(job_id="1", system_prompt="s", user_prompt="u")
    md = render_gap_assessment_md(analysis)
    assert "zhian-federal-resume.md" in md
    assert "already federal-shaped" in md
    assert "5 years AI experience" in md
    assert "have" in md


def test_render_gap_assessment_md_escapes_pipes_and_newlines():
    gaps = (
        GapItem(
            requirement="req | with pipe",
            status="have",
            evidence="line one\nline two",
            gap_type="none",
            mitigation="none",
        ),
    )
    analysis = PacketAnalysis(
        job_id="1",
        gaps=gaps,
        resume_recommendation=ResumeRecommendation(filename="x.md", justification="y"),
        input_tokens=1,
        output_tokens=1,
        estimated_cost_usd=0.0,
    )
    md = render_gap_assessment_md(analysis)
    assert "req \\| with pipe" in md
    assert "line one line two" in md


def test_resume_candidates_reads_loose_md_files_and_skips_subfolders(tmp_path):
    from jobloop.core.packets import _resume_candidates

    resume_dir = tmp_path / "Resume"
    resume_dir.mkdir()
    (resume_dir / "zhian-federal-resume.md").write_text("# Zhi An -- Federal Resume\n\nbody\n")
    (resume_dir / "zhian-resume.docx").write_bytes(b"not markdown")
    (resume_dir / "00-Master-Inventory").mkdir()
    (resume_dir / "00-Master-Inventory" / "Master-Skills-Inventory.md").write_text("# skills\n")

    candidates = _resume_candidates(resume_dir)
    assert candidates == [("zhian-federal-resume.md", "# Zhi An -- Federal Resume")]


def test_resume_candidates_missing_dir_returns_empty(tmp_path):
    from jobloop.core.packets import _resume_candidates

    assert _resume_candidates(tmp_path / "nope") == []


def test_save_packet_writes_both_files(tmp_path):
    analysis = FakeAnalyzer().analyze(job_id="1", system_prompt="s", user_prompt="u")
    from jobloop.core.packets import Packet

    packet = Packet(job_id="1", job_post_md="# Title\n", analysis=analysis)
    packet_dir = tmp_path / "packets" / "1"
    save_packet(packet, packet_dir)

    assert (packet_dir / "Job-Post.md").read_text() == "# Title\n"
    assert "zhian-federal-resume.md" in (packet_dir / "Gap-Assessment.md").read_text()
    assert not (packet_dir / "Job-Post.md.tmp").exists()
