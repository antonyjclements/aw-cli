#!/usr/bin/env node
'use strict';

// augmented-workflow deterministic helper.
//
// One dependency-free CLI that backs six opt-in capabilities configured in
// docs/workflow/config.yml:
//
//   record <event>  Stamp a freshness marker (git-ignored state file) with the
//                   current commit and time, and, when telemetry is enabled,
//                   append a no-PII event to the metrics log (month-sharded by
//                   default: docs/metrics/events-YYYY-MM.jsonl).
//   check           Fail (exit 1) when any configured gate is stale. Each gate
//                   picks a mode: `age` (wall-clock window), `commit` (relevant
//                   paths changed since the recorded commit), or both. Exits 0
//                   when gates.enabled is false. Deterministic; needs no agent.
//                   Wire it into a pre-commit/pre-push hook or a CI job.
//   org-sync        Shallow clone/update the org-shared knowledge repo into a
//                   git-ignored cache dir so skills can read it as a second tier.
//   prune-telemetry Delete telemetry and tracking month shards older than
//                   their configured retention_months (git history is the archive).
//   track <skill>   Append one JSONL line recording a skill invocation to
//                   docs/metrics/skills-YYYY-MM.jsonl. No-op unless
//                   tracking.enabled is true. Fire-and-forget, never fails.
//   trace           Deterministically check spec/test/code traceability.
//   trace-annotate  Deterministically insert explicit spec annotations for skills.
//   workflow-record Deterministically append process breadcrumbs for workflow use.
//   workflow-check  Deterministically validate required workflow breadcrumbs.
//   pin             Run/check behavior pins: two-sided characterization harnesses
//                   that prove a new implementation still matches the old one.
//
// Zero runtime dependencies. Node >= 16.

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execFileSync, spawnSync } = require('child_process');

// The script installs at <repo>/.scripts/aw-gate.js, so the repo root is its
// parent directory. AW_REPO_ROOT overrides for tests or unusual layouts.
const repoRoot = process.env.AW_REPO_ROOT
  ? path.resolve(process.env.AW_REPO_ROOT)
  : path.resolve(__dirname, '..');

const CONFIG_PATH = path.join(repoRoot, 'docs', 'workflow', 'config.yml');

function fail(msg) {
  process.stderr.write(`aw-gate: ${msg}\n`);
  process.exit(1);
}

// --- Minimal YAML reader -------------------------------------------------
// A deliberately partial YAML parser — just enough to read this workflow's
// config.yml without a dependency. Keep config.yml within the supported subset:
// anything outside it may misparse silently. If the config grammar ever needs
// more than this, switch to a real YAML library rather than extending it.
//
// Supported:
//   - nested block mappings by indentation (`key:` then indented children)
//   - scalars: strings (optionally "double"/'single' quoted), booleans
//     (true/false), null (`~` or `null`), integers, floats
//   - block scalar lists:          paths:\n  - a\n  - b
//   - inline flow scalar arrays:   paths: ["a", "b"]   (no commas inside items)
//   - full-line comments (`# ...`), trailing comments outside quotes, and blank lines
//
// NOT supported — avoid in config.yml; these misparse WITHOUT erroring:
//   - inline flow maps (`{a: b}`) and block lists of maps (`- key: value`)
//   - multi-line/folded scalars (`|`, `>`), anchors/aliases (`&`, `*`), tags (`!!type`)
//   - commas inside a quoted item of an inline array
//   - a bare `key:` with no value: this parser opens a child MAPPING ({}), not
//     null or "". For a blank string value write `key: ""` (e.g. source: "").
function stripYamlInlineComment(s) {
  let quote = null;
  for (let i = 0; i < s.length; i += 1) {
    const ch = s[i];
    if (quote) {
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === '#' && (i === 0 || /\s/.test(s[i - 1]))) {
      return s.slice(0, i).trimEnd();
    }
  }
  return s;
}

function parseScalar(s) {
  s = stripYamlInlineComment(s).trim();
  // Inline flow array, e.g. ["src", ":(exclude)docs"]. Split on commas (pathspecs
  // contain none) and parse each element; empty elements are dropped.
  if (s.startsWith('[') && s.endsWith(']')) {
    return s
      .slice(1, -1)
      .split(',')
      .map((item) => item.trim())
      .filter((item) => item.length > 0)
      .map((item) => parseScalar(item));
  }
  if (
    (s.startsWith('"') && s.endsWith('"')) ||
    (s.startsWith("'") && s.endsWith("'"))
  ) {
    return s.slice(1, -1);
  }
  if (s === 'true') return true;
  if (s === 'false') return false;
  if (s === '' || s === '~' || s === 'null') return null;
  if (/^-?\d+$/.test(s)) return parseInt(s, 10);
  if (/^-?\d+\.\d+$/.test(s)) return parseFloat(s);
  return s;
}

function parseYaml(text) {
  const root = {};
  // Each frame tracks the map it opened plus a back-reference to its parent so
  // an indented `- item` block can convert the key's value into an array.
  const stack = [{ indent: -1, node: root, parent: null, key: null }];
  for (const raw of text.split(/\r?\n/)) {
    const trimmed = raw.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const stripped = raw.replace(/^\s+/, '');
    const indent = raw.length - stripped.length;

    // A `- item` at the same indent as the key that owns it is valid YAML and
    // is what Ruby's YAML.dump emits, so a list line only closes frames that
    // are strictly deeper. Popping on `<=` here would reattach the item to the
    // grandparent and turn the owning map into an array — silently emptying
    // `trace`/`e2e` after `upgrade-config.rb --apply` rewrites a config.
    const isListItem = stripped.startsWith('- ');
    while (
      stack.length > 1 &&
      (isListItem ? indent < stack[stack.length - 1].indent : indent <= stack[stack.length - 1].indent)
    ) {
      stack.pop();
    }
    const frame = stack[stack.length - 1];

    if (isListItem) {
      if (!frame.parent) continue; // list at document root: unsupported, ignore
      if (!Array.isArray(frame.parent[frame.key])) frame.parent[frame.key] = [];
      frame.parent[frame.key].push(parseScalar(stripped.slice(2)));
      continue;
    }

    const m = stripped.match(/^([^:]+):\s*(.*)$/);
    if (!m) continue;
    const key = m[1].trim();
    const rest = m[2];
    if (rest === '') {
      const child = {};
      frame.node[key] = child;
      stack.push({ indent, node: child, parent: frame.node, key });
    } else {
      frame.node[key] = parseScalar(rest);
    }
  }
  return root;
}

function loadConfig() {
  try {
    return parseYaml(fs.readFileSync(CONFIG_PATH, 'utf8'));
  } catch (_) {
    return {};
  }
}

// --- git helpers ---------------------------------------------------------
function gitAt(cwd, args, options) {
  return spawnSync('git', ['-C', cwd, ...args], { encoding: 'utf8', ...(options || {}) });
}

function git(args) {
  return gitAt(repoRoot, args);
}

function currentCommit() {
  const r = git(['rev-parse', 'HEAD']);
  return r.status === 0 ? r.stdout.trim() : null;
}

function revParse(ref) {
  const r = git(['rev-parse', '--verify', `${ref}^{commit}`]);
  return r.status === 0 ? r.stdout.trim() : null;
}

function commitReachable(sha) {
  return revParse(sha) !== null;
}

// Returns { changed: bool } or { error: string }. `to` null compares against the
// working tree; otherwise against that ref. `paths` is an optional pathspec list.
function diffHasChanges(from, to, paths) {
  const args = ['diff', '--quiet', from];
  if (to) args.push(to);
  if (Array.isArray(paths) && paths.length) {
    args.push('--', ...paths);
  }
  const r = git(args);
  if (r.status === 0) return { changed: false };
  if (r.status === 1) return { changed: true };
  return { error: (r.stderr || '').trim() || 'git diff failed' };
}

function short(sha) {
  return typeof sha === 'string' ? sha.slice(0, 7) : String(sha);
}

function listFiles(paths) {
  const args = ['ls-files', '-z'];
  if (Array.isArray(paths) && paths.length) args.push('--', ...paths);
  const r = git(args);
  if (r.status !== 0) {
    return { error: (r.stderr || '').trim() || 'git ls-files failed', files: [] };
  }
  return { files: r.stdout.split('\0').filter(Boolean) };
}

function listCurrentFiles(paths) {
  const tracked = listFiles(paths);
  if (tracked.error) return tracked;
  const args = ['ls-files', '-z', '--others', '--exclude-standard'];
  if (Array.isArray(paths) && paths.length) args.push('--', ...paths);
  const untracked = git(args);
  if (untracked.status !== 0) {
    return { error: (untracked.stderr || '').trim() || 'git ls-files --others failed', files: [] };
  }
  return {
    files: Array.from(new Set([
      ...tracked.files,
      ...untracked.stdout.split('\0').filter(Boolean),
    ])).sort(),
  };
}

function resolveRepoPath(rel) {
  if (typeof rel !== 'string' || rel.trim() === '') return null;
  if (path.isAbsolute(rel)) return null;
  const abs = path.resolve(repoRoot, rel);
  const rootWithSep = repoRoot.endsWith(path.sep) ? repoRoot : `${repoRoot}${path.sep}`;
  return abs === repoRoot || abs.startsWith(rootWithSep) ? abs : null;
}

// --- State (git-ignored freshness markers) -------------------------------
function stateFilePath(config) {
  const gates = config.gates || {};
  const rel = typeof gates.state_file === 'string' && gates.state_file.trim() !== ''
    ? gates.state_file
    : '.aw-gate-state.json';
  const abs = resolveRepoPath(rel);
  if (!abs) fail(`gates.state_file must be repo-relative: ${rel}`);
  return abs;
}

function loadState(config) {
  try {
    return JSON.parse(fs.readFileSync(stateFilePath(config), 'utf8'));
  } catch (_) {
    return {};
  }
}

function writeState(config, state) {
  fs.writeFileSync(stateFilePath(config), JSON.stringify(state, null, 2) + '\n');
}

// --- Receipts (git-ignored proof-of-work the recording skill writes) ------
// A gate stamp only asserts "this step ran"; a receipt is the byproduct that
// makes that assertion checkable at record time. When a gate is receipt-required,
// `record <gate>` refuses to stamp unless the matching skill has just written a
// fresh, gate-named receipt summarizing what it did. This does NOT prove the work
// was good (see docs/workflow/gates.md) — it turns "one convenient command clears
// the gate" into "produce substantive, recent, single-use evidence", and leaves
// an auditable trail. Receipts are per-checkout and git-ignored, like gate state.
function receiptPolicy(config, gate) {
  const gates = config.gates || {};
  const globalRequire = gates.require_receipt === true;
  const check = (gates.checks || {})[gate] || {};
  const required = typeof check.require_receipt === 'boolean'
    ? check.require_receipt
    : globalRequire;
  const dir = typeof gates.receipt_dir === 'string' && gates.receipt_dir.trim() !== ''
    ? gates.receipt_dir
    : '.aw/receipts';
  const maxAgeMinutes = Number.isFinite(Number(gates.receipt_max_age_minutes)) && Number(gates.receipt_max_age_minutes) > 0
    ? Number(gates.receipt_max_age_minutes)
    : 180;
  return { required, dir, maxAgeMinutes };
}

function receiptFilePath(policy, gate) {
  const rel = path.join(policy.dir, `${gate}.json`);
  const abs = resolveRepoPath(rel);
  if (!abs) fail(`gates.receipt_dir must be repo-relative: ${policy.dir}`);
  return { rel, abs };
}

// Returns { receipt, rel, abs } on success or { error } describing why the
// receipt does not stand in for a real skill run.
function verifyReceipt(policy, gate) {
  const { rel, abs } = receiptFilePath(policy, gate);
  let text;
  try {
    text = fs.readFileSync(abs, 'utf8');
  } catch (_) {
    return { error: `no receipt at ${rel} — run the skill (it writes the receipt), then record` };
  }
  let receipt;
  try {
    receipt = JSON.parse(text);
  } catch (e) {
    return { error: `receipt ${rel} is not valid JSON: ${e.message}` };
  }
  if (!receipt || typeof receipt !== 'object' || Array.isArray(receipt)) {
    return { error: `receipt ${rel} must be a JSON object` };
  }
  if (receipt.gate !== gate) {
    return { error: `receipt ${rel} is for gate "${receipt.gate}", not "${gate}"` };
  }
  if (typeof receipt.summary !== 'string' || receipt.summary.trim() === '') {
    return { error: `receipt ${rel} has no non-empty summary of what the skill did` };
  }
  const ageMs = Date.now() - Date.parse(receipt.ts);
  if (!Number.isFinite(ageMs)) {
    return { error: `receipt ${rel} has an unreadable ts "${receipt.ts}"` };
  }
  if (ageMs < -5 * 60 * 1000) {
    return { error: `receipt ${rel} ts "${receipt.ts}" is in the future` };
  }
  if (ageMs > policy.maxAgeMinutes * 60 * 1000) {
    const ageMin = (ageMs / 60000).toFixed(0);
    return { error: `receipt ${rel} is stale (${ageMin}m old, limit ${policy.maxAgeMinutes}m) — re-run the skill` };
  }
  return { receipt, rel, abs };
}

