"""Regime relief (engine 33, regime realism RR2): concessions made credible, and a new head's grace.

Two political memories the world did not have before.

**Concession credibility.** The negotiation branch of `society._protests` relieves grievance by
`0.02 + 0.13 * credibility`, where credibility used to be only the government's approval. A
government that concedes has no way to make talks work while it is unpopular, which is exactly when
it needs them: in run 20261018-014944-seed1 the council granted Kessel and the Vell Highlands
cultural status and kept talks open, and still got the 0.02 floor from Month 9. Under
`uprising_model = "legitimacy"` the branch reads `credibility = max(approval credibility,
concession credibility)`: concessions delivered to the region in the last six months are political
memory, decaying linearly to nothing at six months.

The lead's rule (RR-1 decision 5) is that this memory is a separate channel -- talk credibility --
and does **not** suppress the direct effects the same acts already have (`regional.set_status`
raises approval as it is granted, `politics._apply_amnesty` lowers grievance and fear,
`regional.income_boost` raises incomes). One act therefore has its direct effect and its effect on
whether the government's word carries. The existing ceiling on talks stays: `0.02 + 0.13 * 1.0`
= .15 a month, which cannot outlast the grievance real hardship produces.

The list, the region each is credited to, and the credit before decay (starting values for the RR5
sweep; one strong concession moves talks by a quarter to two-fifths of the channel):

    status upgrade (central -> cultural or devolved)   the upgraded region    .40
    amnesty transition (policy.amnesty -> release)     every region           .30
    regional fund begins funding a region              that region            .25
    repeal of a measure a region's protest named       those regions          .30
    minority restored to equal after a restriction     the Vell Highlands     .35

Deduplication is by event: one status change, one amnesty transition, one fund transition, one
repeal transition and one minority restoration each count once, at the month it happened. The
status record is `regional.state(w)["changes"]`; the rest is read from the history rows' `policy`
and `constitution` blocks, with the live state as the last element of the series. A run that opens
with an amnesty or a fund already in force (a scenario's inherited setting) is credited in its first
month against the engine's defaults, which have neither.

**Protest causes.** A repeal is credited only to a region whose protest named the measure. Nothing
recorded a protest's cause before this module, so `record_protest_cause` writes a deterministic,
capped entry in `w.institutions["protest_causes"]` when a region is protesting: the largest live
driver among hunger, repression, status/autonomy envy and the measures in force. It uses no draw and
no text; it is not read by any prompt. See `_driver_scores` for the weights, which follow the
grievance target's own coefficients where they exist.

**The grace period.** A new head of government starts with public goodwill that erodes (Mueller
1970). Under `legitimacy`, `head_changed` grants one `public_mood.react` approval reaction of .03 a
month for three months, halving each month (the channel's limit, `public_mood.LIMIT`). The decision
not to grant it after a coup, to halve it when the new head was already in the council that lost
the public's trust, and to grant it at most once in twelve months is the lead's RR-1 decision 4. The
reaction's value is a monthly modifier, not an approval-point claim: `society.update` multiplies it
by four into the target the group moves toward, and approval closes 18% of that gap in a month. The
record stores the reaction, the scale and why.

Under `uprising_model = "legacy"` (or an absent option) every function here is inert: `society._protests`
keeps its old formula and writes nothing, `politics.apply_motion` grants no reaction, and a scripted
run is byte-identical to the base (tests/test_rr2_relief.py replays two months recorded on 49a8d5b).

Sources: Mueller 1970, Presidential Popularity from Truman to Johnson (grace period); the plan's
4.3-4.4 and the RR-1 decisions; RR0's section 3 (what each concession already does).
"""
from __future__ import annotations

from . import public_mood, regional
from .economy import REQUISITION
from .world import OFFICES, World, clamp

MODE_LEGACY = "legacy"
MODE_LEGITIMACY = "legitimacy"

CONCESSION_MONTHS = 6          # the plan's political memory: six months, then spent
CAUSE_CAP = 12                 # protest-cause entries kept per region (more than one memory window)
HEAD_CHANGE_CAP = 24           # head-change records kept for the report; nothing reads them back

