"""Hybrid pattern: the LLM proposes, a deterministic capability VERIFIES and has the
final say. This is the constructive synthesis of the empirical finding — use the LLM
where it is strong (open-ended NL → structure), and the typed capability where it is
strong (exact computation, proof, provenance) so the LLM's drift is caught, not shipped.

Two flows:
  verify(llm_answer, truth)          -> deterministic verdict; records if the LLM agreed
  extract_and_reconcile(text, model) -> LLM pulls structured amounts from messy free text,
                                        the reconcile capability decides (and corrects) it
"""
from __future__ import annotations

import json
import re
import urllib.request

from hard_tasks import money, reconcile

OLLAMA = "http://127.0.0.1:11434/api/generate"


def verify(llm_answer, truth) -> dict:
    """The deterministic truth always wins; we only record whether the LLM agreed.
    A 'trust but verify' gate: the LLM never ships an unverified number."""
    agreed = llm_answer == truth
    return {"final": truth, "llm_said": llm_answer, "agreed": agreed,
            "note": "OK" if agreed else f"LLM dryfnął: powiedział {llm_answer}, prawda {truth} — "
                                        "użyto wartości deterministycznej"}


def _llm(prompt: str, model: str, as_json: bool = False) -> str:
    body = {"model": model, "prompt": prompt, "stream": False, "keep_alive": "5m",
            "options": {"temperature": 0.4}}
    if as_json:
        body["format"] = "json"
    req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=180)).get("response", "")


def extract_amounts(text: str, model: str = "gemma4:e4b") -> dict:
    """LLM STRENGTH: read a messy free-text note and pull out the structured amounts.
    Returns {order, bank} as strings (whatever the model found)."""
    prompt = ("Z tekstu wyciagnij dwie kwoty jako JSON o kluczach 'zamowienie' i 'bank' "
              "(same liczby jako napisy, bez waluty). Tekst: " + text)
    raw = _llm(prompt, model, as_json=True)
    try:
        d = json.loads(raw)
        return {"order": str(d.get("zamowienie", "")), "bank": str(d.get("bank", ""))}
    except Exception:
        nums = re.findall(r"\d[\d  .,]*\d|\d", text)
        return {"order": nums[0] if nums else "", "bank": nums[1] if len(nums) > 1 else ""}


def extract_and_reconcile(text: str, model: str = "gemma4:e4b") -> dict:
    """Hybrid: LLM extracts the amounts (open-ended), the reconcile capability decides
    whether they match (exact, provable). The capability is the source of truth."""
    got = extract_amounts(text, model)
    rec = reconcile([{"nr": "X", "kwota_brutto": got["order"]}],
                    [{"ref": "X", "suma": got["bank"]}],
                    {"key": ["nr", "ref"], "amount": ["kwota_brutto", "suma"]})
    return {"extracted": got,
            "order_norm": str(money(got["order"])) if got["order"] else None,
            "bank_norm": str(money(got["bank"])) if got["bank"] else None,
            "reconciled": rec["reconciled"], "discrepancies": rec["discrepancies"],
            "verdict": "zgodne" if rec["reconciled"] else "rozbieżność wykryta"}


if __name__ == "__main__":
    import sys
    model = sys.argv[1] if len(sys.argv) > 1 else "gemma4:e4b"
    note = ("Cześć, zamówiliśmy 3 myszki, faktura FV-1 opiewa na 1 665,00 zł, "
            "ale na wyciągu z banku widzę tylko 1655 zł. Możesz sprawdzić?")
    print("tekst:", note)
    r = extract_and_reconcile(note, model)
    print("LLM wyciągnął:", r["extracted"])
    print(f"po normalizacji: zamówienie={r['order_norm']} bank={r['bank_norm']}")
    print("werdykt zdolności:", r["verdict"], r["discrepancies"])
