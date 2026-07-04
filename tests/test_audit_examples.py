"""Invariant: EVERY capability's golden examples conform on the same principle —
a partial-spec output that verifies behaviour (extra runtime fields tolerated,
wrong values caught). Guards against a new capability shipping dead examples.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capability import check_examples, output_matches  # noqa: E402
from audit_examples import registries, reversibility_audit  # noqa: E402


def test_output_matches_is_partial_and_catches_wrong_values():
    # extra runtime fields tolerated
    assert output_matches({"ok": True}, {"ok": True, "inverse": {"pid": 9}, "ms": 3})
    # nested partial
    assert output_matches({"a": {"b": 1}}, {"a": {"b": 1, "c": 2}})
    # wrong value still caught
    assert not output_matches({"value": "hello"}, {"value": "WRONG"})
    # list length must match
    assert not output_matches({"xs": [1, 2]}, {"xs": [1, 2, 3]})


def test_every_example_across_every_registry_conforms():
    weak = []
    for reg_name, reg in registries().items():
        for cap in reg._caps.values():
            if not cap.examples:
                continue
            res = check_examples(reg, cap)
            if res["passed"] != res["total"]:
                weak.append(f"{reg_name} :: {cap.uri} ({res['passed']}/{res['total']})")
    assert not weak, "examples that do not conform:\n  " + "\n  ".join(weak)


def test_every_reversible_capability_has_a_verifiable_rollback():
    # invariant: a capability that declares reversible + examples must carry an inverse
    # whose args satisfy the inverse route's input — a broken rollback fails in CI
    broken = [f"{r['reg']} :: {r['uri']} — {r['why']}"
              for r in reversibility_audit() if not r["ok"]]
    assert not broken, "reversible capabilities with an unverifiable rollback:\n  " + "\n  ".join(broken)


def test_the_audit_actually_covers_reversible_capabilities():
    rev = reversibility_audit()
    assert len(rev) >= 6                              # office(2) + filepair(2) + windowpair(2) + fs
    assert any("office" in r["reg"] for r in rev) and any("fs" in r["reg"] for r in rev)


def test_capabilities_that_carry_examples_actually_have_them():
    # at least the real-handler registries must ship conformance data
    regs = registries()
    for key in ("hard_tasks(real)", "office(real)", "kvstore(real handlers)"):
        assert any(c.examples for c in regs[key]._caps.values()), key