# Credit before decay, 0..1 after summing and clamping. Starting values: the RR5 sweep calibrates
# them. The order reflects how much of the political settlement each act gives away; the fund is
# the most reversible (a monthly line) and the status grant the most durable (a Charter change).
STATUS_CREDIT = .40
AMNESTY_CREDIT = .30
FUND_CREDIT = .25
REPEAL_CREDIT = .30
MINORITY_CREDIT = .35

# The grace period (RR-1 decision 4). .03 is public_mood.LIMIT, one month's channel maximum.
GRACE_VALUE = .03
GRACE_MONTHS = 3
GRACE_DECAY = .5
GRACE_INTERVAL = 12
RESHUFFLE_SCALE = .5
GRACE_REASON = "new head of government"

# The baseline a run's first state is read against: the engine's defaults. A run that opens with a
# concession already in force (only a scenario can) is credited in its first month.
_BASELINE_POLICY = {"amnesty": "none", "regional_fund": "none", "rationing": False,
                    "price_controls": "none", "requisition": "none"}
_BASELINE_CONSTITUTION = {"minority": "equal"}

# Drivers a protest can name, in the order that breaks a tie. "unrest" is the fallback when none of
# the named drivers is live (unrest can be driven by inflation, unemployment and the like).
CAUSES = ("hunger", "repression", "status", "rationing", "price_controls", "requisition", "minority")
RATIONING_PAIN = .35            # synthetic: the salience of rationing when it is in force
PRICE_CONTROL_PAIN = {"none": 0.0, "food": .25, "all": .35}
MINORITY_PAIN = {"equal": 0.0, "restricted": .4, "interned": 1.0}   # society.MINORITY_OPP, local to avoid a cycle


def model(w: World) -> str:
    """The run's uprising model. Absent means legacy, as checkpoints saved before the option did."""
    value = getattr(w, "uprising_model", None)
    if value is None:
        value = (getattr(w, "institutions", None) or {}).get("uprising_model")
    return str(value or MODE_LEGACY).strip().lower()


def enabled(w: World) -> bool:
    return model(w) == MODE_LEGITIMACY


def state(w: World) -> dict:
    """This module's checkpointed record. Created only under `legitimacy`."""
    return w.institutions.setdefault("regime_relief", {})


# ---- concessions ---------------------------------------------------------------------------
def _pget(src, key: str, default):
    """One field from a history row's policy/constitution dict or from the live dataclass."""
    return src.get(key, default) if isinstance(src, dict) else getattr(src, key, default)


def _states(w: World) -> list:
    """(month, policy, constitution) for each completed month, then the live state."""
    out = [(int(row["month"]), row.get("policy") or {}, row.get("constitution") or {})
           for row in w.history if row.get("month") is not None]
    out.append((w.month, w.policy, w.const))
    return out


def _funds(value) -> set:
    return set(regional.REGIONS) if value == "both" else ({value} if value in regional.REGIONS else set())


def _regions(w: World) -> list:
    """Every Karamaniya region, including one currently held by rebels: a national concession is
    still remembered there if the government talks its people down later."""
    return [r.id for r in w.regions if r.nation == "karamaniya"]


def _cause_named(w: World, region: str, measure: str, month: int) -> bool:
    """Whether this region's protests named `measure` in the memory window before `month`."""
    for entry in w.institutions.get("protest_causes", {}).get(region, []):
        when = entry.get("month")
        if when is None or entry.get("cause") != measure:
            continue
        if 0 <= month - int(when) < CONCESSION_MONTHS:
            return True
    return False


