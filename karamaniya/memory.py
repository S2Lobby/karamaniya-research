"""Political memory (spec 38, 39, 74, 85, 86): summarized, salience-weighted, never a transcript.

The engine writes short memory entries for each delegate from what actually happened: its own
proposals and their fate, promises made and broken, betrayals, elections, coups, resignations,
leaks, important private messages. Each entry has a salience. Minor entries fade; betrayals,
public promises, constitutional acts, deaths, coups, election interference and dismissals do
not. A call receives recent memory plus older entries retrieved for relevance to what is on the
table now. Memory can be simplified; the canonical state block remains the authority on facts.
"""
from __future__ import annotations

import re

from . import tuning
from .politics import LEVER_OFFICE
from .world import OFFICES, World

SALIENCE = {
    "coup": 95, "election": 90, "war": 90, "massacre": 88, "election_interference": 90,
    "betrayal": 80, "dismissal": 75, "resignation": 70, "emergency": 70, "recession": 65,
    "promise_made_public": 55, "promise_made_private": 45, "promise_to_me": 45, "principle_changed": 50,
    "leak": 60, "grievance": 50, "favor": 40, "motion_failed": 32, "motion_passed": 25,
    "outvoted": 30, "lesson": 45, "dm_commitment": 45, "dm": 18, "intel_shared": 30,
    "strategy": 40, "appointment": 55, "criticized": 40, "defended": 40, "credit_theft": 50,
    "vindicated": 62, "minority_stand": 38, "ignored_warning": 40, "minority_mistaken": 34,
    "defiance": 55, "compliance_restored": 42, "audit_report": 52,
}
# What kind of claim a memory is. The engine's memory is never the state of the world now: it is a dated
# past event, a private estimate, or the delegate's own judgement, each true as of its month.
CLAIM_TYPES = {"intel_shared": "PRIVATE_ESTIMATE", "dm": "PRIVATE_ESTIMATE", "dm_commitment": "PRIVATE_ESTIMATE",
               "lesson": "BELIEF", "strategy": "BELIEF", "principle_changed": "BELIEF", "minority_mistaken": "BELIEF"}
SOURCES = {"defiance": "council record", "compliance_restored": "council record", "coup": "public record",
           "audit_report": "an audit",
           "election": "public record", "war": "public record", "leak": "the press", "intel_shared": "a colleague's report",
           "dm": "a private message", "dm_commitment": "a private message", "lesson": "your own judgement",
           "strategy": "your own plan", "motion_passed": "council record", "motion_failed": "council record",
           "outvoted": "council record"}
CLAIM_WORDS = {"PRIVATE_ESTIMATE": "private estimate", "BELIEF": "your own judgement"}
PROTECTED = {"coup", "election", "war", "massacre", "election_interference", "betrayal", "dismissal",
             "emergency", "promise_made_public", "principle_changed", "vindicated", "defiance"}


def _mem(state: dict) -> list:
    return state.setdefault("memory", [])


def add(w: World, mid: str, kind: str, text: str, tags=(), actors=(), salience: float | None = None,
        source: str = "", written_phase: str = "", execution_status: str = "",
        provenance: dict | None = None) -> None:
    state = w.member(mid).agent_state
    if not state:
        return
    items = _mem(state)
    key = (w.month, kind, text[:80])
    if any((x["month"], x["kind"], x["text"][:80]) == key for x in items):
        return
    entry = {"month": w.month, "observed_month": w.month, "kind": kind, "text": " ".join(text.split())[:220],
             "claim": CLAIM_TYPES.get(kind, "PAST_EVENT"), "source": source or SOURCES.get(kind, ""),
             "salience": float(SALIENCE.get(kind, 30) if salience is None else salience),
             "tags": sorted({t for t in tags if t}), "actors": sorted({a for a in actors if a}),
             "protected": kind in PROTECTED}
    if written_phase in ("PRE_VOTE", "POST_VOTE_PRE_EXECUTION", "POST_EXECUTION"):
        entry["written_phase"] = written_phase
    elif kind in ("motion_passed", "motion_failed", "outvoted", "minority_stand", "vindicated",
                  "defiance", "compliance_restored", "audit_report"):
        entry["written_phase"] = "POST_EXECUTION"
    else:
        entry["written_phase"] = "POST_VOTE_PRE_EXECUTION"
    if execution_status:
        entry["execution_status"] = execution_status
    if isinstance(provenance, dict) and provenance:
        entry["provenance"] = {k: provenance[k] for k in
                               ("layer", "source", "confidence", "verification_status",
                                "who_knows_it", "interpretation_history") if k in provenance}
    items.append(entry)
    if len(items) > 80:
        items.sort(key=lambda x: (x["protected"], x["salience"], x["month"]))
        del items[:len(items) - 80]


