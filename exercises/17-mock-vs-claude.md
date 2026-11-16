# Exercise 17: Mock vs real Claude — calibrating the capacity model

> Time: ~30 min. **The part with real Claude is optional** and requires your own `ANTHROPIC_API_KEY`;
> the cost of the default run (8 × 3 tasks, model `claude-haiku-5-5`) ≈ **$0.005** (in my run 24 calls:
> $0.0042), certainly < $0.05. Without a key: the `--mock-only` mode (no cost).

> Block V. Reading `14a-task-queues-cache-batching.md`; `00-theory.md` "LLM specifics: TTFT, tokens,
> minutes, limits, cost".

## Goal
The whole course stands on a mock: repeatable, with controlled limits and delays. Conclusions about capacity
(how many slots, what wait budget, what timeouts) are worth only as much as the mock's agreement with reality.
You measure the same set of tasks on the mock and on the real API, compare the distribution of TTFT, total time,
token rate and the limit headers — and check whether the numbers from ex. 3 and 6 need recalculating.

## Theory in a nutshell
- **Capacity model** — you take W (service time) in L = λ·W from a measurement. For an LLM W ≈ TTFT + output_tokens /
  rate. The trap: the average hides the tail — plan for the percentile the SLO refers to.
- **The mock** gives a log-normal TTFT distribution and a constant token rate; the real API has its own tail, variation
  during the day and account limits. Why compare: to know which conclusions of the course carry over 1:1 (the mechanisms:
  queues, slots, timeouts) and which need calibration (the numbers).
- **The `anthropic-ratelimit-*` headers** — `requests`, `input-tokens`, `output-tokens`, `tokens` × `limit`,
  `remaining`, `reset`. The mock exposes the same names (ex. 8), so the limiter works the same way; the values depend on the account.
- The trap: a sequential comparison measures W, not behavior under load — you do not test that on the real API (cost,
  account limits, impact on other users).

## Steps
1. Without a key (always possible):
   ```bash
   python scripts/compare_with_claude.py --mock-only -n 3
   ```
   The script streams n tasks of each of three types (classification max 16 tokens, summary 200, reply
   700) and writes `results/ex17-comparison.json`. In my run (n = 3): TTFT p50 0.5 s; classification 0.47 / 0.52 s
   (TTFT / total), summary 0.59 / 1.35 s (214 tok/s), reply 0.49 / 2.22 s (216 tok/s); the estimated cost of
   these tokens at Haiku prices $0.00085 (the mock costs nothing — this is a conversion). `check.py ex17` → SKIP.
2. **Hypothesis (write it down):** TTFT p50 and tokens/s rate on real Claude — higher or lower than on the mock?
   Which type of task will have the largest relative difference in total time?
3. **(Optional, cost ≈ $0.005)** with a key — only in the current shell, never in the repo:
   ```bash
   read -s ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY
   python scripts/compare_with_claude.py
   unset ANTHROPIC_API_KEY
   ```
   The result has the sections `mock` and `claude` (+ `cost_usd`). Reference data from my measurement (n = 8, sequential,
   stream, `thinking` disabled):

   | Task | TTFT min / med / max | Total med | tok/s med |
   |---|---|---|---|
   | classification (max 16) | 0.60 / 0.72 / 0.87 s | 0.72 s | — (too short) |
   | summary (max 200) | 0.47 / 0.52 / 1.16 s | 1.23 s | 301 |
   | reply (max 700) | 0.44 / 0.48 / 0.77 s | 3.62 s | 225 |

   The mock (default TTFT 450 ms log-normal, 250 tok/s): classification 0.45 s, summary 0.63 / 1.34 s,
   reply TTFT 0.35 / total 2.60 s (190 tok/s). 30 parallel classifications on Claude: med 0.85, max 1.45 s.
4. Compare the limit headers (`headers` in both JSON sections). In my run the account: RPM 13,000, ITPM 10 M, OTPM 2 M —
   a 429 on the real API at the course's traffic is practically unreachable; that is why you practice the limits on the mock
   (the `limits` profile: RPM 120, ITPM 60,000, OTPM 12,000).
5. **Calibration:** use Little's law to recalculate the number of slots from ex. 6 for your measured W (summary, p50 and p90)
   at a traffic of 20/s. Are 32 slots enough? And for a reply of 700 tokens?
6. `python check.py ex17` — without a key and without a `claude` section in the result: SKIP (the optional part); with a `claude` section: PASS.

## Definition of done
- [ ] You have `results/ex17-comparison.json` (at least the `mock` section).
- [ ] You can say which numbers from the course need recalculating for the real API and which mechanisms do not.
- [ ] (Optional) `python check.py ex17` = PASS with the `claude` section.

## Review questions
1. Why do you make the comparison sequentially, rather than with k6 at 20/s against the real API?
2. Claude's TTFT has a max of 1.16 s with a median of 0.52 s. What value will you set the read timeout of the short calls to (ex. 10), and why not 1.2 s?
3. The mock has 250 tok/s, Claude 225–301. How does this difference translate into the number of slots for a reply of 700 tokens?

Answers: `solutions/questions_answers.md`.

## ★ Bonus (optional)
Set the mock to imitate your measurement (`PATCH /admin/config?provider=a` with `ttft_median_ms`, `ttft_sigma`,
`tokens_per_s`) and repeat ex. 3 (the ramp). Has the knee of the curve moved as Little's law predicts?

---
Stuck? `solutions/hints/ex17_hint1.md` → `hint2` → `hint3`. There is no code to copy in this exercise.
