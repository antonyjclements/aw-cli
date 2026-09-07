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
pipx upgrade aw-cli
```

To remove it:

```sh
pipx uninstall aw-cli
```

## Commands

- `aw install` installs AW skills from `https://github.com/antonyjclements/augmented-workflow` into `~/.agents/skills` and links supported agent skill directories to that global installation.
- `aw init` scaffolds or updates AW repo files directly from the AW source for the current directory. It installs gates and enables tracking, telemetry, trace, workflow trace, and behavior pins by default. It asks before replacing every changed existing file; pass `--force` to accept all replacements.
- `aw metrics` opens a Textual TUI over `docs/metrics/*.jsonl` with `textual-plot` hourly activity, gate event bars, skill usage, workflow-session compliance, and a GitHub-style activity heatmap.
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
