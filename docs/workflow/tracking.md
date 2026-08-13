# Tracking

Records one line per skill invocation to a git-tracked JSONL log so cross-repo analysis can answer:

1. Where does the workflow break down? (session-ordered skill sequences)
2. Is AW making things faster? (upstream duration; combine with GitHub PR data)
3. What parts of the workflow are used most? (skill frequency, entry-point distribution)

Follows the same pattern as `docs/metrics/events*.jsonl` — see [Shard telemetry with union-merge and retention](../decisions/2026-07-03-shard-telemetry-with-union-merge-and-retention.md). No network calls, no keys, no dev setup.

## Config

In `docs/workflow/config.yml`:

```yaml
tracking:
  enabled: false                       # per-repo kill switch
  path: docs/metrics/skills.jsonl      # base path; sharded when rotation is set
  rotation: monthly                    # or "none" for a single file
  retention_months: 12                 # aw-synthesize-memory prunes older shards
  session_file: .aw/session            # gitignored; groups events into a session
  session_ttl_hours: 8                 # mint a new session id when the file is older
```

Add `.aw/` to `.gitignore` and `docs/metrics/skills*.jsonl merge=union` to `.gitattributes` (`aw-init` handles both when tracking is enabled).

## When a skill emits

Every AW skill referencing this doc appends one line at the start of the skill, before any real work. Emitting on start (not end) captures the invocation even when the skill aborts, which is what "where does the workflow break down" needs.

If `tracking.enabled` is false or the config file is missing, skip silently. Never block the workflow, never surface an error.

## Payload

One JSON object per line, ISO-8601 UTC timestamp:

```json
{"ts": "2026-07-27T12:34:56.000Z", "session_id": "9f3e...", "skill": "aw-plan", "workflow_step": "plan", "source": "skill"}
```

| Field | Meaning |
| --- | --- |
| `ts` | ISO-8601 UTC timestamp of the invocation |
| `session_id` | UUID grouping consecutive skill calls; read from `session_file` |
| `skill` | The skill name emitting the event (e.g. `aw-plan`) |
| `workflow_step` | Workflow step key from `config.yml` when the skill maps to one; omit otherwise |
| `source` | Always `"skill"` — distinguishes from `aw-gate` writes to `events*.jsonl` |

`repo_hash` is not stored in the file — the file *is* the repo. Aggregators tag rows with the repo at ingest time.

## Session id

`aw-gate.js track` manages the session file transparently (no hook required):

1. If `session_file` exists and its mtime is within `session_ttl_hours`, reuse the UUID from it.
2. Otherwise, mint a new UUID, write it to `session_file`, and use that.

Good-enough grouping without infrastructure. Not perfect for parallel sessions in the same repo — call that out in analysis, not in the writer.

## Emit command

Skills shell out to `aw-gate.js track` — the same deterministic helper that owns telemetry, receipts, and freshness gates. Always guard the call with a presence check so repos installed without `--with-gates` (no `.scripts/aw-gate.js`) stay silent instead of erroring on module-not-found:

```bash
[ -f .scripts/aw-gate.js ] && node .scripts/aw-gate.js track <skill> || true
```

The workflow step is derived inside `aw-gate.js` from the skill name (canonical map + `workflow.steps.<step>.skill` overrides), so skills pass only their own name. Auxiliary and meta skills (`aw-help`, `aw-init`) map to no step and are recorded with `workflow_step` omitted.

Examples:

```bash
[ -f .scripts/aw-gate.js ] && node .scripts/aw-gate.js track aw-plan || true
[ -f .scripts/aw-gate.js ] && node .scripts/aw-gate.js track aw-help || true
```

Two independent layers guarantee fire-and-forget:

- The presence check keeps the command a no-op when the helper isn't installed (repos without `--with-gates`).
- Inside `aw-gate.js`, the whole `cmdTrack` body is wrapped in `try/catch` and returns silently when `tracking.enabled` is false, the config file is missing, or any internal error occurs.

Skills need no additional conditional logic around the call.

Single-line JSONL appends are atomic on POSIX up to `PIPE_BUF` (~4KB), which the payload sits well under. Concurrent skill calls in the same repo won't tear each other's lines; `merge=union` handles concurrent branches.

## Cross-repo aggregation

Deferred until it matters. When enough repos have tracking on, a batch script clones or pulls the AW-adopted repos and reads their `docs/metrics/skills*.jsonl` shards. Nothing needs to change in AW itself when that day comes.

## Rollout

Skills opt in by adding, near the top of their `SKILL.md`:

> Emit a tracking event per `docs/workflow/tracking.md` at the start of this skill.

Instrument all AW skills — the emitter is silent when disabled, so full coverage from day one means no gaps when a repo flips `enabled: true`.
