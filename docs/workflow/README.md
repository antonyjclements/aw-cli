# Workflow Config

`docs/workflow/config.yml` customizes how Augmented Workflow runs in this repo. Most repos should leave skill overrides blank; blank values use the bundled defaults.

Task-size routing belongs in `AGENTS.md`. Use `config.yml` for execution details such as replacement skills, implementation test policy, design hooks, PR templates, commit conventions, CI monitoring, and human reviewers.

For a step-by-step guide on which skills to run and when — by task type and team size — see [field-guide.md](field-guide.md).

## Minimal Example

```yaml
workflow:
  implementation:
    test_policy: acceptance-first
  steps:
    work:
      skill: ""
    check_workflow_compliance:
      skill: ""
  auxiliary:
    research_slack:
      skill: ""
  design:
    enabled: false
    reference_paths:
      - docs/standards
    hooks:
      discovery:
        skill: ""
      spec_review:
        skill: ""
      plan_review:
        skill: ""
      implementation_review:
        skill: ""
      pre_pr:
        skill: ""
pull_request:
  template:
    title: ""
    body: ""
git:
  commit:
    format: conventional
    scope_required: false
    template: "<type>(<scope>): <description>"
    allowed_types: [feat, fix, docs, chore, refactor, test, ci, build, perf, style]
    examples:
      - "docs(readme): update usage guide"
post_pr:
  ci_monitor:
    provider: manual
human_review:
  spec:
    reviewers: []
  plan:
    reviewers: []
```

## Schema

