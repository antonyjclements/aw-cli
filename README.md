# AW CLI

Python command line interface for Augmented Workflow.

## Install

Install the CLI directly from GitHub with `pipx`:

```sh
pipx install git+https://github.com/antonyjclements/aw-cli.git
```

Then install the AW skills globally and initialize a repo:

```sh
aw install
aw init
```

To update an existing install:

```sh
aw update
```

To remove it:

```sh
pipx uninstall aw-cli
```

## Commands

- `aw install` safely migrates AW skills from `https://github.com/antonyjclements/augmented-workflow` into `~/.agents/skills`. Fingerprints preserve custom skills and back up verified retired bundled skills. Name collisions stop before writes, even with `--force`. Use `--dry-run` to preview. `--rollback-skills BACKUP` restores a retained skill transaction only; repository files and links are not rolled back. Retain the compatible source and use `--source` for offline rollback.
- `aw init` scaffolds or updates AW repo files directly from the AW source for the current directory. It installs gates and enables tracking, telemetry, trace, workflow trace, and behavior pins by default. It asks before replacing every changed existing file; pass `--force` to accept all replacements.
- `aw upgrade` safely migrates existing config and refreshes only content-verified AW files without prompting. Custom routing, providers, settings, hooks, and indexes are preserved; an unverified gate helper stops the upgrade for review. Every changed existing file receives a non-overwriting `.bak`/`.bak.N` backup. Use `--dry-run` to preview or `--repo` to target another repository. Ordinary write failures restore prior files; retain backups for manual recovery after process interruption.
- `aw --version` prints the CLI release version. `aw status` and `aw doctor` print both the CLI version and their respective installed AW version.
- `aw metrics` opens a Textual TUI over `docs/metrics/*.jsonl` with hourly and weekday activity charts, skill usage, workflow-session coverage, and a purple activity heatmap.
- `aw update` reinstalls the CLI from its GitHub source with `pipx`; use `--dry-run` to see the command first.
- `aw doctor` reports global skill installation health.
- `aw status` reports the local repo installation state.

The default AW source archive is `https://github.com/antonyjclements/augmented-workflow/archive/refs/heads/main.tar.gz`. Override it with `--source-url` / `AW_SOURCE_URL`, or use a local checkout with `--source` / `AW_SOURCE_DIR`. An explicit `--source-url` takes precedence over `AW_SOURCE_DIR`; explicit `--source` takes precedence over both. Archive symlinks, hard links, special files, and escaping paths are rejected.

## Requirements

- Python 3.11+
- `pipx`
- Ruby when upgrading an existing repository configuration
- AW source 0.15.0+ with the safe migration helpers and bundled fingerprints. Source helpers execute locally; use only trusted checkouts and archive URLs.

## Development

```sh
python3 -m pip install -e ".[dev]"
python3 -m pytest
```
