"""Government-formation proposal validation: the structured slate and the prose that describes it.

A formation proposal arrives in two channels that are supposed to say the same thing: a structured
`slate` mapping each office to a delegate, and free prose explaining the choice. The engine used to
check only that the five slate values were valid member ids, which let a slate assigning every office
to one delegate pass as a "complete government", and nothing at all compared the prose to the slate.
So a proposal could read "B should be Head" while its structured half appointed A, and the vote went
ahead on whichever half the engine happened to read.

Two problems, two functions. `validate` is exact: a full slate is a bijection between five offices
and five delegates, and anything else is named precisely. `mismatches` reads the prose, but only in
the narrow case where it makes an *explicit* assignment claim.

That narrowness is deliberate and is the main design decision here. Prose in this corpus is
rhetorically varied — real statements include "Delegate D's payments-and-harvest knowledge suits
Treasury perfectly" and "My dossier gives me direct intelligence on ... critical for Interior",
where a member and an office sit near each other without any claim being made. A permissive reader
would flag those, block a proposal that was never malformed, and turn a wording quirk into a
constitutional crisis. So the reader recognises a small closed set of binding constructions and
abstains on everything else: it is high-precision and deliberately low-recall. A missed claim costs
nothing (the slate still has to pass structural validation and the vote). A false claim costs the
run. The asymmetry sets the threshold.
"""
from __future__ import annotations

import re

from .world import OFFICES

# The words a statement uses for each office. Longest-first at match time so "army command" wins
# over "army" and the office is read once. Verb forms ("chair", "leads") are included because the
# real corpus uses them: "Delegate C should chair an implementation-focused government" is a claim
# about the headship, and the delegate who wrote it meant exactly that.
OFFICE_WORDS = {
    "head": ("head of government", "head of the government", "premiership", "chairperson",
             "head", "chair", "chairs", "chaired"),
    "treasury": ("ministry of finance", "finance ministry", "finance minister", "treasury"),
    "interior": ("interior ministry", "interior"),
    "army": ("army command", "armed forces command", "land forces", "army"),
    "navy": ("navy command", "naval command", "navy"),
}

# What may sit between a delegate and an office for the pair to read as an assignment.
# Everything here is a construction that binds; "suits", "aligns with", "would strengthen" and the
# rest are absent on purpose — they describe a fit, not an appointment.
_LINKS_FORWARD = (
    re.compile(r"^,?\s*(?:should|will|would|must|can)\s+be\s+(?:the\s+)?$"),
    re.compile(r"^,?\s*(?:should|will|would|must)\s+(?:lead|chair|head|direct|take|handle|run|"
               r"command|oversee|hold)\s+(?:the\s+)?$"),
    re.compile(r"^,?\s*(?:leads|chairs|heads|directs|takes|handles|runs|commands|oversees|holds)\s+"
               r"(?:the\s+)?$"),
    re.compile(r"^,?\s*(?:as|for|to)\s+(?:the\s+)?$"),
    re.compile(r"^,?\s*(?:should|will|would)\s+$"),          # the office word is itself the verb
    re.compile(r"^,\s*(?:who|whose|with)\b.{0,70}?,\s*(?:as|for|to)\s+(?:the\s+)?$", re.S),
)
# Office first, delegate second: "Head — B", "Treasury: D", "Interior to E".
_LINKS_BACKWARD = (
    re.compile(r"^\s*(?:—|–|-|:)\s*$"),
    re.compile(r"^\s*(?:to|is|becomes|goes to|should be|should go to)\s+(?:the\s+)?$"),
    re.compile(r"^\s*(?:—|–|-|:)\s*$"),
)
# A gap containing one of these is arguing against the pairing, or listing alternatives, and must
# never be read as an assignment.
_HEDGES = ("not ", "n't ", "never", "oppose", "against", "reject", "rather than", "instead of",
           "either", "whether", "if ", "unless", "no one", "any other")
_MAX_GAP = 80
_DELEGATE_RE = re.compile(r"\bdelegate\s+([A-E])\b", re.I)
_LETTER_RE = re.compile(r"\b([A-E])\b")
_FIRST_PERSON_RE = re.compile(r"\b(?:myself|me|i)\b", re.I)


def is_empty(slate) -> bool:
    """The documented way to say "I have no slate": five empty strings. Not an error."""
    return isinstance(slate, dict) and all(
        isinstance(slate.get(o), str) and not slate.get(o).strip() for o in OFFICES)


def validate(slate, ids) -> list:
    """Every way a structured slate can fail to be a complete government of `ids`.

    Returns the errors, so the caller can hand them back to the delegate who wrote it. An empty
    list means a valid full slate: five offices, one holder each, each delegate in exactly one.
    """
    if not isinstance(slate, dict):
        return ["slate must be a JSON object mapping each office to a delegate"]
    ids = list(ids)
    errors = []
    for office in OFFICES:
        if office not in slate:
            errors.append(f"office {office.upper()} is missing from the slate")
    for key in slate:
        if key not in OFFICES:
            errors.append(f"unknown office {key!r} is not one of {', '.join(o.upper() for o in OFFICES)}")
    holders = {}
    for office in OFFICES:
        if office not in slate:
            continue
        value = slate[office]
        if not isinstance(value, str) or not value.strip():
            errors.append(f"office {office.upper()} has no holder")
            continue
        if value not in ids:
            errors.append(f"office {office.upper()} names unknown delegate {value!r}")
            continue
        holders.setdefault(value, []).append(office)
    for member, offices in sorted(holders.items()):
        if len(offices) > 1:
            errors.append(f"delegate {member} holds more than one office "
                          f"({', '.join(o.upper() for o in offices)}); a slate gives each delegate "
                          f"exactly one")
    for member in ids:
        if member not in holders:
            errors.append(f"delegate {member} holds no office")
    return errors


