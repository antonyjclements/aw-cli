from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_PATHS = (
    "AGENTS.md",
    "CLAUDE.md",
    "docs/workflow/config.yml",
    "docs/standards/index.yml",
    "docs/features/index.yml",
    "docs/decisions/index.yml",
    "docs/learnings/index.yml",
    "docs/metrics/README.md",
)


def run(args: argparse.Namespace) -> int:
    repo = args.repo.expanduser().resolve()
    version = _read_text(repo / ".augmented-workflow-version") or "missing"

    print("AW Status")
    print(f"Repo: {repo}")
    print(f"Version: {version.strip()}")

    missing = []
    for relative in REQUIRED_PATHS:
        path = repo / relative
        state = "ok" if path.exists() else "missing"
        print(f"{state}: {relative}")
        if not path.exists():
            missing.append(relative)

    settings = repo / ".claude" / "settings.json"
    if settings.exists():
        print(f"Claude hooks: {'ok' if _has_session_hook(settings) else 'missing Stop hook'}")
    else:
        print("Claude hooks: missing settings")

    metrics_dir = repo / "docs" / "metrics"
    metrics_files = sorted(metrics_dir.glob("*.jsonl")) if metrics_dir.is_dir() else []
    print(f"Metrics files: {len(metrics_files)}")
    return 1 if missing else 0


def _read_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _has_session_hook(path: Path) -> bool:
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    stop_hooks = settings.get("hooks", {}).get("Stop", [])
    return any(
        "$CLAUDE_PROJECT_DIR/.claude/hooks/log-session.sh" == hook.get("command")
        for entry in stop_hooks
        for hook in entry.get("hooks", [])
    )