function cmdReceipt(args) {
  const { positional, flags } = parseFlags(args);
  const gate = positional[0];
  if (!gate || !/^[a-z][a-z0-9_-]*$/.test(gate)) {
    fail('receipt requires a gate name like `review`, `capture`, `check_workflow_compliance`, or `synthesize`');
  }
  const summary = typeof flags.summary === 'string' ? flags.summary.trim() : '';
  if (summary === '') {
    fail('receipt requires --summary "<what the skill actually did>" — the proof-of-work the gate verifies');
  }
  const config = loadConfig();
  const policy = receiptPolicy(config, gate);
  const { rel, abs } = receiptFilePath(policy, gate);
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  const receipt = {
    gate,
    ts: new Date().toISOString(),
    commit: currentCommit(),
    summary,
    detail: typeof flags.detail === 'string' ? flags.detail : null,
  };
  fs.writeFileSync(abs, JSON.stringify(receipt, null, 2) + '\n');
  process.stdout.write(`aw-gate: receipt written for ${gate} (${rel})\n`);
  process.exit(0);
}

// --- Commands ------------------------------------------------------------
function parseFlags(args) {
  const positional = [];
  const flags = {};
  for (let i = 0; i < args.length; i += 1) {
    if (args[i].startsWith('--')) {
      const key = args[i].slice(2);
      const val = args[i + 1] && !args[i + 1].startsWith('--') ? args[(i += 1)] : true;
      flags[key] = val;
    } else {
      positional.push(args[i]);
    }
  }
  return { positional, flags };
}

// --- Workflow execution trace -------------------------------------------
function workflowTraceConfig(config) {
  const workflowTrace = config.workflow_trace || {};
  return {
    enabled: workflowTrace.enabled === true,
    path: typeof workflowTrace.path === 'string' && workflowTrace.path.trim() !== ''
      ? workflowTrace.path
      : '.aw/workflow-trace.jsonl',
    require_tier: workflowTrace.require_tier === true,
    required_gates: Array.isArray(workflowTrace.required_gates) ? workflowTrace.required_gates : [],
    max_events: Number.isFinite(Number(workflowTrace.max_events)) && Number(workflowTrace.max_events) > 0
      ? Number(workflowTrace.max_events)
      : 10000,
    max_bytes: Number.isFinite(Number(workflowTrace.max_bytes)) && Number(workflowTrace.max_bytes) > 0
      ? Number(workflowTrace.max_bytes)
      : 5 * 1024 * 1024,
  };
}

function compactWorkflowTrace(abs, workflowTrace) {
  let text = '';
  try {
    text = fs.readFileSync(abs, 'utf8');
  } catch (_) {
    return;
  }
  let lines = text.split(/\r?\n/).filter((line) => line.trim() !== '');
  if (lines.length > workflowTrace.max_events) {
    lines = lines.slice(-workflowTrace.max_events);
  }
  let next = lines.length ? `${lines.join('\n')}\n` : '';
  while (lines.length > 0 && Buffer.byteLength(next, 'utf8') > workflowTrace.max_bytes) {
    lines.shift();
    next = lines.length ? `${lines.join('\n')}\n` : '';
  }
  if (next !== text) fs.writeFileSync(abs, next);
}

function appendWorkflowEvent(config, event) {
  const workflowTrace = workflowTraceConfig(config);
  if (!workflowTrace.enabled) return false;
  const abs = resolveRepoPath(workflowTrace.path);
  if (!abs) fail(`workflow_trace.path must be repo-relative: ${workflowTrace.path}`);
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  const clean = {};
  for (const [key, value] of Object.entries(event)) {
    if (value !== null && value !== undefined && value !== '') clean[key] = value;
  }
  fs.appendFileSync(abs, JSON.stringify({
    ts: new Date().toISOString(),
    commit: currentCommit(),
    source: 'aw-gate',
    ...clean,
  }) + '\n');
  compactWorkflowTrace(abs, workflowTrace);
  return workflowTrace.path;
}

function readWorkflowEvents(workflowTrace) {
  const abs = resolveRepoPath(workflowTrace.path);
  if (!abs) return { events: [], findings: [{ level: 'error', type: 'invalid-path', message: `workflow_trace.path must be repo-relative: ${workflowTrace.path}` }] };
  let text = '';
  try {
    text = fs.readFileSync(abs, 'utf8');
  } catch (_) {
    return { events: [], findings: [] };
  }
  const events = [];
  const findings = [];
  text.split(/\r?\n/).forEach((line, index) => {
    if (!line.trim()) return;
    try {
      const parsed = JSON.parse(line);
      if (parsed && typeof parsed === 'object') events.push(parsed);
      else findings.push({ level: 'error', type: 'invalid-event', message: `${workflowTrace.path}:${index + 1} is not an object` });
    } catch (e) {
      findings.push({ level: 'error', type: 'invalid-json', message: `${workflowTrace.path}:${index + 1}: ${e.message}` });
    }
  });
  return { events, findings };
}

function cmdWorkflowRecord(args) {
  const { positional, flags } = parseFlags(args);
  const event = positional[0];
  if (!event || !/^[a-z][a-z0-9_-]*$/.test(event)) {
    fail('workflow-record requires an event name like `tier`, `step`, `gate`, or `skip`');
  }
  const config = loadConfig();
  const workflowTrace = workflowTraceConfig(config);
  if (!workflowTrace.enabled) {
    process.stdout.write('aw-gate: workflow trace disabled (workflow_trace.enabled is not true) — skipping\n');
    process.exit(0);
  }
  const rel = appendWorkflowEvent(config, {
    event,
    tier: flags.tier,
    step: flags.step,
    gate: flags.gate,
    artifact: flags.artifact,
    status: flags.status || 'recorded',
    reason: flags.reason,
    detail: flags.detail,
  });
  process.stdout.write(`aw-gate: workflow event recorded (${event} -> ${rel})\n`);
  process.exit(0);
}

function workflowSummary(events, findings, workflowTrace) {
  return {
    events: events.length,
    tier: (events.find((event) => event.event === 'tier' && event.tier) || {}).tier || null,
    gates: Array.from(new Set(events
      .filter((event) => event.event === 'gate' && event.gate)
      .map((event) => event.gate))).sort(),
    required_gates: workflowTrace.required_gates,
    errors: findings.filter((f) => f.level === 'error').length,
  };
}

function sortFindings(findings) {
  return findings.sort((a, b) => {
    if (a.level !== b.level) return a.level === 'error' ? -1 : 1;
    if (a.type !== b.type) return a.type < b.type ? -1 : 1;
    return (a.message || '').localeCompare(b.message || '');
  });
}

function filterWorkflowEventsByBase(events, base, findings) {
  if (typeof base !== 'string') return events;
  if (git(['rev-parse', '--verify', base]).status !== 0) {
    findings.push({
      level: 'error',
      type: 'base-ref-not-found',
      message: `workflow-check: base ref ${base} not found — fetch history (CI: fetch-depth: 0)`,
    });
    return [];
  }
  const commits = commitList(base);
  if (commits.error) {
    findings.push({ level: 'error', type: 'workflow-log-error', message: commits.error });
    return [];
  }
  const commitSet = new Set(commits.commits);
  return events.filter((event) => event.commit && commitSet.has(event.commit));
}

function cmdWorkflowCheck(args) {
  const { flags } = parseFlags(args);
  const jsonMode = flags.json === true;
  const config = loadConfig();
  const workflowTrace = workflowTraceConfig(config);
  if (!workflowTrace.enabled) {
    const output = {
      summary: { disabled: true, ...workflowSummary([], [], workflowTrace) },
      findings: [],
    };
    if (jsonMode) process.stdout.write(JSON.stringify(output, null, 2) + '\n');
    else process.stdout.write('aw-gate: workflow trace disabled (workflow_trace.enabled is not true) — skipping\n');
    process.exit(0);
  }

  const loaded = readWorkflowEvents(workflowTrace);
  const findings = loaded.findings;
  const base = typeof flags.base === 'string'
    ? flags.base
    : typeof flags['since-commit'] === 'string'
      ? flags['since-commit']
      : null;
  const events = filterWorkflowEventsByBase(loaded.events, base, findings);
  if (workflowTrace.require_tier && !events.some((event) => event.event === 'tier' && event.tier)) {
    findings.push({ level: 'error', type: 'missing-tier', message: 'workflow trace has no tier event' });
  }
  for (const gate of workflowTrace.required_gates) {
    if (!events.some((event) => event.event === 'gate' && event.gate === gate)) {
      findings.push({ level: 'error', type: 'missing-gate', message: `workflow trace has no ${gate} gate event` });
    }
  }

  sortFindings(findings);

  const output = { summary: workflowSummary(events, findings, workflowTrace), findings };
  if (jsonMode) process.stdout.write(JSON.stringify(output, null, 2) + '\n');
  if (output.summary.errors > 0) {
    process.stderr.write('aw-gate: workflow trace FAILED\n');
    for (const f of findings.filter((item) => item.level === 'error')) {
      process.stderr.write(`  - ${f.type}: ${f.message}\n`);
    }
    process.exit(1);
  }
  if (!jsonMode) {
    process.stdout.write(`aw-gate: workflow trace clean (${output.summary.events} event(s))\n`);
  }
  process.exit(0);
}

// --- Telemetry (git-tracked event log, optionally month-sharded) ---------
function monthStamp(date) {
  const y = date.getUTCFullYear();
  const m = String(date.getUTCMonth() + 1).padStart(2, '0');
  return `${y}-${m}`;
}

// Resolve the log file to append to. With rotation `monthly` (the default), the
// current month is inserted before the extension so each file stays bounded and
// concurrent branches usually touch different files, e.g.
// docs/metrics/events.jsonl -> docs/metrics/events-2026-07.jsonl.
function shardPath(section, defaultBase, date) {
  const base = section.path || defaultBase;
  const rotation = section.rotation || 'monthly';
  if (rotation !== 'monthly') return base;
  const ext = path.extname(base);
  const stem = base.slice(0, base.length - ext.length);
  return `${stem}-${monthStamp(date)}${ext}`;
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Delete month shards older than <config>.retention_months. Git history is the
// archive. No-op unless rotation is monthly and retention_months is a positive
// number. Returns `{ skipped: <reason> }` when nothing was inspected, or
// `{ retention, removed[] }` when a pass ran. The caller renders both shapes.
function pruneShardFamily(section, defaultBase) {
  const base = section.path || defaultBase;
  const rotation = section.rotation || 'monthly';
  const retention = Number(section.retention_months);
  if (rotation !== 'monthly' || !Number.isFinite(retention) || retention <= 0) {
    return { skipped: 'retention not configured' };
  }
  const ext = path.extname(base);
  const stem = path.basename(base, ext);
  const baseAbs = resolveRepoPath(base);
  if (!baseAbs) fail(`shard path must be repo-relative: ${base}`);
  const dir = path.dirname(baseAbs);
  const now = new Date();
  // Keep the current month plus (retention - 1) prior months; drop anything older.
  const cutoff = Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - (retention - 1), 1);
  const re = new RegExp(`^${escapeRegExp(stem)}-(\\d{4})-(\\d{2})${escapeRegExp(ext)}$`);
  const removed = [];
  let entries = [];
  try {
    entries = fs.readdirSync(dir);
  } catch (_) {
    return { skipped: 'directory does not exist' };
  }
  for (const f of entries) {
    const m = f.match(re);
    if (!m) continue;
    const shardMs = Date.UTC(Number(m[1]), Number(m[2]) - 1, 1);
    if (shardMs < cutoff) {
      fs.unlinkSync(path.join(dir, f));
      removed.push(f);
    }
  }
  return { retention, removed };
}

// Prune both the telemetry log (events*.jsonl) and the skill tracking log
// (skills*.jsonl). Both use the same shard/retention model. Invoked by
// aw-synthesize-memory, not on the hot write path.
function cmdPruneTelemetry() {
  const config = loadConfig();
  const families = [
    { label: 'telemetry', section: config.telemetry || {}, defaultBase: 'docs/metrics/events.jsonl' },
    { label: 'tracking', section: config.tracking || {}, defaultBase: 'docs/metrics/skills.jsonl' },
  ];
  for (const { label, section, defaultBase } of families) {
    const result = pruneShardFamily(section, defaultBase);
    if (result.skipped) {
      process.stdout.write(`aw-gate: ${label} ${result.skipped} — keeping all shards\n`);
      continue;
    }
    if (result.removed.length === 0) {
      process.stdout.write(`aw-gate: no ${label} shards older than ${result.retention} month(s)\n`);
    } else {
      process.stdout.write(`aw-gate: pruned ${result.removed.length} ${label} shard(s) older than ${result.retention} month(s):\n`);
      for (const f of result.removed) process.stdout.write(`  - ${f}\n`);
      process.stdout.write('  (git history retains the removed data)\n');
    }
  }
}

