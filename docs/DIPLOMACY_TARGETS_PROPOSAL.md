# Diplomacy targets: the act-target table

A proposal for the user, from the E7 task (engine 24 work, branch `haiku/diplomacy-targets`).

**The table is not changed.** Which acts a country can take with which neighbour is a design decision, and a menu nudges
the models (design rule 25). What this branch does change is the refusal. When a delegate writes an act that its target
does not receive, the refusal now names the acts that target does accept. That text reaches the models, so it needs an
AGENT_PROMPT bump when the reviewer merges (section 10).

## 1. What the census found

The census covers every recorded run in `research\runs` (21 runs). It counts the refused motions in the mismatch family:
52 in all, 50 after repair and 2 unrepaired.

- **21 are table refusals.** The act is one the table does not give to that target (`ACTION_NOT_VALID_FOR_TARGET`). They
  fall on six pairs, taken one by one in section 4.
- **31 are not table refusals.** The table accepts the pair. The refusal comes from the prose reader (16), from a
  declared-subject label that contradicts the act (8), from a delegate who wrote a different act from the one its words
  describe (4), from words that name a pair the table refuses (2), or from a domestic motion that carried a diplomatic
  action (1). Section 7.

| Pair (act to target) | Refusals | What the words were asking for |
|---|---|---|
| status_talks to Dorsania | 6 | Mostly a reply to a Dorsanian demand. `ultimatum_reply` is accepted. |
| status_talks to Veleria | 5 | Mostly a reply to Veleria's land demand. `ultimatum_reply` is accepted. |
| trade_talks to Veleria | 3 | Coal supply talks. |
| trade_talks to the Maritime League | 3 | Supply and credit talks (2), and one statement with no act. |
| trade_talks to Dorsania | 2 | Grain deal wording. `grain_deal` is accepted. |
| trade_deal to Dorsania | 2 | Grain deal wording. `grain_deal` is accepted. |

The row-by-row census, with the label of each refusal, is in `reports\10-diplomacy-targets-appendix.txt` (52 rows). The
rows are numbered "row N" below.

## 2. The table as it is

Source: `karamaniya/motion_actions.py`. `DIPLOMATIC_ACTIONS` (lines 50 to 64) gives each act one default receiver, which
is used when a delegate names no country. `DIPLOMATIC_TARGETS` (lines 72 to 85) widens four acts. `A*` is the default
receiver; `A` is accepted; `.` is refused. 27 of the 60 pairs are accepted and 33 are refused.

| Act | Union | Maritime League | Dorsania | Veleria |
|---|---|---|---|---|
| diplomatic_protest | A* | A | A | A |
| trade_talks | A* | . | . | . |
| status_talks | A* | . | . | . |
| non_aggression_pact | A* | . | A | A |
| federation | A* | . | . | . |
| join_union | A* | . | . | . |
| ceasefire | A* | . | . | . |
| alliance | . | A* | . | . |
| loan_request | . | A* | . | . |
| military_aid | . | A* | . | . |
| trade_deal | . | A* | . | . |
| grain_deal | . | . | A* | . |
| renounce | A* | A | A | A |
| cede_region | . | . | A | A* |
| ultimatum_reply | A* | A | A | A |

## 3. What a refusal says, before and after

Before, the text a delegate reads for a trade talk to Veleria is:

- the detail, shown next month: `a trade_talks can be addressed to Solvaran Union, not the Veleria`;
- the repair request, for Veleria: `Acts the engine can address to the Veleria: cede_region.`

The repair request was also wrong for the other targets. For Dorsania it named only `grain_deal`. For the Maritime League
it left out diplomatic protest, renunciation and ultimatum reply. Its line for the Union was correct.

After (commit `be90490` on this branch):

- the detail: `a trade_talks can be addressed to Solvaran Union, not the Veleria. Veleria accepts: diplomatic_protest, non_aggression_pact, renounce, cede_region, ultimatum_reply`;
- the repair request: `Acts the engine can address to the Veleria: diplomatic_protest, non_aggression_pact, renounce, cede_region, ultimatum_reply.`

Both read the same table the check reads, through `_accepted_acts` (motion_actions.py:906) and
`_not_valid_for_target` (motion_actions.py:913).

