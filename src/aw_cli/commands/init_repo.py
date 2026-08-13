from __future__ import annotations

import argparse
import subprocess

from aw_cli.config import source_url
from aw_cli.source import prepared_source
from aw_cli.workflow_config import enable_default_aw_features


def run(args: argparse.Namespace) -> int:
    repo = args.repo.expanduser().resolve()
    with prepared_source(source=args.source, source_url=source_url(args.source_url)) as source:
        installer = source / "skills" / "aw-init" / "scripts" / "install.sh"
        if not installer.is_file():
            print(f"Missing AW installer: {installer}")
            return 1

        command = [
            str(installer),
            "--with-gates",
            "--skip-skills",
            "--repo",
            str(repo),
        ]
        if args.force:
            command.append("--force")

        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            return completed.returncode

    changed = enable_default_aw_features(repo / "docs" / "workflow" / "config.yml")
    print("Enabled AW defaults: tracking, telemetry, trace, workflow_trace, pin" if changed else "AW defaults already enabled")
    return 0
