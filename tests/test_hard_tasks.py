"""The 'anti-LLM' office tasks, done deterministically — tests assert both the
happy path AND that each catches the messy case an LLM typically fumbles.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capability import dispatch, check_examples  # noqa: E402
from hard_tasks import (hard_registry, money, reconcile, cross_consistency,  # noqa: E402
                        invoice_consistency, refund_eligible, root_cause,
                        field_completeness, instruction_conflicts,
                        extractive_notes, triage_ticket)


# ── money normalisation across systems (the reconciliation nightmare) ──────────
def test_money_normalisation_handles_every_messy_format():
    assert money("1 665,00 zł") == money("1665.00") == money("1,665.00") == money(1665)
    assert money("1.665,00") == money("1665")           # european thousands + comma decimal
    assert money("12,50") != money("1250")               # comma is decimal, not thousands


# ── 1) reconcile two systems with different field names + formats ──────────────
def test_reconcile_matches_across_different_names_and_formats():
    left = [{"nr": "FV-1", "kwota_brutto": "1 665,00 zł"}, {"nr": "FV-2", "kwota_brutto": "555,00"}]
    right = [{"ref": "FV-2", "suma": "555.00"}, {"ref": "FV-1", "suma": "1665.00"}]
    r = reconcile(left, right, {"key": ["nr", "ref"], "amount": ["kwota_brutto", "suma"]})
    assert r["reconciled"] and sorted(r["matched"]) == ["FV-1", "FV-2"]


def test_reconcile_catches_a_discrepancy_an_llm_would_gloss_over():
    # 1665,00 vs 1655,00 — a 10 zł gap hidden by different formatting
    left = [{"nr": "FV-1", "kwota_brutto": "1 665,00 zł"}]
    right = [{"ref": "FV-1", "suma": "1655.00"}]
    r = reconcile(left, right, {"key": ["nr", "ref"], "amount": ["kwota_brutto", "suma"]})
    assert not r["reconciled"]
    assert r["discrepancies"] == [{"key": "FV-1", "left": "1665.00", "right": "1655.00"}]


def test_reconcile_reports_rows_missing_on_either_side():
    r = reconcile([{"nr": "A", "kwota_brutto": "10"}],
                  [{"ref": "B", "suma": "10"}],
                  {"key": ["nr", "ref"], "amount": ["kwota_brutto", "suma"]})
    assert r["only_left"] == ["A"] and r["only_right"] == ["B"] and not r["reconciled"]


# ── 2) cross-document consistency (verify SENSE, not format) ────────────────────
def test_cross_consistency_agrees_despite_formatting():
    r = cross_consistency([{"doc": "zamowienie", "kwota": "1665,00"},
                           {"doc": "faktura", "kwota": "1665.00"},
                           {"doc": "przelew", "kwota": "1 665,00 zł"}])
    assert r["consistent"] and r["distinct"] == 1


def test_cross_consistency_flags_the_odd_document_out():
    r = cross_consistency([{"doc": "zamowienie", "kwota": "1665,00"},
                           {"doc": "faktura", "kwota": "1655,00"},   # the wrong one
                           {"doc": "przelew", "kwota": "1665,00"}])
    assert not r["consistent"] and r["outliers"] == ["faktura"]


# ── 2b) intra-document consistency (do the numbers add up? verify SENSE) ───────
def test_invoice_lines_sum_to_the_stated_total():
    r = invoice_consistency([{"nazwa": "CyberMysz", "ilosc": 3, "cena_brutto": "555,00"}],
                            "1 665,00 zł")
    assert r["consistent"] and r["lines_sum_ok"] and r["computed_sum"] == "1665.00"


def test_invoice_catches_a_tampered_total_an_llm_accepts():
    # lines add up to 1665 but the total says 1650 — a planted 15 zł discrepancy
    r = invoice_consistency([{"nazwa": "CyberMysz", "ilosc": 3, "cena_brutto": "555,00"}],
                            "1 650,00 zł")
    assert not r["consistent"] and r["lines_sum_ok"] is False and r["delta"] == "-15.00"


def test_invoice_catches_wrong_vat():
    # netto 451,22 * 1.23 = 555.00; here brutto is mis-stated as 500,00
    r = invoice_consistency([{"cena_netto": "451,22", "cena_brutto": "500,00", "ilosc": 1}],
                            "500,00")
    assert not r["consistent"] and r["vat_ok"] is False


# ── 3) context-dependent refund rules (auditable decision) ─────────────────────
def test_refund_rules_depend_on_plan_context():
    assert refund_eligible("BASIC", 5, 10)["eligible"] is True
    assert refund_eligible("BASIC", 20, 10)["eligible"] is False     # past 14d window
    assert refund_eligible("PRO", 20, 10)["eligible"] is True        # PRO window is 30d
    assert refund_eligible("PrePaid", 1, 0)["eligible"] is False     # non-refundable
    assert refund_eligible("PRO", 5, 500)["eligible"] is False       # over usage cap


def test_refund_decision_names_the_rule_that_fired():
    d = refund_eligible("PrePaid", 1, 0)
    assert d["rule"] == "prepaid-non-refundable"                     # auditable, not a guess


# ── 4) root cause from ambiguous overlapping symptoms ──────────────────────────
def test_root_cause_picks_the_explanation_covering_most_symptoms():
    # 'connection-refused' is shared by several causes; the CA one explains the most
    r = root_cause(["cert-invalid", "ssl-verify-failed", "connection-refused-https"])
    assert r["root"] == "ca-not-trusted" and r["confidence"] == 1.0


def test_root_cause_reports_what_it_cannot_explain():
    r = root_cause(["cert-invalid", "disk-full"])
    assert r["root"] == "ca-not-trusted"
    assert r["unexplained"] == ["disk-full"] and r["confidence"] == 0.5


# ── 5) missing info scattered across sources (#10) ─────────────────────────────
def test_completeness_finds_missing_fields_with_provenance():
    r = field_completeness(
        [{"source": "email", "data": {"nr": "FV-1", "kwota": "1665"}},
         {"source": "zamowienie", "data": {"nr": "FV-1", "termin": "jutro"}}],
        required=["nr", "kwota", "termin", "nip"])
    assert not r["complete"] and r["missing"] == ["nip"]          # nip is nowhere
    assert r["provenance"]["nr"] == ["email", "zamowienie"]        # nr seen in both
    assert r["provenance"]["termin"] == ["zamowienie"]


def test_completeness_treats_empty_values_as_missing():
    r = field_completeness([{"source": "form", "data": {"nip": "", "nr": "X"}}],
                           required=["nr", "nip"])
    assert r["missing"] == ["nip"]                                 # empty string ≠ present


# ── 6) conflicts in multi-step instructions (#14) ──────────────────────────────
def test_instruction_conflicts_flags_contradictory_values():
    r = instruction_conflicts([{"set": "odbiorca", "to": "szef@firma.pl"},
                               {"set": "kwota", "to": "1665"},
                               {"set": "odbiorca", "to": "ksiegowa@firma.pl"}])
    assert not r["consistent"] and r["count"] == 1
    c = r["conflicts"][0]
    assert c["type"] == "value-conflict" and c["field"] == "odbiorca" and c["steps"] == [0, 2]


def test_instruction_conflicts_flags_require_and_forbid():
    r = instruction_conflicts([{"require": "zalacznik"}, {"set": "temat", "to": "Re"},
                               {"forbid": "zalacznik"}])
    assert not r["consistent"]
    assert any(c["type"] == "require-forbid" and c["field"] == "zalacznik" for c in r["conflicts"])


def test_consistent_instructions_pass():
    r = instruction_conflicts([{"set": "odbiorca", "to": "szef"}, {"require": "faktura"}])
    assert r["consistent"] and r["count"] == 0


# ── 7) extractive notes (verbatim, no hallucination) (#13) ─────────────────────
def test_extractive_notes_keeps_only_decisions_and_numbers_verbatim():
    r = extractive_notes(["Jan: pogoda ladna dzisiaj",
                          "Anna: zamawiamy 3 CyberMysz",
                          "Jan: do zrobienia raport na piatek",
                          "Anna: milo bylo"])
    assert r["kept"] == 2 and r["sources"] == [1, 2]     # small-talk dropped
    # notes are VERBATIM (traceable), not generated
    assert all(n["text"] in ["Anna: zamawiamy 3 CyberMysz", "Jan: do zrobienia raport na piatek"]
               for n in r["notes"])


def test_extractive_notes_every_note_traces_to_a_source_line():
    r = extractive_notes(["kwota 1665 zl", "nic ważnego"])
    assert r["notes"][0]["line"] == 0 and r["notes"][0]["kind"] == "liczba/termin"


# ── 8) deterministic ticket triage (consistent + auditable) (#17) ──────────────
def test_triage_is_consistent_and_auditable():
    a = triage_ticket("System nie działa, awaria, pilne!")
    b = triage_ticket("System nie działa, awaria, pilne!")
    assert a == b                                         # same input -> same output
    assert a["priority"] == "krytyczny" and a["category"] == "techniczne" and a["sla_hours"] == 4
    assert a["matched_on"]                                # names what fired


def test_triage_escalates_on_money_even_when_wording_is_calm():
    calm = triage_ticket("Prośba o informację o fakturze", amount="1500,00")
    assert calm["priority"] == "wysoki"                   # escalated by amount >= 1000
    assert calm["category"] == "płatność"


def test_triage_escalates_on_age():
    r = triage_ticket("Pytanie ogólne", days_open=10)
    assert r["priority"] == "wysoki"                      # open > 7 days


# ── every capability's golden example still conforms (regression guard) ────────
def test_all_hard_capabilities_conform_and_dispatch():
    reg = hard_registry()
    assert len(reg._caps) == 9
    for cap in reg._caps.values():
        res = check_examples(reg, cap)
        assert res["passed"] == res["total"], f"{cap.uri}: {res}"
    # dispatch through the typed layer (input/output validated)
    out = dispatch(reg, "recon://ksiegowosc/faktury/query/reconcile",
                   {"left": [{"nr": "X", "kwota_brutto": "100,00"}],
                    "right": [{"ref": "X", "suma": "100.00"}],
                    "mapping": {"key": ["nr", "ref"], "amount": ["kwota_brutto", "suma"]}})
    assert out["ok"] and out["result"]["reconciled"] is True