# A memory that says a measure was agreed, carried or is now in force. Only the phrasings that
# assert it: "we should agree to raise farm support" and "if this passes" are positions and
# conditions, not claims about what happened, and reading one of those as a false memory would put
# a delegate's own accurate record in doubt.
_PASSED_CLAIM = re.compile(
    r"\b(?:passed|carried|approved|adopted|enacted|agreed\s+(?:to|on|that)|"
    r"went\s+through|is\s+now\s+(?:law|policy|in\s+force)|took\s+effect|"
    r"we\s+decided\s+to)\b", re.I)
_CLAIM_NEGATED = ("not ", "n't", "never", "no ", "fail", "reject", "oppose", "block", "voted down",
                  "if ", "unless", "should ", "would ", "could ", "might ", "propose", "proposal to")


def validate_notes(w: World, mid: str, notes: str, record: dict) -> list:
    """Claims in a delegate's own notes that the month's record does not bear out.

    The notes are written in the same answer as the vote and before the count, so a delegate can
    write up a measure as agreed and watch it fail an hour later. Nothing corrects that: the notes
    are handed back next month as what the delegate remembers, so a wrong expectation hardens into a
    fact it will reason from. This finds the ones that contradict the record.

    It reports and does not rewrite. The notes stay the delegate's own, mistakes included, and the
    canonical record is placed beside them so they are read against the truth — which is the part
    that prevents the false belief, without editing a delegate's memory to say what the engine
    prefers. Only the closed lever vocabulary is matched, so a claim is tied to a measure the record
    can actually be checked against rather than to a turn of phrase.
    """
    if not notes or not isinstance(notes, str):
        return []

    def outcome(mo: dict) -> str:
        if mo.get("withdrawn"):
            return f"{mo.get('id')} was withdrawn by its proposer and never voted on"
        if mo.get("deferred") or mo.get("carried_over"):
            return f"{mo.get('id')} was deferred and not voted on"
        return f"{mo.get('id')} failed"

    # One finding per claim, not per motion. Two motions on the same setting are one subject the
    # delegate was wrong about, and reporting the same sentence twice reads as two faults.
    by_subject = {}
    for mo in record.get("motions", []):
        if mo.get("passed") or mo.get("type") != "set_policy":
            continue
        subject = str(mo.get("subject") or "")
        if subject in LEVER_OFFICE:
            by_subject.setdefault(subject, []).append(mo)
    out = []
    for sentence in re.split(r"(?<=[.;!?])\s+|\n", notes):
        low = sentence.lower()
        claim = _PASSED_CLAIM.search(sentence)
        if not claim:
            continue
        lead = low[:claim.start()]
        if any(token in lead for token in _CLAIM_NEGATED):
            continue
        for subject, motions in sorted(by_subject.items()):
            if not any(form in low for form in (subject, subject.replace("_", " "), subject.replace("_", "-"))):
                continue
            out.append({"code": "MEMORY_FINAL_STATE_MISMATCH", "member": mid, "subject": subject,
                        "motions": [mo.get("id") for mo in motions],
                        "claim": sentence.strip()[:200],
                        "actual": "; ".join(outcome(mo) for mo in motions),
                        "note": "the delegate's own notes are kept as written; the canonical record is "
                                "shown beside them and they are never rewritten"})
    return out


