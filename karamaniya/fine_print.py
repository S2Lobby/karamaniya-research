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

from . import attribution, ministries, motion_actions, public_mood, resolve
from .world import World, clamp, rng_for

KEY = "fine_print"                              # w.institutions key for the offers this run has opened
ADVERSARIES = ("union", "veleria", "dorsania")  # the parties an offer can be made to; the League is not an adversary
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

# The words that say a joint commission looks into an incident (audit MO20): a standing commission on trade does not.
_INCIDENT = r"\b(?:shooting|incident|investigat\w*|inquir\w*|findings)\b"
# A stand-down that names no side: the zone or disengagement that names no forces, and the other wordings of a
# stand-down (audit MO24: "stand our forces down", "halt our patrols", "suspend patrols"). Their reading is kept; only a
# demand on the other side, or the other side as the one pulling back, takes it away (_stand_down_reads).
_STAND_DOWN_NO_SIDE = (
    r"\bstand[\s-]?downs?\b",
    r"\bstand\s+(?:[\w-]+\s+){0,2}?(?:troops|forces|patrols|units|soldiers)\s+down\b",
    r"\b(?:halt|suspend)(?:s|ed|ing)?\s+(?:our\s+|karamanian\s+|karamaniya['’]s\s+|(?:the\s+)?army['’]s\s+)?"
    r"(?:troops|forces|patrols|units|soldiers)\b",
    r"\bdemilitari[sz](?:ed|ation)\b",
    r"\bbuffer\s+zone\b",
    r"\bdisengage(?:ment)?\b",
)
# A pull-back or a withdrawal names the forces that move, so it is an offer only when its words make it ours or
# mutual (_stand_down_reads). Other wordings of it (audit MO24): "pull our patrols back", a few words between "pull"
# and "back", the forces before or after "back". "pull-back" and "pullback" are the same act written with a hyphen or
# as one word; the engine did not read them at all, so a mutual pull-back was not an offer (run 20261011-105713-seed1,
# Month 7).
_STAND_DOWN_PULL_BACK = (
    r"\bpull(?:s|ing|ed)?\s+(?:[\w'’-]+\s+){0,3}?back\b[^.;]{0,40}\b(?:troops|forces|patrols|units|soldiers)\b",
    r"\bpull(?:s|ing|ed)?\s+(?:[\w'’-]+\s+){0,3}?(?:troops|forces|patrols|units|soldiers)\s+"
    r"(?:[\w'’-]+\s+){0,2}?back\b",
    r"\bpull-?backs?\b",
    r"\bwithdraw(?:al|s|ing)?\s+(?:of\s+)?(?:(?:our|karamanian|karamaniya['’]s|(?:the\s+)?army['’]s)\s+)?"
    r"(?:troops|forces|patrols|units|soldiers)\b",
)
CLAUSES = {
    "joint_inquiry": (
        r"\bjoint\s+(?:[\w-]+\s+){0,2}(?:investigation|inquiry|enquiry|probe)",
        r"\bjoint\s+(?:[\w-]+\s+){0,2}commission\b[^.;:!?]*" + _INCIDENT,
        _INCIDENT + r"[^.;:!?]*\bjoint\s+(?:[\w-]+\s+){0,2}commission\b",
        # Inspectors aboard ships are an inspection regime, which foreign_inspection reads, not an inquiry.
        r"\b(?:international|foreign|union|velerian|dorsanian)\s+(?:investigators?|inspectors?|monitors?|observers?)\b"
        r"(?!\s+(?:aboard|on|at|of|in)\s+(?:our\s+|karamanian\s+)?(?:ships|shipping|vessels|ports?|cargo))",
        r"\bfact[\s-]?finding\s+(?:mission|commission|team|investigation|inquiry)\b",
    ),
    "stand_down": _STAND_DOWN_NO_SIDE + _STAND_DOWN_PULL_BACK,
    "foreign_inspection": (
        r"\binspection\s+regime\b",
        r"\b(?:union|velerian|dorsanian|foreign)\s+inspect(?:ion|ions|ors?)\s+(?:of|on|at|aboard)\s+"
        r"(?:our\s+|karamanian\s+)?(?:ships|shipping|vessels|ports?|cargo(?:es)?)\b",
        r"\b(?:accept|allow|permit)\w*\s+(?:the\s+)?(?:union|velerian|dorsanian|foreign)\w*\s+"
        r"(?:right\s+to\s+)?inspect",
    ),
}
# A clause runs from a full stop, semicolon, colon, question or exclamation mark, or from "but" or "while" (MO1).
# Audit MO1-f follow-up: a comma or "and" before a new subject starts a clause too, so a refusal in the clause before
# ("Since the Union rejected our offer, we propose ...") does not rule out the offer that follows it.
_CLAUSE_BREAK = re.compile(r"[.;:!?]|\b(?:but|while)\b|(?:,|\band\b)\s*(?=(?:we|the\s+council|this\s+council|"
                           r"the\s+government|our\s+government|karamaniya)\b)", re.I)
