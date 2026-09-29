# Overnight Engine Report

Engine hardening and causal-world-model shift on Karamaniya.

---

## 1. What this session produced

**Engine version.** `WORLD_ENGINE` raised **2 → 3**. Every run stamps the engine that produced it,
so a run paused under engine 2 and resumed under 3 cannot silently mix two economies in one
history. Older runs keep the version they were recorded with.

**Commits** (this repository had no history before this session — `d8a8ac5` is a baseline snapshot
of the tree as handed over):

| Commit | What |
|---|---|
| `d8a8ac5` | baseline snapshot, 358 tests passing |
| `2d43a41` | structured error taxonomy; foreign action idempotency |
| `4e3fd79` | provenance layers; fixes a hedged warning being read as a coup plot |
| `0ed6078` | causal world model core; run scanner; fixes a prompt-budget bug killing runs |
| `676b929` | lag registry and fiscal multiplier wired live; `docs/CAUSAL_WORLD_MODEL.md` |
| *(final)* | manifest wiring, version stamps, backlog, this report |

**Tests: 358 → 533, all passing.** No pre-existing test was weakened or removed.

---

## 2. What was inspected

The repository was read before anything was changed: `world.py`, `economy.py`, `engine.py`,
`council.py`, `politics.py`, `freshness.py`, `motion_actions.py`, `vacancy.py`, `decision_context.py`,
`intelligence.py`, `foreign.py`, `backends/`, `config.py`, `runner.py`, `storage.py`, the README,
and the full test suite. Then all 88 archived runs under `runs/`.

## 3. What was *not* rebuilt, and why

A large part of the mission brief's Phase 1 was **already implemented and tested** before this
session. Rebuilding it would have been the wrong move, so it was verified and left alone:

| Brief item | Where it already lives |
|---|---|
| A. Canonical directive violation history | `freshness.py` — `defiance_log`, `_streak`, `restored_month`, "prior violations are never erased" |
| B. Memory phase timing | `memory.py` |
| C. Directive vs order vs actual state | `freshness.py` — `current_setting`, `directive_since`, `actual_text` |
| D. Office vacancy / removal authority | `vacancy.py` — `vacant_since`, `PRE_REMOVAL_ORDER` |
| G. Motion execution status | `convergence.py`, `council.py` |
| I. Amendment → final payload | `motion_actions.py` — `MOTION_ACTION_MISMATCH`, `EXECUTION_BLOCKED` |
| J. Numeric grounding | `council.py`, `motion_actions.py` |
| K. Stale memory / freshness | `freshness.py` |
| M. `UNKNOWN_LEVER` | `politics.py` |

This is recorded in `docs/ENGINEERING_BACKLOG.md` so the next reader does not redo it.

---

## 4. Bugs found and fixed

Five genuine defects. Each has a regression test; each was reproduced before being fixed.

### 4.1 A hedged warning was recorded as a coup plot (high)

Found by writing the provenance test first, which then failed.

A leaked private message reading **"Our fiscal fragility may cause a coup."** was matched by a
substring test for the word `coup` and treated as a coup plot. The engine fired `plot_exposed`,
stripped 8 trust and added 5 fear against the speaker, and applied a coup reputation effect
(`council.py`, `_publish_leaks`).

This is precisely the failure the brief's section F names as the example to prevent: *"CANONICAL
FACT: The commander warned about coup risk. No explicit coup instruction or plan was observed."*

**Fix.** The plot determination now requires an assertion of intent from the canonical layer and
reads the raw source rather than the press framing. A phrasal intent detector replaced the
single-word list ("use the army to remove the council" contains no word that a keyword list would
catch). `"if"` was removed from the hedge list: a conditional threat is still a statement of
intent.

### 4.2 Productivity raised potential output but not actual output (high)

A bug in this session's own work, caught by a sanity test.

Potential output grew at the structural productivity rate while actual output did not, so the
output gap **drifted permanently negative from trend growth alone** — about −3% after two years
with nothing wrong. Every downstream consumer would have inherited it: Okun, the regime label, the
demand-pressure term, the trace.

**Fix.** Productivity multiplies actual output as well as potential. The gap now measures
frictions and demand, which is what it is for.

### 4.3 Cline seats aborted the run over prompt length (high)

