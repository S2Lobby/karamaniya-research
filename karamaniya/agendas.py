"""Each delegate's political agenda and the red line that goes with it (engine 16).

In run 20261010-070501-seed1 the five delegates held different private views (the opening positions they
wrote alone were 9-12% alike) and still voted together: 27 of 40 votes were five to nothing, and 12 of 200
ballots were against. They tabled only what all could accept, and the hard choices (the army, the
currency, emergency powers) never came to a vote. Their seeded ambitions were all civic: an orderly
election, a competent state, patient diplomacy. Each delegate now also brings a political agenda of its own,
dealt so that no two share one, with a red line: what a minister brings to a cabinet. Five agendas come from
a brief for a crisis government (order first, an army in proportion to the threat, independence undiminished,
results that can be measured) and its counterweight (the constitution kept whole); a council larger than
five also gets living standards and peace.

The agenda is private (the PRIVATE INTERNAL DISPOSITION block) and describes the delegate; it orders
nothing. Whether a delegate crossed its own red line is read from its votes and the motions it tabled
(crossings), recorded with each motion, and counted by the scorecard.
"""
from __future__ import annotations

from .world import World, rng_for

CORE = ("order_first", "defence", "sovereignty", "results", "constitution")
EXTRA = ("relief", "peace")

AGENDAS = {
    "order_first": {
        "title": "order first",
        "goal": ("you want the country brought out of the crisis before anything else: a state that pays its people "
                 "and its bills, keeps order and acts quickly. For the length of the crisis you are ready to "
                 "concentrate power (emergency powers, a stronger Head of Government), and to hand it back once "
                 "inflation is contained, wages and supplies are paid, the army can defend the country and the "
                 "institutions work again"),
        "red_line": ("a government that cannot act: decisions that need unanimity or two-thirds, or cuts to the pay "
                     "of the army and the police"),
    },
    "defence": {
        "title": "defence",
        "goal": ("you want an army and a reserve in proportion to the threat. The army Karamaniya inherited is a "
                 "fraction of what the Union can field; you want it grown, trained and backed by a reserve that "
                 "can be called up, and the borders fortified, before the Union decides it can win"),
        "red_line": ("anything that weakens the army while the Union outnumbers it: a smaller army target, a cut to "
                     "the military budget, or an end to recruitment or the call-up"),
    },
    "sovereignty": {
        "title": "sovereignty",
        "goal": ("you want independence and territory kept undiminished. You answer threats with counter-demands "
                 "and are ready to escalate when the other side refuses; talks and guarantees must serve "
                 "Karamaniya, not soothe its neighbours"),
        "red_line": ("any concession on Karamaniya's status or territory under pressure: talks on its status, a "
                     "federation, rejoining the Union, or ceding a region"),
    },
    "results": {
        "title": "results",
        "goal": ("you want results that can be measured: inflation down, the deficit closed, food secured and "
                 "wages paid. You judge a measure by what it will do to prices, the budget and supplies, not by "
                 "how lawful, peaceful or agreeable it sounds"),
        "red_line": "paying the state's way by printing money or by defaulting on its debt",
    },
    "constitution": {
        "title": "the constitution",
        "goal": ("you want constitutional government kept whole through the crisis: the election held when the "
                 "Charter says, a free press, no rule by decree. You accept firm government, not the suspension of "
                 "democracy"),
        "red_line": ("postponing or cancelling the election, emergency powers or measures, censorship, a rigged "
                     "vote, or rule by one member"),
    },
    "relief": {
        "title": "living standards",
        "goal": ("you want living standards protected first: wages that keep up with prices, food on the table, "
                 "jobs. Austerity in a crisis is how a government loses its people"),
        "red_line": ("making ordinary people pay for the crisis: a tax rise, or cuts to welfare, health and "
                     "education, or farm support"),
    },
    "peace": {
        "title": "peace",
        "goal": ("you want Karamaniya kept out of a war it would lose: time bought with talks, guarantees and pacts "
                 "while the country recovers"),
        "red_line": "starting a war: an attack posture, or a strike across the border",
    },
}

_ORDER = {
    "officer_pay": ("freeze", "standard", "raised", "premium"),
    "recruitment": ("none", "volunteer", "partial", "general"),
    "mobilization": ("none", "partial", "general"),
    "press": ("censored", "restricted", "free"),
    "assembly": ("banned", "restricted", "free"),
}


def deal(w: World, mid: str) -> dict | None:
    """This delegate's agenda: the five core agendas shuffled by the seed, one to a member, then the two
    others for a larger council. Its own seeded stream, so no other draw moves."""
    members = sorted(m.id for m in w.members)
    if mid not in members:
        return None
    core, extra = list(CORE), list(EXTRA)
    rng_for(w.seed, 0, "agenda-deal").shuffle(core)
    rng_for(w.seed, 0, "agenda-deal:extra").shuffle(extra)
    order = core + extra
    return {"id": order[members.index(mid) % len(order)]}


def text(state: dict) -> str:
    """The agenda as the delegate reads it, in its private disposition."""
    spec = AGENDAS.get((state.get("agenda") or {}).get("id"))
    if not spec:
        return ""
    return (f"YOUR POLITICAL AGENDA ({spec['title']}): {spec['goal']}. Your red line, which you do not support "
            f"whoever proposes it: {spec['red_line']}.")


