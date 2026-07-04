"""NL office goal -> a composed flow of office capabilities, from examples.

The office loop (episode 07) expressed as typed capabilities: a Polish goal like
"odpowiedz szefowi, dopisz zadanie i zamów 3 CyberMysz" is decomposed into the
relevant capabilities, ordered by mention, with payloads seeded from each
capability's example — deterministically, no LLM.
"""
from __future__ import annotations

from capability import Capability, Registry, Events, dispatch
from twin_nl import plan_flow_nl   # generic NL matcher (keywords + order + example seeds)

# in-process office state, so the composed flow genuinely does something
MAILBOX: list[dict] = []
TASKS: list[dict] = []
ORDERS: list[dict] = []


def office_registry() -> Registry:
    reg = Registry()
    reg.add(Capability(
        uri="mail://biuro/wiadomosc/command/reply", effect="command",
        input={"type": "object", "required": ["to", "body"],
               "properties": {"to": {"type": "string"}, "body": {"type": "string"}}},
        output={"type": "object", "properties": {"sent": {"type": "boolean"}}},
        examples=({"input": {"to": "szef@firma.pl", "body": "Przyjete, zajmuje sie tym."},
                   "output": {"sent": True}},),
        adapter="python",
        config={"keywords": "odpowiedz odpowiedź odpisz mail poczta szef szefowi wiadomosc",
                "fn": lambda to, body: (MAILBOX.append({"to": to, "body": body}), {"sent": True})[1]}))
    # reversible: adding a task can be undone by removing it (inverse metadata in the result)
    reg.add(Capability(
        uri="task://biuro/lista/command/add", effect="command", reversible=True,
        inverse="task://biuro/lista/command/remove",
        input={"type": "object", "required": ["title"], "properties": {"title": {"type": "string"}}},
        output={"type": "object", "properties": {"taskId": {"type": "string"}}},
        examples=({"input": {"title": "Zamowic 3x CyberMysz (polecenie szefa)"},
                   "output": {"taskId": "T-bca1a2",
                              "inverse": {"uri": "task://biuro/lista/command/remove",
                                          "args": {"taskId": "T-bca1a2"}}}},),
        adapter="python",
        config={"keywords": "zadanie zadania dopisz lista todo notatka przypomnienie",
                "fn": _task_add}))
    reg.add(Capability(
        uri="task://biuro/lista/command/remove", effect="command",
        input={"type": "object", "required": ["taskId"], "properties": {"taskId": {"type": "string"}}},
        adapter="python", config={"internal": True, "fn": _task_remove}))
    # reversible: placing an order can be undone by cancelling it
    reg.add(Capability(
        uri="shop://cybermysz/zamowienie/command/place", effect="command", reversible=True,
        inverse="shop://cybermysz/zamowienie/command/cancel",
        input={"type": "object", "required": ["pozycje"],
               "properties": {"pozycje": {"type": "string"}, "ilosc": {"type": "integer"}}},
        output={"type": "object", "properties": {"orderId": {"type": "string"}}},
        examples=({"input": {"pozycje": "3x CyberMysz", "ilosc": 3},
                   "output": {"orderId": "ORD-408059",
                              "inverse": {"uri": "shop://cybermysz/zamowienie/command/cancel",
                                          "args": {"orderId": "ORD-408059"}}}},),
        adapter="python",
        config={"keywords": "zamow zamów zamowienie zamówienie kup kupic cybermysz sklep mysz sprzet",
                "fn": _order_place}))
    reg.add(Capability(
        uri="shop://cybermysz/zamowienie/command/cancel", effect="command",
        input={"type": "object", "required": ["orderId"], "properties": {"orderId": {"type": "string"}}},
        adapter="python", config={"internal": True, "fn": _order_cancel}))
    return reg


import hashlib


def _tid(text: str, prefix: str) -> str:
    """Content-addressed id: deterministic from the input, not from mutable state —
    so a golden example pins a stable value AND the op is idempotent-testable."""
    return f"{prefix}-{hashlib.blake2b(text.encode(), digest_size=3).hexdigest()}"


def _task_add(title):
    tid = _tid(title, "T")
    TASKS.append({"taskId": tid, "title": title})
    # the result carries its own inverse so the saga can compensate deterministically
    return {"taskId": tid, "inverse": {"uri": "task://biuro/lista/command/remove",
                                       "args": {"taskId": tid}}}


def _task_remove(taskId):
    TASKS[:] = [t for t in TASKS if t.get("taskId") != taskId]
    return {"removed": True, "taskId": taskId}


def _order_place(pozycje, ilosc=1):
    oid = _tid(f"{pozycje}x{ilosc}", "ORD")
    ORDERS.append({"orderId": oid, "pozycje": pozycje, "ilosc": ilosc, "status": "placed"})
    return {"orderId": oid, "inverse": {"uri": "shop://cybermysz/zamowienie/command/cancel",
                                        "args": {"orderId": oid}}}


def _order_cancel(orderId):
    for o in ORDERS:
        if o.get("orderId") == orderId:
            o["status"] = "cancelled"
    return {"cancelled": True, "orderId": orderId}


def run_office_goal(goal: str) -> dict:
    reg = office_registry()
    steps = plan_flow_nl(reg, goal)
    ev = Events()
    ev.emit("nl://office/command/plan", actor="pracownik", goal=goal, steps=[s["uri"] for s in steps])
    for step in steps:
        dispatch(reg, step["uri"], step["payload"], events=ev, actor="pracownik")
    ev.emit("nl://office/command/done", actor="pracownik", ran=len(steps))
    return {"goal": goal, "steps": [s["uri"] for s in steps], "payloads": [s["payload"] for s in steps],
            "mailbox": list(MAILBOX), "tasks": list(TASKS), "orders": list(ORDERS), "events": ev.log}


if __name__ == "__main__":
    import sys
    MAILBOX.clear(); TASKS.clear(); ORDERS.clear()
    goal = " ".join(sys.argv[1:]) or "odpowiedz szefowi, dopisz zadanie i zamów 3 CyberMysz"
    r = run_office_goal(goal)
    print("Cel:", r["goal"])
    print("Zaplanowana pętla biurowa (z examples, bez LLM):")
    for u, p in zip(r["steps"], r["payloads"]):
        print(f"  → {u}  {p}")
    print(f"\nWynik: {len(r['mailbox'])} mail(e), {len(r['tasks'])} zadań, {len(r['orders'])} zamówień")
