"""The manifest and OpenAPI are PROJECTIONS of the one descriptor — so a connector
never hand-maintains a second copy that can drift."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from projections import to_manifest, projections  # noqa: E402
from hard_tasks import hard_registry  # noqa: E402


def test_manifest_routes_and_effects_come_straight_from_the_descriptors():
    reg = hard_registry()
    man = to_manifest(reg, {"id": "hard", "name": "Hard tasks"})
    uris = list(reg._caps)
    assert man["routes"] == uris                        # routes ARE the capability uris
    assert set(man["effects"]) == set(uris)             # effect per uri, from the descriptor
    # every example in the manifest traces to a capability
    assert all(ex["uri"] in uris for ex in man["examples"])


def test_projection_is_deterministic():
    reg = hard_registry()
    a = to_manifest(reg, {"id": "x"})
    b = to_manifest(reg, {"id": "x"})
    assert a == b                                        # pure projection, no drift possible


def test_one_source_generates_manifest_and_openapi():
    reg = hard_registry()
    p = projections(reg, {"id": "hard"})
    # both the manifest and the OpenAPI cover exactly the descriptor's capabilities
    assert len(p["manifest"]["routes"]) == len(reg._caps)
    assert len(p["openapi"]["paths"]) == len(reg._caps)
    assert p["bytes"]["descriptor"] > 0 and p["bytes"]["manifest"] > 0


def test_reversible_capabilities_are_surfaced_in_the_manifest():
    # a connector with a reversible contract advertises it, straight from the descriptor
    from capability import Capability, Registry
    reg = Registry()
    reg.add(Capability(uri="fs://host/file/command/delete", effect="command", reversible=True,
                       inverse="fs://host/file/command/restore", adapter="python",
                       config={"fn": lambda **k: {"ok": True}}))
    man = to_manifest(reg)
    assert "fs://host/file/command/delete" in man["reversible"]
