"""Three-root configuration and credential resolution.

Spec v4 §3. Nothing here is hardcoded to a machine: every root comes from an
environment variable with a documented default, and everything inside a root is
addressed relatively. Moving a root must not break the agent.

    CODE    ~/Projects/JobLoop            public repo; code only
    CAREER  ~/Projects/attention/career   your artifacts AND all agent config
    DATA    ~/Data/JobLoop                generated output only, no history

The test that decides where a file belongs: if you typed it, it isn't DATA.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError, CredentialError

DEFAULT_CODE_ROOT = "~/Projects/JobLoop"
DEFAULT_CAREER_ROOT = "~/Projects/attention/career"
DEFAULT_DATA_ROOT = "~/Data/JobLoop"

#: Where agent config lives inside CAREER (rule 4 artifacts).
DEV_SUBDIR = "JobLoopDev"
LANES_SUBDIR = f"{DEV_SUBDIR}/lanes"


def _resolve(env_var: str, default: str) -> Path:
    return Path(os.environ.get(env_var) or default).expanduser()


def load_env_file(code_root: Path) -> dict[str, str]:
    """Read key=value pairs from the first env file that exists.

    Resolution order, most specific first:

      1. $JOBLOOP_ENV_FILE      explicit override
      2. <CODE_ROOT>/.env       where Zhi An keeps it
      3. ~/.config/jobloop/env  XDG-conventional fallback

    Real environment variables always win over file contents — the file never
    clobbers something already exported.

    This exists because launchd does not inherit your shell environment. A key
    exported in .zshrc works when you test by hand and is absent at 08:00
    Monday, so the process must read the file itself.
    """
    candidates = []
    if explicit := os.environ.get("JOBLOOP_ENV_FILE"):
        candidates.append(Path(explicit).expanduser())
    candidates.append(code_root / ".env")
    candidates.append(Path("~/.config/jobloop/env").expanduser())

    for path in candidates:
        if not path.is_file():
            continue
        values: dict[str, str] = {}
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("'\"")
        return values
    return {}


@dataclass(frozen=True)
class Config:
    code_root: Path
    career_root: Path
    data_root: Path
    _secrets: dict[str, str]

    @classmethod
    def load(cls) -> "Config":
        code_root = _resolve("JOBLOOP_CODE_ROOT", DEFAULT_CODE_ROOT)
        return cls(
            code_root=code_root,
            career_root=_resolve("JOBLOOP_CAREER_ROOT", DEFAULT_CAREER_ROOT),
            data_root=_resolve("JOBLOOP_DATA_ROOT", DEFAULT_DATA_ROOT),
            _secrets=load_env_file(code_root),
        )

    # -- derived paths ----------------------------------------------------

    @property
    def lanes_dir(self) -> Path:
        """Lane config and ledgers. In CAREER, because you author them."""
        return self.career_root / LANES_SUBDIR

    @property
    def profile_path(self) -> Path:
        return self.career_root / DEV_SUBDIR / "profile.yaml"

    @property
    def global_index_path(self) -> Path:
        """Derived each run by merging lane ledgers with Application-Index.md."""
        return self.data_root / "global-index.json"

    @property
    def status_path(self) -> Path:
        return self.data_root / "LAST-RUN-STATUS.md"

    def lane_data(self, lane: str) -> Path:
        return self.data_root / lane

    def lane_config(self, lane: str) -> Path:
        return self.lanes_dir / lane

    # -- credentials ------------------------------------------------------

    def secret(self, name: str, *, required: bool = True) -> str | None:
        """Fetch a credential. Real env vars take precedence over the env file."""
        value = os.environ.get(name) or self._secrets.get(name)
        if value:
            return value
        if required:
            raise CredentialError(
                f"{name} not found. Set it in the environment, "
                f"$JOBLOOP_ENV_FILE, {self.code_root / '.env'}, "
                f"or ~/.config/jobloop/env"
            )
        return None

    # -- validation -------------------------------------------------------

    def validate(self, *, require_secrets: tuple[str, ...] = ()) -> list[str]:
        """Check everything the run depends on. Returns a list of problems.

        This is the check that would have caught the original breakage on day
        one: the old agent's script had been moved out from under a launchd job
        that kept firing weekly into a path that no longer existed, and nothing
        ever noticed.
        """
        problems: list[str] = []

        for label, path in (
            ("CODE", self.code_root),
            ("CAREER", self.career_root),
            ("DATA", self.data_root),
        ):
            if not path.exists():
                problems.append(f"{label} root does not exist: {path}")
            elif not path.is_dir():
                problems.append(f"{label} root is not a directory: {path}")

        if self.data_root.is_dir() and not os.access(self.data_root, os.W_OK):
            problems.append(f"DATA root is not writable: {self.data_root}")

        if self.career_root.is_dir() and not self.lanes_dir.is_dir():
            problems.append(f"lane config directory missing: {self.lanes_dir}")

        for name in require_secrets:
            try:
                self.secret(name)
            except CredentialError as exc:
                problems.append(str(exc))

        return problems

    def require_valid(self, *, require_secrets: tuple[str, ...] = ()) -> None:
        """Validate and raise loudly on any problem."""
        if problems := self.validate(require_secrets=require_secrets):
            raise ConfigError(
                "startup validation failed:\n  - " + "\n  - ".join(problems)
            )
