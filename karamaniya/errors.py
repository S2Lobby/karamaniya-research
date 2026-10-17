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
    "UNKNOWN_FIELD": ("action", "info", "The named action field does not exist."),
    "UNKNOWN_SCOPE": ("action", "info", "The named scope is not supported."),
    "UNKNOWN_REGION": ("action", "info", "The named region does not exist."),
    "UNKNOWN_ARREARS_CATEGORY": ("action", "info", "The named arrears category does not exist."),
    "UNKNOWN_DIPLOMACY": ("action", "info", "The named diplomatic act is not supported."),
    "UNKNOWN_ACTION_TYPE": ("action", "info", "The structured action type is not supported."),
    "UNKNOWN_DEAL_INTENT": ("action", "info", "The proposed deal intent is not supported."),
    "UNKNOWN_TARGET": ("action", "info", "The named diplomatic target does not exist."),
    "BAD_VALUE": ("action", "info", "The value is not valid for this lever."),
    "VALUE_OUT_OF_RANGE": ("action", "info", "The value lies outside the range its setting takes; the motion is refused so its author can repair it."),
    "BAD_AMOUNT": ("action", "info", "The amount is not valid for this action."),
    # Audit MO18: politics.validate_motion_detail refuses a loan with no amount with this code, and it was unregistered.
    "BAD_LOAN_AMOUNT": ("action", "info", "A loan needs a positive amount in millions of gold."),
    "INVALID_RECIPIENT": ("action", "info", "The act names a recipient that cannot receive it."),
    "ACTION_NOT_VALID_FOR_TARGET": ("action", "info", "The named act cannot be addressed to that target."),
    # Engine 23: the refusals of an ultimatum_reply (engine 22), which were recorded as UNREGISTERED_ERROR_CODE.
    "NO_ULTIMATUM": ("action", "info", "A reply to an ultimatum was sent while no ultimatum stands."),
    "ULTIMATUM_NOT_FROM_TARGET": ("action", "info", "A reply to an ultimatum was addressed to a power that did not "
                                  "issue it."),
    "NOT_DEMANDED": ("action", "info", "A region named for cession has not been demanded by the neighbour addressed."),
    "NO_TARGET": ("action", "info", "The diplomatic act has no target."),
    "NO_STRUCTURED_ACTION": ("action", "info", "The motion has no executable structured action."),
    # Audit CO2 follow-up: a normaliser raised on a delegate's answer. The answer is read as empty for its phase, so this is
    # an engine fault that the run must count, not a delegate's choice.
    "ANSWER_UNREADABLE": ("action", "warning", "A delegate's answer raised an error in its normaliser and was read as empty for that phase."),
    "EMPTY_MOTION_TEXT": ("motion", "info", "The motion has no public text describing what the council will vote on."),
    # -- authority -------------------------------------------------------------------------
    "UNAUTHORIZED_OFFICE_ACTION": ("authority", "info", "A member ordered an office they do not hold."),
    "STALE_AUTHORITY": ("authority", "warning", "An order was issued under authority the member had already lost."),
    "ALREADY_HOLDS_OFFICE": ("authority", "info", "The office is already held by that member."),
    "ALREADY_VACANT": ("authority", "info", "The office is already vacant."),
    "ALREADY_SCHEDULED": ("authority", "info", "The requested change is already scheduled."),
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
    "ALREADY_SET": ("motion", "info", "The requested policy or condition is already set."),
    "DIRECTIVE_ORDER_MISMATCH": ("motion", "warning", "An office order conflicts with a council directive."),
    "MOTION_NOT_HEARD": ("motion", "info", "The council did not reach this motion."),
    "MOTION_CAP_REACHED": ("motion", "info", "A delegate offered more motions in a month than the cap allows; the extra one was not heard."),
    "MOTION_WITHDRAWN": ("motion", "info", "The proposer withdrew this motion."),
    "NOT_PASSED": ("motion", "info", "The motion did not pass."),
    "SESSION_VOID": ("motion", "info", "The session was voided; its motions cannot execute."),
    "DUPLICATE_ACTION": ("motion", "info", "An equivalent action already executed this month."),
    "SAME_MOTION_TABLED": ("motion", "info", "An equivalent motion is already tabled for this session."),
    "SUBSTANTIALLY_DUPLICATES": ("motion", "info", "The motion substantially duplicates one already considered."),
    "COSPONSORED_CARRIED": ("motion", "info", "The carried motion has already been co-sponsored."),
    "RENEWED_CARRIED": ("motion", "info", "The carried motion has already been renewed."),
    "DEFERRAL_MONTH_PAST": ("motion", "info", "The requested deferral month has already passed."),
    "NO_DEFERRAL_TARGET": ("motion", "info", "The motion does not identify a valid deferral target."),
    "EMPTY_AMENDMENT": ("motion", "info", "The amendment contains no change to consider."),
    "ELECTION_MONTH_INVALID": ("motion", "info", "The requested election month is invalid."),
    "NAME_IN_USE": ("motion", "info", "The proposed name is already in use."),
    "NO_ARREARS": ("motion", "info", "There are no arrears matching this payment."),
    "NO_ARREARS_IN_CATEGORY": ("motion", "info", "There are no arrears in the requested category."),
    "NO_FUNDING_CAPACITY": ("motion", "info", "The requested action has no available funding capacity."),
    "RECENTLY_AUDITED": ("audit", "info", "This office was audited too recently for another audit."),
    "TOO_MANY_OPEN": ("audit", "info", "The maximum number of open audits has been reached."),
    "CONDITION_UNRESOLVED": ("motion", "info", "A pending condition is still false; execution stays eligible, not blocked forever."),
    "NUMERIC_GROUNDING_ERROR": ("motion", "warning", "A precise figure was asserted that the speaker could not know."),
    "VOTE_INTENT_MISMATCH": ("motion", "warning", "A final ballot is the other way from the plain verdict its own reason states (a diagnostic, not a behaviour measure; backlog T144)."),
    "CONDITION_EXECUTION_MISMATCH": ("motion", "warning", "A condition the council accepted was not attached to the motion, or execution would have broken it."),
    # -- state media (engine 27, wave 3 A) -------------------------------------------------
    "MEDIA_MISSING_KINDS": ("motion", "info", "A media_campaign names no kind."),
    "MEDIA_UNKNOWN_KIND": ("motion", "info", "A media_campaign kind is not one of the four the engine has."),
    "MEDIA_MISSING_CLAIMS": ("motion", "info", "A media_campaign with claim_figures names no claims."),
    "MEDIA_TOO_MANY_CLAIMS": ("motion", "info", "A media_campaign names more than three claims."),
    "MEDIA_BAD_CLAIM": ("motion", "info", "A media_campaign claim is not a {metric, value} pair."),
    "MEDIA_UNKNOWN_CLAIM_METRIC": ("motion", "info", "A media_campaign claim names a metric the canonical state does not publish."),
    "MEDIA_BAD_CLAIM_VALUE": ("motion", "info", "A media_campaign claim value is not a number."),
    "MEDIA_CLAIMS_WITHOUT_FIGURES": ("motion", "info", "Claims were given without the claim_figures kind."),
    "MEDIA_MISSING_INTENSITY": ("motion", "info", "A media_campaign names no intensity."),
    "MEDIA_MISSING_TEXT": ("motion", "info", "A media_campaign has no text."),
    # -- effect bus (engine 30, Wave A W1) -------------------------------------------------
    "EFFECT_UNKNOWN_CHANNEL": ("action", "info", "An effect names a channel the effect bus does not have."),
    "EFFECT_UNKNOWN_TARGET": ("action", "info", "An effect is aimed at a target its channel cannot reach."),
    "EFFECT_OVER_CAP": ("action", "info", "A single effect moves a channel further than its per-entry cap allows."),
    "EFFECT_MONTH_CAP": ("action", "info", "Effects on one channel and target sum beyond the month's cap."),
    "EFFECT_BAD_VALUE": ("action", "info", "An effect's value, or its decay, is not a usable number."),
    "EFFECT_BAD_MONTHS": ("action", "info", "An effect's duration is not a whole number of at least one month."),
    "EFFECT_TOO_MANY_MONTHS": ("action", "info", "An effect lasts longer than its channel allows."),
    "EFFECT_UNKNOWN_SOURCE": ("action", "info", "An effect's source is not a policy, an open act or a "
                                                "neighbour's open act."),
    # -- open actions (Wave A, W2) ----------------------------------------------------------
    # The tabling refusals of the `policy` motion and the delegate `open_act` (plan 4.2-4.3). Each is raised by
    # actions.validate_new_motion under the arm that offers the type, and travels the council's usual rejection path.
    "POLICY_UNKNOWN_INSTRUMENT": ("motion", "info", "A policy item names an instrument the policy language does not have."),
    "POLICY_BAD_TARGET": ("motion", "info", "A policy item aims at a lever, target, mandate or value it cannot have."),
    "POLICY_BAD_CONDITION": ("motion", "info", "A policy item's condition is not one the engine can test."),
    "POLICY_BAD_SCHEDULE": ("motion", "info", "A policy item's start_in or months is outside its stated range."),
    "POLICY_UNFUNDED": ("motion", "info", "A spending policy item has no amount or no valid funding."),
    "POLICY_LIMIT": ("motion", "info", "A policy motion does not carry the stated one to four items."),
    "OPEN_ACT_TOO_LONG": ("motion", "info", "An open act's text is longer than the stated 60 words."),
    "OPEN_ACT_MISSING_TEXT": ("motion", "info", "An open act has no text saying what the government does."),
    "OPEN_ACT_UNKNOWN_OFFICE": ("motion", "info", "An open act names no office, or one that does not exist."),
    "OPEN_ACT_BAD_BUDGET": ("motion", "info", "An open act's budget is not a positive amount and 1 to 24 months."),
    "OPEN_ACT_UNFUNDED": ("motion", "info", "An open act with a budget has no valid funding."),
    "OPEN_ACT_LIMIT": ("motion", "info", "A delegate tabled more than one open act in a month."),
    "OPEN_ACT_BAD_TARGET": ("foreign", "info", "A cabinet's open act names a target outside Karamaniya, its regions and its own country."),
    # -- the referee (Wave A W4) -------------------------------------------------------------
    # The referee rules an approved open act. Its rulings are validated before anything is scheduled; an invalid
    # ruling is re-asked once and only a second invalid one fails the act. Every code below travels with the
    # problems the engine sends back to the referee in words (the sentences never carry the code).
    "REFEREE_BAD_ANSWER": ("action", "info", "A referee's ruling is not the required shape or value."),
    "REFEREE_BAD_COST": ("action", "info", "A referee's cost is not three usable numbers."),
    "REFEREE_OVER_BUDGET": ("action", "info", "A referee's cost does not fit the act's funding."),
    "REFEREE_FORBIDDEN_ACT": ("action", "info", "A referee made feasible an act that another decision owns."),
    "REFEREE_CHANNEL_NOT_ALLOWED": ("action", "info", "A cabinet's ruling uses a channel or target it cannot reach."),
    "REFEREE_TOO_LONG": ("action", "info", "A referee's reason or public report is over its word limit."),
    "REFEREE_INVALID": ("action", "info", "A referee's ruling was invalid twice, so the act failed."),
    # -- foreign ---------------------------------------------------------------------------
    "FOREIGN_ACTION_DUPLICATE": ("foreign", "warning", "A foreign action's effects were already applied."),
    "FOREIGN_ACTION_INVALID": ("foreign", "info", "A foreign cabinet proposed an act outside its action space."),
    "NO_EXISTING_DEAL": ("foreign", "info", "There is no active agreement to extend, expand, or renounce."),
    "DEAL_ALREADY_EXISTS": ("foreign", "info", "An equivalent agreement is already in force."),
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
