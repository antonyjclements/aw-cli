# Workflow Metrics

This directory holds an append-only, git-tracked telemetry log written by
`.scripts/aw-gate.js record` when `telemetry.enabled: true` in
`docs/workflow/config.yml`. It exists so an engineering-effectiveness team can
see whether the capture / review / synthesis flywheel is actually turning.

By default the log is **sharded by month** (`telemetry.rotation: monthly`), so
events land in `events-YYYY-MM.jsonl` rather than one ever-growing file. This
bounds each file's size and means concurrent branches usually append to different
months. Old shards are removed by `node .scripts/aw-gate.js prune-telemetry` once
they pass `telemetry.retention_months` (git history keeps the removed data). With
`rotation: none` a single `events.jsonl` is used instead.

Telemetry is **opt-in and carries no PII** — each line records only an event
type, an ISO timestamp, an optional short detail string, and the source tool.

## Event schema

One JSON object per line:

```json
{ "ts": "2026-07-03T12:00:00.000Z", "event": "review", "detail": "code", "source": "aw-gate" }
```

| Field | Meaning |
| --- | --- |
| `ts` | ISO-8601 UTC timestamp of the event |
| `event` | Gate/skill name, e.g. `review`, `capture`, `check_workflow_compliance`, `synthesize` |
| `detail` | Optional short qualifier (mode, target), or `null` |
| `source` | Emitting tool (`aw-gate`) |

## Aggregating

The log is plain JSONL in version control, so any tool can consume it. Read
across all month shards (`events*.jsonl`) — for a quick local count by event type:

```sh
node -e 'const fs=require("fs"),p=require("path");const d="docs/metrics";const c={};for(const f of fs.readdirSync(d))if(/^events.*\.jsonl$/.test(f))for(const l of fs.readFileSync(p.join(d,f),"utf8").trim().split("\n"))if(l){const e=JSON.parse(l).event;c[e]=(c[e]||0)+1}console.log(c)'
```

Do not hand-edit these files. Rotation and retention are handled for you:
`prune-telemetry` drops shards past `telemetry.retention_months`, and git history
is the archive. If volume ever outgrows a git-tracked log, move telemetry to an
external sink rather than fighting the file here.