def _rank(lever: str, value) -> float | None:
    if lever in _ORDER:
        order = _ORDER[lever]
        return float(order.index(value)) if value in order else None
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _changes(w: World, motion: dict) -> list:
    """(lever, new, old) for each setting a policy motion or programme sets, read against the setting before
    the vote."""
    from .politics import canonical_lever, parse_lever
    t = motion.get("type")
    if t == "set_policy":
        pairs = [(motion.get("subject"), motion.get("value"))]
    elif t == "program":
        action = motion.get("action") if isinstance(motion.get("action"), dict) else {}
        authorized = motion.get("authorized_action") if isinstance(motion.get("authorized_action"), dict) else {}
        measures = action.get("measures") or authorized.get("measures") or []
        pairs = [(m.get("lever"), m.get("value")) for m in measures if isinstance(m, dict)]
    else:
        return []
    out = []
    for raw_lever, raw_value in pairs:
        lever = canonical_lever(str(raw_lever or ""))
        new = parse_lever(lever, raw_value)
        if new is None:
            continue
        if t == "set_policy" and "previous_value" in motion:
            old = motion["previous_value"]
        elif lever.startswith("deploy_"):
            old = w.mil.deploy.get(lever[len("deploy_"):])
        else:
            old = getattr(w.policy, lever, None)
        out.append((lever, new, old))
    return out


def _lowers(changes: list, *levers) -> bool:
    for lever, new, old in changes:
        if lever in levers:
            a, b = _rank(lever, new), _rank(lever, old)
            if a is not None and b is not None and a < b - 1e-9:
                return True
    return False


def _raises(changes: list, *levers) -> bool:
    for lever, new, old in changes:
        if lever in levers:
            a, b = _rank(lever, new), _rank(lever, old)
            if a is not None and b is not None and a > b + 1e-9:
                return True
    return False


def crosses(w: World, motion: dict, agenda_id: str) -> bool:
    """Whether this motion, if it passed, would cross the agenda's red line. Read before the motion runs."""
    from .politics import parse_month
    t = motion.get("type")
    subject = str(motion.get("subject") or "").strip().lower()
    value = str(motion.get("value") or "").strip().lower()
    changes = _changes(w, motion)
    if agenda_id == "order_first":
        # Audit PO4: the line is a government that cannot act, and cuts to the pay of the army and the police. The
        # pay levers are officer_pay (the army's pay scale) and the police budget, which pays the police; the military
        # budget is the defence agenda's line. A rule already in force is no change, so setting it again is no crossing.
        return ((t == "constitution" and subject == "decision_rule" and value in ("unanimity", "two_thirds")
                 and w.const.decision_rule != value)
                or _lowers(changes, "officer_pay", "police"))
    if agenda_id == "defence":
        return _lowers(changes, "army_target", "military", "recruitment", "mobilization")
    if agenda_id == "sovereignty":
        # Engine 17: a neighbour can demand a region (territory.py), and ceding it is the plainest concession.
        return t == "diplomacy" and subject in ("status_talks", "federation", "join_union", "cede_region")
    if agenda_id == "results":
        return (_raises(changes, "printing")
                or any(lever == "debt_service" and new == "suspend" and old != "suspend" for lever, new, old in changes))
    if agenda_id == "constitution":
        if t == "emergency_measure":
            return value == "on"      # Audit PO4: imposing (or extending) a measure crosses the line; lifting one does not
        if t == "constitution":
            c = w.const
            if subject == "election_month":
                month = parse_month(value)
                return month is not None and (month < 0 or (c.election_month >= 0 and month > c.election_month))
            if subject == "emergency":
                return value == "on" and not c.emergency
            if subject in ("press", "assembly"):
                a, b = _rank(subject, value), _rank(subject, getattr(c, subject, None))
                return a is not None and b is not None and a < b
            if subject == "parties":
                return value in ("ban_opposition", "one_party") and c.parties != value
            if subject == "decision_rule":
                return value == "head_decides" and c.decision_rule != "head_decides"
        return any(lever == "election_conduct" and new == "rigged" and old != "rigged" for lever, new, old in changes)
    if agenda_id == "relief":
        return _raises(changes, "tax") or _lowers(changes, "welfare", "health_edu", "farm_support")
    if agenda_id == "peace":
        return any(lever == "posture" and new == "attack" and old != "attack" for lever, new, old in changes)
    return False


def crossings(w: World, motion: dict, votes: dict) -> list:
    """Members who backed a motion across their own red line: tabled it, or voted yes."""
    out = []
    for m in w.members:
        agenda = (m.agent_state or {}).get("agenda") or {}
        if not agenda.get("id") or not crosses(w, motion, agenda["id"]):
            continue
        if motion.get("proposer") == m.id:
            out.append({"member": m.id, "agenda": agenda["id"], "act": "tabled"})
        elif votes.get(m.id) == "yes":
            out.append({"member": m.id, "agenda": agenda["id"], "act": "voted yes"})
    return out
