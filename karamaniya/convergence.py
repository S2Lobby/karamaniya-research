"""Negotiated convergence and vote analytics (spec 110).

A month can end with three unanimous votes for very different reasons. Five delegates may have
agreed before anyone spoke, or they may have opened on competing farm-support levels, withdrawn
one, added safeguards and then agreed. Both look like "5-0" in the raw record, and reporting the
two as the same thing is the error this module exists to prevent.

Everything here is derived from the audit trail the council already writes: the private opening
positions, the response-round stances and revisions, the motions with their status flags, the
recorded demands and the final votes. Older runs are analysed from the fields they did have; a
field a legacy run never recorded is simply reported as unknown rather than guessed at.

Nothing here is ever shown to the delegates, and nothing here changes what the simulation does.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .deliberation import PROCEDURAL

# ---- motion status ---------------------------------------------------------------------------------
PASSED = "PASSED"
#: The council carried the motion subject to binding execution conditions. The vote is
#: politically valid; execution waits until every condition is met (or fails outright).
PASSED_CONDITIONALLY = "PASSED_CONDITIONALLY"
DEFEATED = "DEFEATED"
WITHDRAWN = "WITHDRAWN"
DEFERRED = "DEFERRED"
REJECTED_INVALID = "REJECTED_INVALID"
SUPERSEDED = "SUPERSEDED"
AGENDA_BLOCKED = "AGENDA_BLOCKED"
# The two below are not in the seven canonical states, but the record genuinely contains them and
# folding them into a canonical state would misreport what happened.
VOID = "VOID"          # the session was ended by force; nothing was decided
LAPSED = "LAPSED"      # the proposer left the government, or the motion was deferred past the window
#: The council carried it, and it was still not applied: its payload was not the act it was
#: described as, or an equivalent act had already run this month.
EXECUTION_BLOCKED = "EXECUTION_BLOCKED"
#: The council carried it, but a binding execution condition failed against canonical state.
#: Stored distinctly so the audit trail can separate "the council approved it" from "the world
#: did it". motion_status reports it as EXECUTION_BLOCKED for readers that only know the family.
EXECUTION_BLOCKED_CONDITION = "EXECUTION_BLOCKED_CONDITION"
#: The council carried it conditionally and the conditions are not yet met. The vote stands;
#: the engine retries the conditions each month the motion is still live.
EXECUTION_PENDING = "EXECUTION_PENDING"

#: States that mean the motion actually reached a vote. Only these may enter a unanimity denominator.
#: A motion blocked at execution did reach a vote, so it belongs here. So did a motion the
#: council carried conditionally or one whose execution is still pending: the politics
#: happened, even though the world has not changed yet.
VOTED_STATES = (PASSED, DEFEATED, EXECUTION_BLOCKED, PASSED_CONDITIONALLY, EXECUTION_PENDING)

#: The terminal states the record may store. A motion's stored `status` is authoritative:
#: every reader uses it rather than re-deriving one. WITHDRAWN means the proposer withdrew
#: it; only an actual losing vote is DEFEATED. PASSED_CONDITIONALLY means the council
#: carried it subject to binding execution conditions; EXECUTION_PENDING means the vote
#: carried but the conditions have not been met yet; EXECUTION_BLOCKED means the vote
#: carried but execution was refused (failed conditions, failed condition match, or a
#: blocked payload). EXECUTION_BLOCKED_CONDITION is the condition-failure member of that
#: family; motion_status folds it into EXECUTION_BLOCKED so legacy readers keep working.
_CANONICAL_STATES = frozenset((PASSED, PASSED_CONDITIONALLY, DEFEATED, WITHDRAWN, DEFERRED,
                               REJECTED_INVALID, SUPERSEDED, AGENDA_BLOCKED, LAPSED, VOID,
                               EXECUTION_BLOCKED, EXECUTION_BLOCKED_CONDITION,
                               EXECUTION_PENDING))
#: States that mean the motion was proposed but never voted on. None of these is a defeat.
UNVOTED_STATES = (WITHDRAWN, SUPERSEDED, DEFERRED, AGENDA_BLOCKED, LAPSED, VOID, REJECTED_INVALID, None)

UNANIMITY_CLASSES = ("INITIAL_CONSENSUS", "NEGOTIATED_CONVERGENCE", "DUPLICATE_CONSOLIDATION",
                     "CONDITIONAL_COMPROMISE", "UNKNOWN")
DIVERGENCE_LEVELS = ("NONE", "LOW", "MODERATE", "HIGH")

STANCE_TO_VOTE = {"support": "yes", "oppose": "no", "undecided": "undecided", "conditional": "conditional"}

# Words common enough in this corpus that sharing them says nothing about two motions being
# alternatives. Kept deliberately short: a long list would hide real overlaps.
_GENERIC = frozenset("""
shall with that this from have will which their them after before under such other provisional government
council member members motion motion_id state states public national only also must made make making
""".split())

# The craft vocabulary of institution-building. Two motions about entirely different institutions
# share most of these - a police oversight board and a procurement review commission both
# "establish", "empower", "publish findings" and "protect due process" - so they cannot anchor a
# family. What anchors one is the subject: procurement, police, arrears, farm support.
_BOILERPLATE = frozenset("""
establish established establishing independent empower empowered publish published findings report
reports reported protect protected protecting process processes complete access records files file
ministry ministries article persons named acted acting upon within against subject only lawful
national security relevant particular beginning officials shall
""".split())


def content_words(text: str) -> set:
    """Significant words of a motion's text, for comparing two motions."""
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) > 3 and w not in _GENERIC}


