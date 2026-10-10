from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from aw_cli.cli import main
from aw_cli.commands.init_repo import ARTIFACTS, GENERATED
from test_cli import make_source


RUBY = shutil.which("ruby")
REQUIRES_RUBY = unittest.skipUnless(RUBY, "Ruby is required for the official config migrator")


def write(repo: Path, relative: str, content: bytes) -> Path:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def snapshot(repo: Path) -> dict[str, bytes]:
    return {str(path.relative_to(repo)): path.read_bytes() for path in repo.rglob("*") if path.is_file()}


def recognize(source: Path, relative: str, content: bytes, *, historical: bool = False) -> None:
    manifest = source / "skills/aw-init/scripts/bundled-skill-fingerprints.json"
    data = json.loads(manifest.read_text())
    digest = hashlib.sha256(content).hexdigest()
    if historical:
        data.setdefault("repo_file_history", {})[relative] = [digest]
    else:
        data.setdefault("repo_files", {})[relative] = digest
    manifest.write_text(json.dumps(data))


def read_config(path: Path) -> dict:
    result = subprocess.run(
        [RUBY, "-rjson", "-ryaml", "-e", "puts JSON.generate(YAML.load_file(ARGV[0]))", str(path)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


class UpgradeTests(unittest.TestCase):
    def upgrade(self, source: Path, repo: Path, *options: str) -> int:
        self.stdout = io.StringIO()
        with redirect_stdout(self.stdout), mock.patch(
            "builtins.input", side_effect=AssertionError("upgrade must not prompt")
        ):
            return main(["upgrade", "--source", str(source), "--repo", str(repo), *options])

    def test_upgrade_adds_missing_files_and_preserves_existing_customizations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            preserved = {
                "AGENTS.md": b"custom routing\r\n",
                "CLAUDE.md": b"custom instructions\n",
                "docs/workflow/README.md": b"custom workflow docs\n",
                "docs/features/index.yml": b"features: [existing]\n",
                ".claude/settings.json": b'{"custom": true}\n',
                ".claude/hooks/log-session.sh": b"custom hook\n",
                ".gitignore": b"custom-ignore\n",
                ".gitattributes": b"custom-attributes\n",
            }
            for relative, content in preserved.items():
                write(repo, relative, content)

            self.assertEqual(self.upgrade(source, repo), 0, self.stdout.getvalue())

            for relative in ARTIFACTS | GENERATED:
                self.assertTrue((repo / relative).is_file(), relative)
            for relative, content in preserved.items():
                self.assertEqual((repo / relative).read_bytes(), content, relative)
            self.assertFalse((repo / "docs/workflow/config.yml.bak").exists())
            self.assertIn("preserve: AGENTS.md", self.stdout.getvalue())
            self.assertIn("write: .scripts/aw-gate.js", self.stdout.getvalue())

    def test_upgrade_refreshes_known_files_with_exact_backups(self) -> None:
        for historical in (False, True):
            with self.subTest(historical=historical), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = make_source(root)
                repo = root / "repo"
                old = b"known old bytes\r\n"
                for relative in ("AGENTS.md", "CLAUDE.md", ".scripts/aw-gate.js", "docs/workflow/README.md"):
                    write(repo, relative, old)
                    recognize(source, relative, old, historical=historical)
                write(repo, "AGENTS.md.bak", b"earlier backup\n")

                self.assertEqual(self.upgrade(source, repo), 0, self.stdout.getvalue())

                self.assertEqual((repo / "AGENTS.md.bak").read_bytes(), b"earlier backup\n")
                self.assertEqual((repo / "AGENTS.md.bak.1").read_bytes(), old)
                self.assertIn("AUGMENTED_WORKFLOW_VERSION=1.2.3", (repo / "AGENTS.md").read_text())
                for relative in ("CLAUDE.md", ".scripts/aw-gate.js", "docs/workflow/README.md"):
                    self.assertEqual((repo / f"{relative}.bak").read_bytes(), old)
                    self.assertNotEqual((repo / relative).read_bytes(), old)
                self.assertTrue((repo / ".scripts/aw-gate.js").stat().st_mode & 0o111)

    def test_customized_gate_blocks_all_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            write(repo, ".scripts/aw-gate.js", b"custom gate\n")
            before = snapshot(repo)
            self.assertEqual(self.upgrade(source, repo), 1)
            self.assertEqual(snapshot(repo), before)
            self.assertIn("aw-gate.js", self.stdout.getvalue())

    def test_upgrade_dry_run_does_not_create_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            self.assertEqual(self.upgrade(source, repo, "--dry-run"), 0)
            self.assertFalse(repo.exists())
            self.assertIn(".scripts/aw-gate.js", self.stdout.getvalue())

    def test_missing_or_incomplete_source_fails_before_repository_writes(self) -> None:
        for missing in ("skills/aw-init/scripts/migrate-skills.py", "skills/aw-init/scripts/bundled-skill-fingerprints.json", "skills/aw-init/scripts/upgrade-config.rb", "skills/aw-init/artifacts/field-guide.md"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = make_source(root)
                (source / missing).unlink()
                repo = root / "repo"
                self.assertEqual(self.upgrade(source, repo), 1)
                self.assertFalse(repo.exists())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(self.upgrade(root / "missing", root / "repo"), 1)
            self.assertFalse((root / "repo").exists())

    def test_target_and_ancestor_symlinks_fail_closed(self) -> None:
        for relative in ("AGENTS.md", "docs", ".scripts", ".augmented-workflow-repo.json"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = make_source(root)
                repo = root / "repo"
                repo.mkdir()
                outside = root / "outside"
                if relative in ("docs", ".scripts"):
                    outside.mkdir()
                    write(outside, "sentinel", b"untouched")
                else:
                    outside.write_bytes(b"untouched")
                target = repo / relative
                target.symlink_to(outside, target_is_directory=outside.is_dir())
                before = snapshot(repo)
                self.assertEqual(self.upgrade(source, repo), 1)
                self.assertEqual(snapshot(repo), before)
                self.assertTrue(target.is_symlink())
                self.assertEqual((outside / "sentinel" if outside.is_dir() else outside).read_bytes(), b"untouched")

    def test_missing_ruby_blocks_existing_config_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            write(repo, "docs/workflow/config.yml", b"telemetry:\n  enabled: false\n")
            before = snapshot(repo)
            with mock.patch("shutil.which", return_value=None):
                self.assertEqual(self.upgrade(source, repo), 1)
            self.assertEqual(snapshot(repo), before)
            self.assertIn("ruby", self.stdout.getvalue().lower())

    @REQUIRES_RUBY
    def test_config_migration_preserves_custom_values_and_moves_legacy_routing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            original = (
                b"custom:\n  project: kept\n"
                b"ticket_creation:\n  skill: custom-ticket\n"
                b"git:\n  commit:\n    skill: custom-commit\n"
                b"post_pr:\n  ci_monitor:\n    provider: circleci\n"
                b"telemetry:\n  enabled: false\n"
                b"tracking:\n  enabled: false\n"
                b"gates:\n  enabled: false\n"
            )
            config = write(repo, "docs/workflow/config.yml", original)
            self.assertEqual(self.upgrade(source, repo), 0, self.stdout.getvalue())
            data = read_config(config)
            self.assertEqual(data["custom"], {"project": "kept"})
            self.assertEqual(data["post_pr"]["ci_monitor"]["provider"], "circleci")
            for key in ("gates", "tracking", "telemetry"):
                self.assertIs(data[key]["enabled"], False)
            self.assertEqual(data["workflow"]["steps"]["create_tickets"]["skill"], "custom-ticket")
            self.assertEqual(data["workflow"]["steps"]["commit"]["skill"], "custom-commit")
            self.assertNotIn("ticket_creation", data)
            self.assertEqual(config.with_name("config.yml.bak").read_bytes(), original)
            self.assertIn("backup: docs/workflow/config.yml.bak", self.stdout.getvalue())

    @REQUIRES_RUBY
    def test_config_conflict_and_invalid_yaml_fail_before_all_writes(self) -> None:
        for content in (
            b"workflow:\n  steps:\n    create_tickets:\n      skill: current\nticket_creation:\n  skill: conflicting\n",
            b"workflow: [invalid YAML\n",
        ):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = make_source(root)
                repo = root / "repo"
                write(repo, "docs/workflow/config.yml", content)
                before = snapshot(repo)
                self.assertEqual(self.upgrade(source, repo), 1)
                self.assertEqual(snapshot(repo), before)

    @REQUIRES_RUBY
    def test_existing_config_dry_run_and_repeated_upgrade_do_not_mutate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            write(repo, "docs/workflow/config.yml", b"telemetry:\n  enabled: false\n")
            before = snapshot(repo)
            self.assertEqual(self.upgrade(source, repo, "--dry-run"), 0)
            self.assertEqual(snapshot(repo), before)
            self.assertEqual(self.upgrade(source, repo), 0, self.stdout.getvalue())
            before = snapshot(repo)
            mtimes = {path: path.stat().st_mtime_ns for path in repo.rglob("*") if path.is_file()}
            self.assertEqual(self.upgrade(source, repo), 0, self.stdout.getvalue())
            self.assertEqual(snapshot(repo), before)
            self.assertEqual({path: path.stat().st_mtime_ns for path in mtimes}, mtimes)

    @REQUIRES_RUBY
    def test_previous_cli_manifest_allows_refresh_but_does_not_own_user_edits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            self.assertEqual(self.upgrade(source, repo), 0)
            self.assertTrue((repo / ".augmented-workflow-repo.json").is_file())
            old_gate = (repo / ".scripts/aw-gate.js").read_bytes()
            (source / "skills/aw-init/artifacts/aw-gate.js").write_bytes(b"new gate\n")
            self.assertEqual(self.upgrade(source, repo), 0, self.stdout.getvalue())
            self.assertEqual((repo / ".scripts/aw-gate.js.bak").read_bytes(), old_gate)
            self.assertEqual((repo / ".scripts/aw-gate.js").read_bytes(), b"new gate\n")
            (repo / ".scripts/aw-gate.js").write_bytes(b"local gate edit\n")
            before = snapshot(repo)
            self.assertEqual(self.upgrade(source, repo), 1)
            self.assertEqual(snapshot(repo), before)

    @REQUIRES_RUBY
    def test_upgrade_does_not_replace_config_when_backup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            config = write(repo, "docs/workflow/config.yml", b"custom: kept\n")
            original_open = Path.open

            def fail_backup(path: Path, *args, **kwargs):
                if path == config.with_name("config.yml.bak"):
                    raise PermissionError("backup denied")
                return original_open(path, *args, **kwargs)

            before = snapshot(repo)
            with mock.patch.object(Path, "open", fail_backup):
                self.assertEqual(self.upgrade(source, repo), 1)
            self.assertEqual(snapshot(repo), before)

    def test_failed_write_restores_prior_files_and_removes_new_files(self) -> None:
        from aw_cli.repo_upgrade import atomic_write

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            original = b"known old AGENTS\r\n"
            agents = write(repo, "AGENTS.md", original)
            agents.chmod(0o640)
            recognize(source, "AGENTS.md", original)
            writes = []

            def fail_config(path: Path, content: bytes, mode: int) -> None:
                writes.append(path)
                if path == repo / "docs/workflow/config.yml":
                    raise PermissionError("write denied")
                atomic_write(path, content, mode)

            with mock.patch("aw_cli.repo_upgrade.atomic_write", side_effect=fail_config):
                self.assertEqual(self.upgrade(source, repo), 1)

            self.assertIn(repo / "CLAUDE.md", writes)
            self.assertEqual(agents.read_bytes(), original)
            self.assertEqual(agents.stat().st_mode & 0o777, 0o640)
            self.assertEqual(snapshot(repo), {"AGENTS.md": original, "AGENTS.md.bak": original})

    def test_symlink_repository_root_fails_without_touching_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            outside = root / "outside"
            write(outside, "sentinel", b"untouched")
            repo = root / "repo"
            repo.symlink_to(outside, target_is_directory=True)
            self.assertEqual(self.upgrade(source, repo), 1)
            self.assertEqual(snapshot(outside), {"sentinel": b"untouched"})

    def test_fresh_repo_needs_no_ruby_and_gets_cli_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            with mock.patch("shutil.which", return_value=None):
                self.assertEqual(self.upgrade(source, repo), 0, self.stdout.getvalue())
            config = (repo / "docs/workflow/config.yml").read_text()
            for key in ("gates", "tracking", "telemetry"):
                self.assertIn(f"{key}:\n  enabled: true", config)

    def test_upgrade_preserves_noncritical_directory_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            (repo / "AGENTS.md").mkdir(parents=True)
            self.assertEqual(self.upgrade(source, repo), 0, self.stdout.getvalue())
            self.assertTrue((repo / "AGENTS.md").is_dir())
            self.assertTrue((repo / ".claude/settings.json").is_file())
            self.assertTrue((repo / ".claude/hooks/log-session.sh").stat().st_mode & 0o111)

    def test_concurrent_edits_during_config_migration_abort_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            repo = root / "repo"
            old_agents = b"known original routing\n"
            agents = write(repo, "AGENTS.md", old_agents)
            recognize(source, "AGENTS.md", old_agents)
            config = write(repo, "docs/workflow/config.yml", b"custom: original\n")
            edited_agents = b"user edited routing during migration\n"
            edited_config = b"custom: concurrent-edit\n"

            def migrate_while_user_edits(*args) -> bytes:
                agents.write_bytes(edited_agents)
                config.write_bytes(edited_config)
                return b"custom: original\nworkflow: {}\n"

            with mock.patch("aw_cli.repo_upgrade.migrated_config", side_effect=migrate_while_user_edits):
                self.assertEqual(self.upgrade(source, repo), 1)

            self.assertEqual(snapshot(repo), {
                "AGENTS.md": edited_agents,
                "docs/workflow/config.yml": edited_config,
            })
            self.assertIn("changed during preflight", self.stdout.getvalue())

    def test_failed_upgrade_rollback_preserves_concurrently_edited_new_file(self) -> None:
        from aw_cli.repo_upgrade import atomic_write

        for edit_mode in (False, True):
            with self.subTest(edit_mode=edit_mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = make_source(root)
                repo = root / "repo"
                agents = repo / "AGENTS.md"
                edited_content = b"user edit after upgrade wrote AGENTS\n"
                written_agents = None

                def fail_after_concurrent_edit(path: Path, content: bytes, mode: int) -> None:
                    nonlocal written_agents
                    if path == repo / "CLAUDE.md":
                        if edit_mode:
                            agents.chmod(0o600)
                        else:
                            agents.write_bytes(edited_content)
                        raise PermissionError("next write denied")
                    atomic_write(path, content, mode)
                    if path == agents:
                        written_agents = content

                with mock.patch("aw_cli.repo_upgrade.atomic_write", side_effect=fail_after_concurrent_edit):
                    self.assertEqual(self.upgrade(source, repo), 1)

                self.assertIsNotNone(written_agents)
                self.assertEqual(snapshot(repo), {"AGENTS.md": written_agents if edit_mode else edited_content})
                if edit_mode:
                    self.assertEqual(agents.stat().st_mode & 0o777, 0o600)
                self.assertIn("recovery preserved concurrent edits", self.stdout.getvalue())
                self.assertIn("AGENTS.md", self.stdout.getvalue())