Found by scanning archived runs: `runs/20260929-003845-seed1` lost two seats at Month 1 with
*"this prompt is too long for a Windows command line"*, and those seats were lost for the
remainder of the run.

`decision_context.compose` advertises a hard contract — the prompt is trimmed to the seat's
budget — but could not always reach it. Its truncation had a 200-character floor and cut only
**one** section, so when the largest section could not absorb the whole overshoot the prompt stayed
over budget. The connector then raised `FatalError`.

**Fix, both ends.** `compose` now runs the ladder all the way down — short forms, then dropping
the least important sections, then cutting the largest repeatedly, then a hard cut of the assembled
text — and the connector trims rather than aborting the run. `prompt_budget` no longer advertises
room the command line does not have (its 4000-char floor could exceed the real capacity).

### 4.4 Foreign actions could apply twice (medium)

No `action_id` or effects ledger existed. An action's effects (propaganda, positions, costs,
reputation) were applied with no record of having been applied.

**Fix.** Deterministic `action_id` from `(actor, month, kind, slot)`, chosen so a replayed month
derives the *same* id — a random id would let a duplicate through with a fresh identity. The
ledger stores the real delta each action moved, not a description of one.

### 4.5 Codex `invalid_json_schema` — investigated, already fixed

An archived run showed Codex rejecting the output schema (`required` missing `action_type`).
Investigation showed `strict_schema` in the current tree already rewrites `required` to include
every property. **No change was needed** and no change was made; recorded here so the finding is
not re-investigated.

---

## 5. The causal world model

New module `karamaniya/causality.py`, integrated into `economy.py`, `society.py`, `engine.py`.
Full detail in **`docs/CAUSAL_WORLD_MODEL.md`**.

**Implemented and live:**

- **Structural parameters per seed** — thirteen coefficients drawn from calibrated bands, fixed for
  the world's lifetime, recorded in the manifest, **hidden from agents**. This is what makes the
  same policy not optimal in every world, which is the precondition for benchmark value.
- **Output gap and potential output** — potential is a slow stock, grown by the world's structural
  productivity rate less war and unrest damage; it does not jump on a bad harvest.
- **Okun's law** for unemployment, level-anchored and persistent. The brief's literal
  growth-rate form has no level anchor — a permanently depressed economy would drift toward *low*
  unemployment because the gap stopped changing — so the level relation is the target, reached
  gradually.
- **Hybrid inflation expectations**, credibility-anchored. Credibility is earned from the record
  (low inflation, no monetisation, reserves held), never asserted; money financing erodes it.
- **Multi-channel inflation** with a recorded decomposition: the money channel, food and goods
  relative prices, demand pressure, exchange-rate pass-through, excess wage growth, import shortage,
  expectations.
- **Lagged fiscal impulse and a state-dependent multiplier.** A material change in spending is
  scheduled at the fiscal lag offsets and the arriving instalments are scaled by the multiplier into
  utilisation. Verified live: the same +0.03 impulse yields **+3.3%** demand support in deep slack
  and **+0.6%** when already overheating.
- **Regime labels** — descriptive only, never attached to a scripted response, with a supply crisis
  named ahead of the inflation it causes.
- **Causal trace** — every month records *why* inflation moved, with named contributions, so a
  reader can distinguish model failure from world dynamics from engine bug. Research only.

**Calibration is grounded, not invented.** Okun's slope sits inside Ball/Leigh/Loungani's −0.14 to
−0.85. The multiplier bands bracket Auerbach–Gorodnichenko's 0–0.5 (expansion) and 1–1.5
(recession). Pass-through sits inside the IMF's range of consumer-price estimates. The document
states plainly that these are **modelling assumptions calibrated to plausible ranges for a
fictional island, not measurements of any real country**, and cites sources for shape and range
only.

**What was deliberately not done:** no demand-determined output closure, no sectoral input-output
model, no DSGE or CGE structure. Brief §40 forbids it and the architecture does not support it.

---

## 6. Provenance, reproducibility, error taxonomy