| Path | Type | Default | Description |
| --- | --- | --- | --- |
| `workflow.implementation.test_policy` | string | `acceptance-first` | How implementation work maps acceptance criteria to tests or checks. |
| `workflow.steps.<step>.skill` | string | `""` | Optional replacement skill for a workflow lifecycle step. Blank uses the bundled default. |
| `workflow.auxiliary.<key>.skill` | string | `""` | Optional replacement skill for a helper capability. Blank uses the bundled default. |
| `workflow.design.enabled` | boolean | `false` | Master switch for additive design-team hooks. |
| `workflow.design.reference_paths` | string list | `["docs/standards"]` | Repo-relative files or directories containing design reference material. |
| `workflow.design.hooks.<hook>.skill` | string | `""` | Optional design skill for a design hook. Blank skips that hook. |
| `pull_request.template.title` | string | `""` | Optional path or URL for a PR title template. |
| `pull_request.template.body` | string | `""` | Optional path or URL for a PR body template. |
| `git.commit.format` | string | `conventional` | Commit message convention used by bundled commit skills. |
| `git.commit.scope_required` | boolean | `false` | Whether commit messages must include a non-empty scope. |
| `git.commit.template` | string | `"<type>(<scope>): <description>"` | Commit subject template. |
| `git.commit.allowed_types` | string list | conventional types | Allowed commit types. |
| `git.commit.examples` | string list | docs example | Example commit messages for style guidance. |
| `post_pr.ci_monitor.provider` | string | `manual` | Post-PR monitor provider. `manual` disables automated monitoring. |
| `human_review.spec.reviewers` | string list | `[]` | GitHub usernames requested on spec review PRs. |
| `human_review.plan.reviewers` | string list | `[]` | GitHub usernames requested on plan review PRs. |
| `gates.enabled` | boolean | `false` | Master switch for freshness enforcement. When false, `aw-gate.js check` is a no-op. |
| `gates.require_receipt` | boolean | `false` (installer ships `true`) | When true, `aw-gate.js record <gate>` refuses to stamp unless the skill has just written a fresh, gate-matching receipt (proof-of-work). Bypass once with `--no-receipt` for bootstrap. |
| `gates.receipt_dir` | string | `.aw/receipts` | Git-ignored directory where receipts are written and consumed (single-use). |
| `gates.receipt_max_age_minutes` | number | `180` | Maximum age, in minutes, a receipt stays valid for `record` to accept it. |
| `gates.checks.<name>.require_receipt` | boolean | inherits `gates.require_receipt` | Per-gate override of the receipt requirement, e.g. strict for `review`, relaxed for `synthesize`. |
| `gates.state_file` | string | `.aw-gate-state.json` | Git-ignored per-checkout file holding the last-run timestamp and commit for each gate. |
| `gates.checks.<name>.mode` | string | `age` | `age` (wall-clock window), `commit` (relevant paths changed since the recorded commit), or `commit-and-age` (both must pass). |
| `gates.checks.<name>.max_age_hours` | number | — | Maximum age, in hours, a recorded gate stays fresh. Required for `age` and `commit-and-age` modes. |
| `gates.checks.<name>.paths` | string list | whole tree | Git pathspecs scoping which changes invalidate a `commit`-mode gate, e.g. `["src", ":(exclude)docs"]`. Omitted means any commit invalidates it. |
| `telemetry.enabled` | boolean | `false` | When true, `aw-gate.js record` appends a no-PII event to the telemetry log. |
| `telemetry.path` | string | `docs/metrics/events.jsonl` | Base path of the git-tracked JSONL event log. With monthly rotation the month is inserted (`events-YYYY-MM.jsonl`). |
| `telemetry.rotation` | string | `monthly` | `monthly` shards the log per month (bounds growth and cuts merge contention); `none` writes a single file. |
| `telemetry.retention_months` | number | `12` | `prune-telemetry` deletes month shards older than this many months (git history is the archive). `0` keeps all. |
| `tracking.enabled` | boolean | `false` | Per-repo kill switch for skill invocation tracking. When true, `aw-gate.js track <skill>` appends a JSONL line to the tracking log; when false, the command is a silent no-op. |
| `tracking.path` | string | `docs/metrics/skills.jsonl` | Base path of the git-tracked skill invocation log. With monthly rotation the month is inserted (`skills-YYYY-MM.jsonl`). |
| `tracking.rotation` | string | `monthly` | `monthly` shards the log per month (bounds growth and cuts merge contention); `none` writes a single file. Same semantics as `telemetry.rotation`. |
| `tracking.retention_months` | number | `12` | `prune-telemetry` deletes tracking shards older than this many months alongside telemetry shards. `0` keeps all. |
| `tracking.session_file` | string | `.aw/session` | Git-ignored file holding the current session UUID; reused while its mtime is within the TTL below. Group `aw-init --with-gates` gitignores this path. |
| `tracking.session_ttl_hours` | number | `8` | Reuse the session UUID while the session file's mtime is within this window; mint a new one afterwards. |
| `org_knowledge.source` | string | `""` | Git URL of the org-shared learnings/standards repo. Blank disables org sync. |
| `org_knowledge.ref` | string | `main` | Branch or tag of the org knowledge repo to sync. |
| `org_knowledge.cache_dir` | string | `.aw-org-cache` | Git-ignored local cache the org repo is cloned into. |
| `org_knowledge.paths.learnings` | string | `learnings` | Learnings subdirectory within the org knowledge repo. |
| `org_knowledge.paths.standards` | string | `standards` | Standards subdirectory within the org knowledge repo. |
| `trace.enabled` | boolean | `false` | Master switch for spec traceability. When false, `trace` exits 0 and `trace-annotate` skips writes. |
| `trace.spec_paths` | string list | `["docs/features/*/spec.md"]` | Git pathspecs for living spec files. Only `/spec.md` files are accepted as requirement sources. |
| `trace.test_paths` | string list | feature/test globs | Git pathspecs for files that may carry test anchors. |
| `trace.code_paths` | string list | `["src"]` | Git pathspecs for files that may carry behavior entry-point anchors. |
| `trace.require_code_anchor` | boolean | `false` | When true, requirements with no code anchor fail trace. When false, they warn only. |
| `pin.enabled` | boolean | `false` | Master switch for behavior pinning. When false, `pin run` and `pin check` exit 0. |
| `pin.manifest_paths` | string list | `["docs/features/*/behavior-pin.yml"]` | Git pathspecs for behavior pin manifests. |
| `pin.worktree_dir` | string | `.aw/pin` | Git-ignored worktree root used for old-tree runs. |
| `pin.out` | string | `.aw/pin/equivalence.json` | JSON result path for `pin run`. |
| `pin.timeout_seconds` | number | `900` | Per-command timeout for setup and harness commands. |
| `e2e.enabled` | boolean | `false` | Master switch for end-to-end test authoring. When false, the capability is skipped entirely. |
| `e2e.trigger_paths` | string list | `[]` | Git pathspecs for the user-facing surface whose changes warrant e2e coverage. Empty means unscoped — every change is a candidate. |
| `e2e.test_paths` | string list | `[]` | Git pathspecs for files that count as e2e specs. Empty means the configured skill uses the project's own convention and `trace` skips the marked-coverage check. |
| `e2e.run_scope` | string | `affected` | How much of the suite runs during local verification: `affected`, `full`, or `none` (CI owns the run). |
| `workflow_trace.enabled` | boolean | `false` | Master switch for deterministic workflow execution breadcrumbs. |
| `workflow_trace.path` | string | `.aw/workflow-trace.jsonl` | Git-ignored JSONL file for local process events. |
| `workflow_trace.max_events` | number | `10000` | Maximum events retained after each append. Older events are dropped first. |
| `workflow_trace.max_bytes` | number | `5242880` | Approximate maximum trace-file size retained after each append. Older events are dropped first. |
| `workflow_trace.require_tier` | boolean | `false` | When true, `workflow-check` fails unless a tier event exists. The installer writes `true` in its sample config. |
| `workflow_trace.required_gates` | string list | `[]` | Gate events that must appear in the workflow trace when enabled. The installer writes review/compliance defaults in its sample config. |

