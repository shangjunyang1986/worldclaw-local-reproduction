#!/usr/bin/env python3
"""Measure rule geometry directly from the currently opened Blender scene."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from worldclaw_core.geometry import (
    circle_radial_error,
    line_deviation,
    planarity_error,
    verticality_error_deg,
)

AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def parse_args() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(values)


def world_point(obj: bpy.types.Object, coordinate: Vector) -> tuple[float, float, float]:
    value = obj.matrix_world @ coordinate
    return (float(value.x), float(value.y), float(value.z))


def require_mesh(name: str) -> bpy.types.Object:
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object is missing: {name}")
    if obj.type != "MESH" or not obj.data.vertices:
        raise ValueError(f"Object is not a measurable mesh: {name}")
    return obj


def axis_world_scale(obj: bpy.types.Object, axis: int) -> float:
    unit = Vector((1.0 if axis == 0 else 0.0, 1.0 if axis == 1 else 0.0, 1.0 if axis == 2 else 0.0))
    scale = (obj.matrix_world.to_3x3() @ unit).length
    if scale <= 0:
        raise ValueError(f"Object has a zero scale axis: {obj.name}")
    return float(scale)


def surface_planarity(obj: bpy.types.Object, probe: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    axis = AXIS_INDEX[probe["local_axis"]]
    values = [float(vertex.co[axis]) for vertex in obj.data.vertices]
    extreme = max(values) if probe["surface_side"] == "max" else min(values)
    local_tolerance = float(probe["surface_tolerance_m"]) / axis_world_scale(obj, axis)
    selected = [
        world_point(obj, vertex.co)
        for vertex in obj.data.vertices
        if abs(float(vertex.co[axis]) - extreme) <= local_tolerance
    ]
    if len(selected) < 3:
        raise ValueError(f"Surface selection has fewer than three points: {obj.name}")
    value = planarity_error(selected, probe["normal"])
    return value, {"selected_vertices": len(selected), "surface_coordinate_local": extreme}


def annulus_circle(obj: bpy.types.Object, probe: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    axes = [AXIS_INDEX[name] for name in probe["plane_axes"]]
    points = [world_point(obj, vertex.co) for vertex in obj.data.vertices]
    center_2d = [sum(point[axis] for point in points) / len(points) for axis in axes]
    expected_property = probe["expected_radius_property"]
    if expected_property not in obj:
        raise ValueError(f"Object {obj.name} lacks radius property {expected_property}")
    expected = float(obj[expected_property])
    selected_2d = []
    for point in points:
        projected = [point[axes[index]] for index in range(2)]
        radius = sum((projected[index] - center_2d[index]) ** 2 for index in range(2)) ** 0.5
        if abs(radius - expected) <= float(probe["radial_band_m"]):
            selected_2d.append((projected[0], projected[1], 0.0))
    if len(selected_2d) < 3:
        raise ValueError(f"Outer circle selection has fewer than three points: {obj.name}")
    center = (center_2d[0], center_2d[1], 0.0)
    value = circle_radial_error(selected_2d, center)
    return value, {
        "selected_vertices": len(selected_2d),
        "expected_radius_m": expected,
        "measured_center": center_2d,
    }


def centerline(
    obj: bpy.types.Object, probe: dict[str, Any]
) -> tuple[list[tuple[float, float, float]], dict[str, Any]]:
    axis = AXIS_INDEX[probe["local_axis"]]
    local_tolerance = float(probe["slice_tolerance_m"]) / axis_world_scale(obj, axis)
    groups: dict[int, list[Vector]] = {}
    for vertex in obj.data.vertices:
        key = round(float(vertex.co[axis]) / local_tolerance)
        groups.setdefault(key, []).append(vertex.co.copy())
    centers = []
    for key in sorted(groups):
        coordinates = groups[key]
        local_center = sum(coordinates, Vector((0.0, 0.0, 0.0))) / len(coordinates)
        centers.append(world_point(obj, local_center))
    if len(centers) < 2:
        raise ValueError(f"Centerline has fewer than two slices: {obj.name}")
    return centers, {"centerline_samples": len(centers)}


def measure_object(obj: bpy.types.Object, probe: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    method = probe["method"]
    if method == "mesh_surface_planarity":
        return surface_planarity(obj, probe)
    if method == "annulus_outer_circle":
        return annulus_circle(obj, probe)
    centers, details = centerline(obj, probe)
    if method == "mesh_centerline":
        return line_deviation(centers), details
    if method == "mesh_centerline_verticality":
        return verticality_error_deg(centers[0], centers[-1]), details
    raise ValueError(f"Unsupported geometry method: {method}")


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
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


def main() -> None:
    args = parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    results = []
    geometry: dict[str, float] = {}
    errors = []
    for probe in plan["probes"]:
        object_results = []
        for name in probe["objects"]:
            try:
                obj = require_mesh(name)
                value, details = measure_object(obj, probe)
                object_results.append({"object": name, "value": value, **details})
            except (KeyError, TypeError, ValueError) as exc:
                errors.append({"probe": probe["id"], "object": name, "error": str(exc)})
        if object_results:
            value = max(float(item["value"]) for item in object_results)
            geometry[probe["metric"]] = max(geometry.get(probe["metric"], 0.0), value)
            results.append(
                {
                    "id": probe["id"],
                    "metric": probe["metric"],
                    "method": probe["method"],
                    "aggregate": probe["aggregate"],
                    "value": value,
                    "objects": object_results,
                }
            )
    blend = Path(bpy.data.filepath).resolve()
    payload = {
        "schema_version": 1,
        "kind": "geometry_observation",
        "scene_id": plan["scene_id"],
        "status": "passed" if not errors and len(results) == len(plan["probes"]) else "failed",
        "source": {
            "blend": str(blend),
            "bytes": blend.stat().st_size if blend.is_file() else 0,
            "blender_version": bpy.app.version_string,
            "measurement_plan": str(args.plan.resolve()),
        },
        "geometry": geometry,
        "probes": results,
        "errors": errors,
    }
    atomic_json(args.output.resolve(), payload)
    print("WORLDCLAW_GEOMETRY_OBSERVATION=" + json.dumps(payload, ensure_ascii=False), flush=True)
    if payload["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
