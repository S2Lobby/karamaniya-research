"""Council deliberation rules (spec 29, 31-34, 87-94).

The council can only give serious attention to a few substantive motions a month. Procedural
appointments do not use agenda slots. The Head of Government ranks topics; motions on the
Head's topics are heard first, then by the proposer's political capital. A member can force a
motion onto a full agenda by spending political capital, and two members tabling the same
measure co-sponsor it. Motions that do not fit are deferred to next month, not silently lost.

Charter amendments cost political capital, more when the Charter has been opened recently.
Near-duplicates of the Charter are rejected with a reason; partial overlaps are allowed but
flagged so the proposer can withdraw, clarify or proceed. Conditional votes can depend on a
metric or on another motion's fate, and say what happens if the condition fails.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from . import standing, tuning
from .politics import LEVER_OFFICE, validate_motion_detail
from .world import World

PROCEDURAL = ("assign_office", "vacate_office")
TOPICS = ("fiscal", "food", "prices", "policing", "military", "navy", "constitution", "diplomacy",
          "currency", "appointments", "emergency", "oversight", "other")

CHARTER = [
    {"ref": "Charter article 1", "text": "The Provisional Government holds state power until a Constituent Assembly is elected.",
     "concepts": {"provisional_authority"}},
    {"ref": "Charter article 2", "text": "Elections to the Constituent Assembly are held in Month 18.",
     "concepts": {"election_date"}},
    {"ref": "Charter article 3", "text": "The government decides by majority vote of its members and may change its own rules.",
     "concepts": {"decision_rule"}},
    {"ref": "Charter article 4", "text": "The government appoints the holders of five offices.",
     "concepts": {"appointments"}},
    {"ref": "Charter article 5", "text": "If the government loses the election, it hands power to the Assembly the following month.",
     "concepts": {"handover"}},
]
CONCEPTS = {
    "election_date": ("election", "month 18", "constituent assembly election", "polling day"),
    "handover": ("hand over", "handover", "transfer of power", "peaceful transfer", "cede power", "step down after"),
    "decision_rule": ("majority vote", "decision rule", "two-thirds", "unanimity", "quorum"),
    "press_freedom": ("press", "journalis", "newspaper", "media freedom", "censorship"),
    "assembly": ("assembly", "protest", "demonstrat", "gather"),
    "minority_rights": ("minority", "vell", "imperial citizens", "equal citizenship", "discriminat"),
    "civilian_control": ("civilian control", "subordinate to", "no coup", "armed forces obey", "military obey", "non-partisan"),
    "emergency_limits": ("emergency", "state of emergency", "sunset", "martial law"),
    "honest_statistics": ("statistic", "honest data", "publish figures", "transparen"),
    "judicial_review": ("court", "judicial", "tribunal", "review"),
    "regional_autonomy": ("autonomy", "self-government", "regional council", "devolution", "federal"),
    "currency": ("currency", "karam", "crown", "central bank"),
    "civil_liberties": ("civil libert", "free speech", "privacy", "due process", "habeas", "detention"),
    "appointments": ("appoint", "office holder", "portfolio"),
    "provisional_authority": ("provisional government", "state power"),
}
CONSTITUTION_CONCEPT = {"press": "press_freedom", "assembly": "assembly", "minority": "minority_rights",
                        "emergency": "emergency_limits", "election_month": "election_date", "decision_rule": "decision_rule"}


def concepts(text: str) -> set:
    s = text.lower()
    return {c for c, words in CONCEPTS.items() if any(word in s for word in words)}


def topic(mo: dict) -> str:
    t, s = mo.get("type"), mo.get("subject", "")
    if t in PROCEDURAL:
        return "appointments"
    if t == "set_policy":
        office = LEVER_OFFICE.get(s)
        if s in ("rationing", "imports", "farm_support", "requisition", "price_controls"):
            return "food"
        if s in ("printing", "rate"):
            return "prices"
        return {"treasury": "fiscal", "interior": "policing", "army": "military", "navy": "navy"}.get(office, "other")
    if t == "settle_arrears":
        return "fiscal"
    if t in ("constitution", "amend", "expel", "referendum"):
        return "constitution"
    if t == "diplomacy":
        return "diplomacy"
    if t == "launch_currency":
        return "currency"
    if t == "investigation":
        return "oversight"
    if t == "emergency_measure":
        return "emergency"
    return "other"


def capacity(w: World) -> int:
    if w.month == 0 and w.founding and w.founding.get("agenda_slots"):
        return int(w.founding["agenda_slots"])
    slots = int(tuning.get(w, "agenda.major_motions"))
    if w.dip.war or w.dip.blockade or w.dip.ultimatum or w.const.emergency:
        slots += int(tuning.get(w, "agenda.emergency_extra"))
    return slots


def redundancy(w: World, mo: dict, tabled: list) -> dict | None:
    """Conceptual duplicates of the Charter, of adopted amendments, or of motions already tabled."""
    if mo.get("type") != "amend":
        return None
    text = str(mo.get("text", ""))
    proposed = concepts(text)
    if not proposed:
        return None
    covered, refs = set(), []
    for clause in CHARTER:
        hit = proposed & clause["concepts"]
        if hit:
            covered |= hit
            refs.append(clause["ref"])
    for i, a in enumerate(w.const.amendments, 1):
        hit = proposed & concepts(a.get("text", ""))
        if hit:
            covered |= hit
            refs.append(f"amendment {i} (Month {a.get('month', 0) + 1})")
    c = w.const
    in_force = {"press_freedom": c.press == "free", "assembly": c.assembly == "free",
                "minority_rights": c.minority == "equal"}
    for concept, ok in in_force.items():
        if concept in proposed and ok:
            covered.add(concept)
            refs.append(f"constitution setting {concept.replace('_', ' ')}")
    for other in tabled:
        if other.get("type") == "amend" and SequenceMatcher(None, text.lower(), str(other.get("text", "")).lower()).ratio() > .7:
            return {"level": "duplicate", "explanation": f"essentially the same as {other.get('id', 'a motion')} tabled this month",
                    "references": [other.get("id", "")]}
    share = len(proposed & covered) / len(proposed)
    if share >= 1 and refs:
        return {"level": "overlap_full", "explanation": "this is substantially already protected by "
                + ", ".join(dict.fromkeys(refs)) + "; say what legal effect it adds, strengthen a missing part, or withdraw it",
                "references": list(dict.fromkeys(refs)), "concepts": sorted(proposed)}
    if share >= float(tuning.get(w, "amendments.overlap_warning")) and refs:
        return {"level": "overlap_partial", "explanation": "part of this is already covered by " + ", ".join(dict.fromkeys(refs)),
                "references": list(dict.fromkeys(refs)), "concepts": sorted(proposed - covered)}
    return None


def amendment_cost(w: World) -> float:
    window = int(tuning.get(w, "amendments.fatigue_window"))
    recent = sum(1 for a in w.const.amendments if w.month - a.get("month", -99) < window)
    return round(float(tuning.get(w, "amendments.capital_cost")) + float(tuning.get(w, "amendments.repeat_cost")) * recent, 3)


def check(w: World, mo: dict, tabled: list, proposer: str) -> tuple[dict | None, dict | None]:
    """(rejection, warning) for one tabled motion."""
    detail = validate_motion_detail(w, mo)
    if detail:
        return detail, None
    key = (mo.get("type"), str(mo.get("subject", "")).casefold(), str(mo.get("value", "")).casefold())
    for other in tabled:
        if (other.get("type"), str(other.get("subject", "")).casefold(), str(other.get("value", "")).casefold()) == key \
                and mo.get("type") != "amend":
            if other.get("proposer") == proposer:
                return {"status": "rejected", "reason_code": "SAME_MOTION_TABLED",
                        "explanation": "you already tabled this motion this month", "related_state": {}}, None
            return None, {"code": "COSPONSOR", "explanation": f"the same measure was tabled by {other.get('proposer')}; "
                                                               "it is heard once, with both of you as sponsors",
                          "cosponsor_of": other.get("id")}
    warning = None
    red = redundancy(w, mo, tabled)
    if red and red["level"] == "duplicate":
        return {"status": "rejected", "reason_code": "SUBSTANTIALLY_DUPLICATES", "explanation": red["explanation"],
                "related_state": {"references": red["references"]}}, None
    if red:
        warning = {"code": "ALREADY_PROTECTED" if red["level"] == "overlap_full" else "PARTIAL_OVERLAP",
                   "explanation": red["explanation"], "references": red["references"]}
    if mo.get("type") == "amend":
        cost = amendment_cost(w)
        s = standing.ensure(w, proposer)
        if s["capital"] < cost:
            return {"status": "rejected", "reason_code": "INSUFFICIENT_CAPITAL",
                    "explanation": f"opening the Charter again needs more political capital than you have now "
                                   f"(the Charter was amended {len(w.const.amendments)} times so far)",
                    "related_state": {"cost": cost, "capital": s["capital"]}}, None
    return None, warning


def allocate(w: World, motions: list, head_priorities: list, forced: set, carried: list) -> tuple[list, list, list]:
    """Decide which motions the council hears this month (spec 92, 93).

    Returns (scheduled, deferred, notes). Procedural motions are always heard. Carried-over
    motions come first, then motions on the Head's priority topics, then forced motions, then the
    rest by the proposer's political capital."""
    slots = capacity(w)
    procedural = [m for m in motions if m["type"] in PROCEDURAL]
    substantive = [m for m in motions if m["type"] not in PROCEDURAL]
    ranks = {t: i for i, t in enumerate(head_priorities or [])}
    def score(m):
        s = standing.ensure(w, m["proposer"])
        return (0 if m.get("carried_over") else 1,
                ranks.get(topic(m), 99),
                0 if m["id"] in forced or m.get("cosponsors") else 1,
                -s["capital"], m["id"])
    ordered = sorted(substantive, key=score)
    scheduled, deferred, notes = [], [], []
    for m in ordered:
        if len(scheduled) < slots:
            scheduled.append(m)
            continue
        if m["id"] in forced:
            cost = float(tuning.get(w, "agenda.force_cost"))
            need = float(tuning.get(w, "agenda.force_capital"))
            if standing.ensure(w, m["proposer"])["capital"] >= need and standing.spend_capital(w, m["proposer"], cost):
                scheduled.append(m)
                m["forced"] = True
                notes.append({"motion": m["id"], "code": "FORCED_ONTO_AGENDA",
                              "explanation": f"{m['proposer']} spent political capital to force {m['id']} onto a full agenda"})
                continue
            notes.append({"motion": m["id"], "code": "FORCE_FAILED",
                          "explanation": "not enough political capital to force this motion onto the agenda"})
        deferred.append(m)
        notes.append({"motion": m["id"], "code": "AGENDA_FULL",
                      "explanation": f"the council can seriously consider {slots} substantive motions this month; "
                                     "this one is deferred to next month"})
    return procedural + scheduled, deferred, notes


