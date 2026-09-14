"""Canonical false-by-default action capability registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_REGISTRY_PATH = Path(__file__).with_name("action_capabilities.json")
_AUTHORIZED_EVIDENCE = {"AUTHORIZED_LIVE_READ", "AUTHORIZED_LIVE_WRITE"}


@dataclass(frozen=True)
class ActionCapability:
    recommendation_supported: bool = False
    approval_supported: bool = False
    live_baseline_read_supported: bool = False
    live_apply_supported: bool = False
    rollback_supported: bool = False
    verification_supported: bool = False
    local_only: bool = False


_RAW: dict[str, dict[str, bool]] = json.loads(_REGISTRY_PATH.read_text())
_REGISTRY = {key: ActionCapability(**value) for key, value in _RAW.items()}


def capability(entity_type: str, action_type: str) -> ActionCapability:
    """Unknown combinations are unsupported rather than inferred."""
    return _REGISTRY.get(
        f"{entity_type}:{action_type}",
        _REGISTRY.get(f"*:{action_type}", ActionCapability()),
    )


def live_ready(readiness_state: str | None, verification_level: str | None) -> bool:
    """Static, docs, fixtures and sandbox evidence never produce live readiness."""
    return readiness_state == "LIVE_READY" and verification_level in _AUTHORIZED_EVIDENCE


def assert_worker_capability(
    entity_type: str,
    action_type: str,
    *,
    phase: str,
    readiness_state: str | None,
    verification_level: str | None,
) -> None:
    item = capability(entity_type, action_type)
    supported = {
        "baseline": item.live_baseline_read_supported,
        "apply": item.live_apply_supported,
        "rollback": item.rollback_supported,
        "verify": item.verification_supported,
    }.get(phase, False)
    if item.local_only or not supported:
        raise RuntimeError(f"unsupported capability: {entity_type}/{action_type}/{phase}")
    if not live_ready(readiness_state, verification_level):
        raise RuntimeError("capability is not LIVE_READY with authorized live evidence")
