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

- `aw install` installs AW skills from `https://github.com/antonyjclements/augmented-workflow` into `~/.agents/skills` and links supported agent skill directories to that global installation.
- `aw init` scaffolds or updates AW repo files directly from the AW source for the current directory. It installs gates and enables tracking, telemetry, trace, workflow trace, and behavior pins by default. It asks before replacing every changed existing file; pass `--force` to accept all replacements.
- `aw upgrade` adds missing scaffold files and replaces changed `.scripts/aw-gate.js`, `docs/workflow/config.yml`, `AGENTS.md`, and `.augmented-workflow-version` without prompting. Other existing files are preserved. Before replacing a changed config, it saves `docs/workflow/config.yml.bak` (or `.bak.1`, `.bak.2`, etc. if earlier backups exist). It uses the same source and config defaults as `aw init`; use `--repo` to target another repository.
- `aw --version` prints the CLI release version. `aw status` and `aw doctor` print both the CLI version and their respective installed AW version.
- `aw metrics` opens a Textual TUI over `docs/metrics/*.jsonl` with hourly and weekday activity charts, skill usage, workflow-session coverage, and a purple activity heatmap.
- `aw update` reinstalls the CLI from its GitHub source with `pipx`; use `--dry-run` to see the command first.
- `aw doctor` reports global skill installation health.
- `aw status` reports the local repo installation state.

The default AW source archive is `https://github.com/antonyjclements/augmented-workflow/archive/refs/heads/main.tar.gz`. Override it with `--source-url` / `AW_SOURCE_URL`, or use a local checkout with `--source` / `AW_SOURCE_DIR`.

## Requirements

- Python 3.11+
- `pipx`

## Development

```sh
python3 -m pip install -e ".[dev]"
python3 -m unittest discover -s tests
```
