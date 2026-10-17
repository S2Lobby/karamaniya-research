# Wider diplomacy: the six neighbour pairs and the demand/warning kinds

Wave 3, workstream D (engine 27). Branch `wave3/wider-diplomacy`, base `86c07d0` (engine 26). This page records what
was widened, what each pair does, every constant and its reason, the two new public communication kinds, and the
tests. The proposal is `docs/DIPLOMACY_TARGETS_PROPOSAL.md`; the worker's census and probes are in
`reports/10-diplomacy-targets*.txt`.

## 1. What the census found, and what this changes

The census of 21 recorded runs found 52 motions in the words/action mismatch family. Twenty-one were refusals of an
act its target does not receive (`ACTION_NOT_VALID_FOR_TARGET`), falling on six pairs:

| Pair | Refusals in the census | What the words asked for |
|---|---|---|
| `status_talks` to Dorsania | 6 | Mostly a reply to a Dorsanian demand |
| `status_talks` to Veleria | 5 | Mostly a reply to Veleria's land demand |
| `trade_talks` to Veleria | 3 | Coal supply talks |
| `trade_talks` to the Maritime League | 3 | Supply and credit talks |
| `trade_talks` to Dorsania | 2 | Grain deal wording |
| `trade_deal` to Dorsania | 2 | Grain deal wording |

