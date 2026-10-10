from __future__ import annotations

import argparse
import subprocess


CLI_SOURCE = "git+https://github.com/antonyjclements/aw-cli.git"


def run(args: argparse.Namespace) -> int:
    command = ["pipx", "install", "--force", CLI_SOURCE]
    if args.dry_run:
        print("Would run: " + " ".join(command))
        return 0

    try:
        result = subprocess.run(command, check=False)
    except FileNotFoundError:
        print("pipx is required to update aw. Install pipx, then run: pipx install --force " + CLI_SOURCE)
        return 1

    if result.returncode:
        print("aw update failed. Re-run the command above for pipx's full diagnostics.")
        return result.returncode

    print("aw updated from GitHub. Start a new shell session to use the updated command.")
    return 0