Where the text goes. The detail goes to the delegate in the next month's prompt, in the note of its own refused motions
(council.py:433 to 447). That note shows up to four motions and cuts each explanation at 300 characters. For 4 of the 21
table refusals the cut falls inside the accepted list. Three are Dorsania grain-wording cases and one is a status-talks
case with a longer preceding reason (`reports\10-diplomacy-targets-cutcheck.txt`). The repair request in the same month
is not cut, so the full list reaches the delegate there. Question 5 asks whether to lift the cut.

`cede_region` is in the list because the table gives it to Veleria and Dorsania. The executor accepts it only for a region
that neighbour has demanded (`territory.cession_problem`, territory.py:51). The list is the static table; a refusal for a
missing demand is still said separately.

## 4. The six pairs with table refusals

For each pair: the census rows, a judgment on whether a real country in Karamaniya's position could do it (judgment, not
a sourced fact), what the world has and needs, and a recommendation. "Probe" means the executor was run in memory on the
refused proposal. The outputs are `reports\10-diplomacy-targets-probe.txt`, `-probe-all.txt` and `-probe-ultimatum.txt`.

### 4.1 status_talks to Dorsania (6 refusals: rows 12, 30, 40, 45, 46, 51)

Five are replies to a Dorsanian demand. Row 12: "Answer to Dorsania's ultimatum" (20261011-105713-seed1, Month 9).
Row 40: "Reply to Dorsania: open status talks; mutual recognition ..." (b1-s1005, Month 4). Row 51 is a grain statement
written as status talks.

Could a real country do it? As a counter-offer to a neighbour's demand, yes (judgment). But the engine's status talks are
talks on Karamaniya's status in the Solvaran Union. The Veleria status demand names the Union as the venue (foreign.py:1232
to 1233), and the Union's status branch answers that demand (director.py:561 to 574).

What exists: `ultimatum_reply` to Dorsania is accepted (motion_actions.py:85). The reply is kept on the ultimatum with its
stance and text (director.py:455 to 474), and the cabinet's facts carry it the month after (foreign_force.py:629 and
638 onward, code reading). A counter-offer of talks fits in that text.

What a widening needs. Probe: status talks to Dorsania get "Dorsania has no standing to answer that proposal on behalf of
the Union" and no effect (foreign.py:1278 to 1279). A Dorsanian branch would be small. The effects of status talks are
not small. Status talks count as talks for the rule that lifts a blockade (director.py:166 to 190), as a standing entry
(standing.py:90), as a concession that the National Front reads when a deadline runs (opposition.py:57 to 61), and as a
concession in the delegates' own check (agents.py:375 to 384). These four readings are from code, not from a run.

Recommendation: keep it refused. The refusal now names `ultimatum_reply`. A talk on a region that is separate from the
Union would be a new act, a large change, and the user's decision (question 2).

### 4.2 status_talks to Veleria (5 refusals: rows 14, 26, 27, 36, 42)

All five are replies to a Veleria ultimatum or demand: rows 14, 26 and 27 to the demand to cede Kessel Valley, row 42 to
Veleria's ultimatum, and row 36 to the demand for withdrawal. Row 14: "We reject the demand to cede Kessel Valley. We counter with immediate de-escalation and open
talks on our status." (20261011-211521-seed1, Month 2). Row 42 says "We reject Veleria's ultimatum and will not negotiate
our status": the act is wrong for the words.

Could a real country do it? As a counter-offer to a demand, yes (judgment).

What exists: `ultimatum_reply` to Veleria is accepted. The land demand has the terms `cede_region` (foreign_force.py:48;
the demand is issued in `_issue_ultimatum`, foreign.py:1213 to 1224). Probe (`-probe-ultimatum.txt`): status talks offered to the Union do not
lift a land demand. The Union "takes note", and the demand stands. They lift only a demand whose terms are status talks
(director.py:568 to 572).

What a widening needs. Probe: status talks to Veleria are answered in the Union's voice ("takes note") and recorded in the
status-talks log, which feeds the readings in 4.1. A table entry on its own would therefore give a status talk that does
not answer the demand.

Recommendation: keep it refused. The refusal now names `ultimatum_reply` for Veleria.

### 4.3 trade_talks to Veleria (3 refusals: rows 4, 5, 13)

