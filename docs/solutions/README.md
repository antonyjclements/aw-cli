# Solutions

Reusable solved-problem docs. When a non-trivial problem is solved and the root
cause, debugging path, or prevention pattern would help a future agent,
`aw-capture solution` records it here.

## Layout

```text
docs/solutions/<category>/YYYY-MM-DD-<slug>.md
```

Categories are `build`, `runtime`, `data`, `integration`, `infra`, `performance`,
`tooling`, and `patterns`. Directories are created on first use, so an empty
category simply does not exist yet.

`patterns/` holds guidance generalized from several concrete solutions. It carries
a higher evidence bar than the other categories because stale generalized advice
misleads at scale.

## No index

This directory is index-free and self-describing, the same as `docs/brainstorms/`
and `docs/sessions/`. Every doc carries its own frontmatter (`title`, `status`,
`created`, `problem_type`, `category`, and optional `module`/`component`/`tags`),
and `aw-refresh solutions` globs the tree rather than reading a registry. Do not
add `index.yml` here.

## Maintenance

`aw-refresh solutions` compares these docs against the current codebase and keeps,
updates, consolidates, replaces, or deletes them, marking uncertain docs
`status: stale`. Deletion is preferred over archiving — git history is the archive.

`README.md` and `_archived/` are excluded from that scope.

## How this differs from neighbouring artifacts

- **Solutions** — how a specific problem was diagnosed and fixed, so it does not
  have to be re-derived.
- **Learnings** (`docs/learnings/`) — corrections to agent behavior, earned through
  corroboration across sessions.
- **Decisions** (`docs/decisions/`) — immutable records of why a choice was made.
- **Standards** (`docs/standards/`) — enforceable rules agents must follow.

A solved problem that reveals an enforceable rule belongs in both: the solution
here, the rule in `docs/standards/`.
