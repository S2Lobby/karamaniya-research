"""The fine print of a motion becomes a real offer (engine 17).

A motion is voted on as its words and its terms, and those can offer a hostile power something the structured
action does not carry: a joint inquiry into an incident, a stand-down of troops on a front, an inspection regime
over Karamanian shipping. In run 20261010-070501-seed1, Month 5, the council passed 5-0 a formal protest to the
Solvaran Union over a shooting on the eastern border. Its text also demanded a joint fact-finding investigation
with published findings, a mutual stand-down of patrols near the incident sector and a reaffirmation of the
non-aggression pact, and the Army and Interior ministers who voted yes volunteered their border post's records.
The engine executed it as a plain protest. Nobody reacted, and army loyalty kept rising.

So the clauses are read here. Once the council passes a motion, each clause it offers is public and the world
answers it: the ministry that must share its work resents it (ministries.py), the public reads a stand-down or a
foreign inspector as a loss of face (public_mood.py), a hostile power accepts an inquiry it can steer and reports
two months later, and a front that is stood down is held more thinly (military._front_defence) until the time
runs out or the other side matches it. No delegate is told what to decide; these are the consequences of what the
motion offered.
"""
from __future__ import annotations

import re

from . import ministries, motion_actions, public_mood
from .world import World, clamp, rng_for

KEY = "fine_print"                              # w.institutions key for the offers this run has opened
ADVERSARIES = ("union", "veleria", "dorsania")  # the parties an offer can be made to; the League is not an adversary
NEGATION_WINDOW = 4                             # words before a match in which a negation rules the clause out
INQUIRY_ACCEPT = .75                            # the chance a hostile power accepts an inquiry it can steer
INQUIRY_MONTHS = 2                              # months from an inquiry's opening to its finding
STANDDOWN_MONTHS = 2                            # months a stand-down holds, counting the month it is made
STANDDOWN_DEFENCE = .85                         # a stood-down front's strength while the other side has not matched it
MATCH_WEARINESS = .3                            # the Union or Veleria matches a stand-down above this weariness
MATCH_TRUST = .5                                # Dorsania matches one above this trust in Karamaniya
FINDING_CUTS = (.6, .9)                         # a finding's roll: under .6 blames our soldiers, under .9 is inconclusive
# What an offer does, in the units the engine already uses: grievances (ministries.MAX caps them), monthly public
# reactions (public_mood.LIMIT caps each), and propaganda and rally, which are shares of one.
ARMY_INVITED = .06           # Army Command, when a hostile power's investigators are invited onto its own border
INTERIOR_SHARED = .04        # the police, when the government shares its investigation with that power
ARMY_STANDDOWN = .05         # Army Command, when it is ordered to pull back from its own border
ARMY_UNMATCHED = .03         # Army Command, when the other side does not match a stand-down
NAVY_INSPECTED = .06         # the Naval staff, with a hostile power's inspectors aboard Karamanian ships
ARMY_FINDING = .04           # Army Command, when a joint inquiry finds against its soldiers
APPROVAL_INQUIRY = -.004     # Karamanian approval, a monthly modifier for three months: the offer, and its finding
APPROVAL_STANDDOWN = -.002   # the same, for two months
APPROVAL_INSPECTION = -.003  # the same, for three months
PROPAGANDA_INQUIRY = .03     # what an offer of a joint inquiry adds to propaganda
PROPAGANDA_BLAME = .06       # a finding that blames Karamanian soldiers
PROPAGANDA_INCONCLUSIVE = .02  # a finding that cannot say who was responsible
PROPAGANDA_OTHER = .05       # a finding that blames the other side costs propaganda ...
RALLY_OTHER = .05            # ... and rallies the country by this much

READABLE = {"joint_inquiry": "a joint inquiry", "stand_down": "a stand-down of Karamanian patrols",
            "foreign_inspection": "an inspection regime over Karamanian shipping"}
FRONT_WORDS = {"north": r"\bnorth(?:ern)?\b|\bkessel\b", "east": r"\beast(?:ern)?\b|\bdorran\b"}
FRONT_NAMES = {"north": "northern", "east": "eastern"}

