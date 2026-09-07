from __future__ import annotations

import argparse
import json
from pathlib import Path

from aw_cli.config import source_url
from aw_cli.source import prepared_source
from aw_cli.workflow_config import with_cli_default_aw_features

ARTIFACTS = {
    "AGENTS.md": "AGENTS.md",
    "CLAUDE.md": "CLAUDE.md",
    "docs/product/prds/template.md": "prd-template.md",
    "docs/standards/coding-approach.md": "coding-approach.md",
    "docs/standards/traceability.md": "traceability.md",
    "docs/standards/behavior-pinning.md": "behavior-pinning.md",
    "docs/standards/e2e-coverage.md": "e2e-coverage.md",
    "docs/solutions/README.md": "solutions-readme.md",
    "docs/workflow/README.md": "workflow-readme.md",
    "docs/workflow/field-guide.md": "field-guide.md",
    "docs/workflow/gates.md": "gates.md",
    "docs/workflow/org-knowledge.md": "org-knowledge.md",
    "docs/workflow/tracking.md": "tracking.md",
    "docs/metrics/README.md": "metrics-readme.md",
    "docs/workflow/config.yml": "config.yml",
    ".scripts/aw-gate.js": "aw-gate.js",
}
GENERATED = {
    "docs/product/prds/index.yml": "prds: []\n",
    "docs/features/index.yml": "features: []\n",
    "docs/standards/index.yml": "standards: []\n",
    "docs/decisions/index.yml": "decisions: []\n",
    "docs/learnings/index.yml": "learnings: []\n",
}
GITIGNORE = (".aw-gate-state.json", ".aw/receipts/", ".aw-org-cache/", ".aw/tmp/", ".aw/workflow-trace.jsonl", ".aw/pin/", ".aw/session")
GITATTRIBUTES = ("docs/metrics/events*.jsonl merge=union", "docs/metrics/skills*.jsonl merge=union")
HOOK_COMMAND = "$CLAUDE_PROJECT_DIR/.claude/hooks/log-session.sh"


def run(args: argparse.Namespace) -> int:
    repo = args.repo.expanduser().resolve()
    with prepared_source(source=args.source, source_url=source_url(args.source_url)) as source:
        try:
            RepoScaffolder(repo, source, force=args.force).install()
        except FileNotFoundError as exc:
            print(f"Missing AW scaffold source: {exc}")
            return 1
    print(f"Initialized AW repository: {repo}")
    return 0


class RepoScaffolder:
    def __init__(self, repo: Path, source: Path, *, force: bool) -> None:
        self.repo, self.source, self.force = repo, source, force

    def install(self) -> None:
        artifacts = self.source / "skills" / "aw-init" / "artifacts"
        version = self._text(self.source / "aw-version.txt").strip()
        if not artifacts.is_dir() or not version:
            raise FileNotFoundError(artifacts if not artifacts.is_dir() else self.source / "aw-version.txt")
        for destination, artifact in ARTIFACTS.items():
            content = self._text(artifacts / artifact)
            if destination == "AGENTS.md":
                content = _with_version(content, version)
            if destination == "docs/workflow/config.yml":
                content = with_cli_default_aw_features(content)
            self.write(destination, content, executable=destination == ".scripts/aw-gate.js")
        for destination, content in GENERATED.items():
            self.write(destination, content)
        self.write(".augmented-workflow-version", f"{version}\n")
        hook = self.source / "skills" / "aw-init" / "hooks" / "log-session.sh"
        if hook.is_file():
            self.write(".claude/hooks/log-session.sh", self._text(hook), executable=True)
            self._settings()
        self._merge(".gitignore", GITIGNORE)
        self._merge(".gitattributes", GITATTRIBUTES)

    def write(self, relative: str, content: str, *, executable: bool = False) -> bool:
        target = self.repo / relative
        if target.exists() and target.is_dir():
            print(f"preserve: {relative} (directory)")
            return False
        if target.is_file() and target.read_text(encoding="utf-8") == content:
            print(f"unchanged: {relative}")
            return False
        if target.exists() and not self._confirm(relative):
            print(f"preserve: {relative}")
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if executable:
            target.chmod(target.stat().st_mode | 0o111)
        print(f"write: {relative}")
        return True

    def _settings(self) -> None:
        path = self.repo / ".claude/settings.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except json.JSONDecodeError:
            data = {}
        stops = data.setdefault("hooks", {}).setdefault("Stop", [])
        if not any(hook.get("command") == HOOK_COMMAND for item in stops for hook in item.get("hooks", [])):
            stops.append({"hooks": [{"type": "command", "command": HOOK_COMMAND}]})
        self.write(".claude/settings.json", json.dumps(data, indent=2) + "\n")

    def _merge(self, relative: str, entries: tuple[str, ...]) -> None:
        target = self.repo / relative
        lines = target.read_text(encoding="utf-8").splitlines() if target.is_file() else []
        missing = [entry for entry in entries if entry not in lines]
        if missing:
            self.write(relative, "\n".join(lines + missing) + "\n")

    def _confirm(self, relative: str) -> bool:
        if self.force:
            return True
        try:
            return input(f"Overwrite existing {relative}? [y/N] ").strip().lower() in {"y", "yes"}
        except EOFError:
            return False

    @staticmethod
    def _text(path: Path) -> str:
        if not path.is_file():
            raise FileNotFoundError(path)
        return path.read_text(encoding="utf-8")


def _with_version(content: str, version: str) -> str:
    marker = "AUGMENTED_WORKFLOW_VERSION="
    return "\n".join(f"{marker}{version}" if line.startswith(marker) else line for line in content.splitlines()) + "\n"
