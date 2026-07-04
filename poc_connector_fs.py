"""Pilot migration: the real urirun-connector-fs (455 lines Python + contracts.py +
manifest.json) as descriptors on the shared runtime. Surfaces the NUANCES a real
connector has that a naive descriptor misses:

  1. reversible cross-route pairs (write-b64 <-> delete) with a concrete `inverse`;
  2. the gate must check each example's inverse.args satisfy the INVERSE route's input
     schema (check_reversibility) — a broken rollback fails declaratively;
  3. `isolated=True` handlers → the descriptor records adapter="subprocess" (isolation
     is a real property, carried in the descriptor, not lost).

The manifest is generated and its routes match the real connector's (interop).
"""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from capability import Capability, Registry

_W = "fs://host/file/command/write-b64"
_D = "fs://host/file/command/delete"


def fs_connector(base: Path) -> Registry:
    base = Path(base)

    def _read(path, max_bytes=None):
        p = base / path.lstrip("/")
        data = p.read_bytes()[: max_bytes] if max_bytes else p.read_bytes()
        return {"ok": True, "connector": "fs", "path": path, "name": p.name,
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "bytes_b64": base64.b64encode(data).decode()}

    def _write(path, bytes_b64, overwrite=False, make_dirs=False):
        p = base / path.lstrip("/")
        if make_dirs:
            p.parent.mkdir(parents=True, exist_ok=True)
        data = base64.b64decode(bytes_b64)
        p.write_bytes(data)
        return {"ok": True, "connector": "fs", "path": path, "requestedPath": path,
                "overwritten": bool(overwrite), "renamed": False, "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                # reversible: undo a write by deleting the path
                "inverse": {"uri": _D, "args": {"path": path}}}

    def _delete(path):
        p = base / path.lstrip("/")
        data = p.read_bytes()
        p.unlink()
        return {"ok": True, "connector": "fs", "path": path, "bytes": len(data),
                # reversible: undo a delete by re-writing the snapshotted bytes
                "inverse": {"uri": _W, "args": {"path": path,
                                                "bytes_b64": base64.b64encode(data).decode(),
                                                "overwrite": True}}}

    reg = Registry()
    reg.add(Capability(
        uri="fs://host/file/query/read-b64", effect="query",
        input={"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}},
        output={"type": "object", "required": ["bytes_b64"]},
        # isolation is a real property of this handler — recorded, not lost
        adapter="python", config={"fn": _read, "isolated": True}))
    reg.add(Capability(
        uri=_W, effect="command", reversible=True, inverse=_D,
        input={"type": "object", "required": ["path", "bytes_b64"],
               "properties": {"path": {"type": "string"}, "bytes_b64": {"type": "string"},
                              "overwrite": {"type": "boolean"}}},
        output={"type": "object", "required": ["sha256"]},
        examples=({"input": {"path": "/a.txt", "bytes_b64": "aGVsbG8="},
                   "output": {"inverse": {"uri": _D, "args": {"path": "/a.txt"}}}},),
        adapter="python", config={"fn": _write, "isolated": True}))
    reg.add(Capability(
        uri=_D, effect="command", reversible=True, inverse=_W,
        input={"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}},
        output={"type": "object", "required": ["bytes"]},
        examples=({"input": {"path": "/a.txt"},
                   "output": {"inverse": {"uri": _W, "args": {"path": "/a.txt",
                                          "bytes_b64": "aGVsbG8=", "overwrite": True}}}},),
        adapter="python", config={"fn": _delete, "isolated": True}))
    return reg
