# Calibration: are the dynamics plausible on every seed?

The engine watch (`karamaniya/watch.py`) flags a broken month inside one run. It cannot see a bias that every run
shares. Inflation that creeps up on every seed, or neighbours whose economies shrink with no war, looks ordinary in any
single run and is obvious only across runs. The calibration harness is the check across runs. It plays many seeds under
simple councils, computes a fixed set of figures for each finished world, and says where those figures leave their
plausible ranges, before a model council is spent on a world that is already off.

The evidence is run 20261010-070501-seed1. An engine bug charged every statement and offer of talks by a neighbour's
cabinet against that neighbour's real output, and kept charging it. The neighbours lost about 30% of their output in
nine months, and prices across the shared crown rose 42%. It took nine months and a counterfactual run by hand to find.
The `rival_output_drift` check is aimed at that failure: a neighbour whose output falls 4% a month for nine months ends
at about 69% of its start and fails it (`tests/test_engine18_calibration.py` reproduces the fall).

Files:

- `karamaniya/calibration.py`: the checks, their ranges and reasons, and the one-council run they judge.
- `tools/calibrate.py`: the command that plays the grid and prints the table.
- `tests/test_engine18_calibration.py`: a small grid, and each check on a passing and a failing history.

## What is checked

Each check is one figure from a finished world, with the range a plausible world stays inside. A figure outside its
range fails that run. The reason beside each range is the one in `calibration.py`; change a range only with a written
reason next to it there and here.

| Check | Figure | Range | Why this range |
| --- | --- | --- | --- |
| `inflation_mean` | mean of the yearly inflation rate over the run | -2% to 40% | Sustained deflation past -2%, or inflation above 40% a year, means the price level has drifted rather than the economy moved. |
| `inflation_monthly_peak` | largest one-month rise of the zone's price level, in months with no war and no printing | at most 6% | The engine watch flags a rise above 2% in such a month (`watch.INFLATION_LIMIT`); 6% is the outer bound. |
| `unemployment_mean` | mean unemployment over the run | 2% to 30% | The founding classes start at 2% to 6% (`world.py`); an average outside 2% to 30% is a structural break. |
| `approval_final` | approval in the last month | 10% to 85% | Near-universal rejection or acclaim is not a state a seed should produce by default. |
| `output_final` | real output in the last month, against its start | 0.55 to 1.50 | A fall to 55%, or a rise to 150%, in three years is a structural break, not a business cycle. |
| `food_ratio_mean` | food available over food needed, averaged over the run | at least 0.70 | Under 70% for a whole run is a famine, not a bad harvest. |
| `emigration_share` | people who emigrated over the run, over the population at the first month | at most 15% in 36 months | An exodus. Shorter runs get the same rate pro rata (12 months: 5%). |
| `rival_output_drift` | the neighbour furthest from its start: real output at the end over its start | 0.75 to 1.25 | Only judged in a run without war. The engine-15 bug lost about 30% in nine months, so a move past 25% either way is more likely a charge the engine made than a development. |
| `army_size_bounds` | the month whose army is furthest outside 5,000 to 200,000 | 5,000 to 200,000 soldiers | 5,000 is a token force for about 4.7 million people; 200,000 is about twice the 100,000 the evidence run set against its 28,000 (`resolve.py`). |

How the figures are taken:

- The checks read every month the run played, as `baseline.summary` does. A run that played past its configured length to
  carry out a handover (`engine.py`) is judged over that extra month too.
- `inflation_monthly_peak` leaves out the months with a war, and the months in which Karamaniya or a neighbour in its
  zone printed money (the test `watch.py` uses). A month of printing can move prices for reasons the check does not
  describe, so it is not held to 6%.
- `rival_output_drift` reads each neighbour's output at the end of the run. A fall that had recovered by then is not seen
  by this check. The monthly path of each neighbour is in the JSON report.
- `rival_output_drift` does not apply to a run with a war in any month. A war moves a neighbour's output for reasons
  the ranges do not describe. The table counts such runs as "skipped", not as passed.
- `army_size_bounds` looks at every month, and `rival_output_drift` at every neighbour. Each reports the figure that
  decides the verdict: the one nearest an edge of its range, or furthest outside it.
- `emigration_share` uses the population at the first month as its starting population. On the seeds checked that is
  within about a hundredth of a per cent of the population at the start of the run.
