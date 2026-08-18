"""JobLoop command line.

Only `doctor` is implemented so far — deliberately. It is the startup
validation from spec v4 §9, and it exists before any feature because the thing
that broke the previous agent was not a bug in its logic: it was a moved file
that nothing checked for, under a scheduled job that kept firing anyway.
"""

from __future__ import annotations

import argparse
import sys

from .core.config import Config
from .core.errors import JobLoopError

# Credentials the scheduled Monday run cannot proceed without.
RUN_SECRETS = ("USAJOBS_API_KEY", "USAJOBS_USER_AGENT", "ANTHROPIC_API_KEY")


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
