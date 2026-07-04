"""The office tasks LLMs are worst at — done DETERMINISTICALLY as typed capabilities.

These are the "anti-LLM" tasks (data reconciliation across systems that name the
same thing differently, cross-document consistency, context-dependent rules,
root-cause from ambiguous symptoms). LLMs fail them for lack of exact reconciliation
and verification-of-sense; typed capabilities do them deterministically, and the
`examples` catch regressions. No LLM anywhere.

Each capability: typed input/output, a pure handler, and golden examples.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from capability import Capability, Registry


# ── helpers ────────────────────────────────────────────────────────────────────
def money(s) -> Decimal:
    """Normalise messy money strings from different systems: '1 665,00 zł',
    '1665.00', '1,665.00', 1665 -> Decimal('1665.00'). The reconciliation LLMs
    keep getting wrong (comma vs dot, thousands sep, currency, spaces)."""
    if isinstance(s, (int, float, Decimal)):
        return Decimal(str(s)).quantize(Decimal("0.01"))
    t = re.sub(r"[^\d,.\-]", "", str(s))          # drop currency/spaces/letters
    if "," in t and "." in t:                      # 1,665.00 or 1.665,00
        if t.rfind(",") > t.rfind("."):            # comma is the decimal sep
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:                                 # 1665,00 -> 1665.00
        t = t.replace(",", ".")
    try:
        return Decimal(t).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")


# ── 1) reconcile two systems that name the same fields differently ─────────────
def reconcile(left, right, mapping):
    """mapping = {"key": (leftField, rightField), "amount": (lf, rf)}. Match rows by
    the key field (named differently on each side), compare normalised amounts."""
    lk, rk = mapping["key"]
    la, ra = mapping["amount"]
    right_by_key = {str(r[rk]): r for r in right}
    matched, discrepancies, only_left = [], [], []
    for l in left:
        rid = str(l[lk])
        r = right_by_key.pop(rid, None)
        if r is None:
            only_left.append(rid); continue
        if money(l[la]) == money(r[ra]):
            matched.append(rid)
        else:
            discrepancies.append({"key": rid, "left": str(money(l[la])),
                                  "right": str(money(r[ra]))})
    only_right = list(right_by_key)
    return {"matched": matched, "discrepancies": discrepancies,
            "only_left": only_left, "only_right": only_right,
            "reconciled": not discrepancies and not only_left and not only_right}


# ── 2) cross-document consistency: an amount must agree across N documents ──────
def cross_consistency(docs, field="kwota"):
    """docs = [{"doc": "zamowienie", "kwota": ...}, ...]. Do all documents agree on
    the amount? Verification-of-SENSE (values equal), not format."""
    vals = {d["doc"]: money(d[field]) for d in docs}
    uniq = set(vals.values())
    return {"consistent": len(uniq) == 1, "values": {k: str(v) for k, v in vals.items()},
            "distinct": len(uniq),
            "outliers": [d for d, v in vals.items() if list(vals.values()).count(v) == 1]
                        if len(uniq) > 1 else []}


# ── 2b) intra-document consistency: do the numbers inside a doc add up? ─────────
def invoice_consistency(lines, stated_brutto, vat_rate="23"):
    """Verify the document makes SENSE, not just that it's formatted: line items must
    sum to the stated gross, and (if netto given) netto*(1+vat) must equal brutto.
    Catches a tampered/typo'd total an LLM tends to accept at face value."""
    computed = sum((money(l.get("cena_brutto", 0)) * int(l.get("ilosc", 1)) for l in lines),
                   Decimal("0.00"))
    stated = money(stated_brutto)
    lines_ok = computed == stated
    rate = Decimal(str(vat_rate)) / 100
    vat_ok = True
    for l in lines:
        if "cena_netto" in l:
            expected = (money(l["cena_netto"]) * (1 + rate)).quantize(Decimal("0.01"))
            vat_ok = vat_ok and expected == money(l.get("cena_brutto", 0))
    return {"consistent": lines_ok and vat_ok, "computed_sum": str(computed),
            "stated": str(stated), "lines_sum_ok": lines_ok, "vat_ok": vat_ok,
            "delta": str(stated - computed)}


# ── 3) context-dependent rules: refund eligibility by plan/days/reason ─────────
_REFUND_WINDOW = {"PRO": 30, "BASIC": 14, "PrePaid": 0}   # rules depend on the plan