Row 4: "Open trade talks with Veleria to secure reliable coal deliveries for Karamanian industry ..." (20261008-130316-seed1,
Month 5). Row 13: "Open trade talks with Veleria for a NEW commercial coal agreement ..." (20261011-105713-seed1, Month 11).

Could a real country do it? Yes (judgment). A state under a coal embargo negotiates coal supply with the neighbour that
imposes the embargo.

What exists: the coal lever. The Veleria cabinet moves `dip.coal_embargo` (foreign.py:815 to 823, code reading), and a
protest eases it (director.py:494 to 500: "relaxes some coal shipment checks"). There is no trade-talks handler for
Veleria.

What a widening needs. Probe: trade talks to Veleria would be answered as the Union. The Union's branch cuts the Dorsania
grain embargo from 0.5 to 0.3 and postpones three months of Union trade measures (director.py:575 to 586). That is the
wrong party and the wrong lever, so a table entry on its own would misroute. A Veleria branch that eases
`dip.coal_embargo` is small, about the size of the Veleria branch in `_protest_reply` (director.py:494 to 500), and it
needs a test. How much relief there is, and what it costs, is a design choice.

Recommendation: keep it refused for the freeze. If the user wants it, the branch and the table entry go in together, with
the probe as the test (question 3).

### 4.4 trade_talks to the Maritime League (3 refusals: rows 1, 9, 52)

Row 9: "Open trade talks with the Maritime League for a standing supply arrangement ... a standby credit line of up to 30M
gold" (20261011-094417-seed1, Month 1). Row 1 is a similar request for credit and grain. Row 52 is a statement, not an act.

Could a real country do it? Yes (judgment): supply and credit talks with the other bloc.

What exists: the League's `trade_deal` (tariff relief when League trust is above 0.45, director.py:667 to 672) and
`loan_request` (director.py:636 to 659) are both accepted, and both have effects. `_league_reply` has no trade-talks branch
(director.py:621 to 672). Probe: a trade talk to the League gives no message and no change.

What a widening needs: a League branch (small) and a table entry. A talk with no effect would be only a menu change. A
talk that moved League trust would be a design choice.

Recommendation: keep it refused. The refusal now names `trade_deal` and `loan_request`, the two League acts that have
effects.

### 4.5 trade_talks to Dorsania (2 refusals: rows 35, 50)

Row 35: "Renegotiate terms with Dorsania to secure grain imports despite their border dispute ..." (b1-s1003, Month 4).
Row 50 is a quoted grain deal.

Could a real country do it? Yes (judgment). Grain talks with the neighbour that controls the grain are the natural act.

What exists: `grain_deal` to Dorsania is accepted, and its effects are real. The grain embargo falls by 0.12, trust rises,
and the agreement runs six or nine months (foreign.py:1281 to 1310). Probe: 0.5 falls to 0.38. Probe for trade talks to
Dorsania: "Dorsania has no standing to answer that proposal on behalf of the Union" (foreign.py:1279), with no effect. The
message is misleading.

Recommendation: keep it refused. The refusal now names `grain_deal`. Talks that are not a deal would need a Dorsanian
branch (small), and the misleading message would have to go with it.

### 4.6 trade_deal to Dorsania (2 refusals: rows 2, 33)

Row 2: "Secure the Dorsania grain deal immediately." (20261008-130316-seed1, Month 3). Row 33: "Establish new grain trade
agreement with Dorsania to secure food supply ..." (20261012-225146-seed1, Month 5). In both, the words describe a grain
deal.

Could a real country do it? A grain deal, yes. A wider trade deal with the neighbour that controls the grain is plausible
(judgment), but Dorsania's only trade lever in the model is the grain agreement.

What exists: `grain_deal` to Dorsania (4.5). `trade_deal` has one effect, the League's tariff relief (director.py:667 to 672).
Probe: `trade_deal` to Dorsania gets the "no standing" message and no effect.

A reader fault makes the words look like a trade deal. "grain trade agreement" reads as `trade_deal` (section 7 of this
proposal; the readings are in `reports\10-diplomacy-targets-reader-check.txt`). So the words and the act appeared to agree,
and the table is what refused it.

Recommendation: keep it refused. The refusal now names `grain_deal`. The reader fault is in section 7.

