"""Expose a Capability registry over a language-neutral HTTP + OpenAPI surface.

The capability descriptor is already JSON + JSON Schema — inherently portable.
This serves it so ANY tech stack (curl, JS, Go, an OpenAPI codegen client) can
drive the same capabilities, with the same typed contracts and events.

    GET  /capabilities        -> list of capability descriptors (portable JSON)
    GET  /openapi.json        -> OpenAPI 3 spec generated from the registry
    POST /dispatch {uri,payload} -> run a capability; returns result + events + ms
    GET  /health

Stdlib only.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from capability import Registry, Events, dispatch, metrics


def to_openapi(reg: Registry) -> dict:
    """Generate an OpenAPI 3 spec: each capability is a POST operation whose
    request/response bodies ARE the capability's input/output JSON Schema."""
    paths = {}
    for uri, cap in reg._caps.items():
        op_id = uri.replace("://", "_").replace("/", "_")
        paths["/dispatch/" + op_id] = {
            "post": {
                "operationId": op_id,
                "summary": uri,
                "x-uri": uri,
                "x-effect": cap.effect,
                "x-capability-id": cap.id(),
                "x-reversible": cap.reversible,
                "requestBody": {"content": {"application/json": {
                    "schema": cap.input or {"type": "object"}}}},
                "responses": {
                    "200": {"description": "ok", "content": {"application/json": {
                        "schema": cap.output or {"type": "object"}}}},
                    "4XX": {"description": "typed error (error:// taxonomy: "
                                           + ", ".join(cap.errors) + ")"},
                },
            }
        }
    return {"openapi": "3.0.3",
            "info": {"title": "urirun capabilities", "version": "2.0",
                     "description": "Language-neutral surface over typed URI capabilities."},
            "paths": paths}


def make_handler(reg: Registry):
    op_index = {uri.replace("://", "_").replace("/", "_"): uri for uri in reg._caps}

    class H(BaseHTTPRequestHandler):
        def _json(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):
            return

        def do_GET(self):
            if self.path == "/health":
                return self._json(200, {"ok": True, "capabilities": len(reg._caps)})
            if self.path == "/openapi.json":
                return self._json(200, to_openapi(reg))
            if self.path == "/capabilities":
                # the PORTABLE descriptor (contract), never the config — config carries
                # the handler fn, which is neither serialisable nor safe to expose
                return self._json(200, {"capabilities": [
                    {**c.contract(), "id": c.id()} for c in reg._caps.values()]})
            return self._json(404, {"ok": False})

        def do_POST(self):
            n = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(n) or b"{}")
            uri = data.get("uri")
            if not uri and self.path.startswith("/dispatch/"):
                uri = op_index.get(self.path[len("/dispatch/"):])
            if not uri:
                return self._json(400, {"ok": False, "error": "uri required"})
            ev = Events()
            out = dispatch(reg, uri, data.get("payload", {}), events=ev, actor="http-client")
            out["metrics"] = metrics(ev)
            return self._json(200 if out.get("ok") else 422, out)

    return H


def serve(reg: Registry, host: str = "127.0.0.1", port: int = 8850):
    print(f"capabilities on http://{host}:{port}  (/openapi.json, /capabilities, POST /dispatch)")
    ThreadingHTTPServer((host, port), make_handler(reg)).serve_forever()


if __name__ == "__main__":
    from capability import Capability
    r = Registry()
    r.add(Capability(
        uri="demo://local/echo/query/text", effect="query", idempotent=True,
        input={"type": "object", "required": ["text"],
               "properties": {"text": {"type": "string"}}},
        output={"type": "object", "required": ["echoed"],
                "properties": {"echoed": {"type": "string"}}},
        adapter="python", config={"fn": lambda text: {"echoed": text}}))
    serve(r)
