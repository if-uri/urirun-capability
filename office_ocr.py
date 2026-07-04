"""Live 'anti-LLM' task #3/#5 on the twin: read a document by OCR and cross-verify
it against systems that disagree — deterministically.

Two systems disagree on an amount (order says 1665,00; bank says 1655,00). Rather
than guess, the worker OPENS the source invoice on the pc1 desktop and OCRs it: the
document corroborates exactly one system, so the other is the error. OCR presence
checks run on the live node; the reconciliation and verdict are deterministic.
"""
from __future__ import annotations

import base64
import json
import subprocess
import time
import urllib.request
from pathlib import Path

from capability import Capability, Registry, dispatch
from hard_tasks import money, reconcile, invoice_consistency

NODE = "http://127.0.0.1:28765"
DESKTOP = "pc1-desktop-1"
EVENTBUS = "http://127.0.0.1:28800"
SHOTS = Path(__file__).resolve().parents[1] / "pc1" / "reports" / "screenshots"

# the two systems that disagree, and the physical invoice that settles it
ORDER = {"nr": "FV-2026-07-1", "kwota_brutto": "1 665,00 zł"}
BANK = {"ref": "FV-2026-07-1", "suma": "1655.00"}
INVOICE_AMOUNT = "1 665,00 zł"     # what the printed invoice actually shows
# the invoice's own line items — used to verify it is internally consistent (#6)
LINES = [{"nazwa": "CyberMysz", "ilosc": 3, "cena_netto": "451,22", "cena_brutto": "555,00"}]

INVOICE_HTML = f"""<!doctype html><meta charset=utf-8><body style="font:28px/1.6 Arial;padding:40px">
<h1 style="color:#5b2ea6">Faktura VAT {ORDER['nr']}</h1>
<p>Sprzedawca: ifURI sp. z o.o. &nbsp; Nabywca: Biuro Firma sp. z o.o.</p>
<table style="font-size:26px;border-collapse:collapse">
<tr><td style="padding:8px 24px">3x CyberMysz</td><td style="padding:8px 24px">555,00 zł</td></tr>
<tr><td style="padding:8px 24px"><b>Razem brutto</b></td>
    <td style="padding:8px 24px"><b>{INVOICE_AMOUNT}</b></td></tr>
</table></body>"""


def ocr_registry(node: str = NODE) -> Registry:
    reg = Registry()
    reg.add(Capability(
        uri="kvm://pc1/ui/query/verify", effect="query",
        input={"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}},
        output={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
        examples=({"input": {"text": "555"}, "output": {"ok": True}},),
        adapter="http-node",
        config={"node": node, "remoteUri": "kvm://host/ui/query/verify"}))
    reg.add(Capability(
        uri="app://pc1/desktop/command/launch", effect="command",
        input={"type": "object", "required": ["app"], "properties": {"app": {"type": "string"}}},
        adapter="http-node",
        config={"node": node, "remoteUri": "app://host/desktop/command/launch"}))
    reg.add(Capability(
        uri="kvm://pc1/screen/query/capture", effect="query",
        input={"type": "object", "properties": {"base64": {"type": "boolean"}}},
        adapter="http-node",
        config={"node": node, "remoteUri": "kvm://host/screen/query/capture"}))
    return reg


def _present(reg, text: str) -> bool:
    out = dispatch(reg, "kvm://pc1/ui/query/verify", {"text": text})
    return bool(out.get("ok") and (out["result"] or {}).get("present"))


def emit(uri, **payload):
    body = json.dumps({"uri": uri, "actor": "biuro.pracownik", "payload": payload}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{EVENTBUS}/emit", data=body, headers={"Content-Type": "application/json"}), timeout=3).read()
    except Exception:
        pass


def run_invoice_audit(node: str = NODE) -> dict:
    reg = ocr_registry(node)

    # 1) two systems disagree — deterministic reconciliation flags it
    rec = reconcile([ORDER], [BANK], {"key": ["nr", "ref"], "amount": ["kwota_brutto", "suma"]})
    disc = rec["discrepancies"][0] if rec["discrepancies"] else None

    # 1b) the invoice is internally consistent (lines sum to gross, VAT 23% checks out)
    intra = invoice_consistency(LINES, INVOICE_AMOUNT)

    # 2) open the source invoice on the desktop and OCR it to settle the dispute
    subprocess.run(["docker", "exec", "-i", DESKTOP, "bash", "-c",
                    "cat > /tmp/faktura.html"], input=INVOICE_HTML.encode(), check=True)
    dispatch(reg, "app://pc1/desktop/command/launch",
             {"app": "chromium", "args": ["--no-sandbox", "--app=file:///tmp/faktura.html",
                                          "--force-device-scale-factor=1.3"], "settle": 7})
    time.sleep(5)
    order_amt = str(money(ORDER["kwota_brutto"]))    # 1665.00
    bank_amt = str(money(BANK["suma"]))              # 1655.00
    # OCR the DIGITS as they appear on the invoice (grouping tolerant)
    doc_shows_order = _present(reg, "1 665") or _present(reg, "1665")
    doc_shows_bank = _present(reg, "1 655") or _present(reg, "1655")

    # 3) deterministic verdict: the document corroborates exactly one system
    if doc_shows_order and not doc_shows_bank:
        verdict = {"invoice": order_amt, "correct_system": "zamowienie", "wrong_system": "bank"}
    elif doc_shows_bank and not doc_shows_order:
        verdict = {"invoice": bank_amt, "correct_system": "bank", "wrong_system": "zamowienie"}
    else:
        verdict = {"invoice": "niejednoznaczne", "correct_system": None, "wrong_system": None}

    # capture evidence
    cap = dispatch(reg, "kvm://pc1/screen/query/capture", {"base64": True})
    shot = None
    if cap.get("ok") and (cap["result"] or {}).get("pngBase64"):
        SHOTS.mkdir(parents=True, exist_ok=True)
        shot = SHOTS / "42-ocr-invoice-audit.png"
        shot.write_bytes(base64.b64decode(cap["result"]["pngBase64"]))

    emit("metric://hard-tasks/ocr/query/summary",
         systems_disagree=bool(disc), discrepancy=disc,
         ocr_shows_order=doc_shows_order, ocr_shows_bank=doc_shows_bank,
         verdict=verdict, intra_consistent=intra["consistent"],
         intra_computed=intra["computed_sum"], intra_stated=intra["stated"],
         deterministic=True, needs_llm=False, shot=str(shot) if shot else None)
    return {"discrepancy": disc, "ocr_order": doc_shows_order, "ocr_bank": doc_shows_bank,
            "verdict": verdict, "intra": intra, "shot": str(shot) if shot else None}


if __name__ == "__main__":
    r = run_invoice_audit()
    print("rozbieżność systemów:", r["discrepancy"])
    print(f"OCR faktury: pokazuje 1665={r['ocr_order']} / 1655={r['ocr_bank']}")
    print(f"werdykt: faktura={r['verdict']['invoice']}, poprawny system="
          f"{r['verdict']['correct_system']}, błędny={r['verdict']['wrong_system']}")
    i = r["intra"]
    print(f"spójność wewnątrz faktury: {i['consistent']} "
          f"(pozycje={i['computed_sum']}, brutto={i['stated']}, VAT ok={i['vat_ok']})")
    print("zrzut:", r["shot"])