// --- Skill tracking (git-tracked skill-invocation log) -------------------
// Silent fire-and-forget writer skills invoke at start. Records one JSONL line
// per invocation to docs/metrics/skills-YYYY-MM.jsonl so cross-repo analysis
// can answer workflow-drop-off, entry-point, and adoption questions. Design
// notes: docs/workflow/tracking.md.
function readOrMintSession(tracking) {
  const rel = tracking.session_file || '.aw/session';
  const ttlHours = Number(tracking.session_ttl_hours);
  const ttlMs = Number.isFinite(ttlHours) && ttlHours > 0 ? ttlHours * 3600 * 1000 : 8 * 3600 * 1000;
  const abs = path.resolve(repoRoot, rel);
  try {
    const stat = fs.statSync(abs);
    if (Date.now() - stat.mtimeMs < ttlMs) {
      const id = fs.readFileSync(abs, 'utf8').trim();
      if (id) return id;
    }
  } catch (_) { /* missing or unreadable — mint below */ }
  const id = crypto.randomUUID();
  try {
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, id + '\n');
  } catch (_) { /* best-effort; if we can't persist, we still return an id */ }
  return id;
}

// Canonical mapping from bundled skill name to workflow step key. Same
// convention as this file's other bundled defaults (`.aw-gate-state.json`,
// `docs/metrics/events.jsonl`) — aw-gate.js owns AW's built-in identifiers.
// A per-repo `workflow.steps.<step>.skill` override wins when present.
const DEFAULT_SKILL_TO_STEP = {
  'aw-prd': 'prd',
  'aw-brainstorm': 'brainstorm',
  'aw-create-spec': 'create_spec',
  'aw-request-human-review': 'request_human_review',
  'aw-plan': 'plan',
  'aw-review': 'review',
  'aw-create-tickets': 'create_tickets',
  'aw-work': 'work',
  'aw-check-workflow-compliance': 'check_workflow_compliance',
  'aw-commit': 'commit',
  'aw-commit-push-pr': 'commit_push_pr',
};

function workflowStepForSkill(config, skill) {
  const steps = (config.workflow && config.workflow.steps) || {};
  for (const key of Object.keys(steps)) {
    const entry = steps[key];
    if (entry && entry.skill && entry.skill === skill) return key;
  }
  return DEFAULT_SKILL_TO_STEP[skill] || null;
}

function cmdTrack(args) {
  // Never fail the caller. Wrap the whole thing and swallow everything.
  try {
    const { positional } = parseFlags(args);
    const skill = positional[0];
    if (!skill) return; // no skill name — nothing to record, silent exit
    const config = loadConfig();
    const tracking = config.tracking || {};
    if (tracking.enabled !== true) return; // per-repo kill switch
    const rel = shardPath(tracking, 'docs/metrics/skills.jsonl', new Date());
    const abs = resolveRepoPath(rel);
    if (!abs) return; // misconfigured path; stay silent
    const sessionId = readOrMintSession(tracking);
    const workflowStep = workflowStepForSkill(config, skill);
    const record = {
      ts: new Date().toISOString(),
      session_id: sessionId,
      skill,
      source: 'skill',
    };
    if (workflowStep) record.workflow_step = workflowStep;
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.appendFileSync(abs, JSON.stringify(record) + '\n');
  } catch (_) { /* fire-and-forget */ }
}

function cmdRecord(args) {
  const { positional, flags } = parseFlags(args);
  const event = positional[0];
  if (!event) fail('record requires an event name, e.g. `record review`');
  const detail = typeof flags.detail === 'string' ? flags.detail : null;
  const config = loadConfig();
  const now = new Date().toISOString();
  const commit = currentCommit();

  // Proof-of-work gate: a receipt-required gate cannot be stamped without a
  // fresh, gate-matching receipt written by the skill. The bypass exists only
  // for bootstrap (the commit that enables this, fresh clones, hand use) and
  // announces itself loudly so a human can spot it in logs.
  const policy = receiptPolicy(config, event);
  let receiptDigest = null;
  if (policy.required && flags['no-receipt'] === true) {
    process.stderr.write(`aw-gate: WARNING recording ${event} with --no-receipt (no proof-of-work verified)\n`);
    receiptDigest = { bypassed: true };
  } else if (policy.required) {
    const verified = verifyReceipt(policy, event);
    if (verified.error) {
      fail(`${verified.error}\n  (bootstrap only: bypass once with --no-receipt; never to skip running the skill)`);
    }
    receiptDigest = {
      summary: verified.receipt.summary,
      ts: verified.receipt.ts,
      commit: verified.receipt.commit || null,
    };
    // Single-use: consume the receipt so it cannot re-stamp a later commit.
    try { fs.unlinkSync(verified.abs); } catch (_) { /* best effort */ }
  }

  const state = loadState(config);
  state[event] = { lastRun: now, commit, detail, receipt: receiptDigest };
  appendWorkflowEvent(config, { event: 'gate', gate: event, status: 'ran', detail });
  writeState(config, state);

  const telemetry = config.telemetry || {};
  if (telemetry.enabled === true) {
    const rel = shardPath(telemetry, 'docs/metrics/events.jsonl', new Date());
    const abs = resolveRepoPath(rel);
    if (!abs) fail(`telemetry.path must be repo-relative: ${telemetry.path || 'docs/metrics/events.jsonl'}`);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    const line = JSON.stringify({ ts: now, event, detail, source: 'aw-gate' });
    fs.appendFileSync(abs, line + '\n');
    process.stdout.write(`aw-gate: recorded ${event} (freshness + telemetry ${rel})\n`);
  } else {
    process.stdout.write(`aw-gate: recorded ${event} (freshness)\n`);
  }
}

// Returns an array of failure strings for one gate (empty means it passed).
function evaluateGate(name, spec, entry, against) {
  const mode = spec.mode || 'age';
  if (!['age', 'commit', 'commit-and-age'].includes(mode)) {
    return [`${name}: unknown mode "${mode}" (expected age, commit, or commit-and-age)`];
  }
  if (!entry) {
    return [`${name}: never recorded (run the skill, then \`aw-gate record ${name}\`)`];
  }
  const failures = [];

  if (mode === 'age' || mode === 'commit-and-age') {
    const maxAgeHours = Number(spec.max_age_hours);
    if (!Number.isFinite(maxAgeHours) || maxAgeHours <= 0) {
      failures.push(`${name}: invalid or missing max_age_hours for ${mode} mode`);
    } else if (!entry.lastRun) {
      failures.push(`${name}: no timestamp recorded`);
    } else {
      const ageMs = Date.now() - Date.parse(entry.lastRun);
      if (!Number.isFinite(ageMs)) {
        failures.push(`${name}: unreadable timestamp "${entry.lastRun}"`);
      } else if (ageMs > maxAgeHours * 3600 * 1000) {
        const ageHours = (ageMs / 3600 / 1000).toFixed(1);
        failures.push(`${name}: stale (last run ${ageHours}h ago, limit ${maxAgeHours}h)`);
      }
    }
  }

  if (mode === 'commit' || mode === 'commit-and-age') {
    const recorded = entry.commit;
    if (!recorded) {
      failures.push(`${name}: no commit recorded — re-run the gate so it stamps the current commit`);
    } else if (!commitReachable(recorded)) {
      failures.push(`${name}: recorded commit ${short(recorded)} not found (rebased or shallow clone) — re-run`);
    } else {
      const to = against === 'worktree' ? null : 'HEAD';
      const res = diffHasChanges(recorded, to, spec.paths);
      if (res.error) {
        failures.push(`${name}: ${res.error}`);
      } else if (res.changed) {
        const scope = Array.isArray(spec.paths) && spec.paths.length
          ? ` in ${spec.paths.join(', ')}`
          : '';
        const target = against === 'worktree' ? 'the working tree' : 'HEAD';
        failures.push(`${name}: code changed${scope} between ${short(recorded)} and ${target} since it last ran`);
      }
    }
  }

  return failures;
}

function cmdCheck(args) {
  const { flags } = parseFlags(args);
  const against = flags.against === 'worktree' ? 'worktree' : 'head';
  const config = loadConfig();
  const gates = config.gates || {};
  if (gates.enabled !== true) {
    process.stdout.write('aw-gate: gates disabled (gates.enabled is not true) — skipping\n');
    process.exit(0);
  }
  const checks = gates.checks || {};
  const names = Object.keys(checks);
  if (names.length === 0) {
    process.stdout.write('aw-gate: no gates configured under gates.checks — nothing to enforce\n');
    process.exit(0);
  }
  const state = loadState(config);
  const failures = [];
  for (const name of names) {
    for (const f of evaluateGate(name, checks[name] || {}, state[name], against)) {
      failures.push(f);
    }
  }
  if (failures.length > 0) {
    process.stderr.write('aw-gate: gate check FAILED\n');
    for (const f of failures) process.stderr.write(`  - ${f}\n`);
    process.exit(1);
  }
  process.stdout.write(`aw-gate: all ${names.length} gate(s) fresh (checked against ${against})\n`);
  process.exit(0);
}

// --- Traceability --------------------------------------------------------
const SPEC_ID_RE = /^[A-Z][A-Z0-9]{1,7}-\d{3,}$/;
const ANCHOR_PATTERN = '@spec:?\\s*([A-Z][A-Z0-9]{1,7}-\\d{3,}(?:\\s*,\\s*[A-Z][A-Z0-9]{1,7}-\\d{3,})*)';

function anchorRe() {
  return new RegExp(ANCHOR_PATTERN, 'g');
}

// A requirement heading opts into end-to-end coverage with an exact `[e2e]`
// suffix on its title: `### PAY-004 — Checkout completes with a saved card [e2e]`.
// The marker must follow the title, never precede the em-dash: the requirement
// heading regex would not match and the requirement would vanish from trace
// silently.
const E2E_MARKER = /\[e2e\]$/;
// Variants that were probably meant as the marker but are not: wrong case,
// round or fullwidth brackets, markdown emphasis or code ticks around it, and
// trailing punctuation. Reported as warnings so a typo fails loudly instead of
// silently uncovering. Backticks matter most — the standard renders the marker
// as `[e2e]` in prose, so copying that phrasing into a heading is a near miss.
const E2E_MARKER_NEAR_MISS = /[*_`]*[[(［]\s*e2e\s*[\])］][*_`]*[\s.,;:!#]*$/i;

function isE2eMarked(title) {
  return E2E_MARKER.test(String(title || '').trim());
}

function isE2eNearMiss(title) {
  const t = String(title || '').trim();
  return !E2E_MARKER.test(t) && E2E_MARKER_NEAR_MISS.test(t);
}

function e2eConfig(config) {
  const e2e = config.e2e || {};
  return {
    enabled: e2e.enabled === true,
    test_paths: Array.isArray(e2e.test_paths) ? e2e.test_paths : [],
  };
}

// A list of nothing but `:(exclude)` pathspecs makes `git ls-files` return the
// whole repository, which would satisfy every `[e2e]` marker from any test
// anywhere — the check would pass while enforcing nothing. Exclusions only
// carve holes inside a positive pattern, so this is always a config error.
function isExcludeOnly(paths) {
  return paths.length > 0 && paths.every((p) => /^\s*(:\(exclude\)|:!)/.test(String(p)));
}

function traceConfig(config) {
  const trace = config.trace || {};
  return {
    enabled: trace.enabled === true,
    spec_paths: Array.isArray(trace.spec_paths) ? trace.spec_paths : ['docs/features/*/spec.md'],
    test_paths: Array.isArray(trace.test_paths) ? trace.test_paths : ['*.feature', '*.test.ts', '*.test.tsx', '*.spec.ts'],
    code_paths: Array.isArray(trace.code_paths) ? trace.code_paths : ['src'],
    require_code_anchor: trace.require_code_anchor === true,
  };
}

// Shared by the enforcing and advisory trace modes: same --out contract, same
// --json payload, same error listing. Only `enforce` differs — the advisory
// mode reports errors it will not act on.
function emitTraceReport(output, flags, jsonMode, label, enforce) {
  if (typeof flags.out === 'string') {
    const out = resolveRepoPath(flags.out);
    if (!out) fail(`trace --out must be a repo-relative path: ${flags.out}`);
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, JSON.stringify(output, null, 2) + '\n');
  }
  if (jsonMode) process.stdout.write(JSON.stringify(output, null, 2) + '\n');

  const errors = output.findings.filter((item) => item.level === 'error');
  if (errors.length) {
    process.stderr.write(`${label}\n`);
    for (const f of errors) process.stderr.write(`  - ${f.type}: ${f.message}\n`);
    if (enforce) process.exit(1);
  }
}

