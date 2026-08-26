from __future__ import annotations

import hashlib
import json
import os
import platform
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_records(paths: Iterable[Path], root: Path) -> list[dict]:
    records = []
    for path in sorted(paths):
        if not path.is_file() or path.is_symlink():
            continue
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return records


def runtime_record() -> dict:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def atomic_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def delivery_manifest(root: Path, files: Iterable[Path], scene_id: str | None = None) -> dict:
    return {
        "schema_version": 1,
        "status": "built",
        "scene_id": scene_id,
        "created_at": datetime.now(UTC).isoformat(),
        "runtime": runtime_record(),
        "files": artifact_records(files, root),
    }
