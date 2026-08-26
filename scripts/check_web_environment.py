#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from webapp.backend.config import Settings


def configured_checks(settings: Settings) -> dict[str, Path]:
    """Keep the command-line preflight aligned with Web Studio settings."""
    return {
        "web Python": settings.web_python,
        "frontend build": settings.frontend_dist / "index.html",
        "Blender": settings.blender,
        "SAM3 Python": settings.sam3_python,
        "SAM3 checkpoint": settings.sam3_checkpoint,
        "SAM3D Python": settings.sam3d_python,
        "SAM3D checkpoint": settings.sam3d_checkpoint,
        "Hunyuan3D Python": settings.hunyuan_python,
        "Hunyuan3D model": settings.hunyuan_model,
        "Hunyuan Omni core": settings.hunyuan_omni_model / "model/pytorch_model.bin",
        "Hunyuan Omni VAE": settings.hunyuan_omni_model / "vae/pytorch_model.bin",
        "world templates": settings.templates_dir,
        "quality profiles": settings.quality_profiles_dir,
        "asset registry": settings.asset_registry,
    }


def main() -> int:
    settings = Settings()
    failed = False
    print("WorldClaw Studio environment")
    for label, path in configured_checks(settings).items():
        ok = path.exists()
        failed |= not ok
        print(f"  {'OK' if ok else 'MISSING':7} {label:22} {path}")
    free_gib = shutil.disk_usage(ROOT).free / 1024**3
    disk_ok = free_gib >= 20
    failed |= not disk_ok
    print(f"  {'OK' if disk_ok else 'LOW':7} {'free disk':22} {free_gib:.1f} GiB")
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.free",
                "--format=csv,noheader",
            ],
            check=True,
            text=True,
            capture_output=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            print(f"  GPU     {line}")
    except (OSError, subprocess.SubprocessError) as exc:
        failed = True
        print(f"  MISSING nvidia-smi: {exc}")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
