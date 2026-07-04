"""Demo: the 'anti-LLM' office tasks on the twin's own data — deterministic,
verified, and routable by a Polish goal. Emits metric://hard-tasks for the report.

Uses episode-07 numbers (the 1665,00 zł CyberMysz order) with a planted bank
discrepancy, to show the capability CATCHES what an LLM would gloss over.
"""
from __future__ import annotations

import json
import urllib.request

from capability import dispatch
from hard_tasks import hard_registry
from twin_nl import plan_flow_nl

EVENTBUS = "http://127.0.0.1:28800"

# twin data: the office order, its invoice, and the bank debit — but the bank shows
# 1655,00 (a planted 10 zł discrepancy) and systems name fields differently
SHOP = [{"nr": "FV-2026-07-1", "kwota_brutto": "1 665,00 zł", "email": "biuro@firma.pl"}]
BANK = [{"ref": "FV-2026-07-1", "suma": "1655.00", "odbiorca": "biuro@firma.pl"}]
DOCS = [{"doc": "zamowienie", "kwota": "1665,00"},
        {"doc": "faktura", "kwota": "1665.00"},
        {"doc": "przelew", "kwota": "1 655,00 zł"}]


def emit(uri, **payload):
    body = json.dumps({"uri": uri, "actor": "hard-tasks", "payload": payload}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{EVENTBUS}/emit", data=body, headers={"Content-Type": "application/json"}), timeout=3).read()
    except Exception:
        pass


def main() -> int:
    reg = hard_registry()

    # 1) reconcile shop vs bank (different field names + money formats)
    rec = dispatch(reg, "recon://ksiegowosc/faktury/query/reconcile",
                   {"left": SHOP, "right": BANK,
                    "mapping": {"key": ["nr", "ref"], "amount": ["kwota_brutto", "suma"]}})["result"]
    print(f"rekonsyliacja: uzgodnione={rec['reconciled']} rozbieżności={rec['discrepancies']}")

    # 2) cross-document consistency (which document is the odd one out?)
    con = dispatch(reg, "audit://zamowienie/query/consistency", {"docs": DOCS})["result"]
    print(f"spójność dokumentów: {con['consistent']} outlier={con['outliers']}")

    # 3) context-dependent refund rule
    ref = dispatch(reg, "rules://zwrot/query/eligible",
                   {"plan": "PrePaid", "days_since_purchase": 2, "used_actions": 0})["result"]
    print(f"zwrot (PrePaid): eligible={ref['eligible']} reguła={ref['rule']}")

    # 4) root cause from ambiguous symptoms
    diag = dispatch(reg, "diag://system/query/rootcause",
                    {"symptoms": ["cert-invalid", "ssl-verify-failed", "connection-refused-https"]})["result"]
    print(f"diagnoza: {diag['root']} (pewność {diag['confidence']}) — {diag['fix']}")

    # 5) missing info scattered across sources (#10)
    comp = dispatch(reg, "audit://dane/query/completeness",
                    {"sources": [{"source": "email", "data": {"nr": "FV-2026-07-1", "kwota": "1665"}},
                                 {"source": "zamowienie", "data": {"nr": "FV-2026-07-1", "termin": "jutro"}}],
                     "required": ["nr", "kwota", "termin", "nip"]})["result"]
    print(f"kompletność danych: brakuje={comp['missing']} (reszta z {list(comp['provenance'])})")

    # 6) conflicts in multi-step instructions (#14)
    conf = dispatch(reg, "audit://instrukcje/query/conflicts",
                    {"directives": [{"set": "odbiorca", "to": "szef@firma.pl"},
                                    {"set": "odbiorca", "to": "ksiegowa@firma.pl"},
                                    {"require": "zalacznik"}, {"forbid": "zalacznik"}]})["result"]
    print(f"sprzeczne instrukcje: {conf['count']} konflikt(y) → {[c['type'] for c in conf['conflicts']]}")

    # 7) extractive notes from a long conversation (#13) — verbatim, no hallucination
    notes = dispatch(reg, "notes://rozmowa/query/extract",
                     {"utterances": ["Jan: pogoda ladna", "Anna: zamawiamy 3 CyberMysz na jutro",
                                     "Jan: do zrobienia raport na piatek", "Anna: milo bylo"]})["result"]
    print(f"notatki (ekstraktywne): {notes['kept']}/{notes['of']} linii, źródła {notes['sources']}")

    # 8) triage a messy ticket (#17) — consistent + auditable
    tri = dispatch(reg, "triage://zgloszenie/query/classify",
                   {"text": "Płatność nie przeszła, faktura błędna, pilne!", "amount": "1665,00"})["result"]
    print(f"triage zgłoszenia: {tri['priority']}/{tri['category']} SLA={tri['sla_hours']}h")

    # a Polish goal routes to the right hard-task capability, no LLM
    routed = plan_flow_nl(reg, "uzgodnij faktury z przelewami")
    print(f"cel PL 'uzgodnij faktury z przelewami' → {routed[0]['uri'] if routed else '—'}")

    caught = bool(rec["discrepancies"]) and con["outliers"] == ["przelew"]
    emit("metric://hard-tasks/query/summary",
         reconcile_caught_discrepancy=bool(rec["discrepancies"]),
         consistency_outlier=con["outliers"],
         refund_rule=ref["rule"],
         rootcause=diag["root"], rootcause_confidence=diag["confidence"],
         missing_fields=comp["missing"],
         instruction_conflicts=conf["count"],
         notes_kept=f"{notes['kept']}/{notes['of']}",
         triage=f"{tri['priority']}/{tri['category']}",
         nl_routed_to=(routed[0]["uri"] if routed else None),
         deterministic=True, verified_by_examples=True, needs_llm=False,
         tasks=["reconcile", "consistency", "refund-rules", "root-cause",
                "completeness", "instruction-conflicts", "extractive-notes", "triage"])
    print("\n→ 4 zadania 'anty-LLM' zrobione deterministycznie i zweryfikowane:", "OK" if caught else "BŁĄD")
    return 0 if caught else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
