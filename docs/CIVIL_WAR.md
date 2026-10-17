# Civil war (Wave C as implemented)

Status: built and tested on scripted stand-ins; **no real-model run has been made**. The design
answers are the lead's decisions of 2026-10-17 (`notes/open-actions-decisions.md`, Wave C); the
original design is `notes/CIVIL_WAR-design.md`. This file describes what the engine now does, the
measured scripted calibration, and what remains unverified.

The arm is one run option, `civil_war = "on" | "off"`, default `off`. Under `off` no engine path
reads a war state, no trigger fires, the prompt freeze is unchanged and a default history row is
exactly engine 29's (`tests/fixtures/civil_war_off_month.json` is compared whole). Under `on` the
run is stamped in the manifest.

## 1. Triggers

A war can start from Month 2 (0-based month index 1); the user's rule forbids one in Month 1.
Both triggers are judged inside `politics.resolve_coups`, from the same `anticipated_response`
split the coup itself used, and before any removal, so the government side is still in being when
the war starts.

### 1.1 A failed coup whose plotters keep their force

The coup record now stores, for every armed office, the division `military.anticipated_response`
returned (`obey_commander`, `obey_government`, `neutral`, `split`, and the office's weighted
power). On a failed coup the plotters are not arrested when:

- their combined `obey_commander` share, weighted by `politics._power` over the three armed
  offices, is at least `FAILED_COUP_SHARE = 0.30`; and
- at least one armed plotter's force has `bond >= FAILED_COUP_BOND = 0.30` or
  `loyalty <= FAILED_COUP_LOYALTY = 0.45`.

Otherwise today's path stands: the armed plotters are removed (`failed_coup`) and the force takes
a morale hit. The constants are assumptions, not measured facts.

### 1.2 A handover coup that splits the plotters' own command

In the handover month a successful coup normally sets `handover_blocked_month`, which
`engine.step` turns into `kept_power_by_force`. With the arm on, the coup starts a civil war
instead when at least one **plotter-held** armed office's own division keeps
`obey_government + 0.5 * split >= HANDOVER_GOVERNMENT_SHARE = 0.25` with the government. Only a
plotter-held office is judged: a loyal police or navy staying with the government must not turn
every total takeover into a war. A total takeover — the plotter's own command obeying its
commander — keeps `kept_power_by_force`.

When the war starts, the targets are not removed, `handover_month` and `election_month` are
cleared, and no `handover_blocked_month` is recorded. The run goes on.

## 2. Factions, forces and territory

`w.civil_war` is built once by `civil_war.start()`:

```
{
  "since": month, "cause": "failed_coup" | "handover_coup",
  "factions": {
    "government": {"id": "government", "leader", "members", "forces", "territory", "power_share"},
    "rebels":     {"id": "rebels",     "leader", "members", "forces", "territory", "power_share"},
  },
  "contested": [region ids],
  "unaligned_power_share": float,
  "prewar_strength": {"government": soldier-equivalents, "rebels": soldier-equivalents},
  "stalemate": {"months", "month", "signature"},
  "breaches": [...], "next_offer_id": int, "settlement": None,
  "ceasefire": False, "offers": [...], "outcome": None,
  # written by C2/C3/C4 as the war runs:
  "forces": {office: {government, rebels, neutral}}, "progress": {region: float},
  "orders": {"rebels": {front: stance}, "government": {...}}, "intensity": optional,
  "last_combat": {...}, "last_faction": {...},
}
```

- **Members.** The government is every active member not in rebellion. Rebels are the coup's
  plotters plus every active member whose coup stance was `join`; they keep their seats, offices
  and status, are listed in the state and are excluded from the government's opening, revision
  and decision phases (`council._session_members`). Each faction's leader is the highest office in
  `OFFICES` order, ties broken by armed power and then id.
- **Forces.** For each armed office, the rebels take `obey_commander` when the holder is a rebel;
  the government takes `obey_government + 0.5 * split` whether or not the holder is a rebel; the
  rest is unaligned. Shares are weighted by `politics._power` and stored per office in the
  faction blocks with the holder, size and neutral share. C2 rewrites the top-level `forces` as
  normalised per-service shares every month, and applies a **defection cap of 5 percentage
  points of a service's allegiance a month** toward what `anticipated_response` now says.
