from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_PARENT = ROOT.parent
MODELS_DIR = (
    Path(os.environ.get("WORLDCLAW_MODELS_DIR", str(Path.home() / ".cache/worldclaw/models")))
    .expanduser()
    .absolute()
)


def env_path(name: str, default: Path) -> Path:
    # Preserve virtual-environment interpreter symlinks. Resolving
    # ``.venv/bin/python`` to its base executable discards pyvenv.cfg discovery
    # and silently runs without the model environment's installed packages.
    return Path(os.environ.get(name, str(default))).expanduser().absolute()


def executable_path(name: str, env_name: str) -> Path:
    configured = os.environ.get(env_name)
    if configured:
        return Path(configured).expanduser().absolute()
    discovered = shutil.which(name)
    if discovered:
        return Path(discovered).absolute()
    local = Path.home() / ".local/bin" / name
    return local.absolute() if local.is_file() else Path(f"/missing/{name}")


def discovered_path(env_name: str, fallback: Path, *candidates: Path) -> Path:
    """Prefer explicit configuration, then compatible sibling checkouts."""
    configured = os.environ.get(env_name)
    if configured:
        return Path(configured).expanduser().absolute()
    for candidate in candidates:
        if candidate.exists():
            return candidate.absolute()
    return fallback.expanduser().absolute()


def nonnegative_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    data_dir: Path = env_path("WORLDCLAW_WEB_DATA", ROOT / "webapp/data")
    jobs_dir: Path = env_path("WORLDCLAW_JOBS_DIR", ROOT / "outputs/web_jobs")
    database: Path = env_path("WORLDCLAW_WEB_DB", ROOT / "webapp/data/worldclaw.db")
    frontend_dist: Path = env_path("WORLDCLAW_FRONTEND_DIST", ROOT / "webapp/frontend/dist")
    web_python: Path = env_path("WORLDCLAW_WEB_PYTHON", ROOT / "webapp/.venv/bin/python")
    sam3_python: Path = discovered_path(
        "WORLDCLAW_SAM3_PYTHON",
        MODELS_DIR / "sam3/.venv/bin/python",
        WORKSPACE_PARENT / "sam3/.venv/bin/python",
    )
    sam3d_python: Path = discovered_path(
        "WORLDCLAW_SAM3D_PYTHON",
        MODELS_DIR / "sam-3d-objects/.conda-env/bin/python",
        WORKSPACE_PARENT / "sam-3d-objects/.conda-env/bin/python",
    )
    hunyuan_python: Path = discovered_path(
        "WORLDCLAW_HUNYUAN_PYTHON",
        MODELS_DIR / "Hunyuan3D-2.1/.conda-env/bin/python",
        WORKSPACE_PARENT / "hunyuan3D/.conda-env/bin/python",
    )
    blender: Path = executable_path("blender", "WORLDCLAW_BLENDER")
    sam3_checkpoint: Path = discovered_path(
        "WORLDCLAW_SAM3_CHECKPOINT",
        MODELS_DIR / "sam3/checkpoints/sam3.pt",
        WORKSPACE_PARENT / "sam3/checkpoints/sam3.pt",
    )
    sam3d_checkpoint: Path = discovered_path(
        "WORLDCLAW_SAM3D_CHECKPOINT",
        MODELS_DIR / "sam-3d-objects/checkpoints/hf/pipeline.yaml",
        WORKSPACE_PARENT / "sam-3d-objects/checkpoints/hf/pipeline.yaml",
    )
    hunyuan_model: Path = discovered_path(
        "WORLDCLAW_HUNYUAN_MODEL",
        MODELS_DIR / "Hunyuan3D-2.1/models/Hunyuan3D-2.1",
        WORKSPACE_PARENT / "hunyuan3D/models/Hunyuan3D-2.1",
    )
    hunyuan_omni_model: Path = discovered_path(
        "WORLDCLAW_HUNYUAN_OMNI_MODEL",
        MODELS_DIR / "Hunyuan3D-Omni/models/Hunyuan3D-Omni",
        WORKSPACE_PARENT / "Hunyuan3D-Omni/models/Hunyuan3D-Omni",
    )
    templates_dir: Path = env_path("WORLDCLAW_TEMPLATES", ROOT / "templates")
    quality_profiles_dir: Path = env_path(
        "WORLDCLAW_QUALITY_PROFILES", ROOT / "configs/quality_profiles"
    )
    asset_registry: Path = env_path(
        "WORLDCLAW_ASSET_REGISTRY", ROOT / "assets/registry/asset_registry.v1.json"
    )
    gpu: str = os.environ.get("WORLDCLAW_GPU", "0")
    testing: bool = os.environ.get("WORLDCLAW_TESTING", "0") == "1"
    api_token: str = ""
    min_free_vram_mib: int = 0

    def prepare(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.database.parent.mkdir(parents=True, exist_ok=True)


settings = Settings(
    api_token=os.environ.get("WORLDCLAW_API_TOKEN", ""),
    min_free_vram_mib=nonnegative_int("WORLDCLAW_MIN_FREE_VRAM_MIB", 12288),
)
