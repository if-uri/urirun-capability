"""Hybrid 'LLM proposes, capability verifies' — the verify gate is pure and always
tested; the live extract→reconcile loop is gated on Ollama (URIRUN_LLM_TEST=1)."""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hybrid import verify, extract_and_reconcile  # noqa: E402


def test_verify_lets_the_deterministic_answer_win():
    r = verify(llm_answer=3, truth=3)
    assert r["agreed"] and r["final"] == 3 and r["note"] == "OK"


def test_verify_catches_llm_drift_and_keeps_the_truth():
    # the empirical case: LLM drifted to 30 on the 50-invoice task
    r = verify(llm_answer=30, truth=3)
    assert not r["agreed"] and r["final"] == 3          # deterministic wins, unverified never ships
    assert "dryf" in r["note"] and "30" in r["note"]


def test_verify_treats_no_commitment_as_disagreement():
    r = verify(llm_answer=None, truth=1)
    assert not r["agreed"] and r["final"] == 1


@pytest.mark.skipif(os.environ.get("URIRUN_LLM_TEST", "") != "1",
                    reason="set URIRUN_LLM_TEST=1 for the live LLM extraction loop")
def test_llm_extracts_and_the_capability_settles_it():
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
    except Exception:
        pytest.skip("Ollama not running")
    text = ("faktura FV-1 opiewa na 1 665,00 zł, ale na wyciągu z banku widzę tylko 1655 zł")
    r = extract_and_reconcile(text, os.environ.get("URIRUN_LLM_MODEL", "gemma4:e4b"))
    # whatever exact strings the LLM pulled, normalization + reconcile must flag the gap
    assert r["order_norm"] == "1665.00" and r["bank_norm"] == "1655.00"
    assert not r["reconciled"] and r["discrepancies"]
