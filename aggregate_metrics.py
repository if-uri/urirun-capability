"""Aggregate the refactor metric across ALL urirun-contract-* packages.

Shows the total system impact of moving every contract package to Capability
descriptors on the shared core. Emits metric://contract/refactor/aggregate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contracts_adopt import adopt_contracts
from openapi import to_openapi
from capability import Events, dispatch, check_examples
from metric_events import emit_metric

GH = Path("/home/tom/github/if-uri")
PKGS = ["capture-click", "filepair", "kvstore", "windowpair"]
SCHEMES = {"capture-click": "kvm", "filepair": "fs", "kvstore": "kv", "windowpair": "kvm"}
CORE_LINES = (Path(__file__).resolve().parent / "capability.py").read_text().count("\n")
# vendored / generated dirs that are not the package's own source
_EXCLUDE = ("__pycache__", "/.git/", "/venv/", "/.venv/", "/node_modules/",
            "/site-packages/", "/dist/", "/build/", "/_site/", "/cache/", "/.pytest_cache/")


def _own_source(f) -> bool:
    s = str(f)
    return not any(x in s for x in _EXCLUDE)


def pkg_stats(name: str) -> dict:
    pkg = GH / f"urirun-contract-{name}"
    if not pkg.exists():
        return {}
    py = [f for f in pkg.rglob("*.py") if _own_source(f) and "test" not in f.name]
    loc = sum(f.read_text(errors="ignore").count("\n") for f in py)
    files = sum(1 for f in pkg.rglob("*") if f.is_file() and _own_source(f))
    gate = sum(f.read_text(errors="ignore").count("\n") for f in (pkg / "toolkit").glob("*.py"))
    cj = pkg / "contracts.json"
    doc = json.loads(cj.read_text())
    reg = adopt_contracts(cj, SCHEMES.get(name, "x"))
    total_examples = sum(len(c.examples) for c in reg._caps.values())
    return {"pkg": name, "contracts": len(doc["contracts"]),
            "old_loc": loc, "old_files": files, "gate_loc": gate,
            "contract_bytes": cj.stat().st_size,
            "openapi_bytes": len(json.dumps(to_openapi(reg))),
            "examples": total_examples}


def main() -> int:
    stats = [s for s in (pkg_stats(p) for p in PKGS) if s]
    if not stats:
        print("brak paczek urirun-contract-*"); return 0

    tot_contracts = sum(s["contracts"] for s in stats)
    tot_old_loc = sum(s["old_loc"] for s in stats)
    tot_old_files = sum(s["old_files"] for s in stats)
    tot_gate = sum(s["gate_loc"] for s in stats)
    tot_bytes = sum(s["contract_bytes"] for s in stats)

    print(f"== Metryka zbiorcza: {len(stats)} paczek urirun-contract-*, "
          f"{tot_contracts} kontraktów\n")
    print(f"  {'paczka':<16} {'kontr.':>6} {'kod(old)':>9} {'plików':>7} "
          f"{'brama':>6} {'dane(B)':>8} {'przykł.':>8}")
    for s in stats:
        print(f"  {s['pkg']:<16} {s['contracts']:>6} {s['old_loc']:>9} {s['old_files']:>7} "
              f"{s['gate_loc']:>6} {s['contract_bytes']:>8} {s['examples']:>8}")
    print(f"  {'-'*16} {'-'*6} {'-'*9} {'-'*7} {'-'*6} {'-'*8} {'-'*8}")
    print(f"  {'RAZEM (STARY)':<16} {tot_contracts:>6} {tot_old_loc:>9} {tot_old_files:>7} "
          f"{tot_gate:>6} {tot_bytes:>8}")
    print(f"  {'NOWY (Capability)':<16} {tot_contracts:>6} {'0':>9} {tot_contracts:>7} "
          f"{'0':>6} {tot_bytes:>8}  (+ rdzeń {CORE_LINES} lin. raz)")

    summary = {
        "packages": len(stats), "contracts": tot_contracts,
        "old_total_loc": tot_old_loc, "new_total_loc": 0, "shared_core_loc": CORE_LINES,
        "old_total_files": tot_old_files, "new_total_files": tot_contracts,
        "duplicated_gate_loc": tot_gate, "contract_data_bytes": tot_bytes,
        "per_pkg": stats,
    }
    emit_metric(
        "metric://contract/refactor/aggregate/query/summary",
        "aggregate-metrics",
        summary,
    )
    Path(__file__).with_name("aggregate-metrics.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False))
    saved = tot_old_loc - CORE_LINES
    print(f"\n  → cały zestaw: {tot_old_loc} linii kodu w {tot_old_files} plikach → "
          f"{CORE_LINES} linii wspólnego rdzenia (oszczędność {saved} linii), "
          f"przy {tot_bytes} B niezmienionych danych kontraktu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
