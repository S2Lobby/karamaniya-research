# Engine 18 audit (2026-10-10)

Ten Haiku agents audited world engine 18 (`e94ce22`), each one slice of the engine, read-only. A finding counted only if
the agent reproduced it by running code; each comes with a proof script (PoC) in the agent's worktree under
`research/.claude/worktrees/agent-<id>/audit/`. Every PoC listed here was re-run independently against `e94ce22`
and gave the output the agent reported (four needed a run folder as an argument; those four were checked against
the code instead). Findings two agents reported independently are merged. Suspicions no one reproduced are not
listed.

Severity is about what a finding can do to a run with models: **high** can change what the delegates or cabinets
decide, or what a run's figures mean; **medium** distorts a mechanic or a measurement in a way a reader would not
expect; **low** is a corner case, a display error or dead code.

Slices: EC economy, FO foreign policy and war, MI military and institutions, PO politics and elections, AG the
delegates' minds, CO the council's month, MO motions and actions, TO what the AIs are told, IN intelligence and
events, RU runs, saves, reports and tools.

## Critical

| ID | What happens | Where | Fix |
|---|---|---|---|
| CO1 | A non-finite number ("nan") is accepted as a policy value, by a motion or by an order with no vote: the tax becomes NaN, NaN spreads into every population's income (105, then 143 values in three months), approval falls, and the state check still reports "clean". A model whose connector does not enforce the schema can send it, and Python's JSON reader accepts the literal | `politics.py:155-201,729-732,1759-1765`, `world.py:59-60` | Refuse non-finite values in `_share_value` and the other parsers; have `state_validation` check levers and incomes for NaN |

## High

