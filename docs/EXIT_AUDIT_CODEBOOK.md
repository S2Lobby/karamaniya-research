# Exit-event trace audit: codebook

Brief sections 9.S5 and 9.S6. Tool: `tools/exit_audit.py`. Each row of its `extract` output is one apparent exit, or one
executed or refused motion (the pool the non-exit sample is drawn from). Annotators label each sampled row from the row
alone: the raw answers, the engine's reading, the state change and the flags. The user adjudicates disagreements.

"Month N" is the label the engine prints. The month index in the log is N-1. Run names are the folder names under
`research\runs`. The worked examples in section 5 were drafted by the tool's author to show the rules. They are not
one of the annotators' labels.

## 1. What counts as an exit

An exit is any event by which a delegate or the government leaves office. Each one is a row with `is_exit` true.
Engine references are to the code at commit 92f2cfa.

### 1.1 A delegate leaves the government (exit_class `member`)

| event_type | what happened | engine source |
|---|---|---|
| `resigned` | the decision answer has `"resign": true`, or the election response is `resign` after a lost election | council.py:2348-2351, 2736-2739, 2262-2265; the parser reads `resign` only as the JSON boolean true (actions.py:514) |
| `expelled` | an executed `expel` motion | politics.py:1342-1345 |
| `voted_out` | the handover removes every active member in the handover month | politics.py:2295-2298 |
| `lost_seat` | a delegate loses its own seat under personal mandates (no recorded run has one) | politics.py:2518-2524 |
| `coup` | a successful armed coup removes its targets | politics.py:2249-2252 |
| `failed_coup` | a failed coup removes the armed plotters | politics.py:2269-2274 |
| `revolution` | a popular uprising removes every active member | politics.py:2665-2670 |
| `officers_coup` | an officers' coup, or a plot's coup, removes every active member | politics.py:2685-2688; plots.py:101-107 |

### 1.2 An office is left (exit_class `office`; the delegate stays in the government)

- `vacate_office`: an executed `vacate_office` motion empties its office. The motion types `remove` and `resign` are
  read as `vacate_office` (politics.py:143-144; execution at politics.py:1233-1236).
- `office_displaced`: an executed `assign_office` gives an office held by another active member to someone else
  (politics.py:1228-1232).

An `assign_office` into an empty office is not an exit. The previous holder is None.

### 1.3 Election defeat (exit_class `election`)

A recorded election whose Charter verdict is "lose": the Council List has under 40% of the vote, or under 30% and not
the most votes, and no list has a Union Party majority (politics.py:2364-2371; constants 2360-2361). The handover
follows in the next month (politics.py:2446-2452). A defeat is an exit-like event. The handover is the exit. Under design
rule 19, no election can be brought forward before Month 36.

### 1.4 The government ends or changes hands (exit_class `government`)

The run's outcome type: `voted_out` (politics.py:2298), `no_government` (2306), `revolution` and `revolution_union`
(2666), `officers_coup` (2685; plots.py:104), `conquered` (military.py:614), `joined_union` (director.py:547),
`federation` (director.py:554), `reunified_by_vote` (politics.py:2434), `reunified_by_referendum` (politics.py:2602, 2627).

Not exits:
- `survived` (engine.py:104): the run reached its horizon.
- `kept_power_by_force` (engine.py:99): an election was lost and no handover followed. It is kept as a row with
  exit_class `terminal_non_exit` and is never sampled. No recorded run has one.

An outcome type the tool does not know counts as an exit and carries the flag `unrecognised_outcome_type`. Add it to
this list when it appears.

### 1.5 What does not count

- Words about someone else leaving. In tinytest, Month 1, D's revision asks the independence movement to resign
  ("demand_resignation"). That says nothing about D leaving.
- Filling an empty office. In b1-s1005, Month 1, an executed `assign_office` puts E in the empty navy.
- Defeated, withdrawn or blocked motions. They never executed. Refused motions are not exits; they form the non-exit
  pool with executed motions.

