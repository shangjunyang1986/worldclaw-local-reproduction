from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .configuration import RuntimeConfiguration


@dataclass(frozen=True)
class AdapterStatus:
    id: str
    kind: str
    available: bool
    executable: str | None
    checkpoint: str | None
    detail: str


@dataclass(frozen=True)
class ExternalAdapter:
    id: str
    kind: str
    executable: Path | None
    checkpoint: Path | None = None
    version_args: tuple[str, ...] = ("--version",)

    def probe(self) -> AdapterStatus:
        executable_ok = bool(self.executable and self.executable.is_file())
        checkpoint_ok = self.checkpoint is None or self.checkpoint.exists()
        detail = "available" if executable_ok and checkpoint_ok else "missing"
        if executable_ok:
            try:
                result = subprocess.run(
                    [str(self.executable), *self.version_args],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
                first = (result.stdout or result.stderr).strip().splitlines()
                if first:
                    detail = first[0][:240]
            except (OSError, subprocess.SubprocessError):
                detail = "executable present; version probe failed"
        return AdapterStatus(
            id=self.id,
            kind=self.kind,
            available=executable_ok and checkpoint_ok,
            executable=str(self.executable) if self.executable else None,
            checkpoint=str(self.checkpoint) if self.checkpoint else None,
            detail=detail,
        )

    def command(self, arguments: Sequence[str | Path]) -> list[str]:
        status = self.probe()
        if not status.available or self.executable is None:
            raise RuntimeError(f"Adapter {self.id} is unavailable: {status.detail}")
        return [str(self.executable), *(str(value) for value in arguments)]


def adapter_catalog(config: RuntimeConfiguration) -> list[ExternalAdapter]:
    return [
        ExternalAdapter("blender", "engine", config.blender, version_args=("--version",)),
        ExternalAdapter("sam3", "segmenter", config.sam3_python, config.sam3_checkpoint),
        ExternalAdapter(
            "sam3d_objects", "reconstructor", config.sam3d_python, config.sam3d_checkpoint
        ),
        ExternalAdapter(
            "hunyuan3d_2_1", "asset_generator", config.hunyuan_python, config.hunyuan_model
        ),
    ]
