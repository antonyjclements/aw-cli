from __future__ import annotations

from pathlib import Path


ENABLED_BLOCKS = {
    "tracking": [
        "tracking:",
        "  enabled: true",
        "  path: docs/metrics/skills.jsonl",
        "  rotation: monthly",
        "  retention_months: 12",
        "  session_file: .aw/session",
        "  session_ttl_hours: 8",
    ],
    "telemetry": [
        "telemetry:",
        "  enabled: true",
        "  path: docs/metrics/events.jsonl",
        "  rotation: monthly",
        "  retention_months: 12",
    ],
    "trace": [
        "trace:",
        "  enabled: true",
        '  spec_paths:',
        '    - "docs/features/*/spec.md"',
        "  test_paths:",
        '    - "*.feature"',
        '    - "*.test.ts"',
        '    - "*.test.tsx"',
        '    - "*.spec.ts"',
        "  code_paths:",
        '    - "src"',
        "  require_code_anchor: false",
    ],
    "pin": [
        "pin:",
        "  enabled: true",
        "  manifest_paths:",
        '    - "docs/features/*/behavior-pin.yml"',
        "  worktree_dir: .aw/pin",
        "  out: .aw/pin/equivalence.json",
        "  timeout_seconds: 900",
    ],
    "workflow_trace": [
        "workflow_trace:",
        "  enabled: true",
        "  path: .aw/workflow-trace.jsonl",
        "  max_events: 10000",
        "  max_bytes: 5242880",
        "  require_tier: true",
        "  required_gates:",
        "    - review",
        "    - check_workflow_compliance",
    ],
}


def enable_default_aw_features(config_path: Path) -> bool:
    if not config_path.is_file():
        return False

    original = config_path.read_text(encoding="utf-8")
    updated = original
    for section, block in ENABLED_BLOCKS.items():
        updated = _ensure_enabled_block(updated, section, block)

    if updated != original:
        config_path.write_text(updated, encoding="utf-8")
    return updated != original


def _ensure_enabled_block(text: str, section: str, default_block: list[str]) -> str:
    lines = text.splitlines()
    start = _top_level_section_start(lines, section)
    if start is None:
        return _insert_missing_block(lines, section, default_block)

    end = _top_level_section_end(lines, start + 1)
    block = lines[start:end]
    enabled_index = next((index for index, line in enumerate(block[1:], start=1) if line.startswith("  enabled:")), None)
    if enabled_index is None:
        block.insert(1, "  enabled: true")
    else:
        block[enabled_index] = "  enabled: true"
    return "\n".join(lines[:start] + block + lines[end:]) + "\n"


def _top_level_section_start(lines: list[str], section: str) -> int | None:
    marker = f"{section}:"
    for index, line in enumerate(lines):
        if line == marker:
            return index
    return None


def _top_level_section_end(lines: list[str], start: int) -> int:
    for index in range(start, len(lines)):
        line = lines[index]
        if line and not line.startswith((" ", "-")) and line.endswith(":"):
            return index
    return len(lines)


def _insert_missing_block(lines: list[str], section: str, block: list[str]) -> str:
    preferred_order = ["tracking", "telemetry", "trace", "pin", "workflow_trace"]
    later_sections = preferred_order[preferred_order.index(section) + 1 :]
    insert_at = next((_top_level_section_start(lines, later) for later in later_sections if _top_level_section_start(lines, later) is not None), None)
    if insert_at is None:
        insert_at = len(lines)
    new_lines = lines[:insert_at] + block + lines[insert_at:]
    return "\n".join(new_lines) + "\n"
