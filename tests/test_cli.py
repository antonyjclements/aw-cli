from __future__ import annotations

import argparse
import importlib.util
import io
import json
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from aw_cli.cli import main
from aw_cli import __version__
from aw_cli.config import DEFAULT_SOURCE_URL
from aw_cli.commands.init_repo import run as init_run
from aw_cli.commands.doctor import run as doctor_run
from aw_cli.commands.metrics import (
    MetricsDataset,
    MetricEvent,
    SkillEvent,
    _build_metrics_app,
    daily_activity,
    hourly_activity,
    load_dataset,
    load_events,
    load_skill_events,
    render_activity_heatmap,
    render_hourly_line_chart,
    render_workflow_compliance,
    workflow_session_counts,
)
from aw_cli.commands.status import run as status_run
from aw_cli.installer import install_aw_skills
from aw_cli.workflow_config import enable_default_aw_features


def make_source(tmp_path: Path) -> Path:
    source = tmp_path / "agentic-workflow"
    skills = source / "skills"
    for name in ("aw-work", "aw-init"):
        skill_dir = skills / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
    (source / "aw-version.txt").write_text("1.2.3\n", encoding="utf-8")
    artifacts = skills / "aw-init" / "artifacts"
    artifacts.mkdir()
    for name in (
        "AGENTS.md",
        "CLAUDE.md",
        "prd-template.md",
        "coding-approach.md",
        "traceability.md",
        "behavior-pinning.md",
        "e2e-coverage.md",
        "solutions-readme.md",
        "workflow-readme.md",
        "field-guide.md",
        "gates.md",
        "org-knowledge.md",
        "tracking.md",
        "metrics-readme.md",
        "aw-gate.js",
        "config.yml",
    ):
        (artifacts / name).write_text(f"{name}\n", encoding="utf-8")
    (artifacts / "AGENTS.md").write_text("AUGMENTED_WORKFLOW_VERSION=old\n", encoding="utf-8")
    (artifacts / "config.yml").write_text(
        "workflow:\n"
        "  implementation:\n"
        "    test_policy: acceptance-first\n"
        "  steps:\n"
        "    work:\n"
        "      skill: \"\"\n"
        "telemetry:\n"
        "  enabled: false\n",
        encoding="utf-8",
    )
    hooks = skills / "aw-init" / "hooks"
    hooks.mkdir()
    (hooks / "log-session.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    return source


class CliTests(unittest.TestCase):
    def test_install_aw_skills_copies_skills_and_links_agent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = make_source(tmp_path)
            skills_dir = tmp_path / "home" / ".agents" / "skills"
            claude_link = tmp_path / "home" / ".claude" / "skills"

            result = install_aw_skills(source, skills_dir, [claude_link])

            self.assertEqual(result.skill_names, ["aw-init", "aw-work"])
            self.assertTrue((skills_dir / "aw-init" / "SKILL.md").is_file())
            self.assertEqual((skills_dir / "aw-version.txt").read_text(encoding="utf-8"), "1.2.3\n")
            self.assertTrue(claude_link.is_symlink())
            self.assertEqual(claude_link.resolve(), skills_dir.resolve())

    def test_cli_install_supports_dry_run_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = make_source(tmp_path)
            skills_dir = tmp_path / "skills"
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["install", "--source", str(source), "--skills-dir", str(skills_dir), "--dry-run"])

            self.assertEqual(exit_code, 0)
            self.assertFalse(skills_dir.exists())
            self.assertIn("Would install 2 AW skills", stdout.getvalue())

    def test_load_events_reads_jsonl_shards_and_skips_bad_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            metrics_dir = tmp_path / "docs" / "metrics"
            metrics_dir.mkdir(parents=True)
            payload = {"ts": "2026-08-13T00:35:35.295Z", "event": "review", "detail": "code", "source": "aw-gate"}
            (metrics_dir / "events-2026-08.jsonl").write_text(json.dumps(payload) + "\nnot-json\n", encoding="utf-8")

            events = load_events(metrics_dir)

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event, "review")
            self.assertEqual(events[0].detail, "code")

    def test_load_dataset_separates_gate_events_from_skill_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            metrics_dir = tmp_path / "docs" / "metrics"
            metrics_dir.mkdir(parents=True)
            gate = {"ts": "2026-08-13T02:35:00.000Z", "event": "review", "detail": "code", "source": "aw-gate"}
            skill = {
                "ts": "2026-08-13T03:10:00.000Z",
                "session_id": "session-1",
                "skill": "aw-review",
                "workflow_step": "review",
                "source": "skill",
            }
            (metrics_dir / "events-2026-08.jsonl").write_text(json.dumps(gate) + "\n", encoding="utf-8")
            (metrics_dir / "skills-2026-08.jsonl").write_text(json.dumps(skill) + "\n", encoding="utf-8")

            dataset = load_dataset(metrics_dir)

            self.assertEqual(len(dataset.events), 1)
            self.assertEqual(len(dataset.skills), 1)
            self.assertEqual(load_skill_events(metrics_dir)[0].session_id, "session-1")

    def test_activity_charts_include_hourly_and_daily_counts(self) -> None:
        first = datetime.fromisoformat("2026-08-13T02:10:00+00:00")
        second = datetime.fromisoformat("2026-08-13T14:10:00+00:00")
        dataset = MetricsDataset(
            events=[MetricEvent(first, "review", "code", "aw-gate")],
            skills=[
                SkillEvent(second, "session-1", "aw-review", "review", "skill"),
                SkillEvent(second, "session-1", "aw-capture", "capture", "skill"),
            ],
        )

        self.assertEqual(hourly_activity(dataset), Counter({14: 2, 2: 1}))
        self.assertEqual(daily_activity(dataset), Counter({date(2026, 8, 13): 3}))

    def test_renderers_show_hourly_heatmap_and_session_compliance(self) -> None:
        skills = [
            SkillEvent(None, "s1", "aw-review", "review", "skill"),
            SkillEvent(None, "s1", "aw-capture", "capture", "skill"),
            SkillEvent(None, "s2", "aw-review", "review", "skill"),
            SkillEvent(None, "s2", "aw-check-workflow-compliance", "check_workflow_compliance", "skill"),
            SkillEvent(None, "s3", "aw-work", "work", "skill"),
        ]
        total, counts = workflow_session_counts(skills)

        self.assertEqual(total, 3)
        self.assertIn("review", render_workflow_compliance(total, counts))
        self.assertIn("2/3", render_workflow_compliance(total, counts))
        self.assertIn("Activity by hour", render_hourly_line_chart(Counter({2: 3, 14: 1})))
        self.assertIn("Peak: 02:00", render_hourly_line_chart(Counter({2: 3, 14: 1})))
        self.assertIn("Activity heatmap", render_activity_heatmap(Counter({date(2026, 8, 13): 4}), today=date(2026, 8, 13), weeks=2))

    def test_metrics_app_compose_accepts_widget_classes(self) -> None:
        if importlib.util.find_spec("textual") is None or importlib.util.find_spec("textual_plot") is None:
            self.skipTest("textual and textual-plot are not installed")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            metrics_dir = tmp_path / "docs" / "metrics"
            metrics_dir.mkdir(parents=True)
            payload = {"ts": "2026-08-13T00:35:35.295Z", "event": "review", "detail": "code", "source": "aw-gate"}
            (metrics_dir / "events-2026-08.jsonl").write_text(json.dumps(payload) + "\n", encoding="utf-8")

            MetricsApp = _build_metrics_app()
            app = MetricsApp(tmp_path)

            widgets = list(app.compose())

            self.assertGreaterEqual(len(widgets), 7)

    def test_status_reports_missing_repo_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            args = argparse.Namespace(repo=tmp_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = status_run(args)

            self.assertEqual(exit_code, 1)
            output = stdout.getvalue()
            self.assertIn("AW Status", output)
            self.assertIn(f"CLI version: {__version__}", output)
            self.assertIn("AW version: missing", output)
            self.assertIn("missing: AGENTS.md", output)

    def test_doctor_reports_cli_and_installed_aw_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = make_source(tmp_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = doctor_run(
                    argparse.Namespace(source=source, source_url=None, skills_dir=tmp_path / "skills", agent_dir=[])
                )

            self.assertEqual(exit_code, 1)
            self.assertIn(f"CLI version: {__version__}", stdout.getvalue())
            self.assertIn("Installed AW version: missing", stdout.getvalue())

    def test_cli_version_flag_prints_package_version(self) -> None:
        stdout = io.StringIO()

        with self.assertRaises(SystemExit) as raised, redirect_stdout(stdout):
            main(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(stdout.getvalue(), f"aw {__version__}\n")

    def test_init_scaffolds_directly_and_enables_aw_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = make_source(tmp_path)
            args = argparse.Namespace(source=source, source_url=None, repo=tmp_path / "repo", force=False)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = init_run(args)

            self.assertEqual(exit_code, 0)
            self.assertTrue((tmp_path / "repo" / ".scripts" / "aw-gate.js").is_file())
            self.assertTrue((tmp_path / "repo" / ".claude" / "hooks" / "log-session.sh").is_file())
            config = tmp_path / "repo" / "docs" / "workflow" / "config.yml"
            config_text = config.read_text(encoding="utf-8")
            self.assertIn("  steps:\n    work:\n      skill: \"\"\n", config_text)
            self.assertIn("gates:\n  enabled: true\n", config_text)
            self.assertIn("tracking:\n  enabled: true\n", config_text)
            self.assertIn("telemetry:\n  enabled: true\n", config_text)
            self.assertIn("trace:\n  enabled: true\n", config_text)
            self.assertIn("pin:\n  enabled: true\n", config_text)
            self.assertIn("workflow_trace:\n  enabled: true\n", config_text)

    def test_init_prompts_for_each_changed_existing_file_and_force_skips_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = make_source(tmp_path)
            repo = tmp_path / "repo"
            repo.mkdir()
            agents = repo / "AGENTS.md"
            agents.write_text("custom\n", encoding="utf-8")

            with mock.patch("builtins.input", return_value="n") as prompt:
                self.assertEqual(init_run(argparse.Namespace(source=source, source_url=None, repo=repo, force=False)), 0)
            self.assertEqual(agents.read_text(encoding="utf-8"), "custom\n")
            prompt.assert_any_call("Overwrite existing AGENTS.md? [y/N] ")

            with mock.patch("builtins.input") as prompt:
                self.assertEqual(init_run(argparse.Namespace(source=source, source_url=None, repo=repo, force=True)), 0)
            self.assertIn("AUGMENTED_WORKFLOW_VERSION=1.2.3", agents.read_text(encoding="utf-8"))
            prompt.assert_not_called()

    def test_enable_default_aw_features_adds_missing_tracking_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.yml"
            config.write_text("telemetry:\n  enabled: false\n", encoding="utf-8")

            changed = enable_default_aw_features(config)

            self.assertTrue(changed)
            self.assertTrue(config.read_text(encoding="utf-8").startswith("tracking:\n  enabled: true\n"))

    def test_default_source_is_augmented_workflow_github_archive(self) -> None:
        self.assertEqual(
            DEFAULT_SOURCE_URL,
            "https://github.com/antonyjclements/augmented-workflow/archive/refs/heads/main.tar.gz",
        )


if __name__ == "__main__":
    unittest.main()
