---
title: End-to-End Coverage
tags:
  - testing
  - specs
  - workflow
file-globs:
  - "docs/features/*/spec.md"
  - "e2e/**"
---

# End-to-End Coverage

Rules for deciding which requirements need an end-to-end test, and for recording that decision where it can be checked.

Applies when `e2e.enabled: true` in `docs/workflow/config.yml`.

## What Warrants an E2E Test

E2E tests are slow, flakier than unit tests, and expensive to maintain. Mark a requirement `[e2e]` only when the end-to-end run proves something cheaper layers cannot:

- **It crosses a boundary the unit tests stub.** Real navigation, a real session, real network, real storage. If the unit test's mocks are where the bugs hide, the e2e test earns its cost.
- **The value is in the sequence, not the steps.** A multi-step user journey where each step passes alone and the flow still breaks.
- **A silent regression is expensive.** Auth, payments, permissions, data loss.
- **It has a regression history.** An integration that has broken before will break again.

Do not mark a requirement when:

- A unit or integration test proves the same behavior at the same fidelity.
- The behavior is pure logic, formatting, validation, or copy.
- A cheaper layer already covers it and the e2e test would only re-assert it.
- The requirement describes internal structure rather than user-visible behavior.

## Keep a Ceiling

A suite that grows without limit gets slow, then flaky, then ignored — and an ignored suite is worse than no suite, because it still costs CI time and still blocks merges for reasons nobody trusts.

If most requirements in a feature are marked, the bar is set wrong. Mark the journeys that carry the feature's value, not every assertion about it.

## The Marker

A requirement opts in with an exact `[e2e]` suffix on its heading:

```markdown
### PAY-004 — Checkout completes with a saved card [e2e]
```

Rules:

- **Suffix only.** The marker goes at the end of the title, after the em-dash. A marker placed before the em-dash — `### PAY-004 [e2e] — Checkout completes` — does not match the requirement heading pattern, and the requirement disappears from `trace` entirely with no error.
- **Exact `[e2e]`, lowercase, undecorated.** `[E2E]`, `(e2e)`, `[ e2e ]`, `**[e2e]**`, a backticked `` `[e2e]` ``, and a trailing `[e2e].` are not the marker. `trace` reports them as `suspect-e2e-marker` warnings rather than treating them as marked. Markdown emphasis around the marker is the easiest mistake to make, because this document renders it in backticks when discussing it — in a heading, write it bare.
- **One marker per requirement.** The marker is a boolean, not a level. If you need "planned but not yet covered", that is a backlog item, not a spec annotation.

## Where the Decision Is Made

Mark requirements at spec time — in `aw-create-spec` or `aw-brainstorm`, as the acceptance criterion is written — and settle disagreements at spec review, where changing your mind is free.

Do not mark at implementation time. A bar set by whoever is writing code that day, under deadline, produces either nothing or everything.

## Adopting the Marker Retrospectively

A repo that already has an e2e suite has already made most of these calls; the specs just never recorded them. Do not re-litigate the suite requirement by requirement — read the decisions back out of it:

```bash
node .scripts/aw-gate.js trace --suggest-e2e
```

This reports unmarked requirements that already carry an anchor in `e2e.test_paths`, plus headings ending in a marker variant, with the exact heading edit for each. It changes nothing, and it exits 0 even when the enforcing `trace` run is failing — pre-existing errors such as a duplicate requirement ID are printed but never fatal, since those are exactly what a repo adopting the marker retrospectively has. It exits 2 only when `trace.enabled` is false, because it reads the same spec configuration the gate does.

It also names what the flip will cost before you make it: `would-become-dangling` lists `@spec` anchors in `e2e.test_paths` with no living spec — retired IDs, or external tracker keys such as `PROJ-1234` — which become `dangling-test-ref` errors the moment `e2e.enabled` is true. Clear those first. If `e2e.test_paths` matches no tracked files at all, the survey says so rather than reporting a clean tree.

Apply the `gate_effect: none` candidates freely — they already have the coverage the marker demands. Treat `enforces` candidates as a real decision: the marker starts being checked immediately and the test still has to exist.

A requirement with no e2e anchor is never suggested, however important it sounds. Deciding that a requirement *should* have end-to-end proof is the judgment this standard puts with a human, and it stays there.

## Exceptions

There is no override trailer. `Spec-Override:` and `Pin-Override:` work because those checks are scoped to a commit range; marked-coverage is a whole-tree invariant, so a per-commit escape hatch would clear once and fail again on the next commit.

If a marked requirement genuinely cannot carry an e2e test — the environment cannot reach a payment vault, the flow needs hardware — remove the marker and record why in the spec prose. An unmarked requirement with a stated reason is honest. A marked requirement with a permanent override is a check everyone learns to ignore.

This also means: mark a requirement when you are ready to cover it. Marking a backlog you do not intend to cover turns `trace` red for weeks and trains the team to skip it.

## Enforcement

`node .scripts/aw-gate.js trace` fails with `missing-e2e-coverage` when a marked requirement has no `@spec` anchor in a file matching `e2e.test_paths`. Anchors record no test layer, so membership is resolved by matching the anchor's file against those pathspecs.

One e2e test may cover several requirements — anchor it with each ID (`// @spec PAY-004, PAY-005`) and each is satisfied.

When `e2e.test_paths` is empty, the check is skipped and marked requirements raise an `e2e-paths-unset` warning. A list of nothing but `:(exclude)` pathspecs is a config error (`e2e-paths-exclude-only`), not a narrow filter: it would match the whole repository and let any test anywhere satisfy every marker. Exclusions only carve holes inside a positive pattern.

Marking a requirement and writing its e2e test are allowed to be separate commits. Anchors found only through `e2e.test_paths` are exempt from `uncoupled-test-change`, so the commit that adds the test the marker demands does not need a `Spec-Override:` trailer. Anchors in `trace.test_paths` keep the coupling rule.

## Boundary

The marker records that a requirement was judged to need end-to-end proof. It does not assert the test is good, the selectors are stable, or the assertion is meaningful. Like traceability, this is accountability, not quality assurance.

Framework conventions — selector strategy, fixtures, wait policy, auth-state reuse — belong in a separate repo-local standard. Keep external test-management keys such as Jira or Xray issue IDs out of `@spec` anchors: the anchor pattern would parse `PROJ-1234` as a requirement ID and `trace` would report it as a dangling reference.
