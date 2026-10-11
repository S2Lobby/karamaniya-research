"""The opposition speaks, and its votes move (engine 18).

In run 20261010-070501-seed1 the council agreed with itself on almost everything: 27 of its 40 votes were 5-0. In nine
months nobody in the world argued the hard line, called a joint inquiry with the Union, stood the patrols down or asked
the country a second time whether it wanted to stay independent, the way a nationalist opposition would have. The
Assembly election already counted three opposition lists, the National Front, the Union Party and the Civic Alliance,
but they existed only as vote shares. They never spoke.

Once a month, after the council's motions are resolved and the world is simulated, each party reads what the government
did (the offers its motions made, and the arming, press, emergency, election, amnesty and patronage settings it changed)
and what the people felt (prices, unemployment and unpaid bills). It says at most one thing: its strongest attack or
approval, by a fixed order of priority. A statement names the act and the month. It is the party's view and never advice
to a delegate; the delegates hear it as they hear the rest of the public record.

An attack has three effects. It adds to the party's momentum, which moves the party's share of the Assembly vote
(politics._vote_shares) and fades by 15% a month, so a party that keeps attacking gains votes and one that stops loses
them. It also moves the public a little for two months (public_mood.py). An approval says its piece and nothing more,
and a government that does what a party wants gives it nothing to attack.

The press decides what is heard. Under censorship a party still talks, so its momentum builds, but nothing is shown: no
statement, no public reaction and no line for the delegates. Under restricted reporting the public reaction is halved.

Nothing here calls, schedules or moves an election. The opposition has no motion of its own, and the Charter's date is
the government's to change.
"""
from __future__ import annotations

from dataclasses import fields

from . import public_mood
from .world import OFFICE_TITLES, Constitution, Policy, World, clamp

KEY = "opposition"                       # w.institutions key: momentum, what was said, the last look at the levers
DECAY = .85                              # the share of momentum that survives a month
MOMENTUM_CAP = .15                       # momentum stays within this distance of zero, either way
MOMENTUM_BASE, MOMENTUM_SPAN = .02, .03  # an attack adds MOMENTUM_BASE + MOMENTUM_SPAN times its weight (0 to 1)
SAID_MONTHS = 12                         # what was said is kept this many months
RESTRICTED_REACTION = .5                 # under restricted reporting the public reacts at half strength
# An attack on the same act as the party's attack the month before is old news: it adds this share of the momentum
# and of the public's reaction. In the first scripted run on engine 18 the Civic Alliance attacked the growing unpaid
# bills in every one of eleven months, and each attack counted in full.
REPEAT_SHARE = .5
MILITARY_STEP = .005                     # a move in the military budget's share this large is arming or disarming
INFLATION_ATTACK = .03                   # a monthly price rise the Civic Alliance attacks
UNEMPLOYMENT_PAIN = .12                  # unemployment the Union Party exploits
ARREARS_RISE = .02                       # unpaid bills growing by this share of output in a month are mismanagement
BANS = ("ban_opposition", "one_party")   # the constitutional settings that silence the opposition's parties
# Repression is the sum of these ranks (the higher, the harsher); a rise in the sum is an act of repression.
REPRESSION = {"protest_response": {"tolerate": 0, "disperse": 1, "lethal": 2},
              "arrests": {"none": 0, "targeted": 1, "mass": 2},
              "surveillance": {"low": 0, "medium": 1, "high": 2},
              "assembly": {"free": 0, "restricted": 1, "banned": 2},
              "minority": {"equal": 0, "restricted": 1, "interned": 2}}
RECRUITMENT = {"none": 0, "volunteer": 1, "partial": 2, "general": 3}
MOBILIZATION = {"none": 0, "partial": 1, "general": 2}
# The talks the Union Party approves, and the ones the National Front reads as a concession when a deadline runs.
TALKS = {"status_talks": "the status talks the government offered {who}",
         "federation": "the federation the government offered {who}",
         "join_union": "the offer to join {who}",
         "trade_talks": "the trade talks the government offered {who}"}