**Provenance** (`provenance.py`) — six layers kept apart: `RAW_SOURCE`, `PRESS_REPORT`,
`PRESS_INTERPRETATION`, `AGENT_BELIEF`, `PUBLIC_BELIEF`, `CANONICAL_FACT`. The raw source is
stored once and never rewritten; the canonical fact is derived from the raw source only. Journalistic
distortion is a *feature* (a public that only sees accurate reporting cannot be misled) — what is
forbidden is the engine forgetting which layer it is reading. Allegations start `ALLEGED` and move
only on evidence; `promote_to_fact` **raises** rather than silently promoting, so there is
deliberately no API that turns an allegation into canonical state.

**Reproducibility** (`manifest.py`) — every run writes `runs/<name>/manifest.json` before its first
call and refreshes it at the end. It records the seed and the derivation of every seeded stream,
prompt/psychology/schema/engine versions, the world's true structural parameters, the seat lineup,
sampling settings, and **the models that actually served each seat** — read from the call log, not
the config, because a label is not evidence of what replied. It does **not** claim model
determinism; it says so explicitly. `divergences()` names the axis on which two runs differ, so a
batch reader is not left guessing whether a comparison is fair.

**Randomness audit.** Every stochastic draw in the package goes through `rng_for(seed, month, tag)`
or `random.Random` on a fixed/seed-derived value. **There are no unseeded random calls.**

**Error taxonomy** (`errors.py`) — 30 registered codes with category and severity. Every motion
rejection and execution block now records a structured entry on the world. A code outside the
taxonomy is stored as `UNREGISTERED_ERROR_CODE` with the attempted code preserved, and a test
asserts this never happens in a real run — so a newly invented failure cannot masquerade as a known
one.

---

## 7. Log mining (the brief's final-verification pass, made reusable)

`tools/scan_runs.py` was written for this and is now part of the repo. It separates **faults**
(the engine broke a rule about itself) from **signals** (something the engine flagged deliberately).

Across **88 runs, 11,260 calls and 962 simulated months**:

- **Zero state faults.** No NaN, no negative reserves/debt/arrears/army, no counters running
  backwards, no motion without a canonical status, no integrity warnings.
- Eight runs with infrastructure call errors — session limits, provider quotas, and the Cline
  prompt-length bug now fixed. None were engine faults.
- Signals recorded deliberately: 35 retried calls, 29 format retries, 16 empty/unserved calls.

---

## 8. Test results

```
python -m unittest discover -s tests -t .
Ran 533 tests in 44s
OK
```

358 before this session → 533 now. **175 new tests**, across:

| File | Tests | Covers |
|---|---|---|
| `test_errors.py` | 13 | taxonomy completeness, no state mutation, unregistered self-policing, save/load |
| `test_foreign_idempotency.py` | 10 | action identity, duplicate refusal, distinct actions still apply |
| `test_provenance.py` | 24 | the brief's exact example, raw immutability, allegation statuses |
| `test_leak_provenance.py` | 7 | end-to-end through a real `Council` |
| `test_causality.py` | 58 | parameters, lags, regimes, expectations, multiplier, Okun |
| `test_causal_economy.py` | 29 | the brief's §43 qualitative sanity list |
| `test_prompt_budget.py` | 16 | budget is a hard contract; connector cannot abort a run |
| `test_manifest.py` | 18 | contents, comparability, served models from the log |

**Verification run, not just tests:** a two-seed scripted simulation smoke test
(`simulate council.scripted.toml --runs 2 --months 6`), all five scenario pressure tests (A–E,
including a democratic handover in E), and the full scan above. Logs were inspected by hand.

---

## 9. Behaviour-changing changes

These alter simulation output. Runs are not comparable across this boundary.

1. **Unemployment is persistent** (Okun) rather than read off current utilisation. A slump that ends
   no longer restores employment immediately.
2. **Productivity now scales actual output**, not only potential.
3. **Fiscal spending changes have lagged demand effects** scaled by a state-dependent multiplier.
4. **Exchange-rate depreciation has lagged pass-through** into consumer prices.
5. **Expectations are credibility-anchored** rather than purely adaptive.
6. **Leaked hedged warnings no longer register as plots**, so `plot_exposed` fires far less often —
   trust and reputation effects that previously fired wrongly do not.
7. **Foreign action effects can no longer double-apply** on a replayed month.
8. **Cline prompts may be trimmed** where they previously killed the run.

## 10. Data and schema changes

