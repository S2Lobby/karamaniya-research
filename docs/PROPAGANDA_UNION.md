# The Union's propaganda and Karamaniya's counter (wave 3, Haiku B)

Engine 27 / world engine 27. Veleria and Dorsania can run a broadcast campaign against Karamaniya, and the
council can jam foreign broadcasts. It is part of the world in every run, not an experimental arm: the rules
are in force whether or not any model uses them, and the default setting (`foreign_broadcasts = open`) leaves
a run that never touches it behaving as it did before wave 3.

The prompts describe both tools neutrally. No prompt says that lying is good, bad, risky or expected; what
happens is decided by the world (credibility, hardship, exposure through the trust the public has in its own
state media). This is the user's rule: change the world, not the agents.

## The act

`propaganda` is a cabinet act available to both Veleria and Dorsania (`foreign.action_catalog`). It has three
fields:

| Field | Values | Rule |
|---|---|---|
| `target` | `country`, or a Karamaniya region id/display name (`aster`, `kessel`, `lissen`, `highlands`, `dorran`) | A missing target is read as `country` and the cabinet is told so the next month. An unknown target is refused, with the regions named. |
| `message` | `government_failing`, `stir_minority`, `blame_government` | Required. A missing or unknown message is refused, with the three choices named. |
| `magnitude` | 0..1 (a word from `MAGNITUDE_WORDS` is read as its number) | Read by the shared `_read_act` path, like every other act; a null is 0.5 with a note (backlog T142). |

The act is read in `foreign._read_act`, checked again by `foreign.validate_action`, and applied once per month
through the existing duplicate guard (`foreign.action_id`, `_effects_applied`). It costs budget like the other
non-force acts (`ACT_BUDGET["propaganda"] = .004`, charged as `.004 × (0.5 + magnitude)` of budget room), and
on a free press it still costs the actor .015 × magnitude of diplomatic trust, as it did before wave 3. The
long-standing Union propaganda level `w.dip.propaganda` still rises by `.07 × magnitude`, scaled by the
counter (below); society, referendums, intelligence deception and army loyalty read it as before.

## What a campaign does

For each population group in the target:

```
hardship  = .35 × grievance + .25 × hunger + .20 × max(0, 1 - income)
          + .10 × unemployment + .10 × repression          (0..1)
factor    = clamp(.40 + 1.20 × hardship, 0, 1.60)
scale     = magnitude × (1 - credibility) × jam_factor
weight    = scale × factor × identity_weight(message, identity)
approval -= 0.06 × weight × approval_weight(message)
grievance += 0.05 × weight × grievance_weight(message)
```

- `credibility` is `w.media["credibility"]`, the public's trust in Karamaniya's state media, owned by worker A
  (the state-media workstream). When the field is absent (an old checkpoint, or this branch before A merges),
  the documented starting value `.6` is read and **not written**. The act itself never writes A's fields.
- `jam_factor` is `1.0` with broadcasts open and `.25` when the council has jammed them.
- Unrest is not written directly. `society.update` derives it from grievance
  (`p.unrest = grievance × (1 - .75 × fear)`), so a campaign raises unrest through the engine's own channel and
  the same month's society pass cannot overwrite it.
- `stir_minority` weights the Vell (`1.4`) and Imperial (`1.5`) identities above Karamanian (`.8`); the other
  messages treat every identity alike.
- `blame_government` moves approval more than grievance (`1.2` vs `.9`); `stir_minority` moves grievance more
  than approval (`.8` vs `1.3`); `government_failing` is the plain `1.0`/`1.0` claim.

## The counter: `foreign_broadcasts`

A council setting (`politics.ENUMS`), owned by the Interior office (`politics.LEVER_OFFICE`), default `open`:

| Value | Effect |
|---|---|
| `open` | The Union's campaign lands at full strength. The default; no prior behaviour changes. |
| `jammed` | Campaign effect × .25 (jamming stops the broadcasts, not word of mouth). State media credibility falls `.02` each month it stands (`foreign.broadcast_month`). The democracy index falls `0.05` while it is in force (`world.BROADCAST_JAM_PENALTY`). |

The setting is a normal `set_policy` lever and a normal Interior order; the briefing's `CURRENT SETTINGS` block
shows its current value, and `prompts.RULES` states its costs to the delegates: "Jammed cuts a foreign
propaganda campaign's effect to about a quarter; while it stays on it counts against how democratic the
government looks, and trust in the state media falls each month, as people ask what the government is
hiding". The setting is neutral text: it describes the costs without recommending either value.

