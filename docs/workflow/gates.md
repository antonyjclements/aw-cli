# Enforcement Gates, Telemetry, Org Knowledge, Traceability, Workflow Trace, and Behavior Pins

A practical guide to `.scripts/aw-gate.js` — the dependency-free helper that turns
the workflow's advisory review/capture/compliance steps into a deterministic,
enforceable contract, records lightweight telemetry, and syncs an org-shared
knowledge tier.

All seven capabilities are **opt-in and disabled by default**. This guide covers
what they are, how to configure them, and how to wire enforcement into a Git hook
or CI. For the terse schema, see [README.md](README.md); this file is the how-to.

> **What gates guarantee — and what they don't.** A gate proves a step *ran*
> recently (`age` mode) or *against the current code* (`commit` mode). It does
> **not** prove the step was done *well* — a rushed review still stamps the review
> gate. Gates are workflow **accountability**, not quality assurance: they make
> "did we review this?" enforceable and deterministic, while the judgment of
> whether the review was any good stays with the agent and the humans. Keep that
> boundary in mind when deciding what to gate on.
>
> **Receipts close the "stamp without running" gap.** Left alone, `record review`
> is a single command an agent can run to clear a blocked push *without running
> `aw-review` at all*. When `gates.require_receipt` is on, `record` refuses to
> stamp unless the skill has just written a fresh, gate-named **receipt**
> summarizing what it did, and consumes that receipt (single-use) so it cannot
> re-stamp a later commit. This does not make a lazy review good — it raises the
> floor from "type one command" to "produce recent, substantive, single-use
> evidence", and leaves an auditable trail. It is a deterrent and an audit aid,
> not a proof of quality.

---

## 1. The idea in one paragraph

Review and compliance are LLM-driven — they cannot block a merge on their own.
So instead of trying to run an agent in CI, the workflow splits the job in two:
a skill **stamps a freshness marker** when it finishes (`record`), and a tiny
deterministic checker **enforces** that the marker is fresh (`check`). The checker
is plain Node + git, needs no agent and no API key, and you wire it wherever you
want it to block. The workflow ships the mechanism and the contract; you choose
the enforcement point.

---

## 2. Install

The helper is installed by `aw-init` behind a flag:

```sh
skills/aw-init/scripts/install.sh --with-gates --repo /path/to/repo
```

This adds `<repo>/.scripts/aw-gate.js`, appends `.aw-gate-state.json`,
`.aw-org-cache/`, `.aw/tmp/`, `.aw/workflow-trace.jsonl`, and `.aw/pin/` to
`.gitignore`, and writes the `gates` / `telemetry` / `org_knowledge` / `trace` /
`workflow_trace` / `pin` sections to `docs/workflow/config.yml` (those config sections
are written on every install; the script itself is gated behind `--with-gates`).

Existing installs: re-run the installer with `--with-gates`, or
`skills/aw-init/scripts/upgrade.sh` to add the config sections.

The script requires **Node ≥ 16** at the enforcement point (local hook or CI).

---

## 3. The CLI

```sh
node .scripts/aw-gate.js receipt <gate> --summary "text" [--detail "text"]
node .scripts/aw-gate.js record <event> [--detail "text"] [--no-receipt]
node .scripts/aw-gate.js check [--against head|worktree]
node .scripts/aw-gate.js trace [--base <ref>] [--json] [--out <path>]
node .scripts/aw-gate.js trace-annotate <spec|test|code> --file <path> --line <n> --id <ID>[,<ID>]
node .scripts/aw-gate.js trace-annotate --batch .aw/tmp/trace-intents.<token>.json [--delete-batch-on-success]
node .scripts/aw-gate.js workflow-record <event> [--tier <tier>] [--step <step>] [--gate <gate>] [--status <status>] [--reason <text>]
node .scripts/aw-gate.js workflow-check [--base <ref>] [--since-commit <ref>] [--json]
node .scripts/aw-gate.js pin run [--json] [--out <path>]
node .scripts/aw-gate.js pin check [--base <ref>] [--json]
node .scripts/aw-gate.js org-sync
```

### `receipt <gate>`

Writes a git-ignored **proof-of-work receipt** for `<gate>` to
`<gates.receipt_dir>/<gate>.json` (default `.aw/receipts/<gate>.json`). The skill
calls this when it finishes, passing a `--summary` that restates what it did. The
receipt records `{ gate, ts, commit, summary, detail }`. `record` verifies and
then consumes it.

