"""Empirical test of the complementarity thesis: run a REAL LLM (local Ollama) on the
same 'anti-LLM' tasks the deterministic capabilities solve, and compare.

Measures, per task, over N runs of the SAME prompt:
  - LLM correctness (does its answer match the ground truth?)
  - LLM consistency (does it give the SAME answer every time?)
The deterministic capability is the ground truth: always correct, always identical.

    python llm_compare.py [model] [runs]     # default gemma4:e4b, 3 runs

Not a fast unit test — it hits a local model. The gated pytest lives in
tests/test_llm_compare.py (URIRUN_LLM_TEST=1).
"""
from __future__ import annotations

import json
import sys
import urllib.request

import re

from hard_tasks import (reconcile, field_completeness, instruction_conflicts)

OLLAMA = "http://127.0.0.1:11434/api/generate"

# ── the REAL anti-LLM shape: volume, buried dependencies, no stated rule ────────
# 15 invoice pairs across two systems with messy formats; exactly ONE mismatches.
_A = [{"nr": f"FV-{i}", "kwota_brutto": v} for i, v in enumerate(
    ["1 665,00 zł", "555,00", "1 234,50 zł", "99,99", "12 000,00 zł", "450,00",
     "1 665,00 zł", "780,20", "3 400,00 zł", "55,55", "9 999,99 zł", "120,00",
     "6 780,00 zł", "1 000,00 zł", "42,00"], 1)]
_B = [{"ref": f"FV-{i}", "suma": v} for i, v in enumerate(
    ["1665.00", "555.00", "1234.50", "99.99", "12000.00", "450.00",
     "1655.00",  # <-- the ONE hidden discrepancy (1665 vs 1655), buried at #7
     "780.20", "3400.00", "55.55", "9999.99", "120.00", "6780.00", "1000.00", "42.00"], 1)]

# 12 instructions with a single conflict buried in the middle (steps 3 and 9)
_DIRECTIVES = [{"set": "temat", "to": "Zamowienie"}, {"require": "faktura"},
               {"set": "odbiorca", "to": "szef@firma.pl"}, {"set": "priorytet", "to": "wysoki"},
               {"set": "waluta", "to": "PLN"}, {"require": "podpis"}, {"set": "jezyk", "to": "pl"},
               {"set": "kopia", "to": "archiwum"}, {"set": "odbiorca", "to": "nikt"},  # conflict w/ #3
               {"set": "format", "to": "pdf"}, {"set": "stopka", "to": "standard"},
               {"require": "numer"}]

# 4 scattered sources; 8 required fields; some are simply nowhere to be found
_SOURCES = [{"source": "email", "data": {"nr": "FV-1", "kwota": "1665"}},
            {"source": "zamowienie", "data": {"nr": "FV-1", "termin": "jutro", "ilosc": 3}},
            {"source": "crm", "data": {"klient": "Biuro", "email": "biuro@firma.pl"}},
            {"source": "magazyn", "data": {"produkt": "CyberMysz"}}]
_REQUIRED = ["nr", "kwota", "termin", "nip", "adres", "klient", "produkt", "regon"]


def _pairs_text(a, b):
    return "; ".join(f"{x['nr']}: A={x['kwota_brutto']} B={y['suma']}" for x, y in zip(a, b))


def _instr_text(ds):
    def one(d):
        if "set" in d: return f"ustaw {d['set']}={d['to']}"
        if "require" in d: return f"wymagaj {d['require']}"
        return str(d)
    return "; ".join(f"({i+1}) {one(d)}" for i, d in enumerate(ds))


# a LARGER reconciliation (50 invoices, 3 hidden discrepancies) — where volume starts
# to break an LLM's attention but not a deterministic pass
_BIGA, _BIGB = [], []
for i in range(1, 51):
    amt = f"{i * 111}"                                  # 111, 222, ... deterministic
    _BIGA.append({"nr": f"F{i}", "kwota_brutto": f"{amt},00 zł"})
    off = ",10" if i in (13, 37, 48) else ",00"        # 3 planted discrepancies
    _BIGB.append({"ref": f"F{i}", "suma": f"{amt}{off.replace(',', '.')}"})


TASKS = [
    {"id": "reconcile-50", "parse": "int",
     "prompt": "Masz 50 faktur w dwoch systemach. Policz, ile ma ROZNA kwote miedzy A i B. "
               "Odpowiedz TYLKO liczba.\n" + "; ".join(
                   f"{x['nr']}:A={x['kwota_brutto']},B={y['suma']}" for x, y in zip(_BIGA, _BIGB)),
     "truth": lambda: len(reconcile(_BIGA, _BIGB, {"key": ["nr", "ref"],
                                                   "amount": ["kwota_brutto", "suma"]})["discrepancies"])},
    {"id": "reconcile-15", "parse": "int",
     "prompt": "Masz 15 faktur w dwoch systemach (formaty kwot roznia sie zapisem). "
               "Policz, ile faktur ma ROZNA kwote miedzy systemem A i B. Odpowiedz TYLKO liczba.\n"
               + _pairs_text(_A, _B),
     "truth": lambda: len(reconcile(_A, _B, {"key": ["nr", "ref"],
                                             "amount": ["kwota_brutto", "suma"]})["discrepancies"])},
    {"id": "conflict-buried-12", "parse": "int",
     "prompt": "Oto 12 instrukcji. Policz, ile jest PAR wzajemnie sprzecznych (to samo pole "
               "ustawione na dwie rozne wartosci). Odpowiedz TYLKO liczba.\n" + _instr_text(_DIRECTIVES),
     "truth": lambda: instruction_conflicts(_DIRECTIVES)["count"]},
    {"id": "missing-fields-8", "parse": "int",
     "prompt": "Wymagane pola: " + ", ".join(_REQUIRED) + ". Dostepne zrodla i ich pola: "
               + "; ".join(f"{s['source']}: {', '.join(s['data'])}" for s in _SOURCES)
               + ". Policz, ile wymaganych pol BRAKUJE we wszystkich zrodlach. Odpowiedz TYLKO liczba.",
     "truth": lambda: len(field_completeness(_SOURCES, _REQUIRED)["missing"])},
]


