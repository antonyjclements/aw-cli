from __future__ import annotations

import argparse

from aw_cli.config import agent_skill_links, skills_dir, source_url
from aw_cli.installer import discover_aw_skills
from aw_cli.source import prepared_source


def run(args: argparse.Namespace) -> int:
    target_skills = skills_dir(args.skills_dir)
    links = agent_skill_links(args.agent_dir)
    remote_url = source_url(args.source_url)
    source_label = str(args.source) if args.source else remote_url

    with prepared_source(source=args.source, source_url=remote_url) as source:
        expected = [path.name for path in discover_aw_skills(source)]
    installed = sorted(path.name for path in target_skills.glob("aw-*") if (path / "SKILL.md").is_file()) if target_skills.is_dir() else []
    missing = sorted(set(expected) - set(installed))
    extra = sorted(set(installed) - set(expected))
    version_file = target_skills / "aw-version.txt"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "missing"

    print("AW Doctor")
    print(f"Source: {source_label}")
    print(f"Skills dir: {target_skills}")
    print(f"Installed version: {version}")
    print(f"Expected skills: {len(expected)}")
    print(f"Installed skills: {len(installed)}")
    print(f"Missing skills: {', '.join(missing) if missing else 'none'}")
    print(f"Extra aw-* skills: {', '.join(extra) if extra else 'none'}")
    for link in links:
        if link.is_symlink():
            print(f"Link: {link} -> {link.readlink()}")
        elif link.exists():
            print(f"Link: {link} is a non-symlink")
        else:
            print(f"Link: {link} missing")

    return 1 if missing else 0
