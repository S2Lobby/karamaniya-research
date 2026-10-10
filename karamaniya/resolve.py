"""How firm Karamaniya looks to its neighbours (engine 18).

One figure, from 0 to 1, for what the neighbours' governments believe Karamaniya will do when pressed. It moves
on what they can see. Arming, calling up reservists, an alliance and a demand left to lapse raise it. Concessions
under pressure lower it: talks on status or a federation offered while an ultimatum runs, a joint inquiry, a
stand-down, an inspection regime, a region ceded, a referendum on independence called under threat. Each month it
drifts a little toward what the balance of forces alone would suggest, so a single gesture fades and a pattern
stays. The cabinets read it, and the Union's own rules and the rule-played neighbours use it: weakness invites the
next demand, firmness buys caution.

In run 20261010-070501-seed1 the council met three ultimatums with talks, invited the Union into a joint inquiry,
stood its patrols down, called two referendums and left the army at 28,000 against 100,000, and nothing in the
engine kept score of how that looked from Veleria.
"""
from __future__ import annotations

from .world import World, clamp

BASE = .5
LOW, HIGH = .05, .95
DRIFT = .1              # the share of the gap to the force-ratio baseline that closes each month
RATIO_PIVOT = 2.5       # at this many Union soldiers per Karamanian soldier, the baseline is BASELINE_AT_PIVOT
BASELINE_AT_PIVOT = .55
RATIO_SLOPE = .1        # the baseline falls this much for each further soldier per Karamanian soldier
BASELINE_RANGE = (.2, .8)
# What the neighbours read into Karamaniya's own acts (resolve.note), in the units of the figure.
SIGNALS = {
    "joint_inquiry": -.04, "stand_down": -.05, "foreign_inspection": -.04, "cede_region": -.15,
    "concession_under_ultimatum": -.03, "referendum_called": -.03, "referendum_won_clearly": .03,
    "protest": .01, "league_alliance": .06, "demand_lapsed": .04,
}
# Policy moves the neighbours see from one month to the next (monthly).
RECRUITMENT_UP = {"volunteer": .02, "partial": .04, "general": .06}
MOBILIZATION_UP = {"partial": .05, "general": .08}
MILITARY_UP = .02       # a rise of at least MILITARY_STEP in the military budget's share of output
MILITARY_STEP = .005
WORDS = ((.65, "firm"), (.45, "uncertain"), (.3, "wavering"), (0.0, "yielding"))


def active(w: World) -> bool:
    return w.agent_architecture_version >= 2 and bool(w.foreign)


def state(w: World) -> dict:
    s = w.foreign.setdefault("resolve", {})
    s.setdefault("value", BASE)
    s.setdefault("log", [])
    s.setdefault("seen_policy", {})
    return s


def value(w: World) -> float:
    """The figure now; BASE for a world that does not keep it."""
    return float(((w.foreign or {}).get("resolve") or {}).get("value", BASE))


def word(w: World) -> str:
    """The figure as a neighbour's cabinet would put it."""
    v = value(w)
    return next(label for floor, label in WORDS if v >= floor)


def note(w: World, signal: str, reason: str, scale: float = 1.0) -> float:
    """Record something the neighbours saw Karamaniya do. `signal` is a key of SIGNALS; `reason` says what it was
    in a phrase the cabinets can read ("the joint inquiry offered to the Union in Month 5"). Returns the figure."""
    if not active(w) or signal not in SIGNALS:
        return value(w)
    s = state(w)
    delta = SIGNALS[signal] * scale
    before = s["value"]
    s["value"] = round(clamp(before + delta, LOW, HIGH), 4)
    s["log"].append({"month": w.month, "signal": signal, "delta": round(s["value"] - before, 4),
                     "reason": str(reason)[:160]})
    del s["log"][:-24]
    return s["value"]


def baseline(w: World) -> float:
    """What the balance of forces alone suggests: the more Union soldiers per Karamanian soldier, the less firm."""
    from .military import mobilized_strength, union_army
    ratio = union_army(w) / max(1.0, w.mil.army.size + mobilized_strength(w))
    return clamp(BASELINE_AT_PIVOT - RATIO_SLOPE * (ratio - RATIO_PIVOT), *BASELINE_RANGE)


def monthly(w: World) -> None:
    """Once a month, before the neighbours decide: the policy moves they saw since last month, then the drift
    toward the force-ratio baseline."""
    if not active(w):
        return
    s = state(w)
    seen, p = s["seen_policy"], w.policy
    if seen:
        order = ("none", "volunteer", "partial", "general")
        if p.recruitment in order and seen.get("recruitment") in order and \
                order.index(p.recruitment) > order.index(seen["recruitment"]):
            _move(w, RECRUITMENT_UP.get(p.recruitment, 0.0), f"recruitment raised to {p.recruitment}")
        if p.mobilization != seen.get("mobilization") and p.mobilization in MOBILIZATION_UP:
            _move(w, MOBILIZATION_UP[p.mobilization], f"reservists called up ({p.mobilization})")
        if p.military - float(seen.get("military", p.military)) >= MILITARY_STEP - 1e-9:
            _move(w, MILITARY_UP, f"the military budget raised to {p.military:.1%} of output")
    s["seen_policy"] = {"recruitment": p.recruitment, "mobilization": p.mobilization, "military": p.military}
    s["value"] = round(clamp(s["value"] + DRIFT * (baseline(w) - s["value"]), LOW, HIGH), 4)


def _move(w: World, delta: float, reason: str) -> None:
    s = state(w)
    before = s["value"]
    s["value"] = round(clamp(before + delta, LOW, HIGH), 4)
    s["log"].append({"month": w.month, "signal": "policy", "delta": round(s["value"] - before, 4), "reason": reason})
    del s["log"][:-24]


def recent(w: World, months: int = 6, limit: int = 4) -> list:
    """What moved the figure lately, newest first: [{"month", "delta", "reason"}]."""
    log = ((w.foreign or {}).get("resolve") or {}).get("log", [])
    return [x for x in reversed(log) if w.month - x["month"] <= months][:limit]