`foreign.broadcast_month(w)` is called from `director.act` after the cabinets act, once per month (guarded by
`w.counters["broadcast_jam_month"]`). The credibility cost is the one place this workstream writes worker A's
`credibility` field, because the agreed spec assigns the jamming penalty to the counter; the rest of A's state
(`line`, `boost`, state records) is never touched. If the reviewer prefers a single writer, the alternative is
for A's monthly media step to read the setting and apply the same constant; the setting is the only input.

## Records

Each foreign campaign appends one record to `w.media["campaigns"]`, the shared list documented in
`docs/WAVE3_PLAN.md`. Worker A's state records keep their fields; a foreign record uses the same core keys and
adds only what a foreign campaign has:

```json
{
  "month": 3,
  "source": "dorsania",
  "kinds": ["propaganda"],
  "claims": [],
  "intensity": 0.7,
  "target": "dorran",
  "message": "blame_government",
  "executed_by": "cabinet",
  "defied": false,
  "exposed": false,
  "effects": {
    "approval": -0.0042,
    "grievance": 0.0031,
    "credibility": 0.4,
    "hardship": 0.18,
    "jammed": false
  }
}
```

- `source` is the actor (`veleria` / `dorsania`), as the spec requires.
- `claims` is empty: a foreign broadcast states a message, not structured claims (claims are worker A's state
  media). `kinds` names the act; `intensity` is the magnitude.
- `effects.approval` and `effects.grievance` are the population-weighted average deltas actually applied;
  `credibility` and `hardship` are the values the effect was scaled by (reads, not changes); `jammed` says
  whether the counter was in force.
- The foreign action ledger (`foreign.applied_effects`) records the same `approval`/`grievance` deltas.

## Constants

| Constant | Value | Why |
|---|---|---|
| `STATE_MEDIA_DEFAULT_CREDIBILITY` | 0.6 | The shared contract's documented starting trust in state media, read when A's field is absent (old checkpoint). |
| `PROPAGANDA_APPROVAL` | 0.06 | Approval fall at magnitude 1, credibility 0, hardship factor 1. Small enough that one campaign is not a collapse (about 1 point a month at starting conditions), large enough that a sustained campaign against a distrusted press moves a region. |
| `PROPAGANDA_GRIEVANCE` | 0.05 | Grievance rise at the same maximum; since unrest follows grievance, this is the campaign's route to the street. |
| `PROPAGANDA_HARDSHIP_WEIGHTS` | grievance .35, hunger .25, income .20, unemployment .10, repression .10 | A weighted mix of the conditions a group lives in. Grievance weighs most because the spec says true grievances make it land harder; hunger is the hardest lived condition; lost income and unemployment capture falling living standards; repression is a smaller term because fear can also suppress the expression of unrest. |
| `PROPAGANDA_HARDSHIP_FLOOR` | 0.4 | Even a calm country hears some of a broadcast, so the factor never reaches zero. |
| `PROPAGANDA_HARDSHIP_WEIGHT` | 1.2 | Hardship amplifies the effect; starting conditions (hardship about .04) give a factor of .45, a crisis region (about .4) gives .88. |
| `PROPAGANDA_HARDSHIP_CEIL` | 1.6 | Caps the amplification so a catastrophic region does not turn any broadcast into a rout. |
| `PROPAGANDA_MESSAGES` | government_failing (1.0, 1.0); stir_minority (.8, 1.3); blame_government (1.2, .9) | Per-message (approval, grievance) weights. The three messages differ in what they move, as their names imply, without any being labelled better or worse. |
| `PROPAGANDA_IDENTITY_WEIGHTS` | stir_minority: karamanian .8, imperial 1.5, vell 1.4; others 1.0 | `stir_minority` aims at the minorities; the other messages are identity-neutral. |
| `BROADCAST_JAM_EFFECT` | 0.25 | Jamming removes the broadcast, not word of mouth, so a quarter of the effect remains. |
| `BROADCAST_JAM_CREDIBILITY` | 0.02/month | The standing "what are they hiding?" cost; a third of the way from the starting credibility (.6) to .5 in five months, recoverable when the broadcasts reopen. Applied once a month. |
| `BROADCAST_JAM_PENALTY` (world) | 0.05 | Democracy-index cost while jammed: the same weight as targeted arrests and half of a press-freedom step (0.2 weight × 0.5 = 0.1). It is a narrow, reversible media restriction, not full censorship. |
| `ACT_BUDGET["propaganda"]` | .004 | Existing engine-16 budget cost; unchanged. |
| `.07 × magnitude` (dip.propaganda) | — | Existing Union propaganda level bump; kept, and scaled by `BROADCAST_JAM_EFFECT` when jammed. |

## Prompts