def anchor_words(text: str) -> set:
    """The words that say what a motion is *about*, not how it is drafted."""
    return content_words(text) - _BOILERPLATE


# ---- status ----------------------------------------------------------------------------------------
def motion_status(motion: dict, note_codes: dict | None = None, deferred_ids: set | None = None) -> str:
    """The one semantic terminal state of a motion.

    A motion withdrawn by its proposer is WITHDRAWN. It is never DEFEATED: defeat means the council
    voted it down, and a motion that never reached a vote was not voted down.
    """
    if motion.get("withdrawn"):
        return SUPERSEDED if (motion.get("superseded_by") or motion.get("replaced_by")) else WITHDRAWN
    # A motion the council carried and then refused to execute is its own outcome. It is not
    # superseded: nothing replaced it before the vote, and the vote it won is what was blocked.
    # The condition-blocked variant reads as the family for legacy readers.
    if motion.get("execution_status") in ("EXECUTION_BLOCKED", "EXECUTION_BLOCKED_CONDITION"):
        return EXECUTION_BLOCKED
    if motion.get("status") == EXECUTION_BLOCKED_CONDITION:
        return EXECUTION_BLOCKED
    if motion.get("superseded_by") or motion.get("replaced_by"):
        return SUPERSEDED
    if motion.get("void"):
        return VOID
    if motion.get("status") in _CANONICAL_STATES:
        return motion["status"]
    mid = motion.get("id")
    code = (note_codes or {}).get(mid)
    if code == "LAPSED":
        return LAPSED
    # The agenda pushed this one out. "The council is full, it waits for next month" is a deferral;
    # "you asked for a place and could not pay for it" is a block.
    if code == "FORCE_FAILED":
        return AGENDA_BLOCKED
    if code == "AGENDA_FULL" or mid in (deferred_ids or set()):
        return DEFERRED
    result = str(motion.get("result") or "")
    if motion.get("passed"):
        return PASSED_CONDITIONALLY if motion.get("conditions") else PASSED
    if result.startswith("lapsed:"):
        return LAPSED
    if reached_vote(motion):
        return DEFEATED
    return None


def _counted(motion: dict) -> list:
    votes = motion.get("votes") or {}
    eligible = motion.get("eligible_voters")
    names = eligible if eligible is not None else list(votes)
    return [votes.get(x) for x in names if votes.get(x) in ("yes", "no")]


def reached_vote(motion: dict) -> bool:
    """True when members actually cast a yes or no. Withdrawn and deferred motions never did."""
    if motion.get("withdrawn") or motion.get("void") or motion.get("deferred"):
        return False
    return bool(_counted(motion))


def _agenda_codes(record: dict) -> dict:
    """The reason the agenda gives for a motion, most specific first.

    A motion that failed to buy a forced place also picks up a plain "agenda full" note; the
    failed purchase is the reason worth keeping.
    """
    out = {}
    for note in record.get("agenda_notes") or []:
        mid, code = note.get("motion"), note.get("code")
        if not mid:
            continue
        # A later note about the same motion (COSPONSOR/RENEWED) does not erase an agenda block.
        if code in ("AGENDA_FULL", "FORCE_FAILED", "LAPSED"):
            if out.get(mid) != "FORCE_FAILED" or code == "LAPSED":
                out[mid] = code
        else:
            out.setdefault(mid, code)
    return out


_note_codes = _agenda_codes


def _deferred_ids(record: dict) -> set:
    ids = {m.get("id") for m in record.get("deferred_motions") or [] if isinstance(m, dict) and m.get("id")}
    return {i for i in ids if i}


def universe(record: dict) -> list:
    """Every motion the month record mentions: heard, newly deferred, or lapsed.

    Motions the agenda pushed out are absent from `motions` altogether, so a status table built
    only from that list would silently drop them.
    """
    out = [m for m in record.get("motions") or [] if m.get("id")]
    seen = {m["id"] for m in out}
    for key in ("deferred_motions", "lapsed_motions"):
        for m in record.get(key) or []:
            if m.get("id") and m["id"] not in seen:
                out.append(m)
                seen.add(m["id"])
    return out


