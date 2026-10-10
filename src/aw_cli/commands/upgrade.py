from __future__ import annotations

import argparse

from aw_cli.config import source_url, selected_source
from aw_cli.repo_upgrade import check_path, upgrade_repository
from aw_cli.source import prepared_source


def run(args: argparse.Namespace) -> int:
    repo = args.repo.expanduser().absolute()
    try:
        check_path(repo)
        with prepared_source(source=selected_source(args.source, args.source_url), source_url=source_url(args.source_url)) as source:
            upgrade_repository(repo, source, dry_run=args.dry_run)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'AW repository upgrade failed: {exc}')
        return 1
    print(f'{"Would upgrade" if args.dry_run else "Upgraded"} AW repository: {repo}')
    return 0