CLAUSES = {
    "joint_inquiry": (
        r"\bjoint\s+(?:[\w-]+\s+){0,2}(?:investigation|inquiry|enquiry|commission|probe)",
        # Inspectors aboard ships are an inspection regime, which foreign_inspection reads, not an inquiry.
        r"\b(?:international|foreign|union|velerian|dorsanian)\s+(?:investigators?|inspectors?|monitors?|observers?)\b"
        r"(?!\s+(?:aboard|on|at|of|in)\s+(?:our\s+|karamanian\s+)?(?:ships|shipping|vessels|ports?|cargo))",
        r"\bfact[\s-]?finding\s+(?:mission|commission|team|investigation|inquiry)\b",
    ),
    "stand_down": (
        r"\bstand[\s-]?downs?\b",
        r"\bpull(?:s|ing|ed)?\s+back\b[^.;]{0,40}\b(?:troops|forces|patrols|units|soldiers)\b",
        r"\bwithdraw(?:al|s|ing)?\s+(?:of\s+)?(?:our\s+|karamanian\s+)?(?:troops|forces|patrols|units|soldiers)\b",
        r"\bdemilitari[sz](?:ed|ation)\b",
        r"\bbuffer\s+zone\b",
        r"\bdisengage(?:ment)?\b",
    ),
    "foreign_inspection": (
        r"\binspection\s+regime\b",
        r"\b(?:union|velerian|dorsanian|foreign)\s+inspect(?:ion|ions|ors?)\s+(?:of|on|at|aboard)\s+"
        r"(?:our\s+|karamanian\s+)?(?:ships|shipping|vessels|ports?|cargo(?:es)?)\b",
        r"\b(?:accept|allow|permit)\w*\s+(?:the\s+)?(?:union|velerian|dorsanian|foreign)\w*\s+"
        r"(?:right\s+to\s+)?inspect",
    ),
}
# The words that rule an act out when they come just before it: "no federation" names no federation.
NEGATED = re.compile(r"\b(?:no|not|never|without|nor|excluding|refus(?:e|es|ed)|reject(?:s|ed)?|rules?\s+out)\b", re.I)


def active(w: World) -> bool:
    """Engine 17 reads the fine print; a world from before agent architecture 2 does not."""
    return getattr(w, "agent_architecture_version", 1) >= 2


def state(w: World) -> dict:
    """The offers this run has opened and not yet closed: stand-downs, inquiries and inspections."""
    s = w.institutions.setdefault(KEY, {})
    s.setdefault("standdowns", [])
    s.setdefault("inquiries", [])
    s.setdefault("inspections", [])
    return s


def _name(w: World, party: str) -> str:
    return (w.names or {}).get(party, party)


def _the(w: World, party: str) -> str:
    """The party as a phrase in an event: "the Solvaran Union", but "Veleria" and "Dorsania" as they are."""
    name = _name(w, party)
    return f"the {name}" if party == "union" else name


# ---- reading a text ----------------------------------------------------------------------------------
def _asserted(text: str, pattern: str) -> bool:
    """Whether a pattern matches the text where the text asserts it. A match with a negation in the few words
    before it, in the same sentence, is the text ruling the act out, and does not count."""
    for match in re.finditer(pattern, text, re.I):
        sentence = re.split(r"[.;:!?]", text[:match.start()])[-1]
        words = re.findall(r"[A-Za-z'-]+", sentence)[-NEGATION_WINDOW:]
        if not NEGATED.search(" ".join(words)):
            return True
    return False


def clauses(w: World, text: str, party: str | None) -> list:
    """The clause kinds a text offers the party it is addressed to, sorted. A text addressed to the League
    offers none: the League is not an adversary."""
    if not active(w) or party not in ADVERSARIES:
        return []
    body = str(text or "")
    return sorted(kind for kind, patterns in CLAUSES.items() if any(_asserted(body, p) for p in patterns))


def detection_text(mo: dict, action: dict) -> str:
    """What a motion says: its words and the terms of its structured action, read as one text."""
    terms = action.get("terms") if isinstance(action, dict) else None
    parts = [str(mo.get("text") or "")]
    if isinstance(terms, list):
        parts += [str(term).strip() for term in terms if str(term).strip()]
    return ". ".join(part for part in parts if part)


def invited_party(w: World, text: str) -> str | None:
    """The hostile power an investigation's text names first (the Union, Veleria or Dorsania), or None."""
    names = w.names or {}
    named = {"union": (names.get("union", "Solvaran Union"), r"\bUnion\b"),
             "veleria": (names.get("veleria", "Veleria"), r"\bVeleria\b"),
             "dorsania": (names.get("dorsania", "Dorsania"), r"\bDorsania\b")}
    body = str(text or "")
    found = []
    for party, (name, word) in named.items():
        match = re.search(f"{re.escape(name)}|{word}", body, re.I)
        if match:
            found.append((match.start(), party))
    return min(found)[1] if found else None