| ID | What happens | Where | Fix |
|---|---|---|---|
| CO2 | One wrongly typed field in a delegate's answer ends the month, and so the run: 47 field and value combinations raise (for example `information_requests: 3.5`), as do malformed repair answers and a foreign cabinet's `union_position`; the run loop catches only usage-limit pauses | `actions.py:352-1097`, `council.py:1698,1913,1958`, `foreign.py:1420`, `runner.py:405` | Type-check each field where it is read, and turn a worker's exception into a logged problem for that delegate |
| MO1 | A motion that *rejects* a joint inquiry or a stand-down offers it: only the four words before a match are checked for a negator, so "We reject the Union's call for a joint inquiry into the shooting" offers one | `fine_print.py:27,110-118` | Look back to the clause or sentence start for a negator |
| MO11 + CO10 | Policy values are read as shares and clamped silently: `military = 0.8` written for 0.8% becomes 80% and then 20% of output; `rate = 1` written for 1% becomes a 100% interest rate; the motion passes with no note | `politics.py:155-201`, `apply_motion` set_policy | Refuse a value outside the lever's range (send it back for repair), or cross-check it with the percentage in the text |
| MO19 | Appointments, expulsions, referendums and emergency motions are not checked against their text: "Appoint member C" with value B appoints B; "Lift the state of emergency" with value on switches it on; "a referendum on a federation" runs the independence referendum | `motion_actions.py:811-822` | Extend the text-against-action check to these motion types |
| TO1 + EC2 + EC4 | Inflation as the delegates and the public see it is wrong in three ways. The founding food price starts at 1.0 whatever the harvest, so Month 1 carries a one-off correction (seed 3: -3.0%). Months 1-11 annualise a partial year by 12/months, turning that into -30.7% "a year", and the public's economic pain (approval, grievance) reads the annualised figure (seed 5: approval -0.4 to -2.1 points in Months 1-4). And the window is one month off: the prompt annualises over one month more than has passed, and from Month 13 "the latest 12 months" is an 11-month change (seed 1: shown 10% in Month 2 against 21.4%; 5% in Month 13 against 6.9%). This is the root cause of T93 | `society.py:25-31`, `world.py:136`, `economy.py:318-319` | Set the founding food price from the founding harvest; publish the change since founding until 12 months have passed, over completed months only; from 12, use the change against `history[-13]` |
| TO2 | Colleagues see a motion's text cut at 160 or 200 characters (an amendment at 140) with no marker, mid-sentence, while the engine keeps 120 words and executes its fine print: the clauses that act are the ones colleagues cannot read when they vote | `prompts.py:522`, `decision_context.py:478,421,40` | Show the stored, word-limited text with its `[cut]` marker |
| MI1 | Calling up reservists is free: `military.reserve_cost` is never called, though the prompt says reservists "cost money to keep embodied"; a general call-up of 63,357 reservists adds no arrears | `military.py:765-781,156-158` | Add the monthly reserve cost to the military bill and charge the activation cost at call-up |
| FO1 + FO2 | The neighbours' call-ups are unlimited in practice: the 12,000 monthly cap is checked per act, so four acts in one decision call up 48,000; and a call-up never draws down the reserve pool (134,998 called up from a pool of 90,000) | `foreign_force.py:32,224-227,317-322,159-161` | Track the month's call-ups per actor against the cap; move called-up soldiers out of the reserve pool |
| FO3 | The cabinets never learn that a region has fallen or is held by rebels: their view lists only regions Karamaniya controls and then tests those for occupation, so `occupied_regions` is always empty, and covert support to a rebel-held region is refused | `foreign_force.py:618,667,242`, `world.py:500-503` | Use `w.k_regions(controlled_only=False)` in those places |
| EC1 | A League loan tranche is counted twice, into the reserves and against the crown budget: the government's net position rises by 24.9M on a 25M loan | `economy.py:209-231,705-707` | Debit the reserves for the crowns the tranche funds, or keep it out of the budget need |
| IN5 | The Treasury's costing of a bigger army charges 900 crowns per soldier a month; the engine pays 260 (the General Staff's own figure): the delegates are shown armies costing 3.5 times what they cost | `intelligence.py:725` | Cost soldiers as `military.update` pays them |
| IN1 | A costing request answered at the start of the next month always says "no costable proposal": the carry-over call answers against an empty motion list | `intelligence.py:672-678`, `council.py:1339` | Resolve the motion when the request is made, and never answer against an empty list |
| IN2 | A temporary movement restriction lowers regional logistics for good (Kessel 1.00 to 0.96, still 0.96 six months after the measure ends), and output is linear in logistics | `dilemmas.py:955-960,872-880` | Record the cut and undo it when the measure expires |
| MI12 | A saved run does not resume faithfully once a region has fallen: `Pop._mobilized_share` is not saved, and the resumed run diverges from Month 4 | `military.py:277,289,302,310,370`, `world.py:97-114` | Save the shares (or derive them), together with the fix for MI11 |
| MO2 + FO9 | An expired demand on the Union's rules path never lapses: the embargo is re-enforced every month (rally 0 to 0.72 in four months) or a blockade holds it open, blocking any new demand, and a land demand stays cedable seven months after its deadline | `director.py:95,111-128`, `foreign_force.py:184-196` | Clear the demand after its first enforcement and run the lapse test before the early return |
| TO6 | A seat with a small context budget loses whole sections silently, and at the 8,192-token Ollama setting (`council.validation-tiny.toml`) the prompt loses the briefing, motions and even the answer format | `decision_context.py:578-628`, `backends/ollama.py:29-40` | Reserve the instructions and schema first, cut the canonical block last, and say in the prompt when a section was shortened or dropped |

## Medium

