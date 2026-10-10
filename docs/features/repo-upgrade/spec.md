# Repository upgrade

`aw upgrade` refreshes an existing repository from the same AW scaffold source
used by `aw init`. It accepts `--repo`, `--source`, and `--source-url`.

### UPGR-001 — Add missing scaffold files

Upgrade creates missing files from the initializer's artifact and generated-file
sets, including optional hooks and supporting dotfiles. It preserves existing
files outside the replacement set, including populated indexes and custom hooks,
without prompting. Existing directories at file destinations are preserved.

### UPGR-002 — Replace selected workflow files

Upgrade replaces changed `.scripts/aw-gate.js`, `docs/workflow/config.yml`,
`AGENTS.md`, and `.augmented-workflow-version` without prompting. Content and
executable permissions follow initialization, including CLI config defaults and
the source version. Identical files are left untouched.

### UPGR-003 — Back up changed configuration

Before replacing an existing changed config, upgrade saves its exact bytes beside
it as `config.yml.bak`. If that path exists, it chooses the first available
`config.yml.bak.N`, starting with 1. Previous backups are never overwritten.
Missing or identical configs do not produce backups. A backup failure prevents
configuration replacement and returns a nonzero exit code.

### UPGR-004 — Report upgrade results

The command reports writes, preserved files, unchanged files, and backup paths,
then confirms the target repository. Missing source artifacts return a nonzero
exit code. `aw update` continues to update the CLI itself.

## Acceptance verification

Coverage lives in `tests/test_upgrade.py`:

- UPGR-001: missing-file and customization tests, plus optional-hook and directory
  conflict coverage.
- UPGR-002: selected replacements, executable gate, config defaults, and repeated
  runs that leave identical files untouched.
- UPGR-003: exact-byte backups, successive backup names, no backup for missing or
  identical config, and a simulated backup failure.
- UPGR-004: CLI dispatch, result messages, and missing-source failure.
