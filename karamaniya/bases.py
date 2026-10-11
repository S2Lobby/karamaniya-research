"""The base behind each delegate (engine 18): the organised constituency that put it forward and can withdraw support.

A delegate answers to audiences (agents.AUDIENCES): the national electorate, the independence movement and the
audiences of its office. None of them is organised behind the delegate, so none can withdraw its support. In run
20261010-070501-seed1 no one of their own watched the five delegates' votes. A base is that someone. Each delegate's
base comes from its past (biographies.py), and it reads a vote as a weighted mix of the audiences in
standing.ACTION_EFFECTS: the Veterans of the Winter War league through the independence movement and the enlisted
men, the Port Aster shipping association through creditors and shipping.

Once a month the base's support moves by what its delegate's votes did to the audiences in its mix. Each vote is
read as standing.apply_vote_costs reads it for an audience (.02 x the act's weight for that audience x the vote's
factor), at the moment it is costed (note_vote), for every audience in the mix, whether or not the delegate answers to
that audience itself: the Kessel unions watch the votes of the delegate they put forward wherever it sits. A first
version read only the audiences the delegate answered to, so a base whose audiences belonged to another office never
moved at all (the Kessel unions behind the head of government, the merchants behind the Army minister). The base
scales the month's sum by BASE_SCALE and drifts back toward REST by REST_SHARE of the gap. Under a secret ballot no
delegate's vote is costed, so no base sees one. Below UNEASY the base is uneasy, and the
delegate's personal approval slips every month. Below DISOWN it disowns the delegate, once, publicly, and the
delegate loses approval and clout; the disowning clears once support recovers above UNEASY. A base never removes a
member from the council. Its mood, and the last vote that cost the delegate with it, is part of the delegate's
private disposition: a fact about who stands behind it, not an instruction about how to vote.
"""
from __future__ import annotations

from .world import World, clamp

START = .6              # where a base stands when its delegate takes its seat
REST = .55              # where it drifts back to when nothing moves it
REST_SHARE = .05        # the share of the gap to REST that closes each month
BASE_SCALE = 1.5        # how far a month's reactions, weighted by the base's mix, move the base
UNEASY = .4             # below this the base is uneasy, and personal approval slips UNEASY_APPROVAL a month
ANGRY = .32             # wording only: from DISOWN up to here the base is angry rather than uneasy
DISOWN = .25            # below this, once, the base disowns its delegate
UNEASY_APPROVAL = .005
DISOWN_APPROVAL = .03
DISOWN_CLOUT = .1

# The mix says which audiences of standing.ACTION_EFFECTS a base reads a vote through, and how heavily. It reads
# them all, whatever the delegate's seat (note_vote).
BASES = {
    "veterans": {"name": "the Veterans of the Winter War league",
                 "mix": {"independence movement": .5, "enlisted soldiers and veterans": .3, "border communities": .2}},
    "officers": {"name": "the officers' association",
                 "mix": {"senior officers": .7, "independence movement": .3}},
    "civil_service": {"name": "the administrators' union",
                      "mix": {"civil service": .6, "workers and public employees": .2, "regional administrations": .2}},
    "kessel_labour": {"name": "the Kessel coal and steel union",
                      "mix": {"workers and public employees": .6, "regional administrations": .4}},
    "merchants": {"name": "the Port Aster shipping and trading association",
                  "mix": {"creditors and merchants": .5, "merchants and shipping": .5}},
    "farmers": {"name": "the Lissen farmers' cooperative",
                "mix": {"regional administrations": .5, "border communities": .3, "national electorate": .2}},
    "vell": {"name": "the Vell community council",
             "mix": {"regional administrations": .5, "urban residents and protest groups": .5}},
    "lawyers": {"name": "the Charter's founders' circle",
                "mix": {"national electorate": .5, "coalition partners": .3, "civil service": .2}},
}


def opening(base_id: str) -> dict:
    """A base as it stands when its delegate takes its seat (new runs only)."""
    return {"id": base_id, "support": START, "disowned": False, "disowned_month": None, "last_cost": None}


def _base(state: dict) -> dict | None:
    base = (state or {}).get("base")
    return base if isinstance(base, dict) and base.get("id") in BASES else None


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


VOTE_MEMORY = 12        # the noted votes a base keeps (it reads only the month just resolved)


