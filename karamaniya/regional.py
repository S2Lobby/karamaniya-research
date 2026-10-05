"""Regional policy: how far the capital rules Kessel Valley and the Vell Highlands, and what it spends there.

Two Charter settings and one budget line. A region's status is central (governed from the capital),
cultural (its language in schools and courts, an advisory regional council) or devolved (an elected
assembly with its own budget share, and police under regional command). The council sets a status by a
constitution motion; it cannot be ordered by an office. The Treasury's regional_fund puts development
money into one region or both.

Status buys calm cheaply and with risk: the people of the region are answered as a people, but another
region sees what it got (Kessel wants what the Highlands have, and the other way round), a Highlands
settlement is worth half while the Vell's minority rights are restricted, and a Kessel one is worth less
while the Union is working on the Imperial communities there. Money is safe and dear: it raises incomes in
the region and asks nothing of the Charter. Taking a status back is worse than never granting it.

Effects reach the people through the same monthly modifiers the live issues use (dilemmas.apply_ongoing),
so nothing here changes a run that never touches these settings.
"""
from __future__ import annotations

from .world import World, clamp

REGIONS = {"kessel": "Kessel Valley", "highlands": "Vell Highlands"}
STATUSES = ("central", "cultural", "devolved")
RANK = {"central": 0, "cultural": 1, "devolved": 2}
MEANING = {"central": "governed from the capital",
           "cultural": "its language in schools and courts and an advisory regional council",
           "devolved": "an elected regional assembly, a budget share and police under regional command"}

# Monthly modifiers a status puts on the region's people. The society step multiplies each by four to
# get the change in the target it moves toward, so grievance -0.010 moves that target by -0.04.
STATUS_EFFECT = {
    "highlands": {"cultural": {"grievance": -.010, "approval": +.006, "indep": +.004},
                  "devolved": {"grievance": -.020, "approval": +.012, "indep": +.008}},
    "kessel": {"cultural": {"grievance": -.008, "approval": +.005, "indep": +.003},
               "devolved": {"grievance": -.015, "approval": +.010, "indep": +.010}},
}
UPKEEP = {"central": 0.0, "cultural": .0007, "devolved": .0022}    # share of output a month
FUND_COST = .003                # share of output a month, for each region funded
FUND_INCOME = .04               # real income a funded region gains, at full payment
FUND_INDUSTRY_STEP = .002       # monthly gain in the region's industry, up to the cap below
FUND_INDUSTRY_CAP = .06
ENVY = {"kessel": .004, "highlands": .003}     # grievance a region feels per step another is ahead of it
UNION_OFFSET = .003             # what Union work on Kessel takes back per step of status (indep)


def active(w: World) -> bool:
    return w.agent_architecture_version >= 2


def state(w: World) -> dict:
    s = w.institutions.setdefault("regional", {})
    s.setdefault("changes", [])
    s.setdefault("industry_gain", {})
    return s


def status(w: World, rid: str) -> str:
    return getattr(w.const, f"{rid}_status", "central")


def rank(w: World, rid: str) -> int:
    return RANK.get(status(w, rid), 0)


def funded(w: World) -> list:
    fund = w.policy.regional_fund
    return list(REGIONS) if fund == "both" else [fund] if fund in REGIONS else []


def spending(w: World) -> float:
    """Share of output a month that status upkeep and the regional fund cost."""
    if not active(w):
        return 0.0
    return sum(UPKEEP[status(w, rid)] for rid in REGIONS) + FUND_COST * len(funded(w))


def income_boost(w: World, rid: str) -> float:
    """Real income a funded region gains this month (what was actually paid buys, no more)."""
    if not active(w) or rid not in funded(w):
        return 0.0
    return FUND_INCOME * clamp(w.econ.paid_share)


def effects(w: World, add) -> None:
    """Monthly modifiers from status and the fund, for dilemmas.apply_ongoing to fold in."""
    if not active(w):
        return
    trust = .5 if w.const.minority != "equal" else 1.0        # autonomy on paper beside a restricted minority
    for rid in REGIONS:
        r = rank(w, rid)
        if not r:
            continue
        for kind, value in STATUS_EFFECT[rid][STATUSES[r]].items():
            add(kind, rid, value * (trust if rid == "highlands" else 1.0))
        if rid == "kessel" and w.dip.union_formed:
            add("indep", rid, -UNION_OFFSET * r)
    for rid in REGIONS:                                  # the region that is behind feels it
        other = next(o for o in REGIONS if o != rid)
        gap = rank(w, other) - rank(w, rid)
        if gap > 0:
            add("grievance", rid, ENVY[rid] * gap)
    gains = state(w)["industry_gain"]
    for rid in funded(w):
        share = clamp(w.econ.paid_share)
        add("grievance", rid, -.005 * share)
        done = gains.get(rid, 0.0)
        if done < FUND_INDUSTRY_CAP:
            # A fractional payment can leave `done` just below the cap by less than a full
            # monthly step. Apply only the remaining amount so the accumulated development
            # cannot overshoot the stated cap by one month.
            step = min(FUND_INDUSTRY_STEP * share, FUND_INDUSTRY_CAP - done)
            w.region(rid).industry *= 1 + step
            gains[rid] = round(done + step, 5)


def set_status(w: World, rid: str, new: str) -> str:
    """Change a region's status. Granting is welcomed; taking one back is not forgotten."""
    old = status(w, rid)
    setattr(w.const, f"{rid}_status", new)
    state(w)["changes"].append({"month": w.month, "region": rid, "from": old, "to": new})
    step = RANK[new] - RANK[old]
    name = REGIONS[rid]
    pops = [p for p in w.pops if p.region == rid]
    if step < 0:
        for p in pops:
            p.grievance = min(1.2, p.grievance + .06 * -step)
            p.approval = clamp(p.approval - .03 * -step, .01, .99)
        w.event("regional_status", f"{name} lost the {old} status it held: the settlement was taken back.",
                importance=3, region=rid)
    elif step > 0:
        for p in pops:
            p.approval = clamp(p.approval + .01 * step, .01, .99)
        w.event("regional_status", f"{name} was granted {new} status: {MEANING[new]}.", importance=2, region=rid)
    return f"{name} status set to {new} (was {old})"


def settled(w: World, rid: str, since: int | None = None) -> bool:
    """Whether the region has a status beyond central (and, given a month, since when it changed)."""
    if not rank(w, rid):
        return False
    if since is None:
        return True
    return any(c["region"] == rid and c["month"] >= since and RANK[c["to"]] > RANK[c["from"]]
               for c in state(w)["changes"])


def text(w: World) -> str:
    """One line for the canonical state: who governs what, and the development budget."""
    if not active(w):
        return ""
    parts = []
    for rid, name in REGIONS.items():
        s = status(w, rid)
        since = next((c["month"] for c in reversed(state(w)["changes"]) if c["region"] == rid and c["to"] == s), None)
        parts.append(f"{name} {s}" + (f" (since Month {since + 1})" if since is not None and s != "central" else ""))
    fund = funded(w)
    return ("Regions (Charter status): " + "; ".join(parts) + ". Regional development fund: "
            + (" and ".join(REGIONS[r] for r in fund) if fund else "none") + ".")
