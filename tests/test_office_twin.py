"""NL office goal -> composed flow -> REAL execution on the live pc1 node.

Offline: planning is deterministic. Live (URIRUN_CAP_LIVE=1): the flow opens the
company shop on the desktop and captures it — the office loop end to end via mesh.
"""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_twin import office_twin_registry, run_office_goal_on_twin  # noqa: E402
from twin_nl import plan_flow_nl  # noqa: E402

NODE = os.environ.get("PC1_NODE", "http://127.0.0.1:28765")


def test_office_goal_plans_shop_then_capture_offline():
    steps = plan_flow_nl(office_twin_registry(NODE),
                         "otwórz sklep CyberMysz na pc1 i zrób zrzut zamówienia")
    assert [s["uri"] for s in steps] == [
        "app://pc1/desktop/command/launch",     # open the shop
        "kvm://pc1/screen/query/capture",        # capture it
    ]
    # the shop URL is seeded from the example, not invented
    assert any("--app=" in a for a in steps[0]["payload"].get("args", []))


@pytest.mark.skipif(os.environ.get("URIRUN_CAP_LIVE", "") != "1",
                    reason="needs the live twin node (URIRUN_CAP_LIVE=1)")
def test_office_goal_runs_on_live_twin_and_captures_shop():
    try:
        urllib.request.urlopen(f"{NODE}/health", timeout=3)
    except Exception:
        pytest.skip("twin pc1 node not running")
    r = run_office_goal_on_twin("otwórz sklep CyberMysz na pc1 i zrób zrzut zamówienia",
                                node=NODE, shot_name="41-office-twin-test")
    assert r["ok"], "the composed office flow must execute on the live node"
    assert r["shot"] and Path(r["shot"]).exists() and Path(r["shot"]).stat().st_size > 5000
    uris = [e["uri"] for e in r["events"]]
    assert "nl://office-twin/command/plan" in uris and "nl://office-twin/command/done" in uris
