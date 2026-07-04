"""One descriptor, many projections. A connector's manifest.json (routes + examples)
and its OpenAPI are PROJECTIONS of the Capability descriptors — generate them, don't
hand-maintain a second/third copy that can drift.

    to_manifest(reg, meta) -> the routes/examples/schemes a connector.manifest.json needs
    to_openapi(reg)        -> OpenAPI 3 (from serve.py)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capability import Registry
from serve import to_openapi


def to_manifest(reg: Registry, meta: dict | None = None) -> dict:
    """Generate the contract-derived parts of a connector manifest from the descriptors.
    Everything here is a pure projection — the descriptor is the single source of truth."""
    meta = meta or {}
    caps = list(reg._caps.values())
    routes = [c.uri for c in caps]
    schemes = sorted({c.uri.split("://", 1)[0] for c in caps})
    adapters = sorted({c.adapter for c in caps})
    examples = []
    for c in caps:
        for ex in c.examples:
            examples.append({"title": c.uri, "uri": c.uri, "payload": ex.get("input", {})})
    return {**{"id": meta.get("id", "connector"), "name": meta.get("name", ""),
               "category": meta.get("category", ""), "summary": meta.get("summary", "")},
            "routes": routes, "uriSchemes": schemes, "adapterKinds": adapters,
            "examples": examples,
            # reversibility + effect are carried in the descriptor, surfaced for the manifest
            "reversible": [c.uri for c in caps if c.reversible],
            "effects": {c.uri: c.effect for c in caps}}


def projections(reg: Registry, meta: dict | None = None) -> dict:
    """All projections from the one source, plus the byte cost of each (so the saving
    from NOT maintaining them by hand is visible)."""
    man = to_manifest(reg, meta)
    api = to_openapi(reg)
    descriptor = [c.contract() for c in reg._caps.values()]
    return {"descriptor": descriptor, "manifest": man, "openapi": api,
            "bytes": {"descriptor": len(json.dumps(descriptor, ensure_ascii=False)),
                      "manifest": len(json.dumps(man, ensure_ascii=False)),
                      "openapi": len(json.dumps(api))}}


if __name__ == "__main__":
    from kvstore import load_kvstore
    reg = load_kvstore(Path("/home/tom/github/if-uri/urirun-contract-kvstore/contracts.json"))
    p = projections(reg, {"id": "kvstore", "name": "Key-Value Store", "category": "storage"})
    print("z JEDNEGO deskryptora wygenerowano:")
    print(f"  manifest: {len(p['manifest']['routes'])} routes, "
          f"{len(p['manifest']['examples'])} examples, {p['bytes']['manifest']} B")
    print(f"  OpenAPI:  {len(p['openapi']['paths'])} ścieżek, {p['bytes']['openapi']} B")
    print(f"  deskryptor (źródło): {p['bytes']['descriptor']} B")
    print("\n→ manifest i OpenAPI są PROJEKCJĄ deskryptora — utrzymujesz jedno, generujesz oba.")
