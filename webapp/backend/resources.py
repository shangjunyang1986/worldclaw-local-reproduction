from __future__ import annotations

import subprocess
from typing import Any


def gpu_memory(device: str, timeout: float = 5) -> dict[str, Any]:
    """Return one configured GPU's memory snapshot without importing CUDA."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                f"--id={device}",
                "--query-gpu=index,name,memory.total,memory.used,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
        line = next(value for value in result.stdout.splitlines() if value.strip())
        index, name, total, used, free = (part.strip() for part in line.split(",", 4))
        return {
            "available": True,
            "index": index,
            "name": name,
            "total_mib": int(total),
            "used_mib": int(used),
            "free_mib": int(free),
        }
    except (OSError, StopIteration, ValueError, subprocess.SubprocessError) as exc:
        return {"available": False, "index": device, "error": str(exc)[:240]}


def capacity_check(device: str, minimum_free_mib: int) -> dict[str, Any]:
    snapshot = gpu_memory(device)
    snapshot["minimum_free_mib"] = minimum_free_mib
    # A zero threshold explicitly permits CPU/non-NVIDIA operation. Otherwise
    # absent telemetry is fail-closed because model stages cannot prove that
    # they have enough memory to start safely.
    snapshot["capacity_ok"] = minimum_free_mib == 0 or (
        snapshot["available"] and int(snapshot.get("free_mib", 0)) >= minimum_free_mib
    )
    return snapshot
