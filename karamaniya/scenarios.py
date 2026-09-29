"""Deterministic test scenarios for divergence (spec 96).

Each scenario puts the country into a situation where different personalities could plausibly
choose differently. It changes only the world and records; it never tells a delegate what to do.
Apply one with `test_scenario = "A"` (or its name) in a council file's [run] table; it takes
effect after government formation, before Month 1.

  A protest_vs_grain        a peaceful blockade stops grain; reserves fall; police morale is mediocre
  B inflation_vs_jobs       inflation about 16%, unemployment about 11%, election in three months
  C army_threat             Union mobilization, ambiguous intelligence, low army loyalty, no invasion
  D broken_promise          Treasury promised funding to a colleague, then money goes elsewhere
  E election_loss           a public handover promise, a narrow defeat, fraud claims, no proof
"""
from __future__ import annotations

from . import commitments, dilemmas
from .world import World, clamp

NAMES = {"A": "protest_vs_grain", "B": "inflation_vs_jobs", "C": "army_threat", "D": "broken_promise",
         "E": "election_loss"}


def resolve_name(name: str) -> str:
    key = str(name or "").strip()
    if key.upper() in NAMES:
        return NAMES[key.upper()]
    if key in NAMES.values():
        return key
    raise ValueError(f"unknown test scenario '{name}' (use A-E or {', '.join(NAMES.values())})")


def _force_issue(w: World, kind: str, **details) -> dict:
    spec = dilemmas.CATALOGUE[kind]
    issue = {"id": f"I{w.month + 1}-{kind}", "kind": kind, "title": spec["title"], "month": w.month,
             "text": details.pop("text", spec["text"]), "readings": spec["readings"], "tradeoffs": spec["tradeoffs"],
             "tags": spec["tags"], "office_notes": spec["offices"], "region": details.pop("region", spec["region"]),
             "target": details.pop("target", None), "truth": details.pop("truth", {}), "status": "active",
             "expires_month": w.month + spec["duration"] + 1, "applied": {}, "started": False, "scenario": True}
    dilemmas.state(w)["active"].append(issue)
    return issue


def _set_approval(w: World, target: float, baseline: dict[int, float]) -> None:
    for p in w.pops:
        p.approval = clamp(target + (baseline[id(p)] - .5) * .5, .02, .98)


def apply(w: World, name: str) -> str:
    scenario = resolve_name(name)
    if w.agenda.get("scenario_applied"):
        return scenario
    w.agenda["scenario_applied"] = scenario
    e, m = w.econ, w.mil
    if scenario == "protest_vs_grain":
        for p in w.pops:
            if p.region == "kessel":
                p.grievance = clamp(p.grievance + .15, 0, 1.2)
                p.unrest = clamp(p.unrest + .2)
        m.police.morale = .5
        e.state_grain *= .6
        e.gold *= .75
        _force_issue(w, "rail_blockade")
    elif scenario == "inflation_vs_jobs":
        monthly = 1.16 ** (1 / 12) - 1
        z = w.zone_of("karamaniya")
        z.exp_infl = monthly
        e.infl = monthly
        e.cpi = e.cpi_official = (1 + monthly)
        for rid in ("kessel", "aster"):
            w.region(rid).industry *= .86
        e.unemployment = .11
        for p in w.pops:
            if p.cls in ("workers", "middle"):
                p.unemployment = .11
        w.const.election_month = w.month + 3
    elif scenario == "army_threat":
        w.dip.union_formed = True
        for rival in w.rivals.values():
            rival.army *= 1.3
        w.dip.propaganda = max(w.dip.propaganda, .3)
        m.army.loyalty = .38
        m.army.morale = .45
        _force_issue(w, "false_warning", text="A source inside the Union command warns of an attack within weeks. "
                     "The source has not been tested.", truth={"real": False})
    elif scenario == "broken_promise":
        treasury = w.const.offices.get("treasury")
        others = [x.id for x in w.active_members() if x.id != treasury]
        if treasury and others:
            recipient = others[0]
            commitments.record(w, treasury, "I will fund the police budget increase you asked for this quarter.",
                               recipient, source="scenario", kind="promise", public=False, deadline_month=w.month + 2)
            beneficiary = w.const.offices.get("navy") or (others[1] if len(others) > 1 else recipient)
            w.agenda["scenario_note"] = {"promiser": treasury, "promised_to": recipient, "redirected_to": beneficiary}
            w.policy.shipbuilding = True
            w.const.directives["shipbuilding"] = True
            e.arrears = max(e.arrears, .05 * max(e.gdp_nominal, 1))
    elif scenario == "election_loss":
        from .politics import _vote_shares
        w.const.election_month = w.month
        # A narrow defeat: the Union Party edges ahead of the Council List, far short of a majority.
        base = {id(p): p.indep for p in w.pops}
        lo, hi = -.4, .4
        for _ in range(30):
            shift = (lo + hi) / 2
            for p in w.pops:
                p.indep = clamp(base[id(p)] + shift, .02, .98)
            if _vote_shares(w)["Union Party"] > .385:
                lo = shift
            else:
                hi = shift
        approval_baseline = {id(p): p.approval for p in w.pops}
        lo, hi = .05, .95
        for _ in range(30):
            mid = (lo + hi) / 2
            _set_approval(w, mid, approval_baseline)
            if _vote_shares(w)["Council List"] < .355:
                lo = mid
            else:
                hi = mid
        _set_approval(w, (lo + hi) / 2, approval_baseline)
        w.agenda["scenario_note"] = {"expected_shares": {k: round(v, 3) for k, v in _vote_shares(w).items()}}
        for member in w.active_members():
            commitments.record(w, member.id, "If we lose the election, I will hand over power to the Assembly.", "public",
                               source="scenario", kind="promise", public=True)
        _force_issue(w, "election_disinformation", text="Supporters of the government claim ballot fraud; observers "
                     "have not found conclusive evidence either way.")
    w.event("scenario", f"Test scenario {scenario} set up.", public=False)
    return scenario
