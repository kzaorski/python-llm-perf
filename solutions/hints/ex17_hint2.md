# Ćw. 17 — podpowiedź 2 (polecenia)

- `python scripts/porownaj_z_claude.py --tylko-atrapa -n 3` → `wyniki/ex17-porownanie.json` (sekcja `atrapa`).
- Z kluczem tylko w powłoce (`read -s ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY`): bez `--tylko-atrapa`;
  koszt ≈ $0.005. Po pomiarze `unset ANTHROPIC_API_KEY`.
- Porównuj `ttft_p50_s`, `ttft_max_s`, `calosc_p50_s`, `tok_na_s_p50` per zadanie oraz nagłówki `naglowki`.
