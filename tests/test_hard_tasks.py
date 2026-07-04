"""The 'anti-LLM' office tasks, done deterministically — tests assert both the
happy path AND that each catches the messy case an LLM typically fumbles.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capability import dispatch, check_examples  # noqa: E402
from hard_tasks import (hard_registry, money, reconcile, cross_consistency,  # noqa: E402
                        refund_eligible, root_cause)


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


# ── every capability's golden example still conforms (regression guard) ────────
def test_all_hard_capabilities_conform_and_dispatch():
    reg = hard_registry()
    assert len(reg._caps) == 4
    for cap in reg._caps.values():
        res = check_examples(reg, cap)
        assert res["passed"] == res["total"], f"{cap.uri}: {res}"
    # dispatch through the typed layer (input/output validated)
    out = dispatch(reg, "recon://ksiegowosc/faktury/query/reconcile",
                   {"left": [{"nr": "X", "kwota_brutto": "100,00"}],
                    "right": [{"ref": "X", "suma": "100.00"}],
                    "mapping": {"key": ["nr", "ref"], "amount": ["kwota_brutto", "suma"]}})
    assert out["ok"] and out["result"]["reconciled"] is True