def statuses(record: dict) -> dict:
    """motion id -> terminal state, for every motion the record mentions."""
    codes, deferred = _note_codes(record), _deferred_ids(record)
    out = {}
    for mo in universe(record):
        out[mo["id"]] = motion_status(mo, codes, deferred)
    for rej in record.get("rejected_motions") or []:
        key = rej.get("motion_id") or (rej.get("motion") or {}).get("id")
        if key:
            out[key] = REJECTED_INVALID
    return {k: v for k, v in out.items() if k}


# ---- families --------------------------------------------------------------------------------------
def _family_key(motion: dict, texts: list) -> tuple:
    """Which policy question a motion competes on. Deliberately narrow.

    Two motions share a family only when they are genuinely alternatives: the same lever at a
    different level, the same funding question asked two ways, or two texts about the same
    institution. Vaguely related motions are left in separate families.
    """
    kind, subject = motion.get("type"), str(motion.get("subject") or "")
    if kind == "settle_arrears":
        # The subject is the funding mechanism (reserves vs domestic bonds); the question is the same.
        return ("settle_arrears", "")
    if kind == "set_policy":
        return ("set_policy", subject.casefold())
    if kind in ("diplomacy", "emergency_measure", "amend"):
        return (kind, subject.casefold())
    return (kind, subject.casefold())


def _amend_cluster(motion: dict, others: list) -> str:
    """Link Charter amendments that address the same institution into one family.

    Text similarity alone is not enough here: four real procurement-review amendments share as
    little as 0.24 Jaccard and still plainly compete. So the test is a set of shared significant
    words, with a floor on overall similarity, and a requirement that at least two of the shared
    words are about the subject rather than the drafting.
    """
    mine = content_words(motion.get("text", ""))
    my_anchors = anchor_words(motion.get("text", ""))
    best, best_key = None, str(motion.get("id"))
    for other in others:
        if other is motion or other.get("type") != "amend":
            continue
        theirs = content_words(other.get("text", ""))
        if not mine or not theirs:
            continue
        shared = mine & theirs
        similarity = len(shared) / len(mine | theirs)
        if len(shared) >= 6 and similarity >= 0.20 and len(my_anchors & shared) >= 2:
            score = (len(my_anchors & shared), similarity)
            if best is None or score > best:
                best, best_key = score, str(other.get("id"))
    return best_key


def families(motions: list) -> dict:
    """motion id -> family key. Motions in one family were competing answers to one question."""
    substantive = [m for m in motions if m.get("type") not in PROCEDURAL and m.get("id")]
    out = {}
    for mo in substantive:
        out[mo["id"]] = _family_key(mo, substantive)
    return _link_amendments(substantive, out)


def _link_amendments(substantive: list, keys: dict) -> dict:
    """Join amendments pairwise, then take the transitive closure.

    Linking each amendment only to its single best match would split three related texts into
    two families whenever the first and third happen to read less alike. Union-find keeps
    "they all address the same institution" meaning one family.
    """
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    amendments = [m for m in substantive if m.get("type") == "amend"]
    for mo in amendments:
        linked = _amend_cluster(mo, amendments)
        if linked != str(mo.get("id")):
            union(str(mo["id"]), linked)
    return {mid: (("amend", find(mid)) if key[0] == "amend" else key) for mid, key in keys.items()}


def structured_change(c: dict) -> bool:
    """A change of position anchored on something the council recorded, not read back from prose.

    A delegate who tabled the 0.05 motion and then voted yes on the 0.03 one has a recorded change.
    A delegate whose opening read was inferred from their private-position text does not, and that
    weaker signal must not on its own turn a quiet vote into negotiated convergence.
    """
    return c.get("from_basis") in ("tabled_motion", "response_round")


def family_groups(motions: list) -> dict:
    """family key -> the motions in it, but only families that really hold an alternative.

    A family of one is not a contest, so single-motion keys are dropped.
    """
    keys = families(motions)
    grouped: dict[tuple, list] = {}
    for mo in motions:
        if mo.get("id") in keys:
            grouped.setdefault(keys[mo["id"]], []).append(mo)
    return {k: v for k, v in grouped.items() if len(v) > 1}


def family_label(key: tuple, motions: list) -> str:
    """A short readable name for a family, for the report."""
    kind, subject = key
    if kind == "settle_arrears":
        return "ARREARS SETTLEMENT"
    if kind == "amend":
        sample = (motions[0].get("text") or "") if motions else ""
        hit = re.search(r"(independent|procurement|police|civilian|judicial)\s+(\w+)", sample, re.I)
        return (f"{hit.group(1)} {hit.group(2)}" if hit else "CHARTER AMENDMENT").upper()
    return (subject or kind).replace("_", " ").upper()


# ---- positions -------------------------------------------------------------------------------------
def _norm_stance(value: str | None) -> str | None:
    """Normalise any recorded position to yes / no / conditional / undecided."""
    if value in STANCE_TO_VOTE:
        return STANCE_TO_VOTE[value]
    if value in ("yes", "no", "abstain", "conditional"):
        return value
    return None


