from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from .adapters import adapter_catalog
from .configuration import runtime_configuration
from .contracts import ContractError, dump_contract, load_contract
from .provenance import atomic_json, delivery_manifest

DEFAULT_OUTPUT = Path("outputs/frontier_valley")


def _plan(prompt: str, preset: str, seed: int) -> dict:
    return {
        "schema_version": 1,
        "preset": preset,
        "prompt": prompt,
        "seed": seed,
        "world": {
            "name": "The Greenwater Frontier",
            "extent_m": 260,
            "terrain_resolution": 385,
            "style": "grounded cinematic realism",
        },
        "regions": [
            {"id": "river", "label": "Greenwater River", "color": "#317fa8"},
            {"id": "village", "label": "Frontier Village", "color": "#b99861"},
            {"id": "forest", "label": "Pine Forest", "color": "#315b35"},
            {"id": "highlands", "label": "Rocky Highlands", "color": "#77746d"},
            {"id": "meadow", "label": "Open Meadow", "color": "#6d934a"},
        ],
        "landmarks": [
            {"type": "village", "position": [29, 23], "radius": 19},
            {"type": "bridge", "position": [7, 0]},
            {"type": "watchtower", "position": [42, 35]},
            {"type": "stone_circle", "position": [-43, 31]},
        ],
        "density": {
            "trees": 210,
            "alpine_trees": 90,
            "grass_patches": 140,
            "rocks": 90,
            "river_rocks": 115,
            "houses": 9,
        },
        "render": {"width": 1920, "height": 1080, "samples": 64, "cycles_samples": 64},
    }


def _world_spec(plan: dict) -> dict:
    extent = float(plan["world"]["extent_m"])
    half = extent / 2.0
    regions = [{"id": region["id"], "label": region["label"]} for region in plan["regions"]]
    landmarks = [
        {"id": f"landmark-{index:02d}-{landmark['type']}", "label": landmark["type"], **landmark}
        for index, landmark in enumerate(plan["landmarks"], start=1)
    ]
    pending_gate = {"status": "pending", "evidence": []}
    return {
        "$schema": "../../schemas/world_spec.v1.schema.json",
        "schema_version": 1,
        "kind": "world_spec",
        "scene_id": f"{plan['preset']}.seed-{plan['seed']}",
        "display_name": plan["world"]["name"],
        "version": "v1.0",
        "intent": {
            "simulation_use": "Local agent-navigation and visual world-generation validation",
            "visual_target": plan["world"]["style"],
        },
        "coordinate_system": {
            "units": "meter",
            "up_axis": "+Z",
            "handedness": "right",
            "horizontal_axes": {"x": "east", "y": "north"},
            "origin_m": [0, 0, 0],
            "crs": None,
        },
        "bounds": {
            "min_m": [-half, -half, -8],
            "max_m": [half, half, 72],
            "extent_m": [extent, extent, 80],
            "protected_geometry_band_m": 1,
        },
        "layers": {
            "reference": {
                "role": "Approved references constrain appearance and layout only",
                "authoritative": False,
                "sources": [],
            },
            "visual_geometry": {
                "role": "Renderable procedural world and validated generated assets",
                "authoritative": False,
                "sources": ["plan.json"],
            },
            "simulation_geometry": {
                "role": "Meter-scale authored terrain and collision proxies",
                "authoritative": True,
                "sources": ["plan.json"],
            },
            "navigation_truth": {
                "role": "Routes and traversable regions derived from explicit geometry",
                "authoritative": True,
                "sources": ["plan.json"],
            },
        },
        "geometry_policy": {
            "authoritative_shape_sources": ["procedural_geometry", "validated_asset"],
            "generated_images_role": "reference_only",
            "allow_panorama_shell_as_truth": False,
            "allow_monocular_depth_as_truth": False,
            "required_features": ["meter_scale", "separate_visual_and_simulation_layers"],
        },
        "topology": {"regions": regions, "landmarks": landmarks, "routes": []},
        "quality_profile": "paper_reproduction.v1",
        "review_gates": {
            "reference": dict(pending_gate),
            "graybox": dict(pending_gate),
            "materials": dict(pending_gate),
            "final": dict(pending_gate),
        },
        "assets": ["cc0_frontier_procedural_kit"],
        "artifacts": {
            "plan": "plan.json",
            "blend": "world.blend",
            "web": "world.glb",
            "delivery": "delivery_manifest.json",
        },
        "execution": {
            "mode": "rebuild",
            "builder": "scripts/build_world.py",
            "source": "plan.json",
            "arguments": ["--engine", "cycles"],
        },
        "metadata": {
            "prompt": plan["prompt"],
            "seed": plan["seed"],
            "paper_workflow_stages": [
                "structured_planning",
                "reference_generation",
                "segmentation",
                "asset_reconstruction",
                "world_assembly",
                "quality_gates",
            ],
        },
    }


