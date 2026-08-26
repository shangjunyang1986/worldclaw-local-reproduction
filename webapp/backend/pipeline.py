from __future__ import annotations

import json
import queue
import shutil
import threading
import traceback
import zipfile
from pathlib import Path
from typing import Any

from .config import Settings
from .resources import capacity_check
from .runner import CommandRunner, JobCancelled
from .store import JobStore

QUALITY_PRESETS: dict[str, dict[str, int]] = {
    "preview": {
        "width": 960,
        "height": 540,
        "cycles": 16,
        "shape_steps": 20,
        "octree": 256,
        "views": 6,
        "texture": 512,
    },
    "standard": {
        "width": 1280,
        "height": 720,
        "cycles": 32,
        "shape_steps": 30,
        "octree": 256,
        "views": 6,
        "texture": 512,
    },
    "paper": {
        "width": 1920,
        "height": 1080,
        "cycles": 64,
        "shape_steps": 50,
        "octree": 384,
        "views": 9,
        "texture": 768,
    },
}

WORKFLOW_STAGES = {
    "template": ["instantiate", "quality_gates"],
    "existing": ["plan", "prepare_assets", "build", "validate", "package"],
    "full": [
        "plan",
        "prepare_assets",
        "segment",
        "review",
        "sam3d",
        "hunyuan_shape",
        "hunyuan_paint",
        "build",
        "validate",
        "package",
    ],
    "validate_existing": ["validate", "package"],
    "denver_regional": [
        "regional_plan",
        "regional_render",
        "regional_composition",
        "regional_segment",
        "regional_sam3d",
        "regional_hunyuan_shape",
        "regional_hunyuan_paint",
        "regional_refine",
        "regional_validate",
        "package",
    ],
}

GPU_STAGES = {
    "segment",
    "sam3d",
    "hunyuan_shape",
    "hunyuan_paint",
    "build",
    "regional_render",
    "regional_segment",
    "regional_sam3d",
    "regional_hunyuan_shape",
    "regional_hunyuan_paint",
    "regional_refine",
}

DEFAULT_PROMPTS = {
    "watchtower": "wooden medieval watchtower",
    "cottage": "rustic wooden cottage",
    "cottage_stone": "stone cottage",
    "bridge": "wooden bridge",
    "windmill": "wooden windmill",
}


class ReviewRequired(RuntimeError):
    pass


def default_plan(quality: str, layout: dict[str, Any] | None = None) -> dict[str, Any]:
    preset = QUALITY_PRESETS[quality]
    plan: dict[str, Any] = {
        "schema_version": 1,
        "preset": "frontier_valley",
        "seed": 260805,
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
        "render": {
            "width": preset["width"],
            "height": preset["height"],
            "samples": 128,
            "cycles_samples": preset["cycles"],
        },
    }
    if layout:
        for key in ("seed", "world", "landmarks", "density"):
            if key not in layout:
                continue
            if isinstance(plan.get(key), dict) and isinstance(layout[key], dict):
                plan[key].update(layout[key])
            else:
                plan[key] = layout[key]
    return plan


def job_paths(job: dict[str, Any]) -> dict[str, Path]:
    root = Path(job["output_dir"])
    return {
        "root": root,
        "input": root / "input",
        "segments": root / "segments",
        "sam3d": root / "sam3d",
        "generated": root / "generated",
        "world": root / "world",
        "logs": root / "logs",
    }


