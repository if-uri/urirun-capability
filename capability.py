"""urirun-capability — a shrunk, invariant core for URI processes.

One typed descriptor (Capability) replaces the binding + contract split. Key
invariants that the current urirun implementation leaves optional or implicit:

  1. The URI is a STABLE NAME, not a carrier of logic. Effect is a typed field,
     not parsed from the "/query/" vs "/command/" path segment.
  2. Identity is CONTENT-ADDRESSED: capability_id = hash(canonical contract).
     A registry can be locked; drift is detected, never silent.
  3. EVERY dispatch emits URI events by construction (run:// / error:// / log://)
     — observability (and thus replay / digital twin) is free for any system.
  4. Output is validated against the contract, so backend drift is caught.

Adapters are plugins. Stdlib only (jsonschema used if present, else a subset).
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

Effect = str  # "query" (read) | "command" (mutate)


# ── the single descriptor ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class Capability:
    uri: str                                    # stable identity (a name, not logic)
    effect: Effect = "query"                    # typed, NOT parsed from the URI
    reversible: bool = False                    # commands only; inverse must exist if True
    idempotent: bool = False
    input: dict = field(default_factory=dict)   # JSON-Schema (one schema language)
    output: dict = field(default_factory=dict)
    errors: tuple[str, ...] = ()                # declared error taxonomy (gRPC-style)
    examples: tuple[dict, ...] = ()             # golden {input,output}: tests + few-shot + planner
    adapter: str = "python"                     # plugin name
    config: dict = field(default_factory=dict)  # adapter config
    inverse: str = ""                           # uri of the inverse capability (if reversible)

    def contract(self) -> dict:
        """The versioned, hashable essence (excludes adapter wiring)."""
        return {"uri": self.uri, "effect": self.effect, "reversible": self.reversible,
                "idempotent": self.idempotent, "input": self.input, "output": self.output,
                "errors": list(self.errors), "examples": list(self.examples)}

    def id(self) -> str:
        blob = json.dumps(self.contract(), sort_keys=True, ensure_ascii=False).encode()
        return "cap-" + hashlib.blake2b(blob, digest_size=8).hexdigest()


# ── event sink: observability by construction ─────────────────────────────────
class Events:
    def __init__(self) -> None:
        self.log: list[dict] = []

    def emit(self, uri: str, actor: str = "runtime", **payload) -> dict:
        rec = {"seq": len(self.log) + 1, "uri": uri, "ts": time.time(),
               "actor": actor, "payload": payload}
        self.log.append(rec)
        return rec

    def by_scheme(self, scheme: str) -> list[dict]:
        return [e for e in self.log if e["uri"].startswith(scheme + "://")]


# ── error taxonomy (typed, addressable) ───────────────────────────────────────
_STATUS = {"INVALID_ARGUMENT": 400, "PERMISSION_DENIED": 403, "NOT_FOUND": 404,
           "FAILED_PRECONDITION": 412, "UNAVAILABLE": 503, "INTERNAL": 500,
           "CONTRACT_VIOLATION": 422}


def _error_code(category: str, message: str) -> str:
    basis = f"{category}|{message}".encode()
    return "E-" + hashlib.blake2b(basis, digest_size=4).hexdigest()


class CapabilityError(Exception):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
        self.message = message


# ── minimal JSON-Schema-subset validator (stdlib fallback) ────────────────────
def _validate(schema: dict, value: Any) -> str | None:
    """Return an error string, or None if valid. Uses jsonschema if installed."""
    if not schema:
        return None
    try:
        import jsonschema  # noqa: PLC0415
        try:
            jsonschema.validate(value, schema)
            return None
        except jsonschema.ValidationError as e:
            return str(e.message)
    except ImportError:
        pass
    # subset fallback: type + required + properties(type)
    t = schema.get("type")
    _py = {"object": dict, "array": list, "string": str, "number": (int, float),
           "integer": int, "boolean": bool}
    if t and t in _py and not isinstance(value, _py[t]):
        return f"expected {t}, got {type(value).__name__}"
    if t == "object" and isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                return f"missing required '{req}'"
        for k, sub in (schema.get("properties") or {}).items():
            if k in value:
                err = _validate(sub, value[k])
                if err:
                    return f"{k}: {err}"
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(schema.get("properties") or {})
            if extra:
                return f"unexpected properties: {sorted(extra)}"
    return None


# ── registry + lockfile (content-addressed pinning) ───────────────────────────
class Registry:
    def __init__(self) -> None:
        self._caps: dict[str, Capability] = {}

    def add(self, cap: Capability) -> Capability:
        self._caps[cap.uri] = cap
        return cap

    def get(self, uri: str) -> Capability | None:
        return self._caps.get(uri)

    def lock(self) -> dict[str, str]:
        """A lockfile: uri -> content-addressed id. Pin what a flow was validated against."""
        return {uri: cap.id() for uri, cap in sorted(self._caps.items())}

    def drift(self, lock: dict[str, str]) -> list[dict]:
        """Compare a lockfile to the live registry; report every mismatch (no silent drift)."""
        out = []
        for uri, pinned in lock.items():
            cap = self._caps.get(uri)
            if cap is None:
                out.append({"uri": uri, "issue": "removed"})
            elif cap.id() != pinned:
                out.append({"uri": uri, "issue": "changed", "was": pinned, "now": cap.id()})
        for uri in self._caps:
            if uri not in lock:
                out.append({"uri": uri, "issue": "added"})
        return out


# ── adapters as plugins (one clean subprocess adapter, not five) ──────────────
ADAPTERS: dict[str, Callable[[Capability, dict], dict]] = {}


def adapter(name: str):
    def deco(fn):
        ADAPTERS[name] = fn
        return fn
    return deco


@adapter("python")
def _python_adapter(cap: Capability, payload: dict) -> dict:
    fn = cap.config.get("fn")
    if not callable(fn):
        raise CapabilityError("INTERNAL", "python adapter needs config.fn")
    return fn(**payload)


def _subst(template: str, payload: dict) -> str:
    """Replace only explicit {key} placeholders for keys in payload — leave any
    other braces (e.g. literal code passed as an argv element) untouched."""
    out = template
    for k, v in payload.items():
        out = out.replace("{" + k + "}", str(v))
    return out


@adapter("http-node")
def _http_node_adapter(cap: Capability, payload: dict) -> dict:
    """Dispatch to a live urirun node (POST /run {uri, payload}). Lets the shrunk
    core drive the existing mesh unchanged — a migration path, not a rewrite."""
    import urllib.request  # noqa: PLC0415
    node = cap.config.get("node")
    remote_uri = cap.config.get("remoteUri", cap.uri)
    if not node:
        raise CapabilityError("INTERNAL", "http-node adapter needs config.node")
    body = json.dumps({"uri": remote_uri, "payload": payload}).encode()
    req = urllib.request.Request(f"{node}/run", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=cap.config.get("timeout", 30)) as resp:
            doc = json.loads(resp.read())
    except Exception as e:  # noqa: BLE001
        raise CapabilityError("UNAVAILABLE", f"node unreachable: {e}")
    if not doc.get("ok", True):
        raise CapabilityError("INTERNAL", str(doc.get("error", "node error"))[:200])
    res = doc.get("result", doc)
    val = res.get("value") if isinstance(res, dict) else None
    return val if isinstance(val, dict) else res


@adapter("subprocess")
def _subprocess_adapter(cap: Capability, payload: dict) -> dict:
    import subprocess  # noqa: PLC0415
    argv = [_subst(str(a), payload) for a in cap.config.get("argv", [])]
    if not argv:
        raise CapabilityError("INTERNAL", "subprocess adapter needs config.argv")
    cp = subprocess.run(argv, capture_output=True, text=True, timeout=cap.config.get("timeout", 30))
    if cp.returncode != 0:
        raise CapabilityError("UNAVAILABLE", cp.stderr.strip() or f"exit {cp.returncode}")
    out = cp.stdout.strip()
    try:
        return json.loads(out) if out.startswith(("{", "[")) else {"stdout": out}
    except json.JSONDecodeError:
        return {"stdout": out}


# ── the whole dispatcher: ~40 lines, events by construction ───────────────────
def dispatch(registry: Registry, uri: str, payload: dict | None = None, *,
             events: Events | None = None, allow_commands: bool = True,
             actor: str = "caller") -> dict:
    events = events or Events()
    payload = payload or {}
    events.emit("run://call/command/start", actor=actor, target=uri)

    cap = registry.get(uri)
    if cap is None:
        return _fail(events, uri, actor, "NOT_FOUND", "no such capability")

    # safety gate — from the TYPED effect field, not a string in the URL
    if cap.effect == "command" and not allow_commands:
        return _fail(events, uri, actor, "PERMISSION_DENIED", "commands not allowed here")

    err = _validate(cap.input, payload)
    if err:
        return _fail(events, uri, actor, "INVALID_ARGUMENT", f"input: {err}")

    try:
        fn = ADAPTERS.get(cap.adapter)
        if fn is None:
            raise CapabilityError("INTERNAL", f"unknown adapter '{cap.adapter}'")
        result = fn(cap, payload)
    except CapabilityError as e:
        return _fail(events, uri, actor, e.category, e.message)
    except Exception as e:  # noqa: BLE001
        return _fail(events, uri, actor, "INTERNAL", f"{type(e).__name__}: {e}")

    # output validated against the contract — backend drift is caught, not trusted
    oerr = _validate(cap.output, result)
    if oerr:
        return _fail(events, uri, actor, "CONTRACT_VIOLATION", f"output: {oerr}")

    events.emit("run://call/command/done", actor=actor, target=uri,
                effect=cap.effect, capId=cap.id(), ok=True)
    return {"ok": True, "uri": uri, "capId": cap.id(), "result": result, "events": events.log}


def _fail(events: Events, uri: str, actor: str, category: str, message: str) -> dict:
    code = _error_code(category, message)
    events.emit(f"error://local/{code}/query/info", actor="runtime",
                code=code, category=category, status=_STATUS.get(category, 500),
                message=message, sourceUri=uri)
    return {"ok": False, "uri": uri, "error": {"code": code, "category": category,
            "message": message}, "events": events.log}


# ── conformance: examples ARE the tests (and few-shot, and a planner seed) ─────
def check_examples(registry: Registry, cap: Capability, events: Events | None = None) -> dict:
    """Run a capability's golden examples through the real adapter."""
    events = events or Events()
    results = []
    for ex in cap.examples:
        got = dispatch(registry, cap.uri, ex.get("input", {}), events=events)
        expected = ex.get("output")
        ok = got.get("ok") and (expected is None or got.get("result") == expected)
        results.append({"input": ex.get("input"), "ok": bool(ok),
                        "expected": expected, "got": got.get("result") or got.get("error")})
    return {"uri": cap.uri, "passed": sum(r["ok"] for r in results),
            "total": len(results), "results": results}
