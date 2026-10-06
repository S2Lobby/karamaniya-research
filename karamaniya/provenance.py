"""Where a claim came from, and how far it has travelled from what was actually observed.

Six layers are easy to collapse into one, and collapsing them is how a simulation starts
inventing politics that never happened:

    RAW_SOURCE          what was actually said or written
    PRESS_REPORT        how a paper reported it
    PRESS_INTERPRETATION how a paper framed it, including motive and certainty it cannot know
    AGENT_BELIEF        what one delegate concluded
    PUBLIC_BELIEF       what the public concluded
    CANONICAL_FACT      what the engine knows to have happened

The example this exists to prevent: a commander writes "our fiscal fragility may cause a coup".
A paper prints "commander discussed using force". A delegate reads the paper and acts as though a
coup was planned. All three of those are real political facts — the reporting and the belief
genuinely happened — but the engine must never let the third overwrite the first. So the raw text
is stored once and is never rewritten by anything downstream, and `canonical()` derives what
actually happened from the raw source only.

Journalistic distortion is a feature, not a bug: a public that only ever sees accurate reporting
cannot be misled, and a great deal of politics is the study of a public being misled. What is
forbidden is the engine forgetting which layer it is reading.
"""
from __future__ import annotations

import re

from .world import World, clamp, rng_for

RAW_SOURCE = "RAW_SOURCE"
PRESS_REPORT = "PRESS_REPORT"
PRESS_INTERPRETATION = "PRESS_INTERPRETATION"
AGENT_BELIEF = "AGENT_BELIEF"
PUBLIC_BELIEF = "PUBLIC_BELIEF"
CANONICAL_FACT = "CANONICAL_FACT"

LAYERS = (RAW_SOURCE, PRESS_REPORT, PRESS_INTERPRETATION, AGENT_BELIEF, PUBLIC_BELIEF, CANONICAL_FACT)
# Layers that describe what an observer concluded, as opposed to what was observed.
INTERPRETIVE = (PRESS_INTERPRETATION, AGENT_BELIEF, PUBLIC_BELIEF)

STORE_CAP = 160

ALLEGED = "ALLEGED"
PARTIALLY_CORROBORATED = "PARTIALLY_CORROBORATED"
CORROBORATED = "CORROBORATED"
DISPROVEN = "DISPROVEN"
UNRESOLVED = "UNRESOLVED"
ALLEGATION_STATUSES = (ALLEGED, PARTIALLY_CORROBORATED, CORROBORATED, DISPROVEN, UNRESOLVED)
_EVIDENCED = (PARTIALLY_CORROBORATED, CORROBORATED, DISPROVEN)

# Phrases that carry a claim about intent rather than about what was said. A single-word list is
# not enough: "use the army to remove the council" asserts an intention without containing any one
# word that would appear in a keyword list, so the patterns are phrasal.
_INTENT_PATTERNS = (
    r"\bcoup\b", r"\bseize\b", r"\bseizing\b", r"\boverthrow\b", r"\bpurge\b", r"\bconspir\w*\b",
    r"\bplot\b", r"\barrest\b", r"\bby force\b", r"\btake over\b", r"\bmarch on\b",
    r"\buse (?:the )?(?:army|military|force|troops|police|soldiers)\b",
    r"\buse (?:our|the) (?:units|divisions|garrison)\b",
    r"\bremove the (?:council|government|head)\b",
    r"\bdeploy \w+ against\b", r"\bmobilize against\b", r"\bsend (?:the )?troops\b",
    r"\bwe will (?:act|move|strike)\b", r"\bwe are prepared to (?:act|move)\b",
)
_INTENT_RE = re.compile("|".join(_INTENT_PATTERNS), re.IGNORECASE)
# "if" is deliberately not here: "we will seize the treasury if the vote fails" is a conditional
# threat, which is an assertion of intent, not a hedge.
_HEDGES = ("may", "might", "could", "perhaps", "possibly", "risk", "fear", "worry", "concern")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _has_intent(text: str) -> bool:
    return bool(_INTENT_RE.search(text))


def _is_hedged(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in _HEDGES)


def canonical(raw_text: str) -> dict:
    """What the engine knows happened, derived from the raw source and nothing else.

    The distinction that matters: `asserts_intent` is true only when the source itself stated an
    intention. A hedged warning about a risk is not an assertion of intent, and no amount of
    press framing afterwards can turn it into one.
    """
    text = _clean(raw_text)
    return {"observed": "speech_act",
            "text": text,
            "asserts_intent": bool(_has_intent(text) and not _is_hedged(text)),
            "hedged": _is_hedged(text),
            "readable_as": ("a warning or speculation about a risk" if _is_hedged(text)
                            else "a statement of intent" if _has_intent(text) else "an ordinary statement")}


