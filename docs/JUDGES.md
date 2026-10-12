# Judges: evaluator models that watch a run from outside it

A judge is not a governor. It holds no office, speaks to no delegate, and nothing it answers
changes the world. Once a month the run hands it the same public record the delegates work from —
the country's figures, who holds what, the recent public events — plus a fixed set of *typed*
questions, and files the answer away in the run's log. The point is not another opinion about the
simulation; it is a second measuring instrument. The report scores each judge against what actually
happened, so a number that looks confident and a number that is right are separately visible.

## The questions

The three kinds follow the contract of TypeSafe's decision model, Jev (System One): a judge does
not write prose, it commits to a position with probabilities. The default panel:

| id | kind | the question | how it is scored |
|---|---|---|---|
| `survive_to_end` | choice: yes / no | will the government still be in office at the planned end? | Brier score of its probability of yes, resolved by the run's outcome |
| `how_ends` | choice: handover / collapse / other | how will the run end? | accuracy of its pick against the real end class |
| `crisis_severity` | score, 0–4 levels | how severe is the situation this month? | its mean reading over the run (and how it moves) |
| `enough_evidence` | noul | is the record enough to judge the economy? | how often it honestly says "not enough evidence" |

The questions live in `karamaniya/judges.py` (`DEFAULT_QUESTIONS`); a run can carry its own list in
the council file, and the same shapes are what the System One API itself speaks, so a panel can be
asked of the hosted decision model and of an ordinary chat model with no translation.

## Enrolling one

In the control room: Council tab → **Evaluator models observe the run** → provider, model, how often
to ask. In a council file, the same thing:

```toml
judge = true
judge_backends = [{ provider = "ollama", model = "qwen3.5:9b", label = "judge" }]
judge_every_months = 1
```

Any provider the seats know works — a local Ollama model costs nothing and keeps the panel honest
about latency; `systemone` (below) speaks the Jev API directly. The control room enrolls one judge;
a council file may carry up to three, which is the useful configuration for research: two evaluators
of different families disagreeing about the same month is itself a measurement.

## The systemone provider

`provider = "systemone"` speaks TypeSafe's Jev HTTP contract directly
(`POST https://api.typesafe.ai/v1/systemone`, `TYPESAFE_API_KEY`). The same provider pointed at a
`base_url` drives a wire-compatible open server — the open replications of the interface run the
official SDK unmodified. Chat-model judges go through the panel's emulated path instead: strict
JSON, one repair attempt, the harness's usual habits. The full contract and the open analogs are
noted in `docs/research/jev-contract.md`.

## What lands in the record

* every survey appends a `judge` record to `log.jsonl` and shows in the control room's feed under
  **Judges** — the answer, its probability, and the reason line;
* the scorecard gains a `judges` block: surveys, errors, answer problems, cost, latency, the mean
  severity, the Brier score of the survival probabilities, the end-class accuracy, and the honest
  "not enough evidence" rate;
* a judge failure (unreachable provider, malformed answers) is recorded as a problem and never
  pauses the run. The government keeps governing whatever the judges do.

## Limits, for now

One judge is configurable from the control room; more come from the council file. Judges see the
public record only — there is deliberately no oracle mode yet (giving a judge the true structural
parameters would make its scores incomparable with what the delegates could ever have known).
Custom question sets are read from the council file but not yet editable in the UI.
