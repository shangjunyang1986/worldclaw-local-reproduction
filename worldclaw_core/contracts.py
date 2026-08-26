from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {
    "world_spec": ROOT / "schemas/world_spec.v1.schema.json",
    "asset_registry": ROOT / "schemas/asset_manifest.v1.schema.json",
    "quality_profile": ROOT / "schemas/quality_profile.v1.schema.json",
    "measurement_plan": ROOT / "schemas/measurement_plan.v1.schema.json",
}


class ContractError(ValueError):
    """Raised when a WorldClaw contract violates its schema."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"Cannot read JSON contract {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"Contract root must be an object: {path}")
    return value


def _format_path(parts: list[Any]) -> str:
    if not parts:
        return "$"
    result = "$"
    for part in parts:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result


def validate_contract(document: dict[str, Any], kind: str | None = None) -> dict[str, Any]:
    contract_kind = kind or document.get("kind")
    if contract_kind not in SCHEMAS:
        raise ContractError(f"Unsupported contract kind: {contract_kind!r}")
    schema = _load_json(SCHEMAS[contract_kind])
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document), key=lambda item: list(item.path)
    )
    if errors:
        details = "; ".join(
            f"{_format_path(list(error.path))}: {error.message}" for error in errors[:12]
        )
        if len(errors) > 12:
            details += f"; ... {len(errors) - 12} more"
        raise ContractError(f"{contract_kind} validation failed: {details}")
    return document


def load_contract(path: str | Path, kind: str | None = None) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return validate_contract(_load_json(resolved), kind)


def dump_contract(path: str | Path, document: dict[str, Any], kind: str | None = None) -> Path:
    validate_contract(document, kind)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        json.dump(document, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    try:
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
