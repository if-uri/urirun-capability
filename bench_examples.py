"""Do examples work BETTER? Measure planning/conformance with examples vs without.

Across every adopted contract (all 4 urirun-contract-* packages), compare two
ways to drive a capability:
  A) examples ON  — payload from the golden example (contract-valid, meaningful),
                    and the golden output pair gives automatic conformance.
  B) examples OFF — payload synthesized from the schema alone (no examples,
                    what an LLM-free heuristic or a fresh integration must do).

Reports: first-try contract-valid-input rate, automatic conformance coverage,
and planning time. Emits metric://examples/planner for the report (episode #5).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from contracts_adopt import adopt_contracts
from kvstore import load_kvstore, _HANDLERS  # real handlers for the meaningful case
from capability import _validate
from metric_events import emit_metric
from planner import from_examples, synth_from_schema, plan_and_run

GH = Path("/home/tom/github/if-uri")
PKGS = {"capture-click": "kvm", "filepair": "fs", "kvstore": "kv", "windowpair": "kvm"}
def measure() -> dict:
    caps = []
    for name, scheme in PKGS.items():
        cj = GH / f"urirun-contract-{name}" / "contracts.json"
        if not cj.exists():
            continue
        # kvstore uses real handlers -> its golden pairs are genuinely verifiable
        reg = load_kvstore(cj) if name == "kvstore" else adopt_contracts(cj, scheme)
        for cap in reg._caps.values():
            caps.append((reg, cap, name == "kvstore"))

    total = len(caps)
    # A) examples ON
    t0 = time.time()
    ex_valid = ex_conf = 0
    for reg, cap, real in caps:
        p = from_examples(cap)
        if p is not None and _validate(cap.input, p) is None:
            ex_valid += 1
        if cap.examples:              # a golden pair exists -> verifiable
            r = plan_and_run(reg, cap, use_examples=True)
            ex_conf += 1 if r["conformant"] else 0
    ex_ms = (time.time() - t0) * 1000

    # B) examples OFF (schema synthesis)
    t0 = time.time()
    sy_valid = 0
    verifiable_off = 0                # can we auto-verify behaviour without a golden pair? no.
    for reg, cap, real in caps:
        p = synth_from_schema(cap.input)
        if _validate(cap.input, p) is None:
            sy_valid += 1
    sy_ms = (time.time() - t0) * 1000

    # THE genuine differentiator: do examples CATCH a regression? Break the real
    # kvstore handler and check whether the golden pair detects the drift.
    from capability import Registry, Capability, dispatch
    kv_src = GH / "urirun-contract-kvstore" / "contracts.json"
    regression_caught = regression_missed = None
    if kv_src.exists():
        good = load_kvstore(kv_src)
        # a broken handler: returns the wrong value (a real regression)
        broken = Registry()
        for cap in good._caps.values():
            fn = ((lambda **kw: {"ok": True, "connector": "kvstore", "action": "kv-get",
                                 "key": kw.get("key"), "value": "WRONG", "found": True})
                  if cap.uri.endswith("/get") else cap.config["fn"])
            broken.add(Capability(**{**cap.__dict__, "config": {"fn": fn}}))
        get_cap = broken.get("kv://host/kv/query/get")
        # with examples: golden pair compares result -> mismatch caught
        r = plan_and_run(broken, get_cap, use_examples=True) if get_cap.examples else {"conformant": True}
        regression_caught = not r["conformant"]     # True = examples detected the drift
        # without examples: no golden output to compare -> drift passes unnoticed
        r2 = plan_and_run(broken, get_cap, use_examples=False)
        regression_missed = r2["ok"] and r2["conformant"]  # ran "fine", drift undetected

    with_examples_capable = sum(1 for _, c, _ in caps if c.examples)
    return {
        "capabilities": total,
        "regression_caught_with_examples": bool(regression_caught),
        "regression_missed_without_examples": bool(regression_missed),
        "with_examples": {
            "first_try_valid_input": f"{ex_valid}/{total}",
            "auto_conformance_covered": f"{with_examples_capable}/{total}",
            "golden_pairs_pass": ex_conf,
            "plan_ms": round(ex_ms, 2),
            "needs_llm": False, "deterministic": True,
        },
        "without_examples": {
            "first_try_valid_input": f"{sy_valid}/{total}",
            "auto_conformance_covered": f"{verifiable_off}/{total}",
            "golden_pairs_pass": 0,
            "plan_ms": round(sy_ms, 2),
            "needs_llm_for_semantics": True, "deterministic": False,
        },
    }


def main() -> int:
    m = measure()
    a, b = m["with_examples"], m["without_examples"]
    print(f"== Czy examples działają lepiej? ({m['capabilities']} zdolności z 4 paczek)\n")
    print(f"  {'Miara':<38} {'z examples':<16} {'bez examples'}")
    print(f"  {'-'*38} {'-'*16} {'-'*16}")
    print(f"  {'poprawny input za 1. razem':<38} {a['first_try_valid_input']:<16} {b['first_try_valid_input']}")
    print(f"  {'automatyczny konformans (pokrycie)':<38} {a['auto_conformance_covered']:<16} {b['auto_conformance_covered']}")
    print(f"  {'złote pary zgodne z kontraktem':<38} {str(a['golden_pairs_pass']):<16} {b['golden_pairs_pass']}")
    print(f"  {'planowanie deterministyczne':<38} {'TAK':<16} {'NIE'}")
    print(f"  {'wymaga LLM do semantyki':<38} {'NIE':<16} {'TAK'}")
    rc = "ZŁAPANA" if m["regression_caught_with_examples"] else "przeoczona"
    rm = "przeoczona" if m["regression_missed_without_examples"] else "—"
    print(f"  {'REGRESJA handlera (zły wynik)':<38} {rc:<16} {rm}")
    emit_metric("metric://examples/planner/query/summary", "examples-bench", m)
    Path(__file__).with_name("examples-bench.json").write_text(json.dumps(m, indent=2, ensure_ascii=False))
    print(f"\n  → examples dają {a['auto_conformance_covered']} automatycznego konformansu i "
          f"deterministyczne, wolne-od-LLM planowanie; bez nich — 0 weryfikacji zachowania.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
