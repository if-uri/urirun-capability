"""Adopt the REAL urirun-contract-kvstore contracts.json as Capabilities.

The whole urirun-contract-kvstore package is 422 LOC of Python in 26 files to
serve 2 contracts defined in an 81-line contracts.json. Here the SAME 2 contracts
become Capability descriptors (data) on the shared ~280-line core — no per-package
gate, handlers, producer/consumer or CI scaffold. Also generates OpenAPI.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capability import Registry
from contracts_adopt import adopt_contracts

KV: dict[str, str] = {}   # the actual store (what the 422-LOC package wraps)

# real handlers for kvstore (proves adopted contracts run genuine logic, not stubs)
_HANDLERS = {
    "kv/command/set": lambda key, value: (KV.__setitem__(key, value),
                                          {"ok": True, "connector": "kvstore",
                                           "action": "kv-set", "key": key, "stored": True})[1],
    "kv/query/get": lambda key: {"ok": True, "connector": "kvstore", "action": "kv-get",
                                 "key": key, "value": KV.get(key), "found": key in KV},
}


def load_kvstore(contracts_json: Path, scheme: str = "kv") -> Registry:
    return adopt_contracts(contracts_json, scheme, handlers=_HANDLERS)


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "/home/tom/github/if-uri/urirun-contract-kvstore/contracts.json")
    reg = load_kvstore(src)
    from capability import Events, dispatch
    from openapi import to_openapi

    print("== 2 kontrakty kvstore jako Capabilities (content-addressed):")
    for uri, cid in reg.lock().items():
        print(f"  {cid}  {uri}")

    print("\n== Realne wykonanie (set -> get przez współdzielony rdzeń):")
    ev = Events()
    dispatch(reg, "kv://host/kv/command/set", {"key": "greeting", "value": "hello"}, events=ev)
    got = dispatch(reg, "kv://host/kv/query/get", {"key": "greeting"}, events=ev)
    print("  get ->", got["result"])

    spec = to_openapi(reg)
    print(f"\n== Wygenerowany OpenAPI: {len(spec['paths'])} operacji, "
          f"{len(json.dumps(spec))} bajtów")