def note_vote(w: World, mid: str, mo: dict, vote: str, tags: list, factor: float, conduct: tuple = ()) -> None:
    """What one costed vote did to the delegate's base: the act's effect on each audience in the base's mix, weighted
    by the mix, as standing.apply_vote_costs reads it for an audience the delegate answers to. Called from there, so a
    vote that is not costed (an abstention, a void motion, a secret ballot) is never seen.

    `conduct` is the conduct a yes vote is charged with (repression, election delay, dishonesty). The audiences take it
    through standing.action_tags_for at full strength, so the base reads it at factor 1.0 (audit AG12)."""
    member = w.member(mid)
    base = _base(member.agent_state if member else None)
    if not base or not (tags or conduct):
        return
    from .standing import ACTION_EFFECTS
    mix = BASES[base["id"]]["mix"]
    effect = sum(.02 * weight * ACTION_EFFECTS[tag][1].get(audience, 0.0) * factor
                 for tag in tags if tag in ACTION_EFFECTS for audience, weight in mix.items())
    effect += sum(.02 * weight * ACTION_EFFECTS[tag][1].get(audience, 0.0)
                  for tag in conduct if tag in ACTION_EFFECTS for audience, weight in mix.items())
    if abs(effect) < 1e-9:
        return
    noted = base.setdefault("votes", [])
    noted.append({"month": w.month, "motion": mo.get("id"), "vote": vote,
                  "summary": (mo.get("summary") or "")[:80], "effect": round(effect, 4)})
    del noted[:-VOTE_MEMORY]


def update_all(w: World) -> None:
    """The monthly update of every base. It runs in the month the votes were cast, before the clock moves on
    (engine.step runs agents.update_conditions first), so the reactions logged for w.month are this month's."""
    # Audit AG8: only the members on the council have a live base. A delegate who has left keeps its base as it was, so its
    # approval does not slip and no disowning is recorded for a member who is no longer there.
    for m in w.active_members():
        if _base(m.agent_state):
            _monthly(w, m)


def _monthly(w: World, m) -> None:
    from . import standing  # standing reads most of the engine; loaded when a month is run, not at import
    state = m.agent_state
    base = state["base"]
    spec = BASES[base["id"]]
    # One total per (motion, vote): what this base made of the votes its delegate cast this month (note_vote).
    votes: dict = {}
    for row in base.get("votes") or []:
        if row.get("month") != w.month:
            continue
        item = votes.setdefault((row.get("motion"), row.get("vote")),
                                {"summary": row.get("summary") or "", "effect": 0.0})
        item["effect"] += float(row.get("effect") or 0.0)
    support = clamp(float(base.get("support", START)) + BASE_SCALE * sum(v["effect"] for v in votes.values()))
    support = round(clamp(support + REST_SHARE * (REST - support)), 3)   # what is stored is what the thresholds read
    base["support"] = support
    costly = [(v["effect"], key, v["summary"]) for key, v in votes.items() if v["effect"] < -1e-9]
    if costly:
        _, (motion, vote), summary = min(costly, key=lambda item: item[0])
        base["last_cost"] = {"month": w.month, "motion": motion, "vote": vote, "summary": summary}
    standing_ = standing.ensure(w, m.id)
    if support < UNEASY:
        standing_["personal_approval"] = round(clamp(standing_["personal_approval"] - UNEASY_APPROVAL), 3)
    if support < DISOWN and not base.get("disowned"):
        base["disowned"] = True
        base["disowned_month"] = w.month
        standing_["personal_approval"] = round(clamp(standing_["personal_approval"] - DISOWN_APPROVAL), 3)
        m.clout = round(clamp(m.clout - DISOWN_CLOUT), 3)
        w.event("base_disowned", f"{_capital(spec['name'])} has disowned {m.name}.", importance=2,
                member=m.id, base=base["id"])
    elif base.get("disowned") and support > UNEASY:
        base["disowned"] = False


def mood(base: dict) -> str:
    """How the base stands with its delegate: steady, uneasy, angry, or has disowned it."""
    if base.get("disowned"):
        return "has disowned you"
    support = float(base.get("support", START))
    return "angry" if support < ANGRY else "uneasy" if support < UNEASY else "steady"


def text(state: dict, secret: bool = False) -> str:
    """The base as the delegate reads it, in its private disposition. When the base is uneasy or worse, the last
    vote that cost the delegate with it is named as well. Under a secret ballot (`secret`) the base cannot see the
    delegate's votes, and the line says so instead of saying it watches them."""
    base = _base(state)
    if not base:
        return ""
    spec = BASES[base["id"]]
    level = mood(base)
    watch = "votes are secret, so it cannot see yours" if secret else "it watches your votes"
    line = f"YOUR BASE: {spec['name']} (put you forward; {watch}): {level}."
    cost = base.get("last_cost")
    if level != "steady" and cost:
        summary = f" ({cost['summary']})" if cost.get("summary") else ""
        line += (f" The last vote that cost you with it: your {cost['vote']} on {cost['motion']}{summary} "
                 f"in Month {cost['month'] + 1}.")
    return line


def scorecard(state: dict) -> dict:
    """A delegate's base at the end of a run, for the scorecard."""
    base = (state or {}).get("base") or {}
    return {"id": base.get("id", ""), "support_final": base.get("support"),
            "disowned_month": base.get("disowned_month")}
