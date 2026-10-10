"""Land handed to a neighbour that demanded it (engine 17).

A neighbour's ultimatum can demand a border region (foreign_force, terms cede_region), and the council can answer it
by ceding that region. A cession motion is checked against the demand when it is tabled and again when it executes
(motion_actions.validate_diplomatic_action, cession_problem here). The neighbour that made the demand takes the region
through cede(), which is the mechanism below. If the deadline passes with the region still held and the troops that
could cross are at the border, the rules send the army across for it instead (director._enforce_land_demand), so
refusing has a cost too.

In run 20261010-070501-seed1 Veleria's cabinet issued three ultimatums (status talks in Months 3 and 6, protection for
Imperial citizens in Month 8) and never demanded land, though its aims said "if nothing more can be had, Kessel
Valley". No term it could set was land, so the aim had no act behind it. A demand that the council can meet by
ceding, and that the rules enforce when it refuses, gives that aim an act to be settled by.

A cession uses the mechanism of losing a region (military.occupy): the region passes to the Union's control, so
k_regions, k_pops and the fronts treat it as lost and the front moves on to the next region. It is not a fall. There
is no fighting and no occupation: the event says the region was ceded. The people leave in larger numbers than when a
region falls (a quarter of the Karamanians and Vell, against occupy's 15%), since they are handed to a power they did
not choose; the Imperials stay (2%). The army and the police resent giving up land they did not fight for, the public
is less approving of the government, and the receiving power is a little less hostile and a little more trusting.
"""
from __future__ import annotations

import re

from . import foreign_force, ministries, public_mood
from .military import _merge
from .world import Pop, World, clamp

CESSION_FLIGHT = .25            # Karamanians and Vell who leave a region handed over (military.occupy: .15)
CESSION_FLIGHT_IMPERIAL = .02   # Imperials who leave one (military.occupy: .03)


def named_region(w: World, raw):
    """The Karamanian region a motion's value names, whether or not Karamaniya still holds it, or None."""
    from .politics import _bare, _region_of
    value = _bare(raw if raw is not None else "")
    region = _region_of(w, value)
    if region is not None:
        return region
    text = re.sub(r"[_-]+", " ", str(value or "").strip().lower())
    return next((r for r in w.regions if r.nation == "karamaniya" and text in (r.id, str(r.name).lower())), None)


def region_id(w: World, raw) -> str:
    """The id of the region a motion names, or "" when it names none (politics.apply_motion)."""
    region = named_region(w, raw)
    return region.id if region is not None else ""


def cession_problem(w: World, mo: dict, actor_id: str) -> dict | None:
    """Why a cession motion addressed to `actor_id` cannot pass, or None. The region must be one of Karamaniya's and
    still held, and the neighbour the motion is addressed to must have a demand for it standing
    (foreign_force.land_demands)."""
    region = named_region(w, mo.get("value"))
    if region is None:
        return {"code": "UNKNOWN_REGION", "detail": "a cession must name the Karamanian region it gives up (the value)"}
    if region.controller != "karamaniya":
        return {"code": "UNKNOWN_REGION", "detail": f"Karamaniya does not hold {region.name}, so it cannot be ceded"}
    demanders = foreign_force.land_demands(w, region.id)
    if actor_id in demanders:
        return None
    rule = "a region can only be ceded to a neighbour that has demanded it; "
    if not demanders:
        return {"code": "NOT_DEMANDED", "detail": rule + f"no one has demanded {region.name}"}
    by = " and ".join(w.names.get(d, d.title()) for d in demanders)
    to = w.names.get(actor_id, actor_id.title())
    return {"code": "NOT_DEMANDED", "detail": rule + f"{region.name} has been demanded by {by}, not {to}"}


def cede(w: World, rid: str, to_actor: str) -> bool:
    """Karamaniya hands the region `rid` to the neighbour `to_actor` that demanded it. Returns False, and moves
    nothing, when Karamaniya does not hold the region (it may have been lost since the motion passed)."""
    from . import foreign
    region = next((r for r in w.regions if r.id == rid and r.nation == "karamaniya"), None)
    if region is None or region.controller != "karamaniya":
        return False
    name = region.name
    to_name = w.names.get(to_actor, to_actor.title())
    region.controller = "union"
    safe = [x for x in w.k_regions() if x.id != rid]
    if safe:
        for p in [p for p in w.pops if p.region == rid]:
            flee = p.size * (CESSION_FLIGHT_IMPERIAL if p.ident == "imperial" else CESSION_FLIGHT)
            if flee < 1:
                continue
            p.size -= flee
            dest = safe[0] if len(safe) == 1 else min(safe, key=lambda s: s.damage + (0 if s.capital else 0.1))
            target = next((q for q in w.pops if q.region == dest.id and q.cls == p.cls and q.ident == p.ident), None)
            if target is None:
                target = Pop(region=dest.id, cls=p.cls, ident=p.ident, size=0.0, approval=p.approval, indep=p.indep)
                w.pops.append(target)
            _merge(target, p, flee)
            w.count("refugees", flee)
    w.institutions.setdefault("ceded", {})[rid] = {"to": to_actor, "month": w.month}
    ult = w.dip.ultimatum or {}
    if ult.get("terms_id") == foreign_force.LAND_TERMS and ult.get("region") == rid and ult.get("by") == to_actor:
        w.dip.ultimatum = {}
    w.event("cession", f"Karamaniya has ceded {name} to {to_name}.", importance=3, actor=to_actor, region=rid)
    foreign._message(w, to_name, f"{to_name} accepts {name}, which Karamaniya has handed over.")
    public_mood.react(w, "approval", "ident:karamanian", -.02, 6, "territory:ceded", decay=.85)
    public_mood.react(w, "grievance", "*", .008, 4, "territory:ceded")
    ministries.aggrieve(w, "army", .15, f"the surrender of {name} without a fight")
    ministries.aggrieve(w, "interior", .05, f"the handover of {name}")
    actors = (w.foreign or {}).get("actors", {})
    if to_actor in actors:
        relations = actors[to_actor]["relations"]["karamaniya"]
        relations["hostility"] = round(clamp(relations["hostility"] - .1), 3)
        relations["trust"] = round(clamp(relations["trust"] + .05), 3)
        foreign._remember(w.foreign, to_actor, "territory", f"Karamaniya handed over {name} under its demand.",
                          w.month, region=rid)
    return True
