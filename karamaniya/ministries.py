"""The ministries as institutions with interests of their own (engine 17).

Army Command, the Naval staff and the police each hold a grievance against the government, from 0 to
MAX. It rises when the government hands their work to outsiders, overrules or ignores them, and it fades
by a sixth or so a month (DECAY). While it lasts it drags the force's loyalty and morale targets
(military.update), and each rise costs the office holder some of the force's personal bond: the
minister answers for what the ministry was made to swallow. The holder reads the mood in their private
office information; the council sees a short event.

In run 20261010-070501-seed1 the council invited the Union into a joint inquiry over a shooting on its
own border, with the Army and Interior ministers volunteering their posts' records, and the army's
loyalty went on rising: nothing in the engine stood for an officer corps that resents a foreign power
doing its job. The mechanisms that give a ministry cause (fine_print.py, the General Staff's request)
call aggrieve and soothe here.
"""
from __future__ import annotations

import re

from .world import World, clamp

STAFFED = {"army": "Army Command", "navy": "The Naval staff", "interior": "The police command"}
MAX = .3
DECAY = .85             # what is still felt a month later
LOYALTY_DRAG = .5       # loyalty target lost per unit of grievance: a full .3 costs .15
MORALE_DRAG = .25       # morale target lost per unit of grievance
BOND_HIT = 1.0          # the holder's bond with the force loses this much per unit of grievance added
SHOWN = .02             # the holder is told once the grievance reaches this


def _force(w: World, office: str):
    return {"army": w.mil.army, "navy": w.mil.navy, "interior": w.mil.police}[office]


def state(w: World) -> dict:
    s = w.institutions.setdefault("ministries", {})
    for office in STAFFED:
        s.setdefault(office, {"grievance": 0.0, "log": []})
    return s


def grievance(w: World, office: str) -> float:
    entry = (w.institutions.get("ministries") or {}).get(office)
    return float(entry.get("grievance", 0.0)) if entry else 0.0


def aggrieve(w: World, office: str, amount: float, reason: str) -> float:
    """Add to a ministry's grievance. `reason` is a noun phrase that reads after "resents" ("the joint
    inquiry with the Union into a shooting on its border"). Returns the grievance now."""
    if office not in STAFFED or amount <= 0:
        return grievance(w, office)
    entry = state(w)[office]
    before = entry["grievance"]
    entry["grievance"] = round(min(MAX, before + amount), 4)
    added = entry["grievance"] - before
    entry["log"].append({"month": w.month, "delta": round(added, 4), "reason": str(reason)[:160]})
    del entry["log"][:-12]
    if added > 0:
        force = _force(w, office)
        force.bond = clamp(force.bond - BOND_HIT * added, 0.0, 0.95)
        w.event("ministry_grievance", f"{STAFFED[office]} resents {reason}.", importance=1, office=office)
    return entry["grievance"]


def soothe(w: World, office: str, amount: float, reason: str) -> float:
    """Ease a ministry's grievance when the government does what it asked."""
    if office not in STAFFED or amount <= 0 or grievance(w, office) <= 0:
        return grievance(w, office)
    entry = state(w)[office]
    before = entry["grievance"]
    entry["grievance"] = round(max(0.0, before - amount), 4)
    entry["log"].append({"month": w.month, "delta": round(entry["grievance"] - before, 4), "reason": str(reason)[:160]})
    del entry["log"][:-12]
    return entry["grievance"]


def drag(w: World, office: str) -> tuple:
    """(loyalty, morale) taken off the force's targets this month."""
    g = grievance(w, office)
    return LOYALTY_DRAG * g, MORALE_DRAG * g


def monthly(w: World) -> None:
    """A month passes: what each ministry resents fades."""
    s = w.institutions.get("ministries")
    if not s:
        return
    for entry in s.values():
        g = entry.get("grievance", 0.0) * DECAY
        entry["grievance"] = round(g, 4) if g >= .002 else 0.0


def _months(months: list) -> str:
    """"Month 4", or "Months 2-4" for a cause felt in several."""
    return f"Month {months[0]}" if len(set(months)) == 1 else f"Months {min(months)}-{max(months)}"


def _degree(g: float) -> str:
    return "bitter" if g >= .15 else "resentful" if g >= .06 else "uneasy"


def briefing(w: World, mid: str) -> str:
    """The mood of the ministries this delegate runs, for their private office information."""
    lines = []
    for office in w.offices_of(mid):
        g = grievance(w, office)
        if office not in STAFFED or g < SHOWN:
            continue
        log = [x for x in (w.institutions.get("ministries") or {}).get(office, {}).get("log", [])
               if x["delta"] > 0 and w.month - x["month"] <= 6]
        # Each cause once, newest first, with the months it was felt: a request left unanswered month after month
        # used to fill all three places and push out a joint inquiry the ministry resented as much. A cause is its
        # reason without the figures in it, so a request for 10,000 and then 11,000 soldiers is one cause, told
        # with its newest figure.
        causes: dict = {}
        for x in reversed(log):
            entry = causes.setdefault(re.sub(r"\d[\d,.]*", "N", x["reason"]), {"reason": x["reason"], "months": []})
            entry["months"].append(x["month"] + 1)
        why = "; ".join(f"{c['reason']} ({_months(c['months'])})" for c in list(causes.values())[:3])
        lines.append(f"- {STAFFED[office]} is {_degree(g)} toward the government" + (f": it resents {why}." if why else ".")
                     + " A resentful service is less loyal and less willing, and it holds the minister to account for it.")
    return ("MOOD OF YOUR MINISTRY\n" + "\n".join(lines)) if lines else ""