## 5. The other 27 refused pairs (no census refusal in these runs)

None of these 27 pairs was refused in the 21 runs. Each was put to the executor (`-probe-all.txt`). "Today" is what the
executor would say and change if the table accepted the pair, from the starting state (peace, no ultimatum). "Judgment" is
the view of whether a real country could do it.

| Pair | Judgment | Today (probe) | What it would need | Recommendation |
|---|---|---|---|---|
| status_talks to Maritime League | No: the League is not the counterpart on status | No message, no change | none | Keep refused |
| non_aggression_pact to Maritime League | Possible; little value in the model | No message, no change | League branch (small) | Keep refused |
| federation to Maritime League | No: a federation is a Union act | No message, no change | none | Keep refused |
| federation to Dorsania | No | "no standing" | none | Keep refused |
| federation to Veleria | No: a Union act, and the Union answers for its members | Union rejects a loose federation | none | Keep refused |
| join_union to Maritime League | No | No message, no change | none | Keep refused |
| join_union to Dorsania | No | "no standing" | none | Keep refused |
| join_union to Veleria | No | Union welcomes the rejoin; the outcome becomes joined_union, which ends the run (world.py:576 to 577) | none; widening would end the run | Keep refused; never open it by routing |
| ceasefire to Maritime League | No war with the League | No message, no change | none | Keep refused |
| ceasefire to Dorsania | Plausible as a border truce; row 47 names Dorsania in its words | "no standing", with or without war | a neighbour-truce mechanic (large) | Keep refused; a truce can be offered in an ultimatum reply |
| ceasefire to Veleria | Plausible only if Veleria fights; Veleria is a Union member | With war: the war with the Union ends. Without: "There is no war to end" | exists (director.py:611 to 620); the question is whether a neighbour may end the Union war | Keep refused (question 4) |
| alliance to Union | No: the League alliance is the counter-bloc | No message, no change | none | Keep refused |
| alliance to Dorsania | No | "no standing" | none | Keep refused |
| alliance to Veleria | No | No message, no change | none | Keep refused |
| loan_request to Union | Possible, borrowing from a hegemon; in the model the Union is the hostile power | No message, no change | a Union loan mechanic (large) | Keep refused |
| loan_request to Dorsania | Possible: credit from a neighbour | "no standing" | a Dorsanian credit mechanic (large) | Keep refused |
| loan_request to Veleria | Possible: credit against coal | No message, no change | a Veleria credit mechanic (large) | Keep refused |
| military_aid to Union | No | No message, no change | none | Keep refused |
| military_aid to Dorsania | No | "no standing" | none | Keep refused |
| military_aid to Veleria | No: Veleria is the threat | No message, no change | none | Keep refused |
| trade_deal to Union | Possible: trade with the hegemon | No message, no change | a Union trade branch (small to medium); trade talks with the Union already exist (director.py:575 to 586) | Keep refused |
| trade_deal to Veleria | Possible: coal trade | No message, no change | the same Veleria branch as 4.3 | Keep refused, with 4.3 |
| grain_deal to Union | No grain route through the Union in the model | No message, no change | none | Keep refused |
| grain_deal to Maritime League | Possible, but the League has no grain lever in the model | No message, no change | a League grain mechanic (large) | Keep refused; `trade_deal` covers League trade |
| grain_deal to Veleria | No: not a grain seller in the model | No message, no change | none | Keep refused |
| cede_region to Union | No: the Union makes no land demand in the model | "Karamaniya no longer holds the region the motion names" (no region given) | none | Keep refused |
| cede_region to Maritime League | No | No message, no change | none | Keep refused |

## 6. Pairs the words name that the table refuses

Two census rows name a refused pair in their words, while the structured act was another one.

- Row 48 (b1-s1013, Month 1): "Request urgent trade talks with the Maritime League ...". Its structured act was `trade_deal`.
  The words name trade talks to the League, which is pair 4.4.
- Row 47 (b1-s1007, Month 7): "Propose a ceasefire with Dorsania ...". Its structured act was a ceasefire with the Union.
  The words name a ceasefire with Dorsania, which is in section 5.

## 7. The 31 refusals that are not table refusals

