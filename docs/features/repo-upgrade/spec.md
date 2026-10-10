# Safe installation and repository upgrade

`aw upgrade` uses one prepared AW source, accepts `--repo`, `--source`,
`--source-url`, and `--dry-run`, and never prompts. `aw update` still only updates
aw-cli. `aw init` retains its interactive scaffolding contract.

### UPGR-001 — Preserve local work

Add missing scaffold files. Preserve custom instructions, populated indexes,
hooks, settings, and other unverified content. Refresh existing artifacts only
when their bytes match the source's bundled history or the previous CLI repository
ownership manifest. A customized or unverified gate helper blocks the upgrade
before writes, because new routing must not claim compatibility with an old helper.

### UPGR-002 — Migrate configuration safely

Run the source's reviewed Ruby config migrator against a disposable copy before
editing the target repository. Preserve user values, unknown keys, and independent
stage providers. Conflicting legacy/current routes fail preflight. Fresh configs
retain CLI defaults; existing configurations are never reset to those defaults.
Sources must include safe migration helpers and fingerprint metadata; unsupported
sources, missing Ruby for an existing config, malformed metadata, and symlink
paths fail closed. Source helpers are executable code: use only trusted sources.

### UPGR-003 — Back up changes and recover failures

Before any destination write, save exact copies of all changed existing files to
exclusive `.bak`, `.bak.1`, etc. files without overwriting previous backups. Apply
individual writes atomically. On an ordinary write failure, restore already written
files to their previous bytes and modes and remove newly written files. Backups
remain available for manual recovery after process interruption; repository writes
are not one crash-atomic transaction. Repeated unchanged upgrades are no-ops.

### UPGR-004 — Preview and report

Dry-run performs the same validation and configuration planning without modifying
repository files. Reports distinguish preserved, unchanged, planned, and written
files. Retired names in custom routing are reported for review, not rewritten
based on their name alone. Local and archive source selections remain consistent.

### INST-001 — Use verified skill migration

`aw install` invokes the selected source's content-fingerprint migrator. Custom
and unverified skills survive. Verified retired bundled skills are backed up and
removed. Consolidated-name collisions fail before install writes; `--force` only
permits replacing conflicting agent symlinks. Dry-run never writes skills or links.

### INST-002 — Explicit skill rollback

`aw install --rollback-skills BACKUP` restores the helper's verified skill
transaction, including ownership/version metadata. It does not change agent links
or repository files. `--dry-run` previews rollback. Keep the compatible source
checkout and restore separately backed-up repository files as needed. The source
helper's journal guards interrupted migrations and refuses rollback collisions.

## Acceptance verification

- `tests/test_upgrade.py`: UPGR-001 through UPGR-004, including real Ruby migration,
  conflicts, byte/mode restoration, backups, source/runtime failures and symlinks.
- `tests/test_installer_migration.py`: INST-001 and INST-002, using the exact reviewed
  upstream helper and a genuine historical skill fixture.
- `tests/test_source.py`: local/environment/archive selection and unsafe archive
  rejection. Real current-AW end-to-end checks supplement these fixtures.
