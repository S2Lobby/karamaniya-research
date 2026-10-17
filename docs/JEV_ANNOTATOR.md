# Jev as annotator 2

Wave 3, worker C. Base commit `86c07d0` (engine 26), branch `wave3/jev`. Tool: `tools/jev_annotate.py`.
The labels and the rules are in `docs/EXIT_AUDIT_CODEBOOK.md`; the detector labels it re-audits are in
`docs/detector_labels/` and `docs/DETECTOR_PRECISION.md`.

No real TypeSafe call was made in this work. The key is read from `TYPESAFE_API_KEY`; the tool never prints, logs or
stores it. Every call path in this document was exercised against `tests/stub_servers.py`'s fake endpoint, whose
answers are fixed. The tests use a sentinel key and assert it never appears in the output.

## 1. What it does

`tools/jev_annotate.py` has two commands.

- **`sample`** reads the CSV that `python tools/exit_audit.py sample` draws. For each row it asks Jev the codebook
  question once, as a Choice of `substantively_supported`, `ambiguous` or `formatting_or_parser` (the brief's
  supported / ambiguous / parser), with the definitions from `docs/EXIT_AUDIT_CODEBOOK.md` section 3 as criteria. It
  writes a copy of the sheet with the second label, the probabilities, the confidence and the resolved model id.
- **`reaudit`** asks the same kind of typed question of the D1 and D2 rows in `docs/detector_labels/`, using
  `docs/DETECTOR_PRECISION.md`'s label definitions, and reports Jev's agreement with the single annotator before and
  after the T144 fixes.

Both commands go through `karamaniya/backends/systemone.py` (`SystemOneBackend`), which speaks the System One HTTP
contract (`POST {base_url}/v1/systemone`, Bearer `TYPESAFE_API_KEY`). A small subclass, `AuditingSystemOne`, adds the
contract's Choice confidence as a numeric field; the base class records it only inside the free-text `reason`
(`systemone.py:114`). No engine or backend file is changed.

## 2. Usage

```
python tools/exit_audit.py extract research/runs/*/ --out events.jsonl
python tools/exit_audit.py sample events.jsonl --seed 1 --other 60 --out sample.csv
python tools/jev_annotate.py sample sample.csv --out sample.jev.csv

# Through OpenRouter's Decisions API (same request contract, same input-only price):
python tools/jev_annotate.py sample sample.csv --openrouter --limit 3 --out sample.jev.csv

python tools/exit_audit.py agreement sample.csv sample.jev.csv --col-b annotator_2
```

`--openrouter` uses `https://openrouter.ai/api/alpha` and the `/decisions` path, reads the key from
`OPENROUTER_API_KEY` instead of `TYPESAFE_API_KEY`, and defaults the model to `typesafe/jev-latest`. `--base-url`
overrides the base (the tests point it at the stub), `--dry-run` builds the requests and prints the estimate without a
key, and the key is never printed. The OpenRouter path is covered by a stub test that asserts the path, the bearer
header and the model id.

The pre-registered sample is seed 1 and 60 non-exit events, with every exit included. The recorded runs give 20
exits, so the sheet has 80 rows.

```
python tools/jev_annotate.py reaudit --labels-dir docs/detector_labels --out-dir docs/detector_labels \
    --runs C:/Users/litle/Karamaniya/research/runs
```

`reaudit` reads the evidence and label CSVs, writes `D1_jev_labels.csv` and `D2_jev_labels.csv` into `--out-dir`, and
prints the agreement lines. `--runs` is read-only input for the current D2 rule; a missing folder is reported, never
created.

Useful options on both commands: `--model` (default `jev-latest`), `--base-url` (default the hosted API; tests point
it at the stub), `--timeout`, `--retries`, `--dry-run`. `sample` also has `--limit N` for a paid trial of N rows.

## 3. Blind protocol

The codebook's reading rule is "read the raw answer, not the engine's text" (section 3.4). The second annotator is
blind to the engine's own reading and to the first annotator's labels. `build_state` sends:

- the event facts: event id, run, month label, event type, exit class, `is_exit`, member, office, motion id and type;
- `raw_answers` in full, every phase, with nothing cut;
- `state_change`, the fields recorded against the row;
- `engine_flags` and `parser_checks`, which the codebook tells the annotator to use.

It leaves out:

- `parsed`, the engine's own reading (the resign flag, election response, coup action or motion fields);
- `raw_reading`, the audit tool's machine extraction of the operative tokens;
- `annotator_1`, `annotator_2`, `adjudicated` and `notes`.

Consequence, stated in the tool and here: F2 ("the engine read something the answer does not say") is judged from the
raw token and the parser checks, not from `parsed` itself. A raw `"resign": "true"` is visible as a string in the
answer; a coup action mismatch is visible where the parser check quotes both readings.

