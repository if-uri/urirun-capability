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
- [ ] Wystawić Capability jako powierzchnię **OpenAPI (query)** / **AsyncAPI+CloudEvents (command)** — dowolny klient steruje node'em.
- [ ] **Negocjacja backendów**: node ogłasza czym spełni kontrakt (zamiast łańcuchów w Pythonie) → node w Rust/Go/JS spełnia ten sam kontrakt.
- [ ] Planner jako przeszukiwanie typowanej przestrzeni z `examples` (LLM opcjonalny).
- [ ] Upstream: emisja zdarzeń jako niezmiennik runtime'u urirun.

Prototyp — cel: pokazać na małym wycinku, o ile prostszy i odporniejszy jest
wynik, zanim zdecydować o większej zmianie.
