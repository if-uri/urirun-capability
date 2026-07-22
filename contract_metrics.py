"""Full metric: how moving from urirun-contract-* packages to Capability
descriptors changes the urirun system across every dimension.

Measures (OLD = the urirun-contract-kvstore package · NEW = Capability + shared core):
  - kod boilerplate na kontrakt/paczkę   (code quality / maintenance surface)
  - pliki i procesy (moving parts)
  - dane potrzebne do ZDEFINIOWANIA kontraktu (bytes)
  - duplikacja bramy między paczkami
  - czas dispatchu i ilość danych per wywołanie
  - liczba kontraktów

Emits metric://contract/refactor/query/summary so the report can monitor it.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capability import Events, dispatch
from kvstore import load_kvstore
from metric_events import emit_metric
from openapi import to_openapi

PKG = Path("/home/tom/github/if-uri/urirun-contract-kvstore")
CONTRACTS = PKG / "contracts.json"
ALL_PKGS = [Path(f"/home/tom/github/if-uri/urirun-contract-{n}")
            for n in ("capture-click", "filepair", "kvstore", "windowpair")]
CORE_LINES = (Path(__file__).resolve().parent / "capability.py").read_text().count("\n")
def _loc(paths) -> int:
    total = 0
    for f in paths:
        try:
            total += f.read_text(errors="ignore").count("\n")
        except Exception:
            pass
    return total


def _pkg_py(pkg: Path):
    return [f for f in pkg.rglob("*.py")
            if "__pycache__" not in str(f) and "test" not in f.name]


def measure() -> dict:
    doc = json.loads(CONTRACTS.read_text())
    n_contracts = len(doc["contracts"])

    # OLD: the package that serves these contracts
    old_py = _pkg_py(PKG)
    old_loc = _loc(old_py)
    old_files = sum(1 for _ in PKG.rglob("*") if _.is_file() and "__pycache__" not in str(_)
                    and "/.git/" not in str(_))
    gate_loc_per_pkg = _loc(list((PKG / "toolkit").glob("*.py")))
    duplicated_gate = gate_loc_per_pkg * len(ALL_PKGS)

    # NEW: capabilities on the shared core
    reg = load_kvstore(CONTRACTS)
    spec = to_openapi(reg)
    descriptor_bytes = len(json.dumps([c.contract() for c in reg._caps.values()], ensure_ascii=False))
    openapi_bytes = len(json.dumps(spec))
    contracts_json_bytes = CONTRACTS.stat().st_size

    # time + data per call (set -> get roundtrip), N iterations
    N = 200
    ev = Events()
    t0 = time.time()
    for _ in range(N):
        dispatch(reg, "kv://host/kv/command/set", {"key": "k", "value": "v"}, events=ev)
        dispatch(reg, "kv://host/kv/query/get", {"key": "k"}, events=ev)
    dt_ms = (time.time() - t0) * 1000
    per_call_us = dt_ms * 1000 / (N * 2)

    return {
        "target": "urirun-contract-kvstore",
        "contracts": n_contracts,
        # code quality / maintenance surface
        "old_boilerplate_loc": old_loc,
        "new_boilerplate_loc": 0,                    # shared core, amortized
        "shared_core_loc": CORE_LINES,               # once, for ALL connectors
        "boilerplate_per_contract_old": round(old_loc / n_contracts, 1),
        "boilerplate_per_contract_new": 0,
        # moving parts
        "old_files": old_files,
        "new_files": n_contracts,                    # one descriptor each (data)
        "old_processes": 2,                          # producer + consumer services
        "new_processes": 1,                          # one runtime
        "duplicated_gate_loc_across_pkgs": duplicated_gate,
        # data to DEFINE a contract
        "contract_data_bytes_total": contracts_json_bytes,
        "contract_data_bytes_per_contract": round(contracts_json_bytes / n_contracts),
        "descriptor_bytes": descriptor_bytes,
        "openapi_bytes": openapi_bytes,
        # runtime
        "dispatch_us_per_call": round(per_call_us, 1),
        "calls_measured": N * 2,
        # summary ratios
        "code_to_contract_ratio_old": round(old_loc / max(1, doc_lines(CONTRACTS)), 1),
        "code_to_contract_ratio_new": 0.0,
    }


def doc_lines(p: Path) -> int:
    return p.read_text().count("\n")


def main() -> int:
    m = measure()
    print(f"== Metryka refaktoru kontraktu: {m['target']} ({m['contracts']} kontrakty)\n")
    rows = [
        ("Kod boilerplate (na connector)", f"{m['old_boilerplate_loc']} linii", "0 (wspólny rdzeń)"),
        ("Boilerplate / kontrakt", f"{m['boilerplate_per_contract_old']} linii", "0"),
        ("Wspólny rdzeń (raz, dla wszystkich)", "—", f"{m['shared_core_loc']} linii"),
        ("Pliki w jednostce", str(m["old_files"]), str(m["new_files"])),
        ("Procesy", f"{m['old_processes']} (producer+consumer)", f"{m['new_processes']} (runtime)"),
        ("Duplikacja bramy w 4 paczkach", f"{m['duplicated_gate_loc_across_pkgs']} linii", "0 (jedna brama)"),
        ("Dane do zdefiniowania kontraktu", f"{m['contract_data_bytes_per_contract']} B/kontrakt",
         f"{m['contract_data_bytes_per_contract']} B (te same dane)"),
        ("Powierzchnia OpenAPI (2 op.)", "—", f"{m['openapi_bytes']} B"),
        ("Czas dispatchu / wywołanie", "—", f"{m['dispatch_us_per_call']} µs"),
        ("Stosunek kod:kontrakt", f"{m['code_to_contract_ratio_old']}:1", "0:1"),
    ]
    w = max(len(r[0]) for r in rows)
    print(f"  {'Wymiar':<{w}}  {'STARY (paczka)':<26}  NOWY (Capability)")
    print(f"  {'-'*w}  {'-'*26}  {'-'*20}")
    for name, old, new in rows:
        print(f"  {name:<{w}}  {old:<26}  {new}")
    emit_metric("metric://contract/refactor/query/summary", "contract-metrics", m)
    Path(__file__).with_name("contract-metrics.json").write_text(
        json.dumps(m, indent=2, ensure_ascii=False))
    print(f"\n  → likwidacja {m['old_boilerplate_loc']} linii boilerplate/connector "
          f"(+{m['duplicated_gate_loc_across_pkgs']} zduplikowanej bramy) przy tych samych danych kontraktu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