```sh
node .scripts/aw-gate.js receipt review --summary "reviewed the auth diff; fixed one P1, no P0s"
```

`--summary` is required and must be non-empty — an empty summary is refused, so
stamping always carries at least a stated claim of what ran.

### `record <event>`

Stamps the current **time and commit** for `<event>` into the git-ignored state
file (`gates.state_file`, default `.aw-gate-state.json`). When `telemetry.enabled`
is true, it also appends a no-PII event to the telemetry log. Idempotent — the
latest stamp wins.

```sh
node .scripts/aw-gate.js record review --detail "code review"
```

When the gate is **receipt-required** (`gates.require_receipt: true`, or a
per-gate `checks.<name>.require_receipt: true`), `record` first verifies a fresh,
gate-matching receipt written by `receipt <gate>`:

- the receipt's `gate` must equal `<event>`;
- its `summary` must be non-empty;
- its `ts` must be within `gates.receipt_max_age_minutes` (default 180) — a stale
  or reused-from-last-week receipt is rejected;

then folds a digest of it into the state entry and **deletes** the receipt so it
is single-use. Without a valid receipt, `record` exits non-zero and does not
stamp. `--no-receipt` bypasses this check with a loud stderr warning — it exists
only for bootstrap (the commit that first enables the gate, fresh clones, hand
use), never to skip running the skill.

The bundled skills call `receipt` then `record` automatically when they finish:
`aw-review` → `review`, `aw-capture` → `capture`,
`aw-check-workflow-compliance` → `check_workflow_compliance`,
`aw-synthesize-memory` → `synthesize`. `aw-synthesize-memory` records its gate
on every invocation, including no-op runs with no unprocessed sessions (its
receipt summary says so), so an age-based `synthesize` gate can enforce periodic
memory review. You can also call them by hand.

### `check`

Reads `gates` from config and exits non-zero if any configured gate is stale.
Exit **0** means every gate is fresh (or gates are disabled); exit **1** means at
least one failed, with a line per failure explaining why. This is the command you
put in a hook or CI job.

- `--against head` (default): commit-mode gates compare the recorded commit to
  `HEAD`. Use in a **pre-push** hook or CI.
- `--against worktree`: compare to the working tree (staged + unstaged). Use in a
  **pre-commit** hook so edits not yet committed are considered.

### `org-sync`

Shallow-clones or updates the configured org knowledge repo into the git-ignored
cache. No-op when `org_knowledge.source` is blank.

### `trace`

Checks opt-in spec traceability without an agent:

- every `@spec` reference in test/code points to a living spec requirement
- every requirement has at least one test anchor
- missing code anchors warn by default, or fail when `trace.require_code_anchor`
  is true
- with `--base <ref>`, changed anchored tests must be paired with a changed
  owning spec or a `Spec-Override:` commit trailer

Exit 0 means clean, warnings-only, or disabled. Exit 1 means at least one error
finding. `--json` prints a stable `{ summary, matrix, findings }` object, and
`--out <path>` writes the same object for CI artifacts.

### `trace-annotate`

Skills use this as the deterministic policy boundary for writing annotations.
When `trace.enabled` is false it skips writes; when a safe batch file under
`.aw/tmp/trace-intents.*.json` is supplied, it deletes that transient file before
exiting. When enabled it validates IDs and line targets before writing.

`aw-work` should prefer batch mode so subagents return annotation intents to the
parent, the parent writes one `.aw/tmp/trace-intents.<token>.json`, and the helper
merges labels and applies edits once:

```json
{
  "intents": [
    { "kind": "test", "file": "src/auth.test.ts", "line": 34, "ids": ["AUTH-001"] },
    { "kind": "code", "file": "src/auth.ts", "line": 8, "ids": ["AUTH-001", "AUTH-002"] }
  ]
}
```

Use `--delete-batch-on-success` for normal enabled runs. Failed enabled batches
are preserved for debugging unless the caller removes them in its cleanup step.

### `workflow-record`

Appends one process breadcrumb to `workflow_trace.path` when
`workflow_trace.enabled` is true:

```sh
node .scripts/aw-gate.js workflow-record tier --tier feature --reason "workflow behavior changed"
node .scripts/aw-gate.js workflow-record step --step aw-work --status ran --artifact docs/features/foo/spec.md
```

When disabled, it exits 0 without writing. Separately, `record <gate>`
automatically appends a `gate` event when workflow trace is enabled, so freshness
gate execution can be checked as process evidence.