def _distort(text: str, rng) -> tuple[str, str]:
    """Reframe for the press. Returns (framed text, what the framing added).

    Deliberately bounded. The paper can drop a hedge, attribute a motive, or promote a worry into
    a plan — the three distortions that actually move politics. It cannot invent a subject that was
    not in the source, because then the raw layer would carry no information at all.
    """
    out = text
    added = []
    if _is_hedged(text) and _has_intent(text):
        # The hedge is what the paper drops: "may" becomes "is preparing to".
        for hedge in ("may", "might", "could", "possibly", "perhaps"):
            if hedge in out.lower():
                out = re.sub(rf"\b{hedge}\b", "is preparing to", out, count=1, flags=re.IGNORECASE)
                added.append("dropped the hedge")
        for soft in ("risk of", "fear of", "concern about", "worry about"):
            if soft in out.lower():
                out = re.sub(rf"\b{soft}\b", "", out, count=1, flags=re.IGNORECASE)
                added.append("removed the qualifier")
    elif not _has_intent(text) and rng.random() < 0.35:
        out = f"{text.rstrip('.')}, though sources describe private intentions that cannot be printed"
        added.append("attributed an unstated motive")
    if rng.random() < 0.30:
        out = f"{out.rstrip('.')}. Ministers are said to be furious"
        added.append("added an unverifiable reaction")
    return _clean(out), "; ".join(added)


def record(w: World, raw_text: str, *, subject: str = "", source: str = "private communication",
           speaker: str = "", origin: str = "intelligence", distort: bool = True) -> dict:
    """Lay a claim down with all of its layers, keeping the raw source immutable."""
    store = w.institutions.setdefault("provenance", {})
    pid = f"P{w.month}-{len(store) + 1}"
    raw = _clean(raw_text)
    fact = canonical(raw)
    rng = rng_for(w.seed, w.month, f"provenance:{pid}:{source}")
    if distort:
        press_text, added = _distort(raw, rng)
    else:
        press_text, added = raw, ""
    overstates = distortion_claimed(fact, press_text, added)
    report_layer = {"text": press_text, "month": w.month, "source": "press"}
    if added:
        report_layer["distortion_added"] = added
    interpretation = {"text": press_text, "month": w.month, "source": "press",
                      "framing": "asserts intent the source did not state" if overstates
                                 else "follows the source"}
    record_ = {
        "id": pid, "month": w.month, "subject": subject, "speaker": speaker, "origin": origin,
        "source": source,
        "layers": {RAW_SOURCE: {"text": raw, "month": w.month, "source": source, "immutable": True},
                   PRESS_REPORT: report_layer},
        "canonical": fact,
        "allegations": [],
        "known_by": [],
        "public_status": "published" if added else "quiet",
    }
    # The interpretation layer exists whenever a paper framed the item, whether or not the
    # framing went beyond the source: "follows the source" is itself useful to record.
    if _has_intent(raw) or added:
        record_["layers"][PRESS_INTERPRETATION] = interpretation
    store[pid] = record_
    if len(store) > STORE_CAP:
        for key in sorted(store, key=lambda k: (store[k]["month"], k))[:len(store) - STORE_CAP]:
            store.pop(key, None)
    return record_


def distortion_claimed(fact: dict, press_text: str, added: str) -> bool:
    """True when the press layer asserts more than the raw source supports."""
    if not added:
        return False
    return bool(_has_intent(press_text) and not fact["asserts_intent"])


def layer(w: World, pid: str, which: str) -> dict | None:
    rec = (w.institutions.get("provenance") or {}).get(pid)
    if rec is None:
        raise KeyError(pid)
    if which == CANONICAL_FACT:
        return rec["canonical"]
    return rec["layers"].get(which)


def raw_text(w: World, pid: str) -> str:
    """The immutable source. Nothing downstream may alter what this returns."""
    return layer(w, pid, RAW_SOURCE)["text"]


def press_text(w: World, pid: str) -> str:
    entry = layer(w, pid, PRESS_REPORT)
    return entry["text"] if entry else ""


