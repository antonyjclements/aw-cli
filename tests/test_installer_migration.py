from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from aw_cli.cli import main
from aw_cli.installer import install_aw_skills

FIXTURES = Path(__file__).parent / "fixtures" / "aw-migration"


def make_source(root: Path) -> Path:
    source = root / "source"
    for name in ("aw-init", "aw-work", "aw-spec", "aw-ship"):
        path = source / "skills" / name
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(f"bundled {name}\n")
    shutil.copytree(FIXTURES, source / "skills" / "aw-init" / "scripts")
    (source / "aw-version.txt").write_text("0.15.0\n")
    return source


def snapshot(root: Path) -> dict[str, bytes | str]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): str(path.readlink()) if path.is_symlink() else path.read_bytes()
        for path in root.rglob("*") if path.is_symlink() or path.is_file()
    }


class InstallerMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = make_source(self.root)
        self.target = self.root / "target"
        self.link = self.root / "agent" / "skills"

    def install(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            return install_aw_skills(self.source, self.target, [self.link], **kwargs)

    def custom(self, name: str) -> Path:
        path = self.target / name
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text("custom content\n")
        return path

    def test_real_helper_installs_ownership_and_preserves_custom_skill(self):
        custom = self.custom("aw-work")
        result = self.install(force=True)
        self.assertEqual((custom / "SKILL.md").read_text(), "custom content\n")
        self.assertNotIn("aw-work", result.skill_names)
        owned = json.loads((self.target / ".augmented-workflow-skills.json").read_text())
        self.assertEqual(sorted(owned["skills"]), result.skill_names)
        self.assertTrue(self.link.is_symlink())

    def test_legacy_names_never_prove_ownership(self):
        for name in ("aw-brainstorm", "aw-create-spec", "aw-commit", "aw-commit-push-pr"):
            self.custom(name)
        (self.target / ".augmented-workflow-skills").write_text("aw-brainstorm\naw-commit\n")
        before = snapshot(self.target)
        self.install()
        for name, content in before.items():
            if name.endswith("SKILL.md"):
                self.assertEqual(snapshot(self.target)[name], content)

    def test_verified_retired_skill_is_backed_up_and_rollback_restores_metadata(self):
        old = self.source / "skills" / "aw-commit"
        old.mkdir()
        (old / "SKILL.md").write_text("old bundle\n")
        self.install()
        before = snapshot(self.target)
        shutil.rmtree(old)
        self.install()
        self.assertFalse((self.target / "aw-commit").exists())
        backups = list((self.target / ".augmented-workflow-backups").iterdir())
        backup = next(path for path in backups if (path / "before" / "aw-commit").exists())
        self.link.unlink()
        self.install(rollback_skills=backup)
        self.assertFalse(self.link.exists(), "rollback must not create agent links")
        self.assertEqual((self.target / "aw-commit" / "SKILL.md").read_text(), "old bundle\n")
        for name in (".augmented-workflow-skills", ".augmented-workflow-skills.json", "aw-version.txt"):
            self.assertEqual((self.target / name).read_bytes(), before[name])

    def test_collision_fails_before_any_writes_even_with_force(self):
        self.custom("aw-spec")
        before = snapshot(self.root)
        with self.assertRaises(RuntimeError):
            self.install(force=True)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.link.exists())

    def test_dry_run_reports_only_managed_skills_without_writes(self):
        self.custom("aw-work")
        before = snapshot(self.root)
        result = self.install(dry_run=True, force=True)
        self.assertNotIn("aw-work", result.skill_names)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.link.exists())

    def test_missing_or_unsupported_contract_fails_before_writes(self):
        scripts = self.source / "skills" / "aw-init" / "scripts"
        for path, invalid in (
            (scripts / "migrate-skills.py", None),
            (scripts / "bundled-skill-fingerprints.json", None),
            (self.source / "aw-version.txt", None),
            (self.source / "aw-version.txt", "unknown\n"),
            (self.source / "aw-version.txt", "0.14.0\n"),
            (scripts / "bundled-skill-fingerprints.json", '{"schema":2,"skills":{}}'),
        ):
            with self.subTest(path=path, invalid=invalid):
                original = path.read_bytes()
                if invalid is None:
                    path.unlink()
                else:
                    path.write_text(invalid)
                before = snapshot(self.root)
                with self.assertRaises((ValueError, FileNotFoundError)):
                    self.install()
                self.assertEqual(snapshot(self.root), before)
                path.write_bytes(original)

    def test_source_equals_target_is_preserved(self):
        before = snapshot(self.source)
        with redirect_stdout(io.StringIO()):
            result = install_aw_skills(self.source, self.source / "skills", [])
        self.assertEqual(snapshot(self.source), before)
        self.assertEqual(result.skill_names, [])

    def test_rollback_dry_run_and_collision_leave_files_untouched(self):
        self.install()
        backup = next((self.target / ".augmented-workflow-backups").iterdir())
        before = snapshot(self.root)
        self.install(rollback_skills=backup, dry_run=True)
        self.assertEqual(snapshot(self.root), before)
        (self.target / "aw-work" / "SKILL.md").write_text("local edit\n")
        before = snapshot(self.root)
        with self.assertRaises(RuntimeError):
            self.install(rollback_skills=backup)
        self.assertEqual(snapshot(self.root), before)

    def test_force_only_replaces_existing_symlink(self):
        wrong = self.root / "wrong"
        wrong.mkdir()
        self.link.parent.mkdir()
        self.link.symlink_to(wrong)
        self.install()
        self.assertEqual(self.link.resolve(), wrong)
        self.install(force=True)
        self.assertEqual(self.link.resolve(), self.target)

    def test_helper_runs_with_current_python_and_propagates_diagnostics(self):
        failure = subprocess.CompletedProcess([], 7, "migration preflight report\n", "unsupported helper interface\n")
        output = io.StringIO()
        help_result = subprocess.CompletedProcess([], 0, "--source --target --version --apply --dry-run --rollback", "")
        with mock.patch("aw_cli.installer.subprocess.run", side_effect=[help_result, failure]) as run:
            with redirect_stdout(output), self.assertRaisesRegex(RuntimeError, "unsupported helper interface"):
                install_aw_skills(self.source, self.target, [self.link], force=True)
        command = run.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1], str(self.source / "skills" / "aw-init" / "scripts" / "migrate-skills.py"))
        self.assertNotIn("--force", command)
        self.assertIn("migration preflight report", output.getvalue())
        self.assertFalse(self.target.exists())
        self.assertFalse(self.link.exists())

    def test_ownership_metadata_symlink_stops_without_link_or_target_writes(self):
        self.target.mkdir()
        outside = self.root / "outside"
        outside.write_text("aw-work\n")
        (self.target / ".augmented-workflow-skills").symlink_to(outside)
        before = snapshot(self.root)
        with self.assertRaisesRegex(RuntimeError, "ownership metadata symlink"):
            self.install()
        self.assertEqual(snapshot(self.root), before)

    def test_historical_fingerprint_retires_legacy_name_only_skill(self):
        baseline = FIXTURES.parent / "aw-migration-baseline" / "aw-commit"
        shutil.copytree(baseline, self.target / "aw-commit")
        (self.target / ".augmented-workflow-skills").write_text("aw-commit\n")
        self.install()
        self.assertFalse((self.target / "aw-commit").exists())
        backup = next((self.target / ".augmented-workflow-backups").iterdir())
        self.assertEqual(snapshot(backup / "before" / "aw-commit"), snapshot(baseline))

    def test_source_metadata_symlinks_are_rejected(self):
        scripts = self.source / "skills" / "aw-init" / "scripts"
        for path in (scripts / "migrate-skills.py", scripts / "bundled-skill-fingerprints.json", self.source / "aw-version.txt"):
            with self.subTest(path=path):
                saved = path.with_suffix(".saved")
                path.rename(saved)
                path.symlink_to(saved)
                try:
                    with self.assertRaises(FileNotFoundError):
                        self.install()
                    self.assertFalse(self.target.exists())
                finally:
                    path.unlink()
                    saved.rename(path)

    def test_symlink_target_or_ancestor_is_rejected(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        self.target.symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "skills directory symlink"):
            self.install()
        with self.assertRaisesRegex(ValueError, "skills directory symlink"):
            install_aw_skills(self.source, self.target / "nested", [])
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_relative_skills_directory_creates_absolute_link_destination(self):
        import os
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            with redirect_stdout(io.StringIO()):
                install_aw_skills(self.source, Path("target"), [self.link])
            self.assertEqual(self.link.readlink(), self.target)
            self.assertTrue((self.link / "aw-work" / "SKILL.md").is_file())
        finally:
            os.chdir(previous)

    def test_unsupported_helper_interface_fails_before_install_writes(self):
        helper = self.source / "skills" / "aw-init" / "scripts" / "migrate-skills.py"
        helper.write_text("print('old unsupported helper')\n")
        before = snapshot(self.root)
        with self.assertRaisesRegex(ValueError, "unsupported AW migration helper"):
            self.install()
        self.assertEqual(snapshot(self.root), before)

    def test_cli_collision_returns_clean_failure_without_success_summary(self):
        self.custom("aw-ship")
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = main(["install", "--source", str(self.source), "--skills-dir", str(self.target), "--agent-dir", str(self.link), "--force"])
        self.assertEqual(status, 1)
        self.assertIn("collision", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())
        self.assertNotIn("Installed", output.getvalue())
        self.assertFalse(self.link.exists())

    def test_cli_rollback_dry_run_and_apply_are_wired_to_real_helper(self):
        self.install()
        backup = next((self.target / ".augmented-workflow-backups").iterdir())
        args = ["install", "--source", str(self.source), "--skills-dir", str(self.target), "--agent-dir", str(self.link), "--rollback-skills", str(backup)]
        before = snapshot(self.root)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args + ["--dry-run"]), 0)
        self.assertEqual(snapshot(self.root), before)
        self.assertIn("Would roll back", output.getvalue())
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args), 0)
        self.assertIn("Rolled back", output.getvalue())
        self.assertNotIn("Installed", output.getvalue())
        self.assertFalse((self.target / "aw-work").exists())

    def test_repeated_install_is_idempotent_without_new_backups(self):
        self.install()
        before = snapshot(self.root)
        self.install()
        self.assertEqual(snapshot(self.root), before)