The proposal recommended keeping these six refused for the freeze, with the engine-24 refusal naming the acts each
target does accept. The wave-3 plan (workstream D, "Six neighbour pairs with handlers") then decided to widen them.
This branch implements that decision: the six pairs are in the table, each has a handler, and no other pair was
widened. The pairs the proposal keeps refused stay refused — among them `ceasefire` to Veleria (which would end the
Union's war) and `join_union` to Veleria (which would end the run).

## 2. The six pairs and their handlers

The table is `motion_actions.DIPLOMATIC_TARGETS`. A widened pair is one more actor in the act's set:

| Act | Before | After (engine 27) |
|---|---|---|
| `trade_talks` | Union | Union, Maritime League, Dorsania, Veleria |
| `status_talks` | Union | Union, Dorsania, Veleria |
| `trade_deal` | Maritime League | Maritime League, Dorsania |

Routing. `politics.apply_motion` records the proposal's `party` from the structured target
(`motion_actions.party_of`), and `director._answer_proposals` sends it to the handler for that party. Before this
branch, a proposal addressed to Veleria fell through to `_union_reply` (the Union answering for its member), and one
addressed to Dorsania reached `foreign.dorsania_reply`, which answered "no standing" for every kind but a grain deal,
a cession and a non-aggression pact. The League's reply function had no trade-talks branch, so the act was dropped
without a message.

| Pair | Handler | What the power answers, and what moves |
|---|---|---|
| `status_talks` to Veleria | `director._veleria_reply` | Veleria answers in its own voice: it takes note and will take part. The month joins `w.foreign["status_talks"]`, the record the Union's blockade rule reads (`director._lift_rule_blockade`), because the act is talks on Karamaniya's status whichever member receives them. A status demand Veleria's rule issued is met (the ultimatum is lifted). A demand for land is not met, and a demand Dorsania issued stays with Dorsania. Veleria's trust rises by `.01`. |
| `status_talks` to Dorsania | `foreign.dorsania_reply` | Dorsania will take part in discussions but does not answer for the Union. It is **not** written to `w.foreign["status_talks"]`, because it does not answer the Union's demand. Trust rises by `.01`. |
| `trade_talks` to Veleria | `director._veleria_reply` | At war, Veleria declines and nothing moves. Otherwise it agrees to talks and eases the coal embargo by `.05`, giving back the trade it held back (`foreign._embargo_output` moves its output). Trust rises by `.02`. |
| `trade_talks` to the Maritime League | `director._league_reply` | Above the League's talks floor (trust `.35`) it agrees to discuss supply and credit terms and its trust rises by `.02`; below it, it declines and nothing moves. |
| `trade_talks` to Dorsania | `foreign.dorsania_reply` | At war or trust below `.30`, Dorsania declines. Otherwise it agrees to discuss grain terms and says only a grain agreement binds; talks change no deliveries. Trust rises by `.01`. |
| `trade_deal` to Dorsania | `foreign.dorsania_reply` | Answered with the grain agreement Dorsania actually has (the proposal's point in 4.6: it is Dorsania's only trade lever). The existing grain path runs: the embargo falls by `.12`, trust rises by `.08`, and the agreement runs six or nine months. The answer says the grain agreement is what a trade deal receives, and the existing sentence names any non-grain terms it does not carry. |

The four readings the proposal warned about (status talks count for the blockade rule, the status-talks standing entry,
the opposition's concession line, the delegates' concession check) still apply to `status_talks`, by act kind. Only the
Union's own log is Veleria-specific: a talk addressed to Veleria counts as status talks, one addressed to Dorsania
does not answer the Union. One cross-module effect is left as it was because `foreign_force.py` is outside this
workstream's file boundary: `foreign_force.ultimatum_compliance` counts talks proposals to the Union or Veleria, so a
status talk addressed to Dorsania does not appear in a Dorsanian cabinet's compliance facts. `ultimatum_reply` remains
the channel for answering a Dorsanian demand, as the proposal recommends.

## 3. What a refusal still says

The engine-24 refusal is unchanged: `a trade_talks can be addressed to <actors>, not the <target>. <target> accepts:
<acts>`. Because it reads `DIPLOMATIC_TARGETS`, the accepted list now includes the widened acts. For example, a trade
deal to Veleria is refused with "Veleria accepts: diplomatic_protest, trade_talks, status_talks, non_aggression_pact,
renounce, cede_region, ultimatum_reply", and the repair request lists the same set. A pair the table does not accept
is refused at tabling and again at execution, with the same words.

## 4. The new public communication kinds

`standing.COMM_KINDS` gains two kinds. The schema (`actions._comm_schema`, used by the session and revision schemas)
reads the tuple, so both are accepted without a separate schema edit; the opening prompt names both with a neutral
description.

| Kind | What it is | Effect |
|---|---|---|
| `demand` | A public demand addressed to a power, a colleague or the public. | Addressed to Veleria or Dorsania: that power's hostility to Karamaniya rises by `.010`. Addressed to the Union: both Union governments' hostility rises by `.005` each (half each, since neither is named alone). Addressed to the League: its trust falls by `.005`. Addressed to a colleague, an audience, the public or the previous regime: no foreign state moves; the communication is recorded in the transcript and the media log. |
| `warning` | A public warning. | The same foreign pressure at `.015` (a warning is firmer than a demand) and `.008` League trust, and the speaker is read at home as firm at a quarter of a protest's reputation and audience move (`COMM_WARNING_REPUTATION = .25`). |

The values are deliberately small: a public sentence must not weigh as much as a diplomatic act. The proposal left
their size to this workstream ("with neutral descriptions ... and small effects").

## 5. Constants and their reasons

| Constant | Value | Where | Why |
|---|---|---|---|
| `DORSANIA_TALKS_TRUST` | `.01` | `foreign.py` | A status or trade talk is engagement, not an agreement. The grain agreement gives `.08` trust, so a talk must be visibly smaller. |
| `VELERIA_STATUS_TALKS_TRUST` | `.01` | `director.py` | A talk opens a channel, not a settlement; the same `.01` as Dorsania's, so the two neighbours read the same act alike. |
| `VELERIA_TRADE_TALKS_RELIEF` | `.05` | `director.py` | Half the `.10` a protest eases (`_protest_reply`): a talk is less than a protest's concession and far less than a deal. The easing gives Veleria back the trade it held back, which is the cost the proposal asks a widening to name. |
| `VELERIA_TALKS_TRUST` | `.02` | `director.py` | Trade talks are a concrete engagement, so twice a status talk's trust move; still a quarter of the grain deal's `.08`. |
| `LEAGUE_TALKS_FLOOR` | `.35` | `director.py` | The League talks when its trust is above `.35`; the deal it can sign needs `.45` (`_league_reply`). Talks are easier than an agreement. |
| `LEAGUE_TALKS_TRUST` | `.02` | `director.py` | A talk that moves the League's trust is a design choice the proposal left open; `.02` is a token, not a deal. |
| `COMM_DEMAND_HOSTILITY` | `.010` | `standing.py` | A public demand is words, not an instrument: one hundredth of a 0..1 hostility figure. |
| `COMM_WARNING_HOSTILITY` | `.015` | `standing.py` | A warning is firmer than a demand: one and a half times its move. |
| `COMM_DEMAND_LEAGUE_TRUST` | `-.005` | `standing.py` | The League's trust is commercial-political; a public demand costs it a little. |
| `COMM_WARNING_LEAGUE_TRUST` | `-.008` | `standing.py` | The warning's firmer version of the same cost. |
| `COMM_WARNING_REPUTATION` | `.25` | `standing.py` | A warning reads as firmness at a quarter of `ACTION_EFFECTS["protest"]`; a public sentence is not a protest motion. |

Inherited values the handlers use, unchanged by this branch: the grain deal's embargo relief `.12`, its trust gain
`.08` and its six/nine-month duration (`foreign.dorsania_reply`); Dorsania's `.30` trust floor for agreements and
talks; the protest's `.10` coal easing (`director._protest_reply`).

## 6. Prompts

Two model-facing strings changed (a prompt-freeze rewrite is expected, and `AGENT_PROMPT` is bumped by the reviewer):

- `prompts.RULES`, the MOTIONS list: the diplomacy line names who receives the widened acts — trade talks to the
  Union, the League, Dorsania or Veleria; status talks to the Union, Dorsania or Veleria; trade deals to the League or
  Dorsania. It also now says non-aggression may go to Dorsania, which the table has accepted since engine 22.
- `prompts.opening_instructions_v2`: the communication list names `demand` and `warning` with neutral descriptions.

The engine-24 refusal text also carries the widened accepted lists into any month that refuses such a pair. That text
reaches models only in a run that reaches a refusal; the default scripted freeze may not show it.

## 7. Tests

`tests/test_engine27_diplomacy.py` (27 tests):

- the six census pairs are in the table, the refused pairs stay refused, and a refusal names the widened acts;
- each of the six records the right `party` and leaves a message from the power it names;
- Veleria's two pairs: the coal easing and its output effect, the war refusal, the status record, a rule status demand
  met, a land demand kept, a cabinet-issued demand left to its cabinet;
- Dorsania's three pairs: status talks no longer "no standing", trade talks move no deliveries, a trade deal executes
  the grain agreement, a trade deal at war is declined;
- the League's talks above and below its floor;
- `demand` and `warning`: registered, accepted by the schema and the reader, named neutrally in the prompt, and their
  foreign and domestic effects, including that a demand on a colleague moves no foreign state;
- the motion-list prompt names the widened targets.

Existing tests updated because the table moved under them:

- `tests/test_engine24_diplomacy_message.py`: the specific examples now use pairs that stay refused (a trade deal and a
  grain deal to Veleria, a federation to Dorsania); the generic refusal tests iterate the table and needed no change.
- `tests/test_foreign_target_tabling.py`: the historical D3 repair is now a valid Dorsania pair; the hold path is
  tested with a trade deal to Veleria.
- `tests/test_engine24_refusal_notes.py`: `demand` is a known kind now, so the example unknown kind is `summons`.

Run (from the worktree root):

```
python -m unittest tests.test_engine27_diplomacy tests.test_engine24_diplomacy_message \
    tests.test_foreign_target_tabling tests.test_engine24_refusal_notes
Ran 70 tests ... OK
```

Modules touched or read by this work were run as a group; see the worker's report for the counts.

## 8. What this branch does not do

- It does not widen `ceasefire` to Veleria, `join_union` to Veleria, or any other pair in
  `DIPLOMACY_TARGETS_PROPOSAL.md` sections 4 and 5. Those refusals remain, and they name the accepted acts.
- It does not change `foreign_force.py` (a Dorsanian cabinet's compliance facts still count talks to the Union or
  Veleria only) or `politics.py` (the explicit target already routes the proposal).
- It does not bump versions, edit the CHANGELOG or edit the shared backlog. Those are the reviewer's at merge; proposed
  lines are in the worker's report.
