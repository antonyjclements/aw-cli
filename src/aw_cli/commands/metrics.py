from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class MetricEvent:
    ts: datetime | None
    event: str
    detail: str | None
    source: str | None


def load_events(metrics_dir: Path) -> list[MetricEvent]:
    events: list[MetricEvent] = []
    if not metrics_dir.is_dir():
        return events
    for path in sorted(metrics_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(
                MetricEvent(
                    ts=_parse_ts(payload.get("ts")),
                    event=str(payload.get("event") or "unknown"),
                    detail=payload.get("detail"),
                    source=payload.get("source"),
                )
            )
    return events


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


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _build_metrics_app():
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.widgets import DataTable, Footer, Header, Label, Static

    class BarChart(Static):
        def __init__(self, title: str, counts: Counter[str]) -> None:
            super().__init__()
            self.title = title
            self.counts = counts

        def render(self) -> str:
            if not self.counts:
                return f"{self.title}\n\nNo data."
            max_count = max(self.counts.values())
            rows = [self.title, ""]
            for name, count in self.counts.most_common(10):
                width = max(1, round((count / max_count) * 32))
                rows.append(f"{name[:24]:24} {'#' * width} {count}")
            return "\n".join(rows)

    class MetricsApp(App[None]):
        CSS = """
        Screen {
            layout: vertical;
        }

        #summary {
            height: 3;
            content-align: center middle;
        }

        .panel {
            border: solid $accent;
            height: 1fr;
            padding: 1;
        }

        DataTable {
            height: 1fr;
        }
        """

        BINDINGS = [("q", "quit", "Quit")]

        def __init__(self, repo: Path) -> None:
            super().__init__()
            self.repo = repo
            self.events = load_events(repo / "docs" / "metrics")

        def compose(self) -> ComposeResult:
            event_counts = Counter(event.event for event in self.events)
            source_counts = Counter(event.source or "unknown" for event in self.events)
            yield Header(show_clock=True)
            yield Label(self._summary(), id="summary")
            with Horizontal():
                yield BarChart("Events", event_counts, classes="panel")
                yield BarChart("Sources", source_counts, classes="panel")
            with Vertical(classes="panel"):
                table = DataTable()
                table.add_columns("Timestamp", "Event", "Detail", "Source")
                for event in sorted(self.events, key=lambda item: item.ts or datetime.min, reverse=True)[:200]:
                    table.add_row(
                        event.ts.isoformat() if event.ts else "",
                        event.event,
                        event.detail or "",
                        event.source or "",
                    )
                yield table
            yield Footer()

        def _summary(self) -> str:
            if not self.events:
                return f"No metrics found in {self.repo / 'docs' / 'metrics'}"
            timestamps = [event.ts for event in self.events if event.ts]
            if not timestamps:
                return f"{len(self.events)} events"
            return f"{len(self.events)} events from {min(timestamps).date()} to {max(timestamps).date()}"

    return MetricsApp
