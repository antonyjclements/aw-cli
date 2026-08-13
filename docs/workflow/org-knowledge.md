# Org-Shared Knowledge: Governance and Use

The org knowledge tier (`org_knowledge.source`) is a git repo of shared learnings
and standards that **every subscribing repo reads and every agent is steered by**.
Unlike a repo-local doc, one edit fans out across many repos at once. That blast
radius is why the org base is **governed content, not just a synced folder**: it
needs an owner, review, freshness, and clear authority — the same rigor you'd put
on a shared API or a security policy.

This guide is for whoever stands up and runs an org knowledge base. For how the
tool syncs it, see [gates.md](gates.md) §10 and the config schema in
[README.md](README.md).

---

## 1. Ownership

**One accountable owner** runs the org knowledge base — in practice a senior lead
or distinguished engineer. The owner is accountable for:

- what earns org-wide status (and what stays local),
- the review cadence and retirement of stale entries,
- resolving conflicts between org entries and repo-local guidance.

They may delegate *review* to a small group, but **accountability is singular** —
name the owner in the org repo's `CODEOWNERS`. An org base without a named owner
is the failure mode this whole document exists to prevent: stale, one-team-opinion
guidance silently steering agents org-wide with nobody responsible for it.

---

## 2. The org repo

Structure the org repo so governance is enforced by tooling, not goodwill:

```text
learnings/                 # matches org_knowledge.paths.learnings
standards/                 # matches org_knowledge.paths.standards
GOVERNANCE.md              # owner, review cadence, promotion process
CODEOWNERS                 # the accountable owner / reviewers
```

- **Changes go through PR review** — no direct pushes. `CODEOWNERS` requires the
  owner (or delegated reviewers) on every change.
- **Consumers pin a reviewed ref.** Set `org_knowledge.ref` to a released tag
  (e.g. `v2026.07`) so a repo takes org changes only when it deliberately bumps
  the pin. Float `main` only if you accept continuous, unreviewed-by-you updates.

---

## 3. Entry metadata

Every learning and standard in the org base carries frontmatter so it is
self-describing and governable:

```yaml
---
title: <short imperative title>
type: learning | standard
authority: advisory | required     # may an agent override it with local judgment?
applies_to: ["*"]                  # or e.g. ["node", "payments-service"] — scope
owner: <handle>                    # accountable person (defaults to the base owner)
reviewed: 2026-07-03               # date of the last governance review
review_by: 2027-01-03              # next review due — after this, treat as stale
status: active | deprecated
source: <URL>                      # originating repo-local learning/decision/PR
---
```

- **`authority`** — `advisory` (default) means agents may override it with local
  judgment and note that they did; `required` means agents apply it and surface
  any conflict with repo-local guidance to a human rather than resolving it silently.
- **`applies_to`** — scopes the entry. `["*"]` is org-wide; a list limits it to
  matching repos/stacks. Agents skip entries that do not apply.
- **`reviewed` / `review_by`** — the freshness contract. Past `review_by`, the
  entry is stale and should be re-affirmed, updated, or retired.
- **`source`** — provenance. Every org entry should trace back to the repo-local
  learning, decision, or discussion that earned it org-wide status.

---

## 4. Authority and precedence

Two rules keep the org tier from quietly overriding local judgment:

1. **Repo-local always wins.** A repo's own learnings, standards, and decisions
   take precedence over the org tier. Org guidance is a *second* opinion, never a
   silent override of the first.
2. **Advisory by default.** Treat an org entry as advisory unless it is marked
   `authority: required`. A `required` entry that conflicts with repo-local
   guidance is surfaced to a human as a conflict — agents do not auto-resolve it.

An org entry with missing governance metadata, or one past its `review_by`, is
treated as **lower-confidence**: apply it cautiously and surface the staleness
rather than trusting it blindly.

---

## 5. Freshness and retirement

Org guidance goes stale, and stale-but-authoritative is worse than absent.

- The owner runs a **review cadence** (e.g. quarterly). Each pass re-affirms,
  updates, deprecates, or removes entries whose `review_by` has passed.
- **Retirement is deliberate.** Mark an entry `status: deprecated` before removal,
  then remove it; git history is the archive.
- Consumers on a pinned `ref` pick up retirements when they bump the pin, which is
  the point — change is reviewed on both sides.

---

## 6. Promotion path (repo-local → org)

Earning org-wide status is **deliberate and human-gated**. Skills never write to
the org tier.

1. A pattern recurs across repos — a human notices, or `aw-synthesize-memory`
   surfaces a cross-repo candidate.
2. Someone opens a **PR to the org repo** with the full entry metadata and a
   `source` link back to the originating repo-local learning/decision.
3. The **owner (or delegated reviewers) assess** correctness, scope (`applies_to`),
   and authority level.
4. On merge, consumers pick it up on their next `org-sync` or `ref` bump.

The reverse never happens automatically: an agent proposing a promotion opens a
PR for human review; it does not push to the org base.

---

## 7. How agents consult the org tier

`aw-capture`, `aw-synthesize-memory`, and `aw-discover-standards` run
`node .scripts/aw-gate.js org-sync` and read the org tier **read-only**, with
repo-local first. They:

- honor `authority` (advisory vs required) and `applies_to` (skip non-matching),
- treat missing-metadata or past-`review_by` entries as lower-confidence and
  surface the staleness,
- never auto-resolve a `required`-vs-local conflict — they raise it,
- never write to the org tier; upstream contribution goes through §6's PR path.

---

## 8. Templates

### `CODEOWNERS` (org repo)

```text
# The accountable owner reviews every change to org-wide knowledge.
*            @your-org/knowledge-owner
/standards/  @your-org/knowledge-owner
/learnings/  @your-org/knowledge-owner
```

### `GOVERNANCE.md` (org repo)

```markdown
# Org Knowledge Governance

Owner: <name> (<handle>) — senior lead / distinguished engineer, accountable for
this knowledge base.

Reviewers: <optional delegated group>

Review cadence: quarterly. Each pass re-affirms, updates, or retires entries past
their `review_by`.

Changes: PR-only, CODEOWNERS-gated. Every entry carries the metadata in
docs/workflow/org-knowledge.md §3 and a `source` link.

Promotion: repo-local guidance earns org-wide status via a PR proposing the entry
with evidence; the owner assesses correctness, scope, and authority.
```

### Org entry (learning or standard)

```markdown
---
title: Prefer idempotent job handlers
type: standard
authority: required
applies_to: ["payments-service", "billing-service"]
owner: jdoe
reviewed: 2026-07-03
review_by: 2027-01-03
status: active
source: https://github.com/your-org/payments/pull/1234
---

# Prefer idempotent job handlers

<the guidance, plus why and the evidence that earned it org-wide status>
```