def _transition_events(w: World, previous, current, month: int) -> list:
    """Concessions visible in one step from `previous` to `current` (policy and constitution)."""
    prev_pol, prev_con = previous
    cur_pol, cur_con = current
    events = []
    if (_pget(prev_pol, "amnesty", "none") != "release"
            and _pget(cur_pol, "amnesty", "none") == "release"):
        events.append({"kind": "amnesty", "month": month, "regions": _regions(w),
                       "weight": AMNESTY_CREDIT, "detail": "release"})
    before = _funds(_pget(prev_pol, "regional_fund", "none"))
    after = _funds(_pget(cur_pol, "regional_fund", "none"))
    for rid in sorted(after - before):
        events.append({"kind": "fund", "month": month, "regions": [rid],
                       "weight": FUND_CREDIT, "detail": "funded"})
    if bool(_pget(prev_pol, "rationing", False)) and not bool(_pget(cur_pol, "rationing", False)):
        events.extend(_repeal_events(w, "rationing", month))
    if (_pget(prev_pol, "price_controls", "none") not in ("none", None)
            and _pget(cur_pol, "price_controls", "none") in ("none", None)):
        events.extend(_repeal_events(w, "price_controls", month))
    if (_pget(prev_pol, "requisition", "none") not in ("none", None)
            and _pget(cur_pol, "requisition", "none") in ("none", None)):
        events.extend(_repeal_events(w, "requisition", month))
    if (_pget(prev_con, "minority", "equal") not in ("equal", None)
            and _pget(cur_con, "minority", "equal") in ("equal", None)):
        # The Vell are the minority whose rights the Charter names; their home is the Highlands.
        events.append({"kind": "minority_restored", "month": month, "regions": ["highlands"],
                       "weight": MINORITY_CREDIT, "detail": "equal"})
    return events


def _repeal_events(w: World, measure: str, month: int) -> list:
    return [{"kind": "repeal", "month": month, "regions": [rid], "weight": REPEAL_CREDIT,
             "measure": measure, "detail": measure}
            for rid in _regions(w) if _cause_named(w, rid, measure, month)]


def _status_events(w: World) -> list:
    """Upgrades recorded by `regional.set_status`, deduplicated by change entry."""
    events, seen = [], set()
    for change in regional.state(w).get("changes", []):
        key = (change.get("month"), change.get("region"), change.get("from"), change.get("to"))
        if key in seen:
            continue
        seen.add(key)
        if regional.RANK.get(change.get("to"), 0) > regional.RANK.get(change.get("from"), 0):
            events.append({"kind": "status", "month": int(change["month"]),
                           "regions": [change["region"]], "weight": STATUS_CREDIT,
                           "detail": change["to"]})
    return events


def _concession_events(w: World) -> list:
    events = list(_status_events(w))
    states = _states(w)
    previous = (_BASELINE_POLICY, _BASELINE_CONSTITUTION)
    for month, pol, con in states:
        events.extend(_transition_events(w, previous, (pol, con), month))
        previous = (pol, con)
    return events


def negotiation_credits(w: World, region: str) -> list:
    """The concessions still live for `region`, each with its decayed credit. Empty under legacy."""
    if not enabled(w):
        return []
    credits = []
    for event in _concession_events(w):
        if region not in event["regions"]:
            continue
        age = w.month - int(event["month"])
        if not 0 <= age < CONCESSION_MONTHS:
            continue
        entry = {"kind": event["kind"], "month": int(event["month"]),
                 "credit": round(event["weight"] * (1.0 - age / CONCESSION_MONTHS), 4)}
        for key in ("measure", "detail"):
            if event.get(key):
                entry[key] = event[key]
        credits.append(entry)
    return credits


def concession_credibility(w: World, region: str) -> float:
    """The region's political memory of delivered concessions: 0..1, decaying over six months."""
    if not enabled(w):
        return 0.0
    return round(clamp(sum(e["credit"] for e in negotiation_credits(w, region)), 0.0, 1.0), 4)


def negotiation(w: World, region: str, approval_credibility: float) -> dict:
    """The negotiate branch's inputs and the credibility it uses. Recorded in the protest event."""
    approval_credibility = clamp(float(approval_credibility), 0.0, 1.0)
    credits = negotiation_credits(w, region)
    concession = clamp(sum(e["credit"] for e in credits), 0.0, 1.0)
    return {"credibility": round(max(approval_credibility, concession), 4),
            "approval_credibility": round(approval_credibility, 4),
            "concession_credibility": round(concession, 4),
            "concessions": credits}


# ---- the protest cause record --------------------------------------------------------------
def _status_envy(w: World, region: str) -> float:
    """The grievance the region feels at another region's higher status (regional.ENVY x steps),
    multiplied by four because the effect bus's modifiers enter the grievance target at that scale."""
    if region not in regional.REGIONS:
        return 0.0
    other = next(o for o in regional.REGIONS if o != region)
    gap = regional.rank(w, other) - regional.rank(w, region)
    return 4.0 * regional.ENVY[region] * max(0, gap)


