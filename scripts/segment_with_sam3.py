#!/usr/bin/env python3
"""Text-prompted SAM3 segmentation for WorldClaw region/object images."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

WORKSPACE_PARENT = Path(__file__).resolve().parents[2]
DEFAULT_CHECKPOINT = WORKSPACE_PARENT / "sam3/checkpoints/sam3.pt"
if not DEFAULT_CHECKPOINT.is_file():
    DEFAULT_CHECKPOINT = Path.home() / ".cache/worldclaw/models/sam3/checkpoints/sam3.pt"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--score-threshold", type=float, default=0.35)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path(
            os.environ.get("WORLDCLAW_SAM3_CHECKPOINT", str(DEFAULT_CHECKPOINT))
        ).expanduser(),
    )
    args = parser.parse_args()

    import numpy as np
    import torch
    from PIL import Image
    from sam3.model.sam3_image_processor import Sam3Processor
    from sam3.model_builder import build_sam3_image_model

    image = Image.open(args.image).convert("RGB")
    if not args.checkpoint.exists():
        raise SystemExit(f"SAM3 checkpoint not found: {args.checkpoint}")
    model = (
        build_sam3_image_model(checkpoint_path=str(args.checkpoint), load_from_HF=False)
        .cuda()
        .eval()
    )
    processor = Sam3Processor(model)
    # The official SAM3 examples run the full forward pass under BF16 autocast.
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        state = processor.set_image(image)
        result = processor.set_text_prompt(state=state, prompt=args.prompt)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rgb = np.asarray(image)
    records = []
    masks = result["masks"].detach().float().cpu().numpy()
    boxes = result["boxes"].detach().float().cpu().numpy()
    scores = result["scores"].detach().float().cpu().numpy()
    for index, (mask, box, score) in enumerate(zip(masks, boxes, scores)):
        score = float(score)
        if score < args.score_threshold:
            continue
        mask = np.squeeze(mask) > 0.5
        rgba = np.dstack((rgb, mask.astype(np.uint8) * 255))
        stem = f"instance_{index:03d}"
        Image.fromarray(mask.astype(np.uint8) * 255).save(args.output_dir / f"{stem}_mask.png")
        Image.fromarray(rgba).save(args.output_dir / f"{stem}.png")
        records.append({"instance": index, "score": score, "box_xyxy": box.tolist()})

    metadata = {
        "source": str(args.image.resolve()),
        "prompt": args.prompt,
        "score_threshold": args.score_threshold,
        "instances": records,
    }
    (args.output_dir / "instances.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output_dir": str(args.output_dir.resolve()), "count": len(records)}))


if __name__ == "__main__":
    main()