| ID | What happens | Where | Fix |
|---|---|---|---|
| PO1 + TO5 | "If the election were held now" leaves out what the vote then adds: the press advantage, the Union's propaganda push and rigging; the verdict can flip both ways (rigged: line "lose" 29%, vote "keep" 41%) | `politics.py:2222-2229` vs `2182-2243` | Compute the outlook as the vote is computed, or say what it leaves out |
| PO2 | The integrity audit counts a motion the execution gate blocked as executed (`CORRECTED_BEHAVIORAL` and a replay point) | `integrity.py:64` | `executed` only when `execution_status == "EXECUTED"` |
| FO4 | The Union's losses are never replaced from its reserves: the replacement code looks up the combat record by actor, which is keyed by front | `rivals.py:90-91`, `military.py:460` | Attribute front losses to actors |
| FO5 | A status demand set by the Union's own rule cannot be met by talks, and no cabinet is shown it (it has no `terms_id`) | `foreign.py:1149-1151` | Give it `terms_id: status_talks` and `by: veleria` |
| FO6 + RU4 | With the foreign cabinets off (`council.30runs.toml`), no neighbour ever sets a demand, in the run or its baselines; the baseline docstring says its neighbours are stand-ins in every baseline | `foreign.py:690-691`, `baseline.py:19-22,49` | Run the baselines' neighbours as stand-ins whatever the run's setting, and let the Union's rule reach its trigger, or document both |
| FO7 | Karamaniya's own `posture = attack` starts a war in Month 1 and re-declares it every month, undoing any ceasefire while the setting stays | `director.py:159-170` | Gate on FIRST_WAR_MONTH (or let it be the council's choice) and start a war only on a change to attack |
| FO8 | Three more paths move an embargo's level without moving the exporter's output (the expired-demand enforcement, a grain deal, a protest), so the engine-18 embargo fix is incomplete | `director.py:120,384`, `foreign.py:1201` | Route every change of level through `_embargo_output` |
| FO10 | A neighbour's defence burden does not depend on its economy, saturates at its cap from Month 1 for Veleria, and wears its readiness down every peacetime month (0.58 to 0.44 in a year) | `rivals.py:17,38-50,81-104` | Price soldiers in money and divide by current output |
| FO11 | Veleria's coal embargo only ratchets up: nothing in its positions can ease it (0.80 stays 0.80), while the changelog says easing gives the trade back | `foreign.py:687-688,782` | A design decision: add an easing path or document it |
| MI3 | "Conservative" reserves cut energy and industrial output, not imports | `operations.py:80`, `economy.py:120-140,227` | Apply the cut to imports, or correct the help text |
| MI4 + MI7 | The General Staff's request: a delivered half answer is judged unanswered (grievance accrues), while any call-up of reservists, however small, counts as an answer | `staff.py:86-92` | Judge both against the gap when the request was made |
| MI11 | Reservists from a region that falls stay on the labour books and the remaining populations are charged the full draw again (1,159 counted twice) | `military.py:271-292` | Remove last month's shares from every population that holds them |
| AG1 | Relationship changes are rounded to 0.1 each, so small effects vanish: resentment below about 3.3 never decays, and twelve routine votes leave respect and affinity unchanged | `agents.py:514-515` | Round the stored value, not each change |
| AG2 | A yes vote to massage the statistics is charged as repression, not dishonesty (the honest reputation never moves); as an order it is not charged at all | `standing.py:212-226`, `agents.py:473-474` | Tag it dishonesty |
| AG3 | A promise made in a public statement and broken by the same month's vote is judged a month late or never | `commitments.py:290` | Judge statement promises in the month, like messages |
| AG4 | Under the secret ballot, promises about funding, raising or cutting are not judged even when a public order breaks them, so the arm differs in more than the ballot | `commitments.py:293-294` | Skip only the vote-based part of the judgement |
| AG11 | Implementation losses fire every month a setting is merely repeated (the arms and food losses), not only when it changes | `standing.py:643-648`, `council.py:1828-1837` | Pass only the levers that changed this month |
| AG12 | A delegate's base does not see the conduct of a yes vote (lethal repression, delaying the election), though the audiences do | `standing.py:413,420` | Pass the conduct tags of a yes vote to `bases.note_vote` |
| MO3-MO8, MO22 | Numeric grounding has holes: "20,000,000 gold" passes where "20 million" is refused; a true figure about the Union's troops is refused against our own army; an opinion word ("alarming") switches the check off; "90/100" is never checked; a figure in any source supports any claim; bare numbers pass; "prices climbed 9%" is not read as inflation | `motion_actions.py:962-1152` | Parse grouped numbers, route Union figures to the Union's truth, drop the opinion guard when a figure is stated, read x/100, tie support to the claimed metric |
| MO9 + CO7 | A threshold written in percentage points is read 100 times too high for inflation and deficits: a motion condition "inflation <= 6" executes at 60% inflation, a vote condition "inflation at or below 2" counts as met at 10%, and a quiet-month wake "inflation at or above 8" never wakes the council | `motion_actions.py:203-220`, `actions.py:1079-1080`, `token_saving.py:185` | Use one rule for every ratio metric |
| MO10 | A safeguard's amount in the motion text is cut short: "1.5bn" becomes 1,000,000, "79.5M" 79,000,000, "12,500,000" 12,000,000 | `motion_actions.py:236-285` | Reuse the figure parser that handles commas and decimals |
| MO13 + MO14 | Repairs of held-back motions are paired by position, so one skipped reply mislabels the others; and a refusal from the repair path is never shown to its author the next month | `council.py:1964,2006,1988,433-447` | Pair by motion id; keep the conflict under its own key |
| MO15 | The prose negation list misses reject, refuse, decline, nothing and several acts, so valid talks motions are refused ("We refuse any federation") | `motion_actions.py:88-115` | One shared negation vocabulary with `fine_print.py` |
| MO16 | "inflation_rate" is an alias for the interest rate | `politics.py:450-476` | Drop the alias |
| IN-M1 | The urgent reports of a false-warning issue are written after the council has met and are never shown, but still move the holder's beliefs | `dilemmas.py:661-674` | Generate them with the month's other reports |
| IN-M2 | Withheld reports can never leak: the leak check runs before they are flagged (72 flagged, 0 leaked in 36 months) | `council.py:1790-1793` | Flag before leaking |
| IN-M3 | Forecasts on approval, unemployment and morale are scored one update early, and the beliefs learn from the wrong error | `engine.py:49` | Resolve forecasts after the society and military updates |
| IN-M4 | A ministry answers up to twice its monthly capacity (the carry-over call and the session call each get a fresh budget) | `intelligence.py:642-647` | Count per month across calls |
| IN-M6 | A costing request for one motion can be answered with another's cost, sign flipped | `intelligence.py:673-676` | Answer that the motion is not on the agenda |
| IN-M7 | A procurement scandal's text says auditors found padded contracts and its reputation hit is the same whether or not it is true | `dilemmas.py:522-529,747-750` | Word it as an allegation and scale the hit by the truth |
| IN-M8 | A report whose estimate is clamped prints a degenerate range ("a 100-100% probability"): 103 of 960 Union-intent reports at war | `intelligence.py:243-253,690-691` | Clamp the centre first, then build the range |
| EC3 | Exchange-rate pass-through acts on the price level for one month and reverses when the currency stops falling | `economy.py:885-898` | Make pass-through accumulate |
| TO3 | The Treasury's tax is printed as 0.18 while 0.185 is in force, next to directives that print 0.185; ordering the printed value changes the tax and records defiance | `briefing.py:275,277` | Print settings with the directives' formatter |
| TO4 + FO15 | The cabinets' estimate of Karamaniya's army is biased about 10% high and contains the truth in under half of months; its ends can be reversed | `foreign.py:510-511` | One centre and a symmetric width |
| RU1 + RU5 + MI5 | `human_factor = false` is broken: the scripted stand-ins cannot form a government (the run pauses before Month 1), psychology is still created and reported, and audits and public reactions never apply | `backends/scripted.py:331-332`, `engine.py:28-32,62-68,318-319` | Gate psychology on the human factor; read traits defensively; gate audits and public reactions on the version alone |
| RU2 | A baseline mode that stopped is recorded as "ok" with zero months, and the report shows dashes | `baseline.py:172-182` | Record failed modes and their stop reason |
| RU7 | `tools/matrix.py --compare` counts a stopped run with the finished ones | `tools/matrix.py:155-160` | Skip runs without an outcome |
| CO3 + CO4 | A deferral "until Month N" is never applied: the link is read before this month's votes are counted, so the motion returns the next month; and once the link works, the next agenda rewrite drops the held motion | `council.py:1512-1524`, `politics.py:1356-1375`, `deliberation.py:287-295` | Write `defer_until` after resolution, and keep held entries when the agenda is rebuilt |
| CO5 | A motion sent back for repair skips the intake checks, then takes a vote and an agenda slot before it lapses as invalid, pushing a valid motion off the agenda | `council.py:1942-1999` | Run `deliberation.check` on repaired motions before they are tabled |
| CO6 | A conditional vote "yes if X passes" counts as met when X won its vote but then lapsed | `deliberation.py:612-615`, `council.py:2312-2315` | Resolve conditions against the final outcome, or say in the prompt that the vote is meant |
| CO8 | A delegate who votes yes and resigns in the same answer loses the vote: 3 of 5 voted yes, the tally is 2-2 and the motion fails | `council.py:2236-2238,2280` | Count the votes cast, then apply the resignation (confirm the intent) |
| CO9 | Unanimity has two definitions in one report: convergence counts abstentions as agreement (a 3-0 vote with 2 abstentions is unanimous), the scorecard and the GUI do not; 16 of 68 motions differ in a 24-month run | `convergence.py:568`, `scorecard.py:263-269`, `gui.html:1801` | One helper used everywhere |

