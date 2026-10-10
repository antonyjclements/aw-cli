#!/usr/bin/env python3
"""Content-verified bundled-skill migration with reversible, journaled changes."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile

NAMES = '.augmented-workflow-skills'
OWNERSHIP = '.augmented-workflow-skills.json'
BACKUPS = '.augmented-workflow-backups'
METADATA = {NAMES, OWNERSHIP, 'aw-version.txt'}
CONSOLIDATED = {'aw-spec', 'aw-ship'}
NAME = re.compile(r'aw-[a-z0-9][a-z0-9-]*\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')


def exists(path):
    return path.exists() or path.is_symlink()


def fingerprint(path):
    """Include every path, file content, executable bits, and symlink target."""
    if not exists(path):
        return None
    digest = hashlib.sha256()
    paths = [path] + sorted(path.rglob('*')) if path.is_dir() and not path.is_symlink() else [path]
    for entry in paths:
        relative = str(entry.relative_to(path))
        mode = entry.lstat().st_mode
        if stat.S_ISLNK(mode):
            value = f'L\0{relative}\0{entry.readlink()}\0'
        elif stat.S_ISDIR(mode):
            value = f'D\0{relative}\0'
        elif stat.S_ISREG(mode):
            value = f'F\0{relative}\0{mode & 0o111}\0{hashlib.sha256(entry.read_bytes()).hexdigest()}\0'
        else:
            raise ValueError(f'unsupported file type: {entry}')
        digest.update(value.encode())
    return digest.hexdigest()


def validate_name(name):
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError(f'invalid skill name in ownership manifest: {name!r}')


def read_ownership(target):
    for name in METADATA:
        if (target / name).is_symlink():
            raise ValueError(f'ownership metadata symlink: {target / name}')
    names_path = target / NAMES
    names = names_path.read_text().splitlines() if names_path.exists() else []
    for name in names:
        validate_name(name)
    path = target / OWNERSHIP
    if not path.exists():
        return {}, set(names)
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get('schema') != 1 or not isinstance(data.get('skills'), dict):
        raise ValueError(f'invalid ownership manifest: {path}')
    for name, digest in data['skills'].items():
        validate_name(name)
        if not isinstance(digest, str) or not SHA.fullmatch(digest):
            raise ValueError(f'invalid ownership fingerprint for {name}')
    return data['skills'], set(names)


def write_json(path, value):
    # Exclusive, unpredictable creation must not follow a planted sibling link.
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def copy(src, dest):
    if src.is_dir() and not src.is_symlink():
        shutil.copytree(src, dest, symlinks=True)
    else:
        shutil.copy2(src, dest, follow_symlinks=False)


def unfinished(target):
    root = target / BACKUPS
    if root.is_symlink():
        raise ValueError(f'backup directory symlink: {root}')
    for path in sorted(root.glob('*/transaction.json')):
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError(f'backup journal symlink: {path}')
        journal = json.loads(path.read_text())
        if not isinstance(journal, dict) or journal.get('state') not in ('applying', 'rolling-back', 'complete', 'rolled-back'):
            raise ValueError(f'invalid migration journal: {path}')
        if journal['state'] in ('applying', 'rolling-back'):
            raise ValueError(f'unfinished migration: {path.parent}; use --rollback-skills with this backup before retrying')


def rollback(target, backup, dry_run):
    backup = backup.absolute()
    if (target / BACKUPS).is_symlink():
        raise ValueError('rollback backup directory symlink')
    if backup.is_symlink() or backup.parent != target / BACKUPS:
        raise ValueError('rollback backup must be a direct, non-symlink child of the target backup directory')
    journal_path = backup / 'transaction.json'
    if journal_path.is_symlink() or (backup / 'before').is_symlink():
        raise ValueError('rollback backup contains an unsafe symlink')
    journal = json.loads(journal_path.read_text())
    if not isinstance(journal, dict) or journal.get('schema') != 1 or journal.get('target') != str(target):
        raise ValueError('rollback backup identity does not match the target skills directory')
    if journal.get('state') not in ('applying', 'rolling-back', 'complete', 'rolled-back') or not isinstance(journal.get('changes'), list):
        raise ValueError('invalid rollback journal')
    if journal.get('state') == 'rolled-back':
        print('Rollback already complete.')
        return
    for item in journal['changes']:
        name = item['name']
        if name not in METADATA:
            validate_name(name)
        before = fingerprint(backup / 'before' / name)
        if before != item['before']:
            raise ValueError(f'rollback backup content changed: {name}')
        for value in (item['before'], item['after']):
            if value is not None and (not isinstance(value, str) or not SHA.fullmatch(value)):
                raise ValueError(f'invalid rollback fingerprint: {name}')
        actual = fingerprint(target / name)
        # A kill may leave either the old state, new state, or the rename gap.
        if actual not in (item['before'], item['after'], None):
            raise ValueError(f'rollback collision: {name} changed after migration; preserve it and resolve manually')
    print(f'Mode: {"dry-run" if dry_run else "rollback"}')
    print(f'Rollback: {backup}')
    if dry_run:
        return
    with tempfile.TemporaryDirectory(prefix='.aw-skills-rollback-', dir=target) as temp:
        stage = Path(temp)
        for item in journal['changes']:
            if item['before'] is not None:
                copy(backup / 'before' / item['name'], stage / item['name'])
        journal['state'] = 'rolling-back'
        write_json(journal_path, journal)
        removed = Path(tempfile.mkdtemp(prefix='rollback-removed-', dir=backup))
        for item in reversed(journal['changes']):
            dest = target / item['name']
            if exists(dest):
                dest.replace(removed / item['name'])
            if item['before'] is not None:
                (stage / item['name']).replace(dest)
    journal['state'] = 'rolled-back'
    write_json(journal_path, journal)
    print('Restored the previous skill bundle and ownership/version metadata. Restore any separately backed-up repo routing/config as the same compatible set.')


def migrate(args):
    target = Path(args.target).expanduser().absolute()
    source = Path(args.source).expanduser().resolve()
    if args.rollback:
        rollback(target, Path(args.rollback).expanduser(), not args.apply)
        return
    unfinished(target)
    owned, old_names = read_ownership(target)
    historical = json.loads(Path(__file__).with_name('bundled-skill-fingerprints.json').read_text())['skills']
    current = {}
    for path in sorted(source.glob('aw-*')):
        if path.is_symlink():
            raise ValueError(f'source skill symlink: {path}')
        if path.is_dir() and (path / 'SKILL.md').is_file():
            validate_name(path.name)
            current[path.name] = fingerprint(path)
    if not current:
        raise ValueError(f'no bundled skills found in {source}')
    if target.exists() and target.resolve() == source:
        print(f'skills preserve: source and target are the same directory: {target}')
        return
    changes = []
    managed = {}
    unresolved = []
    collisions = []
    print('Skill migration report')
    print('Mode: dry-run (preflight; no changes yet)')
    for name, expected in current.items():
        dest = target / name
        actual = fingerprint(dest)
        verified = actual is not None and not dest.is_symlink() and (
            actual == owned.get(name) or actual in historical.get(name, []))
        if actual is None:
            action = 'install'
        elif verified or (name not in CONSOLIDATED and actual == expected):
            action = 'preserve managed' if actual == expected else 'update'
        elif name in CONSOLIDATED:
            collisions.append(name)
            print(f'collision: {name} is user-owned, customized, or unverified; move/rename it explicitly before installing. --force does not bypass this check.')
            continue
        else:
            unresolved.append(name)
            print(f'preserve unresolved: {name} (customized or ownership unverified)')
            continue
        managed[name] = expected
        print(f'{action}: {name}')
        if actual != expected:
            changes.append({'name': name, 'before': actual, 'after': expected})
    # A name, prefix, or legacy name-only manifest is not proof of ownership.
    candidates = set(owned) | old_names | set(historical)
    candidates.update(path.name for path in target.glob('*') if (path / 'SKILL.md').is_file())
    for name in sorted(candidates - set(current)):
        dest = target / name
        if not exists(dest):
            continue
        actual = fingerprint(dest)
        verified = NAME.fullmatch(name) and not dest.is_symlink() and (
            actual == owned.get(name) or actual in historical.get(name, []))
        if verified:
            print(f'retire: {name} (verified bundled content; backup before removal)')
            changes.append({'name': name, 'before': actual, 'after': None})
        else:
            unresolved.append(name)
            print(f'preserve unresolved: {name} (customized or ownership unverified)')
    print(f'Managed bundled skills: {len(managed)}; preserved unresolved directories: {len(unresolved)}')
    print('Compatibility: aw-brainstorm and aw-create-spec are retired bundled entrypoints. Use aw-spec; exact old slash commands are runtime-dependent and no redirect is installed.')
    print('Compatibility: aw-commit and aw-commit-push-pr are retired bundled entrypoints. Use aw-ship; commit and commit_push_pr providers remain independent and no redirect is installed.')
    if collisions:
        raise ValueError('skill name collision; stopped before any install writes')
    if not args.apply:
        return
    target.mkdir(parents=True, exist_ok=True)
    # Stage the complete payload before changing any installed directory.
    with tempfile.TemporaryDirectory(prefix='.aw-skills-stage-', dir=target) as temp:
        stage = Path(temp)
        for item in changes:
            if item['after'] is not None:
                copy(source / item['name'], stage / item['name'])
                if fingerprint(stage / item['name']) != item['after']:
                    raise ValueError(f'source changed during staging: {item["name"]}')
        (stage / NAMES).write_text(''.join(f'{name}\n' for name in sorted(managed)))
        write_json(stage / OWNERSHIP, {'schema': 1, 'version': args.version, 'skills': managed})
        (stage / 'aw-version.txt').write_text(args.version + '\n')
        for name in sorted(METADATA):
            before, after = fingerprint(target / name), fingerprint(stage / name)
            if before != after:
                changes.append({'name': name, 'before': before, 'after': after})
        if not changes:
            print('Skills already current; no changes.')
            return
        backup_root = target / BACKUPS
        backup_root.mkdir(exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-'), dir=backup_root))
        (backup / 'before').mkdir()
        (backup / 'replaced').mkdir()
        for item in changes:
            dest = target / item['name']
            if fingerprint(dest) != item['before']:
                raise ValueError(f'target changed during preflight: {item["name"]}')
            if item['before'] is not None:
                copy(dest, backup / 'before' / item['name'])
        # Keep interrupted payloads inside the retained transaction, away from
        # discoverable top-level skills. Renames share the target filesystem.
        stage = stage.replace(backup / 'staged')
        journal = {'schema': 1, 'state': 'applying', 'target': str(target), 'version': args.version, 'changes': changes}
        journal_path = backup / 'transaction.json'
        write_json(journal_path, journal)
        print(f'Skills backup: {backup}', flush=True)
        try:
            for item in changes:
                dest = target / item['name']
                if fingerprint(dest) != item['before']:
                    raise ValueError(f'target changed during migration: {item["name"]}')
                if exists(dest):
                    dest.replace(backup / 'replaced' / item['name'])
                if item['after'] is not None:
                    (stage / item['name']).replace(dest)
            journal['state'] = 'complete'
            write_json(journal_path, journal)
        except Exception:
            print(f'Migration interrupted; restore with install.sh --skills-dir {target} --rollback-skills {backup}', file=sys.stderr)
            raise
        print(f'skills manifest: {target / OWNERSHIP}')
        print('Skills migration complete. Backups are retained for explicit rollback.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--version', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback')
    args = parser.parse_args()
    if args.rollback and not args.dry_run:
        args.apply = True
    try:
        migrate(args)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f'Skill migration stopped: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
