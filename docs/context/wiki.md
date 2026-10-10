---
generated: 2026-10-10
sessions_synthesized: 0
---

# Project Context Wiki

> Generated 2026-10-10 by aw-synthesize-memory from 0 session logs and current repository sources. Do not edit manually.
> If this date is more than 30 days old, or several unprocessed session logs have
> accumulated since, verify against specs, decisions, and learnings directly.

## Active Features

- Safe installation and repository upgrade: `docs/features/repo-upgrade/spec.md`
  defines verified ownership, staged config migration, non-overwriting backups,
  concurrent-edit preservation, dry-run and explicit skill-only rollback.
- CLI maintenance and metrics: `docs/features/cli-maintenance/spec.md` defines
  self-update, Textual charts, and version 0.3.0. `aw update` updates the CLI only.

## Recent Decisions

- Preserve ownership and configuration during CLI migration (2026-10-10): use
  reviewed source helpers, preserve unverified custom content and preflight before
  writes. `docs/decisions/2026-10-10-safe-cli-migration.md` records the rationale,
  Ruby prerequisite, recovery boundaries and known traceability limitation.

## Top Learnings

None recorded.

## Tentative Learnings

None recorded.

## Known Dead Ends

Do not infer ownership from names or replace existing config with CLI defaults.
Do not claim repository-wide crash atomicity or repository rollback from skill-only
rollback. Machine traceability currently excludes Python tests.

## Useful Sources

- `README.md`: installation, dependencies and command usage.
- `docs/workflow/config.yml`: implementation policy and enabled gates.
- `docs/standards/index.yml`: enforceable project standards.
- `tests/test_upgrade.py`: configuration, backups and concurrent-edit regression tests.
- `tests/test_installer_migration.py`: actual helper and historical skill migration tests.
- `tests/test_source.py`: source selection and archive safety checks.
