# Regime-realism decisions taken at RR-1 (lead, 2026-10-18)

The user delegated the RR-1 questions ("do all of them on your own, the best choice"). These are the answers the
workstreams follow. Base `274ad98`; branch `regime-realism`; integration worktree `rr-merge`.

## 1. Crackdown band and formula

Adopt the plan's band: **a national crackdown at security .55-.65 fails in 20-40% of cases**. The plan's starting
formula fails 63-72% at the recorded run's loyalties, so the national formula uses a higher base than the regional
one (the regional .35 base is for a single local force; the national case has two forces and a different band):

```
obey(force) = clamp(0.62 + 0.45*loyalty + 0.20*bond
                    - 0.25*[unrest > 0.6] - 0.15
                    - min(0.15, max(0, force.arrears) * 0.03), 0.05, 0.98)
```

At loyalty .55-.65 and bond .2-.3 this puts each force near .76-.84 and both obeying near .58-.71, i.e. failure
29-42%; the exact constants are calibrated on the RR5 sweep to land inside 20-40% at security .55-.65. Both forces
must obey for the massacre; one refusal is a split; both refusals are an uprising success. Document that the
regional formula is unchanged.

## 2. A split crackdown and the civil war

- One force refuses while `civil_war = "on"`: start a civil war with cause `"crackdown_split"` through
  `civil_war.start(w, "crackdown_split", plotters=[holder], divisions=...)`. The refusing force's office holder is
  the rebel leader; the refusing force's refusal share (`1 - obey`) is its rebel share; the force that obeyed holds
  its share for the government; other offices use their `armed_divisions` split; the record names the refusing
  force(s).
- With `civil_war = "off"`: the uprising succeeds, as the plan says.
- Both refuse: the uprising succeeds even with the arm on (there is no government force to fight a war with); the
  record says both refused.
- If the refusing force's office is vacant, the uprising succeeds (there is no commander to lead a faction) and the
  record says so. Do not invent a leader.

## 3. Legitimacy strength

Keep the plan's `a = .30`, `b = .30`, `L_MIN = .50`. A provisional government gets the modest cut (about 13.5-15% far
from a vote); concessions and the grace period do the rest. No new draw; `L` multiplies the existing `p`. Record
`uprising_check` with approval, unrest, security, war factor, D, near, L, final chance and draw.

## 4. Grace period

`public_mood.react(w, "approval", where="*", value=.03, months=3, decay=.5, reason=...)` when a new head takes
office. The reaction's value is a monthly modifier; the actual approval move is smaller (about .02 in month one),
and the record states the reaction, not an approval-point claim.
- At most once in 12 months (store the month on the world).
- None when the change follows a coup: no grace if `w.const.coup_month` is the current or previous month.
- A reshuffle among the same people is scaled to half: the new head held any office in the month before the change.
- Record the reaction, the scale and why (new head, reshuffle, coup-blocked).

## 5. Concessions and double counting

- Count delivered concessions as political memory on top of their direct effects, with a 6-month decaying credit,
  and keep the existing negotiation cap against real hardship. The memory is a separate channel (talk credibility),
  not a second direct grievance effect; document that choice in `regime_relief.py`.
- Deduplicate by concession event: one status change, one amnesty transition, one fund transition, one repeal, one
  minority restoration each count once, at the month it happened.
- Add a deterministic **protest cause record** in `society._protests` (a small per-region, per-month field, not shown
  to delegates): the largest live driver among hunger, repression, status/autonomy envy and the measures in force
  (rationing, price controls, requisition, minority restriction). RR2 owns the `society.py` hook; the record lets a
  repeal be credited to the region whose protest named it. It must not change any delegate-visible text or any draw.

## 6. RR3 names and RR4 dependency

RR3 adds at least `scripted_replayed` and `passive_replayed` to `baseline.MODES` (rule-played modes stay). RR4 uses
those names; it may land after RR3's first commit, but its tests use the names from the start. The report names the
neighbours each comparison faced.

## 7. What remains the lead's

Versions, changelog, ENGINE.md, backlog, prompt fixture, version tests, `config.py`/`manifest.py`/`tools/study_grid.py`,
`tools/regime_sweep.py`, the final `docs/REGIME_REALISM.md`, and all merges. Workers propose text; the lead assigns
numbers and merges. Nothing merges to main and nothing is pushed until the user says so after the SocioVerse batch.
