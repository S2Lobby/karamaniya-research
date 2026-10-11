"""Who fired at the border becomes clearer in the months after (engine 18).

In run 20261010-070501-seed1, Month 5, a shooting on the eastern border left casualties and each side blamed the
other. The Army post's accounts contradicted each other and the forensic results "will take weeks". They never came.
The council, unsure who had fired, invited the Union into a joint inquiry (fine_print.py), and that inquiry's finding
was drawn the same way whatever had happened. Nothing in the world ever revealed what had happened, although the engine
had decided it: each border incident has a hidden perpetrator (dilemmas.py), a union patrol, smugglers or our own troops.

So the truth comes out on its own schedule, and the delegates see only what it does to their information. The Army
staff's forensic reports come in the two months after the shooting (intelligence.py). Their estimate of the chance that
the Union's side fired follows the evidence, and a staff that is slow to blame its own soldiers reads high when they
fired. Three months on, the press may learn who fired: a Union patrol rallies the country to the government, and our own
troops cost it approval and hand the Union propaganda. A joint inquiry that reports later finds what the evidence
supports, as steered by the Union (fine_print.py). No delegate is told what to decide; these are the consequences of
what happened on the border.
"""
from __future__ import annotations

from . import public_mood
from .opposition import RESTRICTED_REACTION
from .world import World, clamp, rng_for

KEY = "incidents"                # w.institutions key: the border incidents on record, with their hidden perpetrators
UNION_PATROL = "union patrol"
SMUGGLERS = "smugglers"
OWN_TROOPS = "our own troops"
# The chance the evidence assigns to the Union's side having fired, which the forensic reports estimate (0-100).
TRUTH = {UNION_PATROL: 85.0, SMUGGLERS: 25.0, OWN_TROOPS: 10.0}
FORENSIC_AFTER = (1, 2)          # the Army staff's forensic reports fall due this many months after the shooting starts
ALARMING_AT = 70.0               # a forensic estimate this high is urgent
# A staff is slow to blame its own soldiers, so when they fired its reading of the Union's guilt sits this far above the
# evidence, before any error is drawn: the staff reads high, and an error then moves that reading as it moves any other.
OWN_TROOPS_BIAS = 20.0
LEAK_MONTH = 3                   # the press may learn who fired this many months after the shooting starts
LEAK_CHANCE = .5                 # the chance it does ...
LEAK_FREE_BONUS = .3             # ... plus this much when the press is free
REACTION_MONTHS = 3              # how long a public reaction to what the press learned lasts
LEAK_UNION_APPROVAL = .003       # a Union patrol's fire, learned: a rally to the government (monthly, for REACTION_MONTHS)
LEAK_UNION_RALLY = .05           # ... the rally-round-the-flag share
LEAK_UNION_PROPAGANDA = .03      # ... and the Union's propaganda loses this much
LEAK_OWN_APPROVAL = -.004        # our own troops' fire, learned: the country's approval falls (monthly, for REACTION_MONTHS)
LEAK_OWN_PROPAGANDA = .05        # ... and the Union's propaganda gains this much
RECORD_MONTHS = 12               # an incident stays on record this long, for its leak and the inquiries about it
FINDING_WINDOW = 6               # a joint inquiry's finding draws on an incident this recent
# A joint inquiry's finding, by who fired (the Union steers it): the chance it blames Karamanian soldiers, and the
# chance it is inconclusive. The rest blames the other side. Without a recent incident, fine_print.FINDING_CUTS applies.
FINDING = {UNION_PATROL: (.3, .6), SMUGGLERS: (.4, .5), OWN_TROOPS: (.85, .15)}


def records(w: World) -> list:
    """The border incidents on record, oldest first. Empty before the first one, and it creates no key until then."""
    return list((w.institutions or {}).get(KEY, []))


def record(w: World, issue: dict) -> dict | None:
    """Put a border incident on record as its issue is raised: its start month and its hidden perpetrator. The issue
    itself lives a single month; the incident outlives it, for its forensic reports, its leak and the inquiries about it."""
    truth = issue.get("truth") or {}
    if truth.get("perpetrator") not in TRUTH:
        return None
    entry = {"id": issue["id"], "month": int(issue["month"]), "region": issue.get("region"),
             "perpetrator": truth["perpetrator"], "learned": None}
    w.institutions.setdefault(KEY, []).append(entry)
    return entry


def due(w: World) -> dict | None:
    """The incident whose forensic report the Army staff owes this month: one that started one or two months ago."""
    for entry in records(w):
        if w.month - entry["month"] in FORENSIC_AFTER:
            return entry
    return None


