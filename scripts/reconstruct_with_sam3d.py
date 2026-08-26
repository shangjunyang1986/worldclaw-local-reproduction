#!/usr/bin/env python3
"""Reconstruct one masked object with the official SAM 3D Objects pipeline."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

WORKSPACE_PARENT = Path(__file__).resolve().parents[2]
DEFAULT_SAM3D_ROOT = WORKSPACE_PARENT / "sam-3d-objects"
if not DEFAULT_SAM3D_ROOT.is_dir():
    DEFAULT_SAM3D_ROOT = Path.home() / ".cache/worldclaw/models/sam-3d-objects"
SAM3D_ROOT = (
    Path(os.environ.get("WORLDCLAW_SAM3D_ROOT", str(DEFAULT_SAM3D_ROOT))).expanduser().absolute()
)


def tensor_list(value):
    return value.detach().float().cpu().tolist() if value is not None else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--mask", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--compile", action="store_true")
    parser.add_argument(
        "--mesh-postprocess",
        action="store_true",
        help="Run the official hole filling/simplification post-process.",
    )
    parser.add_argument(
        "--texture-baking",
        action="store_true",
        help="Bake the Gaussian appearance into a 1024px UV texture.",
    )
    args = parser.parse_args()

    if not SAM3D_ROOT.is_dir():
        raise SystemExit("SAM 3D Objects is not configured; set WORLDCLAW_SAM3D_ROOT")

    # httpx does not accept the workstation's legacy `socks://` ALL_PROXY;
    # HTTP(S)_PROXY remains available for any public auxiliary checkpoints.
    os.environ.pop("ALL_PROXY", None)
    os.environ.pop("all_proxy", None)
    os.environ.setdefault("CONDA_PREFIX", str(SAM3D_ROOT / ".conda-env"))
    sys.path.insert(0, str(SAM3D_ROOT))
    sys.path.insert(0, str(SAM3D_ROOT / "notebook"))
    from inference import Inference, load_image, load_mask

    config = (
        Path(
            os.environ.get(
                "WORLDCLAW_SAM3D_CHECKPOINT", str(SAM3D_ROOT / "checkpoints/hf/pipeline.yaml")
            )
        )
        .expanduser()
        .absolute()
    )
    if not config.exists():
        raise SystemExit(
            "SAM3D checkpoint is missing. Request access at "
            "https://huggingface.co/facebook/sam-3d-objects and download it first."
        )

    pipeline = Inference(str(config), compile=args.compile)
    image = load_image(args.image)
    mask = load_mask(args.mask)
    if args.texture_baking:
        # The public notebook forces the PyTorch3D path and does not install
        # diff-gaussian-rasterization, while the upstream baker's multiview
        # helper still defaults to that unavailable "inria" backend.  Route
        # those Gaussian observations through the bundled gsplat renderer.
        from sam3d_objects.model.backbone.tdfy_dit.utils import (
            postprocessing_utils,
            render_utils,
        )

        def render_multiview_gsplat(sample, resolution=512, nviews=30):
            cameras = [render_utils.sphere_hammersley_sequence(i, nviews) for i in range(nviews)]
            yaws = [camera[0] for camera in cameras]
            pitches = [camera[1] for camera in cameras]
            extrinsics, intrinsics = render_utils.yaw_pitch_r_fov_to_extrinsics_intrinsics(
                yaws, pitches, 2, 40
            )
            rendered = render_utils.render_frames(
                sample,
                extrinsics,
                intrinsics,
                {"resolution": resolution, "bg_color": (0, 0, 0), "backend": "gsplat"},
            )
            return rendered["color"], extrinsics, intrinsics

        postprocessing_utils.render_multiview = render_multiview_gsplat
    if args.mesh_postprocess or args.texture_baking:
        rgba = pipeline.merge_mask_to_rgba(image, mask)
        result = pipeline._pipeline.run(
            rgba,
            None,
            args.seed,
            stage1_only=False,
            with_mesh_postprocess=args.mesh_postprocess,
            with_texture_baking=args.texture_baking,
            with_layout_postprocess=False,
            use_vertex_color=not args.texture_baking,
            stage1_inference_steps=None,
        )
    else:
        result = pipeline(image, mask, seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result["gs"].save_ply(str(args.output.with_suffix(".ply")))
    if result.get("glb") is not None:
        result["glb"].export(str(args.output.with_suffix(".glb")))

    layout = {
        "rotation": tensor_list(result.get("rotation")),
        "translation": tensor_list(result.get("translation")),
        "scale": tensor_list(result.get("scale")),
    }
    args.output.with_suffix(".layout.json").write_text(
        json.dumps(layout, indent=2) + "\n", encoding="utf-8"
    )
    print(args.output.resolve())


if __name__ == "__main__":
    main()
