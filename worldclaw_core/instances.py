from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import dump_contract, load_contract, validate_contract
from .gates import GATE_ORDER, transition_gate
from .validation import build_quality_report


class InstanceError(ValueError):
    """Raised when a frozen template cannot be safely instantiated."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def atomic_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _safe_source(root: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise InstanceError(f"Template source escapes the project: {value}") from exc
    if not resolved.is_file():
        raise InstanceError(f"Template source is missing: {value}")
    return resolved


def _portable_path(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if os.path.samefile(source, destination):
            return
        raise InstanceError(f"Instance target already exists: {destination}")
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _derived_scene_id(scene_id: str, job_id: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9_.-]", "-", job_id).strip("-.") or "instance"
    prefix = scene_id[: max(3, 71 - len(suffix))].rstrip("-.")
    return f"{prefix}.d.{suffix}"[:80]


def record_revision(
    world_dir: Path,
    action: str,
    spec: dict[str, Any],
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    revisions = world_dir / "contract_revisions"
    revisions.mkdir(parents=True, exist_ok=True)
    number = len(list(revisions.glob("[0-9][0-9][0-9][0-9]_*.json"))) + 1
    safe_action = re.sub(r"[^a-z0-9_-]", "_", action.lower()).strip("_") or "update"
    canonical = json.dumps(spec, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    payload = {
        "schema_version": 1,
        "revision": number,
        "timestamp": utc_now(),
        "action": action,
        "world_spec_sha256": hashlib.sha256(canonical).hexdigest(),
        "details": details or {},
        "world_spec": spec,
    }
    path = revisions / f"{number:04d}_{safe_action}.json"
    atomic_json(path, payload)
    return {"revision": number, "path": str(path), "sha256": payload["world_spec_sha256"]}


def refresh_quality(world_dir: Path) -> dict[str, Any]:
    spec = load_contract(world_dir / "world_spec.json", "world_spec")
    profile = load_contract(world_dir / "quality_profile.json", "quality_profile")
    observations = json.loads((world_dir / "observations.json").read_text(encoding="utf-8"))
    report = build_quality_report(spec, profile, observations)
    atomic_json(world_dir / "quality_report.json", report)
    return report


def instantiate_template(
    *,
    root: Path,
    template_dir: Path,
    quality_profiles_dir: Path,
    asset_registry: Path,
    job_id: str,
    job_root: Path,
    display_name: str,
    materialize_artifacts: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    template_dir = template_dir.resolve()
    source_spec = load_contract(template_dir / "world_spec.json", "world_spec")
    source_observations = json.loads(
        (template_dir / "observations.json").read_text(encoding="utf-8")
    )
    source_profile = load_contract(
        quality_profiles_dir / f"{source_spec['quality_profile']}.json", "quality_profile"
    )
    source_registry = load_contract(asset_registry, "asset_registry")
    world_dir = job_root / "world"
    world_dir.mkdir(parents=True, exist_ok=True)

    spec = deepcopy(source_spec)
    template_scene_id = source_spec["scene_id"]
    spec["scene_id"] = _derived_scene_id(template_scene_id, job_id)
    spec["display_name"] = display_name
    spec["version"] = "v1"
    metadata = deepcopy(spec.get("metadata", {}))
    metadata.update(
        {
            "derived_from": template_scene_id,
            "derived_from_version": source_spec.get("version"),
            "instance_job_id": job_id,
            "instantiated_at": utc_now(),
            "contract_revision": 1,
        }
    )
    spec["metadata"] = metadata
    for gate in GATE_ORDER:
        spec["review_gates"][gate] = {
            "status": "pending",
            "evidence": [],
            "reviewer": "",
            "notes": f"Requires review for derived instance of {template_scene_id}",
        }

    artifact_mapping: dict[str, str] = {}
    path_mapping: dict[str, str] = {}
    if materialize_artifacts:
        for key, value in source_spec.get("artifacts", {}).items():
            source = _safe_source(root, value)
            if key == "blend":
                destination = world_dir / "world.blend"
            elif key in {"glb", "web_glb"}:
                destination = world_dir / "world.glb"
            else:
                destination = world_dir / "baseline" / source.name
                if destination.exists() and not os.path.samefile(source, destination):
                    destination = world_dir / "baseline" / f"{key}__{source.name}"
            _link_or_copy(source, destination)
            portable = _portable_path(destination, root)
            artifact_mapping[key] = portable
            path_mapping[value] = portable
    spec["artifacts"] = artifact_mapping

    evidence_candidates: dict[str, list[str]] = {gate: [] for gate in GATE_ORDER}
    if materialize_artifacts:
        for gate in GATE_ORDER:
            for value in source_spec["review_gates"][gate].get("evidence", []):
                if value in path_mapping:
                    evidence_candidates[gate].append(path_mapping[value])
                    continue
                source = _safe_source(root, value)
                destination = world_dir / "evidence" / f"{gate}__{source.name}"
                _link_or_copy(source, destination)
                portable = _portable_path(destination, root)
                path_mapping[value] = portable
                evidence_candidates[gate].append(portable)

    blend_path = artifact_mapping.get("blend")
    if blend_path:
        spec["layers"]["visual_geometry"]["sources"] = [blend_path]
        spec["layers"]["simulation_geometry"]["sources"] = [blend_path]

    source_plan_path = source_spec.get("measurement_plan")
    if source_plan_path:
        plan = load_contract(_safe_source(root, source_plan_path), "measurement_plan")
        plan = deepcopy(plan)
        plan["scene_id"] = spec["scene_id"]
        plan_path = world_dir / "measurement_plan.json"
        dump_contract(plan_path, plan, "measurement_plan")
        spec["measurement_plan"] = _portable_path(plan_path, root)
    else:
        spec.pop("measurement_plan", None)

    validate_contract(spec, "world_spec")
    dump_contract(world_dir / "world_spec.json", spec, "world_spec")
    dump_contract(world_dir / "quality_profile.json", source_profile, "quality_profile")
    dump_contract(world_dir / "asset_registry.json", source_registry, "asset_registry")
    observations = deepcopy(source_observations)
    observations["scene_id"] = spec["scene_id"]
    observations["geometry_source"] = (
        "inherited template baseline; run automatic measurement before approval"
    )
    atomic_json(world_dir / "observations.json", observations)
    report = refresh_quality(world_dir)
    revision = record_revision(
        world_dir,
        "instantiate",
        spec,
        {"template_scene_id": template_scene_id, "materialized_artifacts": materialize_artifacts},
    )
    return {
        "world_spec": spec,
        "quality_report": report,
        "evidence_candidates": evidence_candidates,
        "artifacts": artifact_mapping,
        "revision": revision,
    }


def transition_instance_gate(
    world_dir: Path,
    gate: str,
    status: str,
    *,
    evidence: list[str] | None,
    reviewer: str,
    notes: str,
) -> dict[str, Any]:
    spec = load_contract(world_dir / "world_spec.json", "world_spec")
    spec["review_gates"] = transition_gate(
        spec["review_gates"],
        gate,
        status,
        evidence=evidence,
        reviewer=reviewer,
        notes=notes,
    )
    metadata = spec.setdefault("metadata", {})
    metadata["contract_revision"] = int(metadata.get("contract_revision", 1)) + 1
    dump_contract(world_dir / "world_spec.json", spec, "world_spec")
    report = refresh_quality(world_dir)
    revision = record_revision(
        world_dir,
        f"gate_{gate}_{status}",
        spec,
        {"gate": gate, "status": status, "evidence": evidence or [], "reviewer": reviewer},
    )
    return {"world_spec": spec, "quality_report": report, "revision": revision}


def merge_geometry_observation(world_dir: Path, observation_path: Path) -> dict[str, Any]:
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    if observation.get("status") != "passed":
        raise InstanceError("Automatic Blender geometry observation failed")
    observations_path = world_dir / "observations.json"
    observations = json.loads(observations_path.read_text(encoding="utf-8"))
    if observation.get("scene_id") != observations.get("scene_id"):
        raise InstanceError("Geometry observation belongs to a different scene")
    observations["geometry"] = observation["geometry"]
    observations["geometry_source"] = observation_path.relative_to(world_dir).as_posix()
    atomic_json(observations_path, observations)
    spec = load_contract(world_dir / "world_spec.json", "world_spec")
    report = refresh_quality(world_dir)
    revision = record_revision(
        world_dir,
        "automatic_geometry_measurement",
        spec,
        {
            "observation": observation_path.relative_to(world_dir).as_posix(),
            "metrics": observation["geometry"],
        },
    )
    return {"observation": observation, "quality_report": report, "revision": revision}
