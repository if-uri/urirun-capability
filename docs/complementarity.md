# Komplementarność: LLM ↔ deterministyczne zdolności

Ten dokument opisuje logikę, którą projekt `urirun-capability` udowadnia w kodzie i
testach: **model typowanych zdolności jest najsilniejszy dokładnie tam, gdzie sam
LLM jest najsłabszy** — i odwrotnie. To nie konkurencja, lecz podział pracy.

## Gdzie LLM jest najsłabszy

Zadania biurowe, w których LLM-y regularnie zawodzą, mają wspólny mianownik: wymagają
**jednocześnie długiego kontekstu, wielu zależności, dokładnej rekonsyliacji i
weryfikacji sensu** — a nie wygenerowania płynnego tekstu. Z listy „anty-LLM":

| Zadanie | Dlaczego trudne dla LLM | Zdolność deterministyczna |
|---|---|---|
| Uzgadnianie systemów, które inaczej nazywają te same pola | halucynuje dopasowania, myli formaty kwot | `recon://…/reconcile` + `money()` normalizacja |
| Porównanie niespójnych plików/dokumentów | gubi się w układzie, „na oko" akceptuje różnice | `audit://…/consistency` (równość wartości, nie formatu) |
| Reguły zależne od kontekstu (reklamacje, zwroty) | niespójnie stosuje warunki, nie potrafi uzasadnić | `rules://…/eligible` (zwraca regułę, która zadziałała) |
| Diagnoza przyczyny z niejednoznacznych objawów | zgaduje prawdopodobnie brzmiącą przyczynę | `diag://…/rootcause` (pokrycie objawów, raport niewyjaśnionych) |

Wspólna słabość LLM: **brak dokładnej rekonsyliacji i weryfikacji sensu**. Model
generatywny optymalizuje prawdopodobieństwo tekstu, nie równość `1665,00 == 1655,00`.

## Gdzie deterministyczne zdolności są najsilniejsze

Dokładnie w tych samych miejscach — bo typowana zdolność daje:

1. **Typowana normalizacja** — kontrakt (mini-schema → JSON Schema, `money()`) sprowadza
   „`1 665,00 zł`" i „`1665.00`" do jednej wartości, zanim cokolwiek się porówna.
2. **Weryfikacja sensu, nie formatu** — porównanie wartości po normalizacji, nie ich
   zapisu.
3. **Audytowalność** — decyzja zwraca *regułę, która zadziałała* (`prepaid-non-refundable`),
   nie nieokreśloną pewność.
4. **Determinizm** — ten sam wejściowy stan → ten sam wynik, powtarzalnie i testowalnie.
5. **Konformans z `examples`** — złote pary wejście→wyjście łapią regresję zachowania
   (patrz niżej), czego sam schemat nie daje.

## Test empiryczny (uczciwie: LLM nie jest głupi)

Uruchomiliśmy prawdziwy lokalny LLM (`gemma4:e4b` przez Ollama) na tych samych
zadaniach (`llm_compare.py`). Wynik jest bardziej niuansowy niż „LLM tego nie umie":

- **Na małych, jasno sformułowanych zadaniach LLM bywa poprawny i spójny** — rekonsyliacja
  15 faktur, konflikt zakopany w 12 instrukcjach, 8 pól do sprawdzenia: 3/3 trafień.
  Teza w naiwnej formie („LLM nie policzy") jest **za mocna** i byłoby nieuczciwie ją głosić.
- **Różnica ujawnia się przy SKALI i GWARANCJACH.** Przy 50 fakturach model odpowiadał
  raz `3`, raz `30` — **niespójny dryf**, gdy zdolność zawsze zwraca `3`. A niezależnie od
  trafienia: LLM ~21 000 ms/zadanie vs zdolność ~110 µs (**~188 000×**), bez proweniencji
  (nie mówi KTÓRA faktura), bez dowodu, bez powtarzalności.

**Wniosek (właściwa komplementarność):** to nie „LLM kontra reguły". LLM jest dobry do
otwartej interpretacji i małej skali; deterministyczna zdolność wygrywa tam, gdzie liczy
się **skala, spójność, czas, proweniencja i dowód** — i to jest mierzalne, nie deklaratywne.

## Gdzie LLM jest najsilniejszy (i tu zostaje)

LLM świetnie radzi sobie z **otwartą interpretacją celu**: „*otwórz sklep i zrób
zrzut*", „*odpowiedz szefowi i zamów 3 CyberMysz*". W tym projekcie tę rolę pełni
**planner** — ale nawet on jest deterministyczny (dopasowanie słów kluczowych +
kolejność + payload z `examples`), a LLM jest **opcją do doboru/parafrazy celu**, nie
wymogiem do wykonania czy weryfikacji. Podział pracy:

```
   dobór/parafraza celu   →   [ LLM opcjonalnie ]
   planowanie sekwencji   →   deterministyczny planner (examples jako nasiona)
   wykonanie              →   typowane zdolności (adaptery: python / http-node / …)
   weryfikacja wyniku     →   kontrakt out + examples (konformans, regresja)
   cofnięcie/transakcja   →   effect + reversible + inverse (saga, bez LLM)
```

**Wniosek:** LLM do tego, co otwarte i językowe; zdolności do tego, co wymaga
dokładności, powtarzalności i dowodu. Najlepszy system łączy oba, a nie zastępuje
jednego drugim.

## Zasada `examples` — jedna, spójna w całym systemie

`examples` w każdej zdolności pełnią potrójną rolę: **test konformansu**, **dane
few-shot**, **nasiono plannera**. Żeby działały „na tej samej zasadzie" wszędzie,
konformans używa **dopasowania częściowego** (`output_matches`), nie ścisłej równości:

> Golden output przykładu to **specyfikacja częściowa**: każde pole, które podaje, musi
> zgadzać się z wynikiem; handler może dodać pola runtime (wygenerowane `id`, `inverse`
> z konkretnym pid, czas) bez łamania konformansu. **Błędne wartości nadal są łapane** —
> tolerowane są tylko nienazwane pola dodatkowe.

Dzięki temu jedna złota para weryfikuje zachowanie w handlerach, które legalnie
adnotują wynik w runtime. Dwie konsekwencje projektowe, wymuszone audytem
(`audit_examples.py`, `test_audit_examples.py`):

- **Adopcja kontraktu (stub) jest świadoma wejścia** — stub odtwarza output przykładu
  *pasującego do wejścia*, więc kontrakt z wieloma przykładami konformuje na *wszystkich*,
  nie tylko pierwszym.
- **Identyfikatory są content-adresowane** — `id` liczone z treści wejścia, nie ze stanu
  licznika, więc golden pinuje stabilną wartość, a operacja jest idempotentnie-testowalna.

Meta-niezmiennik strzeżony testem: **każda zdolność z `examples` konformuje w 100%**;
nowa zdolność z martwym przykładem wywala `test_every_example_across_every_registry_conforms`.

## Jak to sprawdzić

```bash
python audit_examples.py          # raport konformansu na zdolność, per rejestr
python demo_hard_tasks.py         # 4 zadania „anty-LLM" na danych z twina
pytest tests/test_hard_tasks.py   # happy-path + wychwycenie trudnego przypadku
pytest tests/test_audit_examples.py   # niezmiennik: wszystkie examples konformują
```
