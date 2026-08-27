#!/usr/bin/env python3
"""Build and audit the source-only public release tree.

The release is allowlist-driven. Private outputs, model weights, reference
images, generated 3D assets and unpublished case-study scripts cannot enter by
accident merely because they exist in the production workspace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "release/public_files.json"
DEFAULT_OUTPUT = ROOT / "release_staging/worldclaw-local-reproduction"
MAX_FILE_BYTES = 10 * 1024 * 1024
ALLOWED_SUFFIXES = {
    "",
    ".cff",
    ".css",
    ".example",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".lock",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".webp",
    ".yaml",
    ".yml",
}
BINARY_SUFFIXES = {".webp"}
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
}
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"[A-Za-z]:\\\\Users\\\\", re.IGNORECASE),
)
SECRET_PATTERNS = (
    re.compile(
        r"\b(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*[\"']?[^\s\"']{12,}",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:hf_|ghp_|github_pat_|sk-)[A-Za-z0-9_-]{20,}"),
    re.compile(r"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY"),
)
SECRET_SCAN_EXEMPTIONS = {"scripts/build_public_release.py"}


class ReleaseError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_policy(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1:
        raise ReleaseError("Unsupported public release policy schema")
    return value


def tree_files(path: Path) -> Iterable[Path]:
    for candidate in sorted(path.rglob("*")):
        if not candidate.is_file() or any(part in IGNORED_PARTS for part in candidate.parts):
            continue
        yield candidate


def selected_files(policy: dict) -> list[Path]:
    selected: set[Path] = set()
    for group in ("files", "scripts"):
        for relative in policy.get(group, []):
            path = (ROOT / relative).resolve()
            if not path.is_file():
                raise ReleaseError(f"Required public file is missing: {relative}")
            selected.add(path)
    for relative in policy.get("trees", []):
        path = (ROOT / relative).resolve()
        if not path.is_dir():
            raise ReleaseError(f"Required public tree is missing: {relative}")
        selected.update(tree_files(path))
    return sorted(selected, key=lambda item: item.relative_to(ROOT).as_posix())


def audit_file(path: Path) -> dict:
    relative = path.relative_to(ROOT).as_posix()
    if path.is_symlink():
        raise ReleaseError(f"Symlinks are forbidden in the public release: {relative}")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ReleaseError(f"Public file exceeds {MAX_FILE_BYTES} bytes: {relative} ({size})")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ReleaseError(f"Public file type is not allowlisted: {relative}")
    payload = path.read_bytes()
    if path.suffix.lower() in BINARY_SUFFIXES:
        if not (
            len(payload) >= 12
            and payload[:4] == b"RIFF"
            and payload[8:12] == b"WEBP"
        ):
            raise ReleaseError(f"Invalid WebP documentation media: {relative}")
        return {
            "path": relative,
            "bytes": size,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    if b"\x00" in payload:
        raise ReleaseError(f"Binary payload is forbidden: {relative}")
    text = payload.decode("utf-8")
    for pattern in ABSOLUTE_PATH_PATTERNS:
        match = pattern.search(text)
        if match:
            line = text.count("\n", 0, match.start()) + 1
            raise ReleaseError(f"Machine-specific absolute path: {relative}:{line}")
    if relative not in SECRET_SCAN_EXEMPTIONS:
        for pattern in SECRET_PATTERNS:
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                raise ReleaseError(f"Potential secret: {relative}:{line}")
    return {"path": relative, "bytes": size, "sha256": hashlib.sha256(payload).hexdigest()}


def safe_output(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    staging_root = (ROOT / "release_staging").resolve()
    try:
        resolved.relative_to(staging_root)
    except ValueError as exc:
        raise ReleaseError(f"Output must be under {staging_root}") from exc
    if resolved == staging_root:
        raise ReleaseError("Output must be a child of release_staging")
    return resolved


def atomic_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build(policy_path: Path, output: Path, check_only: bool) -> dict:
    policy = read_policy(policy_path)
    files = selected_files(policy)
    records = [audit_file(path) for path in files]
    report = {
        "schema_version": 1,
        "status": "passed",
        "release_kind": "source_only_clean_room_reproduction",
        "file_count": len(records),
        "bytes": sum(item["bytes"] for item in records),
        "policy_sha256": sha256(policy_path),
        "files": records,
    }
    if check_only:
        return report

    output = safe_output(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        for source in files:
            relative = source.relative_to(ROOT)
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            os.chmod(target, source.stat().st_mode & 0o777)
        atomic_json(temporary / "release-manifest.json", report)
        if output.exists():
            shutil.rmtree(output)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    report["output"] = str(output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        report = build(args.policy.resolve(), args.output, args.check_only)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ReleaseError) as exc:
        raise SystemExit(f"public release audit failed: {exc}") from exc
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