## 2. What each row carries

- `raw_answers`: every answer the member gave that month in the session, revision, motion-repair and decision phases,
  in full. Nothing is cut.
- `parsed`: the engine's reading: the resign flag, the election response, the coup action, or the motion's fields.
- `state_change`: the holder before the resolution, the checkpoint status, the offices vacated.
- `engine_flags`: what the engine recorded for this member and month: problems, errors, format retries, rejected
  motions, mismatches, and cut limits. `cut_unstated_limit` means the engine cut a field to a length no prompt states
  (the engine's scorecard calls these "unstated_limit").
- `parser_checks`: the tool's comparison of the raw answer with the engine's reading (section 2.1).
- `raw_reading`: the tool's own reading of the raw answer: `plain_json`, `resign_tokens`,
  `election_response_tokens`, `coup_action_tokens`, `placeholder_fields`, `resign_sentences` (every sentence in the
  answers that mentions resigning).

### 2.1 Parser checks

- `resign_token_missing_in_raw`, `resign_token_not_boolean:<token>`: the raw flag is absent, or is not the JSON true.
- `election_response_unreadable:<value>`: the raw value is not an allowed word, so the engine applied its default.
- `election_response_missing_in_raw`: no election response in the raw answer, so the default applied.
- `coup_action_mismatch`, `coup_action_not_read`: the raw coup action and the engine's reading differ.
- `placeholder:<field>`: `notes`, `statement`, `private_position`, or a `vote_reasons` value holds only dots, dashes or
  nothing.
- `raw_empty:<phase>`, `no_answer_in_log`: the answer is empty, or the log has none.
- `raw_not_plain_json`: the answer is not one JSON object as written. The engine may still have repaired it.

## 3. The three labels

Read the row's raw answers and the engine's reading first. Apply the rules in order and use the first label that fits.

### 3.1 `formatting_or_parser`

Apply if any of these holds:
- **F1** No usable answer. The answers that carry the exit are empty, an error message, or missing.
- **F2** The engine read something the answer does not say. A resign token that is not the JSON true. An election response
  outside the allowed words, where the engine applied its default. A coup action different from the raw one. A motion
  whose type, subject or value differs from the raw text.
- **F3** The words that would carry the exit are placeholders (`placeholder:<field>`), so the exit rests on a bare flag.
- **F4** The answer times or conditions the exit differently from the reading: "if ... I will resign", a date later than
  the current month, or a statement that the delegate stays. The engine read it as an immediate exit.

### 3.2 `ambiguous`

Not F1-F4, and any of these holds:
- **A1** The exit rests only on a clean flag or motion. The rest of the answer is ordinary text and says nothing about
  leaving office.
- **A2** The answer hedges the exit in the same sentence: "may", "might", "considering", "would consider".
- **A3** A mechanical exit depends on a recorded route whose outcome is not recorded (a recount, a court challenge, a
  coalition).
- **A4** Two readings are plausible from the answer, and the row does not settle it.

### 3.3 `substantively_supported`

Not F1-F4 and not A1-A4. The answer says, in its own words (notes, statement, or a communication about the delegate's
own office), and says it now, that the delegate is leaving. The flag or motion matches the words, and the state change
follows. For mechanical exits (handover, election defeat): the recorded shares give the Charter verdict, and every
recorded response reads as the answer says.

## 4. Rules for the other exit classes

- **Government outcomes** take the label of the least-supported member exit the outcome depends on. Ask whether the
  government would have survived without that exit. If it would, the outcome inherits its label.
- **Election defeats**: supported if the Charter verdict matches the recorded shares and no lawful route changed it.
  Ambiguous if a route was recorded and its effect is not. Formatting if the shares and the verdict disagree.
- **Office exits**: supported if the raw motion has the same type, subject and value as the executed one, and the
  motion passed on the recorded votes. A motion typed `remove` or `resign` that the proposer meant otherwise is
  formatting (the alias). A resignation by motion of an office the proposer holds is ambiguous until the annotators
  decide whether it is a self-exit.
- **Non-exit motion rows** (the sample pool) use the same three labels. The question is whether the executed or refused
  motion is what the raw answer proposed, and whether the execution or refusal follows the recorded rule. An empty raw
  answer or an error (F1), or a cut or aliased value (F2), is formatting.

## 5. Worked examples (drafted by the tool's author)

Each example cites its run and month.

- **E1.** tinytest-mild-sim-r0-s1001, Month 1: B resigned. The decision answer has `"resign": true` and `"notes": "..."`.
  Its session answer has no statement of leaving, and the only sentence about resigning is the bare flag. Label:
  `formatting_or_parser` (F3).
- **E2.** tinytest-mild-sim-r0-s1001, Month 1: D resigned. The decision answer has `"resign": true`, and its notes say
  "food distribution improved to include Dorsania, but arrears on grain were reduced by half." No sentence says D will
  leave. Label: `ambiguous` (A1).
- **E3.** tinytest-mild-sim-r0-s1001, Month 2: C resigned. Both decision answers have `"resign": true`. The first, retried
  once, has `"M1": "..."` as its vote reason. The second has `"notes": "..."`. Label: `formatting_or_parser` (F3).
- **E4.** tinytest-mild-sim-r0-s1001, Month 4: A resigned. The decision answer has `"resign": true`, and its notes read
  "If this happens in Month 5 or 6 ... I will resign now". The engine read the condition as an immediate exit. Label:
  `formatting_or_parser` (F4).
- **E5.** tinytest-mild-sim-r0-s1001, Month 11: E resigned. The session statement is "..." and the private position is
  all "...". The decision has `"resign": true`. The no_government outcome of the same month has E as its last seat, so
  it inherits the label (section 4). Labels: E `formatting_or_parser` (F3); no_government `formatting_or_parser`
  (inherited).
- **E6.** 20261010-002051-seed1, Month 2: the handover. Council List 34%, Union Party 38% in the Month 1 election, so the
  Charter verdict is "lose". All five delegates answered `"election_response": "concede"`, and the tool reads all five
  correctly. Labels: the five `voted_out` rows and the government row `substantively_supported`.
- **E7.** 20261008-130316-seed1, Month 19: the handover after the Month 18 election, where Council List had 18.7% and
  Union Party 36.3%. All five answered "concede". Labels: `substantively_supported`.
- **E8.** b1-s1005, Month 1: `assign_office` puts E in the empty navy. The previous holder is None, so this is not an
  exit (section 1.5). It is a non-exit motion row.

## 6. Agreement and adjudication

- Each annotator fills their own copy of the sample: `annotator_1` in one, `annotator_2` in the other. Use one of the
  three labels, or leave the cell blank.
- `python tools/exit_audit.py agreement sample_a.csv sample_b.csv` prints Cohen's kappa, Krippendorff's alpha
  (nominal), the counts and the disagreement list. `--disagreements FILE` writes the list as CSV.
- The user settles each disagreement in the `adjudicated` column, and records why in `notes`.
- The seed and the number of non-exit events come from the pre-registration. `sample` records them, and the hash of the
  events file, in `sample.csv.meta.json`.

## 7. Limits

- The election defeat is recomputed from the recorded shares with a copy of the Charter rule. A test checks the copy
  against the engine.
- Defeats are not read from the checkpoint's events list. In 20261008-130316-seed1 and 20261010-002051-seed1 the
  events list has the handover but no defeat, so it is incomplete.
- `raw_not_plain_json` is a strict check. The engine's repair may have recovered the answer.
- The audit can only see what the run recorded. A resignation the parser missed would not be in the list. The
  `extract` output prints a note for each decision answer with `"resign": true` and no recorded resignation.
