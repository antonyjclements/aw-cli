from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from aw_cli.commands.init_repo import ARTIFACTS, GENERATED, GITATTRIBUTES, GITIGNORE, HOOK_COMMAND, _with_version
from aw_cli.installer import validate_migration_source
from aw_cli.workflow_config import with_cli_default_aw_features

OWNERSHIP = '.augmented-workflow-repo.json'
CONFIG = 'docs/workflow/config.yml'
GATE = '.scripts/aw-gate.js'


def check_path(path: Path) -> None:
    for entry in (path, *path.parents):
        if entry.is_symlink():
            raise ValueError(f'unsafe symlink in repository path: {entry}')


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def atomic_write(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temp.chmod(mode)
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def backup_file(path: Path, original: tuple[bytes, int]) -> Path:
    number = 0
    while True:
        backup = path.with_name(path.name + ('.bak' if number == 0 else f'.bak.{number}'))
        try:
            with backup.open('xb') as stream:
                stream.write(original[0])
            backup.chmod(original[1])
            return backup
        except FileExistsError:
            number += 1


def migrated_config(repo: Path, source: Path, original: bytes) -> bytes:
    ruby = shutil.which('ruby')
    if ruby is None:
        raise ValueError('Ruby is required to safely migrate existing config; install Ruby and retry. No repository files changed.')
    helper = source / 'skills/aw-init/scripts/upgrade-config.rb'
    if not helper.is_file() or helper.is_symlink():
        raise ValueError(f'AW source lacks the safe config migrator: {helper}')
    # Run the upstream migrator only against a disposable copy. All conflicts,
    # dependencies and source errors are discovered before touching the target.
    with tempfile.TemporaryDirectory(prefix='aw-config-preview-') as temporary:
        stage = Path(temporary)
        config = stage / CONFIG
        config.parent.mkdir(parents=True)
        config.write_bytes(original)
        result = subprocess.run([ruby, str(helper), '--repo', str(stage), '--apply'],
                                capture_output=True, text=True, check=False)
        if result.returncode:
            raise ValueError('Config migration requires review: ' + (result.stdout + result.stderr).strip())
        for line in result.stdout.splitlines():
            if 'preserved' in line or 'retired' in line:
                print(line)
        return config.read_bytes()


def upgrade_repository(repo: Path, source: Path, *, dry_run: bool = False) -> None:
    check_path(repo)
    _, baseline, version = validate_migration_source(source)
    migrator = source / 'skills/aw-init/scripts/upgrade-config.rb'
    if not migrator.is_file() or migrator.is_symlink():
        raise ValueError(f'AW source lacks the safe config migrator: {migrator}')
    artifacts = source / 'skills/aw-init/artifacts'
    payload: dict[str, bytes] = {}
    for relative, name in ARTIFACTS.items():
        path = artifacts / name
        if path.is_symlink():
            raise ValueError(f'unsafe source artifact symlink: {path}')
        content = path.read_text(encoding='utf-8')
        if relative == 'AGENTS.md':
            content = _with_version(content, version)
        if relative == CONFIG:
            content = with_cli_default_aw_features(content)
        payload[relative] = content.encode()
    payload.update({name: content.encode() for name, content in GENERATED.items()})
    payload['.augmented-workflow-version'] = (version + '\n').encode()
    hook = source / 'skills/aw-init/hooks/log-session.sh'
    if hook.is_file():
        if hook.is_symlink():
            raise ValueError(f'unsafe source hook symlink: {hook}')
        payload['.claude/hooks/log-session.sh'] = hook.read_bytes()
        payload['.claude/settings.json'] = (json.dumps({'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': HOOK_COMMAND}]}]}}, indent=2) + '\n').encode()
    payload['.gitignore'] = ('\n'.join((*GITIGNORE, '/.aw/workstreams/')) + '\n').encode()
    payload['.gitattributes'] = ('\n'.join(GITATTRIBUTES) + '\n').encode()
    for relative in (*payload, OWNERSHIP):
        check_path(repo / relative)
    ownership_path = repo / OWNERSHIP
    ownership_snapshot = (ownership_path.read_bytes(), ownership_path.stat().st_mode & 0o777) if ownership_path.exists() else None
    owned = {}
    if ownership_snapshot is not None:
        data = json.loads(ownership_snapshot[0])
        if not isinstance(data, dict) or data.get('schema') != 1 or not isinstance(data.get('files'), dict):
            raise ValueError('invalid repository ownership manifest')
        owned = data['files']
        if any(name not in payload or not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)
               for name, value in owned.items()):
            raise ValueError('invalid repository ownership fingerprint')
    known = baseline.get('repo_files', {})
    history = baseline.get('repo_file_history', {})
    if not isinstance(known, dict) or not isinstance(history, dict):
        raise ValueError('invalid source repository fingerprints')
    for value in known.values():
        if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
            raise ValueError('invalid source repository fingerprint')
    for values in history.values():
        if not isinstance(values, list) or any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value) for value in values):
            raise ValueError('invalid source repository fingerprint history')
    plans: dict[str, bytes] = {}
    snapshots = {}
    managed = {}
    for relative, incoming in payload.items():
        target = repo / relative
        if target.exists() and not target.is_file():
            if relative in (GATE, CONFIG):
                raise ValueError(f'repository compatibility review required: {relative} is not a file')
            print(f'preserve: {relative} (directory)')
            continue
        current = target.read_bytes() if target.exists() else None
        snapshots[relative] = (current, target.stat().st_mode & 0o777) if current is not None else None
        verified = current is not None and digest(current) in [owned.get(relative), known.get(relative), *history.get(relative, [])]
        if relative == GATE and current is not None and current != incoming and not verified:
            raise ValueError(f'helper compatibility review required: {relative} is customized or unverified; no repository files changed')
        if relative == CONFIG and current is not None:
            incoming = migrated_config(repo, source, current)
        elif current is not None and current != incoming and not verified and relative != '.augmented-workflow-version':
            print(f'preserve: {relative} (customized or ownership unverified)')
            if re.search(rb'aw-(brainstorm|create-spec|commit(?:-push-pr)?)(?![a-z0-9-])', current):
                print(f'routing review required: {relative} references retired names; keep custom providers and review bundled routes')
            continue
        managed[relative] = digest(incoming)
        if current != incoming:
            plans[relative] = incoming
            print(f'{"would write" if dry_run else "planned write"}: {relative}')
        else:
            print(f'unchanged: {relative}')
    manifest = (json.dumps({'schema': 1, 'version': version, 'files': managed}, indent=2, sort_keys=True) + '\n').encode()
    if ownership_snapshot is None or ownership_snapshot[0] != manifest:
        plans[OWNERSHIP] = manifest
    snapshots[OWNERSHIP] = ownership_snapshot
    if dry_run:
        return
    # Back up the full changed existing set before the first destination write.
    originals = {relative: snapshots[relative] for relative in plans}
    for relative, before in originals.items():
        target = repo / relative
        check_path(target)
        current = (target.read_bytes(), target.stat().st_mode & 0o777) if target.exists() else None
        if current != before:
            raise ValueError(f'target changed during preflight: {relative}; no repository files changed')
    for relative in plans:
        target = repo / relative
        if originals[relative] is not None:
            backup = backup_file(target, originals[relative])
            print(f'backup: {backup.relative_to(repo)}')
    written = []
    written_modes = {}
    try:
        for relative, content in plans.items():
            target = repo / relative
            check_path(target)
            before = originals[relative]
            current = (target.read_bytes(), target.stat().st_mode & 0o777) if target.exists() else None
            if current != before:
                raise ValueError(f'target changed during upgrade: {relative}')
            mode = before[1] if before else 0o644
            if relative in (GATE, '.claude/hooks/log-session.sh'):
                mode |= 0o111
            atomic_write(target, content, mode)
            written.append(relative)
            written_modes[relative] = mode
            print(f'write: {relative}')
    except Exception as error:
        collisions = []
        for relative in reversed(written):
            target = repo / relative
            try:
                check_path(target)
                matches = target.is_file() and target.read_bytes() == plans[relative] and target.stat().st_mode & 0o777 == written_modes[relative]
            except (OSError, ValueError):
                matches = False
            if not matches:
                collisions.append(relative)
                continue
            original = originals[relative]
            if original is None:
                target.unlink()
            else:
                atomic_write(target, original[0], original[1])
        if collisions:
            raise ValueError('Upgrade failed; recovery preserved concurrent edits to ' + ', '.join(collisions) + '; restore retained backups manually') from error
        raise
