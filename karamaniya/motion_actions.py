"""Motion prose against structured action, and one canonical status per motion (spec 111).

Two failures this module exists to prevent.

The first is a motion whose words and whose executable payload describe different acts. A delegate
wrote a formal protest to the Solvaran Union about merchant-vessel inspections; the structured
fields said `diplomacy / trade_deal`, which routes to the Maritime League, so the engine sent the
League a trade agreement and the Union never heard the protest. Political text, structured motion,
final vote and world-state execution have to describe the same action.

The second is status. A motion withdrawn by its proposer is not a defeat, and no reader - the floor,
the chronicle, Inspect, Compare, the vote table, the analytics or an export - should be able to
reach a different conclusion from any other. So the terminal state is worked out once, here, and
stored on the motion as `status`; everything downstream reads that field rather than re-deriving it
from "not passed".

The consistency checks keep an invalid or misaddressed diplomatic action off the agenda, so the
council does not vote on one action and later discover that a different action was executable.
"""
from __future__ import annotations

import hashlib
import json
import re

from .slate import OFFICE_WORDS as _OFFICE_WORDS

# ---- the action vocabulary -------------------------------------------------------------------------
# Canonical actor ids. These are the vocabulary a structured target is written in, because "Union"
# is not an actor: it is a word that could mean the Solvaran Union, the Maritime League's members,
# or a customs arrangement, and a target that ambiguous cannot be checked against anything. Display
# names stay for prose and for the prompt; the engine keys on these.
SOLVARAN_UNION = "SOLVARAN_UNION"
MARITIME_LEAGUE = "MARITIME_LEAGUE"
DORSANIA = "DORSANIA"
VELERIA = "VELERIA"

ACTORS = (SOLVARAN_UNION, MARITIME_LEAGUE, DORSANIA, VELERIA)
ACTOR_NAMES = {SOLVARAN_UNION: "Solvaran Union", MARITIME_LEAGUE: "Maritime League",
               DORSANIA: "Dorsania", VELERIA: "Veleria"}
# The engine's older lowercase keys, and the party names the state model uses. A saved run, a
# recorded motion and a display name all have to keep resolving to the same actor.
ACTOR_ALIASES = {"union": SOLVARAN_UNION, "league": MARITIME_LEAGUE, "dorsania": DORSANIA,
                 "veleria": VELERIA, "solvaran union": SOLVARAN_UNION,
                 "solvaran_union": SOLVARAN_UNION, "maritime league": MARITIME_LEAGUE,
                 "maritime_league": MARITIME_LEAGUE}

#: What a motion actually does. Deliberately explicit: an overloaded "proposal" type is what let a
#: protest be filed as a trade deal.
DIPLOMATIC_ACTIONS = {
    "diplomatic_protest": SOLVARAN_UNION,
    "trade_talks": SOLVARAN_UNION, "status_talks": SOLVARAN_UNION, "non_aggression_pact": SOLVARAN_UNION,
    "federation": SOLVARAN_UNION, "join_union": SOLVARAN_UNION, "ceasefire": SOLVARAN_UNION,
    "alliance": MARITIME_LEAGUE, "loan_request": MARITIME_LEAGUE,
    "military_aid": MARITIME_LEAGUE, "trade_deal": MARITIME_LEAGUE,
    "grain_deal": DORSANIA,
    # Withdrawing from a commitment is addressed to whichever power holds it, like a protest.
    "renounce": SOLVARAN_UNION,
    # Engine 17: handing over a region a neighbour demanded. Only that neighbour may receive it (below).
    "cede_region": VELERIA,
    # Engine 22: an answer to the ultimatum that stands. Its default receiver is the Union; the power that issued the
    # ultimatum is checked in validate_diplomatic_action (only the issuer, or the Union for a member's demand).
    "ultimatum_reply": SOLVARAN_UNION,
}
#: Which actors each diplomatic act may be addressed to. Most acts are structurally tied to one
#: partner -- you cannot seek Union membership from the League, or a grain purchase from a country
#: with no grain -- and those stay bound. A protest is different: it is addressed to whoever is doing
#: the thing you object to, so it is open to every actor. Welding protest to the Union alone capped
#: what the council could say to the powers actually squeezing it, which is a limit on the delegates
#: rather than a property of the world. DIPLOMATIC_ACTIONS still supplies the default target when a
#: delegate names an act but no country.
DIPLOMATIC_TARGETS = {action: {target} for action, target in DIPLOMATIC_ACTIONS.items()}
DIPLOMATIC_TARGETS["diplomatic_protest"] = {SOLVARAN_UNION, MARITIME_LEAGUE, DORSANIA, VELERIA}
DIPLOMATIC_TARGETS["renounce"] = {SOLVARAN_UNION, MARITIME_LEAGUE, DORSANIA, VELERIA}
# A region goes to a neighbour that demanded it, and only to one of the two (territory.cession_problem).
DIPLOMATIC_TARGETS["cede_region"] = {VELERIA, DORSANIA}
# Veleria is a Union member, but the Union receives the answer on its behalf. Preserve the
# specifically addressed target so a border non-aggression proposal is not silently relabelled as
# a pact with the whole Union. Dorsania is a Union member too: since the Union formed it is answered
# the same way (run 20261011-105713-seed1, Month 8: A's offer of a pact to Dorsania was refused as ACTION_NOT_VALID_FOR_TARGET).
DIPLOMATIC_TARGETS["non_aggression_pact"] = {SOLVARAN_UNION, VELERIA, DORSANIA}
# Engine 27 (wave 3, D): the six pairs the census in docs/DIPLOMACY_TARGETS_PROPOSAL.md section 4 found refused, and
# the only ones widened. Each got a handler before its table entry, so an accepted act cannot vanish: status talks to
# Veleria and Dorsania (their own branches, not the Union's), trade talks to Veleria, the League and Dorsania, and a
# trade deal to Dorsania (answered with the grain agreement, its only trade lever). Every other pair in the proposal
# stays refused: a ceasefire to Veleria would end the Union's war, and join_union to Veleria would end the run.
DIPLOMATIC_TARGETS["trade_talks"] = {SOLVARAN_UNION, MARITIME_LEAGUE, DORSANIA, VELERIA}
DIPLOMATIC_TARGETS["status_talks"] = {SOLVARAN_UNION, DORSANIA, VELERIA}
DIPLOMATIC_TARGETS["trade_deal"] = {MARITIME_LEAGUE, DORSANIA}
# Engine 22: an ultimatum is answered by the power that issued it, and the Union answers for its members'
# demands. Which of the four may receive a reply depends on the ultimatum that stands, so it is checked in
# validate_diplomatic_action rather than here.
DIPLOMATIC_TARGETS["ultimatum_reply"] = {SOLVARAN_UNION, MARITIME_LEAGUE, DORSANIA, VELERIA}
#: The engine's own subject vocabulary, which the diplomatic action names map onto.
ACTION_TO_SUBJECT = {"diplomatic_protest": "diplomatic_protest", "non_aggression_pact": "non_aggression",
                     "loan_request": "loan"}
SUBJECT_TO_ACTION = {v: k for k, v in ACTION_TO_SUBJECT.items()}
#: Names that denote a diplomatic *act*, as opposed to an actor, an office or a topic. The
#: consistency check uses this to tell a motion whose subject claims a different act -- a real
#: contradiction worth stopping -- from one whose subject merely labels what the motion is about.
ACT_NAMES = (set(DIPLOMATIC_ACTIONS) | set(ACTION_TO_SUBJECT) | set(ACTION_TO_SUBJECT.values())
             | set(SUBJECT_TO_ACTION))

#: One negation vocabulary (engine 19, audit MO1 and MO15), read here and by fine_print.py. A negator rules out an
#: act that comes before it in its clause ("no federation", "we refuse any federation"). "nothing" is one, and so
#: are the contractions ("won't", "cannot"). Phrases that affirm despite a negator are in _AFFIRMING_IDIOM.
NEGATOR = (r"\b(?:no|not|nor|neither|never|nothing|without|excluding|cannot|can['’]?t|won['’]?t|don['’]?t|"
           r"doesn['’]?t|didn['’]?t|isn['’]?t|aren['’]?t|wouldn['’]?t|shouldn['’]?t|shan['’]?t|"
           r"rules?\s+out|bar(?:s|ring)?|reject(?:s|ed|ing)?|refus(?:e|es|ed|ing)|declin(?:e|es|ed|ing)|"
           r"oppos(?:e|es|ed|ing))\b")
_AFFIRMING_IDIOM = re.compile(r"\b(?:not\s+only|no\s+(?:less|more)\s+than|nothing\s+(?:less|short)\s+(?:than|of))\b",
                              re.I)
_NEGATOR = re.compile(NEGATOR, re.I)


def negates(text: str) -> bool:
    """Whether a text contains a negator, outside the phrases that affirm despite one."""
    return bool(_NEGATOR.search(_AFFIRMING_IDIOM.sub(" ", str(text or ""))))


#: Prose that names a foreign act, strongest signal first. Each entry is (action_type, patterns).
_LAND = r"(?:kessel|dorran|aster|lissen|highlands|region|territor\w*|province)"  # what a cession names (engine 17)
PROSE_ACTIONS = (
    # Handing a region over (engine 17): cede, cession, hand over, give up, with the land named after the verb. A
    # negator between the verb and the land rules the cession out: "give up nothing in Kessel Valley" (MO15).
    ("cede_region", tuple(rf"{verb}(?:(?!{NEGATOR})[^.;:]){{0,40}}?\b{_LAND}\b" for verb in (
        r"\bcede[sd]?\b", r"\bcession\b", r"\bhand(?:s|ing)?\s+over\b", r"\bgive(?:s|n)?\s+up\b(?!\s+on\b)"))),
    ("diplomatic_protest", (r"\bprotest", r"\bcondemn", r"\bdenounce", r"\bdemand(?:s|ing)?\s+"
                            r"(?:the\s+)?(?:cessation|an?\s+end|that\s+\w+\s+(?:cease|stop|halt))",
                            r"\bcease\s+and\s+desist")),
    ("non_aggression_pact", (r"non[\s-]?aggression", r"\brenounce\s+force", r"\bnon[\s-]?aggression\s+pact")),
    ("ceasefire", (r"\bceasefire", r"\barmistice")),
    ("status_talks", (r"\bstatus\s+(?:talks|negotiations?)", r"\b(?:talks|negotiations?)\b[^.;:]{0,60}?\bstatus\b")),
    ("federation", (r"\bfederation", r"\bfederal\s+arrangement")),
    ("join_union", (r"\brejoin", r"\breunification", r"\bjoin\s+the\s+union")),
    ("alliance", (r"\balliance", r"\bdefensive\s+pact")),
    ("military_aid", (r"\bmilitary\s+(?:aid|equipment|supplies)", r"\barms\s+shipment")),
    ("loan_request", (r"\bloan", r"\bcredit\s+facility", r"\bline\s+of\s+credit")),
    ("grain_deal", (r"\bgrain\s+(?:deal|backstop|agreement|imports|purchase)", r"\bgrain\s+through")),
    ("trade_deal", (r"\btrade\s+(?:deal|arrangement|agreement|pact)", r"\btariff", r"\btrade\s+terms")),
    ("trade_talks", (r"\btrade\s+talks",)),
)

#: An act the prose names only to rule it out. Engine 15 read "this motion authorises no accession, no
#: federation" as naming a federation, so a motion for status talks filed as a federation passed the
#: check, and the engine sent the Union a federation proposal it could have accepted. The acts are the ones
#: PROSE_ACTIONS names (audit MO15: it lacked military aid, grain deals and tariffs), and accession.
_NAMED_ACTS = "|".join(f"(?:{pattern})" for _action, patterns in PROSE_ACTIONS for pattern in patterns)
NEGATED_ACT = re.compile(rf"{NEGATOR}\s+(?:an?\s+|any\s+|the\s+)?(?:[\w-]+\s+){{0,2}}?"
                         rf"(?:accession|{_NAMED_ACTS})\b", re.I)

#: Words that name an actor. The island's own names come first so "Karamaniya" is never read as a
#: foreign target.
def _actor_patterns(w) -> dict:
    names = getattr(w, "names", {}) or {}
    return {
        SOLVARAN_UNION: [names.get("union", "Solvaran Union"), r"\bthe\s+Union\b", r"\bUnion\b"],
        MARITIME_LEAGUE: [names.get("league", "Maritime League"), r"\bthe\s+League\b",
                          r"\bMaritime\s+League\b"],
        DORSANIA: [names.get("dorsania", "Dorsania")],
        VELERIA: [names.get("veleria", "Veleria")],
    }


def _hits(text: str, patterns) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


# ---- the structured side ---------------------------------------------------------------------------
def structured_action(w, motion: dict) -> dict:
    """The executable act a motion encodes, in explicit terms.

    Built from the fields the engine routes on, plus any explicit `action` object the delegate
    supplied. This is the payload that would be executed.
    """
    kind = str(motion.get("type", ""))
    subject = str(motion.get("subject", ""))
    explicit = motion.get("action") if isinstance(motion.get("action"), dict) else {}
    action_type = str(explicit.get("action_type") or SUBJECT_TO_ACTION.get(subject) or subject).strip()
    raw_target = str(explicit.get("target") or "").strip()
    # Preserve an explicit but unrecognized target so validation can reject it. Falling back to
    # the action's default here would silently route a motion to a different country.
    target = (_canonical_actor(w, raw_target) or raw_target) if raw_target else None
    if kind == "diplomacy":
        target = target or DIPLOMATIC_ACTIONS.get(action_type) or DIPLOMATIC_ACTIONS.get(subject)
        return {"action_type": action_type, "target": target, "policy": None,
                "value": motion.get("value"), "issue": str(explicit.get("issue") or "").strip(),
                "terms": explicit.get("terms") or explicit.get("demands") or [],
                "kind": kind, "subject": subject}
    if kind == "set_policy":
        return {"action_type": "directive", "target": None, "policy": subject,
                "value": motion.get("value"), "issue": "", "terms": [], "kind": kind, "subject": subject}
    if kind == "settle_arrears":
        return {"action_type": "settle_arrears", "target": None, "policy": subject,
                "value": motion.get("value"), "issue": "", "terms": [], "kind": kind, "subject": subject}
    if kind == "amend":
        return {"action_type": "charter_amendment", "target": None, "policy": None, "value": None,
                "issue": "", "terms": [], "kind": kind, "subject": subject,
                "text": str(motion.get("text", ""))}
    if kind in ("assign_office", "vacate_office"):
        return {"action_type": "appointment", "target": str(motion.get("value", "")).upper() or None,
                "policy": subject, "value": motion.get("value"), "issue": "", "terms": [],
                "kind": kind, "subject": subject}
    if kind == "program":
        raw_measures = motion.get("measures") or explicit.get("measures") or []
        measures = []
        from .politics import canonical_lever, parse_lever
        for measure in raw_measures:
            if isinstance(measure, dict):
                lever = canonical_lever(str(measure.get("lever", "")))
                raw_value = measure.get("value")
            elif isinstance(measure, (list, tuple)) and len(measure) == 2:
                lever = canonical_lever(str(measure[0]))
                raw_value = measure[1]
            else:
                continue
            parsed_value = parse_lever(lever, raw_value)
            measures.append({"lever": lever,
                             "value": raw_value if parsed_value is None else parsed_value})
        return {"action_type": "program", "target": None, "policy": None,
                "value": motion.get("value"), "issue": "", "terms": [], "kind": kind,
                "subject": subject, "measures": measures}
    if kind == "disaster_relief":
        fields = ("region", "regions", "amount", "funding", "funding_plan", "scope", "military_engineers")
        return {"action_type": "disaster_relief", "target": None, "policy": None,
                "value": motion.get("value"), "issue": "", "terms": [], "kind": kind, "subject": subject,
                **{field: explicit[field] for field in fields if field in explicit}}
    if kind == "media_campaign":
        # Wave 3: the campaign's kinds, claims and intensity are the executable payload.
        return {"action_type": "media_campaign", "target": None, "policy": None,
                "value": motion.get("value"), "issue": "", "terms": [], "kind": kind, "subject": subject,
                "kinds": list(explicit.get("kinds") or []),
                "claims": [dict(c) for c in explicit.get("claims") or [] if isinstance(c, dict)],
                "intensity": str(explicit.get("intensity") or "")}
    if kind == "policy":
        # Wave A (engine 30, W3): the canonical items are the executable payload; the items' own
        # conditions are evaluated monthly by policy.monthly, not as a motion-level gate.
        from . import actions
        return {"action_type": "policy", "target": None, "policy": None,
                "value": motion.get("value"), "issue": "", "terms": [], "kind": kind,
                "subject": subject, "items": actions.policy_items_of(w, motion)}
    return {"action_type": action_type or kind, "target": target, "policy": subject,
            "value": motion.get("value"), "issue": "", "terms": [], "kind": kind, "subject": subject}


