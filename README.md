# urirun-capability — a shrunk, invariant core for URI processes (prototype)

A ~280-line prototype that tests one thesis: the URI-process model is a great
idea carried by too much accidental complexity. Collapse the *binding + contract*
split into **one typed descriptor** and make four things invariant that today's
urirun leaves optional — and the process model fits in a few hundred lines while
being **more** robust, portable and observable.

## Cztery niezmienniki (których dziś brakuje)

1. **URI to stabilna nazwa, nie nośnik logiki.** Efekt to typowane pole
   (`effect: query|command`), nie string parsowany z `/query/` vs `/command/`.
   Bramka bezpieczeństwa czyta pole → deterministyczna.
2. **Tożsamość content-addressed.** `capability_id = hash(kontrakt)`. Rejestr
   ma *lockfile*; dryf jest wykrywany, nigdy cichy (to zabija fragilność
   zbundlowanych/przestarzałych zależności, na którą realnie wpadałem).
3. **Każdy dispatch emituje zdarzenia URI z definicji** (`run://` `error://`
   `log://`). Obserwowalność — a więc replay / cyfrowy bliźniak — za darmo dla
   dowolnego systemu.
4. **Output walidowany przeciw kontraktowi.** Dryf backendu jest łapany, nie
   ufany na słowo (dzisiejsze v2 bindingi zwykle nie mają `outputSchema`).

## Co to daje (udowodnione testami)

| Test | Dowód |
| --- | --- |
| `test_dispatch_emits_events_by_construction` | zdarzenia `run://` bez opt-in |
| `test_effect_is_typed_not_parsed_from_url` | bramka z pola, nie ze stringa |
| `test_output_contract_violation_is_caught` | zły kształt wyniku → `CONTRACT_VIOLATION` |
| `test_content_addressed_identity_and_drift` | lockfile wykrywa zmianę kontraktu |
| `test_examples_are_conformance_tests` | `examples` = testy + few-shot + planner |
| `test_whole_core_is_small` | rdzeń < 350 linii (dziś ~26k) |
| `tests/test_live_node.py` | **nowy rdzeń steruje żywym node'em pc1** i waliduje jego output |
| `tests/test_hard_tasks.py` | zadania „anty-LLM" (rekonsyliacja, spójność, reguły, diagnoza) deterministycznie |
| `tests/test_audit_examples.py` | niezmiennik: **wszystkie** `examples` konformują na jednej zasadzie |
| `tests/test_saga.py` | transakcja all-or-nothing z kompensacją przez `inverse` |

**Komplementarność LLM ↔ zdolności** (dlaczego to najsilniejsze tam, gdzie LLM
najsłabszy) i **jedna zasada `examples`** opisane w
[`docs/complementarity.md`](docs/complementarity.md) — z empirią (LLM dryfuje przy
skali N≈75), wzorcem hybrydowym i sweepem granicy.

**Uproszczenie architektury** (38 connectorów, kontrakt w 2–3 miejscach → jeden
deskryptor, reszta generowana) w
[`docs/architecture-simplification.md`](docs/architecture-simplification.md);
`projections.py` demonstruje generowanie manifestu i OpenAPI z jednego deskryptora.

## Migracja, nie przepisywanie

`adopt.py` mapuje istniejące `urirun.bindings.v2` na Capabilities 1:1, a adapter
`http-node` dyspozycjonuje do działającego mesha bez zmian — to ścieżka
migracji. Adaptery (`python`, `subprocess`, `http-node`) są wtyczkami.

```bash
python -m pytest tests -q                       # rdzeń + konformans
python adopt.py                                  # adoptuj realny rejestr v2, pokaż lock + zdarzenia
URIRUN_CAP_LIVE=1 python -m pytest tests/test_live_node.py   # steruj żywym node'em twina
```

## Następne kroki (wdrażać krok po kroku, obserwować, ulepszać)

- [x] Rdzeń + niezmienniki + testy.
- [x] Adopcja realnego rejestru v2 + wykrywanie dryfu.
- [x] Sterowanie żywym node'em pc1 przez adapter `http-node`.
- [x] **Powierzchnia HTTP + OpenAPI** (`serve.py`) — klient nie-Python (curl/JS/Go)
      steruje tą samą zdolnością z tym samym typowanym kontraktem. `/openapi.json`
      generowany z rejestru → codegen typowanego klienta w dowolnym języku.
- [x] **Metryki na różnych poziomach** (`bench.py`, `capability.metrics`): to samo
      zadanie dwiema drogami — **×1.7 szybciej/zadanie** (749→445 ms), przepustowość
      1.34→2.25 zad./s, plus walidacja outputu, której baseline nie ma. Wynik trafia
      do raportu (`report/out` odcinek #5) jako `metric://`.
- [x] **Node (serwer) w dowolnym języku + negocjacja backendów** — ten sam
      kontrakt `sys://host/os/query/info` spełniają node'y w **JavaScript** i **Go**
      (`nodes/node.js`, `nodes/node.go`); każdy ogłasza przez `/capabilities` co
      potrafi i jakim backendem. Jeden klient Python steruje oboma jednakowo i
      waliduje ich output tym samym kontraktem (`tests/test_polyglot.py`).
- [ ] Planner jako przeszukiwanie typowanej przestrzeni z `examples` (LLM opcjonalny).
- [ ] Upstream: emisja zdarzeń jako niezmiennik runtime'u urirun.

## Warstwa URI-process w dowolnym języku (server dla client)

Tak — „serwer" (node wykonujący URI process) da się napisać w dowolnym języku.
To **protokół sieciowy**, nie biblioteka Pythona:

```
GET  /health        -> { ok, lang, capabilities }
GET  /capabilities  -> ogłasza jakie kontrakty spełnia (+ backend)   ← negocjacja
POST /dispatch {uri, payload} -> { ok, result } | { ok:false, error:{category} }
```

Ten sam kontrakt `sys://host/os/query/info` spełniają:

| Język | Plik | Backend ogłaszany | `result.lang` |
| --- | --- | --- | --- |
| JavaScript | `nodes/node.js` | `node:v20…` | `javascript` |
| Go (kompilowany) | `nodes/node.go` | `go:go1…` | `go` |

Jeden klient (Python Capability core) steruje **oboma** identycznie, waliduje
ich output tym samym typowanym kontraktem, a bramka kontraktu działa niezależnie
od języka serwera. Dopisanie node'a w Rust/PHP/Ruby = te same 3 endpointy.

```bash
URIRUN_CAP_POLYGLOT=1 python -m pytest tests/test_polyglot.py -q   # klient Python ↔ node JS + Go
```

## Reużywalność w dowolnym techstacku

Deskryptor zdolności to JSON + JSON Schema — z natury przenośny. `serve.py`
wystawia go po HTTP z auto-generowanym OpenAPI, więc **dowolny stos** (curl,
JavaScript, Go, klient z codegenu OpenAPI) steruje tymi samymi zdolnościami,
z tą samą typowaną walidacją i tymi samymi zdarzeniami — niezależnie od języka
wywołującego.

```bash
python serve.py &                                   # HTTP + /openapi.json
curl -sX POST localhost:8850/dispatch -d '{"uri":"demo://local/echo/query/text","payload":{"text":"hi"}}'
python bench.py 8                                    # zmierz baseline vs Capability
```

Prototyp — cel: pokazać na małym wycinku, o ile prostszy i odporniejszy jest
wynik, zanim zdecydować o większej zmianie.