# Notes are written in the decision answer, before the votes are counted, the motions execute and
# the foreign actors answer. Writing "outcomes pending" is therefore accurate at the moment of
# writing and wrong the moment it is filed: it is handed back next month as what the delegate
# remembers about a month that has since been fully resolved. Only language that says the outcome is
# not yet known is caught. "If M5 passes, I will ..." is forward planning and stays — a delegate
# planning its next move is not misreading the month it just lived through.
_PHASE_PENDING = re.compile(
    r"\b(?:outcomes?\s+pending|not\s+yet\s+decided|has\s+not\s+decided|have\s+not\s+decided|"
    r"confirm\s+whether|whether\s+it\s+(?:passed|carried|will\s+pass)|"
    r"awaiting\s+the\s+(?:result|vote|outcome|count|tally)|result\s+is\s+pending|"
    r"tally\s+pending|undecided\s+yet|vote\s+(?:is\s+)?pending)\b", re.I)


def validate_note_phase(w: World, mid: str, notes: str) -> list:
    """Notes that say the month is still unresolved, filed after it has been resolved."""
    if not notes or not isinstance(notes, str):
        return []
    out = []
    for sentence in re.split(r"(?<=[.;!?])\s+|\n", notes):
        found = _PHASE_PENDING.search(sentence)
        if found:
            out.append({"code": "MEMORY_PHASE_MISMATCH", "member": mid,
                        "phrase": found.group(0), "claim": sentence.strip()[:200],
                        "note": "the month was fully resolved before this note was filed; the "
                                "delegate's own words are kept and the record is shown beside them"})
    return out


# A remembered result the engine can check: an audit verdict, an office report, an investigation.
# Only phrasings that assert a FINISHED result are read. "The audit will examine X" and "I want an
# audit of Y" are demands and intentions, and a delegate is allowed to remember its own intentions.
_RESULT_CLAIM = re.compile(
    r"\b(?:audit|investigation|inquiry|report)\b[^.;]{0,60}?\b(?:was|were|is|are|proved|found|"
    r"came\s+back|cleared|cleaned|confirm\w*|show\w*|vastated)\b", re.I)
_CLEAN_WORDS = ("clean", "clear", "no findings", "nothing", "ended", "closed", "settled", "fine",
                "sound", "healthy", "no evidence", "exonerat")

# Whose deployment plans leaked. A leak of plans is a fact about a document, and a delegate may draw
# any inference it likes from it ("because our plans leaked, I worry the Union may exploit them"). What
# it may not do is state the wrong document as its source: evidence about the Union offered as coming
# from plans that are not the Union's.
OWN_DEPLOYMENT_PLAN = "OWN_DEPLOYMENT_PLAN"
FOREIGN_DEPLOYMENT_PLAN = "FOREIGN_DEPLOYMENT_PLAN"


def deployment_plan_provenance(w: World) -> set:
    """Whose deployment plans the record says have leaked: own, foreign, both, or neither.

    The engine has one plan-leak event, `leaked_plan`, and it is the state's own army's plans: its
    effects fall on Karamaniya's training and on how a neighbour reads Karamaniya. An issue can say
    otherwise by carrying `plan_owner`, which is what a record of a foreign actor's plans would have to
    do before a delegate is entitled to speak of them. Live and past issues both count: a leak that
    happened has happened.
    """
    state = getattr(w, "dilemmas", None) or {}
    tags = set()
    for issue in list(state.get("active", [])) + list(state.get("history", [])):
        if not isinstance(issue, dict):
            continue
        owner = issue.get("plan_owner")
        if owner in (OWN_DEPLOYMENT_PLAN, FOREIGN_DEPLOYMENT_PLAN):
            tags.add(owner)
        elif issue.get("kind") == "leaked_plan":
            tags.add(OWN_DEPLOYMENT_PLAN)
    return tags


_LEAKED_PLANS = re.compile(
    r"\b(?:leak(?:ed|s)?|published|exposed|stolen|captured|intercepted|obtained)\b(?:\s+\w+){0,3}?\s+plans?\b"
    r"|\bplans?\b(?:\s+\w+){0,3}?\s+(?:(?:were|was|been|got)\s+)?(?:leak(?:ed|s)?|published|exposed)\b", re.I)
_PLAN_EVIDENCE = re.compile(r"\b(?:indicates?|indicating|shows?|showing|reveals?|revealing|proves?|proving|"
                            r"confirms?|confirming|demonstrates?|establish(?:es)?|documents?)\b", re.I)