- `inflation_mean` reads the consumer price index (`infl_yoy`), not the zone's general price level. The index puts 40%
  of its weight on food (`economy.py`), and food's price relative to everything else falls while food supply runs
  above need. A food surplus can therefore take the index below -2% a year while the zone's prices rise. When this check
  fails, read the food ratio (`food_ratio` in the JSON's monthly series) and then the run's history rows, which record
  both the index (`cpi`) and the zone's price (`zone_price`), before the money.
- A slow fall stays inside a wide range. `rival_output_drift` allows a neighbour to lose a quarter of its output, so a
  neighbour that loses a few tenths of a per cent a month still passes. Read the figure in the table, not only the pass
  count.

## How to run it

```bash
python tools/calibrate.py --seeds 1-10 --months 36 --modes passive,scripted,hawk,dove
python tools/calibrate.py --seeds 1-6 --months 36 --modes passive,scripted,hawk,dove --out calibration.json
python -m unittest tests.test_engine18_calibration
```

- `--seeds` takes a range (`1-10`) or a list (`1,3,7-9`). `--modes` takes any of `scripted`, `passive`, `hawk` and
  `dove`; the default is all four. `--months` is 36 unless you say otherwise.
- Each seed and council is one run, played in a temporary folder. No model is called. The run settings are those of
  `council.scripted.toml`, with survey and baseline off. The councils are those of `baseline.py`:
  `scripted` is the five rule-following stand-ins, `passive` a council that tables nothing, `hawk` and `dove` five seats
  of one persona each.
- The exit code is 0 when every check passes in at least 90% of the runs it applies to, and 1 otherwise. A run that
  raises an error is a failed run for every check, and makes the exit code 1 whatever the shares.
- `--out` writes every figure, run by run, as JSON: the figures and their ranges, the monthly series of the run, and each
  neighbour's output month by month.
- The table ends with the time taken, per run and in all, which is what the next grid should be sized from.

## Reading the table

Each row is one check.

- **range** is the bound the figures are judged against, at the run length the grid used.
- **passed** is the number of runs inside the range, over the number of runs the check applied to.
- **skipped** counts the runs the check did not apply to: runs with a war, for `rival_output_drift`, and runs in which
  every month had a war or printing, for `inflation_monthly_peak`.
- **smallest, median, largest** are the figures over the runs the check applied to.
- **worst run** is the run whose figure is nearest its range's edge, or furthest outside it. It names the seed and the
  council, so the run can be reproduced.
- **not assessed** means no run qualified for the check. The exit code is 1 for that, because nothing has been shown.

A check at 90% or more of its runs passes. A table that passes is evidence that the engine's dynamics are inside these
ranges on the grid it was run on. It is not evidence that the world is right. The ranges are only plausibility bounds.

## When a check fails

Investigate first. Never widen a range to make a failing run pass.

1. Find the run in the JSON (`runs`, by seed and mode) and read its monthly series for the check. Find the first month
   where the figure moves away from its usual path. For `rival_output_drift`, read `rivals_monthly`.
2. Look at the engine watch for that run: `w.institutions["engine_watch"]` holds the flags it raised, with the month and
   the mechanism. A flag at the same month is the same finding from a second source.
3. Compare the passive council on the same seed. If the passive run moves the same way, the cause is the world, not
   the council. If only the active councils move, the cause is what they do, and the stand-ins' rules are the thing to
   read.
4. Decide which of two things is true. If the engine computes something wrong, fix the engine, add a test that fails
   on the bug and passes on the fix, and do not touch the range. If the range does not fit what a plausible world does,
   change the range, and write the reason beside it in `calibration.py` and in this file, with the evidence (a run, a
   source, a calculation). A range change with no reason written next to it is not allowed.
5. Re-run the grid and the test file, and say in the commit which checks moved and why.

A check that fails on one seed out of ten, with a reproducible cause, is a finding. A check that fails on most seeds
of one council is usually that council's behaviour, not the world. Both are worth reading before anything is changed.

## What the grid cannot see

- Only the seeds and councils it plays. A bias that needs a seed outside the grid is not caught until that seed is run.
- Councils of stand-ins, not models. A model council can move the figures in ways the stand-ins never do; the checks
  are meant for the world, and a model run should be compared with the same seed under the same stand-ins.
- The checks are judged on the figures the run records. A dynamic that is wrong but never shows in those figures is not
  caught by them.
- `inflation_monthly_peak` judges only the months without war or printing. The scripted, hawk and dove councils printed
  in almost every month of a 36-month run on seeds 1 and 2 (29 to 35 months of 37), so for them the check sees few
  months. A jump caused by printing is excluded by design; read the monthly series when a run prints heavily.
- The first full grid (engine 18, before its release) found Dorsania's output falling in a straight line to 0.892 of
  its start in 36 months, on every seed and council. It was an engine bug: the stand-in Dorsania asked to ease a
  grain embargo that stood at zero in every month, and each ask was charged against its output for good
  (`foreign.EMBARGO_COST`, `tests/test_engine18_embargo.py`). The range did not catch it, since 0.892 is inside
  0.75 to 1.25; the identical straight line on every run did. Read the figure against the range, and read the
  spread too: a figure that is the same on every seed and council is a rule at work, not luck.