def refund_eligible(plan, days_since_purchase, used_actions, reason=""):
    """Refund rules that DEPEND ON CONTEXT (plan-specific window, usage cap, reason).
    Returns the decision AND the rule that fired — auditable, unlike an LLM guess."""
    window = _REFUND_WINDOW.get(plan)
    if window is None:
        return {"eligible": False, "rule": "unknown-plan", "plan": plan}
    if window == 0:
        return {"eligible": False, "rule": "prepaid-non-refundable", "plan": plan}
    if int(days_since_purchase) > window:
        return {"eligible": False, "rule": f"past-{window}d-window", "plan": plan,
                "days": int(days_since_purchase)}
    if int(used_actions) > 100:                     # used the service materially
        return {"eligible": False, "rule": "over-usage-cap", "used": int(used_actions)}
    return {"eligible": True, "rule": f"within-{window}d-and-under-usage", "plan": plan}


# ── 5) missing info scattered across sources + provenance (#10) ────────────────
def field_completeness(sources, required):
    """Which required fields are present across scattered sources, WHERE each came
    from, and which are MISSING — the completeness check LLMs fake ('looks complete')."""
    provenance, present = {}, set()
    for s in sources:
        for k, v in (s.get("data") or {}).items():
            if v not in (None, "", []):
                present.add(k)
                provenance.setdefault(k, []).append(s.get("source", "?"))
    missing = [k for k in required if k not in present]
    return {"complete": not missing, "missing": missing,
            "provenance": {k: provenance[k] for k in required if k in provenance},
            "present": sorted(present & set(required))}


# ── 6) conflicts in multi-step instructions (#14 — LLMs silently skip these) ────
def instruction_conflicts(directives):
    """Detect contradictions in a structured instruction set: the same field set to
    two different values, or a require+forbid on the same thing. An LLM reading a long
    list merges or skips these; a typed checker names each conflict with its steps."""
    conflicts = []
    sets: dict[str, list] = {}
    requires, forbids = {}, {}
    for i, d in enumerate(directives):
        if "set" in d:
            sets.setdefault(d["set"], []).append((i, d.get("to")))
        if "require" in d:
            requires[d["require"]] = i
        if "forbid" in d:
            forbids[d["forbid"]] = i
    for key, vals in sets.items():
        distinct = {v for _, v in vals}
        if len(distinct) > 1:
            conflicts.append({"type": "value-conflict", "field": key,
                              "values": sorted(str(v) for v in distinct),
                              "steps": [i for i, _ in vals]})
    for thing in set(requires) & set(forbids):
        conflicts.append({"type": "require-forbid", "field": thing,
                          "steps": sorted([requires[thing], forbids[thing]])})
    return {"consistent": not conflicts, "conflicts": conflicts,
            "count": len(conflicts)}


# ── 4) root-cause from ambiguous symptoms (a set of error:// codes) ────────────
# symptoms co-occur; the ROOT explains the most of them and comes first causally.
_CAUSES = [
    ("ca-not-trusted", {"cert-invalid", "ssl-verify-failed", "connection-refused-https"},
     "Lokalny CA nie zaufany w kliencie — zainstaluj root CA (setup-ca)."),
    ("node-down", {"connection-refused", "health-timeout", "dispatch-failed"},
     "Node pc1 nie odpowiada — sprawdź kontener i /health."),
    ("dns-unresolved", {"name-not-resolved", "connection-refused", "host-unknown"},
     "Nazwa nie rozwiązuje się w netpl — sprawdź alias DNS."),
]


def root_cause(symptoms):
    """Given ambiguous, overlapping symptoms, pick the root cause that explains the
    MOST of them (deterministic scoring), not a plausible-sounding guess."""
    s = set(symptoms)
    ranked = sorted(_CAUSES, key=lambda c: len(s & c[1]), reverse=True)
    top, cover = ranked[0], s & ranked[0][1]
    if not cover:
        return {"root": "unknown", "explained": [], "confidence": 0.0, "fix": ""}
    return {"root": top[0], "explained": sorted(cover), "fix": top[2],
            "confidence": round(len(cover) / len(s), 2),
            "unexplained": sorted(s - top[1])}