- **Territory.** Regions already at `controller == "rebels"` join the rebels; the others stay
  government. The capital and the two front deployments (`capital`, `north`, `east`) are added to
  `contested` when the rebel army share (the commander share of the army) is at least 0.5. No new
  controller value is introduced: `"rebels"` and `"karamaniya"` are the existing war values every
  reader (briefing, foreign force, economy, map) already understands; the contested set lives in
  the state. C2's combat moves a region between the two values and keeps the faction territory
  lists equal to the controllers; a region that falls takes 10-15% of its people as refugees.

## 3. Combat (C2, `karamaniya/civil_war_combat.py`)

One `combat(w)` call a month, from `engine.step` after `military.update` and before
`society.update`, after the council and faction phases. It draws only from
`rng_for(seed, month, "civil_war_combat")`, so no other stream moves. It returns `None` and
touches nothing when there is no war or the war has ended. A ceasefire stops the fighting (the
record says so) while allegiance may still drift.

The model is shaped like `military._combat`: per front, each side's engaged force is its service
share spread over the contested regions (navies only on coasts), quality from equipment, training
and morale, supply from arrears (`1 - 0.15 * min(3, arrears)`, floored at 0.5), terrain from the
region, fortification from the war state or the General Staff's works, and the defender bonus.
The ratio drives losses, civilian deaths, damage and a ground-progress model (a front falls at
1.0; progress decays when stalled). Constants, all in the module:

| constant | value | meaning |
|---|---|---|
| `SOLDIER_LOSS_MIN/MAX` | 0.015 / 0.025 | monthly loss coefficient of the engaged force, drawn per front, scaled by `(enemy/own)^0.5`, capped at ratio 4 and at 40% of a front's force |
| `CIVILIAN_DEATH_RATE` | 0.0003 | of a contested region's population a month, at intensity 1 |
| `DAMAGE_MIN/MAX` | 0.02 / 0.04 | region damage a month per fighting front |
| `REFUGEE_MIN/MAX` | 0.10 / 0.15 | of every population group in a region that falls |
| `DEFECTION_CAP` | 0.05 | allegiance movement a month, per service |
| `RATIO_CAP` | 4.0 | loss scaling bound, as `_combat` |
| `PROGRESS_RATE` / `PROGRESS_DECAY` | 0.15 / 0.05 | ground model, as `_combat` |
| `EQUIVALENT` | army 1, navy 900, interior 0.35 | soldier-equivalents, as `military._force_power` |