def carried_over(w: World) -> list:
    """Deferred motions still valid this month, with their executable conditions refreshed.

    A deferred conditional motion keeps its vote history but re-derives conditions from its
    final text, so a condition that failed last month is retried against this month's state
    rather than frozen or silently dropped.
    """
    from . import motion_actions
    keep = []
    months = int(tuning.get(w, "agenda.carry_over_months"))
    for m in w.agenda.get("deferred", []):
        if w.month - m.get("deferred_month", w.month) > months:
            continue
        if w.member(m["proposer"]).status != "active":
            continue
        if validate_motion_detail(w, m):
            continue
        carried = {**m, "carried_over": True}
        carried["conditions"] = motion_actions.motion_conditions(carried)
        carried["final_conditions"] = list(carried["conditions"])
        carried["final_motion_text"] = str(carried.get("text", ""))
        keep.append(carried)
    return keep


def coalesce_carried(w: World, candidate: dict, carried: list, proposer: str) -> dict | None:
    """Renew a deferred motion without consuming another agenda slot.

    A sponsor may update its wording; another delegate becomes a co-sponsor. Distinct
    Charter amendments still remain distinct motions.
    """
    if validate_motion_detail(w, candidate):
        return None
    for motion in carried:
        if candidate.get("type") != motion.get("type"):
            continue
        if candidate.get("type") == "amend":
            old = " ".join(str(motion.get("text", "")).casefold().split())
            new = " ".join(str(candidate.get("text", "")).casefold().split())
            if not old or not new or SequenceMatcher(None, old, new).ratio() <= .7:
                continue
        elif (str(candidate.get("subject", "")).casefold(), str(candidate.get("value", "")).casefold()) != \
                (str(motion.get("subject", "")).casefold(), str(motion.get("value", "")).casefold()):
            continue
        if motion["proposer"] == proposer:
            if candidate.get("text") and candidate["text"] != motion.get("text"):
                motion.setdefault("revisions", []).append({"value": motion.get("value"), "text": motion.get("text")})
                motion["text"] = candidate["text"]
                motion["summary"] = _motion_summary(w, motion)
            if candidate.get("conditions") is not None:
                # An amendment may add, narrow or clear execution safeguards; the final
                # text plus these stored conditions are what the gate will test.
                from . import motion_actions
                clean = motion_actions.motion_conditions({**motion, "conditions": candidate["conditions"]})
                motion["conditions"] = clean
                motion["final_conditions"] = list(clean)
                motion["final_motion_text"] = str(motion.get("text", ""))
            elif motion.get("text") and "conditions" in motion:
                from . import motion_actions
                refreshed = motion_actions.motion_conditions(motion)
                motion["conditions"] = refreshed
                motion["final_conditions"] = list(refreshed)
                motion["final_motion_text"] = str(motion.get("text", ""))
            motion["force_agenda"] = bool(candidate.get("force_agenda"))
            return {"code": "RENEWED_CARRIED", "motion": motion["id"]}
        if proposer not in motion.setdefault("cosponsors", []):
            motion["cosponsors"].append(proposer)
        return {"code": "COSPONSORED_CARRIED", "motion": motion["id"]}
    return None


