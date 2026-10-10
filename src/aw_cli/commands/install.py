from __future__ import annotations

import argparse
import sys

from aw_cli.config import agent_skill_links, skills_dir, source_url, selected_source
from aw_cli.installer import install_aw_skills
from aw_cli.source import prepared_source


def run(args: argparse.Namespace) -> int:
    target_skills = skills_dir(args.skills_dir)
    links = agent_skill_links(args.agent_dir)
    remote_url = source_url(args.source_url)
    local_source = selected_source(args.source, args.source_url)
    source_label = str(local_source) if local_source else remote_url

    rollback_skills = getattr(args, "rollback_skills", None)
    try:
        with prepared_source(source=local_source, source_url=remote_url) as source:
            result = install_aw_skills(
                source, target_skills, links, force=args.force, dry_run=args.dry_run,
                rollback_skills=rollback_skills,
            )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"AW install stopped: {error}", file=sys.stderr)
        return 1

    if rollback_skills is not None:
        verb = "Would roll back" if args.dry_run else "Rolled back"
        print(f"{verb} AW skills using {rollback_skills}")
        return 0

    verb = "Would install" if args.dry_run else "Installed"
    print(f"{verb} {len(result.skill_names)} AW skills from {source_label}")
    print(f"Global skills: {result.skills_dir}")
    for name in result.skill_names:
        print(f"  skill: {name}")
    for link in result.links:
        print(f"  link: {link} -> {result.skills_dir}")
    return 0
