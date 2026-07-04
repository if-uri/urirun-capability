"""OpenAPI <-> Capability is bidirectional, because both are the same essence:
a typed operation = (identity, effect, input schema, output schema).

  to_openapi(registry)  -> an OpenAPI 3 spec (already used by serve.py)
  from_openapi(spec)     -> Capabilities (import any external OpenAPI as contracts)

So an OpenAPI document IS a contract source; no per-capability package needed.
"""
from __future__ import annotations

from capability import Capability, Registry

_SAFE = {"get", "head", "options"}


def from_openapi(spec: dict, *, node: str = "", scheme: str = "api") -> Registry:
    """Turn each OpenAPI operation into a Capability.

    method -> effect (GET/HEAD/OPTIONS = query, else command)
    requestBody / parameters schema -> input
    responses 2xx schema -> output
    x-uri (our extension) is honoured; otherwise a uri is derived.
    """
    reg = Registry()
    for path, item in (spec.get("paths") or {}).items():
        for method, op in item.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete", "head", "options"):
                continue
            effect = "query" if method.lower() in _SAFE else "command"
            uri = op.get("x-uri") or _derive_uri(scheme, node, op, path, method, effect)
            inp = (((op.get("requestBody") or {}).get("content") or {})
                   .get("application/json") or {}).get("schema") or {}
            resp = op.get("responses") or {}
            out_schema = {}
            for code in ("200", "201", "2XX", "default"):
                r = resp.get(code)
                if r:
                    out_schema = ((r.get("content") or {}).get("application/json") or {}).get("schema") or {}
                    break
            reg.add(Capability(
                uri=uri, effect=op.get("x-effect", effect),
                reversible=bool(op.get("x-reversible", False)),
                input=inp, output=out_schema,
                adapter="http-node" if node else "python",
                config={"node": node, "protocol": "capability", "remoteUri": uri} if node else {},
            ))
    return reg


def _derive_uri(scheme: str, node: str, op: dict, path: str, method: str, effect: str) -> str:
    op_id = op.get("operationId") or (method + path).replace("/", "_").strip("_")
    authority = node.split("//")[-1].split(":")[0] if node else "host"
    action = op_id.split("_")[-1] or method
    obj = op_id.split("_")[0] if "_" in op_id else op_id
    return f"{scheme}://{authority}/{obj}/{effect}/{action}"


# to_openapi lives in serve.py (used by the HTTP surface); re-export for symmetry
from serve import to_openapi  # noqa: E402,F401
