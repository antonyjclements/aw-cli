from __future__ import annotations

import os
from pathlib import Path

DEFAULT_SOURCE_URL = "https://github.com/antonyjclements/augmented-workflow/archive/refs/heads/main.tar.gz"
DEFAULT_AGENT_SKILL_LINKS = (
    Path("~/.claude/skills"),
    Path("~/.codeium/skills"),
    Path("~/.windsurf/skills"),
)


def source_dir(explicit: Path | None = None) -> Path:
    raw = explicit or os.environ.get("AW_SOURCE_DIR")
    if raw is None:
        raise ValueError("source_dir requires an explicit path or AW_SOURCE_DIR")
    return Path(raw).expanduser().resolve()


def source_url(explicit: str | None = None) -> str:
    return explicit or os.environ.get("AW_SOURCE_URL") or DEFAULT_SOURCE_URL


def skills_dir(explicit: Path | None = None) -> Path:
    raw = explicit or os.environ.get("AW_SKILLS_DIR") or Path("~/.agents/skills")
    return Path(raw).expanduser()


def agent_skill_links(explicit: list[Path] | None = None) -> list[Path]:
    if explicit:
        return [path.expanduser() for path in explicit]
    env_value = os.environ.get("AW_AGENT_SKILL_LINKS")
    if env_value:
        return [Path(path).expanduser() for path in env_value.split(os.pathsep) if path]
    return [path.expanduser() for path in DEFAULT_AGENT_SKILL_LINKS]
