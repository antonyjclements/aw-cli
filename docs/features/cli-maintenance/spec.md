# CLI maintenance and metrics

### CLIM-001 — Update the installed CLI

`aw update` reinstalls the CLI from its GitHub source using
`pipx install --force git+https://github.com/antonyjclements/aw-cli.git`.
`--dry-run` displays the command without executing it. Missing pipx returns 1;
pipx failures propagate their exit code. Success reports completion.

Verification: update dry-run and subprocess dispatch tests in `tests/test_cli.py`;
failure paths checked against the command implementation without updating the
developer's installed CLI.

### CLIM-002 — Display metrics without a plotting dependency

`aw metrics` uses Textual and text-rendered purple charts for hourly activity,
weekday activity, and skill usage. Workflow session coverage and the activity
heatmap remain available. The dashboard scrolls when terminal height is limited.
An empty dataset displays no-activity messages. `textual-plot` is not required.

Verification: aggregation and chart rendering tests in `tests/test_cli.py`, plus
headless Textual mount checks against repository metrics at 120×40 and 80×24.

### CLIM-003 — Report release 0.3.0

Package metadata and `aw --version` report CLI version 0.3.0.

Verification: existing version tests and package metadata inspection.