# ---- execution conditions ---------------------------------------------------------------------------
#: Metrics a binding execution condition may test. Deliberately the same vocabulary as
#: conditional votes, plus the arrears-payment safeguards the live run taught us.
CONDITION_METRICS = ("food_ratio", "reserves", "reserves_after_payment", "arrears", "unemployment",
                     "army_morale", "army_arrears", "inflation", "approval", "deficit",
                     "league_credit_received", "audited_register")
BOUNDED_PROPORTION_METRICS = {"unemployment", "army_morale", "approval"}
UNBOUNDED_RATIO_METRICS = {"food_ratio", "inflation", "deficit"}
#: Ratios where a figure above 1 means percentage points: "inflation at most 2" is 2%, as "approval at
#: most 2" already was. Audit MO9 + CO7: inflation and deficit were converted only at 10 or more, so the
#: same threshold read 100 times too high (2 meant 200%, and a safeguard "at most 6" passed at 60%).
PERCENT_POINT_METRICS = BOUNDED_PROPORTION_METRICS | {"inflation", "deficit"}
MONEY_METRICS = {"reserves", "reserves_after_payment", "arrears", "army_arrears"}


def pays_from_reserves(motion: dict) -> bool:
    """Whether executing this motion pays gold out of the reserves, the only payment a reserve floor can limit.

    An arrears settlement pays from reserves when its subject is reserves; relief does when its funding plan draws on
    them. A loan, a grain or trade deal, a directive or a programme pays nothing out, and a settlement funded from bonds
    pays out of bonds. A reserve floor on any of those tests today's balance, and a loan whose floor needs the loan to
    lift that balance blocks itself (run 20261011-105713-seed1, Month 8, M5).
    """
    kind = str(motion.get("type", "")).strip()
    if kind == "settle_arrears":
        return str(motion.get("subject", "")).strip().lower() == "reserves"
    if kind == "disaster_relief":
        # The funding relief executes with: the plan's allocations when it has them, else its one named source.
        plan = motion.get("action") if isinstance(motion.get("action"), dict) else {}
        allocations = plan.get("funding_plan") if isinstance(plan.get("funding_plan"), list) else []
        if allocations:
            sources = [str(item.get("source", "")).strip().lower() for item in allocations if isinstance(item, dict)]
        else:
            sources = [str(plan.get("funding", "")).strip().lower()]
        return "reserves" in sources
    return False


def _is_non_payment_reserve_floor(cond, motion: dict) -> bool:
    """A "reserves after payment" condition on a motion that has a type and pays nothing out of reserves."""
    return (isinstance(cond, dict) and cond.get("metric") == "reserves_after_payment"
            and bool(str(motion.get("type", "")).strip()) and not pays_from_reserves(motion))


#: A reserve level can be the aim of money rather than a level a payment must keep: "reserves rebuilt above 60M",
#: "restore reserves to at least 60M", "order of use: ... reserves above 60M", "target", "aim". Run
#: 20261011-105713-seed1, Month 8: the purpose of a 50M loan was read as a floor on that loan. A goal is not a condition.
_GOAL_VERB = re.compile(r"^(?:rebuil[dt]\w*|restor\w*|rais\w*|bring\w*|brought|build\w*|built|replenish\w*|recover\w*|"
                        r"lift\w*|increas\w*|grow\w*|grew|grown|boost\w*)$", re.I)
_GOAL_PHRASE = re.compile(r"\b(?:order\s+of\s+use|targets?|aim(?:s|ed|ing)?|goals?)\b", re.I)


#: A sequencing word before a reserve level makes it a precondition: "pay only after reserves are rebuilt above 60M".
_GATE_WORDS = {"after", "once", "when", "if", "unless", "until", "while", "provided", "subject", "long", "condition"}
_FLOOR_WORDS = {"floor", "minimum", "buffer", "threshold"}


def _states_a_goal(sentence: str, start: int, end: int) -> bool:
    """Whether the reserve level at sentence[start:end] names what the money is for, not a level to keep.

    A goal verb in the two words before the reserve word, or inside the phrase, makes it a goal: "rebuild reserves above
    60M", "reserves rebuilt above 60M", "restore reserves to 60M". So does an "order of use", "target" or "aim" earlier
    in the same sentence. A sequencing word before it ("only after reserves are rebuilt above 60M") makes it a
    precondition instead, and "raise the reserve floor to 30M" sets the floor itself, not an aim. "Keep reserves above
    60M" and "reserves remain at or above 30 million" are levels.
    """
    span = sentence[start:end].split()
    # "raise the reserve floor to 30M" sets the floor itself, which is a condition, not an aim for the reserves.
    if len(span) > 1 and span[1].strip(",:;.()").lower() in _FLOOR_WORDS:
        return False
    words = [word.strip(",:;.()").lower() for word in sentence[:start].split()[-2:] + span]
    for word in words:
        if word in _GATE_WORDS:
            return False    # a sequencing word comes first: the level is a precondition, whatever verb follows
        if _GOAL_VERB.match(word):
            return True     # a goal verb comes first, with no sequencing word before it
    return bool(_GOAL_PHRASE.search(sentence[:end]))


def _sentence_before(text: str, pos: int) -> str:
    """The text of the sentence that ends before `pos`: from its last full stop, semicolon or line break."""
    head = text[:pos]
    cut = max(head.rfind(";"), head.rfind("\n"), head.rfind(". "))
    return head[cut + 1:] if cut >= 0 else head


def canonical_metric_value(metric: str, value: float) -> float:
    """Read percent-point thresholds in the same fractional units used by world state."""
    value = float(value)
    if metric in PERCENT_POINT_METRICS and abs(value) > 1:
        value /= 100.0
    elif metric in UNBOUNDED_RATIO_METRICS and abs(value) >= 10:
        # Food coverage is the one ratio that legitimately exceeds 1 (a surplus over 100% of need, and the
        # economy starts at 1.0), so a threshold of 1.05 stays 105%. Only 10 or more is read as percent.
        value /= 100.0
    elif metric in MONEY_METRICS and 0 < abs(value) < 100_000:
        # Briefings commonly express large fiscal values as "90" for 90 million crowns,
        # while world state stores full currency units. Bring bare small money thresholds to
        # the same scale so 90 cannot vacuously pass against an 88,000,000 reserve balance.
        value *= 1_000_000.0
    return value

CONDITION_WORDS = (
    (("reserves", "reserve", "gold", "treasury balance"), "reserves"),
    (("arrears", "unpaid bills", "unpaid bill"), "arrears"),
    (("food", "grain", "harvest", "hunger"), "food_ratio"),
    (("unemployment", "jobless"), "unemployment"),
    (("morale",), "army_morale"),
    (("inflation", "prices"), "inflation"),
    (("approval", "popularity"), "approval"),
    (("deficit",), "deficit"),
    (("league credit", "league loan", "credit clears", "credit arrives", "loan tranche",
      "league tranche"), "league_credit_received"),
    (("audit", "audited", "register verified", "verified register"), "audited_register"),
)

_CONDITION_CLAUSE = re.compile(
    r"(?:only\s+if|provided\s+that|on\s+condition\s+that|subject\s+to|as\s+long\s+as|"
    r"after|once|when|if|unless|until|while|preserv\w*|remain\w*|keep\w*|above|below|"
    r"at\s+least|no\s+less\s+than|no\s+more\s+than|not\s+below|not\s+fall|reserv\w*|floor|cap|"
    # Audit MO10: a full stop inside a figure ("1.5bn", "79.5M") does not end the clause; before this the
    # clause stopped at "1", so a floor of 1.5bn was read as one million crowns.
    r"credit|audit|register|league)(?:[^.;]|\.(?=\d))*", re.IGNORECASE)


_FLOOR_HIT = re.compile(r"(reserv\w*|gold|treasury)[^.;]{0,60}?(>=|at\s+least|no\s+less\s+than|"
                        r"not\s+below|remain\w*|stay\w*|preserv\w*|keep\w*|floor|above|minimum)"
                        r"[^0-9.;]{0,20}(\d[\d,]*(?:\.\d+)?)\s*(m\b|million|bn\b|billion|k\b|%)?")


def parse_conditions(text: str, motion_type: str = "", subject: str = "", action: dict | None = None) -> list:
    """Binding execution safeguards read from final motion prose.

    Never invents conditions: plain payment or policy wording yields []. A floor
    ("reserves remain >= 55M"), a sequencing gate ("only after League credit
    clears") or an audit gate ("audited register") yields a structured condition
    the engine must test before mutating state. Opinion yields nothing.

    Two readings are withheld. A goal is not a floor ("reserves rebuilt above 60M" says what the money is for), and a
    reserve floor binds only a motion that pays out of the reserves (see pays_from_reserves). With no motion type given,
    the text is read as text alone.
    """
    spans = []
    for match in _CONDITION_CLAUSE.finditer(text or ""):
        clause = match.group(0).strip()
        if clause:
            spans.append((_sentence_before(str(text), match.start()).lower(), clause.lower()))
    if not spans:
        return []
    joined = " ; ".join(clause for _lead, clause in spans)
    out: list = []
    seen = set()

    def add(metric: str, operator: str, value: float, source: str):
        key = (metric, operator, round(value, 6))
        if key in seen:
            return
        seen.add(key)
        out.append({"metric": metric, "operator": operator, "value": value, "source": source[:220]})

    # Run 20261011-105713-seed1, Month 8: a 50M loan request read "reserves rebuilt above 60M" as a floor on itself.
    # Clauses are read in turn, and the first reserve level that is not a goal is the floor.
    pays = not motion_type or pays_from_reserves({"type": motion_type, "subject": subject, "action": action})
    floor_hit = None
    for lead, clause in (spans if pays else []):
        floor_hit = next((m for m in _FLOOR_HIT.finditer(clause)
                          if not _states_a_goal(lead + clause, len(lead) + m.start(), len(lead) + m.end())), None)
        if floor_hit:
            break
    if floor_hit:
        # Audit MO10: the figure may carry comma groups ("12,500,000"); a bare "12" here was 12 million.
        try:
            amount = float(floor_hit.group(3).replace(",", ""))
        except ValueError:
            amount = 0.0
        unit = (floor_hit.group(4) or "").strip()
        if unit in ("m", "million"):
            amount *= 1e6
        elif unit in ("bn", "billion"):
            amount *= 1e9
        elif unit in ("k",):
            amount *= 1e3
        elif unit == "%" and amount > 1:
            amount /= 100
        elif not unit and amount < 1e5:
            amount *= 1e6  # bare "55" next to reserves means 55M crowns
        add("reserves_after_payment", ">=", amount, floor_hit.group(0).strip())
    if re.search(r"leagu\w*[^.;]{0,40}(credit|loan|tranche)[^.;]{0,40}"
                 r"(clear|arriv|receiv|first|before|prior|condition|release|approv)", joined) or \
       re.search(r"(after|once|when)[^.;]{0,40}leagu\w*[^.;]{0,40}(credit|loan|tranche)", joined) or \
       re.search(r"only\s+(?:if|after|once)[^.;]*leagu", joined):
        add("league_credit_received", "==", 1.0, "league credit gate")
    is_investigation = str(motion_type).strip().lower() in ("investigation", "audit")
    if not is_investigation and re.search(r"audit", joined) and re.search(r"register|verif|certif|reconcile", joined):
        add("audited_register", "==", 1.0, "audited register gate")
    return out


def motion_conditions(motion: dict) -> list:
    """The binding conditions for one motion: explicit beats derived, never invented.

    Wave A (engine 30, W3): a policy's conditions live on its items, one per item, and policy.monthly
    evaluates them at the start of each month. The motion itself carries none, so prose that reads like a
    condition is a description of the policy rather than a gate on the whole motion.
    """
    if str(motion.get("type", "")).strip() == "policy":
        return []
    explicit = motion.get("conditions") or motion.get("execution_conditions") or []
    if isinstance(explicit, list) and explicit:
        clean = []
        for c in explicit:
            if not isinstance(c, dict) or c.get("metric") not in CONDITION_METRICS:
                continue
            if c.get("operator") not in (">=", "<=", "=="):
                continue
            if _is_non_payment_reserve_floor(c, motion):
                continue  # refused, and reported by dropped_conditions
            try:
                value = float(c.get("value"))
            except (TypeError, ValueError):
                continue
            value = canonical_metric_value(c["metric"], value)
            clean.append({"metric": c["metric"], "operator": c["operator"], "value": value,
                          "source": str(c.get("source", "explicit"))[:220]})
        if clean:
            is_investigation = str(motion.get("type", "")).strip().lower() in ("investigation", "audit")
            if is_investigation:
                clean = [condition for condition in clean
                         if not (condition["metric"] == "audited_register"
                                 and condition["source"] == "audited register gate")]
        if clean:
            return clean
    return parse_conditions(str(motion.get("text", "")), str(motion.get("type", "")),
                            str(motion.get("subject", "")), motion.get("action"))


def dropped_conditions(motion: dict) -> list:
    """The structured reserve floors motion_conditions refuses, each with its reason, for the record.

    A delegate may write "reserves after payment at least 60M" on a loan. The loan pays nothing out, so that floor can
    only be met by the loan it blocks (run 20261011-105713-seed1, Month 8), and motion_conditions does not bind it. It
    is listed here so the refusal is a fact about the motion rather than a silence.
    """
    explicit = motion.get("conditions") or motion.get("execution_conditions") or []
    if not isinstance(explicit, list):
        return []
    action = motion.get("action") if isinstance(motion.get("action"), dict) else {}
    label = str(action.get("action_type") or motion.get("subject") or motion.get("type") or "motion")
    out = []
    for c in explicit:
        if not (isinstance(c, dict) and c.get("metric") in CONDITION_METRICS
                and c.get("operator") in (">=", "<=", "==") and _is_non_payment_reserve_floor(c, motion)):
            continue
        try:
            value = canonical_metric_value("reserves_after_payment", float(c.get("value")))
        except (TypeError, ValueError):
            continue
        out.append({"metric": "reserves_after_payment", "operator": c["operator"], "value": value,
                    "source": str(c.get("source", "explicit"))[:220],
                    "note": (f"not bound: a {label} pays nothing out of reserves, so reserves after payment cannot "
                             f"be a floor on it (reserves_after_payment {c['operator']} {value:,.0f})")})
    return out


def condition_values(w, motion: dict | None = None) -> dict:
    """Canonical state one execution condition may test, in the units conditions use."""
    from .society import inflation_yoy
    e = w.econ
    league = (w.foreign or {}).get("league", {}) if getattr(w, "foreign", None) else {}
    loan = league.get("loan", {}) if isinstance(league, dict) else {}
    credit = 0.0
    try:
        if float(loan.get("principal", 0) or 0) > 0 or float(w.dip.league_loan_pending or 0) > 0 \
                or float(getattr(e, "loans_in", 0) or 0) > 0:
            credit = 1.0
    except (TypeError, ValueError):
        credit = 0.0
    audited = 0.0
    flags = getattr(w, "counters", {}) or {}
    for key in ("arrears_audited", "register_audited", "audit_complete"):
        try:
            if float(flags.get(key, 0) or 0) > 0:
                audited = 1.0
        except (TypeError, ValueError):
            continue
    reserves_after = e.gold
    if isinstance(motion, dict) and motion.get("type") == "settle_arrears":
        from .politics import settle_arrears_cost
        reserves_after = max(0.0, e.gold - settle_arrears_cost(w, motion))
    elif isinstance(motion, dict) and motion.get("type") == "disaster_relief":
        from .politics import parse_money, relief_funding_capacity
        plan = motion.get("action") if isinstance(motion.get("action"), dict) else {}
        approved = parse_money(plan.get("amount", motion.get("value", ""))) or 0.0
        reserve_draw = 0.0
        allocated = 0.0
        funding_plan = plan.get("funding_plan") if isinstance(plan.get("funding_plan"), list) else []
        if funding_plan:
            allocations = [(str(item.get("source", "")).strip().lower(),
                            parse_money(item.get("amount")) or 0.0)
                           for item in funding_plan if isinstance(item, dict)]
        else:
            funding = str(plan.get("funding", "")).strip().lower()
            allocations = [(funding, approved)] if funding else []
        for source, requested in allocations:
            draw = min(requested, relief_funding_capacity(w, source), max(0.0, approved - allocated))
            allocated += draw
            if source == "reserves":
                reserve_draw += draw
        rate = w.zone_of("karamaniya").price / (e.fx_conf if e.currency == "karam" else 1.0)
        reserves_after = max(0.0, e.gold - reserve_draw / max(rate, .01))
    return {"food_ratio": e.food_ratio, "reserves": e.gold, "reserves_after_payment": reserves_after,
            "arrears": e.arrears, "unemployment": e.unemployment, "army_morale": w.mil.army.morale,
            "army_arrears": w.mil.army.arrears, "inflation": inflation_yoy(w),
            "approval": w.avg("approval") if w.k_pops() else 0.0,
            "deficit": e.deficit / max(e.gdp_nominal, 1),
            "league_credit_received": credit, "audited_register": audited}


