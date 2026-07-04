"""Router metod: te same potrzeby → różne connectory zależnie od REALNego profilu środowiska.
Profil 'lenovo' odwzorowuje żywy env z twin://…/env/query/inventory (vision degraded,
brak CDP, ocr=tesseract, kamera, fs-write zepsuty) — patrz [[lenovo-browser-control]].

Zasada tanie→drogie: gdy jest metoda „wystarczająco pewna" (≥0.7), wybierz NAJTAŃSZĄ z nich;
eskaluj do drogiej (wizja LLM) dopiero gdy tania jest słaba (np. decyzja przy vision degraded)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from method_router import plan, select                      # noqa: E402

LENOVO = {
    "input": {"uinput": True, "xdotool": True, "ydotool": True},
    "ocr": {"tesseract": True, "easyocr": False},
    "atspi": True,
    "cdp": {"feasible": True, "reachable": False},
    "plugin": False,
    "camera": True,
    "fs": {"write_ok": False},                                # isolated-write znika
    "smtp": False,
    "llm": True,                                              # host ma dostęp do LLM (VURI)
    "actionMatrix": {"vision": {"locate": "degraded", "click": "degraded"}},
}
WITH_CDP = {**LENOVO, "cdp": {"feasible": True, "reachable": True}, "fs": {"write_ok": True},
            "actionMatrix": {"vision": {"locate": "executable"}}}


def test_read_text_uses_ocr_on_lenovo():
    # OCR obrazu (tesseract) jest tani i wystarczający — w sesji odczytał ekran (2774 znaki)
    p = plan("read", "text", LENOVO)
    assert p["chosen"]["uri"] == "ocr://host/image/query/text"
    assert p["chosen"]["cost"] == "low"


def test_read_text_prefers_dom_when_cdp_available():
    assert plan("read", "text", WITH_CDP)["chosen"]["uri"] == "browser://tab/page/query/text"


def test_read_decision_escalates_to_llm_when_vision_degraded():
    # decyzja o obrazie: tania kotwica OCR słaba (vision degraded, 0.3) → eskalacja do VURI
    p = plan("read", "decision", LENOVO)
    assert p["chosen"]["uri"] == "vision://llm/query/decision-card"
    assert any("ui/query/verify" in e["uri"] for e in p["escalation"])   # tania w eskalacji


def test_read_decision_prefers_cheap_anchor_when_vision_reliable():
    # gdy vision 'executable', tania kotwica OCR (0.8) wystarcza → nie płać za LLM
    p = plan("read", "decision", WITH_CDP)
    assert p["chosen"]["uri"] == "kvm://host/ui/query/verify"
    assert p["chosen"]["cost"] == "low"


def test_distribute_file_falls_back_to_log_when_fs_broken():
    p = plan("distribute", "file", LENOVO)                    # fs write_ok=False → wykluczone
    assert p["chosen"]["uri"] == "log://host/session/command/write"
    assert not any("fs://" in c["uri"] for c in [p["chosen"], *p["escalation"]])


def test_distribute_file_uses_fs_when_healthy():
    assert plan("distribute", "file", WITH_CDP)["chosen"]["uri"] == "fs://host/file/command/write-b64"


def test_distribute_post_uses_keyboard_without_dom():
    assert plan("distribute", "post", LENOVO)["chosen"]["uri"] == "kvm://host/input/command/type"
    assert plan("distribute", "post", WITH_CDP)["chosen"]["uri"] == "browser://tab/page/command/act"


def test_read_image_capture_always_available():
    assert select("read", "image", LENOVO)[0]["uri"] == "kvm://host/screen/query/capture"


def test_mail_blocked_without_smtp():
    p = plan("distribute", "mail", LENOVO)
    assert p["blocked"] and p["chosen"] is None
