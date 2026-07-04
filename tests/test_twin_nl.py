"""NL goal -> flow -> run on the LIVE pc1 node -> auto-rollback via inverse.

The whole thesis end to end: examples seed the planner, typed contracts classify
effect + reversibility, the http-node adapter drives the real mesh, and the
runtime undoes the reversible step deterministically (no LLM).

Gated: URIRUN_CAP_LIVE=1 (needs the twin's pc1 node on 127.0.0.1:28765).
"""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from twin_nl import twin_registry, plan_flow_nl, run_goal  # noqa: E402

NODE = os.environ.get("PC1_NODE", "http://127.0.0.1:28765")

pytestmark = pytest.mark.skipif(
    os.environ.get("URIRUN_CAP_LIVE", "") != "1",
    reason="needs the live twin node (URIRUN_CAP_LIVE=1)")


def _node_up() -> bool:
    try:
        urllib.request.urlopen(f"{NODE}/health", timeout=3)
        return True
    except Exception:
        return False


def test_nl_goal_plans_the_right_sequence_offline():
    # planning is deterministic and needs no node / no LLM
    reg = twin_registry(NODE)
    steps = plan_flow_nl(reg, "otwórz terminal i zrób zrzut ekranu na pc1")
    uris = [s["uri"] for s in steps]
    assert uris == ["app://pc1/desktop/command/launch", "kvm://pc1/screen/query/capture"], uris
    # the internal kill capability is never planned from a goal
    assert "kvm://pc1/proc/command/kill" not in uris
    # payloads came from the examples (seeds)
    assert steps[0]["payload"].get("app") == "xterm"


def test_nl_goal_runs_on_live_node_and_auto_rolls_back():
    if not _node_up():
        pytest.skip("twin pc1 node not running")
    r = run_goal("otwórz terminal i zrób zrzut ekranu na pc1", node=NODE)
    assert r["ok"], "the planned flow must execute on the live node"
    assert r["steps"] == ["app://pc1/desktop/command/launch", "kvm://pc1/screen/query/capture"]
    # the reversible launch was undone automatically via the node's concrete inverse
    assert r["undone"] == ["kvm://pc1/proc/command/kill"], r["undone"]
    # events record the whole episode
    uris = [e["uri"] for e in r["events"]]
    assert "nl://goal/command/plan" in uris and "nl://goal/command/done" in uris