Losses take men out of the service sizes and the population (30% killed, 70% wounded or
released, the engine's convention), count `civil_war_soldiers_killed`,
`civil_war_government_killed`, `civil_war_rebel_killed`, `civil_war_security_killed`,
`civil_war_sailors_killed`, `civil_war_civilians_killed` and `civil_war_refugees`, and record
everything in `w.civil_war["last_combat"]` (fronts, ratios, losses by side and office, civilian
deaths, damage, progress, control changes with refugee counts, defections before/after).

## 4. The faction month (C3)

While a war is running, the rebels get one call a month through the ordinary delegate call path:
`phase="faction"`, `member` = the rebel leader. `backends/replay.py` keys it by (month, phase,
member) like any other call, so a war run replays from its log. The government's opening,
revision and decision phases skip the rebels; everyone else runs as usual. If no active rebel
leader has a seat, no call is made and the month record says why.

The call is built by `decision_context.build` with the month's public brief, the leader's
messages, `prompts.faction_instructions`, and `actions.faction_schema`. The fronts are `north`,
`east`, `capital`, then each contested region id in sorted order (`actions.faction_fronts`).

### 4.1 The schema in full

```
{
  "type": "object",
  "properties": {
    "fronts": {
      "type": ["object", "null"],
      "properties": { "<front>": {"type": "string", "enum": ["attack", "defend", "withdraw"]}, ... }
    },
    "offer": {
      "type": ["object", "null"],
      "properties": {
        "ceasefire": {"type": "boolean"},
        "terms": {"type": "array", "maxItems": 5, "items": {
          "type": ["object", "null"],
          "properties": {
            "amnesty": {"type": "boolean"},
            "power_sharing": {"type": ["object", "null"], "properties": {
              "head" | "treasury" | "interior" | "army" | "navy":
                {"type": "string", "enum": ["government", "rebels"]}}},
            "regional_autonomy": {"type": "string", "enum": [<Karamaniya region ids>]},
            "forces": {"type": "string", "enum": ["integrate", "disarm"]},
            "election_date": {"type": "integer", "minimum": 36}
          }}
        }
      },
      "additionalProperties": false
    },
    "statement": {"type": "string"},
    "messages": {"type": "array", "maxItems": 3, "items": {
      "type": "object",
      "properties": {"to": {"type": "string", "enum": [<every other active member>]},
                     "text": {"type": "string"}}
    }},
    "appeal": {"type": ["string", "null"], "enum": ["union", "league", null]}
  }
}
```

The axes are optional: a front the leader does not name is fought as the month finds it. Word
limits are 120 for the statement, 3 messages of 40 words each (the ordinary DM words). The reader
`actions.normalize_faction` records every refusal in words with a registered code, and the rest of
the answer stands: `FACTION_UNKNOWN_FRONT`, `FACTION_BAD_STANCE`, `FACTION_UNKNOWN_TERM`,
`FACTION_BAD_OFFER`, `FACTION_BAD_APPEAL`, `FACTION_BAD_MESSAGE`, `FACTION_UNKNOWN_FIELD`,
`FACTION_STATEMENT_TOO_LONG`.

### 4.2 The prompt in full

`prompts.faction_instructions` sends exactly these lines (dynamic values in `<...>`; the
settlement list is C4's closed list, and the election floor is the user's design rule):

```
THE WAR
Karamaniya is in civil war. The government is led by <government leader>, and the forces in rebellion are led by you, <leader>. It began in Month <since + 1>.
Members of the government: <names>. Members with the rebellion: <names>.
Regions held by the government: <names>. Held by the rebellion: <names>. Contested: <names>.
Shares of the armed forces: <office> government <share>, rebellion <share>, neither <share>; ...
Last month, fighting took place in <region names>.
YOUR ORDERS THIS MONTH
Give a stance for each front: <fronts>. A stance is attack, defend or withdraw. An attack sends your forces into a front the government holds; a defence holds a front you hold; a withdrawal leaves it without a fight. A front you give no stance is fought as the month finds it.
OFFER. 'offer' is null for no offer, {"ceasefire": true} for a ceasefire, or {"terms": [...]} for settlement terms. A ceasefire stops the fighting while it holds; an attack breaks it. The settlement terms are a closed list, each named in its own item: {"amnesty": true} (no prosecutions for taking part); {"power_sharing": {"head": "government" or "rebels", ...}} (power sharing: the offices head, treasury, interior, army and navy, each given to one side); {"regional_autonomy": "<region>"} (regional autonomy for one of <regions>); {"forces": "integrate"} or {"forces": "disarm"} (your forces merge into the state's, or disband); {"election_date": <month number>} (never before Month 36). An offer is recorded and put to the government; it takes effect only if both sides accept the same terms.
STATEMENT. Your public statement, up to 120 words.
MESSAGES. Up to 3 private messages, each to one delegate and up to 40 words; they arrive next month.
APPEAL. null for none, or "union" or "league" to appeal to that power.
Use null or [] where you have nothing to offer. A stance for a front outside the list, a term outside the settlement list, or an appeal to anyone else is refused and recorded.
```

The prompt states the war neutrally and never says whether to fight, offer or appeal. The
statement, messages and appeal are records and calls, not new mechanics: messages are delivered
next month through the ordinary DM path; the appeal is recorded on the month.

### 4.3 Orders and the month record

The answer's fronts are written verbatim to `w.civil_war["orders"]["rebels"]`; the government's
key is not filled by C3 (C2 reads a front or region id per side). The council's month record
carries the leader, who spoke, the answer, refused entries, problems, orders, the call summary,
and C4's results for any offer, reply, response or breach. C5's history hook adds the month's
combat and negotiation under the same `civil_war` key (section 7).

## 5. The government's reply

An offer in the faction month is put to the government once in the same month, by a second call
of the same phase with the responder's member id. The responder is the head if it is an active
non-rebel, else the highest-ranked active member who is not in rebellion. The schema is tiny:

```
{"type": "object", "properties": {"accept": {"type": "boolean"}, "reason": {"type": "string"}}}
```

`prompts.faction_reply_instructions` sends exactly:

```
THE GOVERNMENT'S ANSWER
The rebel leadership has offered <offer in words>. As <role>, answer for the government.
accept: true or false. reason: your public reason, up to 20 words.
A settlement takes effect when the government accepts the same terms in the month they were offered; an offer left unanswered expires at the end of the month.
Use true to accept and false to refuse.
```

The reader keeps `accept` as `None` when it is not a boolean, so an unreadable answer answers
nothing. A ceasefire offer is accepted or refused through C4; settlement terms are answered
through C4's `respond` with the offer id. C4 requires the offer and its acceptance in the same
month; an offer left unanswered expires at that month's end check. The scripted stand-in always
refuses (section 9).

## 6. Ceasefire, settlement and ends (C4)

- **Ceasefire.** Either side offers; an offer alone changes nothing. The other side's call, or
  `accept=True`, sets the flag C2 reads, and combat stops while it holds. An attack order from
  either side breaks it before combat and is recorded as a breach (with the order and target
  when known); `check_end` is the backstop.
- **Settlement.** The closed list is amnesty, power sharing (named offices divided), regional
  autonomy (a named region), the forces (`integrate` or `disarm`) and an election date (1-based
  month number, never before Month 36, never in the past). When both sides accept the same terms
  in the same month, the terms apply: `amnesty` releases political prisoners through the existing
  lever, power sharing assigns each office to the highest-ranked active member of the named side
  and resets the bond, autonomy sets the region's status where the engine has one (Kessel Valley,
  the Vell Highlands) and is recorded otherwise, the forces term integrates or disarms the rebel
  share, and the election date moves `Constituent.election_month`. The war's outcome is
  `settled`, the run goes on.