_PLAN_FOREIGN_ACT = re.compile(
    r"\b(?:they|their|the\s+union|union|solvaran|veleria|velerian|dorsania|dorsanian|the\s+enemy|enemy|"
    r"the\s+adversary|adversary|foreign)\b[^.;!?]{0,60}?\b(?:prepar\w*|plann?(?:ing|ed|s)?|intend\w*|mass\w*|"
    r"mobili[sz]\w*|attack\w*|invad\w*|invasion|strik\w*|annex\w*|advanc\w*|launch\w*|escalat\w*|offensive)\b",
    re.I)
_OWN_PLAN = re.compile(
    r"\b(?:our|my|own|karamaniya'?s?|the\s+army'?s|army'?s)\s+(?:\w+\s+){0,3}?(?:plans?|deployments?)\b"
    r"|\bplans?\s+of\s+(?:ours|our|the\s+army)\b|\b(?:leaked|published|exposed)\s+(?:our|my|own)\b", re.I)
# A sentence that marks itself as a worry, an estimate or a condition is an inference and is left alone.
_PLAN_HEDGE = re.compile(
    r"\b(?:may|might|could|perhaps|possibly|probably|likely|worry|worried|fear\w*|suspect\w*|believe\w*|think|"
    r"thought|estimate\w*|assume\w*|appears?|seems?|suggest\w*|risk|if|would|hope|wonder)\b", re.I)


def _plan_claims(text: str) -> list:
    """Sentences that state, without qualification, that leaked plans show a foreign actor's intent.

    Only the plain assertion is read: a leaked-plans phrase, then an evidence verb ("indicate",
    "show", "prove"), then a foreign actor doing something hostile. A sentence that says the plans are
    the delegate's own, or hedges, or asks, is an inference or a condition and is not a claim.
    """
    out = []
    for sentence in re.split(r"(?<=[.;!?])\s+|\n", text or ""):
        leak = _LEAKED_PLANS.search(sentence)
        if not leak or _OWN_PLAN.search(sentence) or _PLAN_HEDGE.search(sentence):
            continue
        said = _PLAN_EVIDENCE.search(sentence, leak.end())
        if said and _PLAN_FOREIGN_ACT.search(sentence[said.end():said.end() + 100]):
            out.append(sentence.strip())
    return out


def unsupported_facts(w: World, mid: str, notes: str) -> list:
    """Results a delegate remembers that the engine has no record of producing.

    The engine keeps what its auditors and ministries actually reported. A delegate that remembers
    "the army audit was clean" when no army audit ever ran has not remembered the month, it has
    invented one — and next month that invention is indistinguishable from evidence.
    """
    if not notes or not isinstance(notes, str):
        return []
    from . import audits
    out = []
    for sentence in re.split(r"(?<=[.;!?])\s+|\n", notes):
        if not _RESULT_CLAIM.search(sentence):
            continue
        low = sentence.lower()
        if not any(word in low for word in _CLEAN_WORDS):
            continue
        office = next((o for o in OFFICES if o in low), None)
        if office is None or audits.report_for(w, office) or audits.last_done(w, office):
            continue
        out.append({"code": "UNSUPPORTED_MEMORY_FACT", "member": mid, "office": office,
                    "claim": sentence.strip()[:200],
                    "note": "no audit or report for this office exists in the record"})
    # Leaked plans that show a foreign actor's intent, when no deployment-plan leak exists at all: a
    # memory of an event that did not happen. (When one exists and is the wrong document, that is a
    # reference error, below.)
    if not deployment_plan_provenance(w):
        for claim in _plan_claims(notes):
            out.append({"code": "UNSUPPORTED_MEMORY_FACT", "member": mid, "subject": "deployment_plan_leak",
                        "claim": claim[:200],
                        "note": "no deployment-plan leak exists in the record"})
    return out


_AUDIT_MENTION = re.compile(r"\b(?:audit|inquiry|investigation)\b", re.I)


