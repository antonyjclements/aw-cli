---
title: Spec Traceability
tags:
  - specs
  - tests
  - workflow
file-globs:
  - "docs/features/*/spec.md"
  - "*.feature"
  - "*.test.ts"
  - "*.test.tsx"
  - "*.spec.ts"
  - "src/**"
---

# Spec Traceability

Rules for opt-in links between living spec requirements, tests, and behavior entry points.

## Requirement IDs

When `trace.enabled: true`, each feature-bearing requirement heading in
`docs/features/<feature>/spec.md` uses an ID matching:

```text
^[A-Z][A-Z0-9]{1,7}-\d{3,}$
```

Example:

```markdown
### AUTH-001 — Session expires after inactivity
```

Requirement IDs are unique across living specs. Specs are living documents, so a removed requirement is deleted rather than superseded in place.

## Test Anchors

Tests that cover a requirement carry a nearby anchor:

```text
@spec:AUTH-001
```

or:

```ts
// @spec:AUTH-001
```

Place the anchor on or immediately above the test or scenario it covers.

## Code Anchors

Code anchors go at the behavior entry point only, not every helper:

```ts
// @spec AUTH-001, AUTH-002
```

Use multiple IDs when one entry point implements several requirements. Missing code anchors are warnings by default; require them only after the repo has a stable convention.

## Skill Annotation Path

Skills must route annotation writes through:

```sh
node .scripts/aw-gate.js trace-annotate
```

`aw-work` should batch subagent annotation intents under `.aw/tmp/trace-intents.<token>.json` and call `trace-annotate --batch <path> --delete-batch-on-success`. Subagents return intents to the parent; they do not write annotations directly.

When tracing is disabled, the helper skips writes and cleans safe `.aw/tmp/trace-intents.*.json` batch files. Cleanup is limited to that path pattern.

## Overrides

When a test legitimately changes without its owning spec, use a commit trailer:

```text
Spec-Override: AUTH-001 — test asserted the wrong boundary
```

Traceability is accountability, not quality assurance: an anchor proves a link was claimed, not that the behavior is correct.
