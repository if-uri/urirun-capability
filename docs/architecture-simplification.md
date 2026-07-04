# Czy da się uprościć system: connectors, contracts, transports

Analiza oparta na zmierzonym stanie ekosystemu (nie na wrażeniu), z konkretną ścieżką
uproszczenia. Liczby z `~/github/if-uri` (lipiec 2026).

## Zmierzony stan

| Element | Ile | Uwaga |
|---|---|---|
| Connectory (`urirun-connector-*`) | **38** | każdy to osobna paczka pip |
| Connectory z osobnym `contracts.py` | 18 | **2520 linii** definicji kontraktów |
| Manifesty `connector.manifest.json` | 45 | **druga forma** tych samych kontraktów |
| Paczki `urirun-contract-*` | 4 | brama `toolkit` **36 lin × 4 = 144 zduplikowane** |
| Rdzeń kvm (jeden connector) | 5781 lin | backends+core+contracts+cdp+environment |

## Trzy realne źródła złożoności

### 1. Kontrakt zdefiniowany 2–3 razy
Ten sam kontrakt żyje w:
- `contracts.py` — obiekty `Contract` (inp/out w mini-schemacie, effect, reversible);
- `connector.manifest.json` — rzut: `routes` (48 URI), `examples` (42), metadane;
- **sygnaturach handlerów** — trzecia, niejawna deklaracja tego samego kształtu.

Muszą być ręcznie zsynchronizowane. Rozjazd = cichy błąd (manifest mówi jedno, kod robi drugie).

**Zmierzone empirycznie** (`drift_audit.py`, `metric://architecture/drift`): z 32 connectorów
z manifestem i handlerami **1 ma realny rozjazd** (`twin`: 25 handlerów w kodzie, 0 tras w
manifeście). Pozostałe 31 trzymają się zgodnie — ale **wyłącznie ręczną dyscypliną**. Co
istotniejsze: sam ten audyt wymagał trzech iteracji normalizacji tras (goły dekorator +
prefiks sub-routera `@PAGE.handler` vs pełne URI w manifeście, różna głębokość authority) —
**reprezentacja jest tak niespójna, że wykrycie rozjazdu jest trudne**. Generowanie manifestu
z jednego deskryptora usuwa całą tę klasę problemu: rozjazd staje się strukturalnie niemożliwy,
a forma trasy — jedna.

### 2. Boilerplate na paczkę, nie na kontrakt
Każdy `urirun-contract-*` wozi 36-liniową bramę (`toolkit`) + gate + I/O — **~422 linie na
2 kontrakty** (zmierzone). To kod publikowany, wersjonowany i utrzymywany per paczka, choć
jest identyczny.

### 3. Własny mini-schema DSL zamiast standardu
`inp/out` używają mini-schematu (`"str"`, `"?int"`, `"const:X"`, `oneOf`) — własnego,
nieinteroperacyjnego. Istnieje JSON Schema/OpenAPI z gotowym tooltingiem.

## Propozycja: jeden deskryptor, reszta generowana

Model **Capability** (udowodniony w tym repo, ~320 lin. rdzenia, 81 testów) sprowadza to do
JEDNEGO źródła prawdy — typowanego deskryptora — z którego **generuje się reszta**:

```
                    ┌─────────────────────────────┐
   Capability   →   │ deskryptor (dane): uri,      │
   (jedno źródło)   │ effect, input/output (JSON   │
                    │ Schema), reversible/inverse, │
                    │ errors, examples, adapter    │
                    └──────────────┬──────────────┘
                                   │ projekcje (generowane, nie pisane)
        ┌──────────────────┬───────┴────────┬──────────────────┐
   manifest.json      OpenAPI 3         gate/walidacja     lockfile (drift)
   (routes+examples)  (to/from_openapi)  (wspólny runtime)  (content-address)
```

Konsekwencje, każda zmierzona lub przetestowana w tym repo:

- **contracts.py + manifest.json → jeden deskryptor.** Manifest (routes+examples) i OpenAPI
  są *projekcją* deskryptora — utrzymujesz jedno, generujesz oba. Koniec rozjazdu.
- **422 lin. boilerplate/connector → 0.** Brama, gate, emisja zdarzeń, walidacja outputu to
  **wspólny runtime**, nie kod per paczka (metryka: 1693 lin. w 4 paczkach → 323 lin. rdzenia).
- **mini-schema → JSON Schema.** Konwerter `contracts_adopt.mini_to_jsonschema` już mapuje
  pełną gramatykę; dalej używasz standardu z toolingiem.
- **examples = konformans + few-shot + planner**, jedną zasadą (`output_matches`), pilnowaną
  niezmiennikiem — zamiast osobnych testów per connector.
- **38 paczek pip → deskryptory + adaptery-wtyczki.** Connector = deskryptory (dane) + moduł
  handlera; adapter (`python`/`subprocess`/`http-node`) to jedyna realna zmienność. Reszta
  (transport HTTP/MCP/gRPC, mesh, dispatch) jest wspólna.

## Czego NIE upraszczać (uczciwie)

- **Adaptery** są realną zmiennością (jak dana zdolność się wykonuje) — zostają wtyczkami.
- **Mesh/transport** (discovery, dispatch, diagnoza) to wspólna wartość, nie boilerplate.
- **Handlery** — logika connectora (OCR, CDP, ADB) jest nieredukowalna; upraszczamy *obudowę*
  kontraktu wokół niej, nie samą logikę.
- Zadania otwarte-językowe (obsługa czatu, tłumaczenie z kontekstem) zostają przy LLM — to
  komplementarność, nie coś do „deterministyzacji".

## Ścieżka migracji (bez przepisywania)

1. `adopt_contracts` już czyta realny `contracts.json`/rejestr v2 → Capabilities (1:1).
2. `to_openapi` / `from_openapi` → most do standardu i z powrotem.
3. `http-node` adapter dyspozycjonuje do istniejącego mesha bez zmian po stronie node'a.
4. Manifest generowany z deskryptora (patrz `projections.py`) — przestaje być pisany ręcznie.

Krok po kroku, connector po connectorze; każdy krok mierzalny metryką
`metric://contract/refactor`.

## Dowód end-to-end: connector wyłącznie z deskryptorów (`poc_connector_hash.py`)

Kompletny, działający connector `hash` zbudowany wyłącznie z deskryptorów na wspólnym
rdzeniu — bez `contracts.py`, bez `manifest.json`, bez bramy:

- **4 działające trasy** (sha256/sha1/md5/blake2b) w **80 liniach** jednego pliku;
- realne hashowanie, output walidowany kontraktem, `examples` konformują;
- **manifest i OpenAPI GENEROWANE** z deskryptorów (4 routes, 4 examples, 4 ścieżki) —
  nigdy pisane ręcznie, więc rozjazd jest strukturalnie niemożliwy;
- deskryptor produkuje dokładnie realną formę URI (`hash://host/text/query/sha256`) — interop.

Dla porównania oryginał obsługuje **1 trasę** w 96 liniach Go + ręczny `manifest.json` +
`go.mod` + testy. PoC: 4 trasy, mniej kodu, zero plików kontraktu do utrzymania. To nie
oznacza, że każdy connector jest tak trywialny (kvm ma nieredukowalną logikę CDP/OCR) — ale
**obudowa kontraktu** wokół każdej logiki redukuje się do zera.

## Odpowiedź wprost

**Tak — da się znacząco uprościć**, i to jest zmierzone, nie deklaratywne: kontrakt z 2–3
źródeł do jednego deskryptora, ~422 lin. boilerplate/connector do zera na wspólnym rdzeniu,
własny DSL do JSON Schema/OpenAPI, a 38 paczek do „dane + adapter" na jednym runtime. To, co
zostaje złożone (adaptery, mesh, logika handlerów), jest złożone **z istotnych powodów**, nie
z powielania.
