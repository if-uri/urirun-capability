"""Scale sweep: where does the LLM start to drift? Fix the number of discrepancies
(3) and grow the invoice list; measure LLM correctness + consistency vs N. The
deterministic capability is correct at every N — this maps the boundary.

    python llm_scale_sweep.py [model] [runs]     # default gemma4:e4b, 3

Slow (hits Ollama, longer prompts at bigger N). Gated pytest in tests/.
"""
from __future__ import annotations

import json
import sys
import urllib.request

from hard_tasks import reconcile
from llm_compare import ask_llm, parse

SIZES = [10, 25, 50, 75]
D = 3                                       # exactly 3 planted discrepancies at every size


def make_pairs(n: int, d: int = D):
    """n invoice pairs; exactly d have a mismatched amount, at spread-out positions."""
    positions = sorted({max(1, int(n * f)) for f in (0.2, 0.55, 0.85)})[:d]
    a, b = [], []
    for i in range(1, n + 1):
        amt = i * 111                       # deterministic amounts
        a.append({"nr": f"F{i}", "kwota_brutto": f"{amt},00 zł"})
        off = ".10" if i in positions else ".00"
        b.append({"ref": f"F{i}", "suma": f"{amt}{off}"})
    return a, b, len(positions)


def sweep(model="gemma4:e4b", runs=3) -> dict:
    rows = []
    for n in SIZES:
        a, b, planted = make_pairs(n)
        truth = len(reconcile(a, b, {"key": ["nr", "ref"], "amount": ["kwota_brutto", "suma"]})["discrepancies"])
        assert truth == planted, (n, truth, planted)          # deterministic reference
        prompt = (f"Masz {n} faktur w dwoch systemach (formaty kwot roznia sie zapisem). "
                  "Policz, ile faktur ma ROZNA kwote miedzy systemem A i B. Odpowiedz TYLKO liczba.\n"
                  + "; ".join(f"{x['nr']}:A={x['kwota_brutto']},B={y['suma']}" for x, y in zip(a, b)))
        answers = [parse(ask_llm(prompt, model)[0], "int") for _ in range(runs)]
        correct = sum(1 for x in answers if x == truth)
        rows.append({"n": n, "truth": truth, "answers": answers,
                     "correct": correct, "runs": runs, "consistent": len(set(answers)) == 1})
    return {"model": model, "runs": runs, "sizes": SIZES, "rows": rows}


def _emit(res):
    body = json.dumps({"uri": "metric://llm/scale/query/summary", "actor": "llm-scale",
                       "payload": {"model": res["model"], "runs": res["runs"],
                                   "curve": [{"n": r["n"], "correct": r["correct"], "runs": r["runs"],
                                              "consistent": r["consistent"], "answers": r["answers"]}
                                             for r in res["rows"]]}}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:28800/emit", data=body,
            headers={"Content-Type": "application/json"}), timeout=3).read()
    except Exception:
        pass


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else "gemma4:e4b"
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    print(f"== Sweep skali: LLM ({model}) vs deterministyczne, {D} rozbieżności przy każdym N\n")
    res = sweep(model, runs)
    print(f"  {'N faktur':<10} {'prawda':<7} {'LLM odpowiedzi':<20} {'popr.':<7} {'spójny':<7} determ.")
    print(f"  {'-'*10} {'-'*7} {'-'*20} {'-'*7} {'-'*7} {'-'*7}")
    for r in res["rows"]:
        ans = ",".join(str(a) if a is not None else "?" for a in r["answers"])
        bar = "█" * r["correct"] + "░" * (r["runs"] - r["correct"])
        print(f"  {r['n']:<10} {r['truth']:<7} {ans:<20} {r['correct']}/{r['runs']} {bar}  "
              f"{'tak' if r['consistent'] else 'NIE':<7} zawsze OK")
    breaks = next((r["n"] for r in res["rows"] if r["correct"] < r["runs"] or not r["consistent"]), None)
    _emit(res)
    if breaks:
        print(f"\n  → LLM zaczyna dryfować przy N≈{breaks}; zdolność deterministyczna: "
              f"{len(SIZES)}/{len(SIZES)} rozmiarów zawsze poprawna i spójna.")
    else:
        print(f"\n  → w tym zakresie ({SIZES[0]}–{SIZES[-1]}) LLM nie dryfnął; warto rozszerzyć N.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
