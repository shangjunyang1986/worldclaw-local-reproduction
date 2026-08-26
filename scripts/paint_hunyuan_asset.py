#!/usr/bin/env python3
"""Apply Hunyuan3D-2.1 PBR textures to an existing mesh."""

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
    parser.add_argument("--mesh", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--views", type=int, default=9, choices=range(6, 10))
    parser.add_argument("--resolution", type=int, default=768, choices=(512, 768))
    parser.add_argument("--no-remesh", action="store_true")
    args = parser.parse_args()

    if not HUNYUAN_ROOT.is_dir() or not MODEL_ROOT.is_dir():
        raise SystemExit(
            "Hunyuan3D is not configured; set WORLDCLAW_HUNYUAN_ROOT and WORLDCLAW_HUNYUAN_MODEL"
        )

    mesh_path = args.mesh.resolve()
    image_path = args.image.resolve()
    output_path = args.output.resolve()

    os.chdir(HUNYUAN_ROOT)
    sys.path.insert(0, str(HUNYUAN_ROOT))
    sys.path.insert(0, str(HUNYUAN_ROOT / "hy3dshape"))
    sys.path.insert(0, str(HUNYUAN_ROOT / "hy3dpaint"))

    from torchvision_fix import apply_fix

    apply_fix()
    from hy3dpaint.convert_utils import create_glb_with_pbr_materials
    from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline

    conf = Hunyuan3DPaintConfig(args.views, args.resolution)
    conf.realesrgan_ckpt_path = str(HUNYUAN_ROOT / "hy3dpaint/ckpt/RealESRGAN_x4plus.pth")
    conf.multiview_cfg_path = str(HUNYUAN_ROOT / "hy3dpaint/cfgs/hunyuan-paint-pbr.yaml")
    conf.custom_pipeline = str(HUNYUAN_ROOT / "hy3dpaint/hunyuanpaintpbr")
    conf.multiview_pretrained_path = str(MODEL_ROOT)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline = Hunyuan3DPaintPipeline(conf)
    # The upstream painter always writes Wavefront OBJ first and derives the
    # GLB filename with a literal `.obj` -> `.glb` replacement. Passing a GLB
    # path directly therefore produces an OBJ with the wrong extension.
    obj_output = output_path.with_suffix(".obj")
    result = pipeline(
        mesh_path=str(mesh_path),
        image_path=str(image_path),
        output_mesh_path=str(obj_output.resolve()),
        use_remesh=not args.no_remesh,
        save_glb=True,
    )
    glb_output = obj_output.with_suffix(".glb")
    textures = {
        "albedo": str(obj_output.with_suffix(".jpg")),
        "metallic": str(obj_output.with_name(obj_output.stem + "_metallic.jpg")),
        "roughness": str(obj_output.with_name(obj_output.stem + "_roughness.jpg")),
    }
    create_glb_with_pbr_materials(str(obj_output), textures, str(glb_output))
    if output_path.suffix.lower() == ".glb" and not glb_output.exists():
        raise RuntimeError(f"PBR GLB export failed: {glb_output}")
    print((glb_output if output_path.suffix.lower() == ".glb" else Path(result)).resolve())


if __name__ == "__main__":
    main()
