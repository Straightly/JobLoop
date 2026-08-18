"""JobLoop command line.

`doctor` is the startup validation from spec v4 §9, and it exists before any
feature because the thing that broke the previous agent was not a bug in its
logic: it was a moved file that nothing checked for, under a scheduled job
that kept firing anyway. `run` executes one lane's full weekly pipeline --
what `launchd` calls Monday 08:00 (spec v4 §7), and what you'd run by hand
otherwise.
"""

from __future__ import annotations

import argparse
import sys

from .core.config import Config
from .core.errors import JobLoopError

# Credentials the scheduled Monday run cannot proceed without.
# OpenAI, not spec v4 §9's default of Claude -- Zhi An's call, 2026-08-17.
RUN_SECRETS = ("USAJOBS_API_KEY", "USAJOBS_USER_AGENT", "OPENAI_API_KEY")

#: Lanes with a real pipeline wired up. Only federal-ai-roles so far --
#: the other three are `pending` (spec v4 §4's lane table), not yet ported.
RUNNABLE_LANES = ("federal-ai-roles",)


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = Config.load()
    required = () if args.no_secrets else RUN_SECRETS

    print("JobLoop doctor")
    print(f"  CODE   {cfg.code_root}")
    print(f"  CAREER {cfg.career_root}")
    print(f"  DATA   {cfg.data_root}")
    print(f"  lanes  {cfg.lanes_dir}")
    print()

    problems = cfg.validate(require_secrets=required)
    if not problems:
        print("OK — all roots resolve and every required credential is loadable.")
        return 0

    print(f"FAILED — {len(problems)} problem(s):", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1


def cmd_run(args: argparse.Namespace) -> int:
    cfg = Config.load()
    # Fail loudly before doing anything, same reasoning as `doctor` (spec v4
    # §9) -- this is the check that would have caught the original breakage
    # on day one, and it's exactly what an unattended launchd run needs.
    cfg.require_valid(require_secrets=RUN_SECRETS)

    if args.lane == "federal-ai-roles":
        from .lanes.federal_ai_roles import pipeline

        result = pipeline.run(cfg, picks=args.picks)
    else:
        print(f"error: lane {args.lane!r} has no pipeline wired up yet", file=sys.stderr)
        return 1

    print(
        f"fetched={result.fetch.fetched} kept={result.fetch.kept} "
        f"scored={len(result.scoring.results)} selected={list(result.selected_job_ids)} "
        f"cost=${result.total_cost_usd:.4f}"
    )
    print(f"status: {cfg.status_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobloop", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser(
        "doctor", help="validate roots and credentials; run this before anything else"
    )
    doctor.add_argument(
        "--no-secrets",
        action="store_true",
        help="check roots only, skip credential checks",
    )
    doctor.set_defaults(func=cmd_doctor)

    run = sub.add_parser("run", help="run one lane's full weekly pipeline")
    run.add_argument("lane", choices=RUNNABLE_LANES, help="which lane to run")
    run.add_argument(
        "--picks", type=int, default=1, help="top-N picks to select (0-3; default 1, spec v4 B4)"
    )
    run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except JobLoopError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
