#!/usr/bin/env python3
"""Batch-generate high-resolution meshes with one Hunyuan3D model load."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

WORKSPACE_PARENT = Path(__file__).resolve().parents[2]
DEFAULT_HUNYUAN_ROOT = WORKSPACE_PARENT / "hunyuan3D"
if not DEFAULT_HUNYUAN_ROOT.is_dir():
    DEFAULT_HUNYUAN_ROOT = Path.home() / ".cache/worldclaw/models/Hunyuan3D-2.1"
HUNYUAN_ROOT = (
    Path(os.environ.get("WORLDCLAW_HUNYUAN_ROOT", str(DEFAULT_HUNYUAN_ROOT)))
    .expanduser()
    .absolute()
)
MODEL_ROOT = (
    Path(os.environ.get("WORLDCLAW_HUNYUAN_MODEL", str(HUNYUAN_ROOT / "models/Hunyuan3D-2.1")))
    .expanduser()
    .absolute()
)


def parse_asset(value: str) -> tuple[Path, Path]:
    try:
        image, output = value.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("asset must be IMAGE=OUTPUT") from exc
    return Path(image), Path(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", action="append", type=parse_asset, required=True)
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--octree-resolution", type=int, default=384)
    parser.add_argument("--seed", type=int, default=260805)
    args = parser.parse_args()

    if not HUNYUAN_ROOT.is_dir() or not MODEL_ROOT.is_dir():
        raise SystemExit(
            "Hunyuan3D is not configured; set WORLDCLAW_HUNYUAN_ROOT and WORLDCLAW_HUNYUAN_MODEL"
        )

    sys.path.insert(0, str(HUNYUAN_ROOT))
    sys.path.insert(0, str(HUNYUAN_ROOT / "hy3dshape"))
    from torchvision_fix import apply_fix

    apply_fix()
    import torch
    from hy3dshape import Hunyuan3DDiTFlowMatchingPipeline
    from hy3dshape.rembg import BackgroundRemover
    from PIL import Image

    pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        str(MODEL_ROOT),
        subfolder="hunyuan3d-dit-v2-1",
        use_safetensors=False,
        device="cuda",
    )
    remover = BackgroundRemover()
    for index, (image_path, output_path) in enumerate(args.asset):
        image = remover(Image.open(image_path).convert("RGB")).convert("RGBA")
        mesh = pipeline(
            image=image,
            num_inference_steps=args.steps,
            octree_resolution=args.octree_resolution,
            generator=torch.Generator(device="cuda").manual_seed(args.seed + index),
        )[0]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(output_path)
        print(output_path.resolve(), flush=True)


if __name__ == "__main__":
    main()