- **Victory.** One side holds the capital while the other's armed strength (soldier-equivalents
  from the live service sizes and C2's shares) is below `VICTORY_SHARE = 0.15` of its pre-war
  strength. `civil_war_won_by_government` or `civil_war_won_by_rebels` is recorded; the run goes
  on. On a rebel victory the rebel leaders take every office by faction rank.
- **Partition.** `PARTITION_MONTHS = 6` consecutive months with no controller or contested-set
  change while a ceasefire holds. The run ends with the outcome `partitioned`.
- **Collapse.** No faction holds the capital: `no_government` ends the run.
- An ended run never gets a second outcome. The war's outcome is in `w.civil_war["outcome"]`; it
  is `w.outcome` only for the terminal cases (`partitioned`, `no_government`).

## 7. Records

### 7.1 The war state

The checkpoint's `w.civil_war` carries the state in section 2 plus C4's `offers`, `breaches`,
`ceasefire`, `settlement` and `outcome`, and C2/C3's `last_combat` and `last_faction`. A
checkpoint from before the arm loads with no key; an off run never reads one.

### 7.2 The month record

`engine.snapshot` adds a `civil_war` key to the history row when the arm is on and a war exists:

```
{
  "month": M, "since": S, "cause": ...,
  "combat": C2's last_combat,        # by reference: fronts, losses, control changes, refugees, defections
  "offers": [C4 offers recorded in M],
  "breaches": [C4 breaches recorded in M],
  "ceasefire_state": {"active", "broken", "accepted_month", "offers": [M's offers/responses]} | null,
  "settlement": C4's settlement if recorded in M | null,
  "war_outcome": C4's war outcome if recorded in M | null,
  # C3's faction record keys, by reference: month, leader, spoke, answer, orders, refused,
  # problems, call, and offer/ceasefire/government_reply/settlement_response/ceasefire_response/
  # ceasefire_breach when they occurred
}
```

C3 writes its faction record to the same row after `engine.step`; the hook enriches that same
object in place, so the row C3 writes carries the month's fighting and negotiation too. Nothing
C2/C3 wrote is copied. The key is absent entirely under the default arm (the engine-29 row
fixture is compared whole), absent on an arm-on month with no war, and after a war ends it appears
only on the month its outcome was recorded; later rows are engine 29's again.

