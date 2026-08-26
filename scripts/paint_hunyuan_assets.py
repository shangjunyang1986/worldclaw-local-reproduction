#!/usr/bin/env python3
"""Batch-paint Hunyuan3D meshes with one 9-view PBR model load."""

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


def parse_asset(value: str) -> tuple[Path, Path, Path]:
    fields = value.split("=", 2)
    if len(fields) != 3:
        raise argparse.ArgumentTypeError("asset must be MESH=IMAGE=OUTPUT_GLB")
    return tuple(Path(field) for field in fields)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", action="append", type=parse_asset, required=True)
    parser.add_argument("--views", type=int, default=9, choices=range(6, 10))
    parser.add_argument("--resolution", type=int, default=768, choices=(512, 768))
    parser.add_argument("--no-remesh", action="store_true")
    args = parser.parse_args()
    if not HUNYUAN_ROOT.is_dir() or not MODEL_ROOT.is_dir():
        raise SystemExit(
            "Hunyuan3D is not configured; set WORLDCLAW_HUNYUAN_ROOT and WORLDCLAW_HUNYUAN_MODEL"
        )
    assets = [tuple(path.resolve() for path in spec) for spec in args.asset]

    os.chdir(HUNYUAN_ROOT)
    sys.path[:0] = [
        str(HUNYUAN_ROOT),
        str(HUNYUAN_ROOT / "hy3dshape"),
        str(HUNYUAN_ROOT / "hy3dpaint"),
    ]
    from torchvision_fix import apply_fix

    apply_fix()
    from hy3dpaint.convert_utils import create_glb_with_pbr_materials
    from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline

    conf = Hunyuan3DPaintConfig(args.views, args.resolution)
    conf.realesrgan_ckpt_path = str(HUNYUAN_ROOT / "hy3dpaint/ckpt/RealESRGAN_x4plus.pth")
    conf.multiview_cfg_path = str(HUNYUAN_ROOT / "hy3dpaint/cfgs/hunyuan-paint-pbr.yaml")
    conf.custom_pipeline = str(HUNYUAN_ROOT / "hy3dpaint/hunyuanpaintpbr")
    conf.multiview_pretrained_path = str(MODEL_ROOT)
    pipeline = Hunyuan3DPaintPipeline(conf)

    for mesh_path, image_path, output_path in assets:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        obj_path = output_path.with_suffix(".obj")
        pipeline(
            mesh_path=str(mesh_path),
            image_path=str(image_path),
            output_mesh_path=str(obj_path),
            use_remesh=not args.no_remesh,
            save_glb=False,
        )
        textures = {
            "albedo": str(obj_path.with_suffix(".jpg")),
            "metallic": str(obj_path.with_name(obj_path.stem + "_metallic.jpg")),
            "roughness": str(obj_path.with_name(obj_path.stem + "_roughness.jpg")),
        }
        create_glb_with_pbr_materials(str(obj_path), textures, str(output_path))
        print(output_path, flush=True)


if __name__ == "__main__":
    main()