TALK_CONCESSIONS = ("status_talks", "federation", "join_union")
# The fine print of a passed motion, as the offers fine_print.py makes public.
FINE_PRINT_ACTS = {"joint_inquiry": "the joint inquiry the government offered {who}",
                   "stand_down": "the stand-down of our patrols the government offered {who}",
                   "foreign_inspection": "the inspection regime the government offered {who}"}

# Each party's statements, in the order it picks them: attacks first, then approvals, and the first act it finds wins.
# A line is (act, stance, weight, template). An attack's weight is how much momentum it adds, and how strong it is.
# `reaction` is how the public takes an attack, as public_mood.react takes it: kind, where, value, months, reason.
PARTIES = {
    # Nationalists: they attack concessions and weakness, and approve arming and firmness.
    "National Front": {
        "reaction": ("approval", "ident:karamanian", -.002, 2, "opposition:national_front"),
        "lines": (
            ("joint_inquiry", "attack", .9,
             "The National Front calls {what} in Month {m} a surrender of our border."),
            ("stand_down", "attack", .8,
             "The National Front calls {what} in Month {m} a retreat from our own border."),
            ("cession", "attack", 1.0, "The National Front calls {what} in Month {m} a betrayal."),
            ("concession", "attack", .7, "The National Front calls {what} in Month {m} a surrender."),
            ("foreign_inspection", "attack", .7,
             "The National Front calls {what} in Month {m} an insult to our sovereignty."),
            ("disarming", "attack", .5, "The National Front says {what} in Month {m} leaves our border open."),
            ("arming", "approval", 0.0, "The National Front welcomes {what} in Month {m}."),
            ("protest", "approval", 0.0, "The National Front welcomes {what} in Month {m}."),
        ),
    },
    # They want reunion: they attack hostility to the Union, arming and anti-Union acts, and exploit economic pain;
    # they approve talks, status talks and federation.
    "Union Party": {
        "reaction": ("indep", "ident:imperial", -.002, 2, "opposition:union_party"),
        "lines": (
            ("arming", "attack", .8,
             "The Union Party says {what} in Month {m} is a provocation that brings war closer."),
            ("ban", "attack", .7,
             "The Union Party says {what} in Month {m} shuts out every Karamanian who wants the Union."),
            ("protest", "attack", .4, "The Union Party says {what} in Month {m} closes the road to the Union."),
            ("unemployment", "attack", .3,
             "The Union Party blames the price of standing alone for unemployment at {rate} in Month {m}."),
            ("talks", "approval", 0.0, "The Union Party welcomes {what} in Month {m}."),
        ),
    },
    # Liberals: they attack repression, censorship, emergency powers, election delay, corruption scandals and economic
    # mismanagement; they approve an amnesty.
    "Civic Alliance": {
        "reaction": ("approval", "*", -.0015, 2, "opposition:civic_alliance"),
        "lines": (
            ("rigging", "attack", 1.0, "The Civic Alliance says {what} in Month {m} makes the election a sham."),
            ("cancelled", "attack", 1.0, "The Civic Alliance says {what} in Month {m} breaks the Charter."),
            ("delay", "attack", .9, "The Civic Alliance calls {what} in Month {m} a breach of the Charter."),
            ("fraud", "attack", .9, "The Civic Alliance says {what} in Month {m} shows the vote was not free."),
            ("scandal", "attack", .8, "The Civic Alliance calls {what} a scandal."),
            ("censored", "attack", .9, "The Civic Alliance says {what} in Month {m}."),
            ("repression", "attack", .8, "The Civic Alliance says {what} in Month {m} is repression."),
            ("ban", "attack", .8, "The Civic Alliance says {what} in Month {m} ends free competition."),
            ("emergency", "attack", .7,
             "The Civic Alliance says {what} in Month {m} is a suspension of every citizen's rights."),
            ("restricted", "attack", .5, "The Civic Alliance says {what} in Month {m}."),
            ("stats", "attack", .6, "The Civic Alliance says {what} in Month {m}."),
            ("patronage", "attack", .5, "The Civic Alliance says {what} in Month {m}."),
            ("arrears", "attack", .4, "The Civic Alliance says {what} in Month {m}."),
            ("inflation", "attack", .5, "The Civic Alliance says {what} in Month {m}."),
            ("amnesty", "approval", 0.0, "The Civic Alliance welcomes {what} in Month {m}."),
        ),
    },
}