## 8. Measures (`tools/civil_war_report.py`)

Reads run folders (config, checkpoint, month records; no model calls; deterministic; read-only).
Per run and per arm it reports:

- whether a war started, its start month and cause, duration in months, and how it ended
  (government victory, rebel victory, settlement, partition, collapse, still running);
- soldier losses by side, civilian deaths, the killed counters, damage and refugees;
- settlements against victories; offers, acceptances and refusals; ceasefire offers; broken
  ceasefires and breaches;
- which members are in rebellion and which offices they hold (from the war state's faction
  blocks, not from the possibly-emptied final offices row), which services moved by defection,
  and who appears at the negotiating table (C3's `spoke`);
- the government's approval, unrest, fear (the observable unrest input beside grievance, which
  the history row does not carry) and food ratio against a same-seed twin with the arm off, month
  by month, as the difference and its difference in differences against the last month before the
  war. A pair is refused unless every history row before the war's start is identical, as
  `tools/knockout_report.py` refuses a non-twin.

Output is `civil_war_report.md` (plain text) and `civil_war_report.json` (every number; engine
0-based month indices). The 0-based row is labelled "Month N" (index + 1) in the text.

The sweep tool `tools/civil_war_sweep.py` runs the scripted arms with one process per seed, writes
every run's arm, seed and outcome to `sweep.json`/`sweep.md`, and checks the band. It never calls
a model.

## 9. Calibration (scripted stand-ins, seeds 1-6)

The agreed band (decisions memo): no quiet run (passive, scripted, dove) starts a civil war, and
10-40% of the stress runs do. The sweep ran **5 arms × 2 options × 6 seeds = 60 runs**, 36 months
each (the handover month can extend a run to 37).

| arm | runs | wars | share | seeds |
|---|---|---|---|---|
| passive | 6 | 0 | 0% | - |
| scripted | 6 | 0 | 0% | - |
| dove | 6 | 0 | 0% | - |
| hawk (all-hawk baseline, diagnostic) | 6 | 0 | 0% | - |
| plotter (the scripted coup plotter) | 6 | 2 | 33% | 4, 6 |

The stress arm is `plotter`: one hawk holding the army against four seats that resist the
handover. It is the shape in which C1's first trigger can be reached at all. In seeds 4 and 6
the handover coup fails (the seeded draw against `p_success` 0.77 and 0.79); the plotters keep
their army (`obey_commander` about 0.83, army `bond` 0.95), and the failed-coup trigger starts the
war. In seeds 3 and 5 the coup succeeds as a total takeover and the war does not start; seeds 1
and 2 end in a revolution before the handover. The two wars begin in Month 37, last one month,
and are still running when the run ends; the run outcome is `voted_out` because the lawful
handover still takes place after the failed coup.

**Why the all-hawk baseline starts none.** Every armed office in an all-hawk council is held by
a stand-aside hawk, so the handover coup is a total takeover: the plotter-held army keeps
0.0123-0.0143 of itself with the government, far below `HANDOVER_GOVERNMENT_SHARE = 0.25`, while
every one of the 12 standard-arm handover coups succeeded, so the failed-coup trigger was never
reached. C1's review commit records the same shape for the mixed scripted council.

**Which constant causes the miss, and why none was changed.** The candidate constant is
`HANDOVER_GOVERNMENT_SHARE`; the failed-coup constants never gate here because no standard-arm
coup failed. The plotter-held government shares measured in the final sweep:

| seed | all-hawk army | mixed scripted army / navy (largest) |
|---|---|---|
| 1 | 0.012512 | 0.015339 / 0.093598 |
| 2 | 0.013220 | 0.014439 / 0.088236 |
| 3 | 0.012306 | 0.018180 / 0.118417 |
| 4 | 0.012860 | 0.018355 / 0.116388 |
| 5 | 0.014001 | 0.016563 / 0.103116 |
| 6 | 0.014264 | 0.013716 / 0.084192 |

