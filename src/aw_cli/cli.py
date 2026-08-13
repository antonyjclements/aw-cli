from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aw_cli.commands import doctor, init_repo, install, metrics, status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aw", description="Augmented Workflow CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser("install", help="Install AW skills globally")
    install_parser.add_argument("--source", type=Path, help="Augmented Workflow source directory")
    install_parser.add_argument("--source-url", help="Augmented Workflow source archive URL")
    install_parser.add_argument("--skills-dir", type=Path, help="Global skills directory")
    install_parser.add_argument("--agent-dir", action="append", type=Path, help="Agent directory to receive a skills symlink")
    install_parser.add_argument("--force", action="store_true", help="Replace conflicting symlinks")
    install_parser.add_argument("--dry-run", action="store_true", help="Show what would change")

    init_parser = subparsers.add_parser("init", help="Install AW repo files into the current directory")
    init_parser.add_argument("--source", type=Path, help="Augmented Workflow source directory")
    init_parser.add_argument("--source-url", help="Augmented Workflow source archive URL")
    init_parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Target repo directory")
    init_parser.add_argument("--force", action="store_true", help="Pass --force to the AW installer")

    metrics_parser = subparsers.add_parser("metrics", help="Open workflow metrics TUI")
    metrics_parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Repo containing docs/metrics")

    doctor_parser = subparsers.add_parser("doctor", help="Show global AW skill installation health")
    doctor_parser.add_argument("--source", type=Path, help="Augmented Workflow source directory")
    doctor_parser.add_argument("--source-url", help="Augmented Workflow source archive URL")
    doctor_parser.add_argument("--skills-dir", type=Path, help="Global skills directory")
    doctor_parser.add_argument("--agent-dir", action="append", type=Path, help="Agent directory to inspect")

    status_parser = subparsers.add_parser("status", help="Show local repo AW installation status")
    status_parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Repo to inspect")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "install":
            return install.run(args)
        if args.command == "init":
            return init_repo.run(args)
        if args.command == "metrics":
            return metrics.run(args)
        if args.command == "doctor":
            return doctor.run(args)
        if args.command == "status":
            return status.run(args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
