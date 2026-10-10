from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InstalledSkills:
    source: Path
    skills_dir: Path
    skill_names: list[str]
    links: list[Path]


def discover_aw_skills(source_dir: Path) -> list[Path]:
    skills_root = source_dir / "skills"
    if not skills_root.is_dir():
        raise FileNotFoundError(f"missing AW skills directory: {skills_root}")
    return sorted(path for path in skills_root.glob("aw-*") if (path / "SKILL.md").is_file())


def validate_migration_source(source_dir: Path) -> tuple[Path, dict, str]:
    scripts = source_dir / "skills" / "aw-init" / "scripts"
    helper = scripts / "migrate-skills.py"
    manifest = scripts / "bundled-skill-fingerprints.json"
    version_file = source_dir / "aw-version.txt"
    for path in (helper, manifest, version_file):
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"AW source does not support safe skill migration: missing {path}")
    version = version_file.read_text(encoding="utf-8").strip()
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match or tuple(map(int, match.groups())) < (0, 15, 0):
        raise ValueError(f"unsupported AW migration source version: {version!r}; require 0.15.0 or newer")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("skills"), dict):
        raise ValueError(f"unsupported AW skill fingerprint manifest: {manifest}")
    for name, digests in data["skills"].items():
        if (not re.fullmatch(r"aw-[a-z0-9][a-z0-9-]*", name)
                or not isinstance(digests, list) or not digests
                or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in digests)):
            raise ValueError(f"invalid AW skill fingerprint entry: {name!r}")
    # A source is trusted executable code, just like the source-provided helper
    # used by upstream install.sh. Probe its CLI contract without applying it.
    probe = subprocess.run([sys.executable, str(helper), "--help"], check=False, capture_output=True, text=True)
    if probe.returncode or any(flag not in probe.stdout for flag in ("--source", "--target", "--version", "--apply", "--dry-run", "--rollback")):
        detail = probe.stderr.strip() or "missing required migration options"
        raise ValueError(f"unsupported AW migration helper: {detail}")
    return helper, data, version


def install_aw_skills(
    source_dir: Path,
    skills_dir: Path,
    agent_links: list[Path],
    *,
    force: bool = False,
    dry_run: bool = False,
    rollback_skills: Path | None = None,
) -> InstalledSkills:
    source_dir = source_dir.expanduser().absolute()
    skills_dir = skills_dir.expanduser().absolute()
    for path in (skills_dir, *skills_dir.parents):
        if path.is_symlink():
            raise ValueError(f"unsafe skills directory symlink: {path}")
    skills_dir = skills_dir.resolve()
    helper, _, version = validate_migration_source(source_dir)
    discover_aw_skills(source_dir)
    command = [
        sys.executable, str(helper), "--source", str(source_dir / "skills"),
        "--target", str(skills_dir), "--version", version,
        "--dry-run" if dry_run else "--apply",
    ]
    if rollback_skills is not None:
        command.extend(["--rollback", str(rollback_skills)])
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.returncode:
        detail = result.stderr.strip() or f"helper exited with status {result.returncode}"
        raise RuntimeError(f"AW skill migration failed: {detail}")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    if rollback_skills is not None:
        return InstalledSkills(source=source_dir, skills_dir=skills_dir, skill_names=[], links=[])

    # The reviewed helper reports only content-verified managed entries here.
    # Discovering source names would incorrectly count preserved custom skills.
    installed_names = sorted(
        match.group(1) for line in result.stdout.splitlines()
        if (match := re.fullmatch(r"(?:install|update|preserve managed): (aw-[a-z0-9][a-z0-9-]*)", line))
    )

    linked: list[Path] = []
    for link in agent_links:
        if dry_run:
            linked.append(link)
            continue
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            if link.resolve() == skills_dir.resolve():
                linked.append(link)
                continue
            if force:
                link.unlink()
            else:
                continue
        elif link.exists():
            continue
        link.symlink_to(skills_dir)
        linked.append(link)

    return InstalledSkills(source=source_dir, skills_dir=skills_dir, skill_names=installed_names, links=linked)
