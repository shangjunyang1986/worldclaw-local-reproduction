from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .contracts import ROOT, load_contract


class AssetRegistry:
    def __init__(self, document: dict[str, Any], root: Path = ROOT):
        self.document = document
        self.root = root.resolve()
        self._assets = {asset["id"]: asset for asset in document["assets"]}
        if len(self._assets) != len(document["assets"]):
            raise ValueError("Asset registry contains duplicate ids")

    @classmethod
    def load(cls, path: str | Path, root: Path = ROOT) -> AssetRegistry:
        return cls(load_contract(path, "asset_registry"), root)

    def get(self, asset_id: str) -> dict[str, Any]:
        try:
            return self._assets[asset_id]
        except KeyError as exc:
            raise KeyError(f"Unknown WorldClaw asset: {asset_id}") from exc

    def list(
        self, *, status: str | None = None, category: str | None = None
    ) -> list[dict[str, Any]]:
        values = list(self._assets.values())
        if status:
            values = [asset for asset in values if asset["status"] == status]
        if category:
            values = [asset for asset in values if asset["category"] == category]
        return sorted(values, key=lambda asset: asset["id"])

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def verify_files(self, asset_ids: list[str] | None = None) -> dict[str, Any]:
        selected = asset_ids or sorted(self._assets)
        results = []
        for asset_id in selected:
            asset = self.get(asset_id)
            for entry in asset["files"]:
                path = (self.root / entry["path"]).resolve()
                inside = path.is_relative_to(self.root)
                exists = inside and path.is_file()
                size_matches = exists and path.stat().st_size == entry["bytes"]
                hash_matches = size_matches and self._sha256(path) == entry["sha256"]
                results.append(
                    {
                        "asset_id": asset_id,
                        "role": entry["role"],
                        "path": entry["path"],
                        "inside_root": inside,
                        "exists": exists,
                        "size_matches": bool(size_matches),
                        "hash_matches": bool(hash_matches),
                        "status": "passed" if hash_matches else "failed",
                    }
                )
        return {
            "status": "passed" if all(item["status"] == "passed" for item in results) else "failed",
            "files": results,
        }
