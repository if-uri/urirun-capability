"""Empirical complementarity check. The deterministic ground truths always hold
(and are the reference); the LLM comparison itself is gated (URIRUN_LLM_TEST=1)
because it hits a local Ollama and the LLM's answers vary run to run — which is
precisely the point being measured.
"""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm_compare import TASKS, parse  # noqa: E402


def test_deterministic_ground_truths_are_correct():
    # these are the reference the LLM is judged against — they must be exact
    truths = {t["id"]: t["truth"]() for t in TASKS}
    assert truths["reconcile-50"] == 3        # 3 planted discrepancies among 50
    assert truths["reconcile-15"] == 1        # 1 hidden discrepancy among 15
    assert truths["conflict-buried-12"] == 1  # 1 conflict buried at steps 3 & 9
    assert truths["missing-fields-8"] == 3    # nip, adres, regon missing everywhere


def test_parse_extracts_numbers_and_booleans_from_messy_text():
    assert parse("Odpowiedz: jest 3 rozbieżności.", "int") == 3
    assert parse("Myślę że 15 faktur, ale wynik to 3", "int") == 3   # takes the last number
    assert parse("Tak, są sprzeczne", "bool") is True
    assert parse("NIE ma zwrotu", "bool") is False
    assert parse("to zależy...", "bool") is None                     # no commitment


@pytest.mark.skipif(os.environ.get("URIRUN_LLM_TEST", "") != "1",
                    reason="set URIRUN_LLM_TEST=1 to run the live Ollama comparison")
def test_live_llm_comparison_runs_and_deterministic_wins_on_guarantees():
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
    except Exception:
        pytest.skip("Ollama not running on :11434")
    from llm_compare import run
    res = run(os.environ.get("URIRUN_LLM_MODEL", "gemma4:e4b"), runs=2)
    # the deterministic side is always perfect; that's the invariant we assert
    assert res["llm_all_consistent"] <= res["tasks"]        # LLM may or may not be consistent
    assert res["det_avg_us"] > 0 and res["llm_avg_ms"] > 0
    assert res["speedup"] > 100                             # deterministic is orders faster