def _opening(record: dict, mid: str, motion: dict) -> dict:
    """A delegate's position before the discussion, from structured state where it exists.

    The strongest evidence is a motion the delegate tabled in the same family: that is their
    opening offer, recorded exactly. Only when there is none do we fall back to reading their
    private position text, and that read is labelled as the weaker source.
    """
    from .analytics import initial_stance
    text = (record.get("pre_positions") or {}).get(mid) or {}
    stance = initial_stance(text, motion)
    detail = ""
    if isinstance(text, dict):
        detail = text.get("preferred_policy") or text.get("would_support") or ""
    return {"stance": _norm_stance(stance), "basis": "private_position",
            "raw": "support" if stance == "support" else "oppose" if stance == "oppose" else "unknown",
            "detail": detail[:300]}


def positions(record: dict) -> list:
    """Initial -> response -> final for every delegate on every motion, never overwriting a stage.

    Each stage is kept. A delegate who opened in favour, moved against in the response round and
    voted for the amended motion has all three recorded, with the change events between them.
    """
    motions = {m["id"]: m for m in record.get("motions") or [] if m.get("id")}
    fams = families(record.get("motions") or [])
    revisions = record.get("revisions") or {}
    members = list(record.get("order") or sorted((record.get("pre_positions") or {}).keys()))
    for mid in (record.get("pre_positions") or {}):
        if mid not in members:
            members.append(mid)
    demands = {}
    for mo in record.get("motions") or []:
        for dem in mo.get("demands") or []:
            demands.setdefault(dem.get("motion_id"), []).append(dem)
    out = []
    for mid in members:
        staged = revisions.get(mid) or {}
        stances = staged.get("stances") or {}
        for mo_id, mo in motions.items():
            # Initial: a motion this delegate tabled in the family is their opening offer.
            siblings = [m for m in motions.values()
                        if m.get("proposer") == mid and fams.get(m.get("id")) == fams.get(mo_id)]
            if siblings:
                pick = siblings[0]
                initial = {"stance": "yes", "basis": "tabled_motion",
                           "detail": _offer(pick), "motion": pick["id"]}
            else:
                initial = _opening(record, mid, mo)
            response = {"stance": _norm_stance(stances.get(mo_id)),
                        "recorded": stances.get(mo_id) or "", "demands": [
                            {"from": d.get("member"), "demand": d.get("demand", "")}
                            for d in demands.get(mo_id, []) if d.get("member") != mid]}
            vote = (mo.get("votes") or {}).get(mid)
            final = {"vote": vote, "reasons": (mo.get("vote_reasons") or {}).get(mid, "")}
            changes = []
            if initial["stance"] and response["stance"] and initial["stance"] != response["stance"]:
                changes.append({"stage": "response", "from": initial["stance"], "to": response["stance"],
                                "from_basis": initial["basis"],
                                "reasons": _reasons(record, mid, mo, revisions, "response")})
            anchor = response["stance"] or initial["stance"]
            # A conditional stance that resolves into the vote it was always leaning towards is a
            # condition being met, not a delegate changing their mind.
            if vote in ("yes", "no") and anchor and anchor != vote and response["stance"] != "conditional":
                changes.append({"stage": "final", "from": anchor, "to": vote,
                                "from_basis": "response_round" if response["stance"] else initial["basis"],
                                "reasons": _reasons(record, mid, mo, revisions, "final")})
            out.append({"member": mid, "motion": mo_id, "family": fams.get(mo_id),
                        "initial": initial, "response": response, "final": final, "changes": changes})
    return out


def _offer(motion: dict) -> str:
    value = str(motion.get("value") or "").strip()
    summary = motion.get("summary") or motion.get("subject") or ""
    return f"{summary}" + (f" (value {value})" if value and value not in summary else "")


def _reasons(record: dict, mid: str, motion: dict, revisions: dict, stage: str) -> list:
    """Structured evidence for a change of position. Never guessed from prose."""
    reasons = []
    if motion.get("amended"):
        amendments = [r for r in motion.get("revisions") or []]
        if amendments:
            reasons.append({"code": "MOTION_AMENDED_AFTER_ITS_OWN_TERMS_CHANGED",
                            "detail": f"proposer moved the motion from "
                                      f"{str(amendments[0].get('value')) or 'its original text'}"})
        else:
            reasons.append({"code": "MOTION_AMENDED", "detail": "the motion was amended before the vote"})
    for dem in motion.get("demands") or []:
        if dem.get("member") not in (mid, None):
            reasons.append({"code": "DEMAND_BY_OTHER", "from": dem.get("member"),
                            "detail": dem.get("demand", "")[:200]})
    withdrawn_by = None
    for other_id, staged in (revisions or {}).items():
        if motion["id"] in (staged.get("withdrawn") or []) and other_id != mid:
            withdrawn_by = other_id
    if withdrawn_by:
        reasons.append({"code": "COMPETING_MOTION_WITHDRAWN", "from": withdrawn_by,
                        "detail": f"{withdrawn_by} withdrew {motion['id']}"})
    if (motion.get("conditional_votes") or {}).get(mid):
        reasons.append({"code": "OWN_CONDITIONAL_VOTE",
                        "detail": "condition attached by this delegate"})
    own = (revisions or {}).get(mid) or {}
    if stage == "response" and own.get("response"):
        reasons.append({"code": "STATED_RESPONSE", "detail": own["response"][:300]})
    return reasons