def _reserve_floor_result(w, cond: dict, motion: dict, values: dict) -> dict:
    """A floor on reserves after a payment, tested the way it will be enforced: by sizing the payment.

    "Reserves stay at or above 50M" on a payment from reserves means pay what leaves them there. So the
    floor is met whenever some payment can be made above it, and the payment is limited to
    min(requested, reserves - floor); it fails only when there is no room at all (reserves already at
    or under the floor), and then nothing is paid. Reserves are gold and payments are crowns, so room
    and cost are both in gold here, the unit reserves are held in.
    """
    from .politics import settle_arrears_cost
    try:
        floor = float(cond.get("value"))
        reserves = float(values.get("reserves", 0))
        full = float(settle_arrears_cost(w, motion, floor=0.0))
    except (TypeError, ValueError):
        return {**cond, "met": False, "observed": None, "reason": "no canonical reading for reserves_after_payment"}
    allowed = min(full, max(0.0, reserves - floor))
    after = reserves - allowed
    no_room = full > 0 and allowed <= 0
    met = after >= floor and not no_room
    row = {**cond, "met": bool(met), "observed": after, "requested_cost": full, "allowed_cost": allowed,
           "capped": bool(met and full > 0 and allowed + 1e-6 < full)}
    if not met:
        row["reason"] = (f"reserves {reserves:,.0f} are already below the reserve floor of {floor:,.0f}"
                         if reserves < floor else
                         f"reserves {reserves:,.0f} leave no room for a payment above the reserve floor of {floor:,.0f}")
    return row


def evaluate_conditions(w, conditions: list, motion: dict | None = None) -> list:
    """Test every binding condition against current canonical state. Pure: no mutation."""
    values = condition_values(w, motion)
    results = []
    for cond in conditions or []:
        metric = cond.get("metric")
        # A reserve floor on a motion that pays nothing out of reserves is not tested, and cannot block it: the balance
        # such a motion leaves is today's, so a loan needing its own proceeds to reach the floor would block itself
        # (run 20261011-105713-seed1, Month 8). It is recorded as not applicable, so the record shows why.
        if motion is not None and _is_non_payment_reserve_floor(cond, motion):
            results.append({**cond, "met": True, "observed": None, "applies": False,
                            "reason": "not applicable: this motion pays nothing out of reserves"})
            continue
        # A floor on an arrears payment from reserves limits the payment. A floor on any other motion
        # (disaster relief drawing on reserves, say) is a test of the balance the motion would leave.
        if (metric == "reserves_after_payment" and motion is not None and cond.get("operator") == ">="
                and motion.get("type") == "settle_arrears"):
            results.append(_reserve_floor_result(w, cond, motion, values))
            continue
        observed = values.get(metric)
        detail = ""
        if metric == "reserves_after_payment" and motion is not None:
            if observed is None:
                detail = "post-action reserve balance could not be calculated"
            else:
                detail = (f"reserves_after_payment would fall to {observed:,.0f} "
                          f"(floor {cond.get('value'):,.0f})")
        elif metric == "league_credit_received":
            detail = "league credit received" if observed else "no league credit received yet"
        elif metric == "audited_register":
            detail = "register audited" if observed else "register not yet audited"
        elif observed is not None:
            detail = f"observed {observed:,.4g}, required {cond.get('operator')} {cond.get('value'):,.4g}"
        if observed is None or metric not in values:
            results.append({**cond, "met": False, "observed": None,
                            "reason": f"no canonical reading for {metric}"})
            continue
        op, want = cond.get("operator"), cond.get("value")
        met = observed == want if op == "==" else (observed >= want if op == ">=" else observed <= want)
        row = {**cond, "met": bool(met), "observed": observed}
        if not met:
            row["reason"] = detail or f"condition {metric} {op} {want} not met (observed {observed})"
        results.append(row)
    return results


def condition_mismatch(w, motion: dict) -> dict | None:
    """Final text says 'only after X' but the stored conditions would run now: block."""
    if str(motion.get("type", "")).strip() == "policy":
        # Wave A (engine 30, W3): the policy's gates are its per-item conditions (see motion_conditions);
        # there is no motion-level condition to compare the prose against.
        return None
    text_conds = parse_conditions(str(motion.get("text", "")), str(motion.get("type", "")),
                                  str(motion.get("subject", "")), motion.get("action"))
    if not text_conds:
        return None
    stored = motion.get("conditions") or motion.get("execution_conditions") or []
    if not stored:
        return {"code": "MOTION_CONDITION_MISMATCH",
                "detail": ("the final motion text imposes execution conditions "
                           f"({'; '.join(c['metric'] + ' ' + c['operator'] + ' ' + str(c['value']) for c in text_conds)}) "
                           "but the motion carries no executable conditions; it would run unconditionally"),
                "final_conditions": text_conds, "stored_conditions": [], "missing": text_conds}
    def stored_condition_satisfies(required: dict, candidate) -> bool:
        if not isinstance(candidate, dict) or candidate.get("metric") != required["metric"]:
            return False
        if candidate.get("operator") not in (">=", "<=", "=="):
            return False
        try:
            value = canonical_metric_value(required["metric"], float(candidate.get("value")))
        except (TypeError, ValueError):
            return False
        threshold = canonical_metric_value(required["metric"], float(required["value"]))
        operator = candidate["operator"]
        # A stored safeguard is adequate only when every state in which it permits execution
        # also satisfies the threshold stated in the final prose.
        if required["operator"] == ">=":
            return operator in (">=", "==") and value >= threshold
        if required["operator"] == "<=":
            return operator in ("<=", "==") and value <= threshold
        return operator == "==" and value == threshold

    missing = [c for c in text_conds
               if not any(stored_condition_satisfies(c, candidate) for candidate in stored)]
    if not missing:
        return None
    return {"code": "MOTION_CONDITION_MISMATCH",
            "detail": ("the final motion text requires "
                       f"({'; '.join(c['metric'] + ' ' + c['operator'] + ' ' + str(c['value']) for c in missing)}) "
                       "which the stored executable conditions omit; it would run too early"),
            "final_conditions": text_conds, "stored_conditions": stored, "missing": missing}


def bind_text_conditions(w, motion: dict, conditions: list) -> tuple[list, list]:
    """The conditions a passed motion executes under, and those its final text added.

    When the text the council voted for states a safeguard its executable conditions omit (an
    amendment rewrote the text and left the conditions), the safeguard binds as well: the motion runs
    only when its own conditions and the text's are all met, and a payment is sized to the stricter
    floor. Run under its own conditions alone it would run too early, which is why the gate refused
    it; refused outright, a motion that passed never ran even with the text's safeguard met."""
    mismatch = condition_mismatch(w, {**motion, "conditions": conditions})
    if not mismatch:
        return list(conditions), []
    missing = list(mismatch["missing"])
    return list(conditions) + missing, missing


# ---- what the council accepted ----------------------------------------------------------------------
# A condition is binding when it is among the motion's executable conditions, and those come from its
# proposer: the structured `conditions` it filed, or a safeguard its own words state. But a motion is
# also shaped after it is tabled, by the delegates who vote it through: a co-sponsor who attached a
# safeguard of its own, and the demands the response round exists to collect ("cap the payment at the
# 50M reserve floor"). When the votes that carried a motion are votes that asked for the same floor,
# that floor is what the council agreed, and it has to reach execution whoever happened to table it.
#
# One kind of term is read back from free text: a floor on reserves, for a payment made from reserves.
# It is the one the record showed being lost, it is what such a vote is about (a payment the treasury
# cannot afford), and the constructions that state it are few. A demand that does not plainly state a
# floor states none; under-reading is the safe direction, because an unread demand leaves the engine
# exactly as it was.
_FIGURE = (r"(?P<num>\d[\d,]*(?:\.\d+)?)(?:\s*(?P<unit>bn|billion|mn|million|thousand|m|k)\b)?"
           r"(?!\s*(?:%|(?:percent|months?|weeks?|days?|years?|quarters?|troops?|soldiers?|men|people|persons?|"
           r"workers?|tonnes?|tons?|ships?|vessels?|units?|points?|hectares?)\b))")
_AROUND = r"(?:about\s+|roughly\s+|around\s+)?"
_UNIT_SCALE = {"bn": 1e9, "billion": 1e9, "mn": 1e6, "million": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}
_RESERVE_WORD = re.compile(r"\b(?:reserves?|gold|treasury)\b", re.I)
_FLOOR_PATTERNS = tuple(re.compile(p, re.I) for p in (
    # "do not let reserves fall below 60M", "reserves never fall below 50,000,000", "should not drop under 1.5bn",
    # "no payment that reduces reserves below 55M", "must not push reserves below roughly 50M"
    r"\b(?:not|never|n't|no|without|avoid\w*|prevent\w*|prohibit\w*|forbid\w*)\b[^.;]{0,40}?"
    r"\b(?:fall\w*|fell|drop\w*|dip\w*|sink\w*|slip\w*|go(?:es|ing)?|declin\w*|reduc\w*|push\w*|pull\w*|tak\w*|"
    r"bring\w*|draw\w*|drain\w*|deplet\w*)\b[^.;]{0,15}?"
    r"\b(?:below|under|beneath)\s+" + _AROUND + _FIGURE,
    # "reserves remain at or above 50M", "hold reserves at least 55 million", "stay >= 50M"
    r"\b(?:stay|stays|staying|remain|remains|remaining|keep|keeps|keeping|kept|hold|holds|holding|held|"
    r"maintain\w*|preserv\w*|retain\w*|leave|leaves|leaving|be)\b[^.;]{0,50}?"
    r"(?:>=|≥|\bat\s+or\s+above\b|\bat\s+least\b|\bno\s+(?:less|lower)\s+than\b|\bnot\s+below\b|\babove\b|"
    r"\bover\b|\bminimum\s+of\b)\s*" + _AROUND + _FIGURE,
    # "the 50M reserve floor", "a 45M reserve floor", "50M minimum"
    _FIGURE + r"\s*(?:gold\s+|crowns?\s+)?(?:(?:reserve|reserves)\s+)?(?:floor|minimum|buffer|threshold)\b",
    # "reserve floor of 50M", "a floor at 50M"
    r"\b(?:floor|minimum|buffer|threshold)\s+(?:of|at|to)\s+" + _AROUND + _FIGURE,
    # "at least 50M in reserves", ">= 50M of gold"
    r"(?:>=|≥|\bat\s+least\b|\bno\s+less\s+than\b)\s*" + _FIGURE +
    r"\s*(?:gold\s+|crowns?\s+)?(?:in|of)\s+(?:the\s+)?(?:foreign\s+)?(?:reserves?|gold)\b",
))


_MONEY_TAIL = re.compile(r"\s*(?:gold|crowns?|karams?)\b|\s*(?:gold\s+|crowns?\s+)?(?:reserves?\s+)?"
                         r"(?:floor|minimum|buffer|threshold)\b", re.I)


def _figure_value(match, clause: str) -> float | None:
    """The amount a figure names, in the units reserves are held in, or None if it is not money.

    "50M", "50 million" and "1.5bn" say what they are. A bare figure is money only when it is already
    a full amount (50,000,000) or is written as one ("50 gold", "a 50 reserve floor"): "28,000" in the
    same sentence as "reserves" is a troop count."""
    try:
        number = float(match.group("num").replace(",", ""))
    except ValueError:
        return None
    unit = (match.group("unit") or "").lower()
    if unit:
        return number * _UNIT_SCALE[unit]
    if number >= 1e5:
        return number
    return canonical_metric_value("reserves_after_payment", number) if _MONEY_TAIL.match(clause, match.end("num")) else None


def floor_from_demand(text: str) -> float | None:
    """The reserve floor a piece of response-round prose states, or None.

    "Ensure reserves do not fall below 50M gold" and "cap payment at the 50M reserve floor" state one.
    "Reserves are above 97M", "pay 47M now" and "cap payment at 47M" state a fact or an amount, not a
    floor, and a figure that is not next to floor wording is never read as one. Where one demand states
    several, the highest is taken: a delegate who asks for 60M and for not going under 50M has asked
    for 60M.
    """
    found = []
    for clause in re.split(r";|(?<=[A-Za-z0-9)])\.(?=\s)", str(text or "")):
        for index, pattern in enumerate(_FLOOR_PATTERNS):
            for match in pattern.finditer(clause):
                # The floor has to be about reserves: the word is in the phrase, just before it, or
                # straight after the figure ("55M gold").
                if not _RESERVE_WORD.search(clause[max(0, match.start() - 60):match.end() + 12]):
                    continue
                # The first pattern is the negated one ("do not bring reserves below 50M"). Its verbs name how
                # reserves fall, not an aim, so it is never read as a goal.
                if index and _demand_states_a_goal(clause, match):
                    continue
                value = _figure_value(match, clause)
                if value and value > 0:
                    found.append(value)
    return max(found) if found else None


def _demand_states_a_goal(clause: str, match) -> bool:
    """Whether a demand's floor is an aim: the reserve word nearest the figure, read as _states_a_goal reads it.

    "Reserves to be rebuilt above 60M before any payment" and "raise reserves to a 60M floor" name a goal;
    "keep reserves above 50M" names a level to keep."""
    anchors = [m.start() for m in _RESERVE_WORD.finditer(clause, max(0, match.start() - 60), match.end())]
    start = anchors[-1] if anchors else match.start()
    return _states_a_goal(clause, start, match.end())


def _is_reserve_floor(cond) -> bool:
    return isinstance(cond, dict) and cond.get("metric") == "reserves_after_payment" and cond.get("operator") == ">="


def _says_at_least(have: dict, want: dict) -> bool:
    """Whether a condition the motion already carries says everything `want` says."""
    if have.get("metric") != want.get("metric") or have.get("operator") != want.get("operator"):
        return False
    try:
        held, asked = float(have["value"]), float(want["value"])
    except (KeyError, TypeError, ValueError):
        return False
    op = want["operator"]
    return held >= asked if op == ">=" else (held <= asked if op == "<=" else held == asked)


def accepted_conditions(w, motion: dict, votes: dict) -> list:
    """The reserve floor the coalition that carried an arrears payment from reserves asked for.

    Each yes-voter's stated floor is the highest one it put on the table: a demand in the response
    round, or a safeguard it attached as a co-sponsor. The floor the council accepted is the highest
    F for which the yes-voters who asked for at least F would, alone, carry the motion under the
    decision rule in force: a floor one delegate wants is that delegate's, and a floor a winning
    coalition wants is the council's. Nothing is invented: no stated floor, or none with a winning
    coalition behind it, yields [].
    """
    if str(motion.get("type", "")) != "settle_arrears" or str(motion.get("subject", "")) != "reserves":
        return []
    from .politics import passes
    asked: dict = {}
    for demand in motion.get("demands") or []:
        if isinstance(demand, dict) and demand.get("member"):
            floor = floor_from_demand(str(demand.get("demand_full") or demand.get("demand", "")))
            if floor:
                asked[demand["member"]] = max(asked.get(demand["member"], 0.0), floor)
    for member, conds in (motion.get("sponsor_conditions") or {}).items():
        for cond in conds or []:
            if _is_reserve_floor(cond):
                try:
                    asked[member] = max(asked.get(member, 0.0), float(cond["value"]))
                except (KeyError, TypeError, ValueError):
                    continue
    yes = {member for member, vote in votes.items() if vote == "yes"}
    for floor in sorted({f for member, f in asked.items() if member in yes}, reverse=True):
        backers = sorted(member for member, f in asked.items() if member in yes and f >= floor)
        if passes(w, {member: ("yes" if member in backers else "abstain") for member in votes}):
            return [{"metric": "reserves_after_payment", "operator": ">=", "value": floor,
                     "source": f"accepted by {', '.join(backers)}: a reserve floor stated in the response "
                               f"round or as a co-sponsor's safeguard",
                     "accepted_by": backers}]
    return []


def bind_conditions(stored: list, accepted: list) -> list:
    """The conditions a motion executes under: what it carries, plus what the council accepted that it
    does not already carry. A stricter condition already carried is kept as it is."""
    bound = [c for c in (stored or [])]
    for want in accepted or []:
        if not any(_says_at_least(have, want) for have in bound):
            bound.append(dict(want))
    return bound


