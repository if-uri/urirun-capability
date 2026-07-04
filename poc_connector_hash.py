"""PoC: a complete connector defined ENTIRELY as descriptors on the shared runtime.

The real urirun-connector-hash is 96 lines of Go + a hand-written manifest.json for ONE
route. Here the connector is just typed descriptors + one-line handlers; the manifest and
OpenAPI are GENERATED (never hand-maintained, so they cannot drift), the gate/validation/
events are the shared core, and adding a route is a descriptor + a lambda — no boilerplate.
Bonus: 4 routes instead of 1, for less code than the original's one.

    python poc_connector_hash.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capability import Capability, Registry, dispatch, check_examples
from projections import to_manifest, to_openapi

_ALGOS = {"sha256": hashlib.sha256, "sha1": hashlib.sha1,
          "md5": hashlib.md5, "blake2b": hashlib.blake2b}


def _make(algo):
    def fn(text):
        return {"ok": True, "algo": algo, "hex": _ALGOS[algo](text.encode()).hexdigest()}
    return fn


def hash_connector() -> Registry:
    """The whole connector: one descriptor + one handler per algorithm. That's it."""
    reg = Registry()
    for algo in _ALGOS:
        reg.add(Capability(
            uri=f"hash://host/text/query/{algo}", effect="query",
            input={"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}},
            output={"type": "object", "required": ["hex"],
                    "properties": {"hex": {"type": "string"}, "algo": {"type": "string"}}},
            examples=({"input": {"text": "hello"},
                       "output": {"algo": algo, "hex": _ALGOS[algo](b"hello").hexdigest()}},),
            adapter="python", config={"fn": _make(algo)}))
    return reg


def main() -> int:
    reg = hash_connector()
    print(f"Connector 'hash' z {len(reg._caps)} tras — wyłącznie deskryptory, zero plików boilerplate.\n")

    # it works: real hashing, output validated against the contract
    out = dispatch(reg, "hash://host/text/query/sha256", {"text": "hello"})
    print("dispatch sha256('hello'):", out["result"]["hex"][:24], "…  ok=", out["ok"])

    # every example conforms (the regression guard, shared)
    conform = all(check_examples(reg, c)["passed"] == check_examples(reg, c)["total"]
                  for c in reg._caps.values())
    print("konformans wszystkich examples:", conform)

    # manifest + OpenAPI are GENERATED from the descriptors — never hand-written
    man = to_manifest(reg, {"id": "hash", "name": "Hash", "category": "Utilities"})
    api = to_openapi(reg)
    print(f"\nwygenerowane (nie pisane ręcznie):")
    print(f"  manifest: {len(man['routes'])} routes, {len(man['examples'])} examples")
    print(f"  OpenAPI:  {len(api['paths'])} ścieżek")
    print(f"  routes = {man['routes']}")

    # interop: the descriptor produces exactly the real connector's URI form
    assert "hash://host/text/query/sha256" in man["routes"]

    poc_loc = sum(1 for _ in open(__file__))
    print(f"\n→ cały connector (4 trasy, działające, z generowanym manifestem+OpenAPI): "
          f"{poc_loc} linii, 0 plików kontraktu/manifestu do utrzymania.")
    print("  Oryginał (1 trasa): 96 lin. Go + ręczny manifest.json + go.mod + testy.")
    print("  Rozjazd manifest↔kod: strukturalnie niemożliwy (manifest jest projekcją).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