# ── registry: each as a typed, content-addressed capability with examples ──────
def hard_registry() -> Registry:
    reg = Registry()
    reg.add(Capability(
        uri="recon://ksiegowosc/faktury/query/reconcile", effect="query",
        input={"type": "object", "required": ["left", "right", "mapping"]},
        output={"type": "object", "required": ["reconciled"]},
        examples=({"input": {"left": [{"nr": "FV-1", "kwota_brutto": "1 665,00 zł"}],
                             "right": [{"ref": "FV-1", "suma": "1665.00"}],
                             "mapping": {"key": ["nr", "ref"], "amount": ["kwota_brutto", "suma"]}},
                   "output": {"reconciled": True, "matched": ["FV-1"], "discrepancies": [],
                              "only_left": [], "only_right": []}},),
        adapter="python",
        config={"keywords": "uzgodnij uzgadnianie rekonsyliacja faktury faktur przelewy ksiegowosc zgadza",
                "fn": lambda left, right, mapping: reconcile(left, right, mapping)}))
    reg.add(Capability(
        uri="audit://zamowienie/query/consistency", effect="query",
        input={"type": "object", "required": ["docs"]},
        output={"type": "object", "required": ["consistent"]},
        examples=({"input": {"docs": [{"doc": "zamowienie", "kwota": "1665,00"},
                                      {"doc": "faktura", "kwota": "1665.00"},
                                      {"doc": "przelew", "kwota": "1 665,00 zł"}]},
                   "output": {"consistent": True, "distinct": 1,
                              "values": {"zamowienie": "1665.00", "faktura": "1665.00",
                                         "przelew": "1665.00"}, "outliers": []}},),
        adapter="python",
        config={"keywords": "spojnosc spójność porownaj porównaj dokumenty zamowienie faktura przelew kwota zgodne",
                "fn": lambda docs, field="kwota": cross_consistency(docs, field)}))
    reg.add(Capability(
        uri="audit://faktura/query/consistency", effect="query",
        input={"type": "object", "required": ["lines", "stated_brutto"]},
        output={"type": "object", "required": ["consistent"]},
        examples=({"input": {"lines": [{"nazwa": "CyberMysz", "ilosc": 3, "cena_brutto": "555,00"}],
                             "stated_brutto": "1 665,00 zł"},
                   "output": {"consistent": True, "computed_sum": "1665.00",
                              "stated": "1665.00", "lines_sum_ok": True, "delta": "0.00"}},),
        adapter="python",
        config={"keywords": "faktura pozycje sumuja suma brutto vat wewnetrzna arytmetyka poprawna",
                "fn": lambda lines, stated_brutto, vat_rate="23":
                invoice_consistency(lines, stated_brutto, vat_rate)}))
    reg.add(Capability(
        uri="rules://zwrot/query/eligible", effect="query",
        input={"type": "object", "required": ["plan", "days_since_purchase", "used_actions"]},
        output={"type": "object", "required": ["eligible", "rule"]},
        examples=({"input": {"plan": "BASIC", "days_since_purchase": 5, "used_actions": 10},
                   "output": {"eligible": True, "rule": "within-14d-and-under-usage",
                              "plan": "BASIC"}},),
        adapter="python",
        config={"keywords": "zwrot zwrotu reklamacja refund zwrocic nalezny nalezy pieniadze",
                "fn": lambda plan, days_since_purchase, used_actions, reason="":
                refund_eligible(plan, days_since_purchase, used_actions, reason)}))
    reg.add(Capability(
        uri="diag://system/query/rootcause", effect="query",
        input={"type": "object", "required": ["symptoms"]},
        output={"type": "object", "required": ["root"]},
        examples=({"input": {"symptoms": ["cert-invalid", "ssl-verify-failed"]},
                   "output": {"root": "ca-not-trusted",
                              "explained": ["cert-invalid", "ssl-verify-failed"],
                              "fix": "Lokalny CA nie zaufany w kliencie — zainstaluj root CA (setup-ca).",
                              "confidence": 1.0, "unexplained": []}},),
        adapter="python",
        config={"keywords": "przyczyna awaria awarii diagnoza problem blad błąd rootcause znajdz",
                "fn": lambda symptoms: root_cause(symptoms)}))
    reg.add(Capability(
        uri="audit://dane/query/completeness", effect="query",
        input={"type": "object", "required": ["sources", "required"]},
        output={"type": "object", "required": ["complete"]},
        examples=({"input": {"sources": [{"source": "email", "data": {"nr": "FV-1", "kwota": "1665"}}],
                             "required": ["nr", "kwota", "nip"]},
                   "output": {"complete": False, "missing": ["nip"],
                              "provenance": {"nr": ["email"], "kwota": ["email"]},
                              "present": ["kwota", "nr"]}},),
        adapter="python",
        config={"keywords": "brakujace brakuje kompletnosc dane rozproszone zebrac uzupelnic czego brakuje",
                "fn": lambda sources, required: field_completeness(sources, required)}))
    reg.add(Capability(
        uri="audit://instrukcje/query/conflicts", effect="query",
        input={"type": "object", "required": ["directives"]},
        output={"type": "object", "required": ["consistent"]},
        examples=({"input": {"directives": [{"set": "odbiorca", "to": "szef"},
                                            {"set": "odbiorca", "to": "ksiegowa"}]},
                   "output": {"consistent": False, "count": 1,
                              "conflicts": [{"type": "value-conflict", "field": "odbiorca",
                                             "values": ["ksiegowa", "szef"], "steps": [0, 1]}]}},),
        adapter="python",
        config={"keywords": "instrukcje sprzeczne sprzecznosc konflikt polecenia kroki niespojne wykryj",
                "fn": lambda directives: instruction_conflicts(directives)}))
    return reg
