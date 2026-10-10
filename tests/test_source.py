from __future__ import annotations

import io
import tarfile
from pathlib import Path
from unittest import mock

import pytest

from aw_cli.cli import main
from aw_cli.source import prepared_source
from test_cli import make_source


def archive_source(source, target):
    with tarfile.open(target, 'w:gz') as archive:
        archive.add(source, arcname='aw-pinned')


def test_install_and_upgrade_use_pinned_archive(tmp_path, capsys):
    source = make_source(tmp_path)
    archive = tmp_path / 'pinned.tar.gz'
    archive_source(source, archive)
    skills, repo = tmp_path / 'skills', tmp_path / 'repo'
    args = ['--source-url', archive.as_uri()]
    with mock.patch('builtins.input', side_effect=AssertionError('must not prompt')):
        assert main(['install', *args, '--skills-dir', str(skills), '--agent-dir', str(tmp_path / 'agent-skills')]) == 0
        assert main(['upgrade', *args, '--repo', str(repo)]) == 0
    assert (skills / 'aw-version.txt').read_text() == '1.2.3\n'
    assert (repo / '.augmented-workflow-version').read_text() == '1.2.3\n'


def test_explicit_source_url_overrides_environment_directory(tmp_path, monkeypatch):
    source = make_source(tmp_path)
    archive = tmp_path / 'pinned.tar.gz'
    archive_source(source, archive)
    monkeypatch.setenv('AW_SOURCE_DIR', str(tmp_path / 'does-not-exist'))
    assert main(['upgrade', '--source-url', archive.as_uri(), '--repo', str(tmp_path / 'repo'), '--dry-run']) == 0
    assert not (tmp_path / 'repo').exists()


def test_source_directory_environment_avoids_download(tmp_path, monkeypatch):
    source = make_source(tmp_path)
    monkeypatch.setenv('AW_SOURCE_DIR', str(source))
    with mock.patch('urllib.request.urlretrieve', side_effect=AssertionError('unexpected network')):
        assert main(['upgrade', '--repo', str(tmp_path / 'repo'), '--dry-run']) == 0


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'parent'])
def test_unsafe_archive_fails_without_extracting_outside(tmp_path, kind):
    archive = tmp_path / 'unsafe.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        member = tarfile.TarInfo('../outside' if kind == 'parent' else 'aw/skills/link')
        if kind != 'parent':
            member.type = tarfile.SYMTYPE if kind == 'symlink' else tarfile.LNKTYPE
            member.linkname = '/tmp/outside'
        tar.addfile(member, io.BytesIO())
    with pytest.raises(ValueError), prepared_source(source=None, source_url=archive.as_uri()):
        pass
    assert not (tmp_path / 'outside').exists()