- `World.audit_errors` — new list field (defaults empty; pre-taxonomy checkpoints load fine).
- `World.institutions["provenance"]`, `["structural"]`, `["pending_effects"]`, `["causal_trace"]` —
  new keys inside the existing dict; no migration needed.
- `World.foreign["effects_ledger"]` — new key.
- `Economy` gained 12 fields, all with defaults.
- `runs/<name>/manifest.json` — new artefact, additive.
- `WORLD_ENGINE` 2 → 3.

All are additive with defaults. Archived checkpoints load without migration — verified by scanning
all 88.

## 11. Remaining known limitations

1. **Output is supply-determined.** Demand support moves utilisation, not capacity. No
   `output = min(supply, demand)` closure. The largest simplification.
2. **`fx_pressure` does not drive `e.fx`.** `fx_step()` is implemented and tested but not called by
   the engine; the currency's price remains anchored to the zone price relation, because the
   currency-launch continuity guarantee is a tested invariant and wiring this carelessly would break
   it.
3. **Regimes do not modulate coefficients.** Persistence and the multipliers are drawn per world,
   not per regime, so the model does not become more nonlinear in a crisis.
4. **Only the fiscal lag channel is wired.** The registry is general; the other five profiles are
   declared but those channels reach prices through existing partial adjustment.
5. **Agent forecasts (brief §37) are not implemented.** Deferred deliberately rather than
   half-built; it needs prompt-surface changes that risk the whole deliberation flow.
6. **Regional logistics recover in one month** on dilemma resolution rather than ramping, producing
   a visible step in output and a ~4% GDP oscillation. Pre-existing (confirmed identical in the
   baseline commit), not introduced here.
7. **No sectoral input-output structure.** Agriculture, industry and services do not purchase from
   one another.
8. **Corruption's economic channels are thin** — tracked and fed into implementation, but
   procurement cost inflation and quality loss are not modelled.

## 12. Suggested next experiments

1. **Ten-seed homogeneous benchmark** (Claude fills all five seats) — see §13.
2. **Seat swap at fixed seed and world**, to separate model behaviour from office.
3. **Forecast calibration** — record agents' stated predictions and score them against outcomes.
   This is the natural home for brief §37 and would be the strongest research addition.
4. **Parameter discovery** — do agents learn their world's structure? Give them only outcome
   history. If the engine is right, a good model should converge on the true pass-through while a
   poor one does not.
5. **Crisis-state nonlinearity**, if limitation 3 is lifted — test whether agents distinguish
   "inflation from money" from "inflation from supply".

## 13. Running a 10-seed homogeneous Claude batch

Claude fills all five seats; only the seed varies. Use a config whose five seats are all Claude.

```bash
# 1. Confirm every seat answers before spending anything.
python -m karamaniya check council.example.toml

# 2. Ten seeds, 36 months, same lineup held fixed across seeds.
for s in 1 2 3 4 5 6 7 8 9 10; do
  python -m karamaniya run council.example.toml --name claude-homo-seed$s --seed $s --months 36
done
```

To hold the *world* fixed while varying only the seed's stochastic draws, keep `--seed` constant and
vary `--prefix`; to compare like-for-like, check each run's `runs/<name>/manifest.json` and confirm
`divergences()` is empty apart from `last_run_seed`.

```bash
python -m karamaniya simulate council.example.toml --runs 10 --months 36 --prefix claude-homo
```

For a scripted dry run of the same shape at zero cost:

```bash
python -m karamaniya simulate council.scripted.toml --runs 10 --months 36 --prefix dryrun
```

For the heterogeneous comparison, use `council.example.toml` (five different models) and compare
each run's manifest against the homogeneous batch.

**Cost note.** A 36-month five-seat run makes roughly 375–555 council calls, plus founding
diagnoses, government formation, the questionnaire and monthly foreign cabinets. Ten seeds is a
long batch; run `check` first and mind subscription limits — the runner pauses rather than letting
a seat silently skip a turn.

---

## 14. The one thing to know

The engine now refuses to let a rejection, a distortion or an allegation become canonical state by
accident. A hedged warning is not a plot; a press framing is not the source; an allegation is not a
fact; a passed motion is not an executed one; a promised compliance is not compliance; a model label
is not evidence of which model replied. Interesting politics should emerge from the world, and the
world is now harder to fool.
