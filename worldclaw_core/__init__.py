"""Reusable contracts, quality gates and registries for WorldClaw.

The package keeps its public imports lazy so Blender's bundled Python can use
the dependency-free geometry module without also requiring ``jsonschema``.
"""

from importlib import import_module

__all__ = [
    "AssetRegistry",
    "ContractError",
    "GATE_ORDER",
    "GateTransitionError",
    "build_quality_report",
    "load_contract",
    "transition_gate",
    "validate_contract",
]


_EXPORTS = {
    "AssetRegistry": ("registry", "AssetRegistry"),
    "ContractError": ("contracts", "ContractError"),
    "GATE_ORDER": ("gates", "GATE_ORDER"),
    "GateTransitionError": ("gates", "GateTransitionError"),
    "build_quality_report": ("validation", "build_quality_report"),
    "load_contract": ("contracts", "load_contract"),
    "transition_gate": ("gates", "transition_gate"),
    "validate_contract": ("contracts", "validate_contract"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attribute = _EXPORTS[name]
    value = getattr(import_module(f"{__name__}.{module_name}"), attribute)
    globals()[name] = value
    return value
