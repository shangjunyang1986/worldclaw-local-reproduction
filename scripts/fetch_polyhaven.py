#!/usr/bin/env python3
"""Download selected Poly Haven CC0 assets and verify every file by MD5."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

API = "https://api.polyhaven.com/files/{asset_id}"
USER_AGENT = "WorldClaw-local-reproduction/1.0 (+https://polyhaven.com)"


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def download(entry: dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected = entry["md5"]
    if destination.exists():
        digest = hashlib.md5(destination.read_bytes()).hexdigest()
        if digest == expected:
            print(f"verified {destination}")
            return
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(entry["url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as target:
        while chunk := response.read(1024 * 1024):
            target.write(chunk)
    digest = hashlib.md5(temporary.read_bytes()).hexdigest()
    if digest != expected:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"MD5 mismatch for {destination}: {digest} != {expected}")
    temporary.replace(destination)
    print(f"downloaded {destination}")


def texture_entries(payload: dict, resolution: str) -> list[tuple[Path, dict]]:
    result = []
    for channel in ("Diffuse", "nor_gl", "Rough", "Displacement"):
        entry = payload.get(channel, {}).get(resolution, {}).get("jpg")
        if entry:
            filename = Path(urlparse(entry["url"]).path).name
            result.append((Path(filename), entry))
    return result


def model_entries(payload: dict, resolution: str) -> list[tuple[Path, dict]]:
    entry = payload["gltf"][resolution]["gltf"]
    filename = Path(urlparse(entry["url"]).path).name
    result = [(Path(filename), entry)]
    result.extend((Path(relative), item) for relative, item in entry.get("include", {}).items())
    return result


def hdri_entries(payload: dict, resolution: str) -> list[tuple[Path, dict]]:
    entry = payload.get("hdri", {}).get(resolution, {}).get("hdr")
    if not entry:
        return []
    return [(Path(urlparse(entry["url"]).path).name, entry)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset_id")
    parser.add_argument("kind", choices=("texture", "model", "hdri"))
    parser.add_argument("--resolution", default="2k")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = fetch_json(API.format(asset_id=args.asset_id))
    readers = {"texture": texture_entries, "model": model_entries, "hdri": hdri_entries}
    entries = readers[args.kind](payload, args.resolution)
    if not entries:
        raise SystemExit(f"No {args.kind} files found for {args.asset_id} at {args.resolution}")
    for relative, entry in entries:
        download(entry, args.output / relative)


if __name__ == "__main__":
    main()
