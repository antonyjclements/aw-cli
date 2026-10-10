from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from aw_cli.cli import main
from aw_cli.commands.init_repo import ARTIFACTS, GENERATED
from test_cli import make_source


class UpgradeTests(unittest.TestCase):
    def upgrade(self, source: Path, repo: Path) -> int:
        with redirect_stdout(io.StringIO()), mock.patch(
            "builtins.input", side_effect=AssertionError("upgrade must not prompt")
        ):
            return main(["upgrade", "--source", str(source), "--repo", str(repo)])

    def test_upgrade_adds_missing_files_and_preserves_existing_customizations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            preserved = {
                "CLAUDE.md": b"custom instructions\n",
                "docs/features/index.yml": b"features: [existing]\n",
                ".claude/settings.json": b'{"custom": true}\n',
                ".claude/hooks/log-session.sh": b"custom hook\n",
                ".gitignore": b"custom-ignore\n",
                ".gitattributes": b"custom-attributes\n",
            }
            for relative, content in preserved.items():
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

            self.assertEqual(self.upgrade(source, repo), 0)

            for relative in ARTIFACTS | GENERATED:
                self.assertTrue((repo / relative).is_file(), relative)
            for relative, content in preserved.items():
                self.assertEqual((repo / relative).read_bytes(), content, relative)
            self.assertFalse((repo / "docs/workflow/config.yml.bak").exists())

    def test_upgrade_replaces_selected_files_and_keeps_successive_config_backups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            for relative in ("AGENTS.md", ".scripts/aw-gate.js", ".augmented-workflow-version", "docs/workflow/config.yml"):
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"old\r\n")
            config = repo / "docs/workflow/config.yml"
            backup = config.with_name("config.yml.bak")
            backup.write_bytes(b"earlier backup\n")

            self.assertEqual(self.upgrade(source, repo), 0)

            self.assertEqual(backup.read_bytes(), b"earlier backup\n")
            self.assertEqual(config.with_name("config.yml.bak.1").read_bytes(), b"old\r\n")
            self.assertIn("AUGMENTED_WORKFLOW_VERSION=1.2.3", (repo / "AGENTS.md").read_text())
            self.assertEqual((repo / ".augmented-workflow-version").read_text(), "1.2.3\n")
            gate = repo / ".scripts/aw-gate.js"
            self.assertEqual(gate.read_text(), "aw-gate.js\n")
            self.assertTrue(gate.stat().st_mode & 0o111)
            self.assertIn("tracking:\n  enabled: true", config.read_text())
            modified = config.stat().st_mtime_ns

            self.assertEqual(self.upgrade(source, repo), 0)
            self.assertEqual(config.stat().st_mtime_ns, modified)
            self.assertFalse(config.with_name("config.yml.bak.2").exists())

            config.write_text("another custom config\n")
            self.assertEqual(self.upgrade(source, repo), 0)
            self.assertEqual(config.with_name("config.yml.bak.2").read_text(), "another custom config\n")

    def test_upgrade_creates_optional_hook_settings_and_preserves_directory_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            (repo / "AGENTS.md").mkdir(parents=True)

            self.assertEqual(self.upgrade(source, repo), 0)

            self.assertTrue((repo / "AGENTS.md").is_dir())
            self.assertTrue((repo / ".claude/settings.json").is_file())
            self.assertTrue((repo / ".claude/hooks/log-session.sh").stat().st_mode & 0o111)
            self.assertIn(".aw/session", (repo / ".gitignore").read_text())

    def test_upgrade_reports_missing_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(self.upgrade(root / "missing", root / "repo"), 1)

    def test_upgrade_reports_writes_backups_and_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            config = repo / "docs/workflow/config.yml"
            config.parent.mkdir(parents=True)
            config.write_text("custom\n")
            stdout = io.StringIO()

            with redirect_stdout(stdout), mock.patch("builtins.input") as prompt:
                self.assertEqual(main(["upgrade", "--source", str(source), "--repo", str(repo)]), 0)

            prompt.assert_not_called()
            self.assertIn("write: .scripts/aw-gate.js", stdout.getvalue())
            self.assertIn("backup: docs/workflow/config.yml.bak", stdout.getvalue())
            self.assertIn(f"Upgraded AW repository: {repo.resolve()}", stdout.getvalue())

    def test_upgrade_does_not_replace_config_when_backup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            config = repo / "docs/workflow/config.yml"
            config.parent.mkdir(parents=True)
            config.write_text("custom\n")
            original_open = Path.open

            def fail_backup(path: Path, *args, **kwargs):
                if path.name == "config.yml.bak":
                    raise PermissionError("backup denied")
                return original_open(path, *args, **kwargs)

            with mock.patch.object(Path, "open", fail_backup):
                self.assertEqual(self.upgrade(source, repo), 1)
            self.assertEqual(config.read_text(), "custom\n")
