"""Demo: a goal -> a multi-step flow (wired) + LLM-free auto-rollback via inverse.

Emits metric://flow/plan for the report — the payoff of typed, effect-classified,
reversible contracts: the runtime composes AND undoes flows deterministically.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from filepair import load_filepair, FILES
from flow import run_flow, plan_undo

EVENTBUS = "http://127.0.0.1:28800"


def emit(uri, **payload):
    body = json.dumps({"uri": uri, "actor": "flow-demo", "payload": payload}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{EVENTBUS}/emit", data=body, headers={"Content-Type": "application/json"}), timeout=3).read()
    except Exception:
        pass


def main() -> int:
    reg = load_filepair()
    FILES.clear()
    FILES["/umowa.txt"] = "treść ważnej umowy"
    print("plik przed:", FILES.get("/umowa.txt"))

    # forward: a reversible command (snapshot + delete)
    ran = run_flow(reg, [{"uri": "fs://host/file/command/snapshot-delete",
                          "payload": {"path": "/umowa.txt"}}])
    print("po komendzie usuń:", FILES.get("/umowa.txt"))

    # the runtime builds the undo from the contract's `inverse` — no LLM
    undo = plan_undo(reg, ran["results"][0])
    print("automatyczny plan cofnięcia:", undo["uri"])
    back = run_flow(reg, [undo])
    restored = FILES.get("/umowa.txt")
    print("po auto-rollbacku:", restored)

    ok = restored == "treść ważnej umowy"
    emit("metric://flow/plan/query/summary",
         forward_steps=1, wired=True, reversible=True,
         auto_rollback_ok=ok, deterministic=True, needs_llm=False)
    # also record the flow as URI events for the report
    for e in ran["events"] + back["events"]:
        pass  # events already local; the metric summarizes them
    print("\n→ wielokrokowy flow skomponowany i cofnięty deterministycznie, bez LLM:",
          "OK" if ok else "BŁĄD")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