def investigation_offer(w: World, text: str) -> tuple:
    """What an investigation offers: the hostile power whose investigators it invites (or None), and the joint
    inquiry it opens with them. The council's own audit of an office is not touched by this."""
    party = invited_party(w, text)
    found = ["joint_inquiry"] if party and "joint_inquiry" in clauses(w, text, party) else []
    return party, found


def motion_clauses(w: World, mo: dict) -> list:
    """The clauses a motion offers, as standing.py reads them for the audiences that watch votes: a diplomacy
    motion's clauses for the party it is addressed to, or the joint inquiry an investigation invites."""
    if not active(w):
        return []
    if mo.get("type") == "diplomacy":
        from .politics import DIPLOMACY
        action = motion_actions.structured_action(w, mo)
        party = motion_actions.party_of(action.get("target")) or DIPLOMACY.get(str(mo.get("subject") or "").strip())
        return clauses(w, detection_text(mo, action), party)
    if mo.get("type") == "investigation":
        return investigation_offer(w, str(mo.get("text") or ""))[1]
    return []


# ---- the offer, once the council has passed it ---------------------------------------------------------
def _fronts(w: World, text: str) -> list:
    """The fronts a stand-down covers: the ones the text names, else the front of the newest live border incident,
    else both."""
    named = [front for front, pattern in FRONT_WORDS.items() if re.search(pattern, text, re.I)]
    if named:
        return named
    incidents = [d for d in (w.dilemmas or {}).get("active", []) if d.get("kind") == "border_incident"]
    if incidents:
        newest = max(incidents, key=lambda d: d.get("month", -1))
        region = next((r for r in w.regions if r.id == newest.get("region")), None)
        if region is not None and region.front in ("north", "east"):
            return [region.front]
    return ["north", "east"]


def on_offer(w: World, mo: dict, found: list, party: str | None) -> None:
    """A passed motion's clauses, made public: what each one does to the ministries, the public and the fronts."""
    if not active(w) or not found or party is None:
        return
    action = mo.get("final_executable_action") or motion_actions.structured_action(w, mo)
    text = detection_text(mo, action)
    name = _name(w, party)
    for clause in found:
        if clause == "joint_inquiry":
            ministries.aggrieve(w, "army", ARMY_INVITED,
                                f"the government inviting {name} investigators into a matter on its own border")
            ministries.aggrieve(w, "interior", INTERIOR_SHARED, f"the government sharing its investigation with {name}")
            public_mood.react(w, "approval", "ident:karamanian", APPROVAL_INQUIRY, 3, "fine_print:joint_inquiry")
            w.dip.propaganda = min(1.0, w.dip.propaganda + PROPAGANDA_INQUIRY)
            w.event("fine_print", f"The council's motion offers {_the(w, party)} a joint inquiry; its investigators "
                    "would work alongside ours.", importance=2, clause=clause, party=party)
        elif clause == "stand_down":
            fronts = _fronts(w, text)
            ministries.aggrieve(w, "army", ARMY_STANDDOWN, "being ordered to pull back from its own border")
            public_mood.react(w, "approval", "ident:karamanian", APPROVAL_STANDDOWN, 2, "fine_print:stand_down")
            state(w)["standdowns"].extend(
                {"front": front, "from": w.month, "until": w.month + STANDDOWN_MONTHS, "party": party,
                 "reciprocated": None} for front in fronts)
            w.event("fine_print", "The council's motion offers a stand-down of Karamanian patrols on the "
                    f"{' and '.join(FRONT_NAMES[f] for f in fronts)} border.", importance=2, clause=clause,
                    party=party, fronts=fronts)
        elif clause == "foreign_inspection":
            ministries.aggrieve(w, "navy", NAVY_INSPECTED, f"{name} inspectors aboard Karamanian ships")
            public_mood.react(w, "approval", "ident:karamanian", APPROVAL_INSPECTION, 3,
                              "fine_print:foreign_inspection")
            w.event("fine_print", f"The council's motion offers {_the(w, party)} an inspection regime over "
                    "Karamanian shipping.", importance=2, clause=clause, party=party)


def open_inquiry(w: World, party: str) -> dict:
    """An inquiry with a hostile power's investigators, which reports INQUIRY_MONTHS from now."""
    entry = {"party": party, "from": w.month, "reports": w.month + INQUIRY_MONTHS}
    state(w)["inquiries"].append(entry)
    return entry


