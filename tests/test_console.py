"""Operator console: a Polish goal routes to the right deterministic capability and
returns an auditable verdict — over HTTP, no LLM."""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
from http.server import HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from console import ask, make_handler, console_registry, EXAMPLES  # noqa: E402
from hard_tasks import hard_registry  # noqa: E402

ROUTES = {
    "uzgodnij fakturę z przelewem": "recon://ksiegowosc/faktury/query/reconcile",
    "czy faktura się sumuje": "audit://faktura/query/consistency",
    "czy należy się zwrot": "rules://zwrot/query/eligible",
    "znajdź przyczynę awarii": "diag://system/query/rootcause",
    "czego brakuje w danych": "audit://dane/query/completeness",
    "wykryj sprzeczne instrukcje": "audit://instrukcje/query/conflicts",
    "zrób notatki z rozmowy": "notes://rozmowa/query/extract",
    "sklasyfikuj zgłoszenie": "triage://zgloszenie/query/classify",
}


def test_every_example_goal_routes_and_none_are_dead():
    from twin_nl import plan_flow_nl   # routing only — don't execute (twin goals would launch apps)
    reg = console_registry()           # includes the live-twin actions the chips offer
    for g in EXAMPLES:
        assert plan_flow_nl(reg, g), f"goal did not route: {g!r}"


def test_polish_goals_route_to_the_intended_capability():
    for goal, uri in ROUTES.items():
        assert ask(goal)["routed"] == uri, f"{goal!r} -> {ask(goal)['routed']} (wanted {uri})"


def test_verdict_is_deterministic_and_auditable():
    a = ask("znajdź przyczynę awarii")
    b = ask("znajdź przyczynę awarii")
    assert a == b                                   # same goal -> same verdict, no LLM
    assert a["verdict"]["root"] == "ca-not-trusted" and a["needs_llm"] is False


def test_unmatched_goal_is_reported_not_guessed():
    r = ask("ugotuj obiad")                         # nothing office-like
    assert r["routed"] is None and "brak" in r["note"]


def test_http_ask_endpoint_returns_the_verdict():
    srv = HTTPServer(("127.0.0.1", 0), make_handler(hard_registry()))
    threading.Thread(target=srv.handle_request, daemon=True).start()
    port = srv.server_address[1]
    req = urllib.request.Request(f"http://127.0.0.1:{port}/ask",
                                 data=json.dumps({"goal": "sklasyfikuj zgłoszenie"}).encode(),
                                 headers={"Content-Type": "application/json"})
    out = json.load(urllib.request.urlopen(req, timeout=5))
    assert out["routed"] == "triage://zgloszenie/query/classify"
    assert out["verdict"]["priority"] and out["deterministic"] is True
