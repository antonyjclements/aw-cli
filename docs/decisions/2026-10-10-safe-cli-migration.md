---
title: Preserve ownership and configuration during CLI migration
date: 2026-10-10
status: active
tags:
  - cli
  - migration
  - safety
related_specs:
  - docs/features/repo-upgrade/spec.md
supersedes: []
---

# Preserve ownership and configuration during CLI migration

## Context

The CLI's previous global installer replaced same-name skills, while repository
upgrade reset configuration and selected routing files. Consolidated entrypoints
make those ownership assumptions unsafe for customized installations.

## Decision

Use the selected AW source's reviewed fingerprint migrator for global skills.
A name alone does not prove ownership; preserve unverified skills and stop on
consolidated-name collisions. Stage the source's Ruby configuration migration in
a disposable repository before writing any target files. Preserve custom values
and independent providers; refresh only content-verified repository artifacts.
Require a compatible gate helper rather than silently pairing new routing with
unverified code. Keep one prepared source throughout each operation.

## Consequences

Existing-config upgrades require Ruby and trusted AW source helpers. Unsupported
sources or missing prerequisites fail before repository writes. Every changed
existing repository file is backed up. Normal write failures restore prior files
without overwriting intervening user edits. Repository writes are individually
atomic, not one crash-atomic transaction; retained backups support manual recovery.
Explicit skill rollback restores skills and their metadata, not repository files
or agent links. Unverified older bundled-looking content needs human review.

## Alternatives Considered

Blind replacement and name-only retirement would lose customization. Reimplementing
the migration rules in the CLI would create a second safety contract. Delegating
to the shell installer would risk recursion and source drift.

## Verification Limits

The real helper, Ruby migration, collision, backup, rollback, concurrent-edit and
pinned-source tests passed. Machine traceability remains incomplete because the
existing trace setup does not discover Python tests; prose acceptance mappings do
not turn that check green. Tests do not authenticate arbitrary source helpers.

## Links

- `docs/features/repo-upgrade/spec.md`
- `docs/features/repo-upgrade/plan.md`
