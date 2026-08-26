from __future__ import annotations

from copy import deepcopy
from typing import Any

GATE_ORDER = ("reference", "graybox", "materials", "final")
GATE_STATES = {"pending", "approved", "rejected"}


class GateTransitionError(ValueError):
    """Raised when a review gate transition would bypass an earlier gate."""


def transition_gate(
    gates: dict[str, dict[str, Any]],
    gate: str,
    status: str,
    *,
    evidence: list[str] | None = None,
    reviewer: str = "local-review",
    notes: str = "",
) -> dict[str, dict[str, Any]]:
    if gate not in GATE_ORDER:
        raise GateTransitionError(f"Unknown review gate: {gate}")
    if status not in GATE_STATES:
        raise GateTransitionError(f"Unknown gate status: {status}")
    updated = deepcopy(gates)
    missing = [name for name in GATE_ORDER if name not in updated]
    if missing:
        raise GateTransitionError(f"Review state is missing gates: {', '.join(missing)}")
    if status == "approved":
        previous = GATE_ORDER[: GATE_ORDER.index(gate)]
        blocked = [name for name in previous if updated[name].get("status") != "approved"]
        if blocked:
            raise GateTransitionError(f"Cannot approve {gate} before: {', '.join(blocked)}")
        if not evidence and not updated[gate].get("evidence"):
            raise GateTransitionError(f"Cannot approve {gate} without evidence")
    updated[gate] = {
        "status": status,
        "evidence": list(evidence if evidence is not None else updated[gate].get("evidence", [])),
        "reviewer": reviewer,
        "notes": notes,
    }
    if status == "rejected":
        for later in GATE_ORDER[GATE_ORDER.index(gate) + 1 :]:
            updated[later] = {
                "status": "pending",
                "evidence": [],
                "reviewer": "",
                "notes": "Invalidated by earlier rejection",
            }
    return updated


def gate_summary(gates: dict[str, dict[str, Any]], require_all: bool = True) -> dict[str, Any]:
    statuses = {name: gates.get(name, {}).get("status", "missing") for name in GATE_ORDER}
    passed = (
        all(value == "approved" for value in statuses.values())
        if require_all
        else not any(value == "rejected" for value in statuses.values())
    )
    return {"status": "passed" if passed else "failed", "gates": statuses}