### `workflow-check`

Reads `workflow_trace.path` and exits non-zero when required breadcrumbs are
missing. The initial checks are deliberately small: a tier event when
`workflow_trace.require_tier` is true, and gate events named in
`workflow_trace.required_gates`. Use `--base` or `--since-commit` to consider
only events recorded by commits in that range. Appends retain the newest
`workflow_trace.max_events` entries and trim oldest lines until the file is under
`workflow_trace.max_bytes`.

### `pin run`

Runs each `docs/features/*/behavior-pin.yml` manifest. The default same-repo mode
compares the manifest's old `base` with the current checkout, copying current
oracle/support files into a temporary worktree so both sides run the same
harness. `mode: reference-repo` checks out `reference.repo` at `reference.ref`
under `.aw/pin/` and runs the current-tree harness once with
`AW_PIN_REFERENCE_ROOT`, `AW_PIN_CANDIDATE_ROOT`, `AW_PIN_MANIFEST`,
`AW_PIN_MODE`, and optional `AW_PIN_GOLDEN_ROOT`.

Results are written to `pin.out` with verdicts:

- `pass`: old and new both pass
- `pin-not-characterizing`: old/reference failed, so the oracle does not describe reality
- `equivalence-broken`: old/reference passed and new failed

Manifest `setup` and `harness` commands must be empty or
`node <repo-relative .js path>`. `pin run` does not execute shell strings.
Reference-repo harnesses can exit `10` to report `pin-not-characterizing`.
Golden fixture config is recorded as provenance but does not replace live
reference execution.

### `pin check`

Checks commit history from `--base` (default `origin/main`) to `HEAD` and fails
when one commit changes both a pin's subject and its oracle/support files. Use a
manifest-scoped `Pin-Override: docs/features/<feature>/behavior-pin.yml — <reason>`
trailer only when coupling those edits is intentional.

---

## 4. Gate configuration

```yaml
gates:
  enabled: true                  # master switch; false makes `check` a no-op
  require_receipt: true          # `record` needs a fresh receipt from the skill
  receipt_dir: .aw/receipts      # where receipts are written (git-ignored)
  receipt_max_age_minutes: 180   # how recent a receipt must be to count
  state_file: .aw-gate-state.json
  checks:
    review:
      mode: commit
      paths:
        - "."
        - ":(exclude)docs"
    check_workflow_compliance:
      mode: age
      max_age_hours: 168
    synthesize:
      mode: age
      max_age_hours: 336
```

- `enabled` — when `false`, `check` prints "gates disabled" and exits 0. Nothing
  is enforced until you flip this to `true`.
- `state_file` — where `record` writes markers. Keep it git-ignored; it is
  per-checkout local state, not shared.
- `checks.<name>` — one entry per gate. `<name>` is the event the matching skill
  records. Remove an entry to stop enforcing that gate (the skill still records
  it harmlessly).
