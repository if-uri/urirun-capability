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
    reg.add(Capability(
        uri="task://biuro/lista/command/add", effect="command",
        input={"type": "object", "required": ["title"], "properties": {"title": {"type": "string"}}},
        output={"type": "object", "properties": {"added": {"type": "boolean"}}},
        examples=({"input": {"title": "Zamowic 3x CyberMysz (polecenie szefa)"},
                   "output": {"added": True}},),
        adapter="python",
        config={"keywords": "zadanie zadania dopisz lista todo notatka przypomnienie",
                "fn": lambda title: (TASKS.append({"title": title}), {"added": True})[1]}))
    reg.add(Capability(
        uri="shop://cybermysz/zamowienie/command/place", effect="command",
        input={"type": "object", "required": ["pozycje"],
               "properties": {"pozycje": {"type": "string"}, "ilosc": {"type": "integer"}}},
        output={"type": "object", "properties": {"orderId": {"type": "string"}}},
        examples=({"input": {"pozycje": "3x CyberMysz", "ilosc": 3},
                   "output": {"orderId": "ORD-1"}},),
        adapter="python",
        config={"keywords": "zamow zamów zamowienie zamówienie kup kupic cybermysz sklep mysz sprzet",
                "fn": lambda pozycje, ilosc=1: (ORDERS.append({"pozycje": pozycje, "ilosc": ilosc}),
                                                {"orderId": f"ORD-{len(ORDERS)}"})[1]}))
    return reg


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
