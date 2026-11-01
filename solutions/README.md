# solutions/ — rozwiązania kumulatywne

Każdy plik `exNN_<moduł>.*` to **pełna** wersja modułu po ćwiczeniu NN (zawiera też wcześniejsze zmiany
tego modułu). Kopiowanie odblokowuje Cię na danym etapie — to ostatni szczebel drabinki, po podpowiedziach
z `solutions/hints/`.

```bash
cp solutions/ex06_limiter.py app/llm/limiter.py      # stan modułu po ćw. 06 (zawiera ćw. 01)
```

| Plik | Kopiuj do | Ćw. | Wada |
|---|---|---|---|
| `ex01_limiter.py` | `app/llm/limiter.py` | 01 | (TODO: pomiar czekania na slot) |
| `ex02_otwarty.js` | `k6/otwarty.js` | 02 | W14 model zamknięty zaniża ogon |
| `ex04_klasyfikacja.py` | `app/klasyfikacja.py` | 04 | W1 synchroniczny klient w `async def` |
| `ex05_szablony.py` | `app/szablony.py` | 05 | W2 pula wątków anyio (40) |
| `ex06_limiter.py` | `app/llm/limiter.py` | 06 (+01) | W3 za mało slotów |
| `ex07_gunicorn.py` | `gunicorn.conf.py` | 07 | W13 workery sync / 2×CPU+1 |
| `ex08_limiter.py` | `app/llm/limiter.py` | 08 (+01, 06) | W4 brak limitera tempa → 429 |
| `ex09_klient.py`, `ex09_ponowienia.py` | `app/llm/klient.py`, `app/llm/ponowienia.py` | 09 | W5 ponowienia SDK × aplikacji |
| `ex10_klient.py`, `ex10_wywolanie.py` | `app/llm/klient.py`, `app/llm/wywolanie.py` | 10 (+09) | W6, W16, W17 timeouty / deadline / anulowanie |
| `ex11_fallback.py` | `app/llm/fallback.py` | 11 | W12 fallback bez wyłącznika |
| `ex12_limiter.py`, `ex12_przeciazenie.py` | `app/llm/limiter.py`, `app/przeciazenie.py` | 12 (+01, 06, 08) | W7, W8, W18 |
| `ex13_strumien.py` | `app/strumien.py` | 13 | W9 buforowany strumień |
| `ex14_zadania.py`, `ex14_kolejka_metryki.py` | `app/zadania.py`, `app/kolejka_metryki.py` | 14 | W15 współbieżność/prefetch workera |
| `ex15_cache.py` | `app/cache.py` | 15 | W10 cache stampede |
| `ex16_wsad.py` | `app/wsad.py` | 16 | W11 okno i rozmiar wsadu |

Ćw. 03 (prawo Little'a, `k6/rampa.js`) i 17 (atrapa vs Claude, `scripts/porownaj_z_claude.py`) nie zmieniają
kodu aplikacji. `app/main.py` nie jest zmieniany w żadnym ćwiczeniu, więc nie ma pliku `*_fragmenty`.

## Stan „po ćwiczeniu NN" bez kopiowania

`scripts/nakladka.py --do NN` składa kopię aplikacji w `.run/do-NN/` (Twoje `app/` zostaje nietknięte):

```bash
python scripts/nakladka.py --do 12
uvicorn --app-dir .run/do-12 app.main:app --port 8060
```

Na tym stoją `./smoke.sh` (regresja `check.py --all` na rozwiązaniach) i `./incydent.sh` (finał).

## Utknąłeś? Kolejność ratunku

1. `hints/exNN_hint1.md` — kierunek (bez kodu),
2. `hints/exNN_hint2.md` — które API / metryka / zapytanie,
3. `hints/exNN_hint3.md` — pseudokod,
4. dopiero potem: skopiuj gotowy moduł (tabela powyżej) albo uruchom stan „po ćwiczeniu NN” (`nakladka.py`).

Podpowiedzi są dla wszystkich 18 ćwiczeń (także 03 i 17, które nie zmieniają kodu, i dla finału 18).

## Pozostałe pliki

- `pytania_odpowiedzi.md` — klucz do pytań kontrolnych ćw. 01–18 i do mini-incydentów I–IV; zaglądaj PO
  własnej próbie odpowiedzi.
- `ex18_odpowiedzi.md` — klucz do finału (objaw → ślad → przyczyna → naprawa dla każdej usterki, interakcje,
  wykluczenia) + rubryka samooceny. Otwórz dopiero PO napisaniu własnego raportu.
- `todo.md` — pomysły na rozszerzenia kursu (kolejne wady i ćwiczenia).