def believes(w: World, pid: str, holder: str, layer_name: str = PRESS_REPORT,
             version: str | None = None) -> dict:
    """Record that someone concluded something from one of these layers.

    A belief is stored with the layer it came from, so a delegate who believed the press framing
    of a hedged warning can later be shown to have believed the press framing — not the source.
    """
    rec = (w.institutions.get("provenance") or {}).get(pid)
    if rec is None:
        raise KeyError(pid)
    entry = rec["layers"].get(layer_name)
    if entry is None:
        raise KeyError(layer_name)
    belief = {"holder": holder, "from_layer": layer_name, "text": version or entry["text"],
              "month": w.month,
              "matches_canonical": (version or entry["text"]) == rec["canonical"]["text"]}
    rec.setdefault("beliefs", []).append(belief)
    if holder not in rec["known_by"]:
        rec["known_by"].append(holder)
    return belief


# ---- allegations -------------------------------------------------------------------------------
def allege(w: World, pid: str, claim: str, *, against: str, source: str,
           confidence: float, month: int | None = None) -> dict:
    """File an allegation. It starts ALLEGED and stays there until evidence says otherwise."""
    rec = (w.institutions.get("provenance") or {}).get(pid)
    if rec is None:
        raise KeyError(pid)
    entry = {"id": f"A{len(rec['allegations']) + 1}", "provenance": pid, "claim": _clean(claim),
             "against": against, "source": source, "confidence": round(clamp(confidence), 3),
             "month": w.month if month is None else month,
             "status": ALLEGED, "verification_status": UNRESOLVED,
             "evidence_links": [], "investigation_status": "none",
             "known_by": [source], "public_status": "private"}
    rec["allegations"].append(entry)
    return entry


def add_evidence(w: World, pid: str, allegation_id: str, evidence: str, *, supports: bool) -> dict:
    """Attach evidence. Status moves only when evidence exists to move it."""
    entry = _allegation(w, pid, allegation_id)
    entry["evidence_links"].append({"evidence": _clean(evidence), "supports": bool(supports),
                                    "month": w.month})
    supporting = sum(1 for e in entry["evidence_links"] if e["supports"])
    against = len(entry["evidence_links"]) - supporting
    if against and supporting:
        entry["status"] = PARTIALLY_CORROBORATED
        entry["verification_status"] = PARTIALLY_CORROBORATED
    elif supporting >= 2:
        entry["status"] = CORROBORATED
        entry["verification_status"] = CORROBORATED
    elif against:
        entry["status"] = DISPROVEN
        entry["verification_status"] = DISPROVEN
    else:
        entry["status"] = PARTIALLY_CORROBORATED
        entry["verification_status"] = PARTIALLY_CORROBORATED
    return entry


def publish_allegation(w: World, pid: str, allegation_id: str) -> dict:
    """Make an allegation public without changing what it is. Publishing is not proof."""
    entry = _allegation(w, pid, allegation_id)
    entry["public_status"] = "published"
    return entry


def promote_to_fact(w: World, pid: str, allegation_id: str) -> None:
    """Refuse the one move this module exists to prevent.

    An allegation is never silently promoted into canonical fact. The only route is evidence,
    which moves `status` on the allegation itself; there is deliberately no API that rewrites
    the canonical layer from a belief or an allegation.
    """
    entry = _allegation(w, pid, allegation_id)
    raise PermissionError(
        f"allegation {entry['id']} is {entry['status']}; an allegation becomes a fact only through "
        "add_evidence, never by being asserted. Canonical state is not writable from here.")


def _allegation(w: World, pid: str, allegation_id: str) -> dict:
    rec = (w.institutions.get("provenance") or {}).get(pid)
    if rec is None:
        raise KeyError(pid)
    for entry in rec["allegations"]:
        if entry["id"] == allegation_id:
            return entry
    raise KeyError(allegation_id)


def summary(w: World, pid: str) -> dict:
    """The provenance record as an inspector or the report should read it."""
    rec = (w.institutions.get("provenance") or {}).get(pid)
    if rec is None:
        raise KeyError(pid)
    press = rec["layers"].get(PRESS_REPORT) or {}
    fact = rec["canonical"]
    return {
        "id": pid, "month": rec["month"], "source": rec["source"],
        "raw": layer(w, pid, RAW_SOURCE)["text"],
        "press": press.get("text", ""),
        "distortion": press.get("distortion_added", ""),
        "press_overstates_intent": bool(press.get("distortion_added") and fact["hedged"]),
        "canonical": fact,
        "readable_as": fact["readable_as"],
        "asserts_intent": fact["asserts_intent"],
        "allegations": [{"id": a["id"], "status": a["status"], "against": a["against"],
                         "public_status": a["public_status"], "evidence": len(a["evidence_links"])}
                        for a in rec["allegations"]],
        "known_by": list(rec["known_by"]),
    }