Reader faults (16). A change to the reader changes which motions are refused. It does not change what the models are
told, so it needs no prompt bump. It does change run behaviour, so it is the user's call.

- 8 read a rejected or negated act as the act. The reader sees a negator only when it sits within two words before the
  act (`NEGATED_ACT`, motion_actions.py:141 to 142).
  - 5 are a rejected cession: "Reject Veleria's demand to cede Kessel Valley" (rows 15, 19, 23) and "Reject Dorsania's
    demand to cede Dorran March" (rows 28, 29). In each, the rejection is three or more words before "cede".
    Probe: "Karamaniya formally rejects Veleria's demand to cede Kessel Valley." reads as `cede_region`. "We reject the
    demand to cede Kessel Valley." reads as nothing, because there the negator is close enough.
  - 1 is "Reject Dorsania's demand for immediate status talks" (row 37), read as status talks.
  - 1 is "These talks do not reopen ... status" (row 20), read as status talks.
  - 1 is "excludes ... reunification" (row 6), read as `join_union`. "excludes" is not in the negator list
    (`NEGATOR`, motion_actions.py:99 to 102), while "excluding" is.
- 2 are counter-offers inside a reply, read as the act they name (rows 18, 25: a non-aggression pact). The reply exemption
  applies only when the text says "ultimatum" or "deadline" (`_ULTIMATUM_MENTION` and `_answers_an_ultimatum`,
  motion_actions.py:1053 to 1056). These two texts say neither.
- 5 read "grain trade agreement" or "existing trade terms" as a trade deal (rows 24, 34, 38, 39, 41). The grain pattern does
  not match "grain trade agreement", and the trade-deal patterns do (PROSE_ACTIONS, motion_actions.py:131 to 132).
- 1 reads "tariff revenue" in a loan request as a trade deal (row 8; the pattern `\btariff`, motion_actions.py:132).

Declared-subject labels (8: rows 11, 16, 17, 21, 22, 31, 44, 49). The delegate's own declared label names another act, while
the words and the act agree. The check is strict (`DECLARED_SUBJECT_CONTRADICTS_ACTION`, motion_actions.py:1156). Rows 16
and 17 are a special case: the reader reads a cession or a non-aggression pact in their words, but the reply exemption
suppresses that reading, so only the label refuses them. Whether a label on its own should block a motion is a design
question.

Delegate act errors (4: rows 3, 7, 10, 43). The words describe another accepted act: a loan written as an alliance (row 3),
a status and federation text written as trade talks (row 7), a protest written as status talks (row 10), and a grain deal
written as an ultimatum reply (row 43). The refusal is right. The fix is the delegate's choice, which this branch does not
change.

Words name a refused pair (2: rows 47, 48). See section 6.

Domestic motion carrying a diplomatic action (1: row 32, unrepaired). The refusal is right.

Recommendation for section 7: measure any reader change on the 31 census sentences first, and on the texts that were not
refused in the same runs, so the change is checked both ways. The readings are in
`reports\10-diplomacy-targets-reader-check.txt`.

## 8. What a widening must handle (the executor)

A widening is a routing change first, and a menu change second. `_answer_proposals` (director.py:409 to 444) sends each
accepted proposal to one answer.

- A Veleria or Dorsania proposal goes to `_union_reply` (director.py:436 to 437) unless an earlier branch takes it, so the
  Union's branches apply their effects. Probe: trade talks to Veleria cut the Dorsania grain embargo.
- A Dorsania proposal of any kind except a grain deal, a cession or a non-aggression pact goes to `dorsania_reply`
  (director.py:432 to 435), which answers "no standing" (foreign.py:1278 to 1279).
- A League proposal of a kind with no branch is dropped without a message (director.py:621 to 672; probe).

Effects a widening would trigger. Probe: join_union to Veleria sets the outcome to joined_union, and an outcome ends the
run (world.py:576 to 577); a ceasefire to Veleria during a war ends the war with the Union; trade talks to Veleria change
the Dorsania grain embargo. Code reading only: status talks feed the
blockade rule (director.py:166 to 190), standing (standing.py:90), the opposition's concession reading
(opposition.py:57 to 61), and the delegates' concession check (agents.py:375 to 384). The compliance facts for a status
demand count talks proposals to the Union or Veleria (foreign_force.py:649 to 652).