def condition_execution_mismatch(w, motion: dict, accepted: list, stored: list) -> dict | None:
    """An accepted condition the motion did not carry, and whether executing it as recorded breaks it.

    None when everything the council accepted was already among the motion's own conditions. The cost
    is what the motion would have spent under the conditions it DID carry (none, for the motion that
    was lost on run 20260930-173547-seed1), so `would_violate` is an honest answer to "what would the
    engine have done before this was attached".
    """
    stored = [c for c in (stored or []) if isinstance(c, dict)]
    missing = [c for c in (accepted or []) if not any(_says_at_least(have, c) for have in stored)]
    if not missing:
        return None
    from .politics import settle_arrears_cost
    carried_floor = max((float(c["value"]) for c in stored if _is_reserve_floor(c)), default=0.0)
    reserves = float(w.econ.gold)
    cost = float(settle_arrears_cost(w, motion, floor=carried_floor))
    after = reserves - cost
    violations = [{"metric": c["metric"], "operator": c["operator"], "value": c["value"],
                   "reserves_before": reserves, "requested_cost": cost, "reserves_after_unconstrained": after,
                   "short_by": float(c["value"]) - after}
                  for c in missing if _is_reserve_floor(c) and after < float(c["value"]) - 1e-6]
    asked = "; ".join(f"{c['metric']} {c['operator']} {c['value']:,.0f} (accepted by {', '.join(c.get('accepted_by', []))})"
                      for c in missing)
    return {"code": "CONDITION_EXECUTION_MISMATCH",
            "detail": (f"the council accepted {asked}, but the motion it voted on did not carry it; executed as "
                       + (f"recorded it would have left reserves at {after:,.0f}" if violations else
                          "recorded it would still have respected it")),
            "accepted_conditions": list(accepted), "stored_conditions": stored, "missing": missing,
            "would_violate": bool(violations), "violations": violations}


