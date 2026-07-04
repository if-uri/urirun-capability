"""Saga / compensating transaction over the office loop: roll the WHOLE loop back
via each step's inverse, and auto-compensate when a step fails mid-flow.

The honest limit is explicit: a sent mail cannot be un-sent, so it is reported as
irreversible rather than silently 'rolled back'.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import office_nl  # noqa: E402
from office_nl import office_registry  # noqa: E402
from flow import run_flow, run_saga, undo_flow  # noqa: E402


def _reset():
    office_nl.MAILBOX.clear(); office_nl.TASKS.clear(); office_nl.ORDERS.clear()


OFFICE_STEPS = [
    {"uri": "mail://biuro/wiadomosc/command/reply", "payload": {"to": "szef@firma.pl", "body": "Przyjete."}},
    {"uri": "task://biuro/lista/command/add", "payload": {"title": "Zamowic CyberMysz"}},
    {"uri": "shop://cybermysz/zamowienie/command/place", "payload": {"pozycje": "3x CyberMysz", "ilosc": 3}},
]


def test_undo_flow_rolls_back_the_whole_transaction():
    _reset()
    reg = office_registry()
    ran = run_flow(reg, OFFICE_STEPS)
    assert ran["ok"]
    assert len(office_nl.TASKS) == 1 and office_nl.ORDERS[0]["status"] == "placed"

    # roll the entire loop back — newest first — via each step's inverse
    comp = undo_flow(reg, ran["results"])
    assert "task://biuro/lista/command/remove" in comp["undone"]
    assert "shop://cybermysz/zamowienie/command/cancel" in comp["undone"]
    # the task is gone and the order is cancelled
    assert office_nl.TASKS == []
    assert office_nl.ORDERS[0]["status"] == "cancelled"
    # the sent mail is honestly reported as irreversible (cannot un-send)
    assert "mail://biuro/wiadomosc/command/reply" in comp["irreversible"]

    uris = [e["uri"] for e in comp["events"]]
    assert "saga://tx/command/rollback-start" in uris and "saga://tx/command/rollback-done" in uris


def test_saga_auto_compensates_when_a_step_fails():
    _reset()
    reg = office_registry()
    steps = [
        {"uri": "task://biuro/lista/command/add", "payload": {"title": "krok 1"}},
        {"uri": "shop://cybermysz/zamowienie/command/place", "payload": {"pozycje": "3x CyberMysz", "ilosc": 3}},
        {"uri": "task://biuro/lista/command/add", "payload": {}},   # invalid: missing title -> fails
    ]
    r = run_saga(reg, steps)
    assert not r["ok"] and r["at"] == 2
    # the two completed reversible steps were compensated automatically
    assert "task://biuro/lista/command/remove" in r["compensated"]
    assert "shop://cybermysz/zamowienie/command/cancel" in r["compensated"]
    # no half-applied transaction: task removed, order cancelled
    assert office_nl.TASKS == []
    assert office_nl.ORDERS and office_nl.ORDERS[0]["status"] == "cancelled"


def test_saga_commits_on_success():
    _reset()
    reg = office_registry()
    r = run_saga(reg, OFFICE_STEPS)
    assert r["ok"]
    assert office_nl.ORDERS[0]["status"] == "placed" and len(office_nl.TASKS) == 1
    assert "saga://tx/command/commit" in [e["uri"] for e in r["events"]]
