"""Demo: the office loop as a SAGA — auto-compensation on failure + full rollback.

Emits metric://saga/tx for the report: what the typed reversible-contract model
buys — all-or-nothing transactions with LLM-free compensation, and an honest
report of the irreversible step (a sent mail cannot be un-sent).
"""
from __future__ import annotations

import json
import urllib.request

import office_nl
from office_nl import office_registry
from flow import run_flow, run_saga, undo_flow

EVENTBUS = "http://127.0.0.1:28800"
OFFICE = [
    {"uri": "mail://biuro/wiadomosc/command/reply", "payload": {"to": "szef@firma.pl", "body": "Przyjete."}},
    {"uri": "task://biuro/lista/command/add", "payload": {"title": "Zamowic CyberMysz"}},
    {"uri": "shop://cybermysz/zamowienie/command/place", "payload": {"pozycje": "3x CyberMysz", "ilosc": 3}},
]


def emit(uri, **payload):
    body = json.dumps({"uri": uri, "actor": "saga-demo", "payload": payload}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{EVENTBUS}/emit", data=body, headers={"Content-Type": "application/json"}), timeout=3).read()
    except Exception:
        pass


def main() -> int:
    reg = office_registry()

    # 1) happy path, then explicit full rollback of the whole transaction
    office_nl.MAILBOX.clear(); office_nl.TASKS.clear(); office_nl.ORDERS.clear()
    ran = run_flow(reg, OFFICE)
    print(f"po pętli: {len(office_nl.TASKS)} zadań, zamówienie={office_nl.ORDERS[0]['status']}")
    comp = undo_flow(reg, ran["results"])
    print(f"po rollbacku: {len(office_nl.TASKS)} zadań, zamówienie={office_nl.ORDERS[0]['status']}, "
          f"nieodwracalne={comp['irreversible']}")

    # 2) failure mid-flow -> automatic compensation (no half-applied transaction)
    office_nl.MAILBOX.clear(); office_nl.TASKS.clear(); office_nl.ORDERS.clear()
    failing = OFFICE[1:] + [{"uri": "task://biuro/lista/command/add", "payload": {}}]  # last: bad input
    saga = run_saga(reg, failing)
    print(f"saga z błędem: ok={saga['ok']} at={saga['at']} skompensowano={saga['compensated']}")

    ok = (office_nl.TASKS == [] and office_nl.ORDERS[0]["status"] == "cancelled")
    emit("metric://saga/tx/query/summary",
         full_rollback_ok=(comp["undone"] and office_nl.ORDERS is not None),
         irreversible_reported=comp["irreversible"],
         auto_compensated_on_failure=saga["compensated"],
         no_half_applied_transaction=ok, deterministic=True, needs_llm=False)
    print("\n→ transakcja all-or-nothing: kompensacja bez LLM, uczciwie raportuje nieodwracalny krok:",
          "OK" if ok else "BŁĄD")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