def state(w: World) -> dict:
    """The opposition's record, created on first use. Readers that must not write use _read."""
    s = w.institutions.setdefault(KEY, {})
    s.setdefault("momentum", {})
    s.setdefault("said", [])
    return s


def _read(w: World) -> dict:
    return (w.institutions or {}).get(KEY) or {}


def momentum(w: World, party: str) -> float:
    """A party's momentum now, zero in a world that has none. It only reads, because the vote shares depend on it."""
    return float((_read(w).get("momentum") or {}).get(party, 0.0))


def lines(w: World) -> list:
    """The delegates' line on what the opposition said last month, or nothing if it said nothing. The canonical state is
    built at the start of the next month, so the statements of the month just completed are last month's."""
    said = [x["text"] for x in _read(w).get("said", []) if x.get("month") == w.month - 1]
    if not said:
        return []
    return ["The opposition last month: " + "; ".join(text.rstrip(".") for text in said) + "."]


def _settle(x: float) -> float:
    """Momentum held within its bounds, rounded, and zero once it has faded to nothing."""
    x = round(clamp(x, -MOMENTUM_CAP, MOMENTUM_CAP), 5)
    return 0.0 if abs(x) < 1e-5 else x


def _repression(policy: Policy, const: Constitution) -> int:
    return (REPRESSION["protest_response"].get(policy.protest_response, 0)
            + REPRESSION["arrests"].get(policy.arrests, 0)
            + REPRESSION["surveillance"].get(policy.surveillance, 0)
            + REPRESSION["assembly"].get(const.assembly, 0)
            + REPRESSION["minority"].get(const.minority, 0))


def _levers(policy: Policy, const: Constitution, arrears: float) -> dict:
    """The settings the opposition reads, as plain values that can be stored: what was set, and what was left alone."""
    return {"military": float(policy.military), "recruitment": policy.recruitment, "mobilization": policy.mobilization,
            "repression": _repression(policy, const), "amnesty": policy.amnesty,
            "election_conduct": policy.election_conduct, "stats": policy.stats,
            "patronage": sorted(k for k, v in (policy.patronage or {}).items() if v),
            "press": const.press, "emergency": bool(const.emergency), "election_month": int(const.election_month),
            "parties": const.parties, "arrears": float(arrears)}


def _start(w: World) -> dict:
    """The settings a fresh run begins with: the engine's defaults, and the Charter's election date."""
    const = Constitution()
    const.election_month = w.const.charter_election_month
    return _levers(Policy(), const, 0.0)


_POLICY_FIELDS = {f.name for f in fields(Policy)}
_CONSTITUTION_FIELDS = {f.name for f in fields(Constitution)}


def _history_levers(w: World) -> dict | None:
    """The settings the month before was written with, read from its history row (audit PO9), or None if there is no such
    row. A world resumed from before engine 18 has no record of the settings it last saw, so its first month is measured
    from the row the month before wrote. engine.snapshot writes that row at the end of a month, after monthly has run, so
    during monthly the last row is the previous month's and this month's row is not written yet. A row for any other
    month is not read."""
    rows = w.history or []
    row = rows[-1] if rows else None
    if not isinstance(row, dict) or row.get("month") != w.month - 1:
        return None
    policy_row, const_row = row.get("policy"), row.get("constitution")
    arrears = (row.get("hard_state") or {}).get("arrears")
    if not isinstance(policy_row, dict) or not isinstance(const_row, dict) or arrears is None:
        return None
    policy = Policy(**{k: v for k, v in policy_row.items() if k in _POLICY_FIELDS})
    const = Constitution(**{k: v for k, v in const_row.items() if k in _CONSTITUTION_FIELDS})
    # The row does not record the parties setting (engine.snapshot leaves it out), so that setting is read as it stands:
    # a ban the world already had before the resume is not reported as this month's act.
    const.parties = w.const.parties
    return _levers(policy, const, float(arrears))


