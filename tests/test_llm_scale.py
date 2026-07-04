"""Scale sweep: the deterministic reference is exact at every N (always tested);
the live LLM curve is gated (URIRUN_LLM_TEST=1) since it hits Ollama and is slow."""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm_scale_sweep import make_pairs, SIZES, D  # noqa: E402
from hard_tasks import reconcile  # noqa: E402


def test_planted_discrepancies_are_exact_at_every_size():
    for n in SIZES:
        a, b, planted = make_pairs(n)
        truth = len(reconcile(a, b, {"key": ["nr", "ref"],
                                     "amount": ["kwota_brutto", "suma"]})["discrepancies"])
        assert truth == planted == D, (n, truth, planted)      # deterministic, exact, every N


def test_pairs_grow_but_discrepancy_count_stays_fixed():
    assert len(make_pairs(10)[0]) == 10 and len(make_pairs(75)[0]) == 75
    assert make_pairs(10)[2] == make_pairs(75)[2] == D          # same 3 discrepancies at any scale


@pytest.mark.skipif(os.environ.get("URIRUN_LLM_TEST", "") != "1",
                    reason="set URIRUN_LLM_TEST=1 for the live scale sweep")
def test_live_sweep_deterministic_is_correct_at_every_size():
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
    except Exception:
        pytest.skip("Ollama not running")
    from llm_scale_sweep import sweep
    res = sweep(os.environ.get("URIRUN_LLM_MODEL", "gemma4:e4b"), runs=1)
    # the deterministic reference must be exactly D at every size, regardless of the LLM
    assert all(r["truth"] == D for r in res["rows"])
    assert len(res["rows"]) == len(SIZES)