def forensic_step(w: World) -> int:
    """Which forensic report this is: 1 in the month after the shooting started, 2 in the month after that, else 0."""
    entry = due(w)
    return w.month - entry["month"] if entry is not None else 0


def confidence(w: World) -> str:
    """The first forensic report is low confidence, because the accounts from the post still conflict; the second is medium."""
    return "low" if forensic_step(w) == 1 else "medium"


def truth(w: World) -> float:
    """What the forensic reports estimate: the evidence's chance that the Union's side fired, for the incident whose
    report is due (else the newest on record; 0 when there is none). It is the engine's hidden truth and is never shown
    directly. The due incident comes first so that a second shooting soon after cannot lend the first one's report its
    truth while the staff's bias (staff_bias) is still that of the first."""
    entry = due(w)
    if entry is None:
        past = [x for x in records(w) if x["month"] <= w.month]
        if not past:
            return 0.0
        entry = max(past, key=lambda x: x["month"])
    return TRUTH.get(entry["perpetrator"], 0.0)


def staff_bias(w: World) -> float:
    """How far the Army staff's reading sits above the evidence before any error: OWN_TROOPS_BIAS when its own soldiers fired."""
    entry = due(w)
    return OWN_TROOPS_BIAS if entry is not None and entry["perpetrator"] == OWN_TROOPS else 0.0


def finding_cuts(w: World) -> tuple | None:
    """The two cut points of a joint inquiry's roll, when a border incident within FINDING_WINDOW months is on record:
    under the first the finding blames Karamanian soldiers, under the second it is inconclusive, and otherwise it blames
    the other side. None when there is no such incident, so the finding is drawn as it was before incidents had truths."""
    recent = [x for x in records(w) if 0 <= w.month - x["month"] < FINDING_WINDOW and x["perpetrator"] in FINDING]
    if not recent:
        return None
    blame, inconclusive = FINDING[max(recent, key=lambda x: x["month"])["perpetrator"]]
    return blame, blame + inconclusive


def leaks(w: World) -> list:
    """Each month: the press may learn who fired on the border, three months after it started. The chance is LEAK_CHANCE,
    plus LEAK_FREE_BONUS when the press is free, drawn from the month's own stream. Incidents too old to matter are
    forgotten here. Returns the incidents the press learned of this month."""
    items = w.institutions.get(KEY)
    if not items:
        return []
    learned = []
    for entry in items:
        if entry["learned"] is None and w.month - entry["month"] == LEAK_MONTH:
            rng = rng_for(w.seed, w.month, "incident-leak")
            chance = LEAK_CHANCE + (LEAK_FREE_BONUS if w.const.press == "free" else 0.0)
            entry["learned"] = rng.random() < chance
            if entry["learned"]:
                learn(w, entry)
                learned.append(entry)
    items[:] = [x for x in items if w.month - x["month"] < RECORD_MONTHS]
    return learned


def learn(w: World, entry: dict) -> None:
    """The press has learned what the shooting was: an event for everyone, and what that does to the country. A censored
    press knows it and cannot print it (Audit TO12): the truth is recorded as learned but unpublished, with a private
    event only, and no public reaction or propaganda change, as opposition.py leaves a censored statement unheard.
    Restricted reporting halves the public reaction, as opposition.py does."""
    who, when = entry["perpetrator"], f"Month {entry['month'] + 1}"
    public = w.const.press != "censored"
    share = RESTRICTED_REACTION if w.const.press == "restricted" else 1.0
    entry["published"] = public
    if who == UNION_PATROL:
        union = (w.names or {}).get("union", "Union")
        if public:
            public_mood.react(w, "approval", "ident:karamanian", LEAK_UNION_APPROVAL * share, REACTION_MONTHS,
                              "incident:union_fired")
            w.dip.rally = clamp(w.dip.rally + LEAK_UNION_RALLY)
            w.dip.propaganda = clamp(w.dip.propaganda - LEAK_UNION_PROPAGANDA)
        text = f"The press has learned that the shots on the border in {when} were fired by a {union} patrol."
    elif who == OWN_TROOPS:
        if public:
            public_mood.react(w, "approval", "*", LEAK_OWN_APPROVAL * share, REACTION_MONTHS, "incident:our_troops")
            w.dip.propaganda = clamp(w.dip.propaganda + LEAK_OWN_PROPAGANDA)
        text = f"The press has learned that the shots on the border in {when} were fired by our own troops."
    else:
        text = f"The press has learned that the shots on the border in {when} were fired by smugglers."
    w.event("incident_leak", text, importance=2, public=public, incident=entry["id"])