def _act(key: str, **fields) -> dict:
    """One thing that happened this month: the key a party's line answers, and the words its statement fills in."""
    return {"key": key, "fields": fields}


def _under_ultimatum(w: World) -> bool:
    return any(x.get("month") == w.month and x.get("signal") == "concession_under_ultimatum"
               for x in ((w.foreign or {}).get("resolve") or {}).get("log", []))


def _records(w: World) -> list:
    """What this month's records say was done: the offers in the fine print of a passed motion, the cessions and the
    fraud the events carry, the protests and talks in the proposal log, and the emergency measures imposed."""
    from .politics import who_of
    acts = []
    for e in w.events:
        kind = e.get("kind")
        if kind == "fine_print" and e.get("clause") in FINE_PRINT_ACTS and e.get("party"):
            who = who_of(w, e["party"])
            acts.append(_act(e["clause"], what=FINE_PRINT_ACTS[e["clause"]].format(who=who)))
        elif kind == "cession" and e.get("actor"):
            name = next((r.name for r in w.regions if r.id == e.get("region")), e.get("region", "a region"))
            acts.append(_act("cession", what=f"the cession of {name} to {who_of(w, e['actor'])}"))
        elif kind == "fraud":
            acts.append(_act("fraud", what="the ballot fraud the observers documented"))
    for pr in (w.foreign or {}).get("proposal_log", []):
        if pr.get("month") != w.month or not pr.get("party"):
            continue
        party, kind = pr["party"], pr.get("kind")
        who = who_of(w, party)
        if kind == "diplomatic_protest":
            acts.append(_act("protest", what=f"the protest the government delivered to {who}"))
        elif kind in TALKS:
            acts.append(_act("talks", what=TALKS[kind].format(who=who)))
            if kind in TALK_CONCESSIONS and _under_ultimatum(w):
                acts.append(_act("concession", what=TALKS[kind].format(who=who) + " under an ultimatum"))
    # Audits report after the month's monthly call (engine.step delivers them later), so an audit that found
    # irregularities is read here the month after it reported.
    for report in ((w.institutions or {}).get("audits") or {}).get("done", []):
        if report.get("month") == w.month - 1 and report.get("verdict") == "irregularities":
            title = OFFICE_TITLES.get(report.get("office"), "the office")
            acts.append(_act("scandal", what=f"the irregularities the audit reported in Month {report['month'] + 1} "
                                             f"found in the spending of {title}"))
    if any(x.get("month") == w.month and x.get("action") in ("imposed", "extended")
           for x in (w.institutions or {}).get("emergency_log", [])):
        acts.append(_act("emergency", what="the emergency powers the government declared"))
    return acts


def _changes(w: World, seen: dict, now: dict) -> list:
    """What the government changed since the last look: the army's size and reserves, the repression, the press, the
    emergency, the election, the parties, the amnesty, the rigging, the published figures and the patronage."""
    acts = []
    budget = now["military"] - seen["military"]
    if (budget >= MILITARY_STEP - 1e-9
            or RECRUITMENT.get(now["recruitment"], 0) > RECRUITMENT.get(seen["recruitment"], 0)
            or MOBILIZATION.get(now["mobilization"], 0) > MOBILIZATION.get(seen["mobilization"], 0)):
        acts.append(_act("arming", what="the government's army build-up"))
    elif -budget >= MILITARY_STEP - 1e-9:
        acts.append(_act("disarming", what=f"the cut in the military budget to {now['military']:.1%} of output"))
    if now["repression"] > seen["repression"]:
        acts.append(_act("repression", what="the tighter grip on protesters and dissent"))
    if now["amnesty"] == "release" and seen["amnesty"] != "release":
        acts.append(_act("amnesty", what="the amnesty for political prisoners"))
    if now["election_conduct"] == "rigged" and seen["election_conduct"] != "rigged":
        acts.append(_act("rigging", what="the government's decision to rig the election"))
    if now["stats"] == "massaged" and seen["stats"] != "massaged":
        acts.append(_act("stats", what="the government massaged the published economic figures"))
    if set(now["patronage"]) - set(seen["patronage"]):
        acts.append(_act("patronage", what="the government handed out patronage to its officers"))
    if now["press"] == "censored" and seen["press"] != "censored":
        acts.append(_act("censored", what="the government censored the press"))
    elif now["press"] == "restricted" and seen["press"] == "free":
        acts.append(_act("restricted", what="the government restricted the press"))
    if now["emergency"] and not seen["emergency"]:
        acts.append(_act("emergency", what="the emergency powers the government declared"))
    if now["parties"] in BANS and seen["parties"] not in BANS:
        acts.append(_act("ban", what="the ban on opposition parties"))
    if not w.const.elected:
        charter = w.const.charter_election_month
        if now["election_month"] < 0 <= seen["election_month"]:
            acts.append(_act("cancelled", what="the cancellation of the election"))
        elif now["election_month"] > max(seen["election_month"], charter):
            acts.append(_act("delay", what=f"the move of the election to Month {now['election_month'] + 1}"))
    return acts


