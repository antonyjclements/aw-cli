from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


WORKFLOW_STEPS = ("review", "check_workflow_compliance", "capture", "synthesize")
SKILL_STEP_ALIASES = {
    "aw-review": "review",
    "aw-check-workflow-compliance": "check_workflow_compliance",
    "aw-capture": "capture",
    "aw-synthesize-memory": "synthesize",
}


@dataclass(frozen=True)
class MetricEvent:
    ts: datetime | None
    event: str
    detail: str | None
    source: str | None


@dataclass(frozen=True)
class SkillEvent:
    ts: datetime | None
    session_id: str | None
    skill: str
    workflow_step: str | None
    source: str | None


@dataclass(frozen=True)
class MetricsDataset:
    events: list[MetricEvent]
    skills: list[SkillEvent]


def load_events(metrics_dir: Path) -> list[MetricEvent]:
    events: list[MetricEvent] = []
    for payload in _read_jsonl(metrics_dir, "events*.jsonl"):
        events.append(
            MetricEvent(
                ts=_parse_ts(payload.get("ts")),
                event=str(payload.get("event") or "unknown"),
                detail=payload.get("detail"),
                source=payload.get("source"),
            )
        )
    return events


def load_skill_events(metrics_dir: Path) -> list[SkillEvent]:
    skills: list[SkillEvent] = []
    for payload in _read_jsonl(metrics_dir, "skills*.jsonl"):
        skills.append(
            SkillEvent(
                ts=_parse_ts(payload.get("ts")),
                session_id=str(payload["session_id"]) if payload.get("session_id") else None,
                skill=str(payload.get("skill") or "unknown"),
                workflow_step=str(payload["workflow_step"]) if payload.get("workflow_step") else None,
                source=payload.get("source"),
            )
        )
    return skills


def load_dataset(metrics_dir: Path) -> MetricsDataset:
    return MetricsDataset(events=load_events(metrics_dir), skills=load_skill_events(metrics_dir))


def event_counts(events: list[MetricEvent]) -> Counter[str]:
    return Counter(event.event for event in events)


def skill_counts(skills: list[SkillEvent]) -> Counter[str]:
    return Counter(event.skill for event in skills)


def hourly_activity(dataset: MetricsDataset) -> Counter[int]:
    counts: Counter[int] = Counter()
    for ts in _all_timestamps(dataset):
        counts[ts.hour] += 1
    return counts


def daily_activity(dataset: MetricsDataset) -> Counter[date]:
    counts: Counter[date] = Counter()
    for ts in _all_timestamps(dataset):
        counts[ts.date()] += 1
    return counts


def workflow_session_counts(skills: list[SkillEvent]) -> tuple[int, Counter[str]]:
    by_session: dict[str, set[str]] = defaultdict(set)
    for event in skills:
        if not event.session_id:
            continue
        by_session[event.session_id]
        step = event.workflow_step or SKILL_STEP_ALIASES.get(event.skill)
        if step in WORKFLOW_STEPS:
            by_session[event.session_id].add(step)

    counts: Counter[str] = Counter()
    for steps in by_session.values():
        counts.update(steps)
    return len(by_session), counts


def render_bar_chart(title: str, counts: Counter[str], *, width: int = 36, limit: int = 8) -> str:
    if not counts:
        return f"{title}\n\nNo data yet."
    max_count = max(counts.values())
    rows = [title, ""]
    for name, count in counts.most_common(limit):
        filled = max(1, round((count / max_count) * width))
        bar = "█" * filled
        rows.append(f"{name[:28]:28} {bar:<{width}} {count}")
    return "\n".join(rows)


def render_hourly_line_chart(counts: Counter[int], *, height: int = 6) -> str:
    values = [counts.get(hour, 0) for hour in range(24)]
    max_value = max(values, default=0)
    if max_value == 0:
        return "Activity by hour\n\nNo activity yet."

    rows = ["Activity by hour", ""]
    for level in range(height, 0, -1):
        threshold = max_value * level / height
        label = f"{round(threshold):>3} ┤"
        cells = ["●" if value >= threshold and value > 0 else " " for value in values]
        rows.append(label + "".join(cells))
    rows.append("    └" + "─" * 24)
    rows.append("     00    06    12    18   23")

    peak = max(range(24), key=lambda hour: values[hour])
    rows.append(f"\nPeak: {peak:02d}:00 with {values[peak]} event(s)")
    return "\n".join(rows)