def position_changes(record: dict) -> list:
    """Every recorded change of position, flattened."""
    return [{"member": p["member"], "motion": p["motion"], "family": p["family"], **c}
            for p in positions(record) for c in p["changes"]]


# ---- classification --------------------------------------------------------------------------------
def _is_duplicate(a: dict, b: dict) -> bool:
    """Two motions that ask for the same thing, so consolidating them adds no new content.

    The whole measure has to match, not just the value: paying the arrears from reserves and
    paying them from domestic bonds both carry the value "quarter" and are not duplicates.
    """
    a_triple = (str(a.get("type")), str(a.get("subject")), str(a.get("value")))
    b_triple = (str(b.get("type")), str(b.get("subject")), str(b.get("value")))
    # Amendments carry their content in the text, so an empty subject and value are not an identity.
    if a_triple == b_triple and (a_triple[1] or a_triple[2]):
        return True
    if a.get("type") == "amend" and b.get("type") == "amend":
        return SequenceMatcher(None, str(a.get("text", "")).lower(),
                               str(b.get("text", "")).lower()).ratio() > .7
    return False


def classify_unanimous(record: dict, motion: dict) -> dict:
    """Why did this motion pass unanimously? Structured state, not keyword reading.

    Returns the class plus the evidence that produced it, so the verdict can be checked.
    """
    motions = universe(record)
    fams = families(motions)
    key = fams.get(motion["id"])
    siblings = [m for m in motions if m["id"] != motion["id"] and fams.get(m["id"]) == key] if key else []
    codes, deferred = _note_codes(record), _deferred_ids(record)
    sib_status = {m["id"]: motion_status(m, codes, deferred) for m in siblings}
    withdrawn = [m for m in siblings if sib_status[m["id"]] in (WITHDRAWN, SUPERSEDED)]
    duplicates = [m for m in withdrawn if _is_duplicate(m, motion)]
    contested_withdrawn = [m for m in withdrawn if m not in duplicates]
    # Stances recorded in the response round against this motion.
    opposed = []
    for mid, staged in (record.get("revisions") or {}).items():
        if (staged.get("stances") or {}).get(motion["id"]) == "oppose":
            opposed.append(mid)
    moved = [c for c in position_changes(record)
             if c["motion"] == motion["id"] and structured_change(c)]
    conditions = motion.get("conditional_votes") or {}
    evidence = {"outcome": "PASSED" if motion.get("passed") else "DEFEATED",
                "family": list(key) if key else None, "family_size": len(siblings) + 1,
                "withdrawn_siblings": [m["id"] for m in withdrawn],
                "duplicate_siblings": [m["id"] for m in duplicates],
                "contested_withdrawn": [m["id"] for m in contested_withdrawn],
                "opposed_in_response_round": opposed, "position_changes_on_this_motion": len(moved),
                "amended": bool(motion.get("amended")), "conditional_votes": len(conditions)}
    if duplicates:
        return {"classification": "DUPLICATE_CONSOLIDATION", "confidence": "structured",
                "evidence": evidence,
                "because": "a substantively duplicate motion in the same family was withdrawn"}
    if contested_withdrawn or motion.get("amended") or opposed or moved:
        bits = []
        if contested_withdrawn:
            bits.append(f"a competing alternative ({', '.join(m['id'] for m in contested_withdrawn)}) was withdrawn")
        if motion.get("amended"):
            bits.append("the surviving motion was amended")
        if opposed:
            bits.append(f"{len(opposed)} delegate(s) had recorded opposition in the response round")
        if moved:
            bits.append(f"{len(moved)} delegate(s) changed position on this motion")
        return {"classification": "NEGOTIATED_CONVERGENCE", "confidence": "structured",
                "evidence": evidence, "because": "; ".join(bits)}
    if conditions:
        return {"classification": "CONDITIONAL_COMPROMISE", "confidence": "structured",
                "evidence": evidence,
                "because": f"{len(conditions)} delegate(s) supported it only under a stated condition"}
    # Nothing contested it. Initial consensus still needs affirmative evidence that delegates
    # agreed before speaking; "no data" is not consensus.
    if not siblings:
        # Everyone agreed before speaking: in favour of a motion that passed, or against one that
        # was voted down. Either way the agreement predates the discussion.
        agree = "support" if motion.get("passed") else "oppose"
        word = "supported" if motion.get("passed") else "opposed"
        opens = [_opening(record, mid, motion) for mid in (motion.get("votes") or {})
                 if mid != motion.get("proposer")]
        sure = [o for o in opens if o["raw"] == agree]
        against = [o for o in opens if o["raw"] not in (agree, "unknown")]
        evidence["opening_positions_read"] = len(opens)
        evidence["opening_agreement"] = len(sure)
        if sure and not against:
            return {"classification": "INITIAL_CONSENSUS", "confidence": "structured",
                    "evidence": evidence,
                    "because": f"{len(sure)} delegate(s) privately {word} it before discussion, "
                               "no one took the other side, and no alternative was tabled"}
    return {"classification": "UNKNOWN", "confidence": "low", "evidence": evidence,
            "because": "no structured evidence distinguishes consensus from convergence"}