So each widened pair needs a handler, a probe-style test that checks the party, the state change and the message, and a
decision on each effect.

## 9. Recommendation and questions

For the freeze (about 20 October):

1. Keep the table as it is. The refusal now tells a delegate which acts its target accepts, with no change to the menu.
2. Do not widen any of the six census pairs before the freeze unless the handler and the user's decision are both in place.
3. Treat the reader faults (section 7) as separate work, measured on the 31 census sentences. They change refusals, not
   prompts.

Questions for the user, each with my recommendation:

- **Q1.** Keep the six census pairs refused for the freeze? Recommendation: yes. Five have an accepted act for the same
  purpose: `ultimatum_reply` for the two status pairs, `grain_deal` for the two Dorsanian grain pairs, and `trade_deal` or
  `loan_request` for the League talks. Coal talks with Veleria has no accepted act, so it is the one real gap (Q3). Each
  widening needs a handler first.
- **Q2.** Is `ultimatum_reply` the channel for talks offered to a neighbour that has made a demand? Recommendation: yes. It
  already carries the text and the stance to the issuing cabinet. A region-talk act is a new act and a large change.
- **Q3.** Coal talks with Veleria: a small handler that eases the coal embargo, plus the table entry? Recommendation: after
  the freeze, as a new version, with the relief and its cost decided first.
- **Q4.** May a ceasefire addressed to Veleria end the war with the Union? Recommendation: no. Today the table refuses it,
  and the executor would end the war.
- **Q5.** Lift the 300-character cut in the next-month note (council.py:446)? Recommendation: yes, under design rule 22. It is
  a second code change, so it needs your yes.
- **Q6.** Approve reader work on the 31 census sentences (section 7)? Recommendation: yes, measured both ways, before or
  after the freeze as you choose.
- **Q7.** Approve the AGENT_PROMPT bump for the refusal text, and the fixture write at merge? Recommendation: yes. The text is
  read by the models.

## 10. The prompt question

The refusal text reaches the models. The next month's note (council.py:433 to 447) and the repair request (council.py:2042,
inside `_repair_motions`) both carry it. The brief's rule is that a change to what a model is told bumps AGENT_PROMPT,
followed by `tools/prompt_freeze.py --write`. This branch does not bump it, and it does not write the fixture.

The default scripted freeze still reports "prompts unchanged", because a default scripted run has no such refusal. A run
that reaches one would show the new text. No such run was made here, because model runs are not allowed for this task.

## 11. What was verified, and what was not

Verified by run (outputs in `reports\`):

- The census of 52 records, and the counts above.
- The matrix before and after the change. The table block is identical.
- The executor probes for all 33 refused pairs, and the ultimatum probe.
- The reader readings for the sentences in section 7.
- The new tests: 8 of 8 pass after the change. Before the change, 63 assertion failures (commit `d375658`).
- Related modules: 617 tests in 30 modules, OK.
- The full suite: 2645 tests, OK, 2 skipped (the baseline was 2637 with 2 skipped; the difference is the 8 new tests).
- Prompt freeze: "prompts unchanged".
- The 300-character cut, computed from the census reasons for the 21 table refusals.

Not verified:

- The "could a real country do it" judgments. They are judgments, not sourced facts.
- The effects marked "code reading": the blockade rule, standing, opposition, the concession check and the cabinets'
  compliance facts.
- How the models respond to the new wording. No model runs were allowed.

## Appendix: where the detail is

- `reports\10-diplomacy-targets-census.txt` and `.json`: the census, with counts and examples.
- `reports\10-diplomacy-targets-appendix.txt`: the 52 rows with the label of each.
- `reports\10-diplomacy-targets-matrix.txt`: the table, and the refusal text for each refused pair.
- `reports\10-diplomacy-targets-probe.txt`, `-probe-all.txt`, `-probe-ultimatum.txt`: the executor probes.
- `reports\10-diplomacy-targets-reader-check.txt` and `-prose.txt`: the reader readings.
- `reports\10-diplomacy-targets-cutcheck.txt`: the 300-character check.
- `reports\10-diplomacy-targets-suite.txt`, `-related.txt`, `-test-before.txt`, `-test-after.txt`: the test runs.