def _driver_scores(w: World, region: str, pops: list) -> dict:
    """Each live driver's weight in the region's grievance, on the engine's own coefficients.

    Hunger (.7) and repression (.2) are the grievance target's coefficients (society.update); the
    status term is the regional effect bus's envy term at the same scale. The three measures carry
    the salience they have in the economy rather than a coefficient of the grievance target, which
    does not name them directly: rationing and price controls are synthetic salience weights, the
    requisition is the share economy.REQUISITION takes, and the minority restriction is the
    repression weight society gives the Vell (MINORITY_OPP).
    """
    total = sum(p.size for p in pops) or 1.0
    hunger = sum(p.hunger * p.size for p in pops) / total
    repression = sum(p.repression * p.size for p in pops) / total
    return {
        "hunger": .7 * hunger,
        "repression": .2 * repression,
        "status": _status_envy(w, region),
        "rationing": RATIONING_PAIN if w.policy.rationing else 0.0,
        "price_controls": PRICE_CONTROL_PAIN.get(w.policy.price_controls, 0.0),
        "requisition": REQUISITION.get(w.policy.requisition, 0.0),
        "minority": MINORITY_PAIN.get(w.const.minority, 0.0),
    }


def _largest(scores: dict) -> tuple:
    """The heaviest driver; ties go to the earlier name in CAUSES, so the record is deterministic."""
    best, weight = "unrest", 0.0
    for cause in CAUSES:
        if scores[cause] > weight:
            best, weight = cause, scores[cause]
    return best, weight


def record_protest_cause(w: World, region: str, pops: list) -> dict | None:
    """Record why this region is protesting: no draw, no text, not shown to any delegate."""
    if not enabled(w) or not pops:
        return None
    scores = _driver_scores(w, region, pops)
    cause, weight = _largest(scores)
    entry = {"month": w.month, "cause": cause, "weight": round(weight, 4),
             "drivers": {k: round(v, 4) for k, v in scores.items()}}
    entries = w.institutions.setdefault("protest_causes", {}).setdefault(region, [])
    entries.append(entry)
    del entries[:-CAUSE_CAP]
    return entry


# ---- the new head's grace period -----------------------------------------------------------
def _record_head_change(w: World, record: dict) -> dict:
    changes = state(w).setdefault("head_changes", [])
    changes.append(record)
    del changes[:-HEAD_CHANGE_CAP]
    return record


def head_changed(w: World, old_head: str | None, new_head: str | None) -> dict | None:
    """A different head of government takes office: grant the one grace reaction, or record why not.

    Called by `politics.apply_motion` after the office is set. A vacancy grants nothing (the caller
    does not reach here for `vacate_office`); the reaction is `public_mood`'s approval channel, aimed
    at everyone. Under legacy this returns before touching the world.
    """
    if not enabled(w) or new_head is None or old_head == new_head:
        return None
    record = {"month": w.month, "old": old_head, "new": new_head}
    coup_month = int(getattr(w.const, "coup_month", -99))
    if coup_month >= 0 and 0 <= w.month - coup_month <= 1:
        # RR-1 decision 4: a change in the coup month or the month after it is the coup's doing,
        # not a fresh start, and it does not spend the once-in-twelve-months grant.
        record.update(granted=False, why="coup_blocked", scale=0.0, reaction=None)
        return _record_head_change(w, record)
    last = state(w).get("head_grace_month")
    if last is not None and 0 <= w.month - int(last) < GRACE_INTERVAL:
        record.update(granted=False, why="within_12_months", scale=0.0, reaction=None,
                      last_grace_month=int(last))
        return _record_head_change(w, record)
    # A reshuffle among the same people is not a fresh start: the new head already held an office
    # (the head office itself is excluded, since it was just assigned).
    prior = [o for o in OFFICES if o != "head" and w.const.offices.get(o) == new_head]
    scale = RESHUFFLE_SCALE if prior else 1.0
    reaction = public_mood.react(w, "approval", where="*", value=GRACE_VALUE * scale,
                                 months=GRACE_MONTHS, decay=GRACE_DECAY,
                                 reason=f"{GRACE_REASON} ({new_head})")
    state(w)["head_grace_month"] = w.month
    record.update(granted=True, why="reshuffle" if prior else "new_head", scale=scale,
                  prior_offices=prior, reaction=dict(reaction) if reaction else None)
    return _record_head_change(w, record)
