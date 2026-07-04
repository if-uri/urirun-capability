"""LLM-sterowany agent operacji na pulpicie — decyzje w LOCIE, nie z hardkodowanych stałych.

Zgodnie z zasadą: wszystko istotne z punktu decyzji w trakcie wykonania zadania pochodzi
z LLM, nie z zaszytych współrzędnych/wartości/URL-i. Agent buduje CIĄGŁY STRUMIEŃ operacji
(wpisz / zaznacz / kopiuj / wklej / scroll / kliknij-tekst / weryfikuj), gdzie LLM wybiera
KAŻDĄ następną operację i jej argument na podstawie celu i informacji zwrotnej z ekranu.

Percepcja jest semantyczna (kliknięcia po TEKŚCIE przez OCR, nie po pikselach), a wartości
(co wpisać, co kliknąć) decyduje LLM — nic nie jest zaszyte na sztywno.

Weryfikacja WYNIKU pozostaje deterministyczna (recon://, audit:// z hard_tasks) — to
komplementarność: LLM decyduje i działa, zdolność sprawdza z dowodem.

    python llm_agent.py "wpisz numer faktury FV-1, zaznacz i skopiuj" [model]
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
NODE = os.environ.get("PC1_NODE", "http://127.0.0.1:28765")

# słownik operacji → adres URI węzła (SEMANTYCZNE, bez współrzędnych)
OPS = {
    "type":       ("kvm://host/input/command/type",       lambda a: {"text": a}),
    "select-all": ("kvm://host/input/command/key",         lambda a: {"keys": "ctrl+a"}),
    "copy":       ("kvm://host/input/command/key",         lambda a: {"keys": "ctrl+c"}),
    "paste":      ("kvm://host/input/command/key",         lambda a: {"keys": "ctrl+v"}),
    "key":        ("kvm://host/input/command/key",         lambda a: {"keys": a}),
    "scroll":     ("kvm://host/input/command/scroll",      lambda a: {"dy": -3 if a == "down" else 3}),
    "click-text": ("kvm://host/ui/command/click-text",     lambda a: {"text": a}),
    "verify":     ("kvm://host/ui/query/verify",           lambda a: {"text": a}),
}
VOCAB = "type, select-all, copy, paste, key, scroll, click-text, verify, done"


def _node(uri, payload):
    body = json.dumps({"uri": uri, "mode": "execute", "payload": payload}).encode()
    try:
        env = json.load(urllib.request.urlopen(urllib.request.Request(
            f"{NODE}/run", data=body, headers={"Content-Type": "application/json"}), timeout=60))
        v = (env.get("result") or {}).get("value") or {}
        return {"ok": bool(v.get("ok", env.get("ok", True))), "present": v.get("present")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:100]}


def decide(goal: str, history: list, last: dict, model: str) -> dict:
    """LLM wybiera NASTĘPNĄ operację (JSON). Nic zaszytego — op i arg pochodzą z modelu."""
    prompt = (
        "Jesteś agentem sterującym pulpitem przez pojedyncze operacje. "
        f"CEL: {goal}\n"
        f"Dostępne operacje: {VOCAB}. "
        "Zwróć TYLKO JSON: {\"op\": <operacja>, \"arg\": <argument lub pusty>} — "
        "jedną następną operację prowadzącą do celu. Dla 'type' arg to tekst do wpisania, "
        "dla 'click-text'/'verify' arg to widoczny tekst, dla 'key' arg jak 'ctrl+s'. "
        "Gdy cel osiągnięty, zwróć {\"op\": \"done\"}.\n"
        f"Wykonane dotąd: {json.dumps(history, ensure_ascii=False)}\n"
        f"Wynik ostatniej: {json.dumps(last, ensure_ascii=False)}")
    body = json.dumps({"model": model, "prompt": prompt, "stream": False, "format": "json",
                       "keep_alive": "5m", "options": {"temperature": 0.3}}).encode()
    try:
        resp = json.load(urllib.request.urlopen(urllib.request.Request(
            OLLAMA, data=body, headers={"Content-Type": "application/json"}), timeout=120)).get("response", "")
        d = json.loads(resp)
        return {"op": str(d.get("op", "done")).strip(), "arg": str(d.get("arg", "")).strip()}
    except Exception:
        return {"op": "done", "arg": ""}


def perceive(expect: str) -> dict:
    """Minimalna percepcja: czy spodziewany tekst jest już na ekranie (OCR). LLM używa
    tego jako informacji zwrotnej, żeby decydować na podstawie STANU, nie na ślepo."""
    if not expect:
        return {}
    return {"widoczne": bool(_node(OPS["verify"][0], {"text": expect}).get("present"))}


def run(goal: str, model: str = "gemma4:e4b", max_steps: int = 8) -> dict:
    history, last = [], {}
    stream = []
    for _ in range(max_steps):
        step = decide(goal, history, last, model)
        op, arg = step["op"], step["arg"]
        if op == "done" or op not in OPS:
            break
        uri, mk = OPS[op]
        res = _node(uri, mk(arg))
        # percepcja po akcji karmi następną decyzję LLM (zamknięta pętla, nie ślepa)
        last = {**res, **(perceive(arg) if op in ("type", "click-text") else {})}
        stream.append({"op": op, "arg": arg, "uri": uri, "ok": res.get("ok"),
                       "widoczne": last.get("widoczne")})
        history.append(f"{op}({arg})")
        vis = "" if last.get("widoczne") is None else (" 👁 widać" if last["widoczne"] else " 👁 brak")
        print(f"  LLM → {op}({arg})  → {uri}  {'✓' if res.get('ok') else '✗'}{vis}")
    return {"goal": goal, "stream": stream, "steps": len(stream), "llm_decided": True, "hardcoded": False}


if __name__ == "__main__":
    goal = sys.argv[1] if len(sys.argv) > 1 else "wpisz numer faktury FV-2026-07-1, zaznacz cały tekst i skopiuj do schowka"
    model = sys.argv[2] if len(sys.argv) > 2 else "gemma4:e4b"
    print(f"Cel: {goal}\nStrumień operacji decydowany przez LLM ({model}), bez hardkodowanych wartości:\n")
    r = run(goal, model)
    print(f"\n→ {r['steps']} operacji, wszystkie WYBRANE przez LLM w locie (hardcoded={r['hardcoded']}).")
