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
from capability import check_examples, Registry
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
