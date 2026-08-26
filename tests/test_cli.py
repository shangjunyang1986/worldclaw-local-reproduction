from __future__ import annotations

import json
from pathlib import Path

from webapp.backend import resources
from worldclaw_core.cli import main
from worldclaw_core.contracts import load_contract

ROOT = Path(__file__).resolve().parents[1]


def test_plan_writes_deterministic_plan_and_valid_world_spec(tmp_path: Path) -> None:
    arguments = [
        "plan",
        "--prompt",
        "A reproducible contract fixture",
        "--preset",
        "test_world",
        "--seed",
        "17",
        "--output",
        str(tmp_path),
    ]
    assert main(arguments) == 0
    first = (tmp_path / "plan.json").read_bytes()
    assert main(arguments) == 0
    assert (tmp_path / "plan.json").read_bytes() == first
    spec = load_contract(tmp_path / "world_spec.json", "world_spec")
    assert spec["scene_id"] == "test_world.seed-17"
    assert spec["geometry_policy"]["generated_images_role"] == "reference_only"


def test_package_hashes_delivery_files(tmp_path: Path) -> None:
    (tmp_path / "plan.json").write_text('{"seed": 1}\n', encoding="utf-8")
    assert main(["package", str(tmp_path)]) == 0
    manifest = json.loads((tmp_path / "delivery_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "built"
    assert manifest["files"][0]["path"] == "plan.json"
    assert len(manifest["files"][0]["sha256"]) == 64


def test_public_fixture_contracts_validate() -> None:
    fixture = ROOT / "examples/cc0_frontier"
    assert load_contract(fixture / "world_spec.json", "world_spec")["scene_id"].startswith(
        "cc0_frontier"
    )
    assert (
        load_contract(fixture / "asset_registry.json", "asset_registry")["assets"][0]["status"]
        == "candidate"
    )


def test_gpu_capacity_is_fail_closed_unless_threshold_is_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        resources,
        "gpu_memory",
        lambda _device: {"available": False, "index": "0", "error": "no telemetry"},
    )
    assert resources.capacity_check("0", 12288)["capacity_ok"] is False
    assert resources.capacity_check("0", 0)["capacity_ok"] is True