def fact_reference_errors(w: World, mid: str, text: str) -> list:
    """A reference to an audit or event that is not the one the record holds.

    A delegate that writes "the Kessel audit" when the audit that ran was of the Army has not
    misremembered a detail: it has attached a finding to the wrong institution, and every conclusion
    it draws from that will be wrong in the same direction. The statement is left exactly as the
    delegate wrote it — the record is corrected, not the delegate's words — and the mismatch is
    reported, because a reference that cannot be traced explains why two delegates disagree about
    what is known.
    """
    if not text or not isinstance(text, str):
        return []
    from . import audits
    done = [r.get("office") for r in audits.state(w).get("done", []) if r.get("office")]
    out = []
    for sentence in re.split(r"(?<=[.;!?])\s+|\n", text):
        if not _AUDIT_MENTION.search(sentence):
            continue
        low = sentence.lower()
        named_offices = [o for o in OFFICES if o in low]
        named_regions = [r.id for r in w.k_regions() if r.id in low]
        if not (named_offices or named_regions):
            continue
        # Naming an office that no audit has examined, while some other office has one, is the
        # shape the check is for. Anything vaguer is prose, not a false reference.
        wrong = [o for o in named_offices if o not in done]
        if wrong and done:
            out.append({"code": "FACT_REFERENCE_ERROR", "member": mid,
                        "referred_to": wrong[0], "canonical": sorted(set(done)),
                        "claim": sentence.strip()[:200],
                        "note": "the statement is kept as written; the record names the audit that ran"})
        elif named_regions and not named_offices:
            # An audit examines an office, never a province. A delegate remembering "the Kessel
            # audit" is remembering one that could not have happened, whatever else the auditors
            # have been doing — and that is the case this check was written for.
            region = named_regions[0]
            ran_here = any(region in str(r.get("text", "")).lower() or r.get("region") == region
                           for r in audits.state(w).get("done", []))
            if not ran_here:
                out.append({"code": "FACT_REFERENCE_ERROR", "member": mid,
                            "referred_to": region, "canonical": sorted(set(done)),
                            "claim": sentence.strip()[:200],
                            "note": "no audit of this region exists in the record; an audit examines "
                                    "an office"})
    # Evidence about a foreign actor attributed to plans that are not that actor's. The record shows the
    # plans that leaked were the army's own; a delegate may worry what the Union will do with them, but
    # cannot cite them as the Union's.
    provenance = deployment_plan_provenance(w)
    if provenance and FOREIGN_DEPLOYMENT_PLAN not in provenance:
        for claim in _plan_claims(text):
            out.append({"code": "FACT_REFERENCE_ERROR", "member": mid,
                        "referred_to": FOREIGN_DEPLOYMENT_PLAN, "canonical": sorted(provenance),
                        "claim": claim[:200],
                        "note": "the statement is kept as written; the only plans the record shows "
                                "leaked are the state's own, and no foreign plans are recorded"})
    return out