function sortedLocations(list) {
  return list.slice().sort((a, b) => {
    if (a.file !== b.file) return a.file < b.file ? -1 : 1;
    return a.line - b.line;
  });
}

// Merge two independent anchor scans into one, dropping anchors both scans
// found (a file matched by trace.test_paths and e2e.test_paths is scanned twice).
function mergeAnchorScans(a, b) {
  const seen = new Set();
  const anchors = [];
  for (const anchor of [...a.anchors, ...b.anchors]) {
    const key = `${anchor.id}::${anchor.file}::${anchor.line}`;
    if (seen.has(key)) continue;
    seen.add(key);
    anchors.push(anchor);
  }
  return { anchors: sortedLocations(anchors), findings: [...a.findings, ...b.findings] };
}

function splitIds(raw) {
  if (Array.isArray(raw)) return raw.flatMap((id) => splitIds(id));
  if (typeof raw !== 'string') return [];
  return raw.split(',').map((id) => id.trim()).filter(Boolean);
}

function scanSpecs(trace) {
  const result = listFiles(trace.spec_paths);
  const findings = [];
  const specs = new Map();
  if (result.error) {
    findings.push({ level: 'error', type: 'spec-path-error', message: result.error });
    return { specs, findings };
  }
  for (const file of result.files.filter((f) => f.endsWith('/spec.md'))) {
    const abs = resolveRepoPath(file);
    if (!abs) continue;
    let lines;
    try {
      lines = fs.readFileSync(abs, 'utf8').split(/\r?\n/);
    } catch (_) {
      continue;
    }
    for (let i = 0; i < lines.length; i += 1) {
      const m = lines[i].match(/^#{1,6}\s+([A-Z][A-Z0-9]{1,7}-\d{3,})\s*(?:[—-]\s*(.*))?$/);
      if (!m) continue;
      const id = m[1];
      const entry = { file, line: i + 1, title: m[2] || '' };
      if (specs.has(id)) {
        const first = specs.get(id);
        findings.push({
          level: 'error',
          type: 'duplicate-id',
          id,
          message: `${id} appears in ${first.file}:${first.line} and ${file}:${i + 1}`,
        });
      } else {
        specs.set(id, entry);
      }
    }
  }
  return { specs, findings };
}

function scanAnchors(paths, type) {
  const result = listFiles(paths);
  const findings = [];
  const anchors = [];
  if (result.error) {
    findings.push({ level: 'error', type: `${type}-path-error`, message: result.error });
    return { anchors, findings, files: [], error: result.error };
  }
  for (const file of result.files) {
    const abs = resolveRepoPath(file);
    if (!abs) continue;
    let lines;
    try {
      lines = fs.readFileSync(abs, 'utf8').split(/\r?\n/);
    } catch (_) {
      continue;
    }
    for (let i = 0; i < lines.length; i += 1) {
      const re = anchorRe();
      let m;
      while ((m = re.exec(lines[i])) !== null) {
        for (const id of splitIds(m[1])) {
          // `source` records which pathspec list found the anchor. Only
          // trace.test_paths anchors are subject to commit coupling; see the
          // uncoupled-test-change loop in cmdTrace.
          anchors.push({ id, file, line: i + 1, source: type });
        }
      }
    }
  }
  return { anchors: sortedLocations(anchors), findings, files: result.files };
}

function buildMatrix(specs, testAnchors, codeAnchors) {
  const matrix = {};
  for (const id of Array.from(specs.keys()).sort()) {
    const spec = specs.get(id);
    matrix[id] = {
      spec,
      tests: sortedLocations(testAnchors.filter((a) => a.id === id).map((a) => ({ file: a.file, line: a.line }))),
      code: sortedLocations(codeAnchors.filter((a) => a.id === id).map((a) => ({ file: a.file, line: a.line }))),
    };
  }
  return matrix;
}

function traceSummary(specs, testAnchors, codeAnchors, findings) {
  return {
    requirements: specs.size,
    test_anchors: testAnchors.length,
    code_anchors: codeAnchors.length,
    errors: findings.filter((f) => f.level === 'error').length,
    warnings: findings.filter((f) => f.level === 'warning').length,
  };
}

function changedFiles(base, paths) {
  const args = ['diff', '--name-only', `${base}...HEAD`];
  if (Array.isArray(paths) && paths.length) args.push('--', ...paths);
  const r = git(args);
  if (r.status !== 0) return { error: (r.stderr || '').trim() || 'git diff failed', files: [] };
  return { files: r.stdout.split(/\r?\n/).filter(Boolean) };
}

function commitSpecOverrideIds(commit) {
  const r = git(['log', '-1', '--format=%(trailers:key=Spec-Override,valueonly)', commit]);
  if (r.status !== 0) return new Set();
  const ids = new Set();
  for (const line of r.stdout.split(/\r?\n/)) {
    const m = line.trim().match(/^([A-Z][A-Z0-9]{1,7}-\d{3,})/);
    if (m) ids.add(m[1]);
  }
  return ids;
}

// --- E2E marker suggestions (advisory, read-only) ------------------------
// Derives `[e2e]` markers from evidence the repo already carries rather than
// from requirement prose. Two candidate classes:
//
//   covered-unmarked   an unmarked requirement already anchored in a file
//                      matching e2e.test_paths. The decision was made when
//                      somebody wrote that test; the spec just never recorded
//                      it. Marking it cannot turn the gate red.
//   near-miss-marker   a title ending in a marker variant trace does not
//                      honor, so the requirement reads as marked but is not.
//
// Prose is never inspected. docs/standards/e2e-coverage.md puts the marking
// decision with a human at spec time, and a keyword guess dressed up as a
// finding would quietly move that bar into this script.
function specHeadingLine(file, line) {
  const abs = resolveRepoPath(file);
  if (!abs) return null;
  try {
    const raw = fs.readFileSync(abs, 'utf8').split(/\r?\n/)[line - 1];
    return typeof raw === 'string' ? raw.replace(/\s+$/, '') : null;
  } catch (_) {
    return null;
  }
}

// Suffix-only, per the standard: a marker before the em-dash stops the
// requirement heading from matching at all.
function markedHeading(raw) {
  const trimmed = raw.replace(/\s+$/, '');
  return E2E_MARKER_NEAR_MISS.test(trimmed)
    ? trimmed.replace(E2E_MARKER_NEAR_MISS, '[e2e]').replace(/\s+$/, '')
    : `${trimmed} [e2e]`;
}

function cmdTraceSuggestE2e(config, trace, flags) {
  const jsonMode = flags.json === true;
  const e2e = e2eConfig(config);
  const specScan = scanSpecs(trace);
  const specs = specScan.specs;
  const findings = [...specScan.findings];

  // Scanned regardless of e2e.enabled: surveying candidates before switching
  // the gate on is the migration sequence this mode exists to serve.
  const havePaths = e2e.test_paths.length > 0;
  let anchors = [];
  let e2eFileCount = 0;
  if (havePaths) {
    const scan = scanAnchors(e2e.test_paths, 'e2e');
    findings.push(...scan.findings);
    anchors = scan.anchors;
    e2eFileCount = (scan.files || []).length;
    if (isExcludeOnly(e2e.test_paths)) {
      findings.push({
        level: 'warning',
        type: 'e2e-paths-exclude-only',
        message: `e2e.test_paths contains only exclusions (${e2e.test_paths.join(', ')}) — it matches the whole repository; add a positive pathspec before enabling the gate`,
      });
    } else if (!scan.error && e2eFileCount === 0) {
      findings.push({
        level: 'warning',
        type: 'e2e-paths-match-nothing',
        message: `e2e.test_paths (${e2e.test_paths.join(', ')}) matched 0 tracked files — check the pathspec before marking requirements`,
      });
    }
  }

  // What flipping e2e.enabled: true would cost. The survey is the step that is
  // supposed to de-risk that flip, so it has to name the errors waiting on the
  // other side rather than reporting a clean tree.
  const wouldDangle = anchors.filter((a) => !specs.has(a.id));
  for (const anchor of wouldDangle) {
    findings.push({
      level: 'warning',
      type: 'would-become-dangling',
      id: anchor.id,
      message: `${anchor.id} in ${anchor.file}:${anchor.line} has no living spec — it becomes a dangling-test-ref error once e2e.enabled is true`,
    });
  }

  const suggestions = [];
  for (const id of Array.from(specs.keys()).sort()) {
    const spec = specs.get(id);
    if (isE2eMarked(spec.title)) continue;
    const nearMiss = isE2eNearMiss(spec.title);
    const evidence = sortedLocations(
      anchors.filter((a) => a.id === id).map((a) => ({ file: a.file, line: a.line }))
    );
    if (!nearMiss && evidence.length === 0) continue;
    const current = specHeadingLine(spec.file, spec.line);
    suggestions.push({
      id,
      kind: nearMiss ? 'near-miss-marker' : 'covered-unmarked',
      file: spec.file,
      line: spec.line,
      covered: evidence.length > 0,
      // Marking an already-covered requirement satisfies missing-e2e-coverage
      // on the next run; marking an uncovered one starts failing it.
      gate_effect: evidence.length > 0 ? 'none' : 'enforces',
      evidence,
      current,
      proposed: current === null ? null : markedHeading(current),
    });
  }

  const summary = {
    mode: 'suggest-e2e',
    requirements: specs.size,
    suggestions: suggestions.length,
    covered_unmarked: suggestions.filter((s) => s.kind === 'covered-unmarked').length,
    near_miss_markers: suggestions.filter((s) => s.kind === 'near-miss-marker').length,
    e2e_paths_set: havePaths,
    e2e_files: e2eFileCount,
    would_become_dangling: wouldDangle.length,
    errors: findings.filter((f) => f.level === 'error').length,
    warnings: findings.filter((f) => f.level === 'warning').length,
  };

  sortFindings(findings);
  const output = { summary, suggestions, findings };
  // Advisory by contract: pre-existing spec problems (a duplicate id, a bad
  // pathspec) are exactly what a repo adopting the marker retrospectively has,
  // and aborting on them would deny it the survey. Reported, never fatal.
  emitTraceReport(
    output,
    flags,
    jsonMode,
    'aw-gate: trace --suggest-e2e — pre-existing trace errors, reported but not enforced here',
    false
  );

  if (!jsonMode) {
    const lines = ['aw-gate: e2e marker suggestions — advisory, nothing was modified'];
    if (!havePaths) {
      lines.push('  e2e.test_paths is empty — coverage-derived candidates skipped; only marker typos are detectable');
    }
    for (const f of findings.filter((item) => item.level === 'warning' && item.type !== 'would-become-dangling')) {
      lines.push(`  ${f.type}: ${f.message}`);
    }
    if (wouldDangle.length) {
      lines.push('', `  would-become-dangling (${wouldDangle.length}) — no living spec; these fail once e2e.enabled is true`);
      for (const a of wouldDangle) lines.push(`    ${a.id}  ${a.file}:${a.line}`);
    }
    if (!suggestions.length) {
      lines.push(`  no candidates (${summary.requirements} requirement(s) scanned)`);
    }
    for (const kind of ['covered-unmarked', 'near-miss-marker']) {
      const group = suggestions.filter((s) => s.kind === kind);
      if (!group.length) continue;
      const note = kind === 'covered-unmarked'
        ? 'already anchored in e2e.test_paths; marking is gate-neutral'
        : 'reads as marked but trace does not honor it';
      lines.push('', `  ${kind} (${group.length}) — ${note}`);
      for (const s of group) {
        lines.push(`    ${s.id}  ${s.file}:${s.line}`);
        for (const e of s.evidence) lines.push(`      evidence  ${e.file}:${e.line}`);
        if (s.gate_effect === 'enforces') {
          lines.push('      no anchor in e2e.test_paths — marking starts enforcing coverage');
        }
        if (s.current !== null) {
          lines.push(`      - ${s.current}`);
          lines.push(`      + ${s.proposed}`);
        }
      }
    }
    if (suggestions.length) {
      lines.push('', '  Apply by editing the headings above, then re-run trace to confirm.');
    }
    process.stdout.write(lines.join('\n') + '\n');
  }
  process.exit(0);
}

function cmdTrace(args) {
  const { flags } = parseFlags(args);
  const config = loadConfig();
  const trace = traceConfig(config);
  const jsonMode = flags.json === true;
  // Presence, not value: parseFlags swallows a following positional as the
  // flag's value, and `=== true` would silently fall through to the enforcing
  // run — a different command than the one that was asked for.
  const suggestE2e = Object.prototype.hasOwnProperty.call(flags, 'suggest-e2e');
  if (!trace.enabled) {
    // Suggestion mode reads spec headings and @spec anchors, so it needs the
    // same trace config the gate does. Reported separately from the disabled
    // payload below, which is pinned behaviour.
    if (suggestE2e) {
      process.stderr.write('aw-gate: trace --suggest-e2e needs trace.enabled: true in docs/workflow/config.yml\n');
      process.exit(2);
    }
    if (jsonMode) {
      process.stdout.write(JSON.stringify({
        summary: {
          disabled: true,
          requirements: 0,
          test_anchors: 0,
          code_anchors: 0,
          errors: 0,
          warnings: 0,
        },
        matrix: {},
        findings: [],
      }, null, 2) + '\n');
    } else {
      process.stdout.write('aw-gate: trace disabled (trace.enabled is not true) — skipping\n');
    }
    process.exit(0);
  }

  // Advisory report, never the gate: it prints candidates and exits 0 rather
  // than running the enforcement below, so a repo mid-migration can survey
  // markers while trace is still failing for other reasons.
  if (suggestE2e) return cmdTraceSuggestE2e(config, trace, flags);

  const e2e = e2eConfig(config);
  const scanE2ePaths = e2e.enabled && e2e.test_paths.length > 0;

  const specScan = scanSpecs(trace);
  // e2e.test_paths is independent of trace.test_paths: a repo may keep e2e specs
  // somewhere the trace globs do not reach. Scan each list separately and merge
  // the anchors — concatenating the pathspecs instead would let an `:(exclude)`
  // in one list suppress matches the other list legitimately covers.
  const traceTestScan = scanAnchors(trace.test_paths, 'test');
  const e2eTestScan = scanE2ePaths
    ? scanAnchors(e2e.test_paths, 'e2e')
    : { anchors: [], findings: [] };
  // Only merge when an e2e scan actually ran. Merging unconditionally would
  // apply the de-duplication to the trace scan alone, changing test_anchors
  // counts in the --json payload for repos that never configured e2e.
  const testScan = scanE2ePaths ? mergeAnchorScans(traceTestScan, e2eTestScan) : traceTestScan;
  const codeScan = scanAnchors(trace.code_paths, 'code');
  const findings = [...specScan.findings, ...testScan.findings, ...codeScan.findings];
  const specs = specScan.specs;

  for (const anchor of testScan.anchors) {
    if (!specs.has(anchor.id)) {
      findings.push({
        level: 'error',
        type: 'dangling-test-ref',
        id: anchor.id,
        message: `${anchor.id} in ${anchor.file}:${anchor.line} does not exist in a living spec`,
      });
    }
  }
  for (const anchor of codeScan.anchors) {
    if (!specs.has(anchor.id)) {
      findings.push({
        level: 'error',
        type: 'dangling-code-ref',
        id: anchor.id,
        message: `${anchor.id} in ${anchor.file}:${anchor.line} does not exist in a living spec`,
      });
    }
  }
  for (const id of specs.keys()) {
    if (!testScan.anchors.some((a) => a.id === id)) {
      const spec = specs.get(id);
      findings.push({
        level: 'error',
        type: 'untested-requirement',
        id,
        message: `${id} at ${spec.file}:${spec.line} has no test anchor`,
      });
    }
    if (!codeScan.anchors.some((a) => a.id === id)) {
      const spec = specs.get(id);
      findings.push({
        level: trace.require_code_anchor ? 'error' : 'warning',
        type: 'unanchored-requirement',
        id,
        message: `${id} at ${spec.file}:${spec.line} has no code anchor`,
      });
    }
  }

  // Requirements marked `[e2e]` must carry a test anchor in an e2e spec, not
  // just any test. Anchors record no layer, so membership is resolved through
  // git's own pathspec matching over e2e.test_paths.
  if (e2e.enabled) {
    for (const [id, spec] of specs.entries()) {
      if (!isE2eNearMiss(spec.title)) continue;
      findings.push({
        level: 'warning',
        type: 'suspect-e2e-marker',
        id,
        message: `${id} at ${spec.file}:${spec.line} ends in something like the e2e marker but not exactly "[e2e]"; it is not treated as marked`,
      });
    }
    if (isExcludeOnly(e2e.test_paths)) {
      findings.push({
        level: 'error',
        type: 'e2e-paths-exclude-only',
        message: `e2e.test_paths contains only exclusions (${e2e.test_paths.join(', ')}) — it would match the whole repository; add a positive pathspec`,
      });
    }
    const marked = Array.from(specs.keys()).filter((id) => isE2eMarked(specs.get(id).title));
    if (marked.length && !e2e.test_paths.length) {
      findings.push({
        level: 'warning',
        type: 'e2e-paths-unset',
        message: `${marked.length} requirement(s) marked [e2e] but e2e.test_paths is empty — skipping the marked-coverage check`,
      });
    } else if (marked.length && !e2eTestScan.error && !isExcludeOnly(e2e.test_paths)) {
      // e2eTestScan already scanned exactly the files e2e.test_paths matches,
      // so an anchor it found is by definition an anchor in an e2e spec. Its
      // own path error was already reported by scanAnchors.
      for (const id of marked) {
        if (e2eTestScan.anchors.some((a) => a.id === id)) continue;
        const spec = specs.get(id);
        findings.push({
          level: 'error',
          type: 'missing-e2e-coverage',
          id,
          message: `${id} at ${spec.file}:${spec.line} is marked [e2e] but has no test anchor in ${e2e.test_paths.join(', ')}`,
        });
      }
    }
  }

  if (typeof flags.base === 'string') {
    if (git(['rev-parse', '--verify', flags.base]).status !== 0) {
      findings.push({
        level: 'error',
        type: 'base-ref-not-found',
        message: `trace: base ref ${flags.base} not found — fetch history (CI: fetch-depth: 0)`,
      });
    } else {
      const changedTests = changedFiles(flags.base, trace.test_paths);
      const changedE2e = scanE2ePaths
        ? changedFiles(flags.base, e2e.test_paths)
        : { files: [] };
      if (changedE2e.error) findings.push({ level: 'error', type: 'changed-e2e-error', message: changedE2e.error });
      if (!changedTests.error && !changedE2e.error) {
        changedTests.files = Array.from(new Set([...(changedTests.files || []), ...(changedE2e.files || [])]));
      }
      const changedSpecs = changedFiles(flags.base, trace.spec_paths);
      if (changedTests.error) findings.push({ level: 'error', type: 'changed-tests-error', message: changedTests.error });
      if (changedSpecs.error) findings.push({ level: 'error', type: 'changed-specs-error', message: changedSpecs.error });
      const changedSpecSet = new Set(changedSpecs.files || []);
      const changedTestSet = new Set(changedTests.files || []);
      const commits = commitList(flags.base);
      if (commits.error) findings.push({ level: 'error', type: 'changed-commits-error', message: commits.error });
      for (const commit of commits.commits || []) {
        const files = commitFiles(commit);
        if (files.error) {
          findings.push({ level: 'error', type: 'changed-commit-files-error', message: files.error });
          continue;
        }
        const fileSet = new Set(files.files);
        const changedSpecsInCommit = new Set((changedSpecs.files || []).filter((file) => fileSet.has(file)));
        const overrides = commitSpecOverrideIds(commit);
        // e2e-only anchors are exempt: the marked-coverage check above demands
        // an e2e test for a marker that lands in a spec-only commit, and
        // coupling the answering commit back to a spec change would make the
        // two-commit sequence the standard prescribes unsatisfiable.
        for (const anchor of testScan.anchors.filter((a) => fileSet.has(a.file) && a.source !== 'e2e')) {
          const spec = specs.get(anchor.id);
          if (spec && !changedSpecsInCommit.has(spec.file) && !overrides.has(anchor.id)) {
            findings.push({
              level: 'error',
              type: 'uncoupled-test-change',
              id: anchor.id,
              message: `${anchor.id} changed in ${anchor.file} at ${short(commit)} but owning spec ${spec.file} did not change in that commit; use Spec-Override: ${anchor.id} — <reason> if intentional`,
            });
          }
        }
      }
      for (const [id, spec] of specs.entries()) {
        if (changedSpecSet.has(spec.file) && !testScan.anchors.some((a) => a.id === id && changedTestSet.has(a.file))) {
          findings.push({
            level: 'warning',
            type: 'spec-changed-tests-untouched',
            id,
            message: `${id} changed in ${spec.file} but no anchored test changed`,
          });
        }
      }
    }
  }

  sortFindings(findings);

  const matrix = buildMatrix(specs, testScan.anchors, codeScan.anchors);
  const summary = traceSummary(specs, testScan.anchors, codeScan.anchors, findings);
  const output = { summary, matrix, findings };
  emitTraceReport(output, flags, jsonMode, 'aw-gate: trace FAILED', true);

  if (summary.warnings > 0) {
    if (!jsonMode) {
      process.stdout.write('aw-gate: trace clean with warnings\n');
      for (const f of findings.filter((item) => item.level === 'warning')) {
        process.stdout.write(`  - ${f.type}: ${f.message}\n`);
      }
    }
    process.exit(0);
  }
  if (!jsonMode) {
    process.stdout.write(`aw-gate: trace clean (${summary.requirements} requirement(s), ${summary.test_anchors} test anchor(s), ${summary.code_anchors} code anchor(s))\n`);
  }
  process.exit(0);
}

function isSafeTraceBatch(rel) {
  return typeof rel === 'string' &&
    !path.isAbsolute(rel) &&
    /^\.aw\/tmp\/trace-intents\.[^/]+\.json$/.test(rel);
}

function normalizeIntent(intent) {
  const kind = intent && intent.kind;
  return {
    kind,
    file: intent && intent.file,
    line: Number(intent && intent.line),
    ids: splitIds(intent && (intent.ids || intent.id)),
  };
}

function parseAnnotateIntents(positional, flags) {
  if (typeof flags.batch === 'string') {
    if (!isSafeTraceBatch(flags.batch)) {
      return { error: `trace-annotate batch path must be .aw/tmp/trace-intents.<token>.json: ${flags.batch}` };
    }
    const batchPath = resolveRepoPath(flags.batch);
    if (!batchPath) return { error: `unsafe batch path: ${flags.batch}` };
    let parsed;
    try {
      parsed = JSON.parse(fs.readFileSync(batchPath, 'utf8'));
    } catch (e) {
      return { error: `unable to read batch ${flags.batch}: ${e.message}` };
    }
    if (!parsed || !Array.isArray(parsed.intents)) return { error: 'batch must contain an intents array' };
    return { intents: parsed.intents.map(normalizeIntent), batch: flags.batch };
  }
  return {
    intents: [{
      kind: positional[0],
      file: flags.file,
      line: Number(flags.line),
      ids: splitIds(flags.id),
    }],
  };
}

function lineIds(line) {
  const ids = [];
  const re = anchorRe();
  let m;
  while ((m = re.exec(line || '')) !== null) ids.push(...splitIds(m[1]));
  return ids;
}

function hasAdjacentIds(lines, index, ids) {
  const candidates = [lines[index] || '', lines[index - 1] || ''];
  const found = new Set(candidates.flatMap(lineIds));
  return ids.every((id) => found.has(id));
}

function safeDeleteBatch(rel) {
  if (!isSafeTraceBatch(rel)) return false;
  const abs = resolveRepoPath(rel);
  if (!abs) return false;
  try {
    if (fs.existsSync(abs)) fs.unlinkSync(abs);
    return true;
  } catch (_) {
    return false;
  }
}

function annotationEdits(intents, trace) {
  const specScan = scanSpecs(trace);
  const findings = [...specScan.findings];
  const specs = specScan.specs;
  const editsByFile = new Map();
  const fileTexts = new Map();
  const merged = new Map();

  function readFileForEdit(file, abs) {
    if (fileTexts.has(file)) return fileTexts.get(file);
    const text = fs.readFileSync(abs, 'utf8');
    const newline = text.endsWith('\n') ? '\n' : '';
    const lines = text.split(/\r?\n/);
    if (newline) lines.pop();
    const data = { lines, newline };
    fileTexts.set(file, data);
    return data;
  }

  for (const raw of intents) {
    const intent = normalizeIntent(raw);
    const key = `${intent.kind}|${intent.file}|${intent.line}`;
    if (!merged.has(key)) merged.set(key, intent);
    else {
      const existing = merged.get(key);
      existing.ids = Array.from(new Set([...existing.ids, ...intent.ids])).sort();
    }
  }

  for (const intent of merged.values()) {
    const abs = resolveRepoPath(intent.file);
    if (!['spec', 'test', 'code'].includes(intent.kind)) {
      findings.push({ level: 'error', type: 'invalid-annotation-kind', message: `invalid annotation kind: ${intent.kind}` });
      continue;
    }
    if (!abs) {
      findings.push({ level: 'error', type: 'invalid-annotation-path', message: `annotation path must be repo-relative: ${intent.file}` });
      continue;
    }
    if (!Number.isInteger(intent.line) || intent.line < 1) {
      findings.push({ level: 'error', type: 'invalid-annotation-line', message: `${intent.file}: invalid line ${intent.line}` });
      continue;
    }
    if (intent.ids.length === 0 || intent.ids.some((id) => !SPEC_ID_RE.test(id))) {
      findings.push({ level: 'error', type: 'invalid-spec-id', message: `${intent.file}:${intent.line} has invalid spec id(s): ${intent.ids.join(', ')}` });
      continue;
    }
    if (intent.kind === 'spec' && intent.ids.length !== 1) {
      findings.push({ level: 'error', type: 'invalid-spec-intent', message: `${intent.file}:${intent.line} spec annotations require exactly one id` });
      continue;
    }
    if (intent.kind !== 'spec') {
      for (const id of intent.ids) {
        if (!specs.has(id)) {
          findings.push({ level: 'error', type: 'unknown-spec-id', message: `${intent.file}:${intent.line} references unknown ${id}` });
        }
      }
    } else if (specs.has(intent.ids[0])) {
      const owner = specs.get(intent.ids[0]);
      if (owner.file !== intent.file || owner.line !== intent.line) {
        findings.push({ level: 'error', type: 'duplicate-id', message: `${intent.ids[0]} already belongs to ${owner.file}:${owner.line}` });
      }
    }
    let data;
    try {
      data = readFileForEdit(intent.file, abs);
    } catch (e) {
      findings.push({ level: 'error', type: 'annotation-read-failed', message: `${intent.file}: ${e.message}` });
      continue;
    }
    const lines = data.lines;
    const index = intent.line - 1;
    if (index >= lines.length) {
      findings.push({ level: 'error', type: 'invalid-annotation-line', message: `${intent.file}: line ${intent.line} does not exist` });
      continue;
    }
    if (intent.kind === 'spec') {
      const id = intent.ids[0];
      const m = lines[index].match(/^(#{1,6})\s+(.*)$/);
      if (!m) {
        findings.push({ level: 'error', type: 'invalid-spec-heading', message: `${intent.file}:${intent.line} is not a markdown heading` });
        continue;
      }
      const existing = m[2].match(/^([A-Z][A-Z0-9]{1,7}-\d{3,})(?:\s+[—-]\s+|\s*$)/);
      if (existing && existing[1] !== id) {
        findings.push({ level: 'error', type: 'conflicting-spec-heading', message: `${intent.file}:${intent.line} already starts with ${existing[1]}` });
        continue;
      }
      if (!existing) {
        if (!editsByFile.has(intent.file)) editsByFile.set(intent.file, []);
        editsByFile.get(intent.file).push({ line: intent.line, replace: `${m[1]} ${id} — ${m[2]}` });
      }
      continue;
    }
    if (hasAdjacentIds(lines, index, intent.ids)) continue;
    const comment = intent.kind === 'test' && intent.file.endsWith('.feature')
      ? `@spec:${intent.ids.join(', ')}`
      : intent.kind === 'test'
        ? `// @spec:${intent.ids.join(', ')}`
        : `// @spec ${intent.ids.join(', ')}`;
    if (!editsByFile.has(intent.file)) editsByFile.set(intent.file, []);
    editsByFile.get(intent.file).push({ line: intent.line, insert: comment });
  }

  return { findings, editsByFile, fileTexts };
}

function applyAnnotationEdits(editsByFile, fileTexts) {
  for (const [file, edits] of editsByFile.entries()) {
    const abs = resolveRepoPath(file);
    const data = fileTexts.get(file);
    const lines = data.lines.slice();
    const newline = data.newline;
    const ordered = edits.slice().sort((a, b) => b.line - a.line);
    for (const edit of ordered) {
      const index = edit.line - 1;
      if (edit.replace) lines[index] = edit.replace;
      if (edit.insert) lines.splice(index, 0, edit.insert);
    }
    fs.writeFileSync(abs, lines.join('\n') + newline);
  }
}

function cmdTraceAnnotate(args) {
  const { positional, flags } = parseFlags(args);
  const config = loadConfig();
  const trace = traceConfig(config);
  const batch = typeof flags.batch === 'string' ? flags.batch : null;
  if (!trace.enabled) {
    if (batch) safeDeleteBatch(batch);
    process.stdout.write('aw-gate: trace disabled — annotation skipped\n');
    process.exit(0);
  }
  if (batch && !isSafeTraceBatch(batch)) {
    fail(`trace-annotate batch path must be .aw/tmp/trace-intents.<token>.json: ${batch}`);
  }
  const parsed = parseAnnotateIntents(positional, flags);
  if (parsed.error) fail(parsed.error);
  const { findings, editsByFile, fileTexts } = annotationEdits(parsed.intents, trace);
  const errors = findings.filter((f) => f.level === 'error');
  if (errors.length > 0) {
    process.stderr.write('aw-gate: trace-annotate FAILED\n');
    for (const f of errors) process.stderr.write(`  - ${f.type}: ${f.message}\n`);
    process.exit(1);
  }
  applyAnnotationEdits(editsByFile, fileTexts);
  if (flags['delete-batch-on-success'] === true && batch) safeDeleteBatch(batch);
  const editCount = Array.from(editsByFile.values()).reduce((sum, edits) => sum + edits.length, 0);
  process.stdout.write(`aw-gate: trace annotation applied (${editCount} edit(s))\n`);
  process.exit(0);
}

// --- Behavior pins -------------------------------------------------------
function pinConfig(config) {
  const pin = config.pin || {};
  return {
    enabled: pin.enabled === true,
    manifest_paths: Array.isArray(pin.manifest_paths) ? pin.manifest_paths : ['docs/features/*/behavior-pin.yml'],
    worktree_dir: typeof pin.worktree_dir === 'string' && pin.worktree_dir.trim() !== ''
      ? pin.worktree_dir
      : '.aw/pin',
    out: typeof pin.out === 'string' && pin.out.trim() !== ''
      ? pin.out
      : '.aw/pin/equivalence.json',
    timeout_seconds: Number.isFinite(Number(pin.timeout_seconds)) && Number(pin.timeout_seconds) > 0
      ? Number(pin.timeout_seconds)
      : 900,
  };
}

function asStringList(value) {
  if (Array.isArray(value)) return value.filter((item) => typeof item === 'string' && item.trim() !== '');
  if (typeof value === 'string' && value.trim() !== '') return [value];
  return [];
}

function pinKey(manifestPath) {
  return manifestPath.replace(/[^A-Za-z0-9_.-]+/g, '-').replace(/^-+|-+$/g, '') || 'pin';
}

function sha256(text) {
  return crypto.createHash('sha256').update(text || '').digest('hex');
}

function excerpt(text) {
  const s = String(text || '');
  return s.length > 4000 ? `${s.slice(0, 4000)}\n[truncated]` : s;
}

function writeRunLog(logDir, name, stream, text) {
  const rel = path.join(logDir, `${name}-${stream}.log`);
  const abs = resolveRepoPath(rel);
  if (!abs) fail(`pin log path must be repo-relative: ${rel}`);
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  fs.writeFileSync(abs, text || '');
  return rel;
}

function parsePinCommand(command) {
  const raw = String(command || '').trim();
  if (!raw) return { raw, skipped: true };
  const parts = raw.split(/\s+/);
  if (parts.length !== 2 || parts[0] !== 'node') {
    return { raw, error: 'pin commands must be empty or `node <repo-relative .js path>`' };
  }
  const script = parts[1];
  if (!/^[A-Za-z0-9_./-]+\.js$/.test(script) || path.isAbsolute(script)) {
    return { raw, error: `pin command path must be a repo-relative .js file: ${script}` };
  }
  const abs = resolveRepoPath(script);
  if (!abs) return { raw, error: `pin command path must stay under the repo: ${script}` };
  return { raw, script };
}

function pinCommandScripts(manifest) {
  return [manifest.setup, manifest.harness]
    .map((command) => parsePinCommand(command))
    .filter((parsed) => parsed.script)
    .map((parsed) => parsed.script);
}

function runPinCommand(command, cwd, timeoutMs, logDir, name, env) {
  const parsed = parsePinCommand(command);
  if (parsed.skipped) {
    return {
      command: '',
      skipped: true,
      status: 0,
      signal: null,
      timed_out: false,
      stdout_sha256: sha256(''),
      stderr_sha256: sha256(''),
      stdout_excerpt: '',
      stderr_excerpt: '',
      stdout_log: null,
      stderr_log: null,
    };
  }
  if (parsed.error) {
    return {
      command: parsed.raw,
      skipped: false,
      status: 1,
      signal: null,
      timed_out: false,
      stdout_sha256: sha256(''),
      stderr_sha256: sha256(parsed.error),
      stdout_excerpt: '',
      stderr_excerpt: parsed.error,
      stdout_log: writeRunLog(logDir, name, 'stdout', ''),
      stderr_log: writeRunLog(logDir, name, 'stderr', parsed.error),
    };
  }
  const r = spawnSync(process.execPath, [parsed.script], {
    cwd,
    shell: false,
    timeout: timeoutMs,
    encoding: 'utf8',
    maxBuffer: 10 * 1024 * 1024,
    env: env ? { ...process.env, ...env } : process.env,
  });
  const stdout = r.stdout || '';
  const stderr = r.stderr || '';
  return {
    command: parsed.raw,
    skipped: false,
    status: r.status === null ? 1 : r.status,
    signal: r.signal || null,
    timed_out: Boolean(r.error && r.error.code === 'ETIMEDOUT'),
    stdout_sha256: sha256(stdout),
    stderr_sha256: sha256(stderr),
    stdout_excerpt: excerpt(stdout),
    stderr_excerpt: excerpt(stderr),
    stdout_log: writeRunLog(logDir, name, 'stdout', stdout),
    stderr_log: writeRunLog(logDir, name, 'stderr', stderr),
  };
}

function loadPinManifests(pin) {
  const listed = listCurrentFiles(pin.manifest_paths);
  const findings = [];
  const manifests = [];
  if (listed.error) return { manifests, findings: [{ level: 'error', type: 'manifest-path-error', message: listed.error }] };
  for (const file of listed.files.filter((f) => f.endsWith('behavior-pin.yml'))) {
    const abs = resolveRepoPath(file);
    if (!abs) continue;
    let data;
    try {
      data = parseYaml(fs.readFileSync(abs, 'utf8'));
    } catch (e) {
      findings.push({ level: 'error', type: 'manifest-read-failed', file, message: `${file}: ${e.message}` });
      continue;
    }
    const manifest = {
      path: file,
      key: pinKey(file),
      mode: typeof data.mode === 'string' && data.mode.trim() !== '' ? data.mode : 'same-repo',
      base: typeof data.base === 'string' ? data.base : '',
      harness: typeof data.harness === 'string' ? data.harness : '',
      setup: typeof data.setup === 'string' ? data.setup : '',
      subject: asStringList(data.subject),
      oracle: asStringList(data.oracle),
      support: asStringList(data.support),
      reference: data.reference && typeof data.reference === 'object' && !Array.isArray(data.reference)
        ? {
          repo: typeof data.reference.repo === 'string' ? data.reference.repo : '',
          ref: typeof data.reference.ref === 'string' ? data.reference.ref : '',
        }
        : { repo: '', ref: '' },
      golden: data.golden && typeof data.golden === 'object' && !Array.isArray(data.golden)
        ? {
          dir: typeof data.golden.dir === 'string' ? data.golden.dir : '',
          generated_from: data.golden.generated_from && typeof data.golden.generated_from === 'object' && !Array.isArray(data.golden.generated_from)
            ? {
              repo: typeof data.golden.generated_from.repo === 'string' ? data.golden.generated_from.repo : '',
              ref: typeof data.golden.generated_from.ref === 'string' ? data.golden.generated_from.ref : '',
              sha: typeof data.golden.generated_from.sha === 'string' ? data.golden.generated_from.sha : '',
            }
            : {},
        }
        : {},
      created: data.created || '',
    };
    manifests.push(manifest);
  }
  return { manifests, findings };
}

function pathspecToRegex(spec) {
  let out = '';
  for (let i = 0; i < spec.length; i += 1) {
    const ch = spec[i];
    if (ch === '*') {
      if (spec[i + 1] === '*') {
        if (spec[i + 2] === '/') {
          out += '(?:.*/)?';
          i += 2;
        } else {
          out += '.*';
          i += 1;
        }
      } else {
        out += '[^/]*';
      }
      continue;
    }
    out += /[.+^${}()|[\]\\]/.test(ch) ? `\\${ch}` : ch;
  }
  return new RegExp(`^${out}$`);
}

function pathMatchesSpec(file, spec) {
  if (typeof spec !== 'string' || spec.trim() === '') return false;
  const clean = spec.replace(/^['"]|['"]$/g, '');
  if (clean.includes('*')) return pathspecToRegex(clean).test(file);
  return file === clean || file.startsWith(`${clean.replace(/\/+$/, '')}/`);
}

function pathMatchesAny(file, specs) {
  return specs.some((spec) => pathMatchesSpec(file, spec));
}

function hasUnsafeGitText(value) {
  return /[\x00-\x1f`$;&|<>\s]/.test(value);
}

function isSafeReferenceRepo(repo) {
  if (typeof repo !== 'string' || repo.trim() === '' || repo.startsWith('-') || hasUnsafeGitText(repo)) return false;
  if (/^(https?|ssh|git|file):\/\//.test(repo)) return true;
  if (/^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:[A-Za-z0-9_./-]+$/.test(repo)) return true;
  if (path.isAbsolute(repo)) return true;
  return /^[A-Za-z0-9_./-]+$/.test(repo) && !repo.split('/').includes('..');
}

function isSafeReferenceRef(ref) {
  if (typeof ref !== 'string' || ref.trim() === '' || ref.startsWith('-') || hasUnsafeGitText(ref)) return false;
  if (ref.includes('..') || ref.includes('@{') || ref.endsWith('.') || ref.endsWith('/')) return false;
  return /^[A-Za-z0-9_./+-]+$/.test(ref);
}

function referenceRepoSource(repo) {
  if (/^(https?|ssh|git|file):\/\//.test(repo) || /^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:[A-Za-z0-9_./-]+$/.test(repo)) {
    return repo;
  }
  return path.isAbsolute(repo) ? path.resolve(repo) : path.resolve(repoRoot, repo);
}

function validatePinManifest(manifest) {
  const findings = [];
  if (!['same-repo', 'reference-repo'].includes(manifest.mode)) {
    findings.push({ level: 'error', type: 'unsupported-pin-mode', file: manifest.path, message: `${manifest.path}: unsupported mode ${manifest.mode}` });
  }
  if (manifest.mode === 'same-repo') {
    if (!manifest.base) findings.push({ level: 'error', type: 'missing-base', file: manifest.path, message: `${manifest.path}: base is required` });
    else if (!commitReachable(manifest.base)) findings.push({ level: 'error', type: 'base-ref-not-found', file: manifest.path, message: `${manifest.path}: base ref ${manifest.base} not found` });
  }
  if (manifest.mode === 'reference-repo') {
    if (!manifest.reference.repo) findings.push({ level: 'error', type: 'missing-reference-repo', file: manifest.path, message: `${manifest.path}: reference.repo is required` });
    else if (!isSafeReferenceRepo(manifest.reference.repo)) findings.push({ level: 'error', type: 'unsafe-reference-repo', file: manifest.path, message: `${manifest.path}: reference.repo is not a supported git URL or local path` });
    if (!manifest.reference.ref) findings.push({ level: 'error', type: 'missing-reference-ref', file: manifest.path, message: `${manifest.path}: reference.ref is required` });
    else if (!isSafeReferenceRef(manifest.reference.ref)) findings.push({ level: 'error', type: 'unsafe-reference-ref', file: manifest.path, message: `${manifest.path}: reference.ref is not a supported git ref` });
  }
  if (manifest.golden.dir) {
    const goldenDir = resolveRepoPath(manifest.golden.dir);
    if (!goldenDir) findings.push({ level: 'error', type: 'invalid-golden-dir', file: manifest.path, message: `${manifest.path}: golden.dir must be repo-relative` });
  }
  if (!manifest.harness) findings.push({ level: 'error', type: 'missing-harness', file: manifest.path, message: `${manifest.path}: harness is required` });
  for (const [field, command] of [['setup', manifest.setup], ['harness', manifest.harness]]) {
    const parsed = parsePinCommand(command);
    if (parsed.error) {
      findings.push({ level: 'error', type: 'unsafe-pin-command', file: manifest.path, message: `${manifest.path}: ${field} ${parsed.error}` });
    } else if (!parsed.skipped) {
      const abs = resolveRepoPath(parsed.script);
      if (!abs || !fs.existsSync(abs)) {
        findings.push({ level: 'error', type: 'missing-pin-command-file', file: manifest.path, message: `${manifest.path}: ${field} script not found: ${parsed.script}` });
      }
    }
  }
  if (manifest.subject.length === 0) findings.push({ level: 'error', type: 'missing-subject', file: manifest.path, message: `${manifest.path}: subject paths are required` });
  if (manifest.oracle.length === 0) findings.push({ level: 'error', type: 'missing-oracle', file: manifest.path, message: `${manifest.path}: oracle paths are required` });
  const judged = Array.from(new Set(manifest.oracle.concat(manifest.support, pinCommandScripts(manifest))));
  const subjectFiles = listCurrentFiles(manifest.subject);
  const judgedFiles = listCurrentFiles(judged);
  if (subjectFiles.error) findings.push({ level: 'error', type: 'subject-path-error', file: manifest.path, message: subjectFiles.error });
  if (judgedFiles.error) findings.push({ level: 'error', type: 'oracle-path-error', file: manifest.path, message: judgedFiles.error });
  if (!subjectFiles.error && !judgedFiles.error) {
    const subjectSet = new Set(subjectFiles.files);
    for (const file of judgedFiles.files) {
      if (subjectSet.has(file)) {
        findings.push({ level: 'error', type: 'pin-overlap', file: manifest.path, message: `${manifest.path}: ${file} is both subject and oracle/support` });
      }
    }
  }
  return findings;
}

function copyPinFilesToWorktree(files, worktree) {
  for (const file of files) {
    const src = resolveRepoPath(file);
    if (!src || !fs.existsSync(src) || fs.statSync(src).isDirectory()) continue;
    const dest = path.join(worktree, file);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(src, dest);
  }
}

function pinVerdict(oldSetup, oldHarness, newSetup, newHarness) {
  if ((oldSetup && oldSetup.status !== 0) || oldHarness.status !== 0) return 'pin-not-characterizing';
  if ((newSetup && newSetup.status !== 0) || newHarness.status !== 0) return 'equivalence-broken';
  return 'pass';
}

function migrationPinVerdict(setup, harness) {
  if ((setup && setup.status === 10) || harness.status === 10) return 'pin-not-characterizing';
  if ((setup && setup.status !== 0) || harness.status !== 0) return 'equivalence-broken';
  return 'pass';
}

function runSameRepoPin(manifest, pin) {
  const worktreeRoot = resolveRepoPath(pin.worktree_dir);
  if (!worktreeRoot) fail(`pin.worktree_dir must be repo-relative: ${pin.worktree_dir}`);
  const logDir = path.join(path.dirname(pin.out), 'logs');
  const worktreeName = `${manifest.key}-${process.pid}-${Date.now().toString(36)}-${crypto.randomBytes(4).toString('hex')}`;
  const worktree = path.join(worktreeRoot, worktreeName);
  const timeoutMs = pin.timeout_seconds * 1000;
  const copied = listCurrentFiles(Array.from(new Set(manifest.oracle.concat(manifest.support, pinCommandScripts(manifest)))));
  if (copied.error) {
    return { manifest: manifest.path, verdict: 'pin-not-characterizing', findings: [{ level: 'error', type: 'copy-path-error', message: copied.error }] };
  }
  let oldSetup = null;
  let oldHarness = null;
  let newSetup = null;
  let newHarness = null;
  try {
    fs.rmSync(worktree, { recursive: true, force: true });
    fs.mkdirSync(path.dirname(worktree), { recursive: true });
    const add = git(['worktree', 'add', '--detach', worktree, manifest.base]);
    if (add.status !== 0) {
      return {
        manifest: manifest.path,
        verdict: 'pin-not-characterizing',
        findings: [{ level: 'error', type: 'worktree-add-failed', message: (add.stderr || '').trim() || 'git worktree add failed' }],
      };
    }
    copyPinFilesToWorktree(copied.files, worktree);
    oldSetup = runPinCommand(manifest.setup, worktree, timeoutMs, logDir, `${manifest.key}-old-setup`);
    oldHarness = runPinCommand(manifest.harness, worktree, timeoutMs, logDir, `${manifest.key}-old-harness`);
    newSetup = runPinCommand(manifest.setup, repoRoot, timeoutMs, logDir, `${manifest.key}-new-setup`);
    newHarness = runPinCommand(manifest.harness, repoRoot, timeoutMs, logDir, `${manifest.key}-new-harness`);
  } finally {
    git(['worktree', 'remove', '--force', worktree]);
    fs.rmSync(worktree, { recursive: true, force: true });
  }
  const verdict = pinVerdict(oldSetup, oldHarness, newSetup, newHarness);
  return {
    manifest: manifest.path,
    key: manifest.key,
    mode: manifest.mode,
    verdict,
    base: manifest.base,
    base_sha: revParse(manifest.base),
    subject: manifest.subject,
    oracle: manifest.oracle,
    support: manifest.support,
    copied_files: copied.files,
    old: { setup: oldSetup, harness: oldHarness },
    new: { setup: newSetup, harness: newHarness },
  };
}

function cloneReferenceRepo(manifest, checkout, timeoutMs) {
  const source = referenceRepoSource(manifest.reference.repo);
  const clone = spawnSync('git', ['clone', '--quiet', '--no-checkout', source, checkout], { encoding: 'utf8', timeout: timeoutMs });
  if (clone.status !== 0) return { error: (clone.stderr || '').trim() || 'git clone failed' };
  const checkoutRef = gitAt(checkout, ['checkout', '--quiet', '--detach', manifest.reference.ref], { timeout: timeoutMs });
  if (checkoutRef.status !== 0) return { error: (checkoutRef.stderr || '').trim() || 'git checkout failed' };
  const sha = gitAt(checkout, ['rev-parse', 'HEAD'], { timeout: timeoutMs });
  if (sha.status !== 0) return { error: (sha.stderr || '').trim() || 'git rev-parse failed' };
  return { sha: sha.stdout.trim() };
}

function runReferenceRepoPin(manifest, pin) {
  const worktreeRoot = resolveRepoPath(pin.worktree_dir);
  if (!worktreeRoot) fail(`pin.worktree_dir must be repo-relative: ${pin.worktree_dir}`);
  const logDir = path.join(path.dirname(pin.out), 'logs');
  const checkoutName = `${manifest.key}-reference-${process.pid}-${Date.now().toString(36)}-${crypto.randomBytes(4).toString('hex')}`;
  const checkout = path.join(worktreeRoot, checkoutName);
  const timeoutMs = pin.timeout_seconds * 1000;
  const copied = listCurrentFiles(Array.from(new Set(manifest.oracle.concat(manifest.support, pinCommandScripts(manifest)))));
  if (copied.error) {
    return { manifest: manifest.path, verdict: 'pin-not-characterizing', findings: [{ level: 'error', type: 'copy-path-error', message: copied.error }] };
  }
  let reference = null;
  let setup = null;
  let harness = null;
  try {
    fs.rmSync(checkout, { recursive: true, force: true });
    fs.mkdirSync(path.dirname(checkout), { recursive: true });
    reference = cloneReferenceRepo(manifest, checkout, timeoutMs);
    if (reference.error) {
      return {
        manifest: manifest.path,
        key: manifest.key,
        mode: manifest.mode,
        verdict: 'pin-not-characterizing',
        reference: {
          repo: manifest.reference.repo,
          ref: manifest.reference.ref,
          sha: null,
        },
        golden: manifest.golden,
        findings: [{ level: 'error', type: 'reference-checkout-failed', message: reference.error }],
      };
    }
    const env = {
      AW_PIN_MODE: manifest.mode,
      AW_PIN_MANIFEST: manifest.path,
      AW_PIN_REFERENCE_ROOT: checkout,
      AW_PIN_CANDIDATE_ROOT: repoRoot,
      AW_PIN_GOLDEN_ROOT: manifest.golden.dir ? resolveRepoPath(manifest.golden.dir) : '',
    };
    setup = runPinCommand(manifest.setup, repoRoot, timeoutMs, logDir, `${manifest.key}-migration-setup`, env);
    harness = runPinCommand(manifest.harness, repoRoot, timeoutMs, logDir, `${manifest.key}-migration-harness`, env);
  } finally {
    fs.rmSync(checkout, { recursive: true, force: true });
  }
  const verdict = migrationPinVerdict(setup, harness);
  return {
    manifest: manifest.path,
    key: manifest.key,
    mode: manifest.mode,
    verdict,
    subject: manifest.subject,
    oracle: manifest.oracle,
    support: manifest.support,
    copied_files: copied.files,
    reference: {
      repo: manifest.reference.repo,
      ref: manifest.reference.ref,
      sha: reference.sha,
    },
    golden: manifest.golden,
    run: { setup, harness },
  };
}

function runOnePin(manifest, pin) {
  if (manifest.mode === 'reference-repo') return runReferenceRepoPin(manifest, pin);
  return runSameRepoPin(manifest, pin);
}

function pinSummary(results, findings, disabled) {
  const resultFindings = results.flatMap((r) => Array.isArray(r.findings) ? r.findings : []);
  const allFindings = findings.concat(resultFindings);
  return {
    disabled: disabled === true,
    pins: results.length,
    passed: results.filter((r) => r.verdict === 'pass').length,
    failed: results.filter((r) => r.verdict && r.verdict !== 'pass').length,
    errors: allFindings.filter((f) => f.level === 'error').length,
    warnings: allFindings.filter((f) => f.level === 'warning').length,
  };
}

function writePinOutput(out, payload) {
  const abs = resolveRepoPath(out);
  if (!abs) fail(`pin --out must be repo-relative: ${out}`);
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  fs.writeFileSync(abs, JSON.stringify(payload, null, 2) + '\n');
}

function cmdPinRun(args) {
  const { flags } = parseFlags(args);
  const config = loadConfig();
  const pin = pinConfig(config);
  const jsonMode = flags.json === true;
  if (typeof flags.out === 'string') pin.out = flags.out;
  if (!pin.enabled) {
    const output = { summary: pinSummary([], [], true), results: [], findings: [] };
    if (typeof flags.out === 'string') writePinOutput(pin.out, output);
    if (jsonMode) process.stdout.write(JSON.stringify(output, null, 2) + '\n');
    else process.stdout.write('aw-gate: pin disabled (pin.enabled is not true) — skipping\n');
    process.exit(0);
  }
  const loaded = loadPinManifests(pin);
  const findings = loaded.findings;
  const results = [];
  for (const manifest of loaded.manifests) {
    findings.push(...validatePinManifest(manifest));
  }
  if (findings.some((f) => f.level === 'error')) {
    const output = { summary: pinSummary(results, findings, false), results, findings };
    writePinOutput(pin.out, output);
    if (jsonMode) process.stdout.write(JSON.stringify(output, null, 2) + '\n');
    process.stderr.write('aw-gate: pin run FAILED\n');
    for (const f of findings.filter((item) => item.level === 'error')) process.stderr.write(`  - ${f.type}: ${f.message}\n`);
    process.exit(1);
  }
  for (const manifest of loaded.manifests) {
    results.push(runOnePin(manifest, pin));
  }
  const output = { summary: pinSummary(results, findings, false), results, findings };
  writePinOutput(pin.out, output);
  if (jsonMode) process.stdout.write(JSON.stringify(output, null, 2) + '\n');
  const failed = results.filter((r) => r.verdict !== 'pass');
  if (failed.length > 0) {
    process.stderr.write('aw-gate: pin run FAILED\n');
    for (const r of failed) process.stderr.write(`  - ${r.verdict}: ${r.manifest}\n`);
    process.exit(1);
  }
  if (!jsonMode) process.stdout.write(`aw-gate: pin run clean (${results.length} pin(s))\n`);
  process.exit(0);
}

function commitList(base) {
  if (!currentCommit()) return { commits: [] };
  const r = git(['log', '--format=%H', `${base}..HEAD`]);
  if (r.status !== 0) return { error: (r.stderr || '').trim() || 'git log failed', commits: [] };
  return { commits: r.stdout.split(/\r?\n/).filter(Boolean) };
}

function commitFiles(commit) {
  const r = git(['diff-tree', '--no-commit-id', '--name-only', '-r', commit]);
  if (r.status !== 0) return { error: (r.stderr || '').trim() || 'git diff-tree failed', files: [] };
  return { files: r.stdout.split(/\r?\n/).filter(Boolean) };
}

function commitHasPinOverride(commit, manifestPath) {
  const r = git(['log', '-1', '--format=%(trailers:key=Pin-Override,valueonly)', commit]);
  if (r.status !== 0) return false;
  const prefix = manifestPath.toLowerCase();
  return r.stdout.split(/\r?\n/).some((line) => line.trim().toLowerCase().startsWith(prefix));
}

function cmdPinCheck(args) {
  const { flags } = parseFlags(args);
  const config = loadConfig();
  const pin = pinConfig(config);
  const jsonMode = flags.json === true;
  if (!pin.enabled) {
    const output = { summary: { disabled: true, commits: 0, manifests: 0, errors: 0 }, findings: [] };
    if (jsonMode) process.stdout.write(JSON.stringify(output, null, 2) + '\n');
    else process.stdout.write('aw-gate: pin disabled (pin.enabled is not true) — skipping\n');
    process.exit(0);
  }
  const base = typeof flags.base === 'string' ? flags.base : 'origin/main';
  const findings = [];
  if (git(['rev-parse', '--verify', base]).status !== 0) {
    findings.push({ level: 'error', type: 'base-ref-not-found', message: `pin: base ref ${base} not found — fetch history (CI: fetch-depth: 0)` });
  }
  const loaded = loadPinManifests(pin);
  findings.push(...loaded.findings);
  const commits = findings.some((f) => f.level === 'error') ? { commits: [] } : commitList(base);
  if (commits.error) findings.push({ level: 'error', type: 'pin-log-error', message: commits.error });
  for (const manifest of loaded.manifests) {
    findings.push(...validatePinManifest(manifest));
  }
  if (!findings.some((f) => f.level === 'error')) {
    for (const commit of commits.commits) {
      const files = commitFiles(commit);
      if (files.error) {
        findings.push({ level: 'error', type: 'pin-commit-files-error', message: files.error });
        continue;
      }
      for (const manifest of loaded.manifests) {
        const touchesSubject = files.files.some((file) => pathMatchesAny(file, manifest.subject));
        const touchesOracle = files.files.some((file) => pathMatchesAny(file, [manifest.path].concat(manifest.oracle, manifest.support, pinCommandScripts(manifest))));
        if (touchesSubject && touchesOracle && commitHasPinOverride(commit, manifest.path)) continue;
        if (touchesSubject && touchesOracle) {
          findings.push({
            level: 'error',
            type: 'pin-coupled-change',
            manifest: manifest.path,
            commit,
            message: `${short(commit)} changes subject and oracle/support for ${manifest.path}; use Pin-Override: ${manifest.path} — <reason> if intentional`,
          });
        }
      }
    }
  }
  sortFindings(findings);
  const output = {
    summary: {
      disabled: false,
      manifests: loaded.manifests.length,
      commits: commits.commits ? commits.commits.length : 0,
      errors: findings.filter((f) => f.level === 'error').length,
    },
    findings,
  };
  if (jsonMode) process.stdout.write(JSON.stringify(output, null, 2) + '\n');
  if (output.summary.errors > 0) {
    process.stderr.write('aw-gate: pin check FAILED\n');
    for (const f of findings.filter((item) => item.level === 'error')) process.stderr.write(`  - ${f.type}: ${f.message}\n`);
    process.exit(1);
  }
  if (!jsonMode) process.stdout.write(`aw-gate: pin check clean (${output.summary.manifests} pin(s), ${output.summary.commits} commit(s))\n`);
  process.exit(0);
}

function cmdPin(args) {
  let subIndex = -1;
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (arg === 'run' || arg === 'check') {
      subIndex = i;
      break;
    }
    if ((arg === '--out' || arg === '--base') && args[i + 1] && !args[i + 1].startsWith('--')) {
      i += 1;
    }
  }
  const sub = subIndex >= 0 ? args[subIndex] : null;
  const rest = subIndex >= 0 ? args.slice(0, subIndex).concat(args.slice(subIndex + 1)) : [];
  if (sub === 'run') return cmdPinRun(rest);
  if (sub === 'check') return cmdPinCheck(rest);
  fail('pin requires a subcommand: run or check');
}

function isSafeGitRef(ref) {
  return typeof ref === 'string' &&
    /^[A-Za-z0-9._/-]+$/.test(ref) &&
    !ref.startsWith('-') &&
    !ref.includes('..') &&
    !ref.includes('@{') &&
    !ref.includes('\\') &&
    !ref.endsWith('/') &&
    !ref.endsWith('.lock');
}

function cmdOrgSync() {
  const config = loadConfig();
  const org = config.org_knowledge || {};
  // Require a non-empty string. A bare `source:` parses as an empty mapping ({})
  // under this reader, not "" — guard against it so we skip rather than trying to
  // clone "[object Object]".
  const source = typeof org.source === 'string' ? org.source.trim() : org.source;
  if (typeof source !== 'string' || source === '') {
    process.stdout.write('aw-gate: org_knowledge.source not configured — skipping\n');
    process.exit(0);
  }
  if (!source.startsWith('https://')) {
    fail('org_knowledge.source must be an https:// Git URL');
  }
  const ref = typeof org.ref === 'string' && org.ref.trim() !== '' ? org.ref : 'main';
  if (!isSafeGitRef(ref)) {
    fail(`org_knowledge.ref must be a safe branch or tag name: ${ref}`);
  }
  const cacheDir = typeof org.cache_dir === 'string' && org.cache_dir.trim() !== ''
    ? org.cache_dir
    : '.aw-org-cache';
  const abs = resolveRepoPath(cacheDir);
  if (!abs) fail(`org_knowledge.cache_dir must be repo-relative: ${cacheDir}`);
  try {
    if (fs.existsSync(path.join(abs, '.git'))) {
      // Reset to FETCH_HEAD (what was just fetched) so this resolves for both
      // branches and tags; `origin/<ref>` does not exist for tag refs.
      execFileSync('git', ['-C', abs, 'fetch', '--depth', '1', 'origin', ref], { stdio: 'inherit' });
      execFileSync('git', ['-C', abs, 'reset', '--hard', '-q', 'FETCH_HEAD'], { stdio: 'inherit' });
    } else {
      fs.mkdirSync(path.dirname(abs), { recursive: true });
      execFileSync('git', ['clone', '--depth', '1', '--branch', ref, source, abs], { stdio: 'inherit' });
    }
  } catch (e) {
    fail(`org-sync failed: ${e.message}`);
  }
  const paths = org.paths || {};
  const learnings = path.join(cacheDir, paths.learnings || 'learnings');
  const standards = path.join(cacheDir, paths.standards || 'standards');
  process.stdout.write(`aw-gate: org knowledge synced to ${cacheDir}\n`);
  process.stdout.write(`  learnings: ${learnings}\n`);
  process.stdout.write(`  standards: ${standards}\n`);
}

function usage() {
  process.stdout.write(
    [
      'aw-gate — augmented-workflow deterministic helper',
      '',
      'Usage:',
      '  node .scripts/aw-gate.js receipt <gate> --summary "text" [--detail "text"]',
      '  node .scripts/aw-gate.js record <event> [--detail "text"] [--no-receipt]',
      '  node .scripts/aw-gate.js check [--against head|worktree]',
      '  node .scripts/aw-gate.js trace [--base <ref>] [--json] [--out <path>]',
      '  node .scripts/aw-gate.js trace --suggest-e2e [--json] [--out <path>]',
      '  node .scripts/aw-gate.js trace-annotate <spec|test|code> --file <path> --line <n> --id <ID>[,<ID>]',
      '  node .scripts/aw-gate.js trace-annotate --batch .aw/tmp/trace-intents.<token>.json [--delete-batch-on-success]',
      '  node .scripts/aw-gate.js workflow-record <event> [--tier <tier>] [--step <step>] [--gate <gate>] [--status <status>] [--reason <text>]',
      '  node .scripts/aw-gate.js workflow-check [--base <ref>] [--since-commit <ref>] [--json]',
      '  node .scripts/aw-gate.js pin run [--json] [--out <path>]',
      '  node .scripts/aw-gate.js pin check [--base <ref>] [--json]',
      '  node .scripts/aw-gate.js org-sync',
      '  node .scripts/aw-gate.js prune-telemetry',
      '  node .scripts/aw-gate.js track <skill>',
      '',
      'Config: docs/workflow/config.yml (gates, telemetry, tracking, org_knowledge, trace, e2e, workflow_trace, pin).',
      'All are opt-in and disabled by default.',
      '',
    ].join('\n')
  );
}

function main() {
  const [command, ...rest] = process.argv.slice(2);
  switch (command) {
    case 'receipt':
      return cmdReceipt(rest);
    case 'record':
      return cmdRecord(rest);
    case 'check':
      return cmdCheck(rest);
    case 'trace':
      return cmdTrace(rest);
    case 'trace-annotate':
      return cmdTraceAnnotate(rest);
    case 'workflow-record':
      return cmdWorkflowRecord(rest);
    case 'workflow-check':
      return cmdWorkflowCheck(rest);
    case 'pin':
      return cmdPin(rest);
    case 'org-sync':
      return cmdOrgSync();
    case 'prune-telemetry':
      return cmdPruneTelemetry();
    case 'track':
      return cmdTrack(rest);
    case 'help':
    case '--help':
    case '-h':
    case undefined:
      return usage();
    default:
      process.stderr.write(`aw-gate: unknown command "${command}"\n`);
      usage();
      process.exit(2);
  }
}

main();
