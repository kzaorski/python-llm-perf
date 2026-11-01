# Ćw. 14 — podpowiedź 2 (API Redis / taskiq)

- `await r.xinfo_groups(STRUMIEN)` → słownik grupy `GRUPA`: `lag`, `pending`, `last-delivered-id`.
- Najstarszy nieodebrany: `await r.xrange(STRUMIEN, min="(" + last_delivered_id, max="+", count=1)`;
  wiek = teraz − (ID w ms, część przed `-`).
- Opcjonalnie najstarszy w toku: `await r.xpending(STRUMIEN, GRUPA)` → `min`.
- Worker: `--workers 2 --max-async-tasks 4` (2 × 4 = 8 = moc dostawcy); prefetch (`xread_count` brokera) =
  `ZADANIA_MAX_ASYNC`, nie 100.
