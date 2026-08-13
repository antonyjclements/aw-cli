# AGENTS.md
<!-- AUGMENTED_WORKFLOW_VERSION=0.11.0 -->

This is the repository's portable routing file. It says when to act and where to look; skills and `docs/workflow/` own procedures and reference detail.

## Core Rules

- Inspect the relevant code and docs before editing; follow existing patterns and applicable standards.
- Keep changes scoped to the request. Do not clean up unrelated code or overwrite work you did not create.
- Prefer the smallest verifiable change. Ask only when a material decision cannot be inferred safely.
- Use repo-relative paths in repository artifacts.

## Task Triage

Choose the smallest safe workflow by reversibility, not effort: if the change is wrong, what does undoing it cost? Use a smaller path for cheap-to-undo work, even when it is large. Use the High-Risk path for hard-to-reverse work such as data loss, released contracts, security posture, or behavior others already depend on, even when the diff is one line. The examples below are not exhaustive.

### Trivial Change

For typos, links, comments, formatting, obvious one-line fixes, and tiny docs edits: edit directly, run the narrowest relevant check, and skip specs, plans, compliance, and review unless requested.

### Small Fix

For contained bugs, local config or docs changes, and narrow test fixes: edit directly when the cause is clear; otherwise use `aw-debug`. Run targeted checks. Update durable docs only when behavior, workflow, setup, or intent changes.

### Feature or Behavior Change

For product or workflow behavior, APIs, UX, contracts, or durable intent: ensure the living spec is current, use `aw-plan` when sequencing matters, implement through the configured work step, map acceptance criteria to tests or explicit checks, and run review and workflow compliance before PR creation.

### High-Risk or Cross-Cutting Change

For auth, payments, security, migrations, CI/CD, architecture, multi-module work, data-loss risk, or anything hard to reverse: follow the full spec, plan, human review, work, review, compliance, commit/PR, and configured pipeline path. Require explicit acceptance criteria and review evidence; treat missing evidence as a blocker unless the user accepts the risk.

## Context Sources

- `docs/standards/index.yml`: applicable enforceable project rules. Read the index and only the relevant standards before non-trivial planning, implementation, review, or documentation.
- `docs/features/<feature>/spec.md`: current behavior and durable intent. Plans are temporary execution artifacts at `docs/features/<feature>/plan.md`.
- `docs/decisions/`: immutable decisions; `docs/learnings/`: reusable project knowledge; `docs/product/prds/`: product input; `docs/brainstorms/` and `docs/sessions/`: self-describing transient context.
- `docs/context/wiki.md`: optional orientation. If older than 30 days or behind several unprocessed session logs, verify important claims against their source artifacts.
- `README.md`: user-facing setup and operation. Update it when setup, commands, configuration, architecture, repository structure, or workflow behavior changes.

Keep durable artifacts when knowledge is worth rediscovering later. Keep intent alive in specs, let plans expire, and record decisions immutably. At natural pauses, offer `aw-capture` for resolved trade-offs, corrections, reusable learnings, and meaningful session wrap-up; write immediately only when the target is explicit and repo-local.

## Workflow Step Routing

- Read `docs/workflow/config.yml` before invoking a configurable step. A configured `workflow.steps.<step>.skill` or `workflow.auxiliary.<key>.skill` replaces the bundled default; blank means use the default. See `docs/workflow/README.md` for key maps, contracts, and legacy migration.
- When `workflow.design.enabled` is true, run configured non-empty design hooks at their documented checkpoints; design reference material usually lives in `docs/standards/`.
- Read `workflow.implementation.test_policy` before implementation; blank defaults to `acceptance-first`. Follow the policy described in `docs/workflow/README.md`.
- Use `docs/workflow/field-guide.md` for task and team-size sequences, or `aw-help` when the next step is unclear. Pass each step's artifact or identifier to the next step.
- A ticket is a valid entrypoint. Fetch it through the configured tool, follow its links to source artifacts, and stop if it conflicts with the living spec or decisions.
- Human review is opt-in unless the user asks, reviewers are configured, or the change is High-Risk.
- After PR creation, run `workflow.steps.monitor_pipeline.skill` when configured; otherwise skip monitoring. Fix only failures caused by the current branch.

## Delivery Rules

- Run the narrowest meaningful checks first and broaden them with risk. For behavior changes, add nearby coverage when feasible; report checks that could not run.
- Check branch and worktree state before substantial edits. Never discard user changes, stage unrelated files, use destructive git commands, or commit to the default branch without explicit approval.
- Commit, push, or open a PR only when the user asks. Keep session-log and synthesis commits separate from feature or fix commits.
- Follow enabled gates in `docs/workflow/config.yml` and their commands in `docs/workflow/README.md`.
- Before finishing, summarize changes, files touched, checks run, omitted checks and why, and remaining risks or follow-ups.