# ---- month analytics -------------------------------------------------------------------------------
def _divergence(competing: int, opposing_stances: int, contested_withdrawals: int) -> tuple:
    """How far apart the council was before the revision round. A score, then a label.

    Each signal is capped so one loud month cannot drown the others: what the label describes is
    how many *kinds* of disagreement were live, not how many words were spent on them.
    """
    score = min(3, competing) * 2 + min(4, opposing_stances) + min(2, contested_withdrawals) * 2
    level = "NONE" if score == 0 else "LOW" if score <= 2 else "MODERATE" if score <= 5 else "HIGH"
    return level, score


def month_analytics(record: dict) -> dict:
    """Everything the report needs about one month's negotiation."""
    motions = universe(record)
    substantive = [m for m in motions if m.get("type") not in PROCEDURAL]
    codes, deferred = _note_codes(record), _deferred_ids(record)
    state = {m["id"]: motion_status(m, codes, deferred) for m in substantive if m.get("id")}
    voted = [m for m in substantive if state.get(m.get("id")) in VOTED_STATES]
    unanimous = [m for m in voted if set(_counted(m)) in ({"yes"}, {"no"})]
    groups = family_groups(motions)
    # A family is a contest only where the alternatives actually reached the floor. Two motions the
    # agenda pushed out agreed nothing and competed for nothing.
    live = (PASSED, DEFEATED, WITHDRAWN, SUPERSEDED)
    competing = {k: [m for m in v if state.get(m.get("id")) in live] for k, v in groups.items()}
    competing = {k: v for k, v in competing.items() if len(v) > 1}
    changes = position_changes(record)
    fams = families(motions)
    key_of = {m["id"]: fams.get(m["id"]) for m in substantive}
    # Opposing stances recorded in the response round, against any motion still live at that point.
    # The withdrawn motion matters most here: "A withdrew after the council turned against it" is
    # the case this metric exists to catch, and that motion never passes.
    opposing = {}
    for mid, staged in (record.get("revisions") or {}).items():
        for mo_id, val in (staged.get("stances") or {}).items():
            if val == "oppose" and mo_id in state:
                opposing.setdefault(mo_id, []).append(mid)
    contested_withdrawals = []
    for mid, staged in (record.get("revisions") or {}).items():
        for mo_id in staged.get("withdrawn") or []:
            if state.get(mo_id) not in (WITHDRAWN, SUPERSEDED):
                continue
            family = key_of.get(mo_id)
            rivals = [o for o in substantive
                      if o.get("id") != mo_id and key_of.get(o.get("id")) == family]
            if rivals:
                contested_withdrawals.append({"motion": mo_id, "by": mid,
                                              "replaced_by": _replacement(record, mo_id, rivals, state)})
    for m in substantive:
        if m.get("withdrawn") and m.get("id") not in {c["motion"] for c in contested_withdrawals}:
            family = key_of.get(m.get("id"))
            rivals = [o for o in substantive if o.get("id") != m.get("id") and key_of.get(o.get("id")) == family]
            if rivals:
                contested_withdrawals.append({"motion": m["id"], "by": m.get("withdrawn_by") or m.get("proposer"),
                                              "replaced_by": _replacement(record, m["id"], rivals, state)})
    classifications = {m["id"]: classify_unanimous(record, m) for m in unanimous}
    minority = _minority(record, voted, state)
    structured = [c for c in changes if structured_change(c)]
    level, score = _divergence(len(competing), sum(len(v) for v in opposing.values()),
                               len(contested_withdrawals))
    negotiated = [mid for mid, c in classifications.items() if c["classification"] == "NEGOTIATED_CONVERGENCE"]
    return {
        "month": record.get("month"),
        "final_vote_unanimity": round(len(unanimous) / len(voted), 3) if voted else None,
        "votes_cast": len(voted),
        "unanimous_votes": len(unanimous),
        "pre_revision_divergence": level,
        "pre_revision_divergence_score": score,
        "position_changes": len(changes),
        "position_changes_structured": len(structured),
        "position_change_detail": changes,
        "motions_withdrawn_after_opposition": sum(1 for c in contested_withdrawals if opposing.get(c["motion"])),
        # The number of rival answers on the floor, not the number of families: two arrears motions
        # are two competing alternatives.
        "competing_alternatives": sum(len(v) for v in competing.values()),
        "competing_families": [{"key": list(k), "label": family_label(k, v), "motions": [m["id"] for m in v]}
                               for k, v in competing.items()],
        "negotiated_convergence_count": len(negotiated),
        "negotiated_convergence_motions": negotiated,
        "minority_positions_maintained": minority["maintained"],
        "minority_detail": minority["detail"],
        "failed_votes": sum(1 for m in substantive if state.get(m.get("id")) == DEFEATED),
        "withdrawn_motions": sum(1 for m in substantive if state.get(m.get("id")) in (WITHDRAWN, SUPERSEDED)),
        "superseded_motions": sum(1 for m in substantive if state.get(m.get("id")) == SUPERSEDED),
        "deferred_motions": _deferred_count(record, substantive, state),
        "rejected_invalid_motions": len(record.get("rejected_motions") or []),
        "status_counts": {s: sum(1 for v in state.values() if v == s)
                          for s in sorted({v for v in state.values() if v})},
        "motion_states": state,
        "unanimity_classification": {mid: c["classification"] for mid, c in classifications.items()},
        "unanimity_evidence": classifications,
        "withdrawals": contested_withdrawals,
        "families": {":".join(k): family_report(record, k) for k in groups},
    }