# A list item runs between punctuation, "and" or "or". "Mutual" in the same item governs a pull-back ("a mutual troop
# pull-back"); "mutual" in another item does not ("a mutual non-aggression undertaking", after a demand for a
# pull-back).
_ITEM_BREAK = re.compile(r"[,;:.!?]|\b(?:and|or|but|while)\b", re.I)
_MUTUAL = re.compile(r"\b(?:mutual(?:ly)?|reciprocal(?:ly)?|both\s+sides|each\s+side)\b", re.I)
# A demand on the other side governs the clause it stands in, as a refusal does (_asserted), up to a new predicate
# (_PREDICATE_BREAK). "Must", "should" and "in return" do so when the other side is the one pulling back: "in return ...
# withdraws" is a demand on it.
_DEMAND = re.compile(r"\b(?:demand|require|insist|urge|expect|ask|invite)(?:s|ed|ing)?\b|"
                     r"\bcall(?:s|ed|ing)?\s+on\b", re.I)
_OBLIGATION = re.compile(r"\b(?:must|should|shall)\b|\bin\s+return\b", re.I)
# A coordinator that brings in a new predicate ends a demand's reach: "we demand that the Union pull back its patrols
# and propose a stand-down of our patrols" demands the pull-back and offers the stand-down (engine 22). A noun phrase
# after "and" ("and a stand-down") is still the demand's object, and "stand" is a predicate only when it is not the noun
# "stand-down".
_PREDICATE_BREAK = re.compile(r"\b(?:and|or)\s+(?=(?:(?:will|would|shall|should|must|can|may|propose|offer|suggest|"
                              r"keep|accept|agree|table|open|seek|send|join|end|lift|renounce|reaffirm|pull|withdraw|"
                              r"halt|suspend|ask|demand|require|insist|urge|expect|invite|call)s?\b)"
                              r"|stand(?![\s-]*downs?\b))", re.I)
# The party a clause names as the one that pulls back. A possessive ("the Union's invitation") and a party after a
# preposition or a request ("with the Union", "ask the Union") is not the subject. "Karamaniya's shipping" is not us.
_OUR_NAMES = r"(?:we|karamaniya|(?:the\s+|our\s+|this\s+)?(?:provisional\s+)?(?:government|council))"
_THEIR_NAMES = r"(?:(?:the\s+)?(?:solvaran\s+)?union|veleria|velerian|dorsania|dorsanian)"
_SUBJECT = re.compile(rf"\b(?:(?P<ours>{_OUR_NAMES})|(?P<theirs>{_THEIR_NAMES}|they))\b(?!\s*['’]s)", re.I)
_OBJECT_CUES = frozenset(
    "of to from with by for against on in at between under over about than into onto upon toward towards "
    "ask asks asked invite invites invited call calls called urge urges urged require requires demand demands "
    "expect expects tell tells told warn warns warned that".split())
# The forces a stand-down or pull-back names. Ours: "our", "Karamanian", "Karamaniya's" or "the army's" before them.
# The other side's: "massed", the Union's, Veleria's or Dorsania's (or Dorsanian) before them, or "its" and "their" when
# the subject is not ours.
_FORCES = r"(?:troops|forces|patrols|units|soldiers)"
_THEIR_BARE = r"(?:(?:solvaran\s+)?union|veleria|velerian|dorsania|dorsanian)"
_OUR_FORCES = re.compile(rf"\b(?:our|karamanian|karamaniya['’]s|(?:the\s+)?army['’]s)\s+"
                         rf"(?:[\w-]+\s+){{0,2}}?{_FORCES}\b", re.I)
_MASSED = re.compile(r"\bmassed\b|\bmassing\b", re.I)
_THEIR_NAMED_FORCES = re.compile(rf"\b{_THEIR_BARE}(?:['’]s)?\s+(?:[\w-]+\s+){{0,2}}?{_FORCES}\b", re.I)
_ITS_FORCES = re.compile(rf"\b(?:its|their|them)\s+(?:[\w-]+\s+){{0,2}}?{_FORCES}\b", re.I)
_ITS_TAIL = re.compile(rf"\b(?:its|their)\s+(?:[\w-]+\s+){{0,2}}?{_FORCES}\s+$", re.I)
_THEIR_POSSESSIVE_TAIL = re.compile(rf"\b{_THEIR_BARE}['’]s\s+(?:[\w-]+\s+){{0,2}}$", re.I)


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
def _who_pulls_back(clause: str) -> str | None:
    """"ours" or "theirs" for the party the clause names as its subject, or None when it names neither (engine 22)."""
    who = None
    for match in _SUBJECT.finditer(clause):
        cues = clause[:match.start()].lower().split()[-2:]
        if any(word.strip(",.;:") in _OBJECT_CUES for word in cues):
            continue
        who = "ours" if match.group("ours") else "theirs"
    return who