def condition_execution_violation(w, conditions: list) -> list:
    """Reserve floors the state is under once a payment has run. Empty when every floor held.

    Execution sizes the payment to the floor, so this should always be empty; it is here so a path
    that does not (a payment made some other way) is recorded instead of trusted."""
    reserves = float(w.econ.gold)
    out = []
    for cond in conditions or []:
        if _is_reserve_floor(cond):
            try:
                floor = float(cond["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if reserves < floor - 1e-3:
                out.append({**cond, "observed": reserves})
    return out


def _canonical_actor(w, raw: str) -> str | None:
    """Map a delegate's spelling of an actor onto the canonical ids the engine knows.

    Accepts the canonical id, the display name, and the older lowercase keys that recorded runs and
    saved state still carry, so a motion written under any of them resolves to one actor.
    """
    text = str(raw).casefold()
    if text.strip() in ACTOR_ALIASES:
        return ACTOR_ALIASES[text.strip()]
    # Where a target names more than one actor, the one it names first is the target: "Veleria (a Union member)" is
    # Veleria, not the Union it belongs to (audit MO23). Ties keep the order of _actor_patterns.
    first = None
    for actor, patterns in _actor_patterns(w).items():
        for p in patterns:
            match = re.fullmatch(p.replace(r"\b", "").strip(), text, re.I) or re.search(p, text, re.I)
            if match and (first is None or match.start() < first[0]):
                first = (match.start(), actor)
    return first[1] if first else None


def party_of(actor: str | None) -> str | None:
    """The state model's name for a canonical actor, for routing a proposal."""
    return {SOLVARAN_UNION: "union", MARITIME_LEAGUE: "league", DORSANIA: "dorsania",
            VELERIA: "veleria"}.get(actor)


def _accepted_acts(actor: str) -> list:
    """The acts the table lets this actor receive, in DIPLOMATIC_ACTIONS order: what a refusal tells a delegate it can
    address to that actor (engine 24). It reads the table the check reads, DIPLOMATIC_TARGETS, not each act's default
    receiver, which named only cede_region for Veleria and only grain_deal for Dorsania."""
    return [act for act in DIPLOMATIC_ACTIONS if actor in DIPLOMATIC_TARGETS.get(act, {DIPLOMATIC_ACTIONS[act]})]


def _not_valid_for_target(action_type: str, target: str) -> str:
    """Why an act cannot go to this target: the actors it can go to, and the acts this target accepts (engine 24). A
    delegate that wrote the wrong act for its target reads the act it can send here. Run 20261011-105713-seed1 (status
    talks to Dorsania, Month 9) and run 20261011-211521-seed1 (status talks to Veleria, Month 2) were refused with only
    the actors named, so the delegate had nothing to put in its place."""
    allowed = DIPLOMATIC_TARGETS.get(action_type, {DIPLOMATIC_ACTIONS.get(action_type)})
    names = ", ".join(ACTOR_NAMES[a] for a in sorted(allowed))
    return (f"a {action_type} can be addressed to {names}, not the {ACTOR_NAMES[target]}. "
            f"{ACTOR_NAMES[target]} accepts: {', '.join(_accepted_acts(target))}")


def validate_diplomatic_action(w, motion: dict) -> dict | None:
    """Check diplomatic text/action agreement and statically valid targets before a vote."""
    action = structured_action(w, motion)
    if action.get("kind") != "diplomacy":
        return None
    mismatch = conflict(w, motion)
    if mismatch:
        reasons = mismatch.get("reasons", [])
        details = "; ".join(reason["detail"] for reason in reasons)
        if all(reason["code"] == "ACTION_NOT_VALID_FOR_TARGET" for reason in reasons):
            # The words and the action agree; the act simply cannot go to that actor, and is refused
            # under that name rather than as a disagreement.
            return {"code": "ACTION_NOT_VALID_FOR_TARGET", "detail": details}
        return {"code": mismatch["code"],
                "detail": "the diplomatic motion's text and executable action disagree: " + details}
    if not action.get("target"):
        return {"code": "NO_TARGET",
                "detail": f"a {action['action_type']} does not name a country or institution to address"}
    if action["target"] not in ACTORS:
        return {"code": "UNKNOWN_TARGET", "detail": f"unknown target {action['target']!r}"}
    expected = DIPLOMATIC_ACTIONS.get(action["action_type"])
    if expected is None:
        return {"code": "UNKNOWN_ACTION_TYPE", "detail": f"unknown diplomatic action {action['action_type']!r}"}
    allowed = DIPLOMATIC_TARGETS.get(action["action_type"], {expected})
    if action["target"] not in allowed:
        return {"code": "ACTION_NOT_VALID_FOR_TARGET",
                "detail": _not_valid_for_target(action["action_type"], action["target"])}
    if action["action_type"] == "ultimatum_reply":
        return _ultimatum_reply_problem(w, action)
    if action["action_type"] == "cede_region":
        # Checked here, so it holds at tabling and again when the motion executes (engine 17, territory).
        from . import territory
        return territory.cession_problem(w, motion, party_of(action["target"]))
    return None


def _ultimatum_reply_problem(w, action: dict) -> dict | None:
    """A reply answers the ultimatum that stands, and is addressed to the power that issued it, or to the Union for a
    member's demand (engine 22). Run 20261011-105713-seed1, Months 7-9: the council answered Dorsania's ultimatum
    through grain deals, because no act could carry an answer to it."""
    ult = w.dip.ultimatum or {}
    if not ult:
        return {"code": "NO_ULTIMATUM", "detail": "no ultimatum stands to answer"}
    by = str(ult.get("by") or "veleria")
    issuer = _canonical_actor(w, by) or SOLVARAN_UNION
    if action["target"] not in (issuer, SOLVARAN_UNION):
        name = w.names.get(by, ACTOR_NAMES.get(issuer, issuer))
        target = ("the " if action["target"] in (SOLVARAN_UNION, MARITIME_LEAGUE) else "") + ACTOR_NAMES[action["target"]]
        return {"code": "ULTIMATUM_NOT_FROM_TARGET",
                "detail": f"the ultimatum was issued by {name}, so it is answered by {name} or the Solvaran Union, "
                          f"not by {target}"}
    return None


#: The stance a reply to an ultimatum takes, as its words state it (engine 22). A stance word, read as negated when a
#: negator stands in its clause ("will not accept"), turns the stance; anything else is a counter-proposal.
_STANCE_WORD = re.compile(r"\b(?:accept\w*|agree|agrees|agreed|comply|complies|complied|reject\w*|refus\w*|declin\w*)\b",
                          re.I)
_STANCE_CLAUSE_END = re.compile(r"[;:!?\n]|\.(?!\d)")


def ultimatum_stance(motion: dict) -> str:
    """'accept', 'reject' or 'counter' for a reply to an ultimatum. An explicit action stance is taken as given; otherwise
    the first stance word in the text decides."""
    explicit = motion.get("action") if isinstance(motion.get("action"), dict) else {}
    given = str(explicit.get("stance") or "").strip().lower()
    if given in ("accept", "reject", "counter"):
        return given
    body = str(motion.get("text", "") or "")
    for word in _STANCE_WORD.finditer(body):
        starts = [m.end() for m in _STANCE_CLAUSE_END.finditer(body, 0, word.start())]
        clause = body[starts[-1] if starts else 0:word.start()]
        accepting = word.group(0).lower().startswith(("accept", "agree", "comply"))
        negated = negates(clause)
        if accepting:
            return "reject" if negated else "accept"
        return "counter" if negated else "reject"
    return "counter"


# An actor named as the pressure a motion answers ("against Union pressure", "despite Union threats")
# is not the actor the motion is addressed to. Only these cues count, and only next to the name:
# "from" is deliberately absent, because "a loan from the League" names the counterparty and
# "protection from the Union" names the adversary, and the words alone cannot tell them apart.
_CONTEXT_BEFORE = re.compile(
    r"(?:against|despite|amid|versus|vs\.?|facing|about|regarding|concerning|because\s+of|countering|"
    r"counter|deter(?:ring)?|resist(?:ing)?|pressure\s+from|threats?\s+from)\s+(?:the\s+|a\s+|an\s+)?(?:\w+\s+){0,2}$",
    re.I)
_CONTEXT_AFTER = re.compile(
    r"^\W{0,2}(?:'s\s+)?(?:pressure|threats?|aggression|invasion|annexation|ultimatums?|blockade|embargo|"
    r"sanctions|ambitions?|demands?)\b", re.I)


def _mention_spans(w, text: str) -> dict:
    """actor -> the (start, end) of every place the text names it."""
    out = {}
    for actor, patterns in _actor_patterns(w).items():
        spans = [(m.start(), m.end()) for p in patterns for m in re.finditer(p, text, re.I)]
        if spans:
            out[actor] = spans
    return out


def _as_context(text: str, start: int, end: int) -> bool:
    return bool(_CONTEXT_BEFORE.search(text[max(0, start - 40):start]) or _CONTEXT_AFTER.match(text[end:end + 30]))


def prose_intent(w, text: str) -> dict:
    """What a motion's words say it does: which foreign actors it names, and which act.

    A high-precision read. It reports what the prose names, and nothing about what it might imply.
    `actors` is every actor named. `addressed` is the ones the motion is aimed at: where several are
    named, an actor that appears only as the pressure being answered ("against Union pressure") is
    left out, so a text that names the Union as its adversary is not mistaken for one addressed to it.
    Where only one actor is named it is the addressee whatever its context, as it always was.
    """
    body = str(text or "")
    mentions = _mention_spans(w, body)
    actors = sorted(mentions)
    # An act the text rules out is not an act it names: "no accession, no federation" (engine 16). "Nothing short
    # of a federation" affirms one, so the idiom is blanked first (MO15).
    affirmed = NEGATED_ACT.sub(" ", _AFFIRMING_IDIOM.sub(" ", body))
    actions = [a for a, pats in PROSE_ACTIONS if _hits(affirmed, pats)]
    addressed = actors if len(actors) <= 1 else sorted(
        a for a, spans in mentions.items() if any(not _as_context(body, s, e) for s, e in spans))
    return {"actors": actors, "addressed": addressed, "actions": actions,
            "negates_force": bool(re.search(r"\brenounce\s+force|no\s+recourse\s+to\s+force", body, re.I))}


_ULTIMATUM_MENTION = re.compile(r"\bultimatums?\b|\bdeadlines?\b", re.I)


def _answers_an_ultimatum(action: dict, text: str) -> bool:
    """A reply to an ultimatum names the acts it refuses or keeps ("we reaffirm our non-aggression obligations"). Those are
    its words about the demand, not a different act, so the act check does not read them as one (engine 22)."""
    return action.get("action_type") == "ultimatum_reply" and bool(_ULTIMATUM_MENTION.search(text or ""))


#: A verb that moves a setting, as a delegate writes it. "without cutting" is refused by its negator, not read here.
_SETTING_VERB = re.compile(r"\b(?:rais(?:e|es|ed|ing)|cut|cuts|cutting|lower(?:s|ed|ing)?|set|sets|setting|"
                           r"increas(?:e|es|ed|ing)|reduc(?:e|es|ed|ing)|lift(?:s|ed|ing)?|hike[sd]?|hiking|"
                           r"boost(?:s|ed|ing)?|halv(?:e|es|ed|ing)|doubl(?:e|es|ed|ing)|freez(?:e|es|ed|ing)|"
                           r"slash(?:es|ed|ing)?)\b", re.I)
_LEVER_WORDS = None


def _lever_words():
    """The domestic levers a text can name, as (pattern, {spelling: lever}). The vocabulary is the engine's own: the levers
    in politics.LEVER_OFFICE and their aliases. "protest" is an alias of protest_response, but it names the act, so it
    is left out."""
    global _LEVER_WORDS
    if _LEVER_WORDS is None:
        from .politics import LEVER_ALIASES, LEVER_OFFICE
        canon = {name: name for name in LEVER_OFFICE}
        canon.update({alias: lever for alias, lever in LEVER_ALIASES.items() if alias != "protest"})
        parts = [(_NOT_A_LEVER_RATE if name == "rate" else "") + name.replace("_", r"[\s_-]+") + "s?"
                 for name in sorted(canon, key=len, reverse=True)]
        _LEVER_WORDS = (re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.I), canon)
    return _LEVER_WORDS


def _domestic_lever_change(text: str) -> str | None:
    """The domestic lever a text changes with a verb ("raise the tax take", "set the army target at 39,000"), or None.
    A verb the text refuses is no change ("without cutting police pay"), and a lever named with no verb is a state, not a
    change. Only the clause the verb opens is read, so the verb and its lever stand together."""
    pattern, canon = _lever_words()
    body = str(text or "")
    for verb in _SETTING_VERB.finditer(body):
        starts = [m.end() for m in _STANCE_CLAUSE_END.finditer(body, 0, verb.start())]
        before = body[max(starts[-1] if starts else 0, verb.start() - 40):verb.start()]
        if negates(before):
            continue
        ends = _STANCE_CLAUSE_END.search(body, verb.end())
        window = body[verb.end():min(ends.start() if ends else len(body), verb.end() + 60)]
        hit = pattern.search(window)
        key = re.sub(r"[\s_-]+", "_", hit.group(0).lower()) if hit else ""
        lever = canon.get(key) or canon.get(key[:-1])
        if lever:
            return lever
    return None


# ---- the consistency check --------------------------------------------------------------------------
def conflict(w, motion: dict) -> dict | None:
    """Where a motion's words and its executable payload disagree, or None.

    Only foreign actions are judged this way, and only on evidence the prose actually states: an
    actor it addresses that the payload does not, an act it names that the payload is not, or an act
    that the payload's own target does not receive. A motion whose words address several actors, or
    none, is left alone. The actor a text is aimed at is judged, not every actor it mentions: one named
    only as the pressure being answered is context.
    """
    action = structured_action(w, motion)
    if action["kind"] != "diplomacy":
        if str(motion.get("type", "")) == "set_policy":
            return _policy_figures_conflict(motion, action)
        return _text_action_conflict(w, motion, action)
    text = str(motion.get("text", ""))
    intent = prose_intent(w, text)
    reasons = []
    named = intent["addressed"]
    if len(named) == 1 and action.get("target") and named[0] != action["target"]:
        reasons.append({"code": "FOREIGN_TARGET_MISMATCH", "prose_actor": named[0],
                        "action_actor": action["target"],
                        "detail": f"the text addresses the {ACTOR_NAMES[named[0]]}, but the structured "
                                  f"action is sent to the {ACTOR_NAMES.get(action['target'], action['target'])}"})
    # The motion's value is a second place the counterparty can be named ("DORSANIA, 2.0M gold ...").
    valued = prose_intent(w, str(motion.get("value") or ""))["actors"]
    if len(valued) == 1 and action.get("target") and valued[0] != action["target"] \
            and not any(r["prose_actor"] == valued[0] for r in reasons):
        reasons.append({"code": "FOREIGN_TARGET_MISMATCH", "prose_actor": valued[0],
                        "action_actor": action["target"], "source": "value",
                        "detail": f"the motion's value names the {ACTOR_NAMES[valued[0]]}, but the structured "
                                  f"action is sent to the {ACTOR_NAMES.get(action['target'], action['target'])}"})
    # An act goes to an actor that receives it. This was checked only when the motion tried to
    # execute, so the council voted on a trade deal "with Dorsania" that could never run.
    expected = DIPLOMATIC_ACTIONS.get(action["action_type"])
    allowed = DIPLOMATIC_TARGETS.get(action["action_type"], {expected}) if expected else None
    if allowed and action.get("target") in ACTORS and action["target"] not in allowed:
        reasons.append({"code": "ACTION_NOT_VALID_FOR_TARGET", "action_type": action["action_type"],
                        "action_actor": action["target"], "expected_actor": expected,
                        "detail": _not_valid_for_target(action["action_type"], action["target"])})
    declared = motion.get("declared_subject")
    if declared and motion.get("subject"):
        # Only a subject that names a *different act* contradicts the payload. A subject that is a
        # topic ("Head of Government"), an office ("Treasury") or an actor ("Solvaran Union") is the
        # delegate labelling what the motion concerns, not claiming a different action; reading any
        # such label as a contradiction was rejecting a large share of sound motions on a wording
        # technicality, which is harness friction rather than a genuine disagreement about the act.
        norm = re.sub(r"[\s\-]+", "_", str(declared).strip().lower())
        if norm in ACT_NAMES and norm not in (str(motion.get("subject", "")).lower(),
                                              str(action["action_type"]).lower()):
            reasons.append({"code": "DECLARED_SUBJECT_CONTRADICTS_ACTION", "declared": declared,
                            "action_type": action["action_type"],
                            "detail": f"the motion's own subject says {declared}, but its action says "
                                      f"{action['action_type'].replace('_', ' ')}"})
    said = intent["actions"]
    if said and action["action_type"] not in said and not _answers_an_ultimatum(action, text):
        # "protest" and "trade deal" are different acts even when both are sent abroad.
        closest = _most_specific(said)
        reasons.append({"code": "ACTION_MISMATCH", "prose_action": closest,
                        "action_type": action["action_type"],
                        "detail": f"the text describes {_an_act(closest)}, but the structured "
                                  f"action is {_an_act(action['action_type'])}"})
    if not intent["actors"] and not said:
        # A text that names no foreign power and no foreign act cannot be a protest or a proposal to anyone, so a
        # domestic setting it moves is the measure it is (run 20261011-105713-seed1, Month 8: "raise the tax take to 0.30"
        # tabled as a diplomatic protest to the Solvaran Union, and passed).
        lever = _domestic_lever_change(text)
        if lever:
            target = action.get("target")
            to = (f" to {'the ' if target in (SOLVARAN_UNION, MARITIME_LEAGUE) else ''}{ACTOR_NAMES[target]}"
                  if target in ACTOR_NAMES else "")
            reasons.append({"code": "DOMESTIC_TEXT_FOREIGN_ACTION", "lever": lever,
                            "action_type": action["action_type"], "action_actor": target,
                            "detail": f"the text describes a domestic measure ({lever.replace('_', ' ')}), but the "
                                      f"structured action is {_an_act(action['action_type'])}{to}"})
    if not reasons:
        return None
    return {"code": "MOTION_ACTION_MISMATCH", "motion": motion.get("id"), "prose": text,
            "structured_action": action, "prose_intent": intent, "reasons": reasons}


# What an appointment, an expulsion, a referendum or an emergency says in its own words (audit MO19). The member an
# appointment or an expulsion names comes right after its verb; the verb is read in any case, the name in capitals.
_APPOINTEE = re.compile(r"\b(?i:appoint|nominat|install|designat|promot|nam)\w*\s+(?:(?i:of|the)\s+)*"
                        r"(?:(?i:member|delegate)\s+)?([A-Z])\b")
_EXPELLEE = re.compile(r"\b(?i:expel|expulsion|dismiss|oust|eject|remov)\w*\s+(?:(?i:of|the)\s+)*"
                       r"(?:(?i:member|delegate)\s+)?([A-Z])\b")
_REFERENDUM_QUESTION = re.compile(r"\breferend\w*\b[^.;:!?]*?\b(?:on|about|over|whether|asking)\b\s*([^.;:!?,]+)", re.I)
_INDEPENDENCE = re.compile(r"independen|sovereign", re.I)  # the one question the engine's referendum puts
_RELEASE = r"\b(?:lift|end|repeal|revoke|rescind|terminate|cancel)(?:s|d|ed|ing|led|ling)?\b"
_IMPOSE = r"\b(?:impose|declare|proclaim|invoke|introduce|enact|establish|extend|restore|reinstate)(?:s|d|ed|ing)?\b"
# An office is named by the words slate reads for prose, and the titles a motion uses for the Treasury.
_OFFICE_TITLE_WORDS = {office: tuple(words) + (("minister of finance", "minister of the treasury")
                                               if office == "treasury" else ())
                       for office, words in _OFFICE_WORDS.items()}


def _emergency_object(kind: str, subject: str) -> str:
    """The words that name what an emergency motion switches: the state of emergency, or the measure it names."""
    if kind == "constitution":
        return r"(?:(?:the|this|a|an|our|national|nationwide)\s+)*(?:state\s+of\s+)?emergency\b"
    parts = [re.escape(part) for part in re.split(r"[\s_-]+", subject) if part]
    if not parts:
        return ""
    return r"(?:(?:the|this|a|an|our|emergency|night)\s+)*" + r"[\s_-]+".join(parts) + r"\b"


def _text_action_conflict(w, motion: dict, action: dict) -> dict | None:
    """Where an appointment, an expulsion, a referendum or an emergency says something other than what it executes.

    Audit MO19: the council votes on the text, and the engine executes the fields, so each must say the same. The
    member the text names must be the motion's member, the office it names must be the motion's office, a referendum
    may ask only the question the engine holds (independence), and "lift" against "on" (or "impose" against "off")
    is a conflict. A conflict is held back for repair, as for diplomacy.
    """
    from .world import OFFICE_TITLES, OFFICES
    kind = str(motion.get("type", ""))
    text = str(motion.get("text", "") or "")
    subject = str(motion.get("subject", "") or "").strip()
    value = str(motion.get("value", "") or "").strip().lower()
    reasons = []
    if kind in ("assign_office", "vacate_office") and subject.lower() in OFFICES:
        named = {office for office, words in _OFFICE_TITLE_WORDS.items()
                 if any(re.search(r"\b" + re.escape(word) + r"\b", text, re.I) for word in words)}
        if named and subject.lower() not in named:
            said = ", ".join(OFFICE_TITLES[office] for office in sorted(named))
            reasons.append({"code": "OFFICE_MISMATCH", "office": subject.lower(), "named": sorted(named),
                            "detail": f"the text names {said}, but the motion's office is "
                                      f"{OFFICE_TITLES[subject.lower()]}"})
    if kind == "assign_office":
        appointee = _APPOINTEE.search(text)
        if appointee and value and appointee.group(1) != value.upper():
            reasons.append({"code": "APPOINTEE_MISMATCH", "named": appointee.group(1), "appointed": value.upper(),
                            "detail": f"the text appoints member {appointee.group(1)}, but the motion appoints "
                                      f"{value.upper()}"})
    if kind == "expel":
        expelled = _EXPELLEE.search(text)
        if expelled and subject and expelled.group(1) != subject.upper():
            reasons.append({"code": "EXPULSION_MISMATCH", "named": expelled.group(1), "expelled": subject.upper(),
                            "detail": f"the text expels member {expelled.group(1)}, but the motion expels "
                                      f"{subject.upper()}"})
    if kind == "referendum":
        found = _REFERENDUM_QUESTION.search(text)
        question = found.group(1).strip(" ,") if found else ""
        if question and (not _INDEPENDENCE.search(question) or prose_intent(w, question)["actions"]):
            reasons.append({"code": "REFERENDUM_QUESTION_MISMATCH", "question": question,
                            "detail": f"the text puts another question to the vote ('{question[:120]}'), but the "
                                      "engine holds only the referendum on independence"})
    emergency = kind == "emergency_measure" or (kind == "constitution" and subject.lower() == "emergency")
    if emergency and value in ("on", "off"):
        obj = _emergency_object(kind, subject)
        label = "the state of emergency" if kind == "constitution" else subject.replace("_", " ")
        if obj and value == "on" and re.search(_RELEASE + r"\s+" + obj, text, re.I):
            reasons.append({"code": "EMERGENCY_MISMATCH", "value": value,
                            "detail": f"the text lifts {label}, but the motion switches it on"})
        elif obj and value == "off" and re.search(_IMPOSE + r"\s+" + obj, text, re.I):
            reasons.append({"code": "EMERGENCY_MISMATCH", "value": value,
                            "detail": f"the text imposes {label}, but the motion switches it off"})
    if not reasons:
        return None
    return {"code": "MOTION_ACTION_MISMATCH", "motion": motion.get("id"), "prose": text,
            "structured_action": action, "prose_intent": {}, "reasons": reasons}


# A share moved from one figure to another (audit MO12): the target is a percentage, whether or not the start is
# ("from 6% to 7%", "from 6 percent to 7 percent", "from 6 to 7%", "from 6% up to 7%", "6% -> 7%").
_PERCENT_CHANGE = re.compile(r"(?:\bfrom\s+)?\d+(?:\.\d+)?\s*(?:%|percent)?\s*(?:(?:up|down)\s+)?(?:to|->|→)\s*"
                             r"(\d+(?:\.\d+)?)\s*(?:%|percent)", re.I)
# In decimals a share is already a fraction, and the "from" is what makes it one: "from 0.06 to 0.07".
_DECIMAL_CHANGE = re.compile(r"\bfrom\s+\d*\.\d+\s+(?:(?:up|down)\s+)?to\s+(\d*\.\d+)\b", re.I)


def _share_changes(text: str) -> list:
    """(what the text says, the share it moves the setting to) for each share change it states, in order."""
    found = [(m.start(), m.group(0), float(m.group(1)) / 100) for m in _PERCENT_CHANGE.finditer(text)]
    found += [(m.start(), m.group(0), float(m.group(1))) for m in _DECIMAL_CHANGE.finditer(text)]
    # The quote keeps the figures as the text wrote them, without the "from" that introduces them.
    return [(re.sub(r"^from\s+", "", said, flags=re.I), target) for _start, said, target in sorted(found)]


def _policy_figures_conflict(motion: dict, action: dict) -> dict | None:
    """A policy motion whose text moves a share setting "from A% to B%" while its value sets another.

    Month 8 of the first engine-6 run with real models: the text raised the rate "from 6% to 7%", the
    figures of Month 1, and the motion set it to 0.11 from 0.10; the council voted on one and got the
    other. Only the target is compared: the current figure may have moved since the delegate read it."""
    from .politics import canonical_lever, parse_lever
    lever = canonical_lever(str(motion.get("subject", "")))
    value = parse_lever(lever, motion.get("value")) if lever else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        return None
    text = str(motion.get("text", ""))
    changes = _share_changes(text)
    if not changes or any(abs(target - value) <= 0.0005 for _said, target in changes):
        return None
    said, target = changes[0]
    reason = {"code": "POLICY_FIGURES_MISMATCH", "lever": lever, "value": value, "prose_target": target,
              "detail": f"the text moves {lever} {said}, but the motion sets {lever} to "
                        f"{value:g} ({value * 100:g}%)"}
    return {"code": "MOTION_ACTION_MISMATCH", "motion": motion.get("id"), "prose": text,
            "structured_action": action, "prose_intent": {}, "reasons": [reason]}


def _an_act(name: str) -> str:
    """'a federation', 'status talks': an act named with its article, if it takes one."""
    words = name.replace("_", " ")
    return words if words.endswith("talks") else ("an " if words[0] in "aeiou" else "a ") + words


def _most_specific(actions: list) -> str:
    """The act the prose is really describing when it mentions several."""
    order = [a for a, _ in PROSE_ACTIONS]
    return sorted(actions, key=lambda a: order.index(a))[0]


def _named(actor) -> str:
    """'the Solvaran Union', 'the Maritime League', 'Dorsania': a power as a sentence names it."""
    name = ACTOR_NAMES.get(actor, str(actor))
    return f"the {name}" if actor in (SOLVARAN_UNION, MARITIME_LEAGUE) else name


def repair_request(w, c: dict) -> str:
    """The targeted repair sent back to the same delegate for the one malformed motion."""
    action = c["structured_action"]
    # A motion held back before it is tabled has no id yet, and printing "Motion None" at a model
    # is both sloppy and confusing about which motion is meant.
    motion_id = c.get("motion")
    named = f"Motion {motion_id}" if motion_id else "The motion you just wrote"
    # Engine 29 (backlog T177): in words, with no code line and no engine: the delegate reads it as its government's
    # clerks would put it.
    lines = [f"{named} in this round cannot be carried out because its text and its 'action' describe different "
             "things."]
    lines.append(f"Your motion text: \"{c['prose'][:400]}\"")
    target = action.get("target")
    described = ", ".join(f"{r['detail']}" for r in c["reasons"])
    lines.append(f"Your 'action': {action['action_type'].replace('_', ' ')}"
                 + (f" to {_named(target)}" if target else "")
                 + (f", policy {action['policy']} = {action['value']}" if action.get("policy") else ""))
    lines.append(f"Where they differ: {described}.")
    # Say what the actor can actually receive, so the one repair is not spent guessing. Only actors the
    # conflict itself names are listed, and only from the engine's own action vocabulary.
    for actor in dict.fromkeys(r.get(key) for r in c["reasons"] for key in ("prose_actor", "action_actor")
                               if r.get(key) in ACTORS):
        acts = _accepted_acts(actor)
        if acts:
            lines.append(f"Acts that can be addressed to {_named(actor)}: {', '.join(acts)}.")
    lines.append("Correct either the 'action' or the motion text so they describe the same motion, "
                 "then resubmit that motion only. The rest of your answer stands.")
    return "\n".join(lines)


def structured_action_repair_request(motion: dict, rejection: dict) -> str:
    """Ask for one missing executable payload while preserving the delegate's stated policy."""
    return ("This motion was not tabled because its 'action' is incomplete: "
            f"{rejection.get('explanation', 'the program is missing executable measures')}.\n"
            f"Motion type: {motion.get('type', '')}; subject: {motion.get('subject', '')}; "
            f"value: {motion.get('value', '')}; text: \"{str(motion.get('text', ''))[:400]}\".\n"
            "Return this motion with the same type, subject, value and text. Fill only the 'action' "
            "fields needed to carry out the policy already stated. For a program, provide "
            "measures as [{lever, value}]. Use only levers and choices directly supported by the motion; "
            "do not add new policies or change its political intent. You can send it once more.")


def amendment_repair_request(motion: dict, sent: dict, refusal: dict) -> str:
    """Ask the proposer once to send a refused amendment again (engine 21), with the engine's reason and both texts whole."""
    mid = motion["id"]
    measures = "; ".join(f"{m.get('lever')} = {m.get('value')}" for m in sent.get("measures") or [])
    return (f"Your amendment to {mid} was refused, so {mid} still stands as tabled: "
            f"{refusal.get('explanation') or 'the amendment could not be carried out'}.\n"
            f"{mid} as tabled: \"{motion.get('text', '')}\"\n"
            f"The amendment you sent: \"{sent.get('text', '')}\"" + (f"; measures: {measures}" if measures else "")
            + ".\n"
            "Send the amendment again with the fault corrected and everything else as you meant it, or send an empty "
            f"list to leave {mid} as tabled. Do not add new policies. This is the single repair; the council votes "
            "after it.")


# ---- numeric grounding: what a delegate may claim -------------------------------------------
#: Important numeric claims and where the engine looks for a supporting source.
#: Tolerances are generous: briefing figures carry noise and office reports carry ranges.
#: What is refused is a precise statistic with no available source at all.
GROUNDING_SPECS = (
    # Audit MO22: the words are the ways a claim names the metric. A precise figure whose metric is named in none
    # of them went unchecked ("Consumer prices climbed 9%" at 0% inflation passed). The words below were added.
    ("food_ratio", ("food coverage", "food availability", "food supply", "food shortage",
                    "grain supply", "short of food", "food security", "food stocks", "food supplies",
                    "food ratio", "grain stocks", "grain availability", "food need"),
     "food_ratio", {"abs": 0.10, "rel": 0.25}),
    ("hunger", ("hunger", "hungry", "starving", "food shortage", "famine", "malnutrition", "starvation"),
     "hunger", {"abs": 0.06, "rel": 0.6}),
    ("inflation", ("inflation", "price rise", "price rising", "prices rising", "cpi", "consumer prices",
                   "prices are up", "prices up", "prices climb", "prices rose", "prices risen", "prices have risen",
                   "prices increased", "prices fell", "prices are down", "prices soared", "prices surged",
                   "price increase", "rising prices", "higher prices", "rise in prices", "price level",
                   "cost of living", "cost-of-living"),
     "inflation", {"abs": 0.05, "rel": 0.6}),
    ("reserves", ("reserves", "gold reserve", "treasury gold", "foreign reserve", "gold holdings", "gold stock",
                  "treasury balance", "hard currency"),
     "reserves", {"abs": 15e6, "rel": 0.4}),
    ("arrears", ("arrears", "unpaid bill", "payment backlog", "outstanding bills", "overdue bills", "bills owed",
                 "unpaid debt"),
     "arrears", {"abs": 15e6, "rel": 0.4}),
    ("unemployment", ("unemployment", "jobless", "out of work", "unemployed"),
     "unemployment", {"abs": 0.04, "rel": 0.6}),
    ("approval", ("approval", "popularity", "support for the government", "poll", "popular support",
                  "public support", "public trust", "trust in the government", "public opinion"),
     "approval", {"abs": 0.12, "rel": 0.6}),
    ("unrest", ("unrest", "protest", "riot", "disorder", "demonstrat", "uprising", "public anger", "agitation"),
     "unrest", {"abs": 0.12, "rel": 0.6}),
    ("army_size", ("army size", "soldier", "troop", "army strength", "under arms", "armed forces", "manpower",
                   "field strength", "army numbers"),
     "army_size", {"abs": 6000.0, "rel": 0.3}),
    ("army_readiness", ("readiness", "morale", "loyalty", "equipment", "combat effectiveness", "fighting spirit"),
     "army_readiness", {"abs": 0.2, "rel": 0.6}),
    ("union_forces", ("union force", "union army", "union soldier", "union troops", "union strength",
                      "solvaran union", "veleria", "dorsania", "enemy force", "enemy troops", "enemy army"),
     "union_forces", {"abs": 20000.0, "rel": 0.5}),
)

_GROUNDING_NUMBER = re.compile(
    # Audit MO3: "20,000,000" is one figure. It was read as 20, 000 and 000, and a bare 20 is no reserve
    # figure, so every comma-grouped claim passed while "20 million" was refused.
    # Audit MO6: "90/100" is 90% (the reports print their figures on this scale); it was read as a bare 90 and 100.
    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(%|percentage|percent|/\s*100\b|million|M\b|bn\b|billion|thousand|k\b)?"
    r"\s*(shortage|shortfall|hunger|hungry|starving|coverage|availability|inflation|unemployment|"
    r"approval|unrest|reserves?|gold|arrears|deficit|budget|spending|revenue|"
    r"soldiers?|troops?|warships?|ships?)?", re.IGNORECASE)


def _grounding_truth(w, key: str) -> float:
    if key == "food_ratio":
        return float(w.econ.food_ratio)
    if key == "hunger":
        return (sum(p.size for p in w.k_pops() if p.hunger > 0.1) / max(1.0, w.population())) if w.k_pops() else 0.0
    if key == "inflation":
        from .society import inflation_yoy
        return float(inflation_yoy(w))
    if key == "reserves":
        return float(w.econ.gold)
    if key == "arrears":
        return float(w.econ.arrears)
    if key == "unemployment":
        return float(w.econ.unemployment)
    if key == "approval":
        return float(w.avg("approval")) if w.k_pops() else 0.0
    if key == "unrest":
        return float(w.avg("unrest")) if w.k_pops() else 0.0
    if key == "army_size":
        return float(w.mil.army.size)
    if key == "army_readiness":
        return float((w.mil.army.morale + w.mil.army.loyalty) / 2)
    if key == "union_forces":
        from .military import union_army
        return float(union_army(w))
    return 0.0


def information_available_to(w, mid: str) -> list:
    """Every number this delegate could legitimately be citing: briefing + own reports."""
    from . import briefing as _briefing
    from . import intelligence as _intel
    sources = []
    try:
        sources.append({"label": "public briefing", "text": _briefing.public_v2(w, None)})
    except Exception:
        pass
    try:
        # The decision-phase view: own reports, and everything shared this month up to the vote.
        office_text = _intel.office_context(w, mid, "decision")
    except Exception:
        office_text = ""
    if office_text.strip():
        sources.append({"label": "your office reports", "text": office_text})
    try:
        intel_text = _intel.reports_for(w, mid)
    except Exception:
        intel_text = ""
    if not isinstance(intel_text, str):
        intel_text = ""
    if intel_text.strip() and intel_text.strip() != (office_text or "").strip():
        sources.append({"label": "shared intelligence", "text": intel_text})
    return sources


#: What a unit multiplies its figure by: a percentage is a fraction, "million" is 1e6.
_FIGURE_SCALE = {"%": 0.01, "million": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "thousand": 1e3, "k": 1e3}
#: The dash between the two bounds of a range: "40-60%", "1–25/100".
_RANGE_DASH = re.compile(r"^\s*[-" + chr(0x2010) + "-" + chr(0x2013) + r"]\s*$")
#: Words that number a label or a date, so the figure after them is not a statistic: "Month 19", "Article 1".
_LABEL_WORD = re.compile(r"\b(?:month|year|week|day|round|motion|article|clause|section|item|step|phase)s?\s*#?\s*$",
                         re.I)


def _is_label(text: str, pos: int) -> bool:
    """True when the figure at `pos` is part of an identifier or a date, not a figure. Engine 19: a figure directly
    after a letter ("D1", "M3", "CO2") or after a letter and a hyphen ("R1-ARM3") is part of an identifier, and so is
    one right after "Month" ("Month 19" is a date). A bare 1 read from "D1" was judged as 100%."""
    before = text[:pos]
    if before[-1:].isalpha():
        return True
    if before[-1:] in ("-", chr(0x2010), chr(0x2011)) and before[-2:-1].isalpha():
        return True
    return bool(_LABEL_WORD.search(before[-30:]))


def _numbers_in(text: str) -> list:
    """Every figure in a text, with where it sits, so it can be tied to the sentence that states it. A range ("40-60%")
    is one claim: its value is the high bound and "lo" the low bound, each with the unit that the range carries."""
    text = text or ""
    found = []
    for match in _GROUNDING_NUMBER.finditer(text):
        if _is_label(text, match.start(1)):
            continue
        raw, unit, noun = match.group(1), match.group(2) or "", match.group(3) or ""
        try:
            base = float(raw.replace(",", ""))
        except ValueError:
            continue
        spelled = re.sub(r"\s+", "", unit.lower())      # "/ 100" is spelled "/100"
        noun = noun.lower()
        unit = "%" if spelled in ("%", "percent", "percentage", "/100") else spelled
        found.append({"base": base, "value": base * _FIGURE_SCALE.get(unit, 1.0), "unit": unit, "noun": noun,
                      "start": match.start(1), "end": match.end(),
                      "unit_end": match.end(2) if match.group(2) else match.end(1),
                      "raw": " ".join(x for x in (raw, spelled, noun) if x).strip()})
    out = []
    for fig in found:
        prev = out[-1] if out else None
        if prev is not None and "lo" not in prev and _RANGE_DASH.match(text[prev["end"]:fig["start"]]):
            # "1–25/100" is 1% to 25%: the low bound "1" takes the high bound's unit, so it is not a bare 1 (100%).
            unit = fig["unit"] or prev["unit"]
            scale = _FIGURE_SCALE.get(unit, 1.0)
            lo_scale = _FIGURE_SCALE.get(prev["unit"], 1.0) if prev["unit"] else scale
            out[-1] = {**fig, "start": prev["start"], "unit": unit, "noun": fig["noun"] or prev["noun"],
                       "value": fig["base"] * scale, "lo": prev["base"] * lo_scale,
                       "raw": f'{prev["raw"]}-{fig["raw"]}'}
        else:
            out.append(fig)
    return out


_SOURCE_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|\u2013|to)\s*(\d+(?:\.\d+)?)\s*(%|/100)")
_SOURCE_SCALED = re.compile(r"(\d+(?:\.\d+)?)\s*(%|/100)")
# The words a source sentence must contain for its 0-100 figures to count for a metric.
_RATIO_CONTEXT = {
    "food_ratio": ("food", "grain"), "hunger": ("food", "grain", "hunger", "hungry"),
    "inflation": ("inflation", "prices"), "unemployment": ("unemploy", "jobless", "out of work"),
    "approval": ("approval", "popularity"), "unrest": ("unrest", "protest", "disorder", "riot"),
    "army_readiness": ("readiness", "morale", "loyalty"),
}


