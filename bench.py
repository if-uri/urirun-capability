"""Validate the optimization at several levels: same task, two approaches.

Task: capture pc1's screen N times (the operator episode #5 action).

  A) baseline  — today's operator path: `urirun host run pc1 <uri>` per call
                 (a fresh CLI process + mesh round-trip each time).
  B) capability — the shrunk core: dispatch() via the http-node adapter
                 (persistent, typed, output validated, events by construction).

Reports L1 (per-step ms), L2 (task count / wall time / throughput) and
L3 (success rate, contract violations caught). Emits metric:// events to the
twin event bus so the report can render them.

    python bench.py [N] [node_url] [pc2_container]
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capability import Capability, Registry, Events, dispatch, metrics

N = int(sys.argv[1]) if len(sys.argv) > 1 else 8
NODE = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:28765"
PC2 = sys.argv[3] if len(sys.argv) > 3 else "pc2-pc2-1"
EVENTBUS = "http://127.0.0.1:28800"
URI = "kvm://host/screen/query/capture"


def emit(uri: str, **payload) -> None:
    body = json.dumps({"uri": uri, "actor": "bench", "payload": payload}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{EVENTBUS}/emit", data=body, headers={"Content-Type": "application/json"}), timeout=3).read()
    except Exception:
        pass


def bench_baseline() -> dict:
    ok = 0
    times = []
    for _ in range(N):
        t0 = time.time()
        cp = subprocess.run(
            ["docker", "exec", PC2, "bash", "-lc",
             f"/opt/urirun/bin/urirun host run pc1 '{URI}' --config /work/mesh.json --payload '{{}}'"],
            capture_output=True, text=True, timeout=60)
        dt = (time.time() - t0) * 1000
        times.append(dt)
        try:
            ok += 1 if json.loads(cp.stdout).get("ok") else 0
        except Exception:
            pass
    total = sum(times)
    return {"approach": "baseline (urirun host run, CLI/mesh per call)",
            "dispatches": N, "ok": ok, "failed": N - ok,
            "success_rate": round(ok / N, 3), "total_ms": round(total, 2),
            "avg_ms": round(total / N, 2), "min_ms": round(min(times), 2),
            "max_ms": round(max(times), 2),
            "throughput_per_s": round(ok / (total / 1000), 2) if total else 0.0,
            "output_validated": False, "contract_violations_caught": 0}


def bench_capability() -> dict:
    reg = Registry()
    reg.add(Capability(
        uri="kvm://pc1/screen/query/capture", effect="query",
        input={"type": "object", "properties": {"base64": {"type": "boolean"}}},
        output={"type": "object", "required": ["ok", "backend"],
                "properties": {"ok": {"type": "boolean"}, "backend": {"type": "string"}}},
        adapter="http-node", config={"node": NODE, "remoteUri": URI}))
    ev = Events()
    for _ in range(N):
        dispatch(reg, "kvm://pc1/screen/query/capture", {"base64": False}, events=ev)
    m = metrics(ev)
    m["approach"] = "capability (shrunk core, http-node, typed+validated)"
    m["output_validated"] = True
    return m


def main() -> int:
    if subprocess.run(["docker", "inspect", PC2], capture_output=True).returncode != 0:
        print("pc2 container not running — skip"); return 0
    print(f"Zadanie: {N}x  {URI}   (episode #5 — operator host→node)\n")
    a = bench_baseline()
    b = bench_capability()

    def row(m):
        return (f"  {m['approach']}\n"
                f"    czas łączny: {m['total_ms']:.0f} ms · śr/zadanie: {m['avg_ms']:.1f} ms "
                f"(min {m['min_ms']:.0f} / max {m['max_ms']:.0f})\n"
                f"    przepustowość: {m['throughput_per_s']} zadań/s · sukces: "
                f"{m['ok']}/{m['dispatches']} ({m['success_rate']*100:.0f}%)\n"
                f"    walidacja outputu: {'TAK' if m['output_validated'] else 'NIE'} · "
                f"złapane naruszenia kontraktu: {m['contract_violations_caught']}")

    print("[A]"); print(row(a)); print("\n[B]"); print(row(b))
    speedup = a["avg_ms"] / b["avg_ms"] if b["avg_ms"] else 0
    print(f"\n  → przyspieszenie na zadanie: ×{speedup:.1f}  "
          f"(śr {a['avg_ms']:.0f} ms → {b['avg_ms']:.0f} ms)")

    emit("metric://bench/task/query/summary", task=URI, n=N,
         baseline=a, capability=b, speedup_per_task=round(speedup, 2))
    Path(__file__).with_name("bench-result.json").write_text(
        json.dumps({"task": URI, "n": N, "baseline": a, "capability": b,
                    "speedup_per_task": round(speedup, 2)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
