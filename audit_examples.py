"""Audit: do the `examples` across EVERY capability work on the same principle —
golden input->output pairs that genuinely verify the handler (catch regressions)?

Flags the nuance: real-handler capabilities verify behaviour; stub-adopted ones
(contracts imported via adopt_contracts) may pass only tautologically. Prints a
per-registry report so we can find and fix the weak spots.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capability import check_examples, check_reversibility, Registry
from contracts_adopt import adopt_contracts
from kvstore import load_kvstore
from hard_tasks import hard_registry
from office_nl import office_registry

GH = Path("/home/tom/github/if-uri")
CONTRACT_PKGS = {"capture-click": "kvm", "filepair": "fs", "kvstore": "kv", "windowpair": "kvm"}


def registries() -> dict[str, Registry]:
    regs = {"kvstore(real handlers)": load_kvstore(GH / "urirun-contract-kvstore" / "contracts.json"),
            "hard_tasks(real)": hard_registry(),
            "office(real)": office_registry()}
    for name, scheme in CONTRACT_PKGS.items():
        cj = GH / f"urirun-contract-{name}" / "contracts.json"
        if cj.exists():
            regs[f"adopt:{name}(stub)"] = adopt_contracts(cj, scheme)
    return regs


def reversibility_audit() -> list[dict]:
    """Every reversible capability (with examples) must have a rollback whose args
    satisfy the inverse route — checked across all registries, plus the fs PoC."""
    import tempfile
    regs = dict(registries())
    try:
        from poc_connector_fs import fs_connector
        regs["fs-poc"] = fs_connector(Path(tempfile.mkdtemp()))
    except Exception:
        pass
    rows = []
    for reg_name, reg in regs.items():
        for cap in reg._caps.values():
            if cap.reversible and cap.examples:
                r = check_reversibility(reg, cap)
                rows.append({"reg": reg_name, "uri": cap.uri, "ok": r["ok"],
                             "checked": r.get("checked", 0),
                             "why": (r.get("failures") or [{}])[0].get("why") if not r["ok"] else ""})
    return rows


def audit() -> dict:
    report = {}
    for reg_name, reg in registries().items():
        rows = []
        for cap in reg._caps.values():
            n = len(cap.examples)
            res = check_examples(reg, cap) if n else {"passed": 0, "total": 0}
            rows.append({"uri": cap.uri, "examples": n,
                         "passed": res["passed"], "total": res["total"]})
        report[reg_name] = rows
    return report


def main() -> int:
    report = audit()
    print("== Audyt examples: konformans golden par (wejście→wyjście) na zdolność\n")
    weak = []
    for reg_name, rows in report.items():
        print(f"  {reg_name}")
        for r in rows:
            n, ok = r["total"], r["passed"]
            mark = "OK " if n and ok == n else ("—  " if n == 0 else "!! ")
            print(f"    {mark} {ok}/{n}  {r['uri']}")
            if n and ok < n:
                weak.append(r)
        print()
    if weak:
        print(f"  NIUANS: {len(weak)} zdolności z examples, które NIE konformują w pełni "
              "(prawdopodobnie stub odtwarzający tylko pierwszy przykład):")
        for r in weak:
            print(f"    - {r['uri']}  ({r['passed']}/{r['total']})")
    else:
        print("  Wszystkie examples konformują na tej samej zasadzie.")

    print("\n== Audyt odwracalności: inverse.args ⊨ INPUT trasy odwrotnej\n")
    rev = reversibility_audit()
    broken = [r for r in rev if not r["ok"]]
    for r in rev:
        print(f"    {'OK ' if r['ok'] else '!! '} {r['reg']:18} {r['uri']:46} "
              f"{'' if r['ok'] else r['why']}")
    print(f"\n  {'wszystkie odwracalne zdolności mają weryfikowalny rollback'if not broken else f'{len(broken)} bez weryfikowalnego rollbacku'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