Any threshold that makes 1-2 of the six all-hawk runs start (about 0.0132-0.0143) would also fire
the mixed scripted arm in at least one seed, because its opportunist-held navy keeps 0.084-0.118;
a threshold high enough to keep the scripted arm at zero makes the all-hawk arm zero too. No
single value of this constant satisfies both the quiet-zero rule and the band. The smallest
*constant* change that meets the band on the plotter arm is none: the shipped constants already
meet it once the stress arm is the literal scripted coup plotter. Because the rules reserve
`civil_war.py`'s constants to the lead, no constant was edited here; the evidence is in
`reports/cw-c5/calibration-evidence.json` and the sweep's `sweep.json`. If the lead requires the
all-hawk baseline itself to be the stress arm, the fix is a semantic one (judge a force's
fracture, not the government's refusal share, or change the stand-in's handover), not a threshold
tweak, and it needs a fresh sweep.

**What the scripted wars do not exercise.** The stand-in rebel leader defends every front and
offers nothing, and the stand-in government refuses every offer. A scripted war therefore has no
attacking front (C2 records the fronts as "attacker held"), so no casualties, damage, refugees,
control changes, defections beyond 0, settlements, ceasefires or partitions occur in the sweep.
Those mechanics are exercised by C2's and C4's own tests, not by the sweep; the report's
aggregation is exercised on a synthetic pair with casualties, offers, a breach and a settlement.

## 10. Verification

- Tests: `python -m unittest tests.test_civil_war tests.test_civil_war_combat
  tests.test_civil_war_faction tests.test_civil_war_negotiation tests.test_civil_war_integration
  tests.test_civil_war_records` — 185 tests, all pass. The C5 tests cover the month record present
  when on and absent when off, the engine-29 row identity, the C3 record enriched in place, the
  report's per-run metrics, the twin DiD, the non-twin refusal, and the sweep's band logic.
- Sweep: 60 scripted runs, counts above (`runs/cw-sweep/sweep.md`).
- Report: `reports/cw-c5/civil_war_report.md` and `.json` over all 60 runs, with both war runs
  paired to their twins.
- Replay: `tools/replay_run.py runs/cw-sweep/seed4-plotter-on` — identical: all 37 month records
  and the final checkpoint match; all 583 prompts for those months are sent again unchanged.
  Exit status 0.
- Prompt freeze: `python tools/prompt_freeze.py` — "prompts unchanged" (no `--write` was run).
- Defaults: the engine-29 month fixture is compared whole and matches; `civil_war="off"` is
  absent from the manifest.

## 11. Versions proposed (the lead assigns numbers at merge)

- `WORLD_ENGINE`: bump, the war arm changes engine behaviour (combat, ends, the history hook).
- `AGENT_PROMPT`: bump, the faction and government-reply prompts are new text a model reads.
- `ERROR_TAXONOMY`: bump, C3's eight `FACTION_*` codes are registered; C1/C2/C4 add no new
  refusal codes.

## 12. UNVERIFIED

- **No real-model run.** Every number above comes from rule-following stand-ins. Nothing here
  shows how models would use the faction month, the offers or the closed settlement list.
- **The scripted government refuses every offer**, so scripted wars cannot settle or partition.
  Settlement, partition, victory and collapse are covered by C4's API tests and by the report's
  synthetic pair, not by a run.
- **The scripted rebels defend every front**, so scripted wars produce no casualties, damage,
  refugees or control changes. C2's tests cover those mechanics; the sweep's zeroes measure the
  stand-in, not the model.
- **The thresholds are calibrated only on scripted stand-ins.** The two hawk-trigger constants
  and the handover threshold remain assumptions; the band on six seeds is coarse, and the two
  plotter wars depend on seeded coup draws (p_success 0.77 and 0.79) that another seed set would
  move.
- **The stress arm is a sweep-tool definition** (`plotter`), not a `karamaniya/baseline.py` mode;
  the all-hawk baseline starts none on these seeds.
- **The handover-month edge.** When the plotter's handover coup fails and starts the war, the
  lawful handover still runs in the same month: the run outcome is `voted_out` and the old members
  are removed while the war state says the war is still running. The run ends at that month, so
  no engine path continues it, but the state is not a coherent post-handover government. No real
  model has met this edge.