def _source_ratios(texts: list, words: tuple) -> list:
    """Figures sources state on a 0-100 scale ('58-72/100', '84-88%', '35%') in sentences about
    this metric, as ratio ranges. A figure elsewhere in the same briefing does not count."""
    out = []
    for text in texts:
        for sentence in re.split(r"\n|(?<=[.;])\s+", text or ""):
            low = sentence.lower()
            if not any(word in low for word in words):
                continue
            for a, b, _unit in _SOURCE_RANGE.findall(sentence):
                out.append(tuple(sorted((float(a) / 100, float(b) / 100))))
            for a, _unit in _SOURCE_SCALED.findall(sentence):
                out.append((float(a) / 100, float(a) / 100))
    return out


#: The troop specs. A figure in them is judged against the force it is about, not always our own (Audit MO4).
FORCE_KEYS = {"army_size": "ours", "union_forces": "union"}
#: The specs whose figure is a ratio. A bare figure beside their words is read as percentage points (Audit MO8).
RATIO_KEYS = ("food_ratio", "hunger", "inflation", "unemployment", "approval", "unrest", "army_readiness")
_SENTENCE_END = re.compile(r"[!?;\n]|\.(?!\d)")
_SIDE_OF_ACTOR = {SOLVARAN_UNION: "union", VELERIA: "union", DORSANIA: "union", MARITIME_LEAGUE: "league"}
_FOREIGN_FORCE_WORD = re.compile(r"\benem(?:y|ies)\b", re.I)
_OWN_SIDE_WORD = re.compile(r"\b(?:we|our|ours|us|karamaniya)\b", re.I)
_TROOP_WORD = re.compile(r"\b(?:soldiers?|troops?|men|army|forces?|under\s+arms|field\s+strength|manpower|"
                         r"enem(?:y|ies)|regiments?|divisions?|garrisons?)\b", re.I)
_TROOP_NOUNS = ("soldier", "soldiers", "troop", "troops")
#: A range of troop counts a source gives, as in "78,147-107,917 troops".
_SOURCE_COUNT_RANGE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*(?:-|–|to)\s*(\d{1,3}(?:,\d{3})+|\d+)\s*"
                                 r"(?:soldiers?|troops?|men)\b", re.I)


def _sentence_bounds(text: str, start: int, end: int) -> tuple:
    """The span of the sentence that holds [start, end). A decimal point does not end a sentence."""
    lo = 0
    for stop in _SENTENCE_END.finditer(text, 0, start):
        lo = stop.end()
    stop = _SENTENCE_END.search(text, end)
    return lo, (stop.start() if stop else len(text))


def _force_marks(w, text: str) -> list:
    """Where a text names a side, as (start, end, side). 'union' is the Solvaran Union, Veleria, Dorsania or the
    enemy; 'league' is the Maritime League; 'ours' is we, our, us and Karamaniya."""
    marks = []
    for actor, patterns in _actor_patterns(w).items():
        side = _SIDE_OF_ACTOR.get(actor)
        if side:
            marks += [(m.start(), m.end(), side) for p in patterns for m in re.finditer(p, text, re.I)]
    marks += [(m.start(), m.end(), "union") for m in _FOREIGN_FORCE_WORD.finditer(text)]
    marks += [(m.start(), m.end(), "ours") for m in _OWN_SIDE_WORD.finditer(text)]
    return marks


def _side_of(marks: list, text: str, start: int, end: int) -> str:
    """Whose force a figure at [start, end) is: the side named nearest to it in its own sentence. In "the Solvaran
    Union fields 95,000 troops against our 28,000", the 95,000 is the Union's and the 28,000 is ours."""
    lo, hi = _sentence_bounds(text, start, end)
    best, best_gap = "ours", None
    for s, e, side in marks:
        if s < lo or e > hi:
            continue
        gap = start - e if e <= start else s - end
        if best_gap is None or gap < best_gap:
            best, best_gap = side, gap
    return best


def _claim_side(marks: list, text: str, start: int, end: int, figures=()) -> str | None:
    """Whose force a claimed figure is (T144): the side named nearest to it in its own segment (see
    _segment_span). A segment that names no side takes ours, unless its sentence names another side: then the figure's
    side is not tied, and it is not judged. "Union 14 warships, ~106k troops vs our 59k": the 106k is not tied to a side.
    Source figures keep _side_of, the sentence reading."""
    lo, hi = _segment_span(text, start, end, figures)
    best, best_gap = None, None
    for s, e, side in marks:
        if s < lo or e > hi:
            continue
        gap = start - e if e <= start else s - end
        if best_gap is None or gap < best_gap:
            best, best_gap = side, gap
    if best is not None:
        return best
    sentence_lo, sentence_hi = _sentence_bounds(text, start, end)
    named = {side for s, e, side in marks if s >= sentence_lo and e <= sentence_hi}
    return None if named - {"ours"} else "ours"


#: Units that make a figure an amount of money, never a count of troops: "9-10M" beside "soldiers" is pay.
_MONEY_UNITS = ("million", "m", "billion", "bn")


def _is_troop_figure(text: str, claim: dict) -> bool:
    """A figure that counts troops: it has a troop noun, or no other noun while its sentence speaks of the army.
    "2,000,000 gold" beside "28,000 soldiers" is not one (Audit MO4). A figure in money units is never one."""
    if claim["unit"] in _MONEY_UNITS:
        return False
    if claim["noun"]:
        return claim["noun"] in _TROOP_NOUNS
    lo, hi = _sentence_bounds(text, claim["start"], claim["end"])
    return bool(_TROOP_WORD.search(text[lo:hi]))


def _keys_naming(hits: list, text: str, claim: dict) -> frozenset:
    """The specs whose words name the figure's own sentence. A figure is judged only against the metrics its own
    sentence names: in a quoted cable the reading "(75/100)" is Veleria's, not unrest's, even when a later clause of
    the same quote mentions protests. Empty when the sentence names none, so the whole text decides as before."""
    lo, hi = _sentence_bounds(text, claim["start"], claim["end"])
    sentence = text[lo:hi].lower()
    return frozenset(key for key, keywords, *_rest in hits if any(word in sentence for word in keywords))


def _sentences(text: str) -> list:
    return [s for s in re.split(r"\n|(?<=[.;])\s+", text or "") if s.strip()]


def _metric_words(key: str, keywords: tuple) -> tuple:
    """The words that make a source sentence one about this metric: the spec's own keywords and its ratio context."""
    return tuple(dict.fromkeys(tuple(keywords) + _RATIO_CONTEXT.get(key, ())))


#: What follows a bare figure that makes it a count or a change rather than a level: "5 points", "12 respondents".
_COUNT_AFTER = re.compile(r"\s*(?:points?|pts?\b|people|persons?|respondents?|months?|years?|weeks?|days?|times|"
                          r"votes?|seats?|ministr\w*|provinces?|regions?|districts?|members?|delegates?|men\b|"
                          r"soldiers?|troops?|ships?|vessels?|units?|tonnes?|tons?|hectares?|workers?|households?|"
                          r"families|cities|towns|villages|quarters?)\b", re.I)
#: What comes just before one: "rose by 3", "in 3 provinces", "Month 12".
_COUNT_BEFORE = re.compile(r"\b(?:by|among|across|in|for|from|with|per|month|year|week|day|round|motion|clause|"
                           r"seat|step|item|section|article|no)\.?\s*$", re.I)


def _metric_before(prefix: str) -> frozenset:
    """The specs whose words come last in `prefix`, the clause before a figure: in "unrest and approval are 40" the 40
    is approval's. Specs whose words end in the same place ("food shortage" is both food coverage and hunger) all count."""
    low = prefix.lower()
    best_end, keys = -1, set()
    for key, keywords, *_rest in GROUNDING_SPECS:
        for word in keywords:
            start = low.rfind(word)
            if start < 0:
                continue
            if start + len(word) > best_end:
                best_end, keys = start + len(word), {key}
            elif start + len(word) == best_end:
                keys.add(key)
    return frozenset(keys)


def _metric_after(suffix: str) -> frozenset:
    """The specs whose words come first in `suffix`, the clause after a figure. It is used only when no spec is named
    before the figure in its clause: "Inflation: 9%" has no spec before the 9 in its clause, but one after it."""
    low = suffix.lower()
    best_start, keys = None, set()
    for key, keywords, *_rest in GROUNDING_SPECS:
        for word in keywords:
            start = low.find(word)
            if start < 0:
                continue
            if best_start is None or start < best_start:
                best_start, keys = start, {key}
            elif start == best_start:
                keys.add(key)
    return frozenset(keys)


#: Where a clause ends: a semicolon, colon, comma or bracket, or a sentence end (a decimal point is not one).
_CLAUSE_BREAK = re.compile(r"[;:,()!?\n]|\.(?!\d)")


def _clause_span(text: str, start: int, end: int) -> tuple:
    """The clause that holds the figure at [start, end): from the last clause break before it to the next one after it."""
    lo, hi = 0, len(text)
    for stop in _CLAUSE_BREAK.finditer(text):
        if stop.end() <= start:
            lo = stop.end()
        elif stop.start() >= end:
            hi = stop.start()
            break
    return lo, hi