def _reciprocates(w: World, party: str | None) -> bool:
    """Whether the other side matches a stand-down: the Union and Veleria once the war has worn them down,
    Dorsania once it trusts Karamaniya."""
    if party in ("union", "veleria"):
        return w.dip.union_weariness > MATCH_WEARINESS
    if party == "dorsania":
        actor = (w.foreign or {}).get("actors", {}).get("dorsania", {})
        trust = actor.get("relations", {}).get("karamaniya", {}).get("trust", 0.0)
        return trust > MATCH_TRUST
    return False


def reply(w: World, proposal: dict) -> None:
    """Answer the fine print of a proposal the council sent, as the power it was addressed to would: a message to
    the council, and the inquiry, stand-down or inspection the power agrees to."""
    found = list(proposal.get("clauses") or [])
    if not found or not active(w):
        return
    from .director import _msg
    party = proposal.get("party")
    name = _name(w, party)
    rng = rng_for(w.seed, w.month, "fine-print")
    s = state(w)
    for clause in found:
        if clause == "joint_inquiry":
            if rng.random() < INQUIRY_ACCEPT:
                open_inquiry(w, party)
                _msg(w, name, f"{name} accepts a joint inquiry; its investigators will work alongside ours at "
                     "the border posts.")
            else:
                _msg(w, name, f"{name} dismisses the call for a joint inquiry.")
        elif clause == "stand_down":
            matched = _reciprocates(w, party)
            for entry in s["standdowns"]:
                if entry["from"] == proposal.get("month") and entry["party"] == party and entry["reciprocated"] is None:
                    entry["reciprocated"] = matched
            if matched:
                _msg(w, name, f"{name} matches the stand-down: its patrols will pull back from the incident sector.")
            else:
                _msg(w, name, f"{name} does not match the stand-down; its patrols stay where they are.")
                ministries.aggrieve(w, "army", ARMY_UNMATCHED, "a stand-down the other side did not match")
        elif clause == "foreign_inspection":
            s["inspections"].append({"party": party, "from": w.month})
            _msg(w, name, f"{name} accepts an inspection regime over Karamanian shipping.")


def monthly(w: World) -> None:
    """Once a month, before the proposals are answered: the findings of the inquiries that have reported, and the
    stand-downs that have run out. A world with no fine print is left alone."""
    if not active(w) or not w.institutions.get(KEY):
        return
    s = state(w)
    rng = rng_for(w.seed, w.month, "fine-print:finding")
    for inquiry in s["inquiries"]:
        if inquiry["reports"] > w.month:
            continue
        roll = rng.random()
        if roll < FINDING_CUTS[0]:
            w.dip.propaganda = clamp(w.dip.propaganda + PROPAGANDA_BLAME)
            public_mood.react(w, "approval", "ident:karamanian", APPROVAL_INQUIRY, 3, "fine_print:inquiry_finding")
            ministries.aggrieve(w, "army", ARMY_FINDING, "a joint inquiry's finding against its soldiers")
            said, verdict = "blamed Karamanian soldiers", "karamanian"
        elif roll < FINDING_CUTS[1]:
            w.dip.propaganda = clamp(w.dip.propaganda + PROPAGANDA_INCONCLUSIVE)
            said, verdict = "could not say who was responsible", "inconclusive"
        else:
            w.dip.propaganda = clamp(w.dip.propaganda - PROPAGANDA_OTHER)
            w.dip.rally = clamp(w.dip.rally + RALLY_OTHER)
            said, verdict = "blamed the other side", "other"
        w.event("inquiry_finding", f"The joint inquiry with {_the(w, inquiry['party'])} reported on the border "
                f"incident and {said}.", importance=2, party=inquiry["party"], finding=verdict)
    s["inquiries"] = [x for x in s["inquiries"] if x["reports"] > w.month]
    s["standdowns"] = [x for x in s["standdowns"] if x["until"] >= w.month]


def defence_factor(w: World, front: str) -> float:
    """What a stand-down takes from a front's defence: STANDDOWN_DEFENCE while one is active on it and the other
    side has not matched it, else 1."""
    if not active(w):
        return 1.0
    for entry in (w.institutions.get(KEY) or {}).get("standdowns", []):
        if (entry["front"] == front and entry["from"] <= w.month <= entry["until"]
                and not entry.get("reciprocated")):
            return STANDDOWN_DEFENCE
    return 1.0