class Pipeline:
    def __init__(self, settings: Settings, store: JobStore):
        self.settings = settings
        self.store = store
        self.runner = CommandRunner(store, settings.root)

    def run_stage(self, job: dict[str, Any], stage: str) -> None:
        if self.settings.testing:
            self._testing_stage(job, stage)
            return
        handler = getattr(self, f"stage_{stage}")
        handler(job)

    def _testing_stage(self, job: dict[str, Any], stage: str) -> None:
        paths = job_paths(job)
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)
        if stage == "plan":
            (paths["world"] / "plan.json").write_text(
                json.dumps(default_plan(job["quality"])), encoding="utf-8"
            )
        elif stage == "segment":
            source = Path(job["source_image"])
            for asset_type, prompt in (
                job["config"].get("prompts") or {"watchtower": "watchtower"}
            ).items():
                target = paths["segments"] / asset_type
                target.mkdir(parents=True, exist_ok=True)
                image = target / "instance_000.png"
                mask = target / "instance_000_mask.png"
                shutil.copy2(source, image)
                shutil.copy2(source, mask)
                metadata = {
                    "asset_type": asset_type,
                    "prompt": prompt,
                    "instances": [
                        {
                            "instance": 0,
                            "score": 0.99,
                            "image": str(image.resolve()),
                            "mask": str(mask.resolve()),
                        }
                    ],
                }
                (target / "instances.json").write_text(json.dumps(metadata), encoding="utf-8")
        elif (
            stage == "review"
            and job["config"].get("review_mode") == "manual"
            and not job["config"].get("selected_masks")
        ):
            raise ReviewRequired
        elif stage == "validate":
            (paths["world"] / "validation.json").write_text(
                '{"status":"passed"}\n', encoding="utf-8"
            )
        elif stage == "regional_plan":
            shutil.copy2(
                self.settings.root / "configs/denver_regional_reproduction.json",
                paths["world"] / "regional_plan.json",
            )
        elif stage == "regional_render":
            (paths["input"] / "camera.json").write_text('{"testing":true}\n', encoding="utf-8")
            (paths["input"] / "base_render.png").write_bytes(b"testing")
        elif stage == "regional_composition":
            (paths["input"] / "composition.png").write_bytes(b"testing")
        elif stage == "regional_segment":
            target = paths["segments"] / "arff_crash_tender"
            target.mkdir(parents=True, exist_ok=True)
            (target / "instance_000.png").write_bytes(b"testing")
            (target / "instance_000_mask.png").write_bytes(b"testing")
            (target / "instances.json").write_text(
                '{"instances":[{"instance":0,"score":0.99}]}\n', encoding="utf-8"
            )
        elif stage == "regional_sam3d":
            (paths["sam3d"] / "arff_crash_tender.layout.json").write_text(
                '{"rotation":[],"translation":[],"scale":[]}\n', encoding="utf-8"
            )
        elif stage in {"regional_hunyuan_shape", "regional_hunyuan_paint"}:
            (paths["generated"] / f"{stage}.glb").write_bytes(b"glTFtesting")
        elif stage == "regional_refine":
            (paths["world"] / "denver_airport_worldclaw_regional.glb").write_bytes(b"glTFtesting")
            (paths["world"] / "refinement_report.json").write_text(
                '{"status":"passed"}\n', encoding="utf-8"
            )
        elif stage == "regional_validate":
            (paths["world"] / "validation.json").write_text(
                '{"status":"passed","workflow":"denver_regional"}\n', encoding="utf-8"
            )
        elif stage == "package":
            (paths["root"] / "delivery_manifest.json").write_text(
                '{"testing":true}\n', encoding="utf-8"
            )
        self.runner.log(job, stage, "Testing stage completed")

    def stage_plan(self, job: dict[str, Any]) -> None:
        paths = job_paths(job)
        paths["world"].mkdir(parents=True, exist_ok=True)
        plan = default_plan(job["quality"], job["config"].get("layout"))
        (paths["world"] / "plan.json").write_text(
            json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        self.runner.log(job, "plan", f"World plan written: {paths['world'] / 'plan.json'}")

    def stage_prepare_assets(self, job: dict[str, Any]) -> None:
        target = job_paths(job)["generated"]
        target.mkdir(parents=True, exist_ok=True)
        source = self.settings.root / "assets/generated"
        for asset in source.iterdir():
            destination = target / asset.name
            if not destination.exists() and not destination.is_symlink():
                destination.symlink_to(asset.resolve())
        self.runner.log(job, "prepare_assets", f"Linked verified fallback assets from {source}")

    def stage_regional_plan(self, job: dict[str, Any]) -> None:
        paths = job_paths(job)
        paths["world"].mkdir(parents=True, exist_ok=True)
        source = self.settings.root / "configs/denver_regional_reproduction.json"
        destination = paths["world"] / "regional_plan.json"
        shutil.copy2(source, destination)
        self.runner.log(job, "regional_plan", f"Frozen Denver regional plan: {destination}")

    def stage_regional_render(self, job: dict[str, Any]) -> None:
        paths = job_paths(job)
        plan_path = paths["world"] / "regional_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        source_blend = self.settings.root / plan["scene"]["source_blend"]
        if not source_blend.is_file():
            raise FileNotFoundError(f"Denver source world is missing: {source_blend}")
        render = plan["base_render"]
        self.runner.run(
            job,
            "regional_render",
            [
                self.settings.blender,
                source_blend,
                "--background",
                "--python",
                self.settings.root / "scripts/render_worldclaw_region.py",
                "--",
                "--plan",
                plan_path,
                "--output",
                paths["input"],
                "--engine",
                render["engine"],
                "--samples",
                str(render["samples"]),
            ],
            env={"CUDA_VISIBLE_DEVICES": self.settings.gpu},
        )

    def stage_regional_composition(self, job: dict[str, Any]) -> None:
        paths = job_paths(job)
        destination = paths["input"] / "composition.png"
        uploaded = Path(job["source_image"]) if job.get("source_image") else None
        source = (
            uploaded
            if uploaded and uploaded.is_file()
            else (
                self.settings.root
                / "outputs/denver_worldclaw_reproduction/region/concourse_b_west_apron/composition.png"
            )
        )
        if not source.is_file():
            raise FileNotFoundError("The verified Denver composition preset is missing")
        shutil.copy2(source, destination)
        mode = "uploaded composition" if uploaded else "verified frozen Denver composition"
        self.runner.log(job, "regional_composition", f"Using {mode}: {destination}")

    def stage_regional_segment(self, job: dict[str, Any]) -> None:
        paths = job_paths(job)
        plan_path = paths["world"] / "regional_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        spec = plan["objects"][0]
        output = paths["segments"] / spec["id"]
        self.runner.run(
            job,
            "regional_segment",
            [
                self.settings.sam3_python,
                self.settings.root / "scripts/segment_with_sam3.py",
                "--image",
                paths["input"] / "composition.png",
                "--prompt",
                spec["segmentation_prompt"],
                "--output-dir",
                output,
                "--score-threshold",
                str(spec["minimum_sam3_score"]),
            ],
            env={"CUDA_VISIBLE_DEVICES": self.settings.gpu},
        )
        metadata = json.loads((output / "instances.json").read_text(encoding="utf-8"))
        instances = metadata.get("instances", [])
        if not instances:
            raise RuntimeError("SAM3 did not find the Denver ARFF vehicle")
        selected = max(instances, key=lambda item: float(item["score"]))
        stem = f"instance_{int(selected['instance']):03d}"
        config = job["config"]
        config["regional_selection"] = {
            "image": str((output / f"{stem}.png").resolve()),
            "mask": str((output / f"{stem}_mask.png").resolve()),
            "score": float(selected["score"]),
        }
        self.store.update_config(job["id"], config)
        self.runner.run(
            job,
            "regional_segment",
            [
                self.settings.web_python,
                self.settings.root / "scripts/freeze_composition_metadata.py",
                "--plan",
                plan_path,
                "--base",
                paths["input"] / "base_render.png",
                "--composition",
                paths["input"] / "composition.png",
                "--mask",
                config["regional_selection"]["mask"],
                "--output",
                paths["input"] / "composition.json",
            ],
        )

    def stage_regional_sam3d(self, job: dict[str, Any]) -> None:
        selected = job["config"].get("regional_selection")
        if not selected:
            raise RuntimeError("Denver regional SAM3 selection is missing")
        output = job_paths(job)["sam3d"] / "arff_crash_tender"
        self.runner.run(
            job,
            "regional_sam3d",
            [
                self.settings.sam3d_python,
                self.settings.root / "scripts/reconstruct_with_sam3d.py",
                "--image",
                selected["image"],
                "--mask",
                selected["mask"],
                "--output",
                output,
            ],
            env={"CUDA_VISIBLE_DEVICES": self.settings.gpu},
        )

    def stage_regional_hunyuan_shape(self, job: dict[str, Any]) -> None:
        selected = job["config"].get("regional_selection")
        if not selected:
            raise RuntimeError("Denver regional SAM3 selection is missing")
        paths = job_paths(job)
        output = paths["generated"] / "arff_crash_tender_omni_shape.glb"
        paper = QUALITY_PRESETS["paper"]
        omni_model = self.settings.hunyuan_omni_model
        if (
            not (omni_model / "model/pytorch_model.bin").is_file()
            or not (omni_model / "vae/pytorch_model.bin").is_file()
        ):
            raise FileNotFoundError("Hunyuan3D-Omni point-control weights are incomplete")
        self.runner.run(
            job,
            "regional_hunyuan_shape",
            [
                self.settings.hunyuan_python,
                self.settings.root / "scripts/generate_hunyuan_omni_asset.py",
                "--image",
                selected["image"],
                "--coarse-mesh",
                paths["sam3d"] / "arff_crash_tender.glb",
                "--output",
                output,
                "--model",
                omni_model,
                "--steps",
                str(paper["shape_steps"]),
                "--octree-resolution",
                "512",
            ],
            env={"CUDA_VISIBLE_DEVICES": self.settings.gpu},
        )

    def stage_regional_hunyuan_paint(self, job: dict[str, Any]) -> None:
        selected = job["config"].get("regional_selection")
        if not selected:
            raise RuntimeError("Denver regional SAM3 selection is missing")
        paths = job_paths(job)
        paper = QUALITY_PRESETS["paper"]
        self.runner.run(
            job,
            "regional_hunyuan_paint",
            [
                self.settings.hunyuan_python,
                self.settings.root / "scripts/paint_hunyuan_asset.py",
                "--mesh",
                paths["generated"] / "arff_crash_tender_omni_shape.glb",
                "--image",
                selected["image"],
                "--output",
                paths["generated"] / "arff_crash_tender_omni_pbr.glb",
                "--views",
                str(paper["views"]),
                "--resolution",
                str(paper["texture"]),
            ],
            env={"CUDA_VISIBLE_DEVICES": self.settings.gpu},
        )

    def stage_regional_refine(self, job: dict[str, Any]) -> None:
        paths = job_paths(job)
        selected = job["config"].get("regional_selection")
        if not selected:
            raise RuntimeError("Denver regional SAM3 selection is missing")
        plan_path = paths["world"] / "regional_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        source_blend = self.settings.root / plan["scene"]["source_blend"]
        placement = paths["input"] / "placement_observation.json"
        self.runner.run(
            job,
            "regional_refine",
            [
                self.settings.web_python,
                self.settings.root / "scripts/derive_region_placement.py",
                "--plan",
                plan_path,
                "--camera",
                paths["input"] / "camera.json",
                "--mask",
                selected["mask"],
                "--sam3d-layout",
                paths["sam3d"] / "arff_crash_tender.layout.json",
                "--output",
                placement,
            ],
        )
        self.runner.run(
            job,
            "regional_refine",
            [
                self.settings.blender,
                source_blend,
                "--background",
                "--python",
                self.settings.root / "scripts/refine_worldclaw_region.py",
                "--",
                "--plan",
                plan_path,
                "--placement",
                placement,
                "--asset",
                paths["generated"] / "arff_crash_tender_omni_pbr.glb",
                "--output",
                paths["world"],
                "--samples",
                str(QUALITY_PRESETS["paper"]["cycles"]),
            ],
            env={"CUDA_VISIBLE_DEVICES": self.settings.gpu},
        )

    def stage_regional_validate(self, job: dict[str, Any]) -> None:
        paths = job_paths(job)
        selected = job["config"].get("regional_selection")
        if not selected:
            raise RuntimeError("Denver regional SAM3 selection is missing")
        self.runner.run(
            job,
            "regional_validate",
            [
                self.settings.web_python,
                self.settings.root / "scripts/validate_worldclaw_regional.py",
                paths["root"],
                "--plan",
                paths["world"] / "regional_plan.json",
                "--base",
                paths["input"] / "base_render.png",
                "--composition",
                paths["input"] / "composition.png",
                "--mask",
                selected["mask"],
                "--instances",
                paths["segments"] / "arff_crash_tender/instances.json",
                "--sam3d-layout",
                paths["sam3d"] / "arff_crash_tender.layout.json",
                "--sam3d-mesh",
                paths["sam3d"] / "arff_crash_tender.glb",
                "--omni-shape",
                paths["generated"] / "arff_crash_tender_omni_shape.glb",
                "--omni-metadata",
                paths["generated"] / "arff_crash_tender_omni_shape.omni.json",
                "--asset",
                paths["generated"] / "arff_crash_tender_omni_pbr.glb",
                "--world",
                paths["world"],
            ],
        )

    def stage_segment(self, job: dict[str, Any]) -> None:
        source = Path(job["source_image"] or "")
        if not source.is_file():
            raise FileNotFoundError("A source image is required for the full workflow")
        prompts = job["config"].get("prompts") or DEFAULT_PROMPTS
        command: list[str | Path] = [
            self.settings.sam3_python,
            self.settings.root / "scripts/segment_with_sam3_batch.py",
            "--image",
            source,
            "--output-dir",
            job_paths(job)["segments"],
            "--score-threshold",
            str(job["config"].get("score_threshold", 0.35)),
        ]
        for asset_type, prompt in prompts.items():
            command += ["--prompt", f"{asset_type}={prompt}"]
        self.runner.run(job, "segment", command, env={"CUDA_VISIBLE_DEVICES": self.settings.gpu})

    def _available_instances(self, job: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        records: dict[str, list[dict[str, Any]]] = {}
        segments = job_paths(job)["segments"]
        for metadata in sorted(segments.glob("*/instances.json")):
            data = json.loads(metadata.read_text(encoding="utf-8"))
            records[data["asset_type"]] = data.get("instances", [])
        return records

    def stage_review(self, job: dict[str, Any]) -> None:
        config = job["config"]
        selected = config.get("selected_masks")
        if selected:
            self.runner.log(job, "review", f"Using {len(selected)} approved masks")
            return
        available = self._available_instances(job)
        if config.get("review_mode", "manual") == "manual":
            self.runner.log(job, "review", "Waiting for mask approval in the web interface")
            raise ReviewRequired
        selected = {
            asset_type: {
                "image": instances[0]["image"],
                "mask": instances[0]["mask"],
                "score": instances[0]["score"],
            }
            for asset_type, instances in available.items()
            if instances
        }
        if not selected:
            raise RuntimeError("SAM3 did not produce any masks above the score threshold")
        config["selected_masks"] = selected
        self.store.update_config(job["id"], config)
        self.runner.log(
            job, "review", f"Automatically approved {len(selected)} highest-score masks"
        )

    def stage_sam3d(self, job: dict[str, Any]) -> None:
        selected = job["config"].get("selected_masks", {})
        requested = job["config"].get("sam3d_assets") or list(selected)[:1]
        if not requested:
            self.runner.log(job, "sam3d", "No approved mask; SAM3D audit skipped")
            return
        for asset_type in requested:
            if asset_type not in selected:
                continue
            spec = selected[asset_type]
            output = job_paths(job)["sam3d"] / asset_type
            self.runner.run(
                job,
                "sam3d",
                [
                    self.settings.sam3d_python,
                    self.settings.root / "scripts/reconstruct_with_sam3d.py",
                    "--image",
                    spec["image"],
                    "--mask",
                    spec["mask"],
                    "--output",
                    output,
                ],
                env={"CUDA_VISIBLE_DEVICES": self.settings.gpu},
            )

    def stage_hunyuan_shape(self, job: dict[str, Any]) -> None:
        selected = job["config"].get("selected_masks", {})
        if not selected:
            raise RuntimeError("No approved masks are available for Hunyuan3D")
        preset = QUALITY_PRESETS[job["quality"]]
        generated = job_paths(job)["generated"]
        command: list[str | Path] = [
            self.settings.hunyuan_python,
            self.settings.root / "scripts/generate_hunyuan_assets.py",
            "--steps",
            str(preset["shape_steps"]),
            "--octree-resolution",
            str(preset["octree"]),
            "--seed",
            str(job["config"].get("seed", 260805)),
        ]
        for asset_type, spec in selected.items():
            command += ["--asset", f"{spec['image']}={generated / (asset_type + '_mesh.glb')}"]
        self.runner.run(
            job, "hunyuan_shape", command, env={"CUDA_VISIBLE_DEVICES": self.settings.gpu}
        )

    def stage_hunyuan_paint(self, job: dict[str, Any]) -> None:
        selected = job["config"].get("selected_masks", {})
        preset = QUALITY_PRESETS[job["quality"]]
        generated = job_paths(job)["generated"]
        command: list[str | Path] = [
            self.settings.hunyuan_python,
            self.settings.root / "scripts/paint_hunyuan_assets.py",
            "--views",
            str(preset["views"]),
            "--resolution",
            str(preset["texture"]),
        ]
        for asset_type, spec in selected.items():
            output = generated / f"{asset_type}_pbr.glb"
            # The per-job asset directory initially contains symlinked fallbacks.
            # Remove every painter output alias so Hunyuan never writes through a
            # symlink into the repository's verified master assets.
            for suffix in (".glb", ".obj", ".mtl", ".jpg", "_metallic.jpg", "_roughness.jpg"):
                candidate = generated / f"{asset_type}_pbr{suffix}"
                if candidate.is_symlink():
                    candidate.unlink()
            command += [
                "--asset",
                f"{generated / (asset_type + '_mesh.glb')}={spec['image']}={output}",
            ]
        self.runner.run(
            job, "hunyuan_paint", command, env={"CUDA_VISIBLE_DEVICES": self.settings.gpu}
        )

    def stage_build(self, job: dict[str, Any]) -> None:
        paths = job_paths(job)
        preset = QUALITY_PRESETS[job["quality"]]
        command: list[str | Path] = [
            self.settings.blender,
            "--background",
            "--python",
            self.settings.root / "scripts/build_world.py",
            "--",
            "--plan",
            paths["world"] / "plan.json",
            "--output",
            paths["world"],
            "--asset-dir",
            paths["generated"],
            "--engine",
            "cycles",
            "--samples",
            str(preset["cycles"]),
        ]
        self.runner.run(job, "build", command, env={"CUDA_VISIBLE_DEVICES": self.settings.gpu})

    def stage_validate(self, job: dict[str, Any]) -> None:
        world = job_paths(job)["world"]
        if job["workflow"] == "validate_existing":
            world = Path(job["config"].get("existing_world", ""))
        self.runner.run(
            job,
            "validate",
            [self.settings.web_python, self.settings.root / "scripts/validate_outputs.py", world],
        )
        manifest = json.loads((world / "manifest.json").read_text(encoding="utf-8"))
        plan = json.loads((world / "plan.json").read_text(encoding="utf-8"))
        report = {
            "status": "passed",
            "objects": manifest.get("objects"),
            "meshes": manifest.get("meshes"),
            "hunyuan_asset_used": manifest.get("hunyuan_asset_used"),
            "render_size": [plan["render"]["width"], plan["render"]["height"]],
        }
        paths = job_paths(job)
        paths["world"].mkdir(parents=True, exist_ok=True)
        (paths["world"] / "validation.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

    def stage_package(self, job: dict[str, Any]) -> None:
        paths = job_paths(job)
        source = paths["world"]
        if job["workflow"] == "validate_existing":
            source = Path(job["config"].get("existing_world", ""))
        if job["workflow"] == "denver_regional":
            wanted = [
                "regional_plan.json",
                "placement_observation.json",
                "manifest.json",
                "refinement_report.json",
                "validation.json",
                "renders/regional_refined.png",
                "renders/regional_delivery_hero.png",
                "renders/regional_instance.png",
                "renders/regional_normal.png",
                "renders/regional_depth.png",
                "denver_airport_worldclaw_regional.blend",
                "denver_airport_worldclaw_regional.glb",
            ]
        else:
            wanted = [
                "plan.json",
                "manifest.json",
                "validation.json",
                "global.png",
                "walk_village.png",
                "walk_river.png",
                "tower_close.png",
                "semantic_layout.png",
                "world.blend",
                "world.glb",
            ]
        files = [source / name for name in wanted if (source / name).is_file()]
        local_validation = paths["world"] / "validation.json"
        if local_validation.is_file() and local_validation not in files:
            files.append(local_validation)
        delivery_manifest = {
            "job_id": job["id"],
            "workflow": job["workflow"],
            "quality": job["quality"],
            "files": [
                {"name": file.relative_to(source).as_posix(), "bytes": file.stat().st_size}
                for file in files
            ],
        }
        manifest_path = paths["root"] / "delivery_manifest.json"
        manifest_path.write_text(json.dumps(delivery_manifest, indent=2) + "\n", encoding="utf-8")
        if not job["config"].get("make_archive", False):
            self.runner.log(job, "package", "Archive disabled; delivery manifest written")
            return
        archive = paths["root"] / "delivery.zip"
        with zipfile.ZipFile(
            archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True
        ) as bundle:
            bundle.write(manifest_path, manifest_path.name)
            for file in files:
                bundle.write(file, file.relative_to(source).as_posix())
        self.runner.log(job, "package", f"Archive created: {archive}")


class JobManager:
    def __init__(self, settings: Settings, store: JobStore):
        self.settings = settings
        self.store = store
        self.pipeline = Pipeline(settings, store)
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._queued: set[str] = set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._current_job_id: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._worker, name="worldclaw-gpu-worker", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if not self._thread:
            return
        if self._current_job_id:
            self.store.request_cancel(self._current_job_id)
        while True:
            try:
                pending = self._queue.get_nowait()
            except queue.Empty:
                break
            if pending:
                self.store.update_job(
                    pending, state="interrupted", error="Web service stopped before execution"
                )
        self._queue.put(None)
        self._thread.join(timeout=20)

    def enqueue(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job["state"] in {"running", "queued", "succeeded", "cancelled"}:
            return job
        self.store.update_job(job_id, state="queued", error=None, cancel_requested=False)
        with self._lock:
            if job_id not in self._queued:
                self._queued.add(job_id)
                self._queue.put(job_id)
        return self.store.get_job(job_id)

    def resource_status(self) -> dict[str, Any]:
        with self._lock:
            current = self._current_job_id
            queued = self._queue.qsize()
        return {
            "gpu": capacity_check(self.settings.gpu, self.settings.min_free_vram_mib),
            "current_job_id": current,
            "queued_jobs": queued,
            "policy": "single_worker_serial_gpu_stages",
        }

    def _worker(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is None:
                return
            with self._lock:
                self._queued.discard(job_id)
                self._current_job_id = job_id
            try:
                self._run_job(job_id)
            finally:
                with self._lock:
                    self._current_job_id = None

    def _run_job(self, job_id: str) -> None:
        job = self.store.update_job(job_id, state="running", error=None)
        try:
            for stage_record in job["stages"]:
                if stage_record["state"] in {"succeeded", "skipped"}:
                    continue
                stage = stage_record["name"]
                current = self.store.get_job(job_id)
                if current["cancel_requested"]:
                    raise JobCancelled("Job cancelled by user")
                if not self.settings.testing and stage in GPU_STAGES:
                    gpu = capacity_check(self.settings.gpu, self.settings.min_free_vram_mib)
                    if not gpu["capacity_ok"]:
                        raise RuntimeError(
                            f"GPU {gpu['index']} capacity gate blocked {stage}: "
                            f"{gpu.get('free_mib', 0)} MiB free, "
                            f"{gpu['minimum_free_mib']} MiB required"
                        )
                self.store.update_stage(job_id, stage, "running")
                try:
                    self.pipeline.run_stage(current, stage)
                except ReviewRequired:
                    self.store.update_stage(job_id, stage, "waiting", "Select masks to continue")
                    self.store.update_job(job_id, state="awaiting_review")
                    return
                self.store.update_stage(job_id, stage, "succeeded")
            self.store.update_job(job_id, state="succeeded", current_stage=None, process_pid=None)
        except JobCancelled as exc:
            current = self.store.get_job(job_id)
            stage = current.get("current_stage")
            if stage:
                self.store.update_stage(job_id, stage, "cancelled", str(exc))
            self.store.update_job(job_id, state="cancelled", error=str(exc), process_pid=None)
        except Exception as exc:
            current = self.store.get_job(job_id)
            stage = current.get("current_stage")
            message = f"{type(exc).__name__}: {exc}"
            if stage:
                self.store.update_stage(job_id, stage, "failed", message)
            self.pipeline.runner.log(current, stage or "system", traceback.format_exc())
            self.store.update_job(job_id, state="failed", error=message, process_pid=None)