- `require_receipt` — when `true`, `record <name>` refuses to stamp unless the
  skill has just written a fresh receipt (see [§3](#3-the-cli)). Defaults to
  `false` in the tool for backward compatibility; the installer ships it `true`.
  A per-gate `checks.<name>.require_receipt` boolean overrides this default for
  one gate — e.g. keep it strict for `review` but relax it for `synthesize`.
- `receipt_dir` — where receipts are written and consumed. Keep it git-ignored;
  the installer adds `.aw/receipts/` to `.gitignore`.
- `receipt_max_age_minutes` — how recent a receipt must be to be accepted
  (default 180). Tightening it forces the skill to have run closer to the stamp.

### Modes

| Mode | Fresh while… | Needs | Best for |
| --- | --- | --- | --- |
| `age` (default) | recorded within `max_age_hours` | nothing (git-free) | time-triggered checks that should re-run periodically even when code is unchanged (compliance) |
| `commit` | the gate's `paths` are unchanged since the recorded commit | git; recorded commit reachable | change-triggered checks (review, spec drift) |
| `commit-and-age` | both of the above hold | git + a window | high-assurance gates |

`age` answers *"did this run recently?"* — simple, and it can force a weekly
re-run. `commit` answers *"has the current code been checked?"* — a review from
last week on untouched code stays valid, while any relevant change invalidates it.
Pick per gate; there is no global default beyond `age`.

### Scoping a commit-mode gate with `paths`

`paths` is a list of **git pathspecs** limiting which changes invalidate the gate.
Omit it and *any* commit invalidates the gate. Common patterns:

```yaml
paths:
  - "."                 # everything under the repo root, then narrow with excludes:
  - ":(exclude)docs"    # ...but ignore docs/ — a docs-only change stays fresh
```

```yaml
paths:
  - "src"               # only changes under src/ matter
  - "docs/features"     # ...plus the living specs
```

`:(exclude)<path>` (equivalently `:!<path>`) is git's exclude magic. At least one
positive pathspec (like `.` or `src`) must be present alongside excludes.

### Config parsing: the supported YAML subset

`aw-gate.js` reads `config.yml` with a **deliberately partial, dependency-free
YAML parser** — enough for this workflow's config and nothing more. The upside is
zero dependencies and full portability; the cost is that config outside the
supported subset **misparses silently rather than erroring**. Keep edits within
this subset (or, if the grammar ever needs to grow, the tool should adopt a real
YAML library instead of stretching the parser):

**Supported**

- Nested block mappings by indentation (`key:` then indented children).
- Scalars: strings (optionally `"double"`/`'single'` quoted), booleans
  (`true`/`false`), null (`~` or `null`), integers, floats.
- Block scalar lists — `paths:` then indented `- item` lines.
- Inline flow scalar arrays — `paths: ["src", ":(exclude)docs"]` (no commas
  *inside* an item).
- Full-line comments (`# ...`) and blank lines.

**Not supported — avoid these; they misparse without an error**

- **Trailing/inline comments on a value line.** `enabled: true # note` parses the
  value as the string `"true # note"`, so the gate is silently treated as
  disabled. Put comments on their own line.
- **A bare `key:` with no value.** This parser reads it as a child *mapping*
  (`{}`), not null or `""`. For a blank string, write it explicitly — e.g.
  `source: ""`, not `source:`. (A bare `org_knowledge.source:` yields an object,
  which `org-sync` now treats as unset and skips rather than misusing.)
- Inline flow maps (`{a: b}`) and block lists of maps (`- key: value`).
- Multi-line/folded scalars (`|`, `>`), anchors/aliases (`&`, `*`), tags (`!!type`).
- A comma inside a quoted item of an inline array.

The same subset is documented at the top of `.scripts/aw-gate.js`, beside the
parser. The installer's default `config.yml` and every example in this guide stay
inside it.

---

## 5. Wiring enforcement

The workflow does **not** install a hook — you choose the enforcement point.

### Option A: husky pre-push (this repo)

This repo uses [husky](https://typicode.github.io/husky/). `.husky/pre-push`
contains:

```sh
node .scripts/aw-gate.js check
node .scripts/aw-gate.js trace
node .scripts/aw-gate.js pin check
```

`npm install` re-installs the hooks (via the `prepare` script), so every clone is
protected. A stale gate makes `check` exit 1 and Git aborts the push.

### Option B: a plain Git hook (no npm)

```sh
# .git/hooks/pre-push   (chmod +x)
#!/bin/sh
node .scripts/aw-gate.js check || {
  echo "Push blocked: a workflow gate is stale. Re-run the skill, then push." >&2
  exit 1
}
```

### Option C: pre-commit (catch it earlier)

```sh
# .husky/pre-commit  or  .git/hooks/pre-commit
node .scripts/aw-gate.js check --against worktree
```

### Option D: CI required check

```yaml
# GitHub Actions
- uses: actions/checkout@v4
  with:
    fetch-depth: 0          # commit-mode gates need history to resolve the recorded commit
- uses: actions/setup-node@v4
  with:
    node-version: 20
- run: node .scripts/aw-gate.js check
- run: node .scripts/aw-gate.js trace --base origin/${{ github.base_ref }}
- run: node .scripts/aw-gate.js pin check --base origin/${{ github.base_ref }}
- run: node .scripts/aw-gate.js pin run
```

Make it a **required** status check on the branch so a red gate blocks merge.
Only add trace or pin lines after enabling their config. Disabled commands are
no-ops, but CI jobs are useful only for opted-in repos.

> **Shallow clones:** commit mode resolves the recorded commit with git. In CI,
> fetch full history (`fetch-depth: 0`); otherwise the recorded commit may be
> absent and the gate fails asking you to re-run.

---

## 6. Spec traceability conventions

Traceability is opt-in and disabled by default:

```yaml
trace:
  enabled: false
  spec_paths:
    - "docs/features/*/spec.md"
  test_paths:
    - "*.feature"
    - "*.test.ts"
    - "*.test.tsx"
    - "*.spec.ts"
  code_paths:
    - "src"
  require_code_anchor: false
```

Requirement IDs are markdown headings in living specs:

```markdown
### AUTH-001 — Session expires after inactivity
```

Tests anchor to requirements on or immediately above the test/scenario:

```ts
// @spec:AUTH-001
test('session ends after 30 idle minutes', () => {})
```

Code anchors belong only at behavior entry points:

```ts
// @spec AUTH-001, AUTH-002
export function createSession() {}
```

When a test legitimately changes without its owning spec, include a commit
trailer:

```text
Spec-Override: AUTH-001 — test asserted the wrong boundary
```

An anchor proves a link was claimed, not that the code conforms. Coupling proves
a change was coordinated, not that it was correct. Traceability is workflow
accountability, not quality assurance.

---

## 7. Workflow execution trace

Workflow trace is opt-in and disabled by default:

```yaml
workflow_trace:
  enabled: false
  path: .aw/workflow-trace.jsonl
  require_tier: true
  required_gates:
    - review
    - check_workflow_compliance
```

The file is git-ignored local process evidence. Use `workflow-record` for
explicit process facts and `workflow-check` to validate configured breadcrumbs:

```sh
node .scripts/aw-gate.js workflow-record tier --tier feature --reason "workflow behavior changed"
node .scripts/aw-gate.js workflow-check
```

When enabled, every `record <gate>` call also writes a `gate` event to this file.

---

## 8. The everyday loop

1. You do work and run a skill — e.g. `aw-review`. On completion it writes a
   receipt (`receipt review --summary "…"`) and then runs
   `node .scripts/aw-gate.js record review`, which verifies and consumes that
   receipt and stamps the current commit/time. If the skill did not run, there is
   no receipt and `record` refuses to stamp.
2. You push. The pre-push hook runs `node .scripts/aw-gate.js check`.
3. If the review gate is fresh (no non-doc changes since the review, per its
   `paths`), the push proceeds. If you changed code after reviewing, the gate is
   stale and the push is blocked until you review again.

You rarely call `record` by hand — the skills do it. `check` runs automatically
via the hook.

---

## 9. First-push bootstrap

A gate cannot validate the commit that *installs* it: enabling gates and adding
the hook are themselves non-doc changes, so the review gate is stale for that
commit. For that one push, bypass the hook once:

```sh
git push --no-verify
```

Or record after committing, then push normally. With `require_receipt` on, this
first commit has no receipt yet, so bypass the receipt check once:

```sh
node .scripts/aw-gate.js record review --no-receipt
git push
```

After the bootstrap, the normal loop enforces every subsequent push.

---

## 10. Troubleshooting

| Message from `check` | Meaning | Fix |
| --- | --- | --- |
| `gates disabled … skipping` (exit 0) | `gates.enabled` is not `true` | set `gates.enabled: true` |
| `<gate>: never recorded` | no marker yet | run the skill, or `record <gate>` (first run / fresh clone — state is per-checkout and git-ignored) |
| `no receipt at … — run the skill` (from `record`) | receipt-required gate has no fresh receipt | run the skill (it writes the receipt), or `receipt <gate> --summary "…"` then `record`; bootstrap only: `record <gate> --no-receipt` |
| `receipt … is stale` / `is for gate "X"` (from `record`) | receipt too old or for the wrong gate | re-run the skill so it writes a fresh, correct receipt, then `record` |
| `<gate>: stale (last run Nh ago, limit Mh)` | age-mode window exceeded | re-run the skill |
| `<gate>: code changed in <paths> … since it last ran` | commit-mode: relevant paths changed | re-run the review/skill, then re-record |
| `<gate>: recorded commit <sha> not found (rebased or shallow clone)` | the recorded commit is gone | re-run the skill; in CI use `fetch-depth: 0` |
| `<gate>: invalid or missing max_age_hours` | age/`commit-and-age` gate lacks a window | add `max_age_hours` |
| `trace disabled … skipping` | `trace.enabled` is not `true` | set `trace.enabled: true` after adopting IDs and anchors |
| `dangling-test-ref` / `dangling-code-ref` | an anchor points at a missing requirement ID | fix the ID or add the living spec requirement |
| `untested-requirement` | a requirement has no test anchor | add or annotate coverage, or remove stale requirement text |
| `uncoupled-test-change` | an anchored test changed without its owning spec | update the spec or add a `Spec-Override:` trailer |

The state file is **local and git-ignored**, so a fresh clone or CI checkout
starts with every gate "never recorded". That is intended — enforcement is about
*this* checkout's work. In CI, either record as part of the pipeline or scope the
gate to what CI can verify.

---

## 11. Telemetry

With `telemetry.enabled: true`, each `record` call also appends one JSON line to
`telemetry.path` (default `docs/metrics/events.jsonl`):

```json
{ "ts": "2026-07-03T12:00:00.000Z", "event": "review", "detail": "code", "source": "aw-gate" }
```

It records **only** an event name, timestamp, optional short detail, and source —
no code, no diffs, no PII.

### Rotation, retention, and merge conflicts

The log is append-only and git-tracked, which would otherwise grow without bound
and conflict at the tail when branches merge. Two defaults prevent that:

- **Monthly rotation** (`rotation: monthly`) writes to `events-YYYY-MM.jsonl`, so
  each file stays bounded and concurrent branches usually touch different months.
  `rotation: none` keeps a single `events.jsonl`.
- **`union` merge** — `aw-init --with-gates` adds `docs/metrics/events*.jsonl merge=union`
  to `.gitattributes`. When two branches do append to the same shard, git keeps
  both sides' lines instead of raising a conflict; order is irrelevant since each
  line carries its own `ts`.

Prune old shards with retention (git history keeps the removed data):

```sh
node .scripts/aw-gate.js prune-telemetry   # deletes shards older than telemetry.retention_months (default 12)
```

`aw-synthesize-memory` runs this as part of its retention pass, so you rarely call
it by hand.

Aggregate across all shards (`events*.jsonl`):

```sh
node -e 'const fs=require("fs"),p=require("path");const d="docs/metrics";const c={};for(const f of fs.readdirSync(d))if(/^events.*\.jsonl$/.test(f))for(const l of fs.readFileSync(p.join(d,f),"utf8").trim().split("\n"))if(l){const e=JSON.parse(l).event;c[e]=(c[e]||0)+1}console.log(c)'
```

Telemetry is independent of gates — you can run either without the other. Schema
detail lives in [../metrics/README.md](../metrics/README.md).

---

## 12. Org-shared knowledge

Point `org_knowledge.source` at a git repo of shared learnings and standards to
add an org-wide tier alongside the repo-local `docs/learnings/` and
`docs/standards/`, replacing the per-machine `~/.agents/learnings/` fallback:

```yaml
org_knowledge:
  source: "https://github.com/acme/engineering-knowledge.git"
  ref: main
  cache_dir: .aw-org-cache
  paths:
    learnings: learnings
    standards: standards
```

`node .scripts/aw-gate.js org-sync` shallow-clones or updates that repo into the
git-ignored cache. `aw-capture`, `aw-synthesize-memory`, and
`aw-discover-standards` read the org tier (repo-local first, then org-shared) so a
repo-local entry does not duplicate an org-wide one.

Because one edit to the org base steers agents across every subscribing repo, it
is **governed content, not just a synced folder**: one accountable owner (a senior
lead or distinguished engineer), PR-reviewed changes, self-describing entries
(`authority`, `applies_to`, `owner`, `reviewed`/`review_by`, `source`), advisory-
by-default with repo-local precedence, and a human-gated promotion path — skills
never write to it. Pin `org_knowledge.ref` to a reviewed tag for change control.
The full model and templates are in [org-knowledge.md](org-knowledge.md).

---

## 13. This repo's configuration (worked example)

For reference, `docs/workflow/config.yml` in this repository enforces:

- **`review` — `commit` mode**, scoped `["." , ":(exclude)docs"]`. A docs-only
  change keeps the gate fresh; any change to skills, scripts, or the tool requires
  a fresh review before push.
- **`check_workflow_compliance` — `age` mode, 168h.** Compliance reflects process
  rather than a specific diff, so a weekly window fits better than a commit gate.
- **No `capture` gate.** `aw-capture` still records its marker, but blocking a
  *push* on capture staleness is noise, so it is omitted from `gates.checks`.

Enforcement is a husky `pre-push` hook running `node .scripts/aw-gate.js check`,
`node .scripts/aw-gate.js trace`, and `node .scripts/aw-gate.js pin check`.
Trace, telemetry, and org knowledge are left disabled by default; pinning is
enabled in this repo because it carries a real self-pin.