def command_init(args: argparse.Namespace) -> int:
    target = args.output.expanduser().absolute()
    if target.exists() and not args.force:
        raise SystemExit(f"Configuration already exists: {target}; use --force to replace")
    content = """# WorldClaw local configuration\n[paths]\nmodels_dir = \"~/.cache/worldclaw/models\"\njobs_dir = \"outputs/web_jobs\"\n\n[runtime]\ngpu = \"0\"\n"""
    target.write_text(content, encoding="utf-8")
    print(target)
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    config = runtime_configuration()
    adapters = [
        status.__dict__ for status in (adapter.probe() for adapter in adapter_catalog(config))
    ]
    gpu = {"available": False, "devices": []}
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=True,
        )
        gpu = {
            "available": True,
            "devices": [line.strip() for line in result.stdout.splitlines() if line.strip()],
        }
    except (OSError, subprocess.SubprocessError):
        pass
    report = {
        "status": "ready" if adapters[0]["available"] else "core_ready",
        "configuration": config.jsonable(),
        "adapters": adapters,
        "gpu": gpu,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def command_plan(args: argparse.Namespace) -> int:
    output = args.output.expanduser().absolute()
    output.mkdir(parents=True, exist_ok=True)
    plan = _plan(args.prompt, args.preset, args.seed)
    plan_path = atomic_json(output / "plan.json", plan)
    spec_path = dump_contract(output / "world_spec.json", _world_spec(plan), "world_spec")
    print(json.dumps({"plan": str(plan_path), "world_spec": str(spec_path)}, ensure_ascii=False))
    return 0


def command_build(args: argparse.Namespace) -> int:
    config = runtime_configuration()
    blender = next(adapter for adapter in adapter_catalog(config) if adapter.id == "blender")
    output = args.output.expanduser().absolute()
    plan = (args.plan or output / "plan.json").expanduser().absolute()
    if not plan.is_file():
        raise SystemExit(f"Plan does not exist: {plan}")
    command = blender.command(
        [
            "--background",
            "--python",
            config.root / "scripts/build_world.py",
            "--",
            "--plan",
            plan,
            "--output",
            output,
            "--engine",
            args.engine,
            "--samples",
            str(args.samples),
        ]
    )
    environment = os.environ.copy()
    if args.engine == "cycles":
        environment["CUDA_VISIBLE_DEVICES"] = config.gpu
    subprocess.run(command, cwd=config.root, env=environment, check=True)
    return command_validate(argparse.Namespace(output=output, json=False))


def command_validate(args: argparse.Namespace) -> int:
    root = args.output.expanduser().absolute()
    checks: dict[str, bool] = {"directory": root.is_dir(), "plan": (root / "plan.json").is_file()}
    if (root / "world.blend").is_file():
        checks["blend_header"] = (root / "world.blend").read_bytes()[:7] == b"BLENDER"
    if (root / "world.glb").is_file():
        checks["glb_header"] = (root / "world.glb").read_bytes()[:4] == b"glTF"
    if (root / "world_spec.json").is_file():
        try:
            load_contract(root / "world_spec.json", "world_spec")
            checks["world_spec"] = True
        except ContractError:
            checks["world_spec"] = False
    report = {"status": "passed" if checks and all(checks.values()) else "failed", "checks": checks}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


def command_package(args: argparse.Namespace) -> int:
    root = args.output.expanduser().absolute()
    excluded = {"delivery_manifest.json"}
    files = [path for path in root.rglob("*") if path.is_file() and path.name not in excluded]
    scene_id = None
    if (root / "world_spec.json").is_file():
        scene_id = load_contract(root / "world_spec.json", "world_spec")["scene_id"]
    manifest = delivery_manifest(root, files, scene_id)
    target = atomic_json(root / "delivery_manifest.json", manifest)
    print(target)
    return 0


def command_resume(args: argparse.Namespace) -> int:
    endpoint = f"{args.server.rstrip('/')}/api/jobs/{args.job_id}/retry"
    token = args.token or os.environ.get("WORLDCLAW_API_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(endpoint, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            print(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SystemExit(f"Cannot resume job through {endpoint}: {exc}") from exc
    return 0


def command_serve(args: argparse.Namespace) -> int:
    token = os.environ.get("WORLDCLAW_API_TOKEN", "")
    if args.host not in {"127.0.0.1", "localhost", "::1"} and len(token) < 24:
        raise SystemExit(
            "Refusing non-loopback binding without WORLDCLAW_API_TOKEN (at least 24 characters)"
        )
    os.environ.setdefault("WORLDCLAW_HOST", args.host)
    os.environ.setdefault("WORLDCLAW_PORT", str(args.port))
    import uvicorn

    from webapp.backend.app import app

    uvicorn.run(app, host=args.host, port=args.port, workers=1)
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="WorldClaw clean-room paper reproduction")
    root.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    commands = root.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Create a portable local configuration")
    init.add_argument("--output", type=Path, default=Path(".worldclaw.toml"))
    init.add_argument("--force", action="store_true")
    init.set_defaults(handler=command_init)

    doctor = commands.add_parser("doctor", help="Inspect optional engines, models and GPU")
    doctor.set_defaults(handler=command_doctor)

    plan = commands.add_parser("plan", help="Create a deterministic structured plan")
    plan.add_argument("--prompt", required=True)
    plan.add_argument("--preset", default="frontier_valley")
    plan.add_argument("--seed", type=int, default=260805)
    plan.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    plan.set_defaults(handler=command_plan)

    build = commands.add_parser("build", help="Build an existing plan with Blender")
    build.add_argument("--plan", type=Path)
    build.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    build.add_argument("--engine", choices=("cycles", "eevee"), default="cycles")
    build.add_argument("--samples", type=int, default=64)
    build.set_defaults(handler=command_build)

    validate = commands.add_parser("validate", help="Validate a completed delivery")
    validate.add_argument("output", type=Path)
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(handler=command_validate)

    package = commands.add_parser("package", help="Create a hash-addressed delivery manifest")
    package.add_argument("output", type=Path)
    package.set_defaults(handler=command_package)

    resume = commands.add_parser("resume", help="Retry an interrupted Web Studio job")
    resume.add_argument("job_id")
    resume.add_argument("--server", default="http://127.0.0.1:7865")
    resume.add_argument("--token", help="API token; defaults to WORLDCLAW_API_TOKEN")
    resume.set_defaults(handler=command_resume)

    serve = commands.add_parser("serve", help="Start local Web Studio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=7865)
    serve.set_defaults(handler=command_serve)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return int(args.handler(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
