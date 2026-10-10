from __future__ import annotations

import argparse

from aw_cli.commands.init_repo import RepoScaffolder
from aw_cli.config import source_url
from aw_cli.source import prepared_source


def run(args: argparse.Namespace) -> int:
    repo = args.repo.expanduser().resolve()
    try:
        with prepared_source(source=args.source, source_url=source_url(args.source_url)) as source:
            RepoScaffolder(repo, source, force=False, upgrade=True).install()
    except OSError as exc:
        print(f"AW repository upgrade failed: {exc}")
        return 1
    print(f"Upgraded AW repository: {repo}")
    return 0
