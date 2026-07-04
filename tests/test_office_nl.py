"""NL office goal -> composed flow from examples (episode 07 as capabilities)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import office_nl  # noqa: E402
from office_nl import office_registry, run_office_goal  # noqa: E402
from twin_nl import plan_flow_nl  # noqa: E402


def _reset():
    office_nl.MAILBOX.clear(); office_nl.TASKS.clear(); office_nl.ORDERS.clear()


def test_goal_composes_the_office_loop_in_mention_order():
    steps = plan_flow_nl(office_registry(), "odpowiedz szefowi, dopisz zadanie i zamów 3 CyberMysz")
    assert [s["uri"] for s in steps] == [
        "mail://biuro/wiadomosc/command/reply",
        "task://biuro/lista/command/add",
        "shop://cybermysz/zamowienie/command/place",
    ]
    # payloads came from the examples (seeds), no LLM
    order = next(s for s in steps if "zamowienie" in s["uri"])
    assert order["payload"]["pozycje"] == "3x CyberMysz"


def test_partial_goal_picks_only_relevant_capabilities():
    steps = plan_flow_nl(office_registry(), "zamów CyberMysz do biura")
    uris = [s["uri"] for s in steps]
    assert uris == ["shop://cybermysz/zamowienie/command/place"]  # only the order


def test_composed_flow_runs_and_changes_state():
    _reset()
    r = run_office_goal("odpowiedz szefowi i zamów 3 CyberMysz")
    assert len(r["mailbox"]) == 1 and r["mailbox"][0]["to"] == "szef@firma.pl"
    assert len(r["orders"]) == 1 and r["orders"][0]["ilosc"] == 3
    uris = [e["uri"] for e in r["events"]]
    assert "nl://office/command/plan" in uris and "nl://office/command/done" in uris


def test_input_contract_enforced_on_office_capabilities():
    from capability import dispatch
    reg = office_registry()
    bad = dispatch(reg, "task://biuro/lista/command/add", {})  # missing title
    assert not bad["ok"] and bad["error"]["category"] == "INVALID_ARGUMENT"
