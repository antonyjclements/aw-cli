from __future__ import annotations

import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from aw_cli.cli import main
from aw_cli.config import DEFAULT_SOURCE_URL
from aw_cli.commands.init_repo import run as init_run
from aw_cli.commands.metrics import load_events
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
            self.assertIn("missing: AGENTS.md", output)

    def test_init_enables_aw_defaults_after_successful_installer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = make_source(tmp_path)
            installer = source / "skills" / "aw-init" / "scripts"
            installer.mkdir(parents=True, exist_ok=True)
            (installer / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            config = tmp_path / "repo" / "docs" / "workflow" / "config.yml"
            config.parent.mkdir(parents=True)
            config.write_text(
                "telemetry:\n"
                "  enabled: false\n"
                "trace:\n"
                "  enabled: false\n"
                "pin:\n"
                "  enabled: false\n"
                "workflow_trace:\n"
                "  enabled: false\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(source=source, source_url=None, repo=tmp_path / "repo", force=False)
            stdout = io.StringIO()

            with mock.patch("subprocess.run", return_value=argparse.Namespace(returncode=0)) as subprocess_run:
                with redirect_stdout(stdout):
                    exit_code = init_run(args)

            self.assertEqual(exit_code, 0)
            subprocess_run.assert_called_once()
            command = subprocess_run.call_args.args[0]
            self.assertIn("--with-gates", command)
            self.assertIn("--skip-skills", command)
            self.assertNotIn("--remote", command)
            config_text = config.read_text(encoding="utf-8")
            self.assertIn("tracking:\n  enabled: true\n", config_text)
            self.assertIn("telemetry:\n  enabled: true\n", config_text)
            self.assertIn("trace:\n  enabled: true\n", config_text)
            self.assertIn("pin:\n  enabled: true\n", config_text)
            self.assertIn("workflow_trace:\n  enabled: true\n", config_text)

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
