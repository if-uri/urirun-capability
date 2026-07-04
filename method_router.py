"""Method router — DECYDUJ jak pozyskać i jak rozdystrybuować informację, na podstawie
REALNYCH możliwości środowiska (profil env), nie zaszytego wyboru connectora.

Spina warstwy tej sesji:
  - czytanie: vguard (dhash → kotwica OCR → wizja LLM) = eskalacja metody wg pewności,
  - decyzja: urivision/VURI (DecisionCard),
  - metody: connectory/pluginy/rozszerzenia jako URI (kvm/ocr/camera/browser/fs/mail/web).

Ta sama potrzeba („przeczytaj tę stronę", „wyślij ten wynik") jest realizowana RÓŻNYMI
metodami zależnie od tego, co na danej maszynie DZIAŁA i jak pewnie. Router:
  1. odfiltrowuje metody, których wymagań środowisko nie spełnia,
  2. rankuje pozostałe wg (pewność-tutaj, koszt),
  3. zwraca plan tanie→drogie z eskalacją — wykonawca próbuje po kolei i weryfikuje.

Router jest DETERMINISTYCZNY (wybór z profilu), a warstwą otwartą (co znaczy obraz, jaką
treść wysłać) zostaje LLM/VURI — komplementarność [[complementarity]].
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

_COST = {"low": 0, "med": 1, "high": 2}


@dataclass(frozen=True)
class Method:
    uri: str                              # adres metody (connector/plugin/rozszerzenie)
    kind: str                             # "read" | "distribute"
    payload: str                          # co czyta (text/image/decision) lub wysyła (post/file/mail)
    needs: tuple[str, ...]                # wymagane zdolności (klucze profilu env)
    cost: str = "low"                     # low|med|high (czas/koszt)
    confidence: Callable[[dict], float] = field(default=lambda env: 1.0)  # jak PEWNA tutaj (0..1)
    note: str = ""


def _cap(env: dict, path: str, default=False):
    """Odczyt zagnieżdżonej zdolności z profilu, np. 'ocr.tesseract' albo 'cdp.reachable'."""
    cur = env or {}
    for part in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part, {})
    return cur if cur != {} else default


# --- Rejestr metod: te same POTRZEBY, różne connectory/pluginy/rozszerzenia -----------------
# confidence(env) czyta profil środowiska (twin://…/env/query/inventory + actionMatrix).
METHODS: list[Method] = [
    # ---- POZYSKANIE informacji (read) ----
    Method("kvm://host/screen/query/capture", "read", "image", ("input.uinput",),
           "low", lambda e: 1.0, "zrzut ekranu — prawie zawsze działa"),
    Method("ocr://host/image/query/text", "read", "text", ("ocr.tesseract",),
           "low", lambda e: 0.9 if _cap(e, "ocr.tesseract") else 0.0,
           "OCR obrazu — pewny gdy jest tesseract/easyocr"),
    Method("kvm://host/ui/query/verify", "read", "text", ("ocr.tesseract",),
           "low", lambda e: 0.85 if _cap(e, "actionMatrix.vision.locate") == "executable" else 0.35,
           "kotwica OCR na żywym ekranie — słaba gdy vision 'degraded'"),
    Method("kvm://host/a11y/command/act", "read", "element", ("atspi",),
           "low", lambda e: 0.8 if _cap(e, "atspi") else 0.0,
           "drzewo dostępności — 0 gdy przeglądarka nie wystawia treści (Firefox/Wayland)"),
    Method("browser://tab/page/query/text", "read", "text", ("cdp_or_plugin",),
           "low", lambda e: 0.98 if (_cap(e, "cdp.reachable") or _cap(e, "plugin")) else 0.0,
           "DOM przez CDP/plugin — najpewniejszy, gdy dostępny"),
    Method("camera://host/photo/query/ocr", "read", "text", ("camera",),
           "med", lambda e: 0.75 if _cap(e, "camera") else 0.0, "OCR ze zdjęcia kamery"),
    # DECYZJA o obrazie (nie bulk-tekst): „czy kompozytor otwarty?", „pokazać klientowi?"
    Method("vision://llm/query/decision-card", "read", "decision", ("llm",),
           "high", lambda e: 0.95 if _cap(e, "llm") else 0.0,
           "VURI/DecisionCard — warstwa 3: pytanie decyzyjne o obrazie (gdy OCR nie wystarcza)"),
    Method("kvm://host/ui/query/verify", "read", "decision", ("ocr.tesseract",),
           "low", lambda e: 0.8 if _cap(e, "actionMatrix.vision.locate") == "executable" else 0.3,
           "tania kotwica OCR jako decyzja — słaba gdy vision 'degraded' → eskalacja do VURI"),

    # ---- DYSTRYBUCJA informacji (distribute) ----
    Method("browser://tab/page/command/act", "distribute", "post", ("cdp_or_plugin",),
           "low", lambda e: 0.95 if (_cap(e, "cdp.reachable") or _cap(e, "plugin")) else 0.0,
           "publikacja po DOM — pewna"),
    Method("kvm://host/input/command/type", "distribute", "post", ("input.uinput",),
           "med", lambda e: 0.6, "publikacja klawiaturą (Ctrl+L/TAB) — działa, ale krucha bez DOM"),
    Method("mail://host/skrzynka/command/send", "distribute", "mail", ("smtp",),
           "low", lambda e: 0.9 if _cap(e, "smtp") else 0.0, "e-mail"),
    Method("fs://host/file/command/write-b64", "distribute", "file", ("fs.write_ok",),
           "low", lambda e: 0.95 if _cap(e, "fs.write_ok") else 0.0,
           "zapis pliku — 0 na węźle z zepsutym isolated-write (lenovo)"),
    Method("log://host/session/command/write", "distribute", "log", (),
           "low", lambda e: 0.8, "zapis do logu węzła — fallback zawsze dostępny"),
    Method("log://host/session/command/write", "distribute", "file", (),
           "low", lambda e: 0.5, "gdy fs zepsute: utrwal dane jako wpis logu (degradacja)"),
]

# Próg „wystarczająco pewna": powyżej wybieramy NAJTAŃSZĄ (tanie→drogie), poniżej — najpewniejszą.
GOOD_ENOUGH = 0.7


def _satisfies(need: str, env: dict) -> bool:
    if need == "cdp_or_plugin":
        return bool(_cap(env, "cdp.reachable") or _cap(env, "plugin"))
    return bool(_cap(env, need))


def select(kind: str, payload: str, env: dict, top: int = 3) -> list[dict]:
    """Zwróć uszeregowany plan metod dla potrzeby (kind, payload) w danym środowisku.
    Filtr wymagań → ranking (pewność malejąco, koszt rosnąco). Pusty = brak metody tutaj."""
    cand = []
    for m in METHODS:
        if m.kind != kind or m.payload != payload:
            continue
        conf = round(float(m.confidence(env)), 3)
        capable = all(_satisfies(n, env) for n in m.needs)
        if capable and conf > 0:
            cand.append({"uri": m.uri, "confidence": conf, "cost": m.cost, "note": m.note})
    # tanie→drogie: jeśli jakaś metoda jest „wystarczająco pewna", preferuj NAJTAŃSZĄ z nich
    # (eskalacja do drogiej tylko gdy tania nie wystarcza); inaczej rankuj wg pewności.
    good = [c for c in cand if c["confidence"] >= GOOD_ENOUGH]
    if good:
        good.sort(key=lambda c: (_COST[c["cost"]], -c["confidence"]))
        rest = sorted([c for c in cand if c["confidence"] < GOOD_ENOUGH],
                      key=lambda c: -c["confidence"])
        cand = good + rest
    else:
        cand.sort(key=lambda c: (-c["confidence"], _COST[c["cost"]]))
    return cand[:top]


def plan(kind: str, payload: str, env: dict) -> dict:
    """Plan wykonania tanie→drogie: pierwsza metoda to próba domyślna, reszta to eskalacja."""
    ranked = select(kind, payload, env, top=len(METHODS))
    return {
        "need": {"kind": kind, "payload": payload},
        "chosen": ranked[0] if ranked else None,
        "escalation": ranked[1:],
        "blocked": not ranked,
        "reason": ("brak metody spełniającej wymagania w tym środowisku"
                   if not ranked else f"wybrano {ranked[0]['uri']} (conf {ranked[0]['confidence']})"),
    }
