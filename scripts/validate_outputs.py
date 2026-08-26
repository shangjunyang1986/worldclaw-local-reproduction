#!/usr/bin/env python3
"""Fast structural QA for WorldClaw-Lite outputs."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a PNG: {path}")
    return struct.unpack(">II", data[16:24])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("output", type=Path)
    args = p.parse_args()
    root = args.output
    manifest = json.loads((root / "manifest.json").read_text())
    plan = json.loads((root / "plan.json").read_text())
    assert manifest["hunyuan_asset_used"], "Hunyuan3D asset was not integrated"
    assert manifest["objects"] >= 450
    assert (root / "world.blend").read_bytes()[:7] == b"BLENDER"
    assert (root / "world.glb").read_bytes()[:4] == b"glTF"
    for name in ("global.png", "walk_village.png", "walk_river.png", "tower_close.png"):
        assert png_size(root / name) == (plan["render"]["width"], plan["render"]["height"]), name
    assert png_size(root / "semantic_layout.png") == (512, 512)
    print(
        json.dumps(
            {
                "status": "passed",
                "objects": manifest["objects"],
                "meshes": manifest["meshes"],
                "hunyuan_asset_used": True,
                "render_size": [plan["render"]["width"], plan["render"]["height"]],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
