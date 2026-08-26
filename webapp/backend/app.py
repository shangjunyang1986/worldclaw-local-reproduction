from __future__ import annotations

import asyncio
import hmac
import json
import mimetypes
import shutil
import subprocess
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from worldclaw_core.contracts import ContractError, load_contract
from worldclaw_core.gates import GATE_ORDER, GateTransitionError
from worldclaw_core.instances import (
    InstanceError,
    atomic_json,
    instantiate_template,
    merge_geometry_observation,
    transition_instance_gate,
)
from worldclaw_core.registry import AssetRegistry

from .config import Settings
from .config import settings as default_settings
from .pipeline import DEFAULT_PROMPTS, QUALITY_PRESETS, WORKFLOW_STAGES, JobManager, job_paths
from .store import TERMINAL_STATES, JobStore

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _inside(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise HTTPException(400, "Path escapes the job directory") from exc
    return resolved


def _job_or_404(store: JobStore, job_id: str) -> dict[str, Any]:
    try:
        return store.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(404, "Job not found") from exc


def _template_dir(templates_dir: Path, scene_id: str) -> Path:
    for path in templates_dir.glob("*/world_spec.json"):
        try:
            spec = load_contract(path, "world_spec")
        except ContractError:
            continue
        if spec["scene_id"] == scene_id:
            return path.parent
    raise HTTPException(404, "Scene template not found")


def create_app(app_settings: Settings = default_settings) -> FastAPI:
    app_settings.prepare()
    store = JobStore(app_settings.database)
    manager = JobManager(app_settings, store)
    contract_lock = threading.RLock()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        manager.start()
        yield
        manager.stop()

    app = FastAPI(title="WorldClaw Studio", version="1.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.store = store
    app.state.manager = manager

    @app.middleware("http")
    async def protect_api(request: Request, call_next):
        token = app_settings.api_token
        if token and request.url.path.startswith("/api"):
            authorization = request.headers.get("authorization", "")
            bearer = authorization[7:] if authorization.lower().startswith("bearer ") else ""
            supplied = (
                bearer
                or request.headers.get("x-worldclaw-token", "")
                or request.query_params.get("token", "")
                or request.cookies.get("worldclaw_token", "")
            )
            if not supplied or not hmac.compare_digest(supplied, token):
                return JSONResponse({"detail": "WorldClaw API token required"}, status_code=401)
            response = await call_next(request)
            if request.cookies.get("worldclaw_token") != token:
                response.set_cookie(
                    "worldclaw_token",
                    token,
                    httponly=True,
                    samesite="strict",
                    secure=request.url.scheme == "https",
                    max_age=12 * 60 * 60,
                )
            return response
        return await call_next(request)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        checks = {
            "blender": app_settings.blender.is_file(),
            "sam3_python": app_settings.sam3_python.is_file(),
            "sam3_checkpoint": app_settings.sam3_checkpoint.is_file(),
            "sam3d_python": app_settings.sam3d_python.is_file(),
            "sam3d_checkpoint": app_settings.sam3d_checkpoint.is_file(),
            "hunyuan_python": app_settings.hunyuan_python.is_file(),
            "hunyuan_model": app_settings.hunyuan_model.is_dir(),
            "hunyuan_omni_model": (
                app_settings.hunyuan_omni_model / "model/pytorch_model.bin"
            ).is_file()
            and (app_settings.hunyuan_omni_model / "vae/pytorch_model.bin").is_file(),
            "world_contracts": app_settings.templates_dir.is_dir()
            and app_settings.quality_profiles_dir.is_dir(),
            "asset_registry": app_settings.asset_registry.is_file(),
        }
        resources = manager.resource_status()
        return {
            "status": "ready" if all(checks.values()) else "degraded",
            "checks": checks,
            "gpu": resources["gpu"],
            "resources": resources,
            "quality_presets": QUALITY_PRESETS,
        }

    @app.get("/api/resources")
    def resources() -> dict[str, Any]:
        return manager.resource_status()

    @app.get("/api/defaults")
    def defaults() -> dict[str, Any]:
        return {
            "prompts": DEFAULT_PROMPTS,
            "quality_presets": QUALITY_PRESETS,
            "workflows": WORKFLOW_STAGES,
        }

    @app.get("/api/catalog")
    def catalog() -> dict[str, Any]:
        profiles = []
        for path in sorted(app_settings.quality_profiles_dir.glob("*.json")):
            try:
                profile = load_contract(path, "quality_profile")
            except ContractError as exc:
                profiles.append({"path": str(path), "status": "invalid", "error": str(exc)})
                continue
            profiles.append(
                {
                    "profile_id": profile["profile_id"],
                    "label": profile["label"],
                    "render": profile["render"],
                    "status": "valid",
                }
            )
        templates = []
        for path in sorted(app_settings.templates_dir.glob("*/world_spec.json")):
            try:
                spec = load_contract(path, "world_spec")
            except ContractError as exc:
                templates.append({"path": str(path), "status": "invalid", "error": str(exc)})
                continue
            report_path = path.with_name("quality_report.json")
            report = (
                json.loads(report_path.read_text(encoding="utf-8"))
                if report_path.is_file()
                else {"status": "missing"}
            )
            templates.append(
                {
                    "scene_id": spec["scene_id"],
                    "display_name": spec["display_name"],
                    "version": spec.get("version"),
                    "quality_profile": spec["quality_profile"],
                    "bounds_m": spec["bounds"]["extent_m"],
                    "review_gates": spec["review_gates"],
                    "quality_status": report.get("status", "missing"),
                    "status": "valid",
                }
            )
        try:
            registry = AssetRegistry.load(app_settings.asset_registry, app_settings.root)
            assets = registry.list()
            registry_summary = {
                "status": "valid",
                "count": len(assets),
                "approved": sum(asset["status"] == "approved" for asset in assets),
                "categories": sorted({asset["category"] for asset in assets}),
            }
        except (ContractError, OSError, ValueError) as exc:
            registry_summary = {
                "status": "invalid",
                "error": str(exc),
                "count": 0,
                "approved": 0,
                "categories": [],
            }
        return {
            "schema_version": 1,
            "templates": templates,
            "quality_profiles": profiles,
            "asset_registry": registry_summary,
        }

    @app.get("/api/templates/{scene_id}")
    def scene_template(scene_id: str) -> dict[str, Any]:
        template = _template_dir(app_settings.templates_dir, scene_id)
        path = template / "world_spec.json"
        spec = load_contract(path, "world_spec")
        report_path = path.with_name("quality_report.json")
        observations_path = path.with_name("observations.json")
        measurement_path = path.with_name("measurement_plan.json")
        return {
            "world_spec": spec,
            "quality_report": json.loads(report_path.read_text(encoding="utf-8"))
            if report_path.is_file()
            else None,
            "observations": json.loads(observations_path.read_text(encoding="utf-8"))
            if observations_path.is_file()
            else None,
            "measurement_plan": load_contract(measurement_path, "measurement_plan")
            if measurement_path.is_file()
            else None,
        }

    @app.post("/api/templates/{scene_id}/instantiate", status_code=201)
    def instantiate_scene(
        scene_id: str, payload: dict[str, Any] = Body(default_factory=dict)
    ) -> dict[str, Any]:
        template = _template_dir(app_settings.templates_dir, scene_id)
        template_spec = load_contract(template / "world_spec.json", "world_spec")
        name = str(payload.get("name") or f"{template_spec['display_name']} · Derived").strip()[
            :120
        ]
        if len(name) < 3:
            raise HTTPException(422, "Derived scene name must contain at least three characters")
        materialize = payload.get("materialize_artifacts", True)
        if not isinstance(materialize, bool):
            raise HTTPException(422, "materialize_artifacts must be a boolean")
        job_id = uuid.uuid4().hex[:12]
        root = app_settings.jobs_dir / job_id
        for folder in ("input", "segments", "sam3d", "generated", "world", "logs"):
            (root / folder).mkdir(parents=True, exist_ok=True)
        try:
            result = instantiate_template(
                root=app_settings.root,
                template_dir=template,
                quality_profiles_dir=app_settings.quality_profiles_dir,
                asset_registry=app_settings.asset_registry,
                job_id=job_id,
                job_root=root,
                display_name=name,
                materialize_artifacts=materialize,
            )
        except (ContractError, InstanceError, OSError, ValueError) as exc:
            shutil.rmtree(root, ignore_errors=True)
            raise HTTPException(422, f"Template instantiation failed: {exc}") from exc
        config = {
            "template_scene_id": scene_id,
            "template_version": template_spec.get("version"),
            "quality_profile": template_spec["quality_profile"],
            "materialized_artifacts": materialize,
            "evidence_candidates": result["evidence_candidates"],
            "contract_revision": result["revision"]["revision"],
        }
        job = store.create_job(
            job_id=job_id,
            name=name,
            workflow="template",
            quality="paper",
            config=config,
            output_dir=root,
            source_image=None,
            stages=WORKFLOW_STAGES["template"],
        )
        store.update_stage(job_id, "instantiate", "succeeded", f"Derived from {scene_id}")
        store.update_stage(job_id, "quality_gates", "waiting", "Reference review is required")
        job = store.update_job(job_id, state="contract_review", current_stage="quality_gates")
        (root / "logs/pipeline.log").write_text(
            f"Template {scene_id} instantiated as {result['world_spec']['scene_id']}.\n",
            encoding="utf-8",
        )
        return job

    @app.get("/api/assets")
    def assets(status: str | None = None, category: str | None = None) -> dict[str, Any]:
        try:
            registry = AssetRegistry.load(app_settings.asset_registry, app_settings.root)
        except (ContractError, OSError, ValueError) as exc:
            raise HTTPException(503, f"Asset registry unavailable: {exc}") from exc
        values = registry.list(status=status, category=category)
        return {"schema_version": 1, "count": len(values), "assets": values}

    @app.get("/api/jobs")
    def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
        return store.list_jobs(max(1, min(limit, 500)))

    @app.post("/api/jobs", status_code=201)
    async def create_job(
        name: str = Form("Untitled World"),
        workflow: str = Form("existing"),
        quality: str = Form("paper"),
        config_json: str = Form("{}"),
        source: UploadFile | None = File(None),
    ) -> dict[str, Any]:
        if workflow not in WORKFLOW_STAGES:
            raise HTTPException(422, f"Unsupported workflow: {workflow}")
        if workflow == "template":
            raise HTTPException(422, "Use the template instantiate endpoint")
        if quality not in QUALITY_PRESETS:
            raise HTTPException(422, f"Unsupported quality: {quality}")
        if workflow == "denver_regional" and quality != "paper":
            raise HTTPException(422, "The Denver regional reproduction is fixed to paper quality")
        try:
            config = json.loads(config_json)
            if not isinstance(config, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(422, "config_json must be a JSON object") from exc
        if workflow == "full" and source is None:
            raise HTTPException(422, "The full workflow requires a reference image")
        if workflow == "validate_existing":
            existing = Path(config.get("existing_world", "")).expanduser().resolve()
            if not (existing / "manifest.json").is_file():
                raise HTTPException(422, "existing_world must contain manifest.json")

        job_id = uuid.uuid4().hex[:12]
        root = app_settings.jobs_dir / job_id
        paths = {
            folder: root / folder
            for folder in ("input", "segments", "sam3d", "generated", "world", "logs")
        }
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)
        source_path: Path | None = None
        if source is not None:
            suffix = Path(source.filename or "reference.png").suffix.lower()
            if suffix not in IMAGE_SUFFIXES:
                raise HTTPException(422, "Reference image must be PNG, JPEG, or WebP")
            source_path = paths["input"] / f"reference{suffix}"
            with source_path.open("wb") as target:
                while chunk := await source.read(1024 * 1024):
                    target.write(chunk)
            if source_path.stat().st_size > 100 * 1024 * 1024:
                source_path.unlink(missing_ok=True)
                raise HTTPException(413, "Reference image exceeds 100 MB")
        config.setdefault("review_mode", "manual")
        config.setdefault("make_archive", False)
        return store.create_job(
            job_id=job_id,
            name=name.strip()[:120] or "Untitled World",
            workflow=workflow,
            quality=quality,
            config=config,
            output_dir=root,
            source_image=source_path,
            stages=WORKFLOW_STAGES[workflow],
        )

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return _job_or_404(store, job_id)

    @app.post("/api/jobs/{job_id}/start")
    def start_job(job_id: str) -> dict[str, Any]:
        job = _job_or_404(store, job_id)
        if job["workflow"] == "template":
            raise HTTPException(
                409, "Template instances advance through quality gates, not the GPU queue"
            )
        if job["state"] == "awaiting_review":
            raise HTTPException(409, "Approve masks before resuming")
        resources = manager.resource_status()
        gpu = resources["gpu"]
        if not app_settings.testing and not gpu["capacity_ok"]:
            raise HTTPException(
                409,
                f"GPU {gpu['index']} has {gpu.get('free_mib', 0)} MiB free; "
                f"the configured minimum is {gpu['minimum_free_mib']} MiB. "
                "Stop another GPU workload or lower WORLDCLAW_MIN_FREE_VRAM_MIB.",
            )
        return manager.enqueue(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        job = _job_or_404(store, job_id)
        if job["workflow"] == "template":
            raise HTTPException(409, "Template review has no running process to cancel")
        if job["state"] in TERMINAL_STATES:
            return job
        if job["state"] in {"created", "interrupted", "awaiting_review"}:
            if job.get("current_stage"):
                store.update_stage(job_id, job["current_stage"], "cancelled", "Cancelled by user")
            return store.update_job(
                job_id, state="cancelled", error="Cancelled by user", cancel_requested=True
            )
        return store.request_cancel(job_id)

    @app.post("/api/jobs/{job_id}/retry")
    def retry_job(
        job_id: str, payload: dict[str, Any] = Body(default_factory=dict)
    ) -> dict[str, Any]:
        job = _job_or_404(store, job_id)
        if job["workflow"] == "template":
            raise HTTPException(
                409, "Use geometry measurement and quality gates for template instances"
            )
        if job["state"] in {"running", "queued"}:
            raise HTTPException(409, "Job is already active")
        stage = payload.get("from_stage") or job.get("current_stage") or job["stages"][0]["name"]
        try:
            store.reset_from_stage(job_id, stage)
        except KeyError as exc:
            raise HTTPException(422, "Unknown stage") from exc
        return manager.enqueue(job_id)

    @app.get("/api/jobs/{job_id}/review")
    def review_candidates(job_id: str) -> dict[str, Any]:
        job = _job_or_404(store, job_id)
        candidates: dict[str, Any] = {}
        for metadata in job_paths(job)["segments"].glob("*/instances.json"):
            data = json.loads(metadata.read_text(encoding="utf-8"))
            for item in data.get("instances", []):
                item["image_url"] = (
                    f"/api/jobs/{job_id}/files/{Path(item['image']).relative_to(Path(job['output_dir']))}"
                )
                item["mask_url"] = (
                    f"/api/jobs/{job_id}/files/{Path(item['mask']).relative_to(Path(job['output_dir']))}"
                )
            candidates[data["asset_type"]] = data
        return {"selected": job["config"].get("selected_masks", {}), "candidates": candidates}

    @app.post("/api/jobs/{job_id}/review")
    def approve_review(job_id: str, selections: dict[str, int] = Body(...)) -> dict[str, Any]:
        job = _job_or_404(store, job_id)
        approved: dict[str, Any] = {}
        segments = job_paths(job)["segments"]
        for asset_type, instance_index in selections.items():
            metadata = segments / asset_type / "instances.json"
            if not metadata.is_file():
                raise HTTPException(422, f"No candidates for {asset_type}")
            instances = json.loads(metadata.read_text(encoding="utf-8")).get("instances", [])
            match = next((item for item in instances if item["instance"] == instance_index), None)
            if match is None:
                raise HTTPException(422, f"Invalid instance for {asset_type}")
            approved[asset_type] = {key: match[key] for key in ("image", "mask", "score")}
        if not approved:
            raise HTTPException(422, "Select at least one mask")
        config = job["config"]
        config["selected_masks"] = approved
        store.update_config(job_id, config)
        store.reset_from_stage(job_id, "review")
        return manager.enqueue(job_id)

    @app.put("/api/jobs/{job_id}/layout")
    def update_layout(job_id: str, layout: dict[str, Any] = Body(...)) -> dict[str, Any]:
        job = _job_or_404(store, job_id)
        if job["workflow"] == "template":
            raise HTTPException(
                422, "The frozen contract must be revised through a versioned template workflow"
            )
        if job["workflow"] == "denver_regional":
            raise HTTPException(422, "The Denver reproduction uses its frozen regional plan")
        if job["state"] in {"running", "queued"}:
            raise HTTPException(409, "Stop the job before editing its layout")
        config = job["config"]
        config["layout"] = layout
        store.update_config(job_id, config)
        if any(stage["state"] != "pending" for stage in job["stages"]):
            store.reset_from_stage(job_id, "plan")
        return store.get_job(job_id)

    @app.get("/api/jobs/{job_id}/artifacts")
    def artifacts(job_id: str) -> list[dict[str, Any]]:
        job = _job_or_404(store, job_id)
        root = Path(job["output_dir"])
        result = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            result.append(
                {
                    "path": relative,
                    "bytes": path.stat().st_size,
                    "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    "url": f"/api/jobs/{job_id}/files/{relative}",
                }
            )
        return result

    @app.get("/api/jobs/{job_id}/quality")
    def job_quality(job_id: str) -> dict[str, Any]:
        job = _job_or_404(store, job_id)
        world = Path(job["output_dir"]) / "world"
        spec_path = world / "world_spec.json"
        report_path = world / "quality_report.json"
        validation_path = world / "validation.json"
        spec = None
        if spec_path.is_file():
            try:
                spec = load_contract(spec_path, "world_spec")
            except ContractError as exc:
                return {"status": "failed", "contract_status": "invalid", "error": str(exc)}
        report = (
            json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else None
        )
        validation = (
            json.loads(validation_path.read_text(encoding="utf-8"))
            if validation_path.is_file()
            else None
        )
        if report is None and validation is not None:
            checks = validation.get("checks", {})
            report = {
                "schema_version": 1,
                "scene_id": validation.get("scene_id", job_id),
                "profile_id": "legacy_validation",
                "status": validation.get("status", "unknown"),
                "groups": {
                    "legacy_checks": all(checks.values())
                    if checks
                    else validation.get("status") == "passed"
                },
                "checks": checks,
            }
        revisions = []
        for path in sorted((world / "contract_revisions").glob("*.json")):
            try:
                revision = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            revisions.append(
                {
                    "revision": revision.get("revision"),
                    "timestamp": revision.get("timestamp"),
                    "action": revision.get("action"),
                    "sha256": revision.get("world_spec_sha256"),
                }
            )
        return {
            "status": (report or {}).get("status", "missing"),
            "contract_status": "valid" if spec else "legacy",
            "world_spec": spec,
            "quality_report": report,
            "validation": validation,
            "editable_gates": job["workflow"] == "template",
            "measurement_available": bool(
                spec and spec.get("measurement_plan") and (world / "world.blend").is_file()
            ),
            "revisions": revisions,
        }

    @app.post("/api/jobs/{job_id}/gates/{gate}")
    def update_quality_gate(
        job_id: str, gate: str, payload: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        job = _job_or_404(store, job_id)
        if job["workflow"] != "template":
            raise HTTPException(
                409, "Frozen deliveries are read-only; instantiate a template first"
            )
        if job["state"] in {"running", "queued"}:
            raise HTTPException(409, "Cannot review a running job")
        status = payload.get("status")
        if status not in {"approved", "rejected"}:
            raise HTTPException(422, "Gate status must be approved or rejected")
        reviewer = str(payload.get("reviewer") or "local-user").strip()[:120]
        notes = str(payload.get("notes") or "").strip()[:1000]
        raw_evidence = payload.get("evidence", [])
        if (
            not isinstance(raw_evidence, list)
            or len(raw_evidence) > 20
            or not all(isinstance(item, str) for item in raw_evidence)
        ):
            raise HTTPException(422, "evidence must be a list of at most 20 paths")
        root = Path(job["output_dir"])
        evidence = []
        for value in raw_evidence:
            candidate = Path(value)
            if candidate.is_absolute():
                resolved = _inside(candidate, root)
            else:
                direct = root / candidate
                project_relative = app_settings.root / candidate
                resolved = _inside(direct if direct.is_file() else project_relative, root)
            if not resolved.is_file():
                raise HTTPException(422, f"Evidence file does not exist: {value}")
            evidence.append(resolved.relative_to(root.resolve()).as_posix())
        world = root / "world"
        try:
            with contract_lock:
                result = transition_instance_gate(
                    world,
                    gate,
                    status,
                    evidence=evidence,
                    reviewer=reviewer,
                    notes=notes,
                )
        except GateTransitionError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ContractError, InstanceError, OSError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        config = job["config"]
        config["contract_revision"] = result["revision"]["revision"]
        store.update_config(job_id, config)
        complete = all(
            result["world_spec"]["review_gates"][name]["status"] == "approved"
            for name in GATE_ORDER
        )
        if complete:
            store.update_stage(
                job_id, "quality_gates", "succeeded", "All four review gates approved"
            )
            updated_job = store.update_job(
                job_id, state="succeeded", current_stage="quality_gates", error=None
            )
        else:
            next_gate = next(
                (
                    name
                    for name in GATE_ORDER
                    if result["world_spec"]["review_gates"][name]["status"] != "approved"
                ),
                "final",
            )
            store.update_stage(
                job_id, "quality_gates", "waiting", f"Waiting for {next_gate} review"
            )
            updated_job = store.update_job(
                job_id, state="contract_review", current_stage="quality_gates", error=None
            )
        with (root / "logs/pipeline.log").open("a", encoding="utf-8") as log:
            log.write(f"Gate {gate} changed to {status} by {reviewer}.\n")
        return {"job": updated_job, **result}

    @app.post("/api/jobs/{job_id}/measure")
    def measure_geometry(job_id: str) -> dict[str, Any]:
        job = _job_or_404(store, job_id)
        if job["workflow"] != "template":
            raise HTTPException(409, "Automatic measurement is available on template instances")
        root = Path(job["output_dir"])
        world = root / "world"
        spec = load_contract(world / "world_spec.json", "world_spec")
        if not spec.get("measurement_plan"):
            raise HTTPException(409, "This template has no Blender measurement plan")
        plan_value = Path(spec["measurement_plan"])
        plan_path = plan_value if plan_value.is_absolute() else app_settings.root / plan_value
        plan_path = _inside(plan_path, root)
        blend_value = Path(spec.get("artifacts", {}).get("blend", ""))
        blend_path = blend_value if blend_value.is_absolute() else app_settings.root / blend_value
        blend_path = _inside(blend_path, root)
        if not plan_path.is_file() or not blend_path.is_file():
            raise HTTPException(409, "Materialized measurement plan or BLEND is missing")
        load_contract(plan_path, "measurement_plan")
        output = world / "automatic_geometry_observation.json"
        output.unlink(missing_ok=True)
        if app_settings.testing:
            observations = json.loads((world / "observations.json").read_text(encoding="utf-8"))
            atomic_json(
                output,
                {
                    "schema_version": 1,
                    "kind": "geometry_observation",
                    "scene_id": spec["scene_id"],
                    "status": "passed",
                    "source": {"blend": str(blend_path), "testing": True},
                    "geometry": observations.get("geometry", {}),
                    "probes": [],
                    "errors": [],
                },
            )
        else:
            try:
                process = subprocess.run(
                    [
                        str(app_settings.blender),
                        str(blend_path),
                        "--background",
                        "--python",
                        str(app_settings.root / "scripts/measure_blender_geometry.py"),
                        "--",
                        "--plan",
                        str(plan_path),
                        "--output",
                        str(output),
                    ],
                    cwd=app_settings.root,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise HTTPException(500, f"Blender measurement failed to start: {exc}") from exc
            if process.returncode != 0 or not output.is_file():
                detail = (process.stderr or process.stdout)[-3000:]
                raise HTTPException(500, f"Blender measurement failed: {detail}")
        try:
            with contract_lock:
                result = merge_geometry_observation(world, output)
        except (ContractError, InstanceError, OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        config = job["config"]
        config["contract_revision"] = result["revision"]["revision"]
        config["geometry_measured"] = True
        store.update_config(job_id, config)
        with (root / "logs/pipeline.log").open("a", encoding="utf-8") as log:
            log.write("Automatic Blender geometry measurement passed.\n")
        return result

    @app.get("/api/jobs/{job_id}/files/{relative_path:path}")
    def job_file(job_id: str, relative_path: str) -> FileResponse:
        job = _job_or_404(store, job_id)
        root = Path(job["output_dir"])
        path = _inside(root / relative_path, root)
        if not path.is_file():
            raise HTTPException(404, "File not found")
        return FileResponse(path)

    @app.get("/api/jobs/{job_id}/logs")
    async def stream_logs(job_id: str) -> StreamingResponse:
        job = _job_or_404(store, job_id)
        log_path = job_paths(job)["logs"] / "pipeline.log"

        async def events():
            position = 0
            idle_after_terminal = 0
            while True:
                if log_path.is_file():
                    with log_path.open("r", encoding="utf-8", errors="replace") as source:
                        source.seek(position)
                        data = source.read()
                        position = source.tell()
                    if data:
                        idle_after_terminal = 0
                        yield f"event: log\ndata: {json.dumps(data)}\n\n"
                state = store.get_job(job_id)["state"]
                yield f"event: state\ndata: {json.dumps(state)}\n\n"
                if state in TERMINAL_STATES:
                    idle_after_terminal += 1
                    if idle_after_terminal >= 2:
                        return
                await asyncio.sleep(1)

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str) -> dict[str, bool]:
        job = _job_or_404(store, job_id)
        if job["state"] in {"running", "queued"}:
            raise HTTPException(409, "Cancel the active job before deleting it")
        root = _inside(Path(job["output_dir"]), app_settings.jobs_dir)
        store.delete_job(job_id)
        shutil.rmtree(root, ignore_errors=True)
        return {"deleted": True}

    if app_settings.frontend_dist.is_dir():
        app.mount(
            "/", StaticFiles(directory=app_settings.frontend_dist, html=True), name="frontend"
        )

    return app


app = create_app()