def _deferred_count(record: dict, substantive: list, state: dict) -> int:
    """Motions the council did not reach this month.

    Newer runs list them with their ids; a run saved before that only kept the summaries, and the
    summaries are still enough to count them.
    """
    counted = sum(1 for m in substantive if state.get(m.get("id")) in (DEFERRED, AGENDA_BLOCKED, LAPSED))
    if record.get("deferred_motions") is None:
        counted = len(record.get("deferred") or []) + len(record.get("lapsed") or [])
    return counted


def _replacement(record: dict, motion_id: str, rivals: list, state: dict) -> str | None:
    """Which rival the withdrawn motion's proposer fell in behind, from recorded votes."""
    src = next((m for m in record.get("motions") or [] if m.get("id") == motion_id), None)
    if not src:
        return None
    explicit = src.get("replaced_by") or src.get("superseded_by")
    if explicit:
        return explicit
    who = src.get("withdrawn_by") or src.get("proposer")
    for rival in rivals:
        if (rival.get("votes") or {}).get(who) == "yes" and state.get(rival.get("id")) == PASSED:
            return rival["id"]
    return None


def _minority(record: dict, voted: list, state: dict) -> dict:
    """Did anyone hold a losing position through the final vote?"""
    detail, count = [], 0
    revisions = record.get("revisions") or {}
    for mo in voted:
        counted = [v for v in _counted(mo)]
        if len(set(counted)) < 2:
            continue
        yes = counted.count("yes")
        majority = "yes" if yes > len(counted) - yes else "no"
        for mid, vote in (mo.get("votes") or {}).items():
            if vote not in ("yes", "no") or vote == majority:
                continue
            recorded = (revisions.get(mid) or {}).get("stances", {}).get(mo["id"])
            # Structured confirmation: the delegate said the same thing in the response round.
            confirmed = recorded is not None and STANCE_TO_VOTE.get(recorded) == vote
            count += 1
            detail.append({"member": mid, "motion": mo["id"], "vote": vote, "majority": majority,
                           "response_round_stance": recorded or "not recorded",
                           "maintained_after_negotiation": confirmed})
    return {"maintained": count, "detail": detail}


def _family_narrative(record: dict, key: tuple, members: list) -> dict:
    """Initial -> after negotiation -> final, for one contested family."""
    fams = families(record.get("motions") or [])
    revisions = record.get("revisions") or {}
    codes, deferred = _note_codes(record), _deferred_ids(record)
    members_sorted = sorted({m.get("proposer") for m in members if m.get("proposer")} |
                            set(record.get("pre_positions") or {}))
    initial, after = [], []
    for mid in members_sorted:
        mine = [m for m in members if m.get("proposer") == mid]
        if mine:
            initial.append({"member": mid, "preferred": _offer(mine[0]), "motion": mine[0]["id"],
                            "basis": "tabled_motion"})
        else:
            rep = members[0]
            op = _opening(record, mid, rep)
            initial.append({"member": mid, "preferred": op["detail"] or "no recorded preference",
                            "motion": None, "basis": op["basis"], "lean": op["raw"]})
        staged = (revisions.get(mid) or {}).get("stances") or {}
        support = [i for i in (m["id"] for m in members) if staged.get(i) in ("support", "conditional")]
        oppose = [i for i in (m["id"] for m in members) if staged.get(i) == "oppose"]
        withdrew = [i for i in ((revisions.get(mid) or {}).get("withdrawn") or [])
                    if i in {m["id"] for m in members}]
        if support or oppose or withdrew:
            after.append({"member": mid, "supports": support, "opposes": oppose, "withdrew": withdrew})
    final_motions = [m for m in members if motion_status(m, codes, deferred) in VOTED_STATES]
    final = []
    for mo in final_motions:
        final.append({"motion": mo["id"], "summary": mo.get("summary"), "tally": mo.get("tally"),
                      "status": motion_status(mo, codes, deferred),
                      "votes": {k: v for k, v in (mo.get("votes") or {}).items() if v in ("yes", "no")}})
    return {"key": ":".join(key), "label": family_label(key, members),
            "motions": [{"id": m["id"], "proposer": m.get("proposer"), "summary": m.get("summary"),
                         "status": motion_status(m, codes, deferred), "value": m.get("value")}
                        for m in members],
            "initial": initial, "after_negotiation": after, "final": final,
            "outcome": _family_outcome(record, members, codes, deferred)}


