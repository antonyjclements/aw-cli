from __future__ import annotations

import shutil
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


def install_aw_skills(
    source_dir: Path,
    skills_dir: Path,
    agent_links: list[Path],
    *,
    force: bool = False,
    dry_run: bool = False,
) -> InstalledSkills:
    skill_paths = discover_aw_skills(source_dir)
    version_file = source_dir / "aw-version.txt"

    if not dry_run:
        skills_dir.mkdir(parents=True, exist_ok=True)
        if version_file.is_file():
            shutil.copy2(version_file, skills_dir / "aw-version.txt")

    installed_names: list[str] = []
    for skill_path in skill_paths:
        installed_names.append(skill_path.name)
        dest = skills_dir / skill_path.name
        if dry_run:
            continue
        if dest.exists() or dest.is_symlink():
            if dest.is_dir() and not dest.is_symlink():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        shutil.copytree(skill_path, dest)

    if not dry_run:
        manifest = skills_dir / ".augmented-workflow-skills"
        manifest.write_text("\n".join(installed_names) + "\n", encoding="utf-8")

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