#: The breaks a figure's metric cannot be tied across: a clause break, or a comparison that sets two figures against
#: each other. In "Fleet readiness 53-65/100 vs 13-16 Union warships" the 13-16 is not the readiness figure (T144).
_SEGMENT_BREAK = re.compile(_CLAUSE_BREAK.pattern + r"|\b(?:vs\.?|versus|against|compared\s+(?:with|to))\b", re.I)


def _segment_span(text: str, start: int, end: int, figures=()) -> tuple:
    """The text a figure at [start, end) may be tied to (T144): from the nearest clause break or comparison, or
    the neighbouring figure, on each side. A metric outside it is not this figure's metric."""
    lo, hi = 0, len(text)
    for stop in _SEGMENT_BREAK.finditer(text):
        if stop.end() <= start:
            lo = stop.end()
        elif stop.start() >= end:
            hi = stop.start()
            break
    for other in figures:
        if other["end"] <= start:
            lo = max(lo, other["end"])
        elif other["start"] >= end:
            hi = min(hi, other["start"])
    return lo, hi


def _owners(text: str, claim: dict, sentence_keys: frozenset, figures=()) -> frozenset:
    """The metric a figure is judged against (engine 19, tied locally for T144): the metric its own segment names,
    the nearest before it, else the nearest after it. A segment that names none ties the figure to nothing, and the figure
    is unverifiable, not judged. The sentence does not decide it: "Economy: output 82, unemployment 10%" does not make the
    82 an unemployment figure, and "Army actual 36.5k vs Union 98k" does not tie the 36.5k to the Union's force (T144)."""
    if not sentence_keys:
        return frozenset()
    lo, hi = _segment_span(text, claim["start"], claim["end"], figures)
    keys = _metric_before(text[lo:claim["start"]]) & sentence_keys
    return keys or (_metric_after(text[claim["end"]:hi]) & sentence_keys)


def _as_percent_points(text: str, claim: dict, key: str) -> dict:
    """A bare figure from 1.5 to 100 that is about a ratio metric is percentage points: "Approval is 95" is 95%, as an
    approval threshold already reads (Audit MO8). Counts, changes and identifiers keep their face value."""
    value = claim["value"]
    if claim["unit"] or claim["noun"] or not 1.5 < value <= 100:
        return claim
    before = text[max(0, claim["start"] - 15):claim["start"]]
    if before[-1:].isalpha() or before[-1:] == "#" or _COUNT_BEFORE.search(before) \
            or _COUNT_AFTER.match(text[claim["end"]:claim["end"] + 30]):
        return claim
    if key not in claim["owners"]:
        return claim
    return {**claim, "value": value / 100, "unit": "%", "raw": claim["raw"] + "%",
            **({"lo": claim["lo"] / 100} if "lo" in claim else {})}


def _source_figures(w, texts: list, words: tuple) -> list:
    """The figures a source states about one metric, as (figure, side). A figure counts only in a sentence about the
    metric: a food figure does not support a claim about inflation (Audit MO7). The side says whose force a troop
    figure is about (Audit MO4)."""
    out = []
    for text in texts:
        for sentence in _sentences(text):
            if not any(word in sentence.lower() for word in words):
                continue
            marks = _force_marks(w, sentence)
            for fig in _numbers_in(sentence):
                out.append((fig, _side_of(marks, sentence, fig["start"], fig["end"])))
    return out


def _source_count_ranges(w, texts: list, side: str) -> list:
    """The troop ranges a source gives for one side. A figure inside the range the holder's reports gave is
    grounded (Audit MO4)."""
    out = []
    for text in texts:
        for sentence in _sentences(text):
            if not _SOURCE_COUNT_RANGE.search(sentence):
                continue
            marks = _force_marks(w, sentence)
            for m in _SOURCE_COUNT_RANGE.finditer(sentence):
                if _side_of(marks, sentence, m.start(), m.end()) == side:
                    a, b = (float(g.replace(",", "")) for g in m.groups())
                    out.append((min(a, b), max(a, b)))
    return out


# ---- which figures are claims (engine 19): a statistic the text states as a fact about the state -------------
# A figure a motion proposes, requests, pays, allocates or borrows is an amount, not a statement of where the state
# stands. So is a threshold or condition on the state, a setting the motion sets, a change, and a figure whose own
# noun names a quantity no spec checks (a deficit, a bill, a loan). Those are left alone. What remains is judged:
# "Our reserves stand at 20,000,000 gold", "Inflation is 40%", "Unemployment has reached 9%".
_CLAUSE_END = ";!?\n"


def _is_decimal_point(text: str, i: int) -> bool:
    return 0 < i < len(text) - 1 and text[i - 1].isdigit() and text[i + 1].isdigit()


def _clause_before(text: str, pos: int) -> str:
    """The clause that holds `pos`, up to `pos`. A clause ends at a sentence end or at a comma outside brackets, so
    "Pay half of the bills (about 24M crowns, so ~12M gold)" is one clause for both figures."""
    start, depth = 0, 0
    for i, ch in enumerate(text[:pos]):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch in _CLAUSE_END or (ch == "." and not _is_decimal_point(text, i)):
            start, depth = i + 1, 0
        elif ch == "," and depth == 0:
            start = i + 1
    return text[start:pos]


#: What a motion does with an amount, as a verb: it pays, settles, requests, borrows, allocates, transfers or releases
#: it. A verb counts anywhere in the clause before the figure ("Pay half of the arrears (about 10M crowns)").
_AMOUNT_VERB = re.compile(
    r"\b(?:paid|pays?|paying|repaid|repays?|repaying|settled|settles?|settling|cleared|clears?|clearing|"
    r"requested|requests?|requesting|proposed|proposes?|authori[sz](?:e|es|ed)|approved|approves?|renewed|renews?|"
    r"pledged|pledges?|borrowed|borrows?|borrowing|lent|lends?|allocated|allocates?|allocate|reallocated|reallocates?|"
    r"spent|spends?|issued|issuing|transferred|transfers?|released|releases?|funded|funding|invested|invests?|"
    r"donated|donates?|earmarked|earmarks?|diverted|diverts?|bought|buys?|purchased|purchases?|sold|sells?|drawn)\b",
    re.I)
#: The verb or noun that opens an amount's clause: "Pay half of", "Funded 4M by", "Relief for Lissen Coast: 8M".
_AMOUNT_OPENER = re.compile(
    r"^\s*(?:pay|settle|request|propose|authori[sz]e|approve|renew|pledge|borrow|lend|allocate|reallocate|spend|issue|"
    r"transfer|release|fund|repair|clear|repay|invest|donate|earmark|divert|buy|purchase|sell|extend|grant|draw|"
    r"paid|settled|requested|proposed|authori[sz]ed|approved|renewed|pledged|borrowed|lent|allocated|reallocated|"
    r"spent|issued|transferred|released|funded|repaired|repaid|invested|donated|earmarked|diverted|bought|purchased|"
    r"sold|drawn)\b", re.I)
_AMOUNT_TITLE = re.compile(r"^\s*(?:relief|tranche|loan|credit|grant|repair|package|arrangement|renewal|facility|"
                           r"standby|reallocation|allocation|payment|repayment|settlement|purchase|aid)\s+"
                           r"(?:for|of|to|up|:)\b", re.I)
#: The noun that an amount hangs on, as the last content word before it: "a loan of 40M", "first tranche 10M".
_AMOUNT_NOUN = re.compile(r"^(?:loans?|credits?|tranches?|relief|repairs?|grants?|aid|subsid(?:y|ies)|packages?|"
                          r"arrangements?|facility|standby|reallocation|allocations?|payments?|repayments?|"
                          r"settlements?|purchases?|pool|chest|proposals?)$", re.I)
_FUNCTION_WORDS = frozenset({"of", "for", "a", "an", "the", "at", "to", "up", "about", "roughly", "around", "some",
                             "approximately", "just"})
#: "the budget of 20M", "cost 12M": an amount named by its budget or cost.
_AMOUNT_BEFORE_END = re.compile(r"\b(?:costs?|budget(?:ed|s)?)\s*(?:of\s+|for\s+)?$", re.I)
#: "a package of 10M for ports": an amount for a purpose.
_OF_AMOUNT_FOR = re.compile(r"\bof\s*$", re.I)
_FOR_AFTER = re.compile(r"\s*for\b", re.I)
#: "the target of 9%", "aims to hold 5%", "before we reach 80M", "to reach 80M": a target the text sets. A forecast ("will
#: reach 50% next month") is not a target: it states a level the state is expected to have, and is checked.
_TARGET_WORDS = re.compile(r"\b(?:targets?|targeted|targeting|aims?|aimed|aiming|goals?|objectives?|"
                           r"(?:to|before|until|by|we|they|can|could|may|might)\s+reach(?:ing)?)\b", re.I)


def _amount_noun_before(before: str) -> bool:
    """True when the last content word before the figure is an amount's noun. Function words are skipped, so "a loan of"
    and "first tranche" count, while "credit is" (a subject, the figure's verb after it) does not."""
    for word in reversed(re.findall(r"[A-Za-z][A-Za-z-]*", before)):
        if word.lower() in _FUNCTION_WORDS:
            continue
        return bool(_AMOUNT_NOUN.match(word))
    return False


_CLAUSE_CONDITION = re.compile(r"\b(?:only\s+if|provided(?:\s+that)?|unless|until|if|whenever)\b", re.I)
_TIMED_CONDITION = re.compile(r"\b(?:before|after)\b", re.I)
#: A past tense in the clause: "before the crisis, reserves were 80M" states the past, so "before" does not condition it.
_PAST_IN_CLAUSE = re.compile(r"\b(?:was|were|had|did|fell|fallen|rose|risen|climbed|stood|reached|hit|ended|went|came|"
                             r"has\s+been|have\s+been|had\s+been)\b", re.I)
_COMPARATOR = re.compile(r"\b(?:at\s+least|at\s+most|(?:no|not)\s+(?:more|less)\s+than|up\s+to|above|below|over|under|"
                         r"exceed\w*|minimum|maximum|floor|ceiling|cap|capped|limit|limits|threshold|remains?|keeps?)\b",
                         re.I)
#: The words that make a comparison a statement of where the state is ("is over 9%", "fell below 15M").
_STATE_BEFORE_COMPARATOR = re.compile(r"\b(?:is|are|am|was|were|stands?|stood|sits?|been|fell|fallen|rose|risen|"
                                      r"dropped|dipped|slipped|sank|climbed|reached|hit|ended|went|came)\s*$", re.I)
_MODAL_BEFORE_BE = re.compile(r"\b(?:will|would|must|shall|should|can|could|may|might|to|need|needs)\s+be\s*$", re.I)
#: A rise, fall or change: "a rise of 1 percentage point", "fell by 20M". It is a change, not a level.
_CHANGE_BEFORE = re.compile(r"(?:\bby|\b(?:rises?|risen|increases?|increased|decreases?|decreased|falls?|fallen|"
                            r"drops?|dropped|cuts?|reductions?|gains?|jumps?|slides?|hikes?|growth|declines?)\s+"
                            r"(?:of|by))\s*$", re.I)
_CHANGE_AFTER = re.compile(r"^\s*(?:percentage\s+)?points?\b|^\s*pts?\b", re.I)
#: Quantities no spec checks, when they follow the figure: "a 33M/month structural deficit", "a 24M bill".
_AFTER_QUANTITY = (r"deficits?|bills?|loans?|tranch\w*|payments?|repairs?|relief|credits?|grants?|budgets?|spending|"
                   r"revenues?|debts?|wages?|payrolls?|bonds?|lines?|funds?|allocations?|subsid(?:y|ies)|aid|transfers?|"
                   r"expenditures?|outlays?|income|surpluses|surplus|arrangements?|facilit(?:y|ies)|standby|packages?|"
                   r"programmes?|programs?|schemes?|contracts?|tenders?|investments?|purchases?|pool|insurance|imports?|"
                   r"exports?|sales?|taxes|losses")
#: Participles that make a figure a past amount: "the 8 million already spent".
# Engine 19: a passive may put its auxiliary before the participle ("only 9.6M was paid of 142.5M requested"), so the
# auxiliary is optional. "paid", "spent", "transferred" and "released" were already amounts; "was paid" was not seen.
_AFTER_AMOUNT = (r"(?:(?:was|were|been|being|had\s+been|has\s+been|have\s+been)\s+)?"
                 r"(?:spent|paid|disbursed|allocated|committed|drawn|borrowed|lent|issued|granted|released|transferred|"
                 r"used|raised|received|collected|lost|saved|printed|earmarked|diverted|repaid)")
_AFTER_SKIP = (r"(?:/\s*(?:month|year|week|day)s?|(?:per|a|each|every)\s+(?:month|year|week|day)|"
               r"monthly|annual(?:ly)?|yearly|weekly|daily|structural|recurring|extra|additional|further|new|total|net|"
               r"gross|current|outstanding|remaining|one-off|single|initial|first|second|third|last|next|already|"
               r"unpaid|so\s+far|in\s+total|altogether)\b")
_FLOW_AFTER = re.compile(rf"^(?:\s*{_AFTER_SKIP})*\s*(?:{_AFTER_QUANTITY}|{_AFTER_AMOUNT})\b", re.I)


#: Words a setting may carry between the lever's name and its value: "tax share of output to 0.27", "police line 0.015".
_SETTING_WORDS = r"(?:share|of|output|line|level|rate|setting|value|ratio|cap|unchanged|held|kept|steady|from|by)"
_SETTING_TARGET = r"(?:to|at|=|->|→|from|held|kept|unchanged|steady)"
#: The metric words that take "rate" as a statistic, not a lever: "unemployment rate 9%" is a state, not a setting.
_NOT_A_LEVER_RATE = (r"(?<!employment\s)(?<!inflation\s)(?<!exchange\s)(?<!growth\s)(?<!approval\s)(?<!birth\s)"
                     r"(?<!death\s)")
_SETTING = None


def _setting_patterns():
    """Two readings of a lever's setting, as regexes over the clause before a figure. Lever names are those in
    politics.LEVER_OFFICE and their aliases; imported here, since politics imports this module's neighbours.
    marked: the lever set `to`, `at`, `=` or `from` a figure ("raise tax to 0.20", "rate from 6% to 7%").
    bare:   the lever named just before a share figure ("tax 0.24, welfare 0.045")."""
    global _SETTING
    if _SETTING is None:
        from .politics import LEVER_ALIASES, LEVER_OFFICE
        names = sorted(set(LEVER_OFFICE) | set(LEVER_ALIASES), key=len, reverse=True)
        parts = [(_NOT_A_LEVER_RATE if name == "rate" else "") + name.replace("_", r"[\s_-]+") for name in names]
        lever = "|".join(parts)
        marked = re.compile(rf"\b(?:{lever})(?:\s+{_SETTING_WORDS})*(?:\s+[\d][\d.,]*\s*(?:%|percent|points?|pts?)?)?"
                            rf"\s*{_SETTING_TARGET}\s*(?:about\s+|roughly\s+|around\s+|the\s+|~|≈)?$", re.I)
        bare = re.compile(rf"\b(?:{lever})(?:\s+{_SETTING_WORDS})*\s*$", re.I)
        _SETTING = (marked, bare)
    return _SETTING


def _setting_before(before: str, claim: dict | None = None) -> bool:
    """True when the figure is a lever's setting, not a statistic of the state. A share figure (a percentage, or a
    decimal up to 1.5) named just after a lever is its setting too."""
    marked, bare = _setting_patterns()
    if marked.search(before):
        return True
    share = claim is not None and (claim["unit"] == "%" or (not claim["unit"] and not claim["noun"]
                                                            and 0 < claim["value"] <= 1.5))
    return share and bool(bare.search(before))


def _comparison_is_threshold(before: str) -> bool:
    """A comparison that sets a floor, cap or condition: "remain above the 80M floor", "will be at least 70M",
    "to reach 80M". A comparison that states where the state is ("is over 9%", "fell below 15M") is not one."""
    window = before[-45:]
    for m in _COMPARATOR.finditer(window):
        prior = window[:m.start()]
        if _MODAL_BEFORE_BE.search(prior) or not _STATE_BEFORE_COMPARATOR.search(prior):
            return True
    return False


#: A conjunction or colon that joins a state to the amount before it: "We paid 10M and reserves stand at 20M gold",
#: "Settled arrears: reserves stand at 20M". A colon that titles an amount ("Port Aster repair: 8M") is not followed by a
#: state verb, so it stays part of the amount's clause.
_CONJUNCTION = re.compile(r"\b(?:and|but|while|whereas|yet)\b|:", re.I)
_STATE_VERB = re.compile(r"\b(?:is|are|am|was|were|stands?|stood|sits?|has|have|had|reached|fell|fallen|rose|risen|"
                         r"climbed|dropped|hit|sank|slipped|remains?|remained|stays?|stayed|shows?|showed)\b", re.I)


def _figure_clause(before: str) -> str:
    """The clause of a figure, from the clause text before it: after the last conjunction that a state verb follows.
    "Pay 10M and 6M" is one list of amounts; "paid 10M and reserves stand at" is a payment and then a state."""
    joints = list(_CONJUNCTION.finditer(before))
    if joints and _STATE_VERB.search(before[joints[-1].end():]):
        return before[joints[-1].end():]
    return before