def _family_outcome(record: dict, members: list, codes: dict, deferred: set) -> str:
    passed = [m for m in members if motion_status(m, codes, deferred) == PASSED]
    if passed and len(passed) == 1:
        mo = passed[0]
        return f"{mo.get('summary')} — {mo.get('tally')}"
    if passed:
        return "; ".join(f"{m.get('summary')} ({m.get('tally')})" for m in passed)
    return "no alternative carried"


def family_report(record: dict, key: tuple) -> dict:
    """Everything the report needs about one family of competing motions."""
    motions = universe(record)
    mine = [m for m in motions if families(motions).get(m.get("id")) == key]
    if not mine:
        return {}
    return _family_narrative(record, key, mine)


# ---- run level -------------------------------------------------------------------------------------
def run_convergence(months: list) -> dict:
    """Month-by-month convergence, plus the totals the report shows."""
    per_month = [month_analytics(rec) for rec in months]
    totals = {k: sum(m[k] or 0 for m in per_month) for k in
              ("position_changes", "motions_withdrawn_after_opposition", "competing_alternatives",
               "negotiated_convergence_count", "minority_positions_maintained", "failed_votes",
               "withdrawn_motions", "deferred_motions", "unanimous_votes", "votes_cast")}
    classes = {}
    for m in per_month:
        for cls in m["unanimity_classification"].values():
            classes[cls] = classes.get(cls, 0) + 1
    returns = [{"month": m["month"], "final_vote_unanimity": m["final_vote_unanimity"],
                "unanimous_votes": m["unanimous_votes"], "votes_cast": m["votes_cast"]}
               for m in per_month]
    return {"months": per_month, "totals": totals, "unanimity_classes": classes,
            "final_vote_unanimity": (round(totals["unanimous_votes"] / totals["votes_cast"], 3)
                                     if totals["votes_cast"] else None),
            "monthly_unanimity": returns}


# ---- promises and bargains -------------------------------------------------------------------------
PROMISE_LABELS = {"active": "PENDING", "fulfilled": "KEPT", "broken": "BROKEN", "lapsed": "EXPIRED",
                  "withdrawn": "WITHDRAWN"}


def promise_status(promise: dict) -> str:
    """The exposed status of a recorded promise.

    A promise is BROKEN only on a recorded broken verdict, which the council reaches by testing the
    condition the delegate actually stated - never because a preferred policy failed to pass.
    """
    status = promise.get("status") or "active"
    label = PROMISE_LABELS.get(status, status.upper())
    if label == "PENDING" and _ambiguous(promise):
        return "AMBIGUOUS"
    return label


def _ambiguous(promise: dict) -> bool:
    """A live promise whose stated condition the council cannot test."""
    if promise.get("condition_metric"):
        return False
    norm = promise.get("normalized") or {}
    return not norm.get("type")


def promise_followthrough(world: dict) -> list:
    """Every recorded promise, with counterparty, condition and how it stands."""
    out = []
    for member in world.get("members", []):
        for p in member.get("promises", []) or []:
            evaluations = p.get("evaluations") or []
            out.append({
                "member": member.get("id"), "promise_id": p.get("id"),
                "promise": p.get("text", ""), "counterparty": p.get("to") or "public",
                "condition": p.get("condition_text") or p.get("condition") or "",
                "condition_metric": p.get("condition_metric"),
                "status": promise_status(p),
                "recorded_status": p.get("status") or "active",
                "made_month": p.get("created_month"), "settled_month": p.get("fulfilled_month"),
                "verdicts": [e.get("verdict") for e in evaluations],
                "violations": len(p.get("violations") or []),
                "public": bool(p.get("public")),
            })
    return out


def bargain_followthrough(months: list) -> list:
    """Favours owed between delegates, and whether the favour was repaid by a recorded vote."""
    out = []
    for rec in months:
        for mid, social in ((rec.get("social") or {}).get("members") or {}).items():
            for debt in (social.get("favor_debts") or []):
                out.append({"month": rec.get("month"), "member": mid, "to": debt.get("to"),
                            "what": debt.get("motion") or debt.get("what"),
                            "status": (debt.get("status") or "active").upper(),
                            "importance": debt.get("importance")})
    return out
