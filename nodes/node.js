#!/usr/bin/env node
// A capability node (the "server" that executes URI processes) written in
// JavaScript. It speaks the language-neutral capability wire protocol, so a
// client in ANY language drives it with the same typed contract:
//
//   GET  /health        -> { ok, lang, capabilities }
//   GET  /capabilities  -> advertises what contracts it can satisfy (+ backend)
//   POST /dispatch {uri, payload} -> { ok, result } | { ok:false, error }
//
// Implements the SAME contract as the Go node: sys://host/os/query/info
"use strict";
const http = require("http");
const os = require("os");

const CAPS = [{
  uri: "sys://host/os/query/info",
  effect: "query",
  input: { type: "object", properties: {} },
  output: {
    type: "object", required: ["ok", "os", "arch", "lang"],
    properties: {
      ok: { type: "boolean" }, os: { type: "string" },
      arch: { type: "string" }, hostname: { type: "string" }, lang: { type: "string" },
    },
  },
  backend: "node:" + process.version,          // negotiation: how I satisfy it
}];

const HANDLERS = {
  "sys://host/os/query/info": () => ({
    ok: true, os: os.platform(), arch: os.arch(),
    hostname: os.hostname(), lang: "javascript",
  }),
};

function send(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, { "Content-Type": "application/json" });
  res.end(body);
}

http.createServer((req, res) => {
  if (req.method === "GET" && req.url === "/health")
    return send(res, 200, { ok: true, lang: "javascript", capabilities: CAPS.length });
  if (req.method === "GET" && req.url === "/capabilities")
    return send(res, 200, { lang: "javascript", capabilities: CAPS });
  if (req.method === "POST" && req.url === "/dispatch") {
    let data = "";
    req.on("data", (c) => (data += c));
    req.on("end", () => {
      let uri, payload;
      try { ({ uri, payload } = JSON.parse(data || "{}")); }
      catch { return send(res, 400, { ok: false, error: { category: "INVALID_ARGUMENT", message: "bad json" } }); }
      const h = HANDLERS[uri];
      if (!h) return send(res, 404, { ok: false, error: { category: "NOT_FOUND", message: "no such capability" } });
      try { send(res, 200, { ok: true, result: h(payload || {}) }); }
      catch (e) { send(res, 500, { ok: false, error: { category: "INTERNAL", message: String(e) } }); }
    });
    return;
  }
  send(res, 404, { ok: false });
}).listen(process.env.PORT || 8861, "0.0.0.0", () =>
  console.log(`capability node (javascript) on :${process.env.PORT || 8861}`));