#: T144: a threshold, a projection or an accrual next to a figure. See _states_a_fact.
_THRESHOLD_WORD = re.compile(r"\b(?:floors?|ceilings?|minimums?|maximums?|caps?|limits?|thresholds?|triggers?)\b", re.I)
_PROJECTED_BEFORE = re.compile(r"(?:->|→|=>)\s*~?\s*$")
_ACCRUAL_AFTER = re.compile(r"^\s*(?:still\s+|also\s+|further\s+|additional\s+)?"
                            r"(?:accrues?|accrued|accruing|accrual|accumulates?|accumulated|accumulating)\b", re.I)
#: A rate right after the figure: "46M monthly", "2M a month", "3M per year". A drain or a cost per period is a flow.
_RATE_AFTER = re.compile(r"^\s*(?:/\s*(?:month|year|week|day)s?|(?:per|a|each|every)\s+(?:month|year|week|day)|"
                         r"monthly|annual(?:ly)?|yearly|weekly|daily)\b", re.I)


def _threshold_after(text: str, claim: dict) -> bool:
    """A threshold word within the two words that follow the figure in its clause: "a 60M floor", "9% cap". The figure's
    match takes the space after it, so the words are read from the text, not from a leading space."""
    _lo, hi = _clause_span(text, claim["start"], claim["end"])
    words = re.findall(r"[\w'-]+", text[claim["end"]:hi])[:2]
    return bool(_THRESHOLD_WORD.search(" ".join(words)))


def _states_a_fact(text: str, claim: dict) -> bool:
    """True when the figure is a statistic the text states as a fact about the current or past state. False when the
    figure is an amount the text proposes, requests, pays, allocates or borrows; a threshold, floor, cap or condition;
    a setting the text sets; a change; a projection; an accrual; or a figure whose noun names a quantity no spec checks."""
    before = _figure_clause(_clause_before(text, claim["start"]))
    # The text after the figure's unit, so the noun the figure carries ("40M deficit") is read as the noun it is.
    after = text[claim["unit_end"]:claim["end"] + 60]
    if _AMOUNT_VERB.search(before) or _AMOUNT_OPENER.match(before) or _AMOUNT_TITLE.match(before):
        return False
    if _amount_noun_before(before) or _AMOUNT_BEFORE_END.search(before):
        return False
    if _OF_AMOUNT_FOR.search(before) and _FOR_AFTER.match(after):
        return False
    if _TARGET_WORDS.search(before):
        return False
    if _CLAUSE_CONDITION.search(before) or (_TIMED_CONDITION.search(before) and not _PAST_IN_CLAUSE.search(before)):
        return False
    if _setting_before(before, claim) or _comparison_is_threshold(before):
        return False
    if _CHANGE_BEFORE.search(before) or _CHANGE_AFTER.match(after):
        return False
    if (_threshold_after(text, claim) or _PROJECTED_BEFORE.search(before) or _ACCRUAL_AFTER.match(after)
            or _RATE_AFTER.match(after)):
        return False
    return not _FLOW_AFTER.match(after)


def check_numeric_grounding(w, mid: str, text: str, unverifiable: list | None = None) -> dict | None:
    """A precise statistic with no available source is sent back, not silently kept.

    T144: a figure is judged only when its own segment ties it to one metric, and to one side for a troop
    figure. A figure that cannot be tied is unverifiable, not an error: it is not flagged, and it is appended to
    `unverifiable` when the caller passes a list (the replay audit counts those; the month record keeps flags only)."""
    if not text or not text.strip():
        return None
    lowered = text.lower()
    hits = [spec for spec in GROUNDING_SPECS if any(p in lowered for p in spec[1])]
    if not hits:
        return None
    # Engine 19 claim test: a figure the text proposes, pays, thresholds, sets, changes or counts in another quantity is
    # not a statement of the state, and is not checked against it (see _states_a_fact).
    numbers = [claim for claim in _numbers_in(text) if _states_a_fact(text, claim)]
    if not numbers:
        return None
    # Every figure in the text, claim or not, bounds the segment of its neighbours (see _segment_span).
    figures = _numbers_in(text)
    # Audit MO5: an opinion word ("alarming", "weak") used to switch the check off when no figure had a noun
    # ("Inflation of 9% is alarming" passed at 0%). A stated figure is always checked; with no figure there is
    # nothing to check, which the early return above already covers.
    marks = _force_marks(w, text)
    for claim in numbers:
        claim["side"] = _claim_side(marks, text, claim["start"], claim["end"], figures)
    # Audit MO4: a troop figure about the Union is checked against the Union's force even when no Union keyword
    # is in the text: "The Solvaran Union has 95000 soldiers" names soldiers, and only the army spec would match.
    if not any(spec[0] == "union_forces" for spec in hits) and any(
            c["side"] == "union" and _is_troop_figure(text, c) for c in numbers):
        hits.append(next(spec for spec in GROUNDING_SPECS if spec[0] == "union_forces"))
    for claim in numbers:
        claim["owners"] = _owners(text, claim, _keys_naming(hits, text, claim), figures)
        # A Union troop figure whose sentence names no metric is about the Union's force (Audit MO4). Its side is
        # tied (above), so the figure is the Union's only when its own segment names the Union.
        if not claim["owners"] and claim["side"] == "union" and _is_troop_figure(text, claim):
            claim["owners"] = frozenset({"union_forces"})
        if not claim["owners"] and unverifiable is not None:
            unverifiable.append({"raw": claim["raw"], "value": claim["value"], "start": claim["start"]})
    sources = information_available_to(w, mid)
    source_texts = [src["text"] for src in sources]
    shortage_talk = any(word in lowered for word in ("shortage", "shortfall", "short of food"))
    for key, patterns, _truth_key, tol in hits:
        try:
            truth = float(_grounding_truth(w, key))
        except Exception:
            continue
        band = max(tol["abs"], abs(truth) * tol["rel"])
        words = _metric_words(key, patterns)
        figures = _source_figures(w, source_texts, words)
        side = FORCE_KEYS.get(key)
        counts = _source_count_ranges(w, source_texts, side) if side else []
        ranges = _source_ratios(source_texts, words) if key in RATIO_KEYS else []
        for raw_claim in numbers:
            # A figure is judged only against the metric it is about (its owners, see _owners).
            if key not in raw_claim["owners"]:
                continue
            claim = _as_percent_points(text, raw_claim, key) if key in RATIO_KEYS else raw_claim
            value = claim["value"]
            money = value >= 1e3 or claim["unit"] in ("million", "m", "billion", "bn", "thousand", "k")
            ratio = (not money and value <= 1.5) or claim["unit"] in ("%", "percent", "percentage")
            if key in ("reserves", "arrears") and not money:
                continue
            # A troop figure is judged only against the force it is about; a figure about the other side is not ours to check.
            if side and (ratio or value < 100 or claim["side"] != side or not _is_troop_figure(text, claim)):
                continue
            if key in RATIO_KEYS and not ratio:
                continue
            # A range is grounded when the truth lies inside it, within the band; a single figure is the range of one.
            low_bound, high_bound = min(claim.get("lo", value), value), max(claim.get("lo", value), value)
            if low_bound - band <= truth <= high_bound + band:
                continue
            shortage = ratio and key in ("food_ratio", "hunger") and (
                shortage_talk or claim["noun"] in ("shortage", "shortfall"))
            if shortage and abs(value - max(0.0, 1 - float(w.econ.food_ratio))) <= max(.03, band * .5):
                continue        # a shortage stated as what coverage falls short of 100%
            supported = any(claim["unit"] == fig["unit"] and abs(value - fig["value"]) <= max(band * 0.5, 1e-9)
                            and (side is None or owner == side) for fig, owner in figures)
            if ratio and not supported:
                slack = max(band * 0.5, .01)
                values = [value] + ([1 - value] if shortage else [])
                supported = any(lo - slack <= v <= hi + slack for v in values for lo, hi in ranges)
            if side and not supported:
                supported = any(lo <= value <= hi for lo, hi in counts)
            if supported:
                continue
            hunger_now = _grounding_truth(w, "hunger")
            if key in ("hunger", "food_ratio") and claim["noun"] in ("shortage", "shortfall"):
                repair = (f"Your available reports show food coverage near {w.econ.food_ratio:.0%} "
                          f"and hunger near {hunger_now:.1%}. "
                          f"No source available to you supports a {claim['raw']} food shortage. "
                          f"Correct the figure or identify the report you are relying on.")
            else:
                labels = {"food_ratio": f"food coverage near {truth:.0%}",
                          "hunger": f"hunger near {truth:.1%}",
                          "inflation": f"inflation near {truth:.1%}",
                          "reserves": f"reserves near {truth:,.0f}",
                          "arrears": f"unpaid bills near {truth:,.0f}",
                          "unemployment": f"unemployment near {truth:.1%}",
                          "approval": f"approval near {truth:.0%}",
                          "unrest": f"unrest near {truth:.0%}",
                          "army_size": f"army strength near {truth:,.0f}",
                          "army_readiness": f"readiness near {truth:.0%}",
                          "union_forces": f"Union forces near {truth:,.0f}"}.get(key, str(truth))
                repair = (f"Your available reports show {labels}. "
                          f"No source available to you supports '{claim['raw']}'. "
                          f"Correct the figure or identify the report you are relying on.")
            return {"code": "NUMERIC_GROUNDING_ERROR", "metric": key, "claimed": claim["value"],
                    "observed": truth, "claim_text": claim["raw"],
                    "sources": [s["label"] for s in sources],
                    "detail": f"unsupported numeric claim about {key}: '{claim['raw']}'",
                    "repair": repair}
    return None


# ---- execution --------------------------------------------------------------------------------------
def execution_key(w, motion: dict) -> str:
    """A semantic key for one action, used to stop the same act being sent twice in a cycle.

    Two motions that ask for the same thing to the same actor produce the same key; two genuinely
    different diplomatic actions, even aimed at the same country, do not. A programme is the measures
    it sets, so its words do not change its key.
    """
    action = structured_action(w, motion)
    payload = {"action_type": action["action_type"], "target": action.get("target"),
               "policy": action.get("policy"), "value": str(action.get("value") or ""),
               "issue": _normalise(action.get("issue") or ""), "month": int(getattr(w, "month", 0))}
    if action["action_type"] == "charter_amendment":
        payload["text"] = _normalise(action.get("text") or "")[:400]
    # Audit MO21: a diplomatic act that names no issue is told apart by its words. Without them, two protests to one
    # power about different things, in one month, were one act, and the second was refused as a duplicate.
    if action["kind"] == "diplomacy" and not payload["issue"]:
        payload["text"] = _normalise(motion.get("text") or "")
    # T136: the key ignored a programme's measures, so two programmes with empty values were one act and the second was
    # refused as a duplicate of the first (run 20261011-211521-seed1, month index 4). A programme is the same act when it
    # sets the same measures: the canonical payload the tabling check uses (deliberation._program_measure_key).
    if action["kind"] == "program":
        from .deliberation import _program_measure_key
        payload = {"action_type": "program", "month": payload["month"],
                   "measures": [list(pair) for pair in _program_measure_key(w, motion)]}
    # Wave 3: a media campaign is the line it sets, so two campaigns differ by their kinds, claims and
    # intensity rather than sharing the empty subject/value every media motion carries.
    if action["kind"] == "media_campaign":
        payload = {"action_type": "media_campaign", "month": payload["month"],
                   "kinds": sorted(action.get("kinds") or []),
                   "claims": [[str(c.get("metric")), str(c.get("value"))] for c in action.get("claims") or []],
                   "intensity": str(action.get("intensity") or "")}
    # Wave A (engine 30, W3): a policy is the canonical items it carries, so its label and wording do not
    # change its key, and re-tabling the same items in another order is the same motion (W2's key beside
    # the month, the programme branch's shape).
    if action["kind"] == "policy":
        from .deliberation import _policy_measure_key
        payload = {"action_type": "policy", "month": payload["month"],
                   "items": list(_policy_measure_key(w, motion))}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _normalise(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text).casefold()))


def _policy_conflict(items: list) -> dict | None:
    """A policy whose own items contradict each other, or a spending item the reader left incomplete.

    Wave A (engine 30, W3). Two set_lever items on one setting name two values for it; a set_lever item and
    a funding cut on the same setting mean the policy both raises and lowers that line. Neither can be
    carried out as written, so the motion is blocked rather than resolved by item order.
    """
    from . import actions
    if not items:
        return {"code": "POLICY_LIMIT", "detail": "the policy carries no item the engine could read"}
    set_levers = [str(entry.get("lever")) for entry in items
                  if entry.get("instrument") == "set_lever"]
    duplicates = sorted({lever for lever in set_levers if set_levers.count(lever) > 1})
    if duplicates:
        return {"code": "POLICY_LIMIT",
                "detail": (f"the policy sets {', '.join(duplicates)} more than once; one policy may not "
                           "name two values for the same setting")}
    cuts = {str(entry.get("funding"))[len("cut:"):] for entry in items
            if str(entry.get("funding") or "").startswith("cut:")}
    clash = sorted(set(set_levers) & cuts)
    if clash:
        return {"code": "POLICY_LIMIT",
                "detail": (f"the policy sets {', '.join(clash)} and also funds spending by cutting it; "
                           "one policy may not both set a setting and cut it")}
    missing = [entry for entry in items if entry.get("instrument") in actions.POLICY_SPENDING
               and (not entry.get("amount") or not entry.get("funding"))]
    if missing:
        return {"code": "POLICY_UNFUNDED",
                "detail": "a spending item reached the council without an amount or a funding source"}
    return None


def validate_execution(w, motion: dict, executed: dict | None = None) -> dict | None:
    """Everything that must hold before a motion is allowed to change canonical state.

    Returns None when the motion may execute, or {code, detail} saying why it may not. A refusal
    here must never be worked around by guessing what the delegate meant. Binding execution
    conditions are evaluated last, against current canonical state: a conditional motion that
    carried politically but whose floor is not met returns EXECUTION_BLOCKED_CONDITION with
    per-condition results, never a silent unconditional run.
    """
    if not isinstance(motion, dict):
        return {"code": "NO_STRUCTURED_ACTION", "detail": "the motion record must be an object"}
    status = str(motion.get("status") or "")
    if status in ("WITHDRAWN", "SUPERSEDED"):
        return {"code": "MOTION_WITHDRAWN", "detail": "the proposer withdrew this motion; it cannot execute"}
    if status in ("DEFERRED", "AGENDA_BLOCKED", "LAPSED"):
        return {"code": "MOTION_NOT_HEARD", "detail": f"the council never reached this motion ({status})"}
    if motion.get("void"):
        return {"code": "SESSION_VOID", "detail": "the session was ended by force; nothing it passed is executed"}
    if not motion.get("passed"):
        return {"code": "NOT_PASSED", "detail": "the motion did not carry"}
    if str(motion.get("type", "")).strip() == "policy":
        # Wave A (engine 30, W3): a policy's gates are per item and monthly (policy.monthly evaluates each
        # item's condition at the start of the month), so a condition written in the prose is a description
        # of the policy, not a motion-level gate. The motion is blocked here only when its own items
        # contradict each other, and the duplicate key is the canonical items (W2's key).
        from . import actions
        conflict = _policy_conflict(actions.policy_items_of(w, motion))
        if conflict:
            return conflict
        if executed is not None:
            key = execution_key(w, motion)
            if key in executed:
                return {"code": "DUPLICATE_ACTION", "detail": "an equivalent action already executed this month",
                        "duplicate_of": executed[key]}
        return None
    mismatch = condition_mismatch(w, motion)
    if mismatch:
        return {**mismatch, "condition_results": [],
                "blocking_reason": mismatch["detail"]}
    action = structured_action(w, motion)
    if not action.get("action_type"):
        return {"code": "NO_STRUCTURED_ACTION", "detail": "the motion carries no executable action"}
    if action["kind"] == "diplomacy":
        problem = validate_diplomatic_action(w, motion)
        if problem:
            return problem
    if executed is not None:
        key = execution_key(w, motion)
        if key in executed:
            return {"code": "DUPLICATE_ACTION", "detail": "an equivalent action already executed this month",
                    "duplicate_of": executed[key]}
    conditions = motion_conditions(motion)
    if conditions:
        results = evaluate_conditions(w, conditions, motion)
        failed = [r for r in results if not r.get("met")]
        if failed:
            first = failed[0]
            return {"code": "EXECUTION_BLOCKED_CONDITION",
                    "detail": (f"Council vote: PASSED_CONDITIONALLY. Reason execution paused: "
                               f"{first.get('reason') or (first['metric'] + ' not met')}"),
                    "condition_results": results,
                    "blocking_reason": "; ".join(r.get("reason") or r["metric"] for r in failed)}
    return None