def ask_llm(prompt: str, model: str) -> tuple[str, float]:
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "keep_alive": "5m", "options": {"temperature": 0.8}}).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=180))
    return d.get("response", ""), d.get("total_duration", 0) / 1e6   # ns -> ms


def parse(resp: str, mode: str):
    """Extract the LLM's committed answer; None if it never clearly commits."""
    if mode == "int":
        # take the LAST standalone integer (models often restate then conclude)
        nums = re.findall(r"-?\d+", resp.replace(",", "").replace(".", ""))
        return int(nums[-1]) if nums else None
    up = resp.upper()
    has_tak, has_nie = "TAK" in up, "NIE" in up
    return True if has_tak and not has_nie else False if has_nie and not has_tak else None


def run(model="gemma4:e4b", runs=3) -> dict:
    import time
    rows, llm_ms, det_us = [], [], []
    for t in TASKS:
        # deterministic ground truth + its latency (microseconds)
        t0 = time.perf_counter(); truth = t["truth"](); det_us.append((time.perf_counter() - t0) * 1e6)
        answers, durs = [], []
        for _ in range(runs):
            resp, ms = ask_llm(t["prompt"], model)
            answers.append(parse(resp, t["parse"])); durs.append(ms)
        llm_ms.extend(durs)
        correct = sum(1 for a in answers if a == truth)
        rows.append({"id": t["id"], "truth": truth, "answers": answers,
                     "llm_correct": f"{correct}/{runs}", "llm_consistent": len(set(answers)) == 1})
    avg_llm = sum(llm_ms) / len(llm_ms) if llm_ms else 0
    avg_det = sum(det_us) / len(det_us) if det_us else 0
    return {"model": model, "runs": runs, "rows": rows,
            "llm_all_correct": sum(all(a == r["truth"] for a in r["answers"]) for r in rows),
            "llm_all_consistent": sum(r["llm_consistent"] for r in rows), "tasks": len(rows),
            "llm_avg_ms": round(avg_llm, 1), "det_avg_us": round(avg_det, 1),
            "speedup": round((avg_llm * 1000) / avg_det) if avg_det else 0}


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else "gemma4:e4b"
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    print(f"== LLM ({model}, {runs}× każdy) vs deterministyczne zdolności\n")
    res = run(model, runs)
    print(f"  {'zadanie':<22} {'prawda':<7} {'LLM (odp.)':<20} {'popr.':<6} {'spójny':<7} determ.")
    print(f"  {'-'*22} {'-'*7} {'-'*20} {'-'*6} {'-'*7} {'-'*7}")
    for r in res["rows"]:
        ans = ",".join(str(a) if a is not None else "?" for a in r["answers"])
        print(f"  {r['id']:<22} {str(r['truth']):<7} {ans:<20} {r['llm_correct']:<6} "
              f"{'tak' if r['llm_consistent'] else 'NIE':<7} zawsze OK")
    print(f"\n  LLM ({model}): {res['llm_all_correct']}/{res['tasks']} w pełni poprawnych, "
          f"{res['llm_all_consistent']}/{res['tasks']} spójnych · śr. {res['llm_avg_ms']} ms/zadanie")
    print(f"  Deterministyczne: {res['tasks']}/{res['tasks']} poprawne i spójne (zawsze) · "
          f"śr. {res['det_avg_us']} µs/zadanie")
    print(f"\n  → nawet gdy LLM trafia, zdolność jest **~{res['speedup']}× szybsza**, "
          "zawsze spójna, audytowalna (wskazuje KTÓRA faktura / KTÓRE kroki) i dowiedziona testami.")
    _emit(res)
    return 0


def _emit(res):
    payload = {"model": res["model"], "runs": res["runs"], "tasks": res["tasks"],
               "llm_correct": res["llm_all_correct"], "llm_consistent": res["llm_all_consistent"],
               "deterministic_correct": res["tasks"], "deterministic_consistent": res["tasks"],
               "llm_avg_ms": res["llm_avg_ms"], "det_avg_us": res["det_avg_us"],
               "speedup": res["speedup"]}
    body = json.dumps({"uri": "metric://llm/compare/query/summary",
                       "actor": "llm-compare", "payload": payload}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:28800/emit", data=body,
            headers={"Content-Type": "application/json"}), timeout=3).read()
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
