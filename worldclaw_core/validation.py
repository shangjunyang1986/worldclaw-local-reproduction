from __future__ import annotations

from typing import Any

from .gates import gate_summary

METRIC_RULES = {
    "planarity_error_m": ("max_planarity_error_m", "max"),
    "circle_radial_error_m": ("max_circle_radial_error_m", "max"),
    "line_deviation_m": ("max_line_deviation_m", "max"),
    "verticality_error_deg": ("max_verticality_error_deg", "max"),
    "ground_contact_error_m": ("max_ground_contact_error_m", "max"),
    "collision_clearance_m": ("min_collision_clearance_m", "min"),
}


def _measurement_result(name: str, value: float, thresholds: dict[str, float]) -> dict[str, Any]:
    threshold_name, direction = METRIC_RULES[name]
    if threshold_name not in thresholds:
        return {
            "metric": name,
            "value": value,
            "status": "failed",
            "reason": f"missing threshold {threshold_name}",
        }
    threshold = float(thresholds[threshold_name])
    passed = value <= threshold if direction == "max" else value >= threshold
    return {
        "metric": name,
        "value": value,
        "threshold": threshold,
        "operator": "<=" if direction == "max" else ">=",
        "status": "passed" if passed else "failed",
    }


def build_quality_report(
    world_spec: dict[str, Any],
    profile: dict[str, Any],
    observations: dict[str, Any],
) -> dict[str, Any]:
    geometry = profile["geometry"]
    observed_metrics = observations.get("geometry", {})
    metric_results = []
    for name in geometry["required_metrics"]:
        if name not in observed_metrics:
            metric_results.append(
                {"metric": name, "status": "failed", "reason": "required measurement missing"}
            )
        else:
            metric_results.append(
                _measurement_result(name, float(observed_metrics[name]), geometry["thresholds"])
            )

    render_observed = observations.get("render", {})
    render_expected = profile["render"]
    render_checks = {
        "engine": render_expected["engine"] == "ANY"
        or render_observed.get("engine") == render_expected["engine"],
        "width": int(render_observed.get("width", 0)) >= render_expected["min_width"],
        "height": int(render_observed.get("height", 0)) >= render_expected["min_height"],
        "samples": int(render_observed.get("samples", 0)) >= render_expected["min_samples"],
        "views": int(render_observed.get("views", 0)) >= render_expected["min_views"],
    }

    required_checks = set(
        profile["visual"]["required_checks"] + profile["simulation"]["required_checks"]
    )
    observed_checks = observations.get("checks", {})
    check_results = {name: observed_checks.get(name) is True for name in sorted(required_checks)}

    web_observed = observations.get("web", {})
    web_expected = profile["web"]
    web_checks = {
        "draw_calls": int(web_observed.get("draw_calls", web_expected["max_draw_calls"] + 1))
        <= web_expected["max_draw_calls"],
        "glb_bytes": int(web_observed.get("glb_bytes", web_expected["max_glb_bytes"] + 1))
        <= web_expected["max_glb_bytes"],
        "fallback_frames": int(web_observed.get("fallback_frames", 0))
        >= web_expected["min_fallback_frames"],
        "meshopt": (not web_expected["require_meshopt"]) or web_observed.get("meshopt") is True,
    }

    gates = gate_summary(world_spec["review_gates"], profile["gates"]["require_all_approved"])
    groups = {
        "geometry": all(item["status"] == "passed" for item in metric_results),
        "render": all(render_checks.values()),
        "required_checks": all(check_results.values()),
        "web": all(web_checks.values()),
        "gates": gates["status"] == "passed",
    }
    return {
        "schema_version": 1,
        "scene_id": world_spec["scene_id"],
        "profile_id": profile["profile_id"],
        "status": "passed" if all(groups.values()) else "failed",
        "groups": groups,
        "geometry": metric_results,
        "render": {"observed": render_observed, "checks": render_checks},
        "checks": check_results,
        "web": {"observed": web_observed, "checks": web_checks},
        "review_gates": gates,
        "quality_boundary": "Reference imagery, visual geometry, simulation geometry and navigation truth are evaluated as separate layers.",
    }
