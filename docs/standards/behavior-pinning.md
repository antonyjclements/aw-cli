---
title: Behavior Pinning
tags:
  - testing
  - workflow
  - characterization
file-globs:
  - "docs/features/*/behavior-pin.yml"
  - "test/pin/**"
  - ".scripts/aw-gate.js"
---

# Behavior Pinning

Rules for opt-in equivalence checks between an old implementation and a new one.

## Equivalence, Not Correctness

A green behavior pin proves the new implementation behaves like the old one. It
does not prove either implementation is correct. Pinning bug-for-bug is intended:
fix behavior in a separate change after equivalence is proven.

## Two-Sided Runs

Every pin runs the same oracle against two trees:

- old tree: the manifest's `base`
- new tree: the current checkout

The old run must pass first. If it fails, the oracle does not characterize real
behavior and the verdict is `pin-not-characterizing`. If old passes and new
fails, the verdict is `equivalence-broken`.

## Manifests

Behavior pin manifests live at:

```text
docs/features/<feature>/behavior-pin.yml
```

Supported keys stay within the workflow YAML subset:

```yaml
base: c338665
harness: node test/pin/example.pin.js
setup: ""
subject:
  - .scripts/aw-gate.js
oracle:
  - test/pin/example.pin.js
support:
  - package.json
```

Migration pins compare the current repo to a pinned reference implementation:

```yaml
mode: reference-repo
reference:
  repo: ../old-system
  ref: 8f41c2a
harness: node test/pin/migration-contract.pin.js
subject:
  - src
oracle:
  - test/pin/migration-contract.pin.js
golden:
  dir: test/golden
  generated_from:
    repo: ../old-system
    ref: 8f41c2a
    sha: 8f41c2a...
```

`support` is optional and is for current-tree files needed to run the oracle in
the old tree, such as package scripts, test config, helpers, or fixtures.
`subject` must not overlap `oracle` or `support`.

Reference-repo harnesses run once from the current repo with
`AW_PIN_REFERENCE_ROOT`, `AW_PIN_CANDIDATE_ROOT`, `AW_PIN_MANIFEST`,
`AW_PIN_MODE`, and optional `AW_PIN_GOLDEN_ROOT` environment variables. Exit
code `10` means the reference implementation failed the oracle and reports
`pin-not-characterizing`; other non-zero exits report `equivalence-broken`.
Golden fixtures are provenance/caching data, not the primary authority.

## Ordering Rule

Do not edit a manifest or oracle/support files and the subject they judge in the
same commit. `node .scripts/aw-gate.js pin check` enforces this by checking each
commit in the range. If a coupled change is intentional, add a commit trailer:

```text
Pin-Override: docs/features/<feature>/behavior-pin.yml — <reason>
```

Use overrides sparingly. A pin loses value when the implementation and its
oracle are adjusted together.

## Runtime Surface

`pin run` accepts only empty commands or `node <repo-relative .js path>` for
manifest `setup` and `harness` entries. It does not execute shell strings.
Keep pinning opt-in, review manifest command changes like code, and run slow
pins in CI rather than pre-push.
