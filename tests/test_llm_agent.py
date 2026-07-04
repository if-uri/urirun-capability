"""LLM-driven agent: operations are chosen at runtime by the LLM from a semantic
vocabulary (no hardcoded coordinates/values). Structure tested always; the live
LLM loop is gated (URIRUN_LLM_TEST=1)."""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm_agent import OPS, VOCAB  # noqa: E402


def test_operation_vocabulary_is_semantic_not_coordinate_based():
    # every op maps to a URI + an arg-builder; none takes pixel coordinates
    assert set(OPS) >= {"type", "select-all", "copy", "paste", "scroll", "click-text", "verify"}
    for name, (uri, mk) in OPS.items():
        assert uri.startswith("kvm://host/")
        args = mk("Zamów")
        assert "x" not in args and "y" not in args               # semantic, not pixels
    # copy/paste/select are keyboard-driven (portable), not screen coordinates
    assert OPS["copy"][1]("")["keys"] == "ctrl+c"
    assert OPS["paste"][1]("")["keys"] == "ctrl+v"
    assert OPS["select-all"][1]("")["keys"] == "ctrl+a"


def test_click_target_is_text_not_a_hardcoded_position():
    uri, mk = OPS["click-text"]
    assert mk("Zamów CyberMysz") == {"text": "Zamów CyberMysz"}   # LLM decides the text, at runtime


@pytest.mark.skipif(os.environ.get("URIRUN_LLM_TEST", "") != "1",
                    reason="set URIRUN_LLM_TEST=1 for the live LLM-driven agent loop")
def test_llm_decides_the_operation_stream_live():
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
    except Exception:
        pytest.skip("Ollama not running")
    from llm_agent import run
    r = run("wpisz numer FV-1 i skopiuj go", os.environ.get("URIRUN_LLM_MODEL", "gemma4:e4b"), max_steps=5)
    assert r["llm_decided"] and r["hardcoded"] is False
    assert r["steps"] >= 1
    # the stream is chosen from the vocabulary — every op is a known semantic operation
    assert all(s["op"] in OPS for s in r["stream"])