For the re-audit, `build_d1_state` sends the flag id, run, month, member, field, flagged metric, the engine's claim
text, the claimed and observed values, how the figure was located, whether the decision prompt was recorded, the
sentence and the briefing lines. `build_d2_state` sends the flag id, run, month, member, motion fields, tally, the
final vote, the recorded stance and its source, the vote condition, the full reason and the month's statement. Neither
state contains the single annotator's label or reason.

## 4. Fields written

The `sample` output keeps every input column (including `annotator_1`) and adds:

| Column | Meaning |
|---|---|
| `annotator_2` | the Choice's top option, in the codebook spelling |
| `annotator_2_probabilities` | the contract's probability map, as JSON |
| `annotator_2_confidence` | the contract's Choice confidence, as a number |
| `annotator_2_model` | the response's resolved model id (`model`, not the alias sent) |

Because `event_id` is preserved, the output joins directly with `exit_audit.py agreement`; the tests run that join.
`reaudit` writes the same four columns plus `flag_id` and `annotator_1`, one sheet per detector.

The backend lowercases the contract's choice (`systemone.py:117`). The exit labels are lowercase already; the D1/D2
labels are upper case, so the tool matches case-insensitively and writes the report's spelling. An answer outside the
label set is an error, never a label; the run stops with the row id and writes no sheet.

## 5. Cost estimate

The estimate is printed before any call:

```
Cost estimate (input tokens only; output is free; approximate, characters/4): N rows, ~LOW-HIGH tokens per request
(TOTAL total); at $0.042 per Mtok = $X.
```

The rule is `tokens = (len(state) + len(question JSON)) / 4` per request, one question per request. The price is
`SystemOneBackend.price_in_per_mtok` ($0.042 per Mtok, input only; output is free). It is approximate because the
repository has no tokenizer. After the run the tool prints the provider's reported input tokens and cost, and the
estimate, so the two can be compared. A request estimated above 30,000 tokens (the contract's 32k bound for state
plus the longest question) stops the run before any call.

Measured estimates, from the two dry runs in this work:

| Run | Rows | Estimated input tokens | Estimated cost |
|---|---|---|---|
| Exit-audit sample (20 exits + 60 non-exit, seed 1) | 80 | 260,706 | $0.010950 |
| Re-audit D1 | 51 | 22,905 | $0.000962 |
| Re-audit D2 | 36 | 12,137 | $0.000510 |

The exit sample's states include every raw answer, so the per-row estimate ranges from about 800 to about 6,100
tokens. The re-audit states are shorter (about 300-500 tokens). The whole task is under two cents at the published
price.

## 6. Dry run

`--dry-run` builds every state and question, prints the estimate and the first request, sends nothing, writes
nothing, and needs no key. The runs are read-only input for `exit_audit.py extract`.

```
$ python tools/jev_annotate.py sample "$TMP/sample.csv" --dry-run
Cost estimate (input tokens only; output is free; approximate, characters/4): 80 rows, ~797-6094 tokens per request (260706 total); at $0.042 per Mtok = $0.010950.

Dry run: 80 rows. No request was sent. The blind state and the question for the first row follow.

--- state (what Jev would see) ---
EXIT-EVENT AUDIT ROW (one apparent exit, or one executed or refused motion)

event id: 20261011-211521-seed1|m6|motion_refused|A
run: 20261011-211521-seed1
month: Month 7
event type: motion_refused
exit class: motion_refused
is an exit: False
member: A
motion type: diplomacy

RAW ANSWERS (verbatim; every phase the engine recorded):
--- A session 6.139
{"communications":[],"information_requests":[...],"motions":[...]}
...
--- question ---
{
  "criteria": {
    "ambiguous": "Not F1-F4, and any of: A1 ... (a bare \"resign\": true with ordinary notes is A1); ...",
    "formatting_or_parser": "F1: ... F4: ...",
    "substantively_supported": "Not F1-F4 and not A1-A4. ..."
  },
  "id": "exit_label",
  "kind": "choice",
  "options": ["substantively_supported", "ambiguous", "formatting_or_parser"],
  "text": "You are the second annotator of an exit-event trace audit. ..."
}

The blind state leaves out: parsed (the engine's reading), raw_reading, annotator_1, annotator_2, adjudicated, notes.
With a key in TYPESAFE_API_KEY, this run would write .../sample.jev.csv.
```

The state above is abridged at the long raw answer; the run itself prints it in full. The actual first row is a refused
motion because the sample is ordered by the seed's hash, not by exit class.

### Stub-server demonstration

The HTTP path was run against `tests/stub_servers.py`, with a fixed reply and a placeholder key, on three real sample
rows:

