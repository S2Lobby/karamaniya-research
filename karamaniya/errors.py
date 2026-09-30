"""Structured, non-fatal engine errors.

The engine rejects actions far more often than it crashes: an agent names a lever that does not
exist, a motion contradicts itself, a foreign agreement arrives twice, a condition is not met.
Those are *data* — they are how the research question "is the action vocabulary wide enough?"
gets answered — so they are recorded, not raised.

Every rejection carries a code from one taxonomy, and this module is that taxonomy. A code that
is not registered here is still recorded, but it is recorded as `UNREGISTERED_ERROR_CODE`, which
`tests/test_errors.py` asserts never happens. That way a newly invented code cannot quietly enter
the logs and make two different failures look like one.

Recording never mutates canonical state and never raises. If a caller has already validated, it
records and continues; the simulation is not interrupted by a bookkeeping failure.
"""
from __future__ import annotations

from .world import World

# code -> (category, severity, description)
#
# severity "info"    - expected, healthy rejection (an agent tried something the rules forbid)
# severity "warning" - a real inconsistency worth watching, but survivable
# severity "error"   - the engine could not do what it was asked; state is untouched
TAXONOMY: dict[str, tuple[str, str, str]] = {
    # -- action vocabulary (brief M: agents outrunning the actuator set) --------------------
    "UNKNOWN_ACTION": ("action", "info", "The named action is not in the vocabulary."),
    "UNKNOWN_LEVER": ("action", "info", "The named policy lever does not exist."),
    "UNKNOWN_TYPE": ("action", "info", "The named motion type does not exist."),
    "UNKNOWN_OFFICE": ("action", "info", "The named office does not exist."),
    "UNKNOWN_FUNDING": ("action", "info", "The named funding source does not exist."),
    "UNKNOWN_MEASURE": ("action", "info", "The named measurable condition is not supported."),
    "BAD_VALUE": ("action", "info", "The value is not valid for this lever."),
    "INVALID_RECIPIENT": ("action", "info", "The act names a recipient that cannot receive it."),
    # -- authority -------------------------------------------------------------------------
    "UNAUTHORIZED_OFFICE_ACTION": ("authority", "info", "A member ordered an office they do not hold."),
    "STALE_AUTHORITY": ("authority", "warning", "An order was issued under authority the member had already lost."),
    "ALREADY_HOLDS_OFFICE": ("authority", "info", "The office is already held by that member."),
    "ALREADY_VACANT": ("authority", "info", "The office is already vacant."),
    "NOT_A_MEMBER": ("authority", "info", "The named delegate is not an active member."),
    # -- motion integrity ------------------------------------------------------------------
    "MOTION_ACTION_MISMATCH": ("motion", "info", "Motion text and structured action describe different acts."),
    "MOTION_SEMANTIC_MISMATCH": ("motion", "warning", "Final amended payload no longer matches the voted text."),
    "MOTION_ACTION_MISMATCH_AFTER_REPAIR": ("motion", "warning", "A repaired motion still contradicts itself."),
    "MOTION_ACTION_MISMATCH_UNREPAIRED": ("motion", "warning", "A contradicting motion was recorded, not executed."),
    "EXECUTION_BLOCKED": ("motion", "warning", "A motion passed but was not executed."),
    "EXECUTION_BLOCKED_CONDITION": ("motion", "info", "A motion passed but its conditions are not met yet."),
    "MOTION_CONDITION_MISMATCH": ("motion", "warning", "Recorded conditions do not match the motion text."),
    "ALREADY_IN_FORCE": ("motion", "info", "A directive already has exactly this value."),
    "CONDITION_UNRESOLVED": ("motion", "info", "A pending condition is still false; execution stays eligible, not blocked forever."),
    "NUMERIC_GROUNDING_ERROR": ("motion", "warning", "A precise figure was asserted that the speaker could not know."),
    "VOTE_INTENT_MISMATCH": ("motion", "warning", "A final ballot contradicts the position the delegate clearly stated, with no reversal stated."),
    # -- foreign ---------------------------------------------------------------------------
    "FOREIGN_ACTION_DUPLICATE": ("foreign", "warning", "A foreign action's effects were already applied."),
    "FOREIGN_ACTION_INVALID": ("foreign", "info", "A foreign cabinet proposed an act outside its action space."),
    # -- memory and belief -----------------------------------------------------------------
    "MEMORY_PHASE_MISMATCH": ("memory", "warning", "A memory claims knowledge from a phase it was not written in."),
    "STALE_FACT_ASSERTION": ("memory", "info", "A claim was phrased as current after newer information existed."),
    # -- engine ----------------------------------------------------------------------------
    "INVALID_NUMERIC_STATE": ("engine", "error", "A tracked quantity became non-finite or negative."),
    "UNREGISTERED_ERROR_CODE": ("engine", "warning", "A code was recorded that is not in the taxonomy."),
}

MAX_RECORDED = 500


def is_registered(code: str) -> bool:
    return code in TAXONOMY


def describe(code: str) -> dict:
    category, severity, description = TAXONOMY.get(code, TAXONOMY["UNREGISTERED_ERROR_CODE"])
    return {"code": code, "category": category, "severity": severity, "description": description,
            "registered": code in TAXONOMY}


def taxonomy() -> list[dict]:
    """The whole taxonomy, sorted, for documentation and validation."""
    return [describe(code) for code in sorted(TAXONOMY)]


def record(w: World, code: str, message: str, **details) -> dict:
    """Record one structured engine error and continue. Never raises, never mutates world state.

    The entry is kept on the world so it survives checkpointing and can be counted in the report;
    a non-public event is emitted so the error sits in the same timeline as the month it happened.
    """
    entry = describe(code)
    entry.update(month=w.month, message=message, details=details)
    if not entry["registered"]:
        # Store under the fallback code so counts and filters stay meaningful, but keep the
        # code the caller actually used — that is the thing worth fixing.
        entry["originally_attempted"] = code
        entry["code"] = "UNREGISTERED_ERROR_CODE"
    log = getattr(w, "audit_errors", None)
    if log is None:                      # a world loaded from a pre-taxonomy checkpoint
        log = []
        w.audit_errors = log
    log.append(entry)
    if len(log) > MAX_RECORDED:
        del log[:len(log) - MAX_RECORDED]
    w.event("engine_error", f"{entry['code']}: {message}", public=False,
            code=entry["code"], severity=entry["severity"], category=entry["category"])
    return entry


def summary(w: World) -> dict:
    """Counts by code and severity, for the report and for integrity checks."""
    log = getattr(w, "audit_errors", []) or []
    by_code: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for entry in log:
        by_code[entry["code"]] = by_code.get(entry["code"], 0) + 1
        by_severity[entry["severity"]] = by_severity.get(entry["severity"], 0) + 1
    return {"total": len(log), "by_code": dict(sorted(by_code.items())),
            "by_severity": dict(sorted(by_severity.items())),
            "unregistered": by_code.get("UNREGISTERED_ERROR_CODE", 0)}


def since(w: World, month: int | None = None) -> list[dict]:
    log = getattr(w, "audit_errors", []) or []
    if month is None:
        return list(log)
    return [e for e in log if e.get("month") == month]