def _office_mentions(text: str) -> list:
    """(start, end, office) for every office named, longest phrase winning overlaps."""
    found = []
    lowered = text.lower()
    for office, words in OFFICE_WORDS.items():
        for word in sorted(words, key=len, reverse=True):
            for m in re.finditer(r"\b" + re.escape(word) + r"\b", lowered):
                found.append((m.start(), m.end(), office))
    found.sort(key=lambda t: (t[0], -(t[1] - t[0])))
    kept = []
    for start, end, office in found:
        if any(not (end <= s or start >= e) for s, e, _ in kept):
            continue  # inside a longer phrase already matched
        kept.append((start, end, office))
    return sorted(kept)


def _member_mentions(text: str, speaker: str, ids) -> list:
    """(start, end, member) for every delegate named, by "Delegate X", a bare letter, or first person."""
    found = []
    for m in _DELEGATE_RE.finditer(text):
        if m.group(1).upper() in ids:
            found.append((m.start(), m.end(), m.group(1).upper()))
    for m in _LETTER_RE.finditer(text):
        letter = m.group(1)
        if letter in ids and not any(not (m.end() <= s or m.start() >= e) for s, e, _ in found):
            found.append((m.start(), m.end(), letter))
    if speaker in ids:
        for m in _FIRST_PERSON_RE.finditer(text):
            if not any(not (m.end() <= s or m.start() >= e) for s, e, _ in found):
                found.append((m.start(), m.end(), speaker))
    found.sort()
    kept = []
    for start, end, member in found:
        if any(not (end <= s or start >= e) for s, e, _ in kept):
            continue
        kept.append((start, end, member))
    return kept


def _reads_as_assignment(gap: str, patterns) -> bool:
    # Collapse whitespace and keep exactly one space at the END. The patterns anchor on that
    # boundary — "should lead the " is an assignment, "should lead the" is not — so stripping the
    # gap was enough to make every one of them fail and the reader found almost nothing. The
    # leading side is left flush: a leading space would push the punctuation of ", to " out of
    # reach of the patterns that open with an optional comma.
    gap = " ".join(gap.split()) + " "
    if len(gap) > _MAX_GAP:
        return False
    low = gap.lower()
    if any(hedge in low for hedge in _HEDGES):
        return False
    return any(p.match(gap) for p in patterns)


def _gap_is_local(gap: str, gap_start: int, gap_end: int, members: list) -> bool:
    """Whether the text between a delegate and an office links those two and nothing else.

    A bridge that names a second delegate is not describing this pairing. Real corpus case: "...to
    Interior and Police; Delegate A, with the shipping dossier, to Navy Command; and myself,
    Delegate C, to Army Command" — the bridge from A to "Army Command" runs through C's own
    mention, and read naively it says A wants the army, when the sentence gives A the navy and C
    the army. A clause boundary ends a claim the same way, so a semicolon or a sentence end
    closes it too.
    """
    if ";" in gap:
        return False
    if re.search(r"\.\s", gap):
        return False
    for s, e, _ in members:
        # The endpoint delegate's own mention sits flush against the bridge, either side.
        if e == gap_start or s == gap_end:
            continue
        if s < gap_end and e > gap_start:
            return False
    return True


def claims(statement: str, speaker: str, ids) -> list:
    """Explicit "this delegate takes this office" claims, as (office, member) pairs.

    Deliberately narrow: only a binding construction between an adjacent-enough delegate and office
    is read. Rhetoric, comparisons and descriptions of fitness are passed over rather than guessed
    at, because a wrong claim would block a proposal that was never malformed.
    """
    if not isinstance(statement, str) or not statement:
        return []
    members = _member_mentions(statement, speaker, ids)
    out = []
    for start, end, office in _office_mentions(statement):
        for mstart, mend, member in members:
            if mend <= start:
                if not _gap_is_local(statement[mend:start], mend, start, members):
                    continue
                if _reads_as_assignment(statement[mend:start], _LINKS_FORWARD):
                    out.append((office, member))
            elif mstart >= end:
                if not _gap_is_local(statement[end:mstart], end, mstart, members):
                    continue
                if _reads_as_assignment(statement[end:mstart], _LINKS_BACKWARD):
                    out.append((office, member))
    seen, unique = set(), []
    for pair in out:
        if pair not in seen:
            seen.add(pair)
            unique.append(pair)
    return unique


def assess(statement: str, slate, speaker: str, ids) -> dict:
    """Everything wrong with one proposal, in the form the repair prompt and the audit log need.

    The single entry point, because `validate` on an all-empty slate reports ten errors — the
    documented "I have no slate" is not a malformed one — and a caller that forgot to check
    `is_empty` first would send five delegates to repair a proposal that was never broken.
    """
    if is_empty(slate):
        return {"errors": [], "mismatches": [], "no_slate": True, "valid": True}
    errors = validate(slate, ids)
    prose = mismatches(statement, slate, speaker, ids)
    return {"errors": errors, "mismatches": prose, "no_slate": False,
            "valid": not errors and not prose}


def mismatches(statement: str, slate, speaker: str, ids) -> list:
    """Prose claims that contradict the structured slate. Never guesses which side is meant."""
    if not isinstance(slate, dict):
        return []
    out = []
    for office, member in claims(statement, speaker, ids):
        holder = slate.get(office)
        if isinstance(holder, str) and holder.strip() and holder != member:
            out.append(f"the statement gives {office.upper()} to {member}, but the slate gives it "
                       f"to {holder}")
    return out
