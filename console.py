"""Operator console: type a Polish goal → it routes to the right deterministic
capability, runs it on a canned office scenario, and shows the verdict + provenance.

One UI over all the 'anti-LLM' audits. Routing is deterministic (plan_flow_nl over
the hard-task registry), execution is a typed capability, the verdict is auditable —
no LLM in the loop. GET / serves the page; POST /ask {goal} returns the verdict JSON.

    python console.py            # serve on :8790
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from capability import dispatch, Registry
from hard_tasks import hard_registry
from twin_nl import plan_flow_nl

# canned office scenarios so a routed capability has something real to chew on
SCENARIOS = {
    "recon://ksiegowosc/faktury/query/reconcile": {
        "left": [{"nr": "FV-2026-07-1", "kwota_brutto": "1 665,00 zł"}],
        "right": [{"ref": "FV-2026-07-1", "suma": "1655.00"}],
        "mapping": {"key": ["nr", "ref"], "amount": ["kwota_brutto", "suma"]}},
    "audit://zamowienie/query/consistency": {
        "docs": [{"doc": "zamowienie", "kwota": "1665,00"}, {"doc": "faktura", "kwota": "1655,00"},
                 {"doc": "przelew", "kwota": "1665,00"}]},
    "audit://faktura/query/consistency": {
        "lines": [{"nazwa": "CyberMysz", "ilosc": 3, "cena_brutto": "555,00"}],
        "stated_brutto": "1 650,00 zł"},
    "rules://zwrot/query/eligible": {"plan": "PrePaid", "days_since_purchase": 2, "used_actions": 0},
    "diag://system/query/rootcause": {"symptoms": ["cert-invalid", "ssl-verify-failed",
                                                    "connection-refused-https"]},
    "audit://dane/query/completeness": {
        "sources": [{"source": "email", "data": {"nr": "FV-1", "kwota": "1665"}},
                    {"source": "zamowienie", "data": {"nr": "FV-1", "termin": "jutro"}}],
        "required": ["nr", "kwota", "termin", "nip"]},
    "audit://instrukcje/query/conflicts": {
        "directives": [{"set": "odbiorca", "to": "szef"}, {"set": "odbiorca", "to": "ksiegowa"},
                       {"require": "zalacznik"}, {"forbid": "zalacznik"}]},
    "notes://rozmowa/query/extract": {
        "utterances": ["Jan: pogoda ladna", "Anna: zamawiamy 3 CyberMysz na jutro",
                       "Jan: do zrobienia raport na piatek", "Anna: milo bylo"]},
    "triage://zgloszenie/query/classify": {
        "text": "Płatność nie przeszła, faktura błędna, pilne!", "amount": "1665,00"},
}

EXAMPLES = ["uzgodnij fakturę z przelewem", "sprawdź spójność zamówienia",
            "czy faktura się sumuje", "czy należy się zwrot", "znajdź przyczynę awarii",
            "czego brakuje w danych", "wykryj sprzeczne instrukcje",
            "zrób notatki z rozmowy", "sklasyfikuj zgłoszenie"]


def ask(goal: str, reg: Registry | None = None) -> dict:
    reg = reg or hard_registry()
    steps = plan_flow_nl(reg, goal)
    if not steps:
        return {"goal": goal, "routed": None, "verdict": None,
                "note": "brak pasującej zdolności — spróbuj innego sformułowania"}
    uri = steps[0]["uri"]
    payload = SCENARIOS.get(uri, steps[0].get("payload", {}))
    out = dispatch(reg, uri, payload)
    return {"goal": goal, "routed": uri, "ok": out.get("ok"),
            "input": payload, "verdict": out.get("result") if out.get("ok") else out.get("error"),
            "deterministic": True, "needs_llm": False}


PAGE = """<!doctype html><meta charset=utf-8><title>Konsola operatora — audyty anty-LLM</title>
<style>
body{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;max-width:820px;margin:0 auto;padding:24px;
background:#141414;color:#ededed}
h1{font-size:22px;color:#b18cf0}input{width:100%;padding:11px;font-size:16px;border-radius:8px;
border:1px solid #3b3b3b;background:#1b1b1b;color:#ededed}
button{margin-top:10px;padding:10px 18px;background:#5b2ea6;color:#fff;border:0;border-radius:8px;
font-size:15px;cursor:pointer}
.chip{display:inline-block;margin:3px;padding:5px 10px;background:#26222f;border:1px solid #3b3b3b;
border-radius:20px;font-size:13px;cursor:pointer;color:#d6c7ff}
pre{background:#1b1b1b;border:1px solid #3b3b3b;border-radius:8px;padding:14px;overflow-x:auto;
white-space:pre-wrap;color:#d6c7ff}
.uri{color:#82b4ff;font-weight:600}.muted{color:#b4b4b4;font-size:13px}
</style>
<h1>Konsola operatora — deterministyczne audyty „anty-LLM"</h1>
<p class=muted>Wpisz cel po polsku. Router (bez LLM) dobierze zdolność, wykona ją na scenariuszu
biurowym i pokaże audytowalny werdykt.</p>
<input id=g placeholder="np. uzgodnij fakturę z przelewem" onkeydown="if(event.key=='Enter')go()">
<button onclick=go()>Wykonaj</button>
<div id=ex></div>
<div id=out></div>
<script>
var EX=__EXAMPLES__;
document.getElementById('ex').innerHTML=EX.map(function(e){return '<span class=chip onclick="pick(this)">'+e+'</span>'}).join('');
function pick(el){document.getElementById('g').value=el.textContent;go()}
function go(){var goal=document.getElementById('g').value;
 fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({goal:goal})})
 .then(function(r){return r.json()}).then(function(d){
   var v='<h3>Cel: '+goal+'</h3>';
   if(!d.routed){v+='<p class=muted>'+(d.note||'brak trafienia')+'</p>'}
   else{v+='<p>zdolność: <span class=uri>'+d.routed+'</span></p>';
        v+='<p class=muted>determinacja bez LLM · werdykt audytowalny</p>';
        v+='<pre>'+JSON.stringify(d.verdict,null,2)+'</pre>'}
   document.getElementById('out').innerHTML=v;
 })}
</script>"""


def make_handler(reg: Registry):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _send(self, code, body, ctype="application/json"):
            b = body.encode() if isinstance(body, str) else body
            self.send_response(code); self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE.replace("__EXAMPLES__", json.dumps(EXAMPLES, ensure_ascii=False)),
                           "text/html; charset=utf-8")
            elif self.path == "/health":
                self._send(200, json.dumps({"ok": True}))
            else:
                self._send(404, json.dumps({"error": "not found"}))

        def do_POST(self):
            if self.path != "/ask":
                return self._send(404, json.dumps({"error": "not found"}))
            n = int(self.headers.get("Content-Length", 0))
            goal = json.loads(self.rfile.read(n) or b"{}").get("goal", "")
            self._send(200, json.dumps(ask(goal, reg), ensure_ascii=False))
    return H


def serve(port: int = 8790):
    reg = hard_registry()
    print(f"Konsola operatora: http://127.0.0.1:{port}")
    HTTPServer(("127.0.0.1", port), make_handler(reg)).serve_forever()


if __name__ == "__main__":
    serve()