## Enforcement Gates, Telemetry, Org Knowledge, Traceability, End-to-End Coverage, Workflow Trace, and Behavior Pinning

These seven capabilities are opt-in, disabled by default, and all powered by one
dependency-free helper, `.scripts/aw-gate.js`, installed with
`aw-init --with-gates` (or by re-running the installer with that flag). None of
them require an agent to run in CI — the enforcement path is fully deterministic.

### Freshness gates (`gates`)

The LLM-driven review, compliance, and memory-synthesis skills cannot run as a blocking CI check on
their own. Instead, this workflow converts them into a **freshness contract**:

1. After a successful run, the skill writes a proof-of-work **receipt**
   (`node .scripts/aw-gate.js receipt <gate> --summary "..."`) and then stamps a
   marker: `node .scripts/aw-gate.js record <gate> [--detail "..."]`. This writes
   the last-run timestamp **and the current commit** to the git-ignored
   `gates.state_file`. When `gates.require_receipt` is on, `record` refuses to
   stamp without a fresh receipt and consumes it (single-use), so an agent cannot
   clear the gate by running `record` without actually running the skill.
2. A deterministic checker enforces the contract:
   `node .scripts/aw-gate.js check` exits non-zero when any gate under
   `gates.checks` fails its mode, and exits 0 when `gates.enabled` is false.

Wire `check` wherever you want it to block: a Git `pre-commit`/`pre-push` hook, or
a required CI job. The workflow ships the script and the contract; the consumer
chooses the enforcement point. The bundled event names are `review`, `capture`,
`check_workflow_compliance`, and `synthesize`; configure any subset under
`gates.checks`.

Each gate picks a **mode**:

- **`age`** (default): the gate is fresh while it was recorded within its
  `max_age_hours` window. Simple and git-free; a gate recorded within its window
  passes regardless of intervening commits. Best for time-triggered checks that
  should re-run periodically even when nothing changed (e.g. compliance).
- **`commit`**: the gate is fresh while nothing in its `paths` changed since the
  recorded commit (`git diff` between that commit and `HEAD`). Answers "has the
  *current* code been reviewed?" rather than "did review run recently?", and is
  fully deterministic in CI. Best for change-triggered checks (review, spec drift).
- **`commit-and-age`**: both conditions must hold.

`check` compares `commit`-mode gates against `HEAD` by default; pass
`--against worktree` in a `pre-commit` hook so staged/unstaged edits (not yet in
`HEAD`) are considered. Commit mode requires that the recorded commit still be
reachable — a rebase, squash, or shallow clone that drops it fails the gate and
asks you to re-run. In CI, fetch enough history (e.g. `fetch-depth: 0`) so the
recorded commit is present.

### Telemetry (`telemetry`)

When `telemetry.enabled` is true, the same `record` call also appends a no-PII
event (`ts`, `event`, `detail`, `source`) to the git-tracked JSONL log, so an
engineering-effectiveness team can aggregate it directly from version control.

Because the log is append-only and git-tracked, two safeguards keep it from
becoming a growth or merge-conflict problem:

- **Monthly rotation** (`telemetry.rotation: monthly`, the default) writes to
  `events-YYYY-MM.jsonl` instead of one ever-growing file. Each file stays bounded,
  and concurrent branches usually append to different months. Set `rotation: none`
  to keep the legacy single-file behavior.
- **`union` merge** — `aw-init --with-gates` adds `docs/metrics/events*.jsonl merge=union`
  to `.gitattributes`, so when branches do append to the same shard, git keeps both
  sides' lines instead of raising a conflict. Order does not matter; every line
  carries its own `ts`.
- **Retention** — `node .scripts/aw-gate.js prune-telemetry` deletes shards older
  than `telemetry.retention_months` (default 12; git history is the archive).
  `aw-synthesize-memory` runs it as part of its retention pass.

Schema and aggregation notes live in `docs/metrics/README.md`.

### Skill tracking (`tracking`)

When `tracking.enabled` is true, every skill emits `node .scripts/aw-gate.js track <skill>` at its first step, appending a JSONL line (`ts`, `session_id`, `skill`, optional `workflow_step`, `source: "skill"`) to `tracking.path` (`docs/metrics/skills.jsonl` by default, month-sharded → `skills-YYYY-MM.jsonl`). The workflow-step mapping is owned by `aw-gate.js`; per-repo `workflow.steps.<step>.skill` overrides win when present.

The writer is deliberately fire-and-forget: silent when tracking is disabled, when the config file is missing, or when any internal error occurs — it never blocks the caller. Skills always emit through a guard so repos installed without `--with-gates` (no `.scripts/aw-gate.js`) also stay silent.

Same shard/merge/retention story as telemetry: `aw-init --with-gates` registers `docs/metrics/skills*.jsonl merge=union` in `.gitattributes` alongside the telemetry entry, and `node .scripts/aw-gate.js prune-telemetry` deletes tracking shards older than `tracking.retention_months` in the same pass that prunes telemetry.

Sessions are grouped through the gitignored `tracking.session_file` (default `.aw/session`), whose UUID is reused while its mtime is within `tracking.session_ttl_hours`. No hook required, so tracking works in environments where custom lifecycle hooks are forbidden.

Design and analysis intent live in `docs/workflow/tracking.md`.

### Org-shared knowledge (`org_knowledge`)

Set `org_knowledge.source` to a git URL to add a second, org-wide tier of
learnings and standards alongside the repo-local `docs/learnings/` and
`docs/standards/`, replacing the per-machine `~/.agents/learnings/` fallback.
`node .scripts/aw-gate.js org-sync` shallow-clones (or updates) that repo into the
git-ignored `org_knowledge.cache_dir`. Skills that read learnings or standards
(`aw-capture`, `aw-synthesize-memory`, `aw-discover-standards`) consult the org
tier when it is configured. Precedence: repo-local first, then org-shared.

Because one edit to the org base steers agents across every subscribing repo, it
is **governed content, not just a synced folder**:

- **One accountable owner** (a senior lead or distinguished engineer, named in the
  org repo's `CODEOWNERS`) owns what earns org-wide status, the review cadence, and
  retiring stale entries. Changes to the org base are PR-reviewed, not pushed.
- **Advisory by default, repo-local always wins.** Agents treat an org entry as
  advisory unless it is marked `authority: required`; a `required` entry that
  conflicts with repo-local guidance is surfaced to a human, not auto-resolved.
- **Entries are self-describing.** Each carries `authority`, `applies_to`,
  `owner`, `reviewed`/`review_by`, and a `source` link; entries past `review_by`
  or missing metadata are treated as lower-confidence.
- **Promotion is human-gated.** A repo-local learning earns org-wide status via a
  PR to the org base; skills never write to the org tier.
- **Consumers pin `org_knowledge.ref`** to a reviewed tag for change control.

The full governance model, templates (`CODEOWNERS`, `GOVERNANCE.md`, entry
frontmatter), and promotion path live in the augmented-workflow project at
`docs/workflow/org-knowledge.md`.

### Spec traceability (`trace`)

`trace` links living spec requirements to tests and optional behavior entry
points without running an agent in CI:

```sh
node .scripts/aw-gate.js trace [--base origin/main] [--json] [--out docs/trace.json]
```

The command resolves every `@spec` anchor, fails when a requirement has no test
anchor, warns by default when no code anchor exists, and with `--base` fails when
a changed anchored test is not paired with a changed owning spec or a
`Spec-Override:` commit trailer. It is deterministic and is **not** a freshness
gate, so do not add it under `gates.checks`.

`trace --suggest-e2e` is a separate read-only mode that reports which
requirements an existing e2e suite already covers, for repos adopting the `[e2e]`
marker retrospectively. It enforces nothing: it exits 0 even when the enforcing
`trace` run is failing, reporting pre-existing errors without acting on them, and
exits 2 only when `trace.enabled` is false — see
[Adopting the marker in a repo that already has e2e tests](#adopting-the-marker-in-a-repo-that-already-has-e2e-tests).

Skills write annotations through the deterministic proxy:

```sh
node .scripts/aw-gate.js trace-annotate --batch .aw/tmp/trace-intents.<token>.json --delete-batch-on-success
```

When `trace.enabled` is false, `trace-annotate` skips target writes and cleans
safe `.aw/tmp/trace-intents.*.json` batch files. When enabled, it validates IDs,
merges batch labels, and inserts only explicit line-targeted annotations.

### Workflow execution trace (`workflow_trace`)

`workflow_trace` records process breadcrumbs so later checks can answer whether
the selected workflow path was actually followed:

```sh
node .scripts/aw-gate.js workflow-record tier --tier feature --reason "workflow behavior changed"
node .scripts/aw-gate.js workflow-check [--base origin/main]
```

When enabled, `record <gate>` automatically appends a `gate` event for the same
gate name, so review/compliance/synthesis gate execution is traceable without
extra skill-specific logic. `workflow-check` validates configured requirements
such as a chosen tier and required gate events. Pass `--base` or
`--since-commit` to scope checks to events recorded by commits in that range.
After each append, the helper retains only the newest `max_events` and trims
oldest lines until the file is under `max_bytes`. When disabled, both commands
are clean no-ops.

### Behavior pinning (`pin`)

`pin` runs characterization harnesses against both the old tree declared in a
manifest and the current checkout. With `mode: reference-repo`, it compares the
current repo to a pinned external/local reference repo through a black-box
harness:

```sh
node .scripts/aw-gate.js pin run [--json] [--out .aw/pin/equivalence.json]
node .scripts/aw-gate.js pin check [--base origin/main] [--json]
```

`pin run` accepts only empty commands or `node <repo-relative .js path>` for
manifest `setup` and `harness` entries; it does not execute shell strings.
It reports `pin-not-characterizing` when the oracle fails on old code and
`equivalence-broken` when old passes but new fails. `pin check` fails when one
commit changes both the judged subject and its manifest/oracle/support files,
unless the commit has a manifest-scoped `Pin-Override:
docs/features/<feature>/behavior-pin.yml — <reason>` trailer. A green pin proves
equivalence, not correctness.

Reference-repo manifests declare `reference.repo` and `reference.ref`. Their
current-tree Node harness receives `AW_PIN_REFERENCE_ROOT`,
`AW_PIN_CANDIDATE_ROOT`, `AW_PIN_MANIFEST`, `AW_PIN_MODE`, and optional
`AW_PIN_GOLDEN_ROOT`; exit code `10` reports `pin-not-characterizing`. Optional
`golden` metadata records fixture provenance without replacing live reference
execution.

## End-to-End Test Authoring (`e2e`)

End-to-end frameworks are stack-specific, so this workflow ships no bundled e2e
skill. It defines the slot and the contract; the repo supplies the tool. Point
`workflow.auxiliary.e2e_tests.skill` at a Playwright, Cypress, XCUITest, or
in-house skill and set `e2e.enabled: true`.

E2E authoring is **not** a lifecycle step and **not** a freshness gate. It hangs
off the implementation test policy, because e2e specs are the automation of
user-facing acceptance criteria. The invocation pattern mirrors
`pin_behavior`: routing lives in `workflow.auxiliary`, enablement and scope live
in this top-level block, and `aw-work` invokes it at a documented checkpoint.

Checkpoints:

- **`aw-work` Phase 1**, after acceptance criteria are mapped and before Phase 2
  edits, when `e2e.enabled` is true, the skill is configured, and the change
  touches `e2e.trigger_paths`. Under `acceptance-first`, `tdd`, or `bdd` the
  specs are authored before feature code.
- **`aw-work` Phase 3**, run the suite according to `e2e.run_scope`. Local runs
  stay narrow; `full` belongs to CI via `workflow.steps.monitor_pipeline.skill`.
- **`aw-check-workflow-compliance`**, which reports a finding when a change
  touches `e2e.trigger_paths` with the capability enabled but carries neither
  e2e coverage nor a stated exception.

`e2e.trigger_paths` uses git pathspec semantics, like `gates.checks.<name>.paths`
and `trace.*_paths`. The list is a positive allowlist — paths matching nothing in
it are already out, so `:(exclude)` entries are only needed to carve holes inside
a broader positive pattern:

```yaml
e2e:
  enabled: true
  trigger_paths:          # narrow positive: no exclude needed
    - src/app
    - src/components
  test_paths: [e2e]
  run_scope: affected
```

Configured skills must preserve a small contract:

- **Accept** the acceptance criteria (or spec/plan/ticket path), the changed
  paths, and the `e2e.*` config.
- **Return** the spec files written, the command that runs them, and **which
  acceptance criterion each spec covers** — that mapping is what feeds compliance
  reporting and the PR body.
- **State unsupported cases explicitly** rather than silently producing nothing.

Because the contract names the capability rather than the tool, swapping
frameworks is a config change. Tool-specific conventions — selector strategy,
fixtures, wait policy, auth-state reuse, external test-management identifiers —
belong in `docs/standards/` indexed in `docs/standards/index.yml`, not in this
config. Skills that onboard tests into an external test-management platform
(Xray, TestRail, Zephyr) own that integration and its credentials themselves;
the workflow does not model it.

### Relationship to gates and traceability

E2E authoring is **not** a freshness gate and must not be added under
`gates.checks`. Gates exist for LLM-judgment steps that cannot run in CI; an e2e
suite is a deterministic run, so CI owns enforcement. The coupling is indirect:
`aw-check-workflow-compliance` reports e2e coverage, so the finding rides inside
that gate's receipt.

Note that a `mode: age` compliance gate is time-triggered, so it will not re-fire
when new in-scope code lands inside its window. Repos that want the e2e finding
to block on change should use `mode: commit-and-age` with `paths` mirroring
`e2e.trigger_paths`.

E2E specs are picked up by the default `trace.test_paths` — the `*.spec.ts`
pathspec matches at any depth, so `e2e/login.spec.ts` needs no config change —
and `@spec` anchors in them satisfy a requirement's test-anchor obligation.

Trace records no test layer on an anchor, only its ID, file, and line, so
`untested-requirement` is satisfied by a unit test just as well as by an e2e
spec. To express "this requirement specifically needs end-to-end proof", mark the
requirement heading with an exact `[e2e]` suffix:

```markdown
### PAY-004 — Checkout completes with a saved card [e2e]
```

When `e2e.enabled` is true, `trace` then fails with `missing-e2e-coverage` if a
marked requirement has no anchor in a file matching `e2e.test_paths`, and warns
with `suspect-e2e-marker` on near-misses such as `[E2E]`, `(e2e)`, `**[e2e]**`,
a backticked `` `[e2e]` ``, or a trailing `[e2e].`. With `e2e.test_paths` empty
the check is skipped and marked requirements raise `e2e-paths-unset`; a list of
nothing but `:(exclude)` pathspecs fails with `e2e-paths-exclude-only`, since it
would match the whole repository and satisfy every marker from any test. One e2e
test may satisfy several requirements through a multi-ID anchor
(`// @spec PAY-004, PAY-005`).

`e2e.test_paths` is independent of `trace.test_paths` — e2e specs may live
anywhere, including outside the trace globs. `trace` scans the two lists
separately and merges the anchors, so an e2e spec is always discovered even when
no trace glob reaches it, and an `:(exclude)` in one list never suppresses
matches the other legitimately covers. A file can therefore be a valid anchor
source for `untested-requirement` while still not counting as e2e coverage.

The marker must be a suffix. Placed before the em-dash it does not match the
requirement heading pattern and the requirement disappears from `trace` with no
error. There is no override trailer for marked coverage — it is a whole-tree
invariant, so a per-commit escape hatch would clear once and fail on the next
commit. Marking a requirement and adding its test may still be separate commits:
anchors found only through `e2e.test_paths` are exempt from
`uncoupled-test-change`, so the commit answering a marker needs no
`Spec-Override:` trailer. Anchors in `trace.test_paths` keep the coupling rule.
The full rule for what earns a marker lives in the installed
`docs/standards/e2e-coverage.md`.

Keep external test-management identifiers out of `@spec` anchors. The anchor
pattern accepts any `[A-Z][A-Z0-9]{1,7}-\d{3,}` ID, so a Jira or Xray key such as
`PROJ-1234` parses as a requirement ID and `trace` reports `dangling-test-ref`
when it is not in a living spec. Record platform keys in a separate annotation.

### Adopting the marker in a repo that already has e2e tests

Marking requirements one by one is the wrong first move when a suite already
exists — the repo has already made most of those calls, it just never wrote them
into the specs. `trace --suggest-e2e` prints the candidates and changes nothing:

```bash
node .scripts/aw-gate.js trace --suggest-e2e            # human-readable
node .scripts/aw-gate.js trace --suggest-e2e --json     # or --out <path>
```

It reports two candidate classes, both derived from evidence rather than from
requirement prose:

| Candidate | Meaning | `gate_effect` |
| --- | --- | --- |
| `covered-unmarked` | Unmarked, but already anchored in a file matching `e2e.test_paths` | `none` |
| `near-miss-marker` | Title ends in a variant such as `[E2E]`, `(e2e)`, or `**[e2e]**`, which `trace` does not honor | `none` if covered, else `enforces` |

The survey also warns about what the flip would break before you make it:
`would-become-dangling` lists anchors in `e2e.test_paths` with no living spec —
retired IDs or external tracker keys — which turn into `dangling-test-ref` errors
the moment `e2e.enabled` is true. Clear those before flipping. If
`e2e.test_paths` is non-empty but matches no tracked files, the survey reports
that rather than "no candidates".

Each candidate carries the heading's current text and the proposed replacement,
so applying the set is a mechanical edit. `gate_effect: none` means the
requirement already has the coverage the marker would demand, so marking it
cannot turn `trace` red; `enforces` means the marker starts being checked on the
next run and the test still has to be written.

Requirements with no e2e anchor and no marker variant are never suggested. Which
requirements *deserve* end-to-end proof is a judgment the standard puts with a
human at spec time, and a keyword guess dressed up as a finding would quietly
move that bar into a script.

The mode is advisory: it exits 0 even when it has suggestions, and it does not
run the coverage gate, so it stays readable while `trace` is failing for other
reasons. It needs `trace.enabled: true` but deliberately not `e2e.enabled`, which
is what makes the adoption order work — point `e2e.test_paths` at the existing
suite, survey the candidates, apply the markers, then set `e2e.enabled: true` on
a tree that is already green.

## Workflow Step Keys

```text
prd -> aw-prd
brainstorm -> aw-brainstorm
create_spec -> aw-create-spec
request_human_review -> aw-request-human-review
plan -> aw-plan
review -> aw-review
create_tickets -> aw-create-tickets
work -> aw-work
check_workflow_compliance -> aw-check-workflow-compliance
commit -> aw-commit
commit_push_pr -> aw-commit-push-pr
monitor_pipeline -> (no bundled skill; set workflow.steps.monitor_pipeline.skill)
```

## Auxiliary Skill Keys

```text
refresh -> aw-refresh
debug -> aw-debug
create_worktree -> aw-create-worktree
capture -> aw-capture
discover_standards -> aw-discover-standards
research_slack -> (no bundled skill; set workflow.auxiliary.research_slack.skill for enterprise routing)
pin_behavior -> aw-pin-behavior
e2e_tests -> (no bundled skill; set workflow.auxiliary.e2e_tests.skill)
resolve_pr_feedback -> aw-resolve-pr-feedback
synthesize_memory -> aw-synthesize-memory
```

## Design Hooks

Design hooks are additive checkpoints for teams with design skills. They do not replace the core workflow steps; use `workflow.steps.<step>.skill` when a design-owned skill should replace an entire lifecycle step.

Design reference material lives in repo-local docs, usually `docs/standards/`, and should be indexed in `docs/standards/index.yml` when it is intended to guide agents. Use feature specs for feature-specific UX requirements, decisions for durable design tradeoffs, and learnings for corrections that should influence future work.

Hook keys:

```text
discovery -> after PRD intake or during brainstorming, before durable UX intent is settled
spec_review -> after a spec is created or updated
plan_review -> after a plan is created, before tickets or implementation
implementation_review -> after UI-affecting implementation work
pre_pr -> before PR creation for design acceptance evidence
```

When `workflow.design.enabled` is false, agents skip design hooks. When it is true, agents invoke only hooks with a non-empty `skill`, passing the current artifact path, diff, or PR URL that matches the hook. Design hook skills should read `workflow.design.reference_paths`, report pass/fail evidence or findings, and state any unsupported contract element.

## Artifact Handoff Contract

Each workflow step returns the artifact path or ID that becomes input to the next step. Custom replacement skills must preserve this contract.

- `aw-prd` outputs `docs/product/prds/<prd>.md` -> pass to `aw-brainstorm` when ambiguity remains, or `aw-create-spec` when ready for a direct spec draft.
- `aw-brainstorm` usually outputs `docs/features/<feature>/spec.md` -> pass to `aw-plan`; when the user asks for PRD output, route to `aw-prd`.
- `aw-create-spec` outputs `docs/features/<feature>/spec.md` -> pass to `aw-plan`.
- When a PRD becomes a spec, mark the PRD `status: promoted`, set `promoted_to` to the spec path, and leave the PRD body unchanged.
- When a source artifact is no longer needed in the working tree, mark it `status: archived`; `aw-refresh cleanup` removes it from the working tree and index while git preserves history.
- `aw-plan` outputs `docs/features/<feature>/plan.md` -> pass to `aw-create-tickets` or `aw-work`.
- `aw-create-tickets` outputs ticket IDs/URLs -> pass one ticket at a time to `aw-work`.
- `aw-commit-push-pr` outputs the PR URL -> invoke `workflow.steps.monitor_pipeline.skill` with it when configured.

## Test Policies

| Value | Meaning |
| --- | --- |
| `acceptance-first` | Start from acceptance criteria, then choose the lightest automated or manual verification that proves them. |
| `tdd` | Write failing tests before implementation, then make them pass. |
| `bdd` | Express expected behavior in scenario-style tests or checks before implementation where practical. |
| `characterization-first` | Capture current behavior with tests before changing legacy or poorly understood code. |
| `test-after` | Implement first, then add targeted tests/checks before shipping. |
| `manual-verification` | Use explicit manual checks when automation is unavailable or disproportionate. |
| `none` | No test policy is enforced by workflow config. Use only for intentionally unverified work. |

## Legacy Fields

Older installs may contain renamed fields or keys. Run `skills/aw-init/scripts/upgrade.sh --repo /path/to/repo --dry-run` to preview the migration, then `--apply` to migrate safely. Do not maintain old and new shapes side by side.

| Legacy shape | Current shape |
| --- | --- |
| `ticket_creation.skill` | `workflow.steps.create_tickets.skill` |
| `git.commit.skill` | `workflow.steps.commit.skill` |
| `post_pr.ci_monitor.skill` | `workflow.steps.monitor_pipeline.skill` |
| `research.slack.skill` | `workflow.auxiliary.research_slack.skill` |
| Step keys `import_prd`, `create_prd` | Step key `prd` |
| Step keys `review_code`, `review_spec`, `review_plan` | Step key `review` |
| Auxiliary key `simplify_code` | Step key `review` (`aw-review simplify`) |
| Auxiliary keys `index_features`, `refresh_decisions`, `refresh_solutions` | Auxiliary key `refresh` |
| Auxiliary keys `log_decision`, `record_retrospective`, `capture_solution`, `log_session` | Auxiliary key `capture` |
| Auxiliary key `clean_artifacts` | Removed — cleanup is the `aw-refresh cleanup` mode, no config key |
| Helper keys misplaced under `workflow.steps` | The matching `workflow.auxiliary.<key>.skill` |

Non-skill configuration fields are unchanged and remain authoritative, including `git.commit.*`, `pull_request.template`, `post_pr.ci_monitor.provider`, and `human_review.*.reviewers`. The migration preserves unknown fields and stops for manual review when old and new routing fields conflict.
