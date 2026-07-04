"""Operator console: a Polish goal routes to the right deterministic capability and
returns an auditable verdict — over HTTP, no LLM."""
from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import console  # noqa: E402
from console import ask, ask_hybrid, make_handler, console_registry, EXAMPLES  # noqa: E402
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


def test_hybrid_degrades_honestly_when_ollama_is_down(monkeypatch):
    # point the hybrid at a dead port -> it must report, not crash
    monkeypatch.setattr("hybrid.OLLAMA", "http://127.0.0.1:1/api/generate")
    r = ask_hybrid("faktura na 1665 zł, bank 1655 zł")
    assert r["llm_proposed"] is None and "Ollama" in r["note"]


@pytest.mark.skipif(os.environ.get("URIRUN_LLM_TEST", "") != "1",
                    reason="set URIRUN_LLM_TEST=1 for the live hybrid extraction")
def test_hybrid_llm_extracts_and_capability_confirms():
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
    except Exception:
        pytest.skip("Ollama not running")
    r = ask_hybrid("faktura FV-1 na 1 665,00 zł, ale bank pokazuje tylko 1655 zł")
    assert r["llm_proposed"] is not None                       # LLM did the extraction
    conf = r["capability_confirmed"]
    assert conf["zamowienie"] == "1665.00" and conf["bank"] == "1655.00"  # capability normalized
    assert conf["rozbieznosci"]                                # and proved the gap


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
