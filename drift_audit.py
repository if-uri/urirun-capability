"""Real-connector drift audit: does each connector's manifest.json still match the
routes its CODE actually serves (@conn.handler / @handler decorators)? A mismatch is
the concrete cost of keeping the contract in two hand-maintained places.

    python drift_audit.py

Read-only; scans ~/github/if-uri/urirun-connector-*.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

GH = Path("/home/tom/github/if-uri")
_HANDLER = re.compile(r'@\w+\.handler\(\s*["\']([^"\']+)["\']')


def _tail(route: str) -> str:
    """The scheme/authority/router-independent part: the decorator's route is a SUFFIX
    of the manifest's full URI ('command/click' vs 'webnode://page/command/click'),
    because the object/authority is added by the sub-router and scheme."""
    return route.split("://", 1)[-1]


def code_routes(pkg: Path) -> set[str]:
    routes = set()
    for f in pkg.rglob("*.py"):
        if "__pycache__" in str(f) or "/venv/" in str(f) or "/test" in str(f):
            continue
        try:
            for m in _HANDLER.finditer(f.read_text(errors="ignore")):
                routes.add(_tail(m.group(1)))          # scheme-stripped, symmetric with manifest
        except Exception:
            pass
    return routes


def manifest_routes(pkg: Path) -> list[str] | None:
    mf = next((p for p in pkg.rglob("connector.manifest.json") if "/venv/" not in str(p)), None)
    if not mf:
        return None
    try:
        return [_tail(r) for r in json.loads(mf.read_text()).get("routes", [])]
    except Exception:
        return []


def audit() -> list[dict]:
    rows = []
    for pkg in sorted(GH.glob("urirun-connector-*")):
        code = code_routes(pkg)
        man = manifest_routes(pkg)
        if man is None or not code:
            continue                                   # no manifest or no decorator-based handlers
        # a manifest route is COVERED if some code decorator route is its suffix
        only_man = sorted(m for m in man if not any(m == c or m.endswith("/" + c) for c in code))
        covered_by = {m for m in man for c in code if m == c or m.endswith("/" + c)}
        only_code = sorted(c for c in code
                           if not any(m == c or m.endswith("/" + c) for m in covered_by))
        rows.append({"pkg": pkg.name.replace("urirun-connector-", ""),
                     "code": len(code), "manifest": len(man),
                     "in_sync": not only_code and not only_man,
                     "only_code": only_code, "only_manifest": only_man})
    return rows


def main() -> int:
    rows = audit()
    drifted = [r for r in rows if not r["in_sync"]]
    print(f"== Audyt rozjazdu kod↔manifest: {len(rows)} connectorów z manifestem i handlerami\n")
    print(f"  {'connector':<20} {'kod':>4} {'manifest':>9} {'zsync':>6}  rozjazd")
    print(f"  {'-'*20} {'-'*4} {'-'*9} {'-'*6}  {'-'*30}")
    for r in sorted(rows, key=lambda x: x["in_sync"]):
        d = ""
        if not r["in_sync"]:
            bits = []
            if r["only_code"]:
                bits.append(f"kod-only: {', '.join(r['only_code'][:3])}" + ("…" if len(r['only_code']) > 3 else ""))
            if r["only_manifest"]:
                bits.append(f"manifest-only: {', '.join(r['only_manifest'][:3])}" + ("…" if len(r['only_manifest']) > 3 else ""))
            d = " | ".join(bits)
        print(f"  {r['pkg']:<20} {r['code']:>4} {r['manifest']:>9} {'tak' if r['in_sync'] else 'NIE':>6}  {d}")
    print(f"\n  → {len(drifted)}/{len(rows)} connectorów ma realny rozjazd; pozostałe trzymają się "
          "zgodnie — ale WYŁĄCZNIE ręczną dyscypliną, w dwóch osobnych reprezentacjach.")
    print("  → Uwaga: sam ten audyt wymagał normalizacji tras (dekorator goły + prefiks sub-routera "
          "vs pełne URI w manifeście, różna głębokość authority) — niespójność reprezentacji jest tak "
          "duża, że jej wykrycie jest trudne. Generowanie manifestu z JEDNEGO deskryptora usuwa całą "
          "tę klasę problemu: rozjazd staje się strukturalnie niemożliwy, a forma — jedna.")
    _emit(len(rows), len(drifted))
    return 0


def _emit(total, drifted):
    body = json.dumps({"uri": "metric://architecture/drift/query/summary", "actor": "drift-audit",
                       "payload": {"connectors_audited": total, "drifted": drifted,
                                   "in_sync": total - drifted}}).encode()
    try:
        import urllib.request
        urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:28800/emit", data=body,
            headers={"Content-Type": "application/json"}), timeout=3).read()
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
