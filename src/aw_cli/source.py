from __future__ import annotations

import tarfile
import tempfile
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def prepared_source(*, source: Path | None, source_url: str) -> Iterator[Path]:
    if source is not None:
        yield source.expanduser().resolve()
        return

    with tempfile.TemporaryDirectory(prefix="aw-source-") as tmp:
        archive = Path(tmp) / "source.tar.gz"
        extract_dir = Path(tmp) / "extract"
        extract_dir.mkdir()
        urllib.request.urlretrieve(source_url, archive)
        with tarfile.open(archive, "r:gz") as tar:
            _safe_extract(tar, extract_dir)

        skills_dir = next(extract_dir.glob("*/skills"), None)
        if skills_dir is None:
            raise FileNotFoundError(f"remote source did not contain a skills directory: {source_url}")
        yield skills_dir.parent


def _safe_extract(tar: tarfile.TarFile, destination: Path) -> None:
    destination_root = destination.resolve()
    for member in tar.getmembers():
        target = (destination / member.name).resolve()
        if destination_root != target and destination_root not in target.parents:
            raise ValueError(f"unsafe archive member path: {member.name}")
    tar.extractall(destination)
