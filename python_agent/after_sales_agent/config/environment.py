from __future__ import annotations

import os
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def local_env_candidates() -> tuple[Path, ...]:
    """The local .env files this process may read, in priority order."""
    return (
        Path(__file__).resolve().parent / ".env",
        Path.cwd() / "python_agent" / ".env",
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    )


def read_local_env_file() -> dict[str, str]:
    """Read the local .env file into a mapping without touching os.environ.

    Reading a file must not have the side effect of mutating the process
    environment, and it must honour the same disable switch as
    :func:`load_agent_env` so the test session never sees local credentials.
    """
    if _env_bool("AGENT_ENV_DISABLED", False):
        return {}
    for path in local_env_candidates():
        if not path.is_file():
            continue
        values: dict[str, str] = {}
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            if name:
                values[name] = value.strip().strip('"').strip("'")
        return values
    return {}


def load_agent_env(
    *,
    override: bool | None = None,
    disabled: bool | None = None,
) -> Path | None:
    """Load local Agent settings without overriding deployment environment variables.

    ``disabled`` exists so the test session can keep the developer's local
    ``.env`` (which holds real credentials) out of the process entirely.
    """
    if disabled is None:
        disabled = _env_bool("AGENT_ENV_DISABLED", False)
    if disabled:
        return None
    should_override = _env_bool("AGENT_ENV_OVERRIDE", True) if override is None else override
    for path in local_env_candidates():
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip().strip('"').strip("'")
            if name:
                if should_override:
                    os.environ[name] = value
                else:
                    os.environ.setdefault(name, value)
        return path
    return None
