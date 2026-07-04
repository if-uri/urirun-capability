"""NL office goal -> composed flow -> REAL execution on the live pc1 node.

Offline: planning is deterministic. Live (URIRUN_CAP_LIVE=1): the flow opens the
company shop on the desktop and captures it — the office loop end to end via mesh.
"""
from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_twin import office_twin_registry, run_office_goal_on_twin  # noqa: E402
from twin_nl import plan_flow_nl  # noqa: E402
from flow import run_saga, undo_flow  # noqa: E402

NODE = os.environ.get("PC1_NODE", "http://127.0.0.1:28765")
DESKTOP = "pc1-desktop-1"


def _proc_state(pid: int) -> str:
    r = subprocess.run(["docker", "exec", DESKTOP, "ps", "-p", str(pid), "-o", "stat", "--no-headers"],
                       capture_output=True, text=True)
    return r.stdout.strip() or "GONE"


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


@pytest.mark.skipif(os.environ.get("URIRUN_CAP_LIVE", "") != "1",
                    reason="needs the live twin node (URIRUN_CAP_LIVE=1)")
def test_saga_on_live_twin_terminates_what_it_launched():
    """A saga on the live twin: launch a process, then roll the transaction back —
    the compensation (kill the launched pid via the node's inverse) actually
    terminates it. (The launcher becomes a zombie because the node's pid 1 does
    not reap children — a separate node-container defect; the process is dead.)"""
    try:
        urllib.request.urlopen(f"{NODE}/health", timeout=3)
    except Exception:
        pytest.skip("twin pc1 node not running")
    if subprocess.run(["docker", "inspect", DESKTOP], capture_output=True).returncode != 0:
        pytest.skip("pc1-desktop-1 not running")

    reg = office_twin_registry(NODE)
    steps = [{"uri": "app://pc1/desktop/command/launch", "payload": {"app": "xterm", "settle": 2}},
             {"uri": "kvm://pc1/screen/query/capture", "payload": {"base64": False}}]
    saga = run_saga(reg, steps)
    assert saga["ok"]
    pid = saga["results"][0]["result"]["pid"]
    assert not _proc_state(pid).startswith(("Z", "GONE")), "process should be alive inside the tx"

    comp = undo_flow(reg, saga["results"])
    assert "kvm://pc1/proc/command/kill" in comp["undone"], "compensation must dispatch the kill"
    import time
    time.sleep(2)
    st = _proc_state(pid)
    assert st == "GONE" or st.startswith("Z"), f"launched pid must be terminated, got {st}"
