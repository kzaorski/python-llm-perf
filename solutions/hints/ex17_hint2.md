# Ex. 17 — hint 2 (commands)

- `python scripts/compare_with_claude.py --mock-only -n 3` → `results/ex17-comparison.json` (the `mock` section).
- With a key only in the shell (`read -s ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY`): without `--mock-only`;
  cost ≈ $0.005. After the measurement `unset ANTHROPIC_API_KEY`.
- Compare `ttft_p50_s`, `ttft_max_s`, `total_p50_s`, `tok_per_s_p50` per task and the `headers` sections.