def _stand_down_reads(text: str, match: re.Match, needs_side: bool) -> bool:
    """Whether a stand-down the text names is Karamaniya's offer (engine 22). Run 20261011-105713-seed1 read two demands
    on the Union as ours: Month 4 demanded "an immediate pull-back to garrison levels" and carried the term "Pull back
    massed forces to garrison levels"; Month 5 asked the Union to "withdraw troops massed on our borders". The words of
    the match's clause and its list item decide it, in this order:
    - "mutual", "reciprocal", "both sides" or "each side" in the item: an offer, whoever is named;
    - a demand on the other side in the clause, before any predicate a coordinator brings in, or "must" and "in return"
      when the other side is the one pulling back;
    - the other side named as the one pulling back, or its forces named ("massed", "the Union's troops", "its patrols");
    - our forces named ("our", "Karamanian", "Karamaniya's" or "the army's" troops, forces, patrols, units or
      soldiers), or we, Karamaniya, the council or the government pulling back.
    Otherwise a stand-down that names no side keeps its reading (needs_side is False), and a pull-back that names no
    side, a bare imperative, is not ours (needs_side is True)."""
    start, end = match.start(), match.end()
    clause = _CLAUSE_BREAK.split(text[:start])[-1]
    rest = match.group(0) + _ITEM_BREAK.split(text[end:])[0]
    if _MUTUAL.search(_ITEM_BREAK.split(text[:start])[-1] + rest):
        return True
    who = _who_pulls_back(clause)
    demanded = _PREDICATE_BREAK.split(clause)[-1]
    if _DEMAND.search(demanded) or (_OBLIGATION.search(demanded) and who != "ours"):
        return False
    if who == "theirs" or _THEIR_POSSESSIVE_TAIL.search(clause):
        return False
    if _OUR_FORCES.search(rest):
        return True
    if _MASSED.search(rest) or _THEIR_NAMED_FORCES.search(rest):
        return False
    if who is None and (_ITS_FORCES.search(rest) or _ITS_TAIL.search(clause)):
        return False
    if who == "ours":
        return True
    return not needs_side


def _asserted(text: str, pattern: str, stand_down: bool = False) -> bool:
    """Whether a pattern matches the text where the text asserts it. A match is ruled out when a negator stands
    anywhere from the start of its clause to the match, or inside the match: "we reject the Union's call for a
    joint inquiry" offers none (audit MO1, which a window of four words missed). A stand-down is ruled out too when
    it is not Karamaniya's offer (_stand_down_reads)."""
    for match in re.finditer(pattern, text, re.I):
        clause = _CLAUSE_BREAK.split(text[:match.start()])[-1]
        if motion_actions.negates(clause + " " + match.group(0)):
            continue
        if not stand_down or _stand_down_reads(text, match, needs_side=pattern in _STAND_DOWN_PULL_BACK):
            return True
    return False


def clauses(w: World, text: str, party: str | None) -> list:
    """The clause kinds a text offers the party it is addressed to, sorted. A text addressed to the League
    offers none: the League is not an adversary."""
    if not active(w) or party not in ADVERSARIES:
        return []
    body = str(text or "")
    return sorted(kind for kind, patterns in CLAUSES.items()
                  if any(_asserted(body, p, stand_down=kind == "stand_down") for p in patterns))


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
        # Engine 18: the neighbours see the offer too (resolve.py).
        resolve.note(w, clause, f"{READABLE[clause]} offered to {_the(w, party)} in Month {w.month + 1}")
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
            # Audit MI2+MO17: a stand-down holds the month it is made and STANDDOWN_MONTHS - 1 more, so `until` is the
            # last of its STANDDOWN_MONTHS months (defence_factor and the monthly prune both test it inclusively).
            state(w)["standdowns"].extend(
                {"front": front, "from": w.month, "until": w.month + STANDDOWN_MONTHS - 1, "party": party,
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
    # Engine 18: a finding draws on the border incident it is about, once one is on record (attribution.py). Without
    # one, the finding is drawn as it was before the incidents had a truth.
    cuts = attribution.finding_cuts(w) or FINDING_CUTS
    for inquiry in s["inquiries"]:
        if inquiry["reports"] > w.month:
            continue
        roll = rng.random()
        if roll < cuts[0]:
            w.dip.propaganda = clamp(w.dip.propaganda + PROPAGANDA_BLAME)
            public_mood.react(w, "approval", "ident:karamanian", APPROVAL_INQUIRY, 3, "fine_print:inquiry_finding")
            ministries.aggrieve(w, "army", ARMY_FINDING, "a joint inquiry's finding against its soldiers")
            said, verdict = "blamed Karamanian soldiers", "karamanian"
        elif roll < cuts[1]:
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


INSPECTION_MONTHS = 3    # Audit MI6: months an accepted inspection regime holds, counting the month it is accepted


def inspected(w: World) -> bool:
    """Whether an accepted inspection regime over Karamanian shipping is in force this month (Audit MI6). Its inspectors
    count the army, so the cabinets' estimate of it is exact while it runs (foreign._signal_intelligence). It reads the
    record and creates none."""
    records = ((w.institutions or {}).get(KEY) or {}).get("inspections", [])
    return any(r.get("from") is not None and int(r["from"]) <= w.month < int(r["from"]) + INSPECTION_MONTHS
               for r in records)