def _motion_summary(w: World, motion: dict) -> str:
    from .actions import motion_summary
    return motion_summary(w, motion)


def resolve_mutual_withdrawals(motions: list) -> list:
    """Stop a mutual consolidation from taking the whole agreement off the agenda.

    Withdrawals are applied one delegate at a time, so two delegates can each withdraw their own
    motion in order to fall in behind the other's, and both stand withdrawn before either can be
    seen beside the other. E withdraws M1 to support M4; A withdraws M4 to support M1; the council
    is left with neither, and the agreement both of them were acting on is nowhere to be voted on.
    Neither withdrawal is wrong on its own, which is why only a pass over the finished set can see
    it — the cycle exists in the links, not in any single delegate's answer.

    One motion is restored, chosen by the consolidation itself: the target that the most of the
    cycle's delegates fell in behind, then the one with the most co-sponsors, then the one tabled
    earliest. That is the motion the withdrawals were converging on, read back out of them. Nothing
    is invented and no proposal is rewritten — the survivor is one a delegate already tabled.

    Returns one record per collision for the audit trail.
    """
    from .convergence import families, _is_duplicate

    by_id = {m["id"]: m for m in motions if m.get("id")}
    withdrawn = {mid for mid, m in by_id.items() if m.get("withdrawn")}
    order = {m["id"]: i for i, m in enumerate(motions) if m.get("id")}
    fam = families(motions)
    seen, collisions = set(), []
    for start in sorted(withdrawn, key=lambda mid: order.get(mid, 0)):
        chain, cur = [], start
        while isinstance(cur, str) and cur in withdrawn and cur not in chain:
            chain.append(cur)
            cur = by_id[cur].get("replaced_by")
        if not (isinstance(cur, str) and cur in chain):
            continue                          # the chain ran out, or left the withdrawn set
        cycle = chain[chain.index(cur):]
        key = frozenset(cycle)
        if len(cycle) < 2 or key in seen:
            continue
        seen.add(key)
        members = [by_id[mid] for mid in cycle]
        # How many of the cycle's own delegates named this motion as the one they fell in behind.
        consensus = {m["id"]: sum(1 for other in members if other.get("replaced_by") == m["id"])
                     for m in members}
        kept = max(members, key=lambda m: (consensus[m["id"]], len(m.get("cosponsors") or []),
                                           -order.get(m["id"], 0)))
        kept["withdrawn"] = False
        kept["restored_from_collision"] = {
            "with": [m["id"] for m in members if m["id"] != kept["id"]],
            "why": "each proposer withdrew in favour of another in the same group, so all of them "
                   "would have left the agenda together"}
        collisions.append({
            "code": "MUTUAL_WITHDRAWAL_COLLISION",
            "motions": sorted(cycle, key=lambda mid: order.get(mid, 0)),
            "proposers": {m["id"]: m.get("proposer") for m in members},
            "kept": kept["id"], "dropped": [m["id"] for m in members if m["id"] != kept["id"]],
            "fell_in_behind": consensus,
            "same_family": len({fam.get(m["id"]) for m in members}) == 1,
            "duplicates": all(_is_duplicate(members[0], m) for m in members[1:]),
            "note": "one motion was restored: the rest of the cycle stays withdrawn, so the "
                    "consolidation still reduces the agenda to a single motion",
        })
    return collisions