def render_activity_heatmap(counts: Counter[date], *, today: date | None = None, weeks: int = 26) -> str:
    today = today or date.today()
    start = today - timedelta(days=(weeks * 7) - 1)
    start -= timedelta(days=start.weekday())
    days = [start + timedelta(days=offset) for offset in range((weeks + 1) * 7)]
    max_count = max((counts.get(day, 0) for day in days), default=0)

    rows = [f"Activity heatmap ({weeks} weeks)", ""]
    rows.append("      " + _month_labels(days))
    for weekday, label in enumerate(("Mon", "", "Wed", "", "Fri", "", "")):
        cells = []
        for week in range(weeks + 1):
            day = days[week * 7 + weekday]
            cells.append(_heat_cell(counts.get(day, 0), max_count))
        rows.append(f"{label:>3}   " + " ".join(cells))
    rows.append("")
    rows.append("      Less ░ ▒ ▓ █ More")
    return "\n".join(rows)


def render_workflow_compliance(total_sessions: int, counts: Counter[str]) -> str:
    rows = ["Workflow compliance by session", ""]
    if total_sessions == 0:
        rows.append("No skill session data yet. Run AW skills after tracking is enabled to populate docs/metrics/skills*.jsonl.")
        return "\n".join(rows)
    for step in WORKFLOW_STEPS:
        count = counts.get(step, 0)
        pct = round((count / total_sessions) * 100)
        rows.append(f"{step[:28]:28} {count:>3}/{total_sessions:<3} {pct:>3}%")
    return "\n".join(rows)


def run(args: argparse.Namespace) -> int:
    try:
        MetricsApp = _build_metrics_app()
    except ModuleNotFoundError as exc:
        if exc.name == "textual":
            print('Textual is required for aw metrics. Install with: python3 -m pip install -e ".[dev]"')
            return 1
        raise
    MetricsApp(args.repo.expanduser().resolve()).run()
    return 0


def _read_jsonl(metrics_dir: Path, pattern: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if not metrics_dir.is_dir():
        return rows
    for path in sorted(metrics_dir.glob(pattern)):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _all_timestamps(dataset: MetricsDataset) -> list[datetime]:
    return [event.ts for event in dataset.events + dataset.skills if event.ts is not None]


def _month_labels(days: list[date]) -> str:
    labels: list[str] = []
    last_month = None
    for index in range(0, len(days), 7):
        day = days[index]
        if day.month != last_month:
            labels.append(day.strftime("%b").ljust(4))
            last_month = day.month
        else:
            labels.append("  ")
    return " ".join(labels)


def _heat_cell(count: int, max_count: int) -> str:
    if count <= 0 or max_count <= 0:
        return "░"
    ratio = count / max_count
    if ratio < 0.34:
        return "▒"
    if ratio < 0.67:
        return "▓"
    return "█"


def _build_metrics_app():
    from textual.app import App, ComposeResult
    from textual.containers import Grid
    from textual.widgets import Footer, Header, Label, Static

    class ChartPanel(Static):
        def __init__(self, content: str, **kwargs: object) -> None:
            super().__init__(content, **kwargs)

    class MetricsApp(App[None]):
        CSS = """
        Screen {
            layout: vertical;
        }

        #summary {
            height: 3;
            content-align: center middle;
            text-style: bold;
        }

        #dashboard {
            grid-size: 2 3;
            grid-rows: 1fr 1fr 1fr;
            grid-columns: 1fr 1fr;
            height: 1fr;
        }

        .panel {
            border: solid $accent;
            padding: 1 2;
            height: 100%;
        }

        #heatmap {
            column-span: 2;
        }

        """

        BINDINGS = [("q", "quit", "Quit")]

        def __init__(self, repo: Path) -> None:
            super().__init__()
            self.repo = repo
            self.dataset = load_dataset(repo / "docs" / "metrics")

        def compose(self) -> ComposeResult:
            sessions, compliance = workflow_session_counts(self.dataset.skills)
            yield Header(show_clock=True)
            yield Label(self._summary(sessions), id="summary")
            with Grid(id="dashboard"):
                yield ChartPanel(render_hourly_line_chart(hourly_activity(self.dataset)), classes="panel")
                yield ChartPanel(render_bar_chart("Gate events", event_counts(self.dataset.events)), classes="panel")
                yield ChartPanel(render_bar_chart("Skill usage", skill_counts(self.dataset.skills)), classes="panel")
                yield ChartPanel(render_workflow_compliance(sessions, compliance), classes="panel")
                yield ChartPanel(render_activity_heatmap(daily_activity(self.dataset)), id="heatmap", classes="panel")
            yield Footer()

        def _summary(self, sessions: int) -> str:
            timestamps = _all_timestamps(self.dataset)
            if not timestamps:
                return f"No metrics found in {self.repo / 'docs' / 'metrics'}"
            return (
                f"{len(self.dataset.events)} gate events, {len(self.dataset.skills)} skill events, "
                f"{sessions} tracked session(s) from {min(timestamps).date()} to {max(timestamps).date()}"
            )

    return MetricsApp