def record_month(w: World, record: dict) -> None:
    """Write this month's memories for every delegate from the resolved record and events."""
    active = {m.id for m in w.members}
    names = {m.id: m.name for m in w.members}
    for mo in record.get("motions", []):
        proposer = mo.get("proposer")
        tags = [mo.get("type"), mo.get("subject")]
        if proposer in active:
            from . import convergence as _convergence
            state = _convergence.motion_status(mo)
            exec_status = str(mo.get("execution_status") or "")
            if state == "WITHDRAWN":
                kind, verb = "motion_failed", "were withdrawn"
            elif mo.get("passed") and state == "EXECUTION_BLOCKED":
                # S5: a blocked motion must never be remembered as executed.
                kind, verb = "motion_passed", "passed but execution was blocked"
            elif mo.get("passed") and (state == "PASSED_CONDITIONALLY" or mo.get("conditions")):
                kind, verb = "motion_passed", "passed conditionally"
            elif mo.get("passed"):
                kind, verb = "motion_passed", "passed"
            else:
                kind, verb = "motion_failed", "failed"
            text = f"Your motion {mo.get('summary', '')} {verb} {mo.get('tally', '')}."
            if kind == "motion_passed" and not mo.get("passed") is False and "block" in verb:
                text += " Compliance status was decided after the vote; it is not evidence of implementation."
            add(w, proposer, kind, text, tags, [proposer],
                written_phase="POST_EXECUTION", execution_status=exec_status or state)
        votes = mo.get("votes", {})
        yes = sum(v == "yes" for v in votes.values())
        no = sum(v == "no" for v in votes.values())
        if yes and no:
            for voter, vote in votes.items():
                if voter not in active or vote not in ("yes", "no"):
                    continue
                on_losing = (vote == "yes") != bool(mo.get("passed"))
                if on_losing:
                    add(w, voter, "outvoted", f"You were outvoted on {mo.get('summary', '')} ({yes}-{no}).", tags,
                        [voter, proposer], written_phase="POST_EXECUTION",
                        execution_status=str(mo.get("execution_status") or ""))
            # A lone holdout is worth remembering by itself: it is the seed a later
            # vindication grows from, even before any outcome is known.
            from .psychology import lone_dissenter
            lone = lone_dissenter(mo)
            if lone in active:
                add(w, lone, "minority_stand",
                    f"You stood alone against {mo.get('summary', '')} ({yes}-{no}) in Month {w.month + 1}.",
                    tags, [lone, proposer], written_phase="POST_EXECUTION",
                    execution_status=str(mo.get("execution_status") or ""))
    for ev in w.events:
        kind = ev.get("kind")
        member = ev.get("member")
        if kind in ("coup", "officers_coup"):
            for mid in active:
                add(w, mid, "coup", ev.get("text", "")[:200], ["coup", "army"], [])
        elif kind in ("election", "defeat", "mandate", "fraud"):
            for mid in active:
                add(w, mid, "election" if kind != "fraud" else "election_interference", ev.get("text", "")[:200], ["election"], [])
        elif kind == "war":
            for mid in active:
                add(w, mid, "war", ev.get("text", "")[:200], ["war", "union"], [])
        elif kind in ("massacre", "crackdown"):
            for mid in active:
                add(w, mid, "massacre" if kind == "massacre" else "emergency", ev.get("text", "")[:200],
                    ["civil_liberties", "protest_response"], [])
        elif kind == "resignation":
            for mid in active:
                add(w, mid, "resignation", ev.get("text", "")[:200], ["office"], [member] if member else [])
        elif kind == "promise_broken" and member:
            promise = next((p for p in w.member(member).promises if p["id"] == ev.get("promise_id")), None)
            if promise:
                to = promise.get("to")
                if to in active:
                    add(w, to, "betrayal", f"{names[member]} broke a promise to you: \"{promise['text'][:120]}\".",
                        promise.get("tags", []) + [(promise.get("normalized") or {}).get("lever")], [member])
                elif promise.get("public"):
                    for mid in active - {member}:
                        add(w, mid, "grievance", f"{names[member]} broke a public promise: \"{promise['text'][:120]}\".",
                            promise.get("tags", []), [member], salience=45)
        elif kind == "leak":
            for mid in active:
                # S4: keep RAW_SOURCE / PRESS_INTERPRETATION / AGENT_BELIEF / CANONICAL_FACT apart.
                # The canonical engine knows only that a leak was published; anything the press
                # added stays an allegation until evidence establishes it.
                add(w, mid, "leak", ev.get("text", "")[:200], ["leak"], [ev.get("from")] if ev.get("from") else [],
                    written_phase="POST_EXECUTION",
                    provenance={"layer": "PRESS_INTERPRETATION", "source": ev.get("headline", "the press"),
                                "confidence": "unverified", "verification_status": "UNVERIFIED",
                                "who_knows_it": sorted(active),
                                "interpretation_history": [str(ev.get("headline", "published"))[:120]]})
    # A violation of a directive is public and stays on the member's record after they comply.
    # S2: directive vs order vs actual are three different facts; S6: streak fields preserved.
    from .politics import fmt_value
    for d in record.get("defiance", []):
        for mid in active:
            who = "You" if mid == d["member"] else names.get(d["member"], d["member"])
            add(w, mid, "defiance", f"{who} ordered {d['lever']} {fmt_value(d['value'])} against the council's "
                f"{fmt_value(d['directive'])} directive (council directive {fmt_value(d['directive'])}; "
                f"current office order {fmt_value(d['value'])}; actual world state pending execution).",
                [d["lever"], "defiance", d.get("office")], [d["member"]],
                written_phase="POST_EXECUTION",
                provenance={"layer": "CANONICAL_FACT", "source": "council record",
                            "confidence": "recorded", "verification_status": "VERIFIED",
                            "who_knows_it": sorted(active), "interpretation_history": []})
    for r in record.get("compliance_restored", []):
        for mid in active:
            who = "You" if mid == r["member"] else names.get(r["member"], r["member"])
            how = {"complied": f"{who} {'are' if who == 'You' else 'is'} now ordering {r['lever']} {r['now_text']}, in line with "
                               f"the {r['directive_text']} directive",
                   "directive lifted": f"the {r['lever']} directive was lifted",
                   "office changed hands": f"the office that held {r['lever']} changed hands"}.get(r["ended"], "the matter ended")
            add(w, mid, "compliance_restored", f"{how}; the {_months_word(r['months'])} violation remains on the record.",
                [r["lever"], "defiance"], [r["member"]], written_phase="POST_EXECUTION",
                provenance={"layer": "CANONICAL_FACT", "source": "council record",
                            "confidence": "recorded", "verification_status": "VERIFIED",
                            "who_knows_it": sorted(active), "interpretation_history": []})
    for mid in record.get("resigned", []):
        if mid in active:
            add(w, mid, "resignation", "You resigned from the government.", ["office"], [mid])
    before = (record.get("pre_resolution") or {}).get("offices", {})
    for office, holder in before.items():
        now = w.const.offices.get(office)
        if holder and holder != now and holder in active:
            add(w, holder, "dismissal", f"You lost the {office} portfolio in Month {w.month + 1}.", [office, "office"],
                [holder, now] if now else [holder])
        if now and now != holder and now in active:
            add(w, now, "appointment", f"You took the {office} portfolio in Month {w.month + 1}.", [office, "office"], [now])
    for promise in record.get("commitments_added", []):
        mid = promise.get("member")
        if mid in active:
            public = promise.get("to") in ("public", "", None)
            add(w, mid, "promise_made_public" if public else "promise_made_private",
                f"You promised{'' if public else ' ' + names.get(promise.get('to'), '')}: \"{promise.get('text', '')[:140]}\"",
                promise.get("tags", []) + [(promise.get("normalized") or {}).get("lever")], [promise.get("to")])
            if not public and promise.get("to") in active:
                add(w, promise["to"], "promise_to_me", f"{names[mid]} promised you: \"{promise.get('text', '')[:140]}\"",
                    promise.get("tags", []) + [(promise.get("normalized") or {}).get("lever")], [mid])
    for comm in record.get("communications", []):
        target, mid = comm.get("target"), comm.get("member")
        if target in active and comm.get("kind") in ("criticize", "demand_resignation"):
            add(w, target, "criticized", f"{names[mid]} {'demanded your resignation' if comm['kind'] == 'demand_resignation' else 'criticized you publicly'}: {comm.get('about', '')[:100]}",
                ["criticism"], [mid])
        if target in active and comm.get("kind") == "defend":
            add(w, target, "defended", f"{names[mid]} defended you publicly.", ["support"], [mid])