# ---- the revision round (spec 33) ---------------------------------------------------------------
def apply_revisions(w: World, mid: str, revision: dict, motions: list, tabled_all: list) -> dict:
    """Withdrawals and amendments of a delegate's own motions after hearing the council."""
    notes = {"withdrawn": [], "amended": [], "rejected": []}
    own = {m["id"]: m for m in motions if m["proposer"] == mid or mid in m.get("cosponsors", [])}
    for item in revision.get("withdraw", []):
        # The structured form carries the stated reason and the motion the delegate fell in behind;
        # older runs send a bare id.
        entry = item if isinstance(item, dict) else {"motion_id": item}
        motion_id = entry.get("motion_id")
        m = own.get(motion_id)
        if m and not m.get("withdrawn"):
            if m["proposer"] != mid and mid in m.get("cosponsors", []):
                m["cosponsors"] = [x for x in m["cosponsors"] if x != mid]
                continue
            if m.get("cosponsors"):
                m["previous_proposer"] = mid
                m["proposer"] = m["cosponsors"].pop(0)
                continue
            m["withdrawn"] = True
            m["withdrawn_by"] = mid
            if entry.get("reason"):
                m["withdrawal_reason"] = entry["reason"]
            if entry.get("replaced_by"):
                m["replaced_by"] = entry["replaced_by"]
            notes["withdrawn"].append(motion_id)
    limit = int(tuning.get(w, "revision.max_amendments"))
    for item in revision.get("amend", [])[:limit]:
        m = own.get(item.get("motion_id"))
        if not m or m.get("withdrawn") or m["proposer"] != mid:
            continue
        candidate = {**m, "value": str(item.get("value", m.get("value", ""))).strip() or m.get("value", ""),
                     "text": str(item.get("text", "")).strip() or m.get("text", "")}
        if isinstance(item.get("conditions"), list):
            from .motion_actions import motion_conditions as _motion_conditions
            candidate["conditions"] = list(item["conditions"])
            candidate["final_conditions"] = _motion_conditions({**candidate})
            candidate["final_motion_text"] = str(candidate.get("text", ""))
        if candidate["value"] == m.get("value") and candidate["text"] == m.get("text") \
                and candidate.get("conditions", m.get("conditions")) == m.get("conditions"):
            continue
        detail = validate_motion_detail(w, candidate)
        if detail:
            notes["rejected"].append({"motion": m["id"], **detail})
            continue
        m.setdefault("revisions", []).append({"value": m.get("value"), "text": m.get("text"),
                                              "conditions": list(m.get("conditions", [])) if m.get("conditions") else []})
        m["value"], m["text"] = candidate["value"], candidate["text"]
        if "conditions" in candidate:
            from .motion_actions import motion_conditions as _final_conditions
            m["conditions"] = _final_conditions({**m, "conditions": candidate.get("conditions")})
        elif m.get("text"):
            from .motion_actions import motion_conditions as _refresh_conditions
            refreshed = _refresh_conditions(m)
            if refreshed or m.get("conditions"):
                m["conditions"] = refreshed
        if m.get("conditions") is not None:
            m["final_conditions"] = list(m.get("conditions") or [])
            m["final_motion_text"] = str(m["text"])
        m["amended"] = True
        notes["amended"].append(m["id"])
    return notes


