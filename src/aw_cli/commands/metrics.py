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
HEATMAP_BG_COLORS = ("#161b22", "#0e4429", "#006d32", "#26a641", "#39d353")


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
    days = _heatmap_days(today, weeks)
    max_count = _heatmap_max_count(counts, days)

    rows = [_heatmap_title(weeks), ""]
    rows.append("      " + _month_labels(days))
    for weekday, label in enumerate(("Mon", "", "Wed", "", "Fri", "", "")):
        cells = []
        for week in range(weeks + 1):
            day = days[week * 7 + weekday]
            cells.append(_plain_heat_cell(counts.get(day, 0), max_count))
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
        if exc.name in {"textual", "textual_plot"}:
            print('Textual and textual-plot are required for aw metrics. Install with: python3 -m pip install -e ".[dev]"')
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
    level = _heat_level(count, max_count)
    return ("░", "▒", "▓", "█", "█")[level]


def _heat_level(count: int, max_count: int) -> int:
    if count <= 0 or max_count <= 0:
        return 0
    ratio = count / max_count
    if ratio < 0.25:
        return 1
    if ratio < 0.5:
        return 2
    if ratio < 0.75:
        return 3
    return 4


def _heat_style(count: int, max_count: int) -> str:
    return f"on {HEATMAP_BG_COLORS[_heat_level(count, max_count)]}"


def _heatmap_days(today: date, weeks: int) -> list[date]:
    start = today - timedelta(days=(weeks * 7) - 1)
    start -= timedelta(days=start.weekday())
    return [start + timedelta(days=offset) for offset in range((weeks + 1) * 7)]


def _heatmap_max_count(counts: Counter[date], days: list[date]) -> int:
    return max((counts.get(day, 0) for day in days), default=0)


def _heatmap_title(weeks: int) -> str:
    return f"Activity heatmap ({weeks} weeks)"


def _plain_heat_cell(count: int, max_count: int) -> str:
    level = _heat_level(count, max_count)
    if level == 0:
        return "░"
    if level == 1:
        return "▒"
    if level in {2, 3}:
        return "▓"
    return "█"


def _build_metrics_app():
    from textual.app import App, ComposeResult
    from textual.containers import Grid, Vertical
    from textual.widgets import Footer, Header, Label, Static
    from textual_plot import PlotWidget
    from rich.text import Text

    class ChartPanel(Static):
        def __init__(self, content: str, **kwargs: object) -> None:
            super().__init__(content, **kwargs)

    class HeatmapPanel(Static):
        def __init__(self, counts: Counter[date], weeks: int = 26, **kwargs: object) -> None:
            super().__init__(**kwargs)
            self.counts = counts
            self.weeks = weeks

        def render(self) -> Text:
            today = date.today()
            days = _heatmap_days(today, self.weeks)
            max_count = _heatmap_max_count(self.counts, days)
            text = Text()
            text.append(_heatmap_title(self.weeks), style="bold")
            text.append("\n\n")
            text.append("      " + _month_labels(days) + "\n", style="dim")
            for weekday, label in enumerate(("Mon", "", "Wed", "", "Fri", "", "")):
                text.append(f"{label:>3}   ", style="dim")
                for week in range(self.weeks + 1):
                    day = days[week * 7 + weekday]
                    text.append("  ", style=_heat_style(self.counts.get(day, 0), max_count))
                    text.append(" ")
                text.append("\n")
            text.append("\n      Less ", style="dim")
            for index, color in enumerate(HEATMAP_BG_COLORS):
                text.append("  ", style=f"on {color}")
                if index < len(HEATMAP_BG_COLORS) - 1:
                    text.append(" ")
            text.append(" More", style="dim")
            return text

    class PlotPanel(Vertical):
        def __init__(self, title: str, plot_id: str, **kwargs: object) -> None:
            super().__init__(**kwargs)
            self.title = title
            self.plot_id = plot_id

        def compose(self) -> ComposeResult:
            yield Label(self.title, classes="plot-title")
            yield PlotWidget(id=self.plot_id)

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

        PlotPanel {
            height: 100%;
        }

        PlotWidget {
            height: 1fr;
        }

        .plot-title {
            height: 1;
            text-style: bold;
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
                yield PlotPanel("Activity by hour", "hourly-plot", classes="panel")
                yield PlotPanel("Gate events", "gate-events-plot", classes="panel")
                yield PlotPanel("Skill usage", "skill-usage-plot", classes="panel")
                yield PlotPanel("Workflow compliance by session", "workflow-compliance-plot", classes="panel")
                yield HeatmapPanel(daily_activity(self.dataset), id="heatmap", classes="panel")
            yield Footer()

        def on_mount(self) -> None:
            self._plot_hourly_activity()
            self._plot_gate_events()
            self._plot_skill_usage()
            self._plot_workflow_compliance()

        def _summary(self, sessions: int) -> str:
            timestamps = _all_timestamps(self.dataset)
            if not timestamps:
                return f"No metrics found in {self.repo / 'docs' / 'metrics'}"
            return (
                f"{len(self.dataset.events)} gate events, {len(self.dataset.skills)} skill events, "
                f"{sessions} tracked session(s) from {min(timestamps).date()} to {max(timestamps).date()}"
            )

        def _plot_hourly_activity(self) -> None:
            counts = hourly_activity(self.dataset)
            plot = self.query_one("#hourly-plot", PlotWidget)
            plot.clear()
            x = list(range(24))
            y = [counts.get(hour, 0) for hour in x]
            plot.plot(x=x, y=y, line_style="bright_green", label="activity")
            plot.set_xlabel("Hour of day")
            plot.set_ylabel("Events")
            plot.set_xlimits(0, 23)
            plot.set_ylimits(ymin=0)

        def _plot_gate_events(self) -> None:
            self._plot_bar("#gate-events-plot", event_counts(self.dataset.events), "Gate", "Events")

        def _plot_skill_usage(self) -> None:
            self._plot_bar("#skill-usage-plot", skill_counts(self.dataset.skills), "Skill", "Invocations")

        def _plot_workflow_compliance(self) -> None:
            sessions, counts = workflow_session_counts(self.dataset.skills)
            percentages = Counter(
                {
                    step: round((counts.get(step, 0) / sessions) * 100) if sessions else 0
                    for step in WORKFLOW_STEPS
                }
            )
            self._plot_bar("#workflow-compliance-plot", percentages, "Workflow step", "% sessions")

        def _plot_bar(self, selector: str, counts: Counter[str], xlabel: str, ylabel: str) -> None:
            plot = self.query_one(selector, PlotWidget)
            plot.clear()
            labels = [name for name, _ in counts.most_common(8)]
            values = [counts[name] for name in labels]
            if not labels:
                labels = ["no data"]
                values = [0]
            plot.bar(labels, values, width=0.8, bar_style="bright_green", label=ylabel)
            plot.set_xlabel(xlabel)
            plot.set_ylabel(ylabel)
            plot.set_ylimits(ymin=0)

    return MetricsApp