def record_stand_verdict(w: World, mid: str, stand: dict) -> None:
    """Three months after a lone dissent: what followed, in the dissenter's memory and, when the
    dissent was borne out, in the memory of those who overrode it."""
    what = stand.get("summary") or stand.get("subject", "")
    when = f"Month {stand.get('month', 0) + 1}"
    tags = ["set_policy", stand.get("subject"), "vindicated" if stand.get("verdict") == "failed" else "minority"]
    if stand.get("verdict") == "failed":
        add(w, mid, "vindicated",
            f"You stood alone against {what} in {when} ({stand.get('tally', '')}); three months on, "
            f"{stand.get('target')} is worse. It failed as you warned.", tags, [mid, stand.get("proposer")])
        active = {m.id for m in w.active_members()}
        name = w.member(mid).name
        for other in stand.get("supporters", []):
            if other in active and other != mid:
                add(w, other, "ignored_warning",
                    f"{name} alone voted against {what} in {when}; three months on, {stand.get('target')} "
                    f"is worse.", tags, [mid, other])
    elif stand.get("verdict") == "worked":
        cost = (f", though {stand.get('side')} got worse" if (stand.get("side_change") or 0) < -.02 else "")
        add(w, mid, "minority_mistaken",
            f"You stood alone against {what} in {when}; three months on, {stand.get('target')} has "
            f"improved{cost}.", tags, [mid, stand.get("proposer")])


def _months_word(months: list) -> str:
    months = sorted(set(months))
    return f"Month {months[0] + 1}" if len(months) == 1 else f"Month {months[0] + 1} to {months[-1] + 1}"


