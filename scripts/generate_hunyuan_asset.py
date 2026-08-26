#!/usr/bin/env python3
"""Generate one mesh using the workstation's existing Hunyuan3D-2.1 install."""

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--octree-resolution", type=int, default=256)
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

    source = Image.open(args.image)
    # Preserve audited SAM3 alpha masks. Converting an RGBA cutout to RGB here
    # used to restore the original screenshot background and made Hunyuan build
    # nearby paving as floating geometry.
    has_alpha = source.mode in {"RGBA", "LA"} and source.getchannel("A").getextrema()[0] < 255
    if has_alpha:
        image = source.convert("RGBA")
        bbox = image.getchannel("A").getbbox()
        if bbox is None:
            raise RuntimeError(f"Input alpha mask is empty: {args.image}")
        image = image.crop(bbox)
        side = max(image.size)
        padding = max(24, int(side * 0.12))
        canvas_side = side + padding * 2
        canvas = Image.new("RGBA", (canvas_side, canvas_side), (255, 255, 255, 0))
        canvas.alpha_composite(
            image, ((canvas_side - image.width) // 2, (canvas_side - image.height) // 2)
        )
        image = canvas
    else:
        image = BackgroundRemover()(source.convert("RGB")).convert("RGBA")
    pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        str(MODEL_ROOT),
        subfolder="hunyuan3d-dit-v2-1",
        use_safetensors=False,
        device="cuda",
    )
    mesh = pipeline(
        image=image,
        num_inference_steps=args.steps,
        octree_resolution=args.octree_resolution,
        generator=torch.Generator(device="cuda").manual_seed(260805),
    )[0]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(args.output)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
