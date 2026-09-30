# Compute plan for the Haiku clean baseline (Task-0004 remainder)

No token counts invented. Anchors: README `Cost and time` (~375-555 council
calls per 36-month 5-seat run + founding/formation/survey + foreign cabinets);
per-call in/out tokens + latency + cost already logged (`council.py:298-300`);
Haiku served once via claude_cli (`runs/20260928-204444-seed1/survey.json:220`).

## Calls per run (measured, not estimated)

Measure before projecting: run
`tools/research_mine.py` (call-type counts) + sum `input_tokens/output_tokens`
over `type=call/foreign_call` rows in the 090535 log (220 lines, 6 months) to get
per-month-per-seat means; scale to 36 months for the plan. Do this after the
first Haiku pilot run lands (1 pilot run >> all projection).

## Why sequential dependence prevents trivial batching

Month m+1 prompts embed month-m outcomes (snapshot, memories, directives);
`parallel_decisions` parallelizes seats WITHIN a phase, never across months.
Wall-clock ~= months x slowest-seat latency x phases. CLI seats serialize
additionally when the connector does.

## Pilot (Haiku 4.5, Condition A): 3 seeds x 6-12 months

- Config: 5x `provider=claude_cli, model=claude-haiku-4-5-20251001`, effort unset
  (Haiku ignores effort), ports per seat auto. Start 6 months; extend to 12 if
  stable. Cost: subscription seats log cost_usd=0 by design
  (`compute_instrumentation_gap.md`); real cost = subscription time, not tokens.
- Seat-test first: `python -m karamaniya check council.haiku.toml` (one tiny call
  per seat, shows served model) — required before `run`.
- After each run: research_mine row + episode export + human labels + agreement.

## Paper scale (after pilot variances)

A: 10 seeds; B: 10; C: 2 swaps x 5 seeds = 10; D (optional): 5 mixed.
Total ~= 30-35 runs. With pilot TDI variance, compute N for 80% power on A-vs-B
TDI difference; if variance is high, report as exploratory + publish pilot.

## Config file

See `council.haiku.toml` (new, repo root): 5x Haiku seats, seed placeholder,
6-month pilot default, survey ON, foreign cabinets ON, prices unset (subscription).