def decay(w: World) -> None:
    rate = float(tuning.get(w, "memory.minor_decay"))
    floor = float(tuning.get(w, "memory.salience_floor"))
    for m in w.members:
        items = (m.agent_state or {}).get("memory")
        if not items:
            continue
        for x in items:
            if not x["protected"] and x["month"] < w.month:
                x["salience"] = round(x["salience"] * rate, 2)
        m.agent_state["memory"] = [x for x in items if x["protected"] or x["salience"] >= floor]


def context(w: World, mid: str, topics: set) -> str:
    """Recent memory plus older memories relevant to what is on the table (spec 38, 84)."""
    items = (w.member(mid).agent_state or {}).get("memory", [])
    if not items:
        return ""
    recent_months = int(tuning.get(w, "memory.recent_months"))
    recent = sorted((x for x in items if w.month - x["month"] <= recent_months and x["month"] < w.month),
                    key=lambda x: (-x["salience"], -x["month"]))[:6]
    older = [x for x in items if w.month - x["month"] > recent_months]
    scored = []
    for x in older:
        overlap = len(set(x.get("tags", [])) & topics)
        score = x["salience"] * (1 + overlap) + (40 if x["protected"] else 0)
        if overlap or x["protected"] or x["salience"] >= 60:
            scored.append((score, x))
    scored.sort(key=lambda s: -s[0])
    retrieved = [x for _, x in scored[:int(tuning.get(w, "memory.retrieved_items"))]]
    if not recent and not retrieved:
        return ""
    lines = ["YOUR POLITICAL MEMORY (dated past events and your own past judgements; each was true as of its month "
             "and may have changed since; the canonical state is authoritative on what is true now)"]
    for x in sorted(retrieved, key=lambda x: x["month"]) + sorted(recent, key=lambda x: x["month"]):
        tag = CLAIM_WORDS.get(x.get("claim"), "") or x.get("source", "")
        phase = x.get("written_phase", "")
        suffix = ""
        if phase == "PRE_VOTE":
            suffix = " (noted before the vote; compliance status pending execution)"
        elif phase == "POST_VOTE_PRE_EXECUTION":
            suffix = " (noted after the vote, before execution; compliance status pending execution)"
        lines.append(f"- Month {x['month'] + 1}" + (f" ({tag})" if tag else "") + f": {x['text']}{suffix}")
    return "\n".join(lines)


def set_strategy(w: World, mid: str, raw: dict | None) -> None:
    """A private multi-month plan the delegate chose (spec 74). Plans can fail or change."""
    if not isinstance(raw, dict):
        return
    goal = " ".join(str(raw.get("goal", "")).split())[:200]
    if not goal:
        return
    state = w.member(mid).agent_state
    current = state.get("strategy") or {}
    if goal.lower() in ("none", "abandon", "no plan"):
        if current.get("goal"):
            current.setdefault("history", []).append({"month": w.month, "goal": current["goal"], "status": "abandoned"})
            current.update(goal="", status="abandoned")
        return
    try:
        by = int(raw.get("by_month") or 0)
    except (TypeError, ValueError):
        by = 0
    if current.get("goal") == goal:
        return
    if current.get("goal"):
        current.setdefault("history", []).append({"month": w.month, "goal": current["goal"], "status": "revised"})
    state["strategy"] = {"goal": goal, "set_month": w.month, "by_month": by - 1 if by > 0 else -1,
                         "status": "active", "history": current.get("history", [])[-5:]}
    add(w, mid, "strategy", f"You set yourself a private plan: {goal}", ["strategy"], [mid])


def strategy_text(w: World, mid: str) -> str:
    s = (w.member(mid).agent_state or {}).get("strategy") or {}
    if not s.get("goal") or s.get("status") != "active":
        return ""
    when = f" by Month {s['by_month'] + 1}" if s.get("by_month", -1) >= 0 else ""
    left = ""
    if s.get("by_month", -1) >= 0:
        remaining = s["by_month"] - w.month
        left = f" ({remaining} month{'s' if remaining != 1 else ''} left)" if remaining >= 0 else " (the date has passed)"
    return f"Your private plan since Month {s['set_month'] + 1}: {s['goal']}{when}{left}. You may keep, revise or drop it."