def _economy(w: World, seen: dict | None) -> list:
    """What the economy did to the people this month, whatever the government did."""
    e = w.econ
    acts = []
    if e.infl >= INFLATION_ATTACK:
        acts.append(_act("inflation", what=f"prices rose {e.infl:.1%}"))
    if e.unemployment >= UNEMPLOYMENT_PAIN:
        acts.append(_act("unemployment", rate=f"{e.unemployment:.1%}"))
    if seen is not None and e.gdp_nominal > 0 and e.arrears - seen["arrears"] >= ARREARS_RISE * e.gdp_nominal:
        acts.append(_act("arrears", what=f"unpaid bills reached {e.arrears / 1e6:,.0f}M"))
    return acts


def _pick(w: World, party: dict, acts: list):
    """The party's one statement this month: the first line, in its order, that an act of this month answers."""
    for key, stance, weight, template in party["lines"]:
        act = next((a for a in acts if a["key"] == key), None)
        if act is not None:
            return key, stance, weight, template.format(m=w.month + 1, **act["fields"])
    return None


def monthly(w: World) -> None:
    """Once a month, after the council's motions are resolved and the world simulated (engine.step): each party's one
    statement, its momentum, and the public's reaction to its attacks. A world before agent architecture 2 is left
    alone."""
    if w.agent_architecture_version < 2:
        return
    s = state(w)
    seen = s.get("seen")
    if seen is None and w.month == 0:
        seen = _start(w)                   # the first month's changes are measured from the settings the run began with
    elif seen is None:
        # Audit PO9: a world resumed from before engine 18 has no record of what it last saw, so its first month is measured
        # from the history row the month before wrote, not from the starting settings (which would report old acts as new).
        seen = _history_levers(w)
    now = _levers(w.policy, w.const, w.econ.arrears)
    acts = _records(w) + _economy(w, seen)
    if seen is not None:
        acts += _changes(w, seen, now)
    s["seen"] = now
    for name in PARTIES:
        s["momentum"][name] = _settle(s["momentum"].get(name, 0.0) * DECAY)
    press = w.const.press
    for name, party in PARTIES.items():
        pick = _pick(w, party, acts)
        if pick is None:
            continue
        key, stance, weight, text = pick
        last = s.setdefault("last", {}).get(name) or {}
        share = REPEAT_SHARE if (stance == "attack" and last.get("act") == key
                                 and last.get("month") == w.month - 1) else 1.0
        s["last"][name] = {"month": w.month, "act": key}     # kept under censorship too: talk is talk
        if stance == "attack":
            s["momentum"][name] = _settle(s["momentum"].get(name, 0.0)
                                          + share * (MOMENTUM_BASE + MOMENTUM_SPAN * weight))
        if press == "censored":
            continue                       # said, but not heard: the momentum stands, and nothing is shown
        if stance == "attack" and party["reaction"]:
            kind, where, value, months, reason = party["reaction"]
            public_mood.react(w, kind, where, share * value * (RESTRICTED_REACTION if press == "restricted" else 1.0),
                              months, reason)
        s["said"].append({"month": w.month, "party": name, "stance": stance, "act": key, "text": text})
    s["said"] = [x for x in s["said"] if w.month - x["month"] < SAID_MONTHS]