## Low

| ID | What happens | Where |
|---|---|---|
| PO3 | The duplicate-amendment guard protects the election date only when the clause says Month 18 (the date is Month 36) | `politics.py:305-309` |
| PO4 | Red-line crossings recorded for motions the line does not describe (lifting a curfew, re-setting the rule in force) | `agendas.py:176-196` |
| PO5 | A rigged vote above about 88% records negative shares for the other lists | `politics.py:2238-2242` |
| PO6 | Whether the vote was rigged shifts the officers' coup draw (one stream shared) | `politics.py:2243` |
| PO7 | The engine-17 referendum formula applies to architecture-1 worlds | `politics.py:2410-2450` |
| PO8 | `integrity.record_replay` ignores `up_to_month` (dead code) | `integrity.py:176-182` |
| PO9 | A world resumed from before engine 18 measures no opposition acts in its first month | `opposition.py:299-307` |
| PO10 | The integrity replay point is month 0 when the first wrong motion is in month 0 | `integrity.py:139-144` |
| FO12 | An arming in Month 1 never reaches the neighbours' figure (resolve's first look is the baseline) | `resolve.py:92` |
| FO13 | Army intelligence's offensive risk still ignores the alliance, pact and ceasefire terms of the Union's threshold | `intelligence.py:42-63` |
| FO14 | Each troop deployment is charged to output again, even when the same soldiers move back and forth | `foreign_force.py:355` |
| FO16 | A lapsed land demand can still be ceded for three months while the lapse message says it expired | `foreign_force.py:184-195` |
| FO17 | A step down in mobilization is recorded as a call-up in resolve | `resolve.py:97-98` |
| FO18 + TO7 | A cabinet is told its demand has expired in the month it can still answer it | `foreign_force.py:594,606` |
| FO19 | Veleria's `trade_concession` moves nothing the engine reads | `foreign.py:982-985` |
| MI2 + MO17 | A stand-down documented as two months holds three | `fine_print.py:216,320` |
| MI6 | An accepted inspection regime has no effect | `fine_print.py:277-279` |
| MI8 | Civil-support feeding is overwritten within the month | `operations.py:118` |
| MI9 | The head's diplomatic tone is overwritten before the month ends | `operations.py:62-70` |
| MI10 | Audit findings are shown four months; the docs say three | `audits.py:300` |
| AG6 | The order of grievances follows set iteration, so prompts differ between processes | `agents.py:685-686` |
| AG7 | The YOUR PAST and YOUR BASE lines push the priorities or fears out of the short disposition used for small seats | `decision_context.py:723` |
| AG8 | A base keeps updating (and disowning) after its delegate has left | `bases.py:97-102` |
| AG9 | Audience support resets to 0.5 when an office is lost and regained | `agents.py:291-301` |
| AG10 | The secret arm still writes stand memories (own vote and public tally only; not a leak) | `memory.py:414-434` |
| MO12 | The policy-figure check sees only "from A% to B%" | `motion_actions.py:878-901` |
| MO18 | BAD_LOAN_AMOUNT is not a registered error code | `politics.py:801`, `errors.py` |
| MO20 | "joint commission" is read as a joint inquiry | `fine_print.py:59` |
| MO21 | Two different protests in one month merge as duplicates when neither names an issue | `motion_actions.py:1185-1240` |
| MO23 | "Veleria (a Union member)" resolves to the Union | `motion_actions.py:119-127,704-717` |
| MO24 | Stand-downs written in other words ("halt our patrols") are not detected | `fine_print.py:65-72` |
| IN-L1 | A governor-defiance or civil-service compliance cut is overwritten before revenue | `dilemmas.py:723,761`, `economy.py:649-652` |
| IN-L2 | Undoing a floored logistics cut restores more than it took | `dilemmas.py:626-629,879` |
| IN-L3 | A deferred request still takes a capacity slot | `intelligence.py:647-650` |
| IN-L4 | A contested lens report's id depends on whether the plot report was generated | `intelligence.py:482-483` |
| IN-L5 | A hedge word inside another word ("mayor", "dismayed") hides an explicit coup intent | `provenance.py:77-79` |
| IN-L6 | The documented non-fiscal lag channels are never scheduled | `causality.py:118-130` |
| IN-L7 | Costing a boolean lever already in that state still charges a cost | `intelligence.py:703-718` |
| EC5 | The founding output gap is zero by construction | `world.py:713-737` |
| EC6 | The currency launch moves the new zone's prices 0.34 points | `economy.py:985` |
| EC7 | The causal price trace uses other weights than the price formula and names channels not in it | `economy.py:928-938` |
| EC8 | Foreign interest is paid from the crown budget, not the reserves | `economy.py:674-707` |
| EC9 | Industrial utilisation can exceed 100% | `economy.py:139-165` |
| EC10 | The regime label reads HIGH_INFLATION during deflation | `causality.py:257-258` |
| EC11 | The calibration's monthly-peak check reads almost no months in scripted runs | `calibration.py:95-111` |
| EC12 | Neighbours never print money or change their rate; the code that reads those fields is dead | `world.py:273-274`, `economy.py:823` |
| TO8 | One prompt prints two different outputs for the same month (canonical 95, public briefing 97) | `briefing.py:460-462` |
| TO9 | With seeded names, the English word "union" becomes the seeded name ("the administrators' federacy") | `naming.py:67-89` |
| TO10 | An emergency measure lasts four months; the motion detail says three | `dilemmas.py:930-934` |
| TO11 | The Dorsania grain arrangement is shown as ended a month before the engine ends it | `politics.py:1573` |
| TO12 | A border-incident leak is published under a censored press | `attribution.py:116-151` |
| RU3 | A secret-ballot run prints "0 of 0 that moved them" for costly votes | `scorecard.py:180-187,344-345` |
| RU6 | `bargain_followthrough` is always empty (wrong key) | `convergence.py:825` |
| CO11 | Deployment shares depend on the key order of one answer (each share set renormalises the others) | `politics.py:1759-1765` |
| CO12 | The audit state logs approval as null for every executed motion | `council.py:644` |
| CO13 | A formation repair that returns nothing is logged as "repaired", and the head office can stay vacant | `council.py:968-984` |
| CO14 | A third motion beyond the two-motion cap is dropped without telling the delegate the next month | `actions.py:352-358`, `council.py:433-447` |

## Checked and found sound (selected)

Determinism across processes (several runs under different `PYTHONHASHSEED` values, apart from AG6); stop and resume
for open, secret and cabinets-off runs, including a usage-limit pause and a crash mid-month (apart from MI12); a
scripted run against its own scripted baseline; the baseline engine gate; the arrears ledger (it balances every
month; the 3.9 times monthly output is the true sum of unpaid bills in the rule councils); the Month-36 handover (the
hawk councils' `kept_power_by_force` is the stand-in hawk's own takeover, not an engine error); vote shares; the
referendum's parts; the plot's coup outcome; public-mood caps; fine-print timing; the Charter date; word limits;
report ids of the engine-18 reports; error-kind frequencies; storm damage; save and load of intelligence, the
economy and the delegates' state.