```
$ python "$TMP/stub_demo.py" "$TMP/sample.csv" "$TMP/sample.jev.csv"
Cost estimate (input tokens only; output is free; approximate, characters/4): 3 rows, ~2858-3559 tokens per request (9314 total); at $0.042 per Mtok = $0.000391.

Wrote 3 rows to .../sample.jev.csv; resolved model: jev-stub-1.
Actual usage reported: 15000 input tokens, $0.000630 (the estimate was $0.000391).
Labels: {"ambiguous": 3}
exit code: 0
20261011-211521-seed1|m6|motion_refused|A | ambiguous | {"ambiguous": 0.6, "formatting_or_parser": 0.2, "substantively_supported": 0.2} | 0.5 | jev-stub-1
20261012-225146-seed1|m0|motion_executed|M5 | ambiguous | {"ambiguous": 0.6, "formatting_or_parser": 0.2, "substantively_supported": 0.2} | 0.5 | jev-stub-1
20261008-130316-seed1|m18|voted_out|C | ambiguous | {"ambiguous": 0.6, "formatting_or_parser": 0.2, "substantively_supported": 0.2} | 0.5 | jev-stub-1
```

The stub gives the same answer to every question; these labels demonstrate the second column, the probabilities, the
confidence and the resolved id, not Jev's judgement. No real call is made by this or any test.

## 7. The re-audit method

The re-audit asks the D1 and D2 questions of every row that already carries the single annotator's label, then
compares Jev's label with that label with the same statistics as `exit_audit.py agreement` (exact agreement, Cohen's
kappa and Krippendorff's alpha, from `exit_audit._kappa_alpha`).

Rows and row sets:

| Set | Rows | What it is |
|---|---|---|
| D1 sample (recorded flags, before T144) | 40 | `D1_labels_sample40.csv`, the pre-registered sample of the recorded flags |
| D1 replay-labelled remainder (after the replay) | 11 | `D1_labels_replay_unsampled11.csv`, flagged by the replay and labelled separately |
| D1 all labelled rows | 51 | the two files above |
| D1 current fixed check (after T144) | 0 | rows in `D1_replay_current_main.csv` with `replay == "flagged"` |
| D2 recorded stance flags (before T144) | 36 | `D2_labels_36.csv` |
| D2 current reason rule (after T144) | 0 | `council._reason_contradictions` over every yes/no ballot in the runs |

Verified on this branch (engine 26, no model call):

- `python tools/detector_audit.py score` prints `D1 on the current code (replay, same metric): {'labelled': 0, ...}`
  and the replay CSV is 121 `unverifiable` + 16 `clear`, so the fixed D1 check flags 0 of the 137 recorded texts.
- The same command prints `D2 (precision: TRUE_MISMATCH of decided): ... decided: 35 ...` for the recorded flags, and
  `tools/detector_audit.py reason-check` prints `ballots yes or no in the recorded runs: 1517; flagged by the reason
  rule: 0`. `jev_annotate.current_d2_flags` re-reads the same rule with a caller-chosen runs folder and gives
  `{'ballots': 1517, 'flagged': 0}`.

So on the final T144 code there are no post-fix flags to label: the fixes removed the flags rather than relabelling
them. The re-audit reports the before-T144 agreement (40 D1 rows and 36 D2 rows), the replay-labelled 11, and the
empty after sets. `docs/DETECTOR_PRECISION.md` section D1b still says 19 texts are flagged; that text predates the
final T144 commit `23698ed`, which changed untied figures to `unverifiable`. The current counts above are the ones to
quote.

The user runs the real calls with their own key. On the stub, the agreement arithmetic is exercised end to end; those
numbers are plumbing checks, not evidence about Jev.

## 8. Tests

```
python -m unittest tests.test_jev_annotate tests.test_engine24_exit_audit tests.test_detector_audit -v
```

18 tests in `tests/test_jev_annotate.py`, 60 in the three modules together, all passing on this branch. The tests
cover the blind state, the question shape and criteria, the estimate rule, the oversize guard, the dry run (no key,
no request, no output), the stub run (label, probabilities, confidence, resolved model, the key never printed), the
invalid-answer and refused-request paths, the input checks, the agreement arithmetic, and the re-audit on a synthetic
label folder.

## 9. Limits

- No real call was made; Jev's labels and the real agreement numbers do not exist yet. Everything above is the tool,
  the stub path, the estimates and the row counts.
- The blind state withholds `parsed`, so F2 is judged from the raw token and the parser checks. If the user prefers
  the annotator to see the engine's reading, that is a one-line change in `build_state`, but it would break the
  protocol this work was asked to implement.
- The cost estimate assumes four characters per token; the provider's reported usage after a real run is the figure
  to record.
- The D1/D2 re-audit compares against one annotator's hand labels. Agreement with Jev does not make those labels
  correct; it measures whether a second, independent reader reaches them.