# ---- conditional votes (spec 34) ----------------------------------------------------------------
METRICS = ("food_ratio", "reserves", "arrears", "unemployment", "army_morale", "army_arrears",
           "inflation", "approval", "deficit")


def resolve_conditionals(w: World, motions: list, votes_by_motion: dict, conditions: dict,
                         opening_values: dict) -> dict:
    """Turn conditional votes into yes / no / abstain.

    conditions: motion id -> member -> condition dict. Metric conditions are tested against the
    state at the start of the session. Motion conditions ('yes if M2 passes') are resolved in
    dependency order using the other motions' provisional outcomes."""
    from .politics import passes
    outcome = {}
    details = {}
    pending = {mid_: dict(conds) for mid_, conds in conditions.items()}
    order = [m["id"] for m in motions]
    for _ in range(3):
        progress = False
        for motion_id in order:
            for member, cond in list(pending.get(motion_id, {}).items()):
                kind = cond.get("kind", "metric")
                met = None
                if kind == "metric":
                    value = opening_values.get(cond.get("metric"))
                    if value is not None:
                        met = value >= cond["value"] if cond.get("operator") == ">=" else value <= cond["value"]
                else:
                    other = cond.get("other_motion")
                    if other in outcome:
                        met = outcome[other] == (cond.get("other_outcome", "passes") == "passes")
                    elif other not in order:
                        met = False
                if met is None:
                    continue
                fallback = cond.get("if_unmet", "abstain")
                votes_by_motion[motion_id][member] = "yes" if met else (fallback if fallback in ("no", "abstain") else "abstain")
                details.setdefault(motion_id, {})[member] = {"condition": cond, "met": met,
                                                             "observed": opening_values.get(cond.get("metric")) if kind == "metric" else outcome.get(cond.get("other_motion")),
                                                             "counted_as": votes_by_motion[motion_id][member]}
                del pending[motion_id][member]
                progress = True
            if not pending.get(motion_id):
                counted = {k: v for k, v in votes_by_motion[motion_id].items() if w.member(k).status == "active"}
                outcome[motion_id] = passes(w, counted)
        if not progress:
            break
    for motion_id, members in pending.items():
        for member, cond in members.items():
            votes_by_motion[motion_id][member] = "abstain"
            details.setdefault(motion_id, {})[member] = {"condition": cond, "met": None, "observed": None,
                                                         "counted_as": "abstain", "note": "condition could not be resolved"}
    return details
