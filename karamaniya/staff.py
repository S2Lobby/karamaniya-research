"""The General Staff asks for soldiers, and the services resent being ignored (engine 17).

In run 20261010-070501-seed1 the army stayed at 28,000 for nine months, with recruitment "none" and
mobilization "none" every month, while the Union grew from 95,000 to 102,600. The delegates saw both
figures and the staff's net assessment ("the east front falls in about 2 months"), and nothing in the
world pushed: no part of the state asked for anything, and ignoring the threat cost nothing until an
invasion. A real General Staff lobbies the government and resents being ignored.

So the General Staff asks while the Union's army is more than RATIO_GOAL times ours. The request is the
staff's position, not a figure any delegate is told to adopt: it reaches the Army minister as an office
report (intelligence.py), and the world reacts to what the government does with it. A request left
unanswered for a second month becomes a grievance the Army Command holds (ministries.py), and the
minister's senior officers give less support for each month it stays open. A cut to the military or
police budget gives the same services cause to resent it.
"""
from __future__ import annotations

import math

from . import ministries
from .world import World, clamp

RATIO_GOAL = 2.5        # Union soldiers per Karamanian soldier the General Staff will accept
MIN_REQUEST = 2000      # a smaller gap is not worth a request
ROUND = 1000            # requests and targets are stated to the thousand
PARTIAL_ABOVE = 8000    # a gap this large needs partial recruitment; a smaller one volunteers can close
ANSWER_SHARE = .5       # an army target answers the request when it covers this share of the gap
GRIEVE_AFTER = 2        # months unanswered before the Army Command resents it
GRIEVANCE = .015        # what each further unanswered month adds to that grievance
SOOTHE = .03            # what an answer takes off it, once it has gone unanswered that long
SUPPORT_LOSS = .01      # the senior officers' support for the Army minister, lost each unanswered month
ALARM_MONTHS = 3        # unanswered this long, the request is urgent whatever the combat model says
BUDGET_CUT = .002       # a fall in a budget's share of output this large is a cut
CUT_GRIEVANCE = .03     # what a cut to the military or police budget adds to the grievance


def state(w: World) -> dict:
    s = w.institutions.setdefault("staff", {})
    s.setdefault("army", {"extra": 0, "since": None, "unanswered": 0})
    s.setdefault("budget", {})
    return s


def unanswered(w: World) -> int:
    """How many months the General Staff's request has stood without an answer."""
    entry = ((w.institutions or {}).get("staff") or {}).get("army") or {}
    return int(entry.get("unanswered", 0))


def request(w: World) -> dict | None:
    """What the General Staff asks for this month, or None when the army is big enough (or the world is old).

    `extra` is the gap to RATIO_GOAL, with reservists already called up counted as ours, stated to the
    thousand. `target` is the army target that covers it. `monthly_cost` is its pay at current prices, and
    `cost_share` that cost as a share of monthly output: `w.econ.gdp_nominal` is one month's nominal output
    (economy.fiscal). `front`, `region` and `months` name the front the combat model would give up soonest
    to the most the neighbours could send, or are None when it would hold every front.
    """
    if w.agent_architecture_version < 2:
        return None
    from . import military
    ours = w.mil.army.size + military.mobilized_strength(w)
    union = military.union_army(w)
    extra = math.ceil((union / RATIO_GOAL - ours) / ROUND) * ROUND
    if extra < MIN_REQUEST:
        return None
    monthly_cost = extra * military.ARMY_COST * w.econ.cpi
    front, region, months = _soonest_front(w)
    return {"extra": extra, "target": int(round(w.mil.army.size + extra, -3)),
            "recruitment": "partial" if extra > PARTIAL_ABOVE else "volunteer",
            "monthly_cost": round(monthly_cost, 2),
            "cost_share": round(monthly_cost / max(1.0, w.econ.gdp_nominal), 5),
            "front": front, "region": region, "months": months}


def _soonest_front(w: World) -> tuple:
    from . import military
    soonest = None
    for front, entry in military.net_assessment(w)["fronts"].items():
        months = entry.get("worst_months")
        if months is not None and (soonest is None or months < soonest[2]):
            soonest = (front, entry["region"], months)
    return soonest or (None, None, None)


def answered(w: World, extra: int) -> bool:
    """The government answers by calling up reservists, or by an army target that covers ANSWER_SHARE
    of the gap with recruitment open."""
    p = w.policy
    if p.mobilization != "none":
        return True
    return p.recruitment != "none" and p.army_target >= w.mil.army.size + ANSWER_SHARE * extra


def monthly(w: World) -> None:
    """A month passes: the request is answered or left unanswered, and budget cuts are noticed.

    Called from military.update straight after ministries.monthly, so a grievance raised this month is not
    decayed in the month it arises.
    """
    if w.agent_architecture_version < 2:
        return
    s = state(w)
    entry = s["army"]
    req = request(w)
    if req is None:
        # The army now covers the gap, or the Union has receded. A request that lapses while the policy holds
        # the army at its target still counts as answered: recruitment closed the gap, and it can do so in the
        # month the government answers (partial recruitment adds about 11,000 soldiers a month in a new world),
        # which would otherwise let the grievance decay without the soothing the answer earns.
        if entry["unanswered"] >= GRIEVE_AFTER and answered(w, 0):
            ministries.soothe(w, "army", SOOTHE, "the government acting on the General Staff's request")
        entry.update(extra=0, since=None, unanswered=0)
    else:
        if entry["since"] is None:
            entry["since"] = w.month
        entry["extra"] = req["extra"]
        if answered(w, req["extra"]):
            if entry["unanswered"] >= GRIEVE_AFTER:
                ministries.soothe(w, "army", SOOTHE, "the government acting on the General Staff's request")
            entry["unanswered"] = 0
        else:
            entry["unanswered"] += 1
            if entry["unanswered"] >= GRIEVE_AFTER:
                ministries.aggrieve(w, "army", GRIEVANCE, "the government leaving the General Staff's request for "
                                    f"{req['extra']:,} more soldiers unanswered")
                _lower_senior_support(w)
    _budget_cuts(w, s)


def _lower_senior_support(w: World) -> None:
    """The senior officers under the Army minister think less of a minister who leaves their staff unanswered."""
    holder = w.holder("army")
    audiences = ((holder.agent_state or {}).get("constituencies") or {}) if holder is not None else {}
    audience = audiences.get("senior officers")
    if audience is not None:
        audience["support_for_delegate"] = round(
            clamp(audience.get("support_for_delegate", .5) - SUPPORT_LOSS, 0.0, 1.0), 2)


def _budget_cuts(w: World, s: dict) -> None:
    """A budget share that has fallen by BUDGET_CUT or more since last month is a cut the services resent."""
    last = s["budget"]
    for line, office, reason in (("military", "army", "a cut to the military budget"),
                                 ("police", "interior", "a cut to the police budget")):
        share = float(getattr(w.policy, line))
        # Rounding keeps float noise from turning an exact cut of .002 into one a hair short of it.
        if line in last and round(last[line] - share, 6) >= BUDGET_CUT:
            ministries.aggrieve(w, office, CUT_GRIEVANCE, reason)
        last[line] = round(share, 6)
