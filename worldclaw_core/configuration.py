from __future__ import annotations

import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _env_path(name: str, default: Path | None = None) -> Path | None:
    value = os.environ.get(name)
    if value:
        return Path(value).expanduser().absolute()
    return default.expanduser().absolute() if default is not None else None


def _executable(name: str, env_name: str) -> Path | None:
    configured = _env_path(env_name)
    if configured is not None:
        return configured
    discovered = shutil.which(name)
    if discovered:
        return Path(discovered).absolute()
    local = Path.home() / ".local/bin" / name
    return local.absolute() if local.is_file() else None


def _discover(env_name: str, fallback: Path, *candidates: Path) -> Path:
    configured = _env_path(env_name)
    if configured is not None:
        return configured
    for candidate in candidates:
        if candidate.exists():
            return candidate.absolute()
    return fallback.expanduser().absolute()


@dataclass(frozen=True)
class RuntimeConfiguration:
    root: Path
    data_dir: Path
    jobs_dir: Path
    models_dir: Path
    blender: Path | None
    sam3_python: Path | None
    sam3_checkpoint: Path | None
    sam3d_python: Path | None
    sam3d_checkpoint: Path | None
    hunyuan_python: Path | None
    hunyuan_model: Path | None
    hunyuan_omni_model: Path | None
    gpu: str

    def jsonable(self) -> dict[str, str | None]:
        result = asdict(self)
        return {
            key: str(value) if isinstance(value, Path) else value for key, value in result.items()
        }


def runtime_configuration(root: Path | None = None) -> RuntimeConfiguration:
    project_root = (root or _env_path("WORLDCLAW_ROOT", PROJECT_ROOT) or PROJECT_ROOT).absolute()
    workspace_parent = project_root.parent
    models = _env_path("WORLDCLAW_MODELS_DIR", Path.home() / ".cache/worldclaw/models")
    assert models is not None
    return RuntimeConfiguration(
        root=project_root,
        data_dir=_env_path("WORLDCLAW_WEB_DATA", project_root / "webapp/data")
        or project_root / "webapp/data",
        jobs_dir=_env_path("WORLDCLAW_JOBS_DIR", project_root / "outputs/web_jobs")
        or project_root / "outputs/web_jobs",
        models_dir=models,
        blender=_executable("blender", "WORLDCLAW_BLENDER"),
        sam3_python=_discover(
            "WORLDCLAW_SAM3_PYTHON",
            models / "sam3/.venv/bin/python",
            workspace_parent / "sam3/.venv/bin/python",
        ),
        sam3_checkpoint=_discover(
            "WORLDCLAW_SAM3_CHECKPOINT",
            models / "sam3/checkpoints/sam3.pt",
            workspace_parent / "sam3/checkpoints/sam3.pt",
        ),
        sam3d_python=_discover(
            "WORLDCLAW_SAM3D_PYTHON",
            models / "sam-3d-objects/.conda-env/bin/python",
            workspace_parent / "sam-3d-objects/.conda-env/bin/python",
        ),
        sam3d_checkpoint=_discover(
            "WORLDCLAW_SAM3D_CHECKPOINT",
            models / "sam-3d-objects/checkpoints/hf/pipeline.yaml",
            workspace_parent / "sam-3d-objects/checkpoints/hf/pipeline.yaml",
        ),
        hunyuan_python=_discover(
            "WORLDCLAW_HUNYUAN_PYTHON",
            models / "Hunyuan3D-2.1/.conda-env/bin/python",
            workspace_parent / "hunyuan3D/.conda-env/bin/python",
        ),
        hunyuan_model=_discover(
            "WORLDCLAW_HUNYUAN_MODEL",
            models / "Hunyuan3D-2.1/models/Hunyuan3D-2.1",
            workspace_parent / "hunyuan3D/models/Hunyuan3D-2.1",
        ),
        hunyuan_omni_model=_discover(
            "WORLDCLAW_HUNYUAN_OMNI_MODEL",
            models / "Hunyuan3D-Omni/models/Hunyuan3D-Omni",
            workspace_parent / "Hunyuan3D-Omni/models/Hunyuan3D-Omni",
        ),
        gpu=os.environ.get("WORLDCLAW_GPU", "0"),
    )
