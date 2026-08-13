# When to Use What: Augmented Workflow Field Guide

## First session in any repo

```
aw-init
```

That's it. Review `AGENTS.md` and `docs/workflow/config.yml`, then start working.

Not sure which skill fits your situation? Use `aw-help` for an interactive recommendation.

---

## By task type

### Bug fix

```
1. aw-debug                     ← skip if root cause is already clear
2. fix it, run tests
3. aw-capture learning          ← if the bug was non-obvious or likely
                                   to recur
   aw-capture decision          ← if the fix resolved ambiguous intended
                                   behavior (not just a clear defect)
4. aw-commit-push-pr
```

### Small feature or config change (< 1 day, clear scope)

```
1. update/create spec           ← only if durable behavior or workflow
                                   intent changes; skip for most config
                                   changes and internal-only fixes
2. aw-work
3. aw-capture decision          ← if you resolved a real tradeoff
4. aw-commit-push-pr
```

### New feature with unclear scope or product questions

```
1. aw-prd                       ← if a PRD exists or product wants one
2. aw-brainstorm                ← resolves scope, outputs spec
3. aw-plan                      ← skip for simple features
4. aw-work
5. aw-review
6. aw-capture decision/learning
7. aw-commit-push-pr
```

### Large or risky feature (auth, payments, migrations, API contracts)

```
1. aw-prd                       ← get product intent documented
2. aw-brainstorm                ← resolve ambiguity, output spec
3. aw-plan
4. aw-request-human-review      ← spec review before building
5. aw-create-tickets            ← break into tickets if multiple people
6. aw-work  (one ticket at a time)
7. aw-review
8. aw-check-workflow-compliance
9. aw-capture decision/learning/solution
10. aw-commit-push-pr
```

### Refactor or simplification

```
1. aw-review simplify           ← finds AND applies behavior-preserving
                                   simplifications, verifying as it goes
2. aw-review                    ← optional second pass for large refactors
3. aw-commit-push-pr
```

For refactors that change behavior or need structural work beyond simplification, use the feature path (spec if intent changes → `aw-work` → `aw-review`) instead.

### Reviewing someone else's PR or spec

```
aw-review <PR link or spec path>
```

---

## By team size

### Solo or pair (1–2 people)

**Start with just three things:**

- `aw-capture decision` — whenever you resolve a real tradeoff
- `docs/standards/` — when the same convention comes up twice, write it down with `aw-discover-standards`
- `aw-commit-push-pr` — for everything you ship

Everything else is optional. Add specs when features get complex enough that you'd otherwise lose track of intent. Add `aw-capture session` at the end of long sessions if you want continuity.

**Avoid:** `aw-check-workflow-compliance`, `aw-request-human-review`, `aw-create-tickets` — the overhead exceeds the benefit at this scale.

---

### Small team (3–8 people)

Add to the above:

- `aw-brainstorm` before anything with product ambiguity — a 10-minute scope alignment now saves a week of rework later
- `aw-create-spec` for features that touch multiple people's code
- `aw-capture learning` after postmortems or non-obvious bugs
- `aw-synthesize-memory` monthly, to distill session logs into team learnings

**The minimum viable workflow for a new feature:**

```
aw-brainstorm → spec → aw-work → aw-review → aw-commit-push-pr
```

Skip `aw-plan` unless the feature has real sequencing complexity or multiple contributors.

---

### Larger team or multi-repo (8+ people, or agency/contractor context)

The full chain pays off here because context loss and cross-session continuity become real problems.

- Run `aw-synthesize-memory` after each sprint to keep `docs/context/wiki.md` current — new team members and agents can orient from it
- Use `aw-create-tickets` to split plans into Linear/GitHub issues so agents can pick up work independently
- Use `aw-request-human-review` for specs and plans before implementation starts
- Use `aw-check-workflow-compliance` before PRs on any high-risk change
- Configure `workflow.design` hooks when a design team should participate in discovery, spec review, plan review, implementation review, or pre-PR acceptance
- Configure `workflow.steps.monitor_pipeline.skill` for CI monitoring

---

## Minimal starter pack by goal

| Goal | Run |
|------|-----|
| Just capture decisions | `aw-capture decision` ad hoc |
| Standardize code conventions | `aw-discover-standards` once, then reference `docs/standards/` |
| Add design-team checkpoints | configure `workflow.design` hooks and put design references in `docs/standards/` |
| Author e2e tests during implementation | set `e2e.enabled: true` and point `workflow.auxiliary.e2e_tests.skill` at your framework's skill |
| Keep AI sessions continuous | `aw-capture session` at session end; `aw-synthesize-memory` monthly |
| Structured feature development | brainstorm → spec → work → review → PR |
| Team onboarding / cross-session wiki | `aw-synthesize-memory` → `docs/context/wiki.md` |
| Full workflow compliance | add `aw-check-workflow-compliance` + `aw-request-human-review` |

---

## Rules of thumb

- **Skip ceremony that produces artifacts nobody will read.** A plan doc nobody references is waste.
- **Always capture decisions.** This is the highest-ROI habit at any team size and costs almost nothing.
- **Add specs when intent starts drifting** between what was built and what was meant. Not before.
- **`aw-brainstorm` before `aw-plan`.** Scope surprises in planning are cheap; scope surprises in implementation are expensive.
- **`aw-capture session` at natural pauses**, not just at the end of a project. The value is in continuity across sessions, not archiving completed work.
