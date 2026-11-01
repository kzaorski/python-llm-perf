# Ćwiczenie 17: Atrapa vs prawdziwy Claude — kalibracja modelu pojemności

> Czas: ~30 min. **Część z prawdziwym Claude jest opcjonalna** i wymaga własnego klucza `ANTHROPIC_API_KEY`;
> koszt domyślnego przebiegu (8 × 3 zadania, model `claude-haiku-5-5`) ≈ **$0.005** (u mnie 24 wywołania:
> $0.0042), na pewno < $0.05. Bez klucza: tryb `--tylko-atrapa` (bez kosztu).

> Blok V. Czytanka `14a-kolejki-zadan-cache-batching.md` („Atrapa a rzeczywistość”); `00-teoria.md` „Czas
> wywołania LLM: TTFT, tokeny/s, ogon”.

## Cel
Cały kurs stoi na atrapie: powtarzalnej, z kontrolowanymi limitami i opóźnieniami. Wnioski o pojemności
(ile slotów, jaki budżet czekania, jakie timeouty) są tyle warte, ile zgodność atrapy z rzeczywistością.
Mierzysz ten sam zestaw zadań na atrapie i na prawdziwym API, porównujesz rozkład TTFT, czasu całkowitego,
tempa tokenów i nagłówki limitów — i sprawdzasz, czy liczby z ćw. 03 i 06 trzeba przeliczyć.

## Teoria w pigułce
- **Model pojemności** — W (czas obsługi) w L = λ·W bierzesz z pomiaru. Dla LLM W ≈ TTFT + tokeny_wyjścia /
  tempo. Pułapka: średnia ukrywa ogon — planuj na percentyl, którego dotyczy SLO.
- **Atrapa** daje rozkład log-normalny TTFT i stałe tempo tokenów; realne API ma własny ogon, zmienność w ciągu
  dnia i limity konta. Po co porównanie: żeby wiedzieć, które wnioski kursu przenoszą się 1:1 (mechanizmy:
  kolejki, sloty, timeouty), a które wymagają kalibracji (liczby).
- **Nagłówki `anthropic-ratelimit-*`** — `requests`, `input-tokens`, `output-tokens`, `tokens` × `limit`,
  `remaining`, `reset`. Atrapa wystawia te same nazwy (ćw. 08), więc limiter działa tak samo; wartości zależą od konta.
- Pułapka: porównanie sekwencyjne mierzy W, nie zachowanie pod obciążeniem — tego na prawdziwym API nie
  testujesz (koszt, limity konta, wpływ na innych użytkowników).

## Kroki
1. Bez klucza (zawsze możliwe):
   ```bash
   python scripts/porownaj_z_claude.py --tylko-atrapa -n 3
   ```
   Skrypt wysyła strumieniem po n zadań trzech typów (klasyfikacja max 16 tokenów, streszczenie 200, odpowiedź
   700) i zapisuje `wyniki/ex17-porownanie.json`. ⟨E17-ATRAPA⟩
2. **Hipoteza (zapisz):** TTFT p50 i tempo tokenów/s na prawdziwym Claude — większe czy mniejsze niż na atrapie?
   Który typ zadania będzie miał największą względną różnicę czasu całkowitego?
3. **(Opcjonalnie, koszt ≈ $0.005)** z kluczem — tylko w bieżącej powłoce, nigdy w repo:
   ```bash
   read -s ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY
   python scripts/porownaj_z_claude.py
   unset ANTHROPIC_API_KEY
   ```
   Wynik ma sekcje `atrapa` i `claude` (+ `koszt_usd`). Dane referencyjne z mojego pomiaru (n = 8, sekwencyjnie,
   strumień, `thinking` wyłączone):

   | Zadanie | TTFT min / med / max | Całość med | tok/s med |
   |---|---|---|---|
   | klasyfikacja (max 16) | 0.60 / 0.72 / 0.87 s | 0.72 s | — (za krótko) |
   | streszczenie (max 200) | 0.47 / 0.52 / 1.16 s | 1.23 s | 301 |
   | odpowiedź (max 700) | 0.44 / 0.48 / 0.77 s | 3.62 s | 225 |

   Atrapa (domyślnie TTFT 450 ms log-normal, 250 tok/s): klasyfikacja 0.45 s, streszczenie 0.63 / 1.34 s,
   odpowiedź TTFT 0.35 / całość 2.60 s (190 tok/s). 30 równoległych klasyfikacji na Claude: med 0.85, max 1.45 s.
4. Porównaj nagłówki limitów (`naglowki` w obu sekcjach JSON). U mnie konto: RPM 13 000, ITPM 10 M, OTPM 2 M —
   429 na prawdziwym API przy ruchu z kursu jest praktycznie nieosiągalne; dlatego limity ćwiczysz na atrapie
   (profil `limity`: RPM 120, ITPM 60 000, OTPM 12 000).
5. **Kalibracja:** przelicz z Little'a liczbę slotów z ćw. 06 dla Twoich zmierzonych W (streszczenie, p50 i p90)
   przy ruchu 20/s. Czy 32 sloty wystarczą? A dla odpowiedzi 700 tokenów?
6. `python check.py ex17` — bez klucza i bez sekcji `claude` w wyniku: SKIP (część opcjonalna); z sekcją `claude`: PASS.

## Kryteria „done”
- [ ] Masz `wyniki/ex17-porownanie.json` (co najmniej sekcję `atrapa`).
- [ ] Umiesz powiedzieć, które liczby z kursu wymagają przeliczenia dla prawdziwego API, a które mechanizmy nie.
- [ ] (Opcjonalnie) `python check.py ex17` = PASS z sekcją `claude`.

## Pytania kontrolne
1. Dlaczego porównanie robisz sekwencyjnie, a nie k6 z 20/s na prawdziwe API?
2. TTFT Claude ma max 1.16 s przy medianie 0.52 s. Na którą wartość ustawisz read timeout krótkich (ćw. 10) i dlaczego nie na 1.2 s?
3. Atrapa ma 250 tok/s, Claude 225–301. Jak ta różnica przekłada się na liczbę slotów dla odpowiedzi 700 tokenów?

Odpowiedzi: `solutions/pytania_odpowiedzi.md`.

## ★ Bonus (opcjonalnie)
Ustaw atrapę tak, by naśladowała Twój pomiar (`PATCH /admin/config?provider=a` z `ttft_median_ms`, `ttft_sigma`,
`tokens_per_s`) i powtórz ćw. 03 (rampa). Czy kolano krzywej przesunęło się tak, jak przewiduje Little?

---
Utknąłeś? `solutions/hints/ex17_hint1.md` → `hint2` → `hint3`. W tym ćwiczeniu nie ma kodu do skopiowania.