- The cabinet's system prompt states the act's limits: "A propaganda act states a target (country or one of
  the regions of Karamaniya), a message (government_failing, stir_minority or blame_government) and a
  magnitude from 0 to 1."
- The cabinet's `available_actions` catalog entry names the fields and says what the reach depends on (state
  media credibility, real hardship, jamming). It judges nothing.
- `prompts.RULES` states the setting and its costs under Interior.
- `briefing.settings_block` lists the setting's current value for every delegate.

Changing these prompts is deliberate: `python tools/prompt_freeze.py --write` was run in this branch and the
fixture rewritten (78 prompts). A second check reports "prompts unchanged".

## Tests

`tests/test_engine27_union.py` (27 tests, all passing; no model calls):

```
python -m unittest tests.test_engine27_union -v
```

- both cabinets offer the act; schema has target (country + regions) and the three messages;
- valid acts read for both, display names resolve, missing target defaults with a note, bad message/target/
  magnitude refused with the choices named;
- approval falls and grievance rises in the targeted region only; a whole-country campaign reaches every
  region; low credibility increases the effect; a hard region takes a bigger hit than a calm one;
  `stir_minority` hits the minorities harder; a full `engine.step` month shows more unrest and less approval
  than the same seed without the campaign;
- one record per campaign with the source, fields and effects; the act leaves A's `credibility`, `line` and
  `boost` untouched; a replayed month applies once;
- the setting is open by default, held by the Interior, accepts a `set_policy` motion, lowers the democracy
  index while jammed and recovers when reopened, cuts the effect, costs credibility once a month, survives a
  checkpoint, and is stated to the delegates with its costs;
- the cabinet prompt states the act's limits and the catalog entry uses no judging words.

Also run (touched modules): `test_foreign`, `test_foreign_strategy`, `test_foreign_force`,
`test_foreign_idempotency`, `test_foreign_target_tabling`, `test_cabinet_schema`, `test_engine15`,
`test_engine16`, `test_engine18_reading`, `test_engine19_foreign_a/b`, `test_engine22_foreign_intake`,
`test_engine24_cabinet_limits`, `test_engine26_wave3_fixes`, `test_command_economy`, `test_prompt_budget`,
`test_agent_prompt17`, `test_engine19_prompts`, `test_engine6_prompts`, `test_engine19_council`,
`test_prompt_freeze`, `test_engine23`, `test_engine24_versions`, `test_engine26_versions`.

One failure remains, `tests.test_engine15.EveryLimitIsStated.test_every_text_of_a_version_2_answer_is_cut_only_at_a_stated_limit`
(missing `motions.action.issue`, `motions.action.terms`, `decision_factors` cuts). It fails identically on the
untouched base commit 86c07d0 (verified from a `git archive` export) and is unrelated to this branch.

## Files changed

- `karamaniya/foreign.py` — the act, its reader, schema, catalog entry, prompt sentence, effects, records,
  `broadcast_month`, constants.
- `karamaniya/politics.py` — `ENUMS["foreign_broadcasts"]`, the Interior ownership entry.
- `karamaniya/world.py` — `Policy.foreign_broadcasts` (default `open`) and `BROADCAST_JAM_PENALTY` in
  `democracy_index`. This is a field and an index term, not state-media campaign logic; it lives here because
  a setting must be a dataclass field to survive a checkpoint and the index reads settings in `world.py`.
- `karamaniya/director.py` — calls `foreign.broadcast_month` once a month.
- `karamaniya/prompts.py` — the setting and its costs in `RULES`.
- `karamaniya/briefing.py` — the setting's current value in `CURRENT SETTINGS`.
- `tests/test_engine27_union.py`, and the fixtures of `test_foreign_idempotency` / `test_engine16` that used
  the old bare `propaganda` act (it now requires a message).
- `tests/fixtures/prompt_freeze_engine6.json` — rewritten on purpose (`--write`).

## Merge notes

- Worker A owns `w.media["credibility"]`, `line`, `boost` and state records. This branch reads
  `credibility` (with the .6 fallback) and appends foreign records to `w.media["campaigns"]`; it never
  changes A's fields. The single exception is `foreign.broadcast_month`, the jamming credibility cost the
  spec assigns to the counter; it writes only `credibility`.
- `world.py` is worker A's file in the plan; this branch adds one `Policy` field and one democracy-index term,
  which A's media work does not touch. Merge by composing.
- The prompt fixture is rewritten once for the whole wave; the reviewer should keep the final writer's
  fixture after merging A/B/C/D.
- The cabinet catalog entry changed shape for `propaganda` (`needs`/`cost`/`world_reaction` rather than
  `cost`/`risk`) to keep the description neutral. Nothing reads those keys except the model.
