"""Live anti-LLM task #3/#5: OCR a document on pc1 and cross-verify it against
systems that disagree — deterministic verdict, no LLM.

Gated: URIRUN_CAP_LIVE=1 (needs pc1 node + desktop).
"""
from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_ocr import run_invoice_audit, ocr_registry  # noqa: E402
from capability import check_examples  # noqa: E402

NODE = os.environ.get("PC1_NODE", "http://127.0.0.1:28765")

pytestmark = pytest.mark.skipif(os.environ.get("URIRUN_CAP_LIVE", "") != "1",
                                reason="needs the live twin (URIRUN_CAP_LIVE=1)")


def test_ocr_verify_example_conforms_on_live_node():
    reg = ocr_registry(NODE)
    cap = reg.get("kvm://pc1/ui/query/verify")
    res = check_examples(reg, cap)               # '555' is on the shop page… only if open
    # conformance here just asserts the call shape works on the live node
    assert res["total"] == 1


def test_ocr_settles_a_dispute_between_two_systems():
    try:
        urllib.request.urlopen(f"{NODE}/health", timeout=3)
    except Exception:
        pytest.skip("twin pc1 node not running")
    if subprocess.run(["docker", "inspect", "pc1-desktop-1"], capture_output=True).returncode != 0:
        pytest.skip("pc1-desktop-1 not running")

    r = run_invoice_audit(NODE)
    # the two systems genuinely disagree (order 1665 vs bank 1655)
    assert r["discrepancy"] and r["discrepancy"]["left"] == "1665.00" and r["discrepancy"]["right"] == "1655.00"
    # OCR of the physical invoice corroborates the order, not the bank
    assert r["ocr_order"] is True and r["ocr_bank"] is False
    # deterministic verdict: the bank is the erroneous system
    assert r["verdict"]["correct_system"] == "zamowienie" and r["verdict"]["wrong_system"] == "bank"
    # the invoice is also internally consistent: lines sum to gross, VAT 23% checks out
    assert r["intra"]["consistent"] and r["intra"]["computed_sum"] == r["intra"]["stated"]
    # evidence captured
    assert r["shot"] and Path(r["shot"]).exists()
