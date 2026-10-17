"""Delegates' open acts (engine 30, Wave A W5): the one path that carries a passed `open_act` out.

A delegate may propose, in free words, an act the menu does not list. The council votes on it like any
other motion; once it passes the execution gate, this module carries it out. It makes no policy decision
of its own:

* the referee (W4, `karamaniya/referee.py`) is asked once, in the words of the act, what the act can
  achieve, what it costs and how likely it is to work; it is re-asked once by `Referee.ask` if its first
  ruling cannot be used;
* the act's success is drawn once, on its own stream `rng_for(seed, month, "open_act")` (`referee.outcome`),
  so no other draw in the month moves;
* the ruling's cost is charged through the same funding paths W3's policy items use, and its effects are
  scheduled through the effect bus (W1) with source `{"kind": "open_act", "actor": proposer, "motion": id,
  "month": m}`.

`referee_effects = "zeroed"` is the ablation the plan asks for (section 4.6): the referee is still asked,
the ruling still logged, the draw still made and the cost still charged; only the effects are withheld, and
the record says what would have been applied. The two arms therefore differ only in effects.

Funding. The same capacity rules as W3's policy module, reimplemented here because policy.py is not W5's
file to edit: reserves above the item's reserve floor (an open act carries no condition, so its floor is
zero), domestic borrowing within `politics.borrowing_capacity`, and `cut:<lever>` within the lever's room
above its lower bound. `cut:<lever>` lowers the setting and holds it while the act's monthly charges run,
restoring it when they end unless a later decision changed the setting (then the hold is recorded as
superseded). A one-off cost and the first month's cost are charged in the execution month; the remaining
monthly charges are kept in `w.institutions["open_act_charges"]` and stepped by `monthly(w)`, which the
council calls at the start of each month beside its pre-session calls. A later charge that cannot be paid
is recorded with its reason and stops the remaining charges; the effects of the act remain, because they
landed when the act was carried out.

Records. `month_record(w)` is the month's `open_acts` record; `engine.snapshot` adds it to the history row
when it exists, so a default run's rows are exactly engine 29's. Each act record carries the motion, the
proposer, the office, the text, the ruling, the validation problems, the success draw, the cost charged and
its funding, the effects scheduled (or withheld under zeroed), whether it was public, and the referee's
first call id. A refused act also carries its code and reason; the council adds it to the proposer's
next-month refusal note. Later-charge failures are recorded as `kind = "charge"` entries in the same list.

Briefing. `briefing.public`/`public_v2` read the previous month's `open_acts` from the council record and
describe each act that was carried out: what the public was told (or that it was not announced), what it
cost and whether it worked. Nothing is added when no open act ran, so the default prompts do not change.
"""
from __future__ import annotations

from . import actions, effects, errors, politics

RECORD_KEY = "open_act_record"
CHARGES_KEY = "open_act_charges"
SOURCE_KIND = "open_act"

# Readable office names for the record and the briefing. The referee module has the same table; it is
# repeated rather than imported so this module does not depend on the referee for a display string.
OFFICE_TITLES = {"head": "Head of Government", "treasury": "Treasury", "interior": "Interior",
                 "army": "Army", "navy": "Navy"}
TOLERANCE = 1e-6


# ---- state ---------------------------------------------------------------------------------------
def state(w) -> list:
    """The live monthly charges, created on first use. An old checkpoint has none and starts empty."""
    charges = w.institutions.get(CHARGES_KEY)
    if not isinstance(charges, list):
        charges = []
        w.institutions[CHARGES_KEY] = charges
    return charges


def month_record(w, month: int | None = None) -> dict | None:
    """The open-act record of `month` (default: this month), or None. The council reads it to add the
    proposer's refusals to the next month's notes; engine.snapshot adds it to the history row."""
    record = w.institutions.get(RECORD_KEY)
    wanted = w.month if month is None else int(month)
    if not isinstance(record, dict) or record.get("month") != wanted:
        return None
    return record


def _record(w) -> dict:
    record = w.institutions.get(RECORD_KEY)
    if not isinstance(record, dict) or record.get("month") != w.month:
        record = {"month": w.month, "open_acts": []}
        w.institutions[RECORD_KEY] = record
    return record


def _append(w, entry: dict) -> None:
    _record(w)["open_acts"].append(entry)


# ---- the caller's interface ----------------------------------------------------------------------
def execute(w, motion, *, settings=None, referee=None, store=None, next_call_id=None,
            names=None) -> dict:
    """Carry out one passed open-act motion, and return its record entry.

    `settings` is the run's settings (its `referee_effects` selects the ablation). `referee` is W4's
    Referee, built once per run by the council so its precedents accumulate there; `store` and
    `next_call_id` are the council's log and call numbering, so every attempt is logged like a seat's
    call. `names` is the council's seeded-name table, applied to the referee's prompts.

    A usage limit or an unreachable referee raises `council.RunPaused` after the attempt is logged: the
    month is abandoned and replayed when the run resumes, exactly as for a delegate's seat. Every other
    refusal is recorded and returned, never raised.
    """
    settings = dict(settings or {})
    zeroed = str(settings.get("referee_effects", "applied")) == "zeroed"
    act = dict(actions.open_act_of(w, motion) or {})
    proposer = motion.get("proposer")
    entry = {
        "kind": "act", "motion": motion.get("id"), "proposer": proposer,
        "office": act.get("office"), "text": str(act.get("text") or ""),
        "budget": act.get("budget"), "funding": act.get("funding"),
        "public": False, "ruling": None, "outcome": None, "effects": [],
        "cost": {"one_off": 0.0, "monthly": 0.0, "months": 0, "charged": 0.0,
                 "funding": act.get("funding"), "remaining_charges": 0, "payments": []},
        "refused": False, "code": "", "reason": "", "carried_out": False, "zeroed": zeroed,
        "attempts": 0, "call_id": None, "result": "",
    }
    if _acted_this_month(w, proposer):
        # W2's tabling rule refuses a second act; a direct call (a stand-in, a replay) reaches the same
        # verdict here rather than carrying two acts out.
        return _refuse(w, entry, "OPEN_ACT_LIMIT",
                       "a delegate may carry out one open act a month; this delegate already has one "
                       "this month")
    if referee is None:
        # Decision (d): under harness = "open" a run without a referee is refused at start (W6); this is
        # the same failure in words from the execution path, for a direct call or a run assembled early.
        return _refuse(w, entry, "EXECUTION_BLOCKED",
                       "No referee is configured for this run, so the act could not be carried out.")
    result = referee.ask(w, {**act, "motion": motion.get("id"), "proposer": proposer}, names=names)
    call_ids = _log(w, result, store, next_call_id)
    entry["attempts"] = result.attempts
    entry["call_id"] = call_ids[0] if call_ids else None
    if result.paused or result.unavailable:
        from .council import RunPaused      # deferred: council.py imports this module
        raise RunPaused(result.seat, result.seat,
                        result.reason or "could not be reached", role="Referee")
    if result.failed:
        reason = (result.reason + " " + result.detail).strip()
        return _refuse(w, entry, "REFEREE_INVALID", reason, record_error=False)
    ruling = dict(result.ruling or {})
    entry["ruling"] = ruling
    entry["public"] = bool(ruling.get("public"))
    entry["cost"].update(one_off=float(ruling["cost"]["one_off"]),
                         monthly=float(ruling["cost"]["monthly"]),
                         months=int(ruling["cost"]["months"]))
    if not ruling.get("feasible"):
        # A valid refusal: the administration cannot do it. No draw, no cost, no effects.
        entry["refused"] = True
        entry["reason"] = str(ruling.get("reason") or "")
        entry["result"] = f"open act not carried out: {entry['reason']}"
        _append(w, entry)
        return entry

    outcome = referee.outcome(w, ruling)
    entry["outcome"] = outcome
    charge = _charge_entry(w, motion, act, ruling["cost"])
    # The first month is charged now; a ruling whose cost runs zero months has no monthly payment at all,
    # so its monthly figure is not charged. (W4's validator refuses monthly > 0 with months 0, but the
    # charge rule is stated here rather than relying on that: the schema allows months 0.)
    charged = _initial_charge(ruling["cost"])
    paid, payment = _pay(w, charged, act.get("funding"), charge)
    entry["cost"]["payments"].append(payment)
    if not paid:
        return _refuse(w, entry, "OPEN_ACT_UNFUNDED",
                       payment.get("reason") or "the money could not be found")
    entry["carried_out"] = True
    entry["cost"]["charged"] = round(charged, 3)
    entry["cost"]["remaining_charges"] = int(charge.get("months_left", 0))
    if charge.get("months_left", 0) > 0:
        state(w).append(charge)
    elif charge.get("cut"):
        _release_cut(w, charge, "its schedule ended")

    if outcome["worked"]:
        if zeroed:
            # The ablation: the ruling stands and the cost is paid, the effects are withheld. The record
            # says what would have been applied.
            entry["effects"] = [{key: item.get(key) for key in ("channel", "target", "value", "months")}
                                | {"applied": False} for item in ruling["effects"]]
        else:
            source = {"kind": SOURCE_KIND, "actor": proposer, "motion": motion.get("id"),
                      "month": w.month}
            effects.schedule(w, ruling["effects"], source)
            entry["effects"] = [{key: item.get(key) for key in ("channel", "target", "value", "months")}
                                | {"applied": True} for item in ruling["effects"]]
    if entry["public"]:
        # What the public sees: the report of what the act achieved, or that it did not. A quiet act is
        # recorded and never announced.
        w.event(SOURCE_KIND, outcome["report"], importance=2, public=True)
    title = OFFICE_TITLES.get(str(act.get("office") or ""), "government")
    if outcome["worked"]:
        entry["result"] = f"open act carried out by the {title}: {outcome['report']}"
    else:
        entry["result"] = (f"open act carried out by the {title}, but it did not work: "
                           f"{outcome['report']}")
    _append(w, entry)
    return entry


def refusal_entry(entry: dict) -> dict:
    """A refused act in the shape the council's next-month refusal note reads (`_rejected_last_month`)."""
    return {"member": entry.get("proposer"),
            "motion": {"type": "open_act", "subject": "", "value": "",
                       "text": entry.get("text", "")},
            "status": "rejected", "reason_code": entry.get("code") or "",
            "explanation": entry.get("reason") or ""}


def _acted_this_month(w, proposer) -> bool:
    record = month_record(w)
    return bool(record) and any(item.get("kind", "act") == "act" and item.get("proposer") == proposer
                                for item in record.get("open_acts") or [])


def _refuse(w, entry: dict, code: str, reason: str, record_error: bool = True) -> dict:
    entry["refused"] = True
    entry["code"] = code
    entry["reason"] = reason
    entry["result"] = f"open act not carried out: {reason}"
    if record_error and code:
        errors.record(w, code, reason, member=entry.get("proposer"), motion=entry.get("motion"),
                      act=entry.get("text", "")[:160])
    _append(w, entry)
    return entry


def _log(w, result, store, next_call_id) -> list:
    """Every attempt as a call and a prompt record, keyed like a delegate's (W4's log_records).

    Returns the call ids it used (none when the caller kept no log), so the act's record can name the
    referee's first call.
    """
    if store is None or next_call_id is None:
        return []
    ids = [next_call_id() for _ in result.answers]
    for record in result.log_records(w, ids):
        store.log(record["call"])
        store.log_prompt(record["prompt"])
    return ids


# ---- funding (W3's semantics, reimplemented here) -------------------------------------------------
def _gold_to_local(w) -> float:
    """Crowns one unit of gold buys, as W3's policy funding and the relief path read it."""
    e = w.econ
    return w.zone_of("karamaniya").price / (e.fx_conf if e.currency == "karam" else 1.0)


def _lever_value(w, lever: str):
    """A setting's actual value in force (deployments and patronage are not plain attributes)."""
    return politics._current_order_value(w, politics.LEVER_OFFICE.get(lever), lever)


def _same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < 1e-6
        except (TypeError, ValueError):
            return False
    return a == b


def _initial_charge(cost: dict) -> float:
    """Millions charged in the execution month: the one-off plus the first month's monthly, if any.

    A ruling whose cost runs zero months has no monthly month, so only its one-off is paid.
    """
    one_off = float(cost.get("one_off", 0.0) or 0.0)
    monthly = float(cost.get("monthly", 0.0) or 0.0)
    return one_off + (monthly if int(cost.get("months", 0) or 0) > 0 else 0.0)


def _charge_entry(w, motion, act, cost: dict) -> dict:
    """The record of the act's monthly charges still to be paid (the first month is paid at once).

    A ruling whose cost runs zero months has no monthly charge: months_left is 0 and nothing is scheduled.
    """
    months = int(cost.get("months", 0))
    return {"motion": motion.get("id"), "proposer": motion.get("proposer"),
            "monthly": float(cost.get("monthly", 0.0)) if months > 0 else 0.0,
            "months_left": max(0, months - 1) if months > 0 else 0,
            "funding": act.get("funding"), "next_month": w.month + 1, "created": w.month}


def _pay(w, millions: float, funding, entry: dict) -> tuple:
    """Charge `millions` crowns-million through `funding`. (paid, payment record with a reason in words).

    The capacity rules are W3's: reserves above the item's floor, the domestic market's monthly room, and
    a cut within the lever's room above its lower bound. An open act carries no condition, so its reserve
    floor is zero.
    """
    amount = max(0.0, float(millions or 0.0))
    if amount <= TOLERANCE:
        return True, {"source": str(funding or "none"), "paid": 0.0}
    if not isinstance(funding, str) or not funding:
        return False, {"source": None, "paid": 0.0,
                       "reason": "the act's ruling costs money, but it names no funding source"}
    crowns = amount * 1e6
    if funding == "reserves":
        rate = _gold_to_local(w)
        capacity = max(0.0, float(w.econ.gold) * rate)
        if crowns > capacity + TOLERANCE:
            return False, {"source": funding, "requested": round(amount, 3), "paid": 0.0,
                           "capacity": round(capacity / 1e6, 2),
                           "reason": (f"the reserves hold {w.econ.gold / 1e6:,.1f}M, which can pay "
                                      f"{capacity / 1e6:,.1f}M this month, not {amount:g}M")}
        w.econ.gold = max(0.0, w.econ.gold - crowns / max(rate, .01))
        return True, {"source": funding, "requested": round(amount, 3), "paid": round(amount, 3),
                      "capacity": round(capacity / 1e6, 2)}
    if funding == "borrowing":
        capacity = politics.borrowing_capacity(w)
        if crowns > capacity + TOLERANCE:
            return False, {"source": funding, "requested": round(amount, 3), "paid": 0.0,
                           "capacity": round(capacity / 1e6, 2),
                           "reason": (f"the domestic market can lend {capacity / 1e6:,.1f}M crowns this "
                                      f"month, not {amount:g}M")}
        w.econ.debt_dom += crowns
        # The same-month issuance registry economy.fiscal reads: a policy's borrowing competes with the
        # budget's, and so does an open act's.
        issued = w.institutions.setdefault("arrears_bonds", {"month": w.month, "amount": 0.0})
        if issued.get("month") != w.month:
            issued.update(month=w.month, amount=0.0)
        issued["amount"] = float(issued.get("amount", 0.0)) + crowns
        return True, {"source": funding, "requested": round(amount, 3), "paid": round(amount, 3),
                      "capacity": round(capacity / 1e6, 2)}
    if funding.startswith("cut:"):
        lever = funding[len("cut:"):]
        if lever not in actions.SPENDING_LEVERS:
            return False, {"source": funding, "requested": round(amount, 3), "paid": 0.0,
                           "reason": (f"a cut can fund only a spending setting "
                                      f"({', '.join(actions.SPENDING_LEVERS)}); '{lever}' is not one")}
        return _apply_cut(w, entry, lever, crowns, amount)
    return False, {"source": funding, "requested": round(amount, 3), "paid": 0.0,
                   "reason": f"'{funding}' is not a funding source an open act can use"}


def _apply_cut(w, entry: dict, lever: str, crowns: float, amount: float) -> tuple:
    """Lower a spending setting by the payment's share and hold it there (W3's cut funding)."""
    hold = entry.get("cut")
    if isinstance(hold, dict) and not (lever in w.const.directives
                                       and _same(w.const.directives.get(lever), hold.get("held"))):
        # W3's rule: a later decision that changed the setting supersedes the cut, so the funding is gone.
        return False, {"source": f"cut:{lever}", "requested": round(amount, 3), "paid": 0.0,
                       "reason": ("the setting its funding came from was changed by a later decision, so "
                                  "the cut no longer funds it")}
    bounds = politics.lever_bounds(lever)
    low = bounds[0] if bounds else 0.0
    current = _lever_value(w, lever)
    try:
        current = float(current)
    except (TypeError, ValueError):
        return False, {"source": f"cut:{lever}", "requested": round(amount, 3), "paid": 0.0,
                       "reason": f"{lever} has no value that could be cut"}
    capacity = max(0.0, (current - low) * max(1.0, w.econ.gdp_nominal))
    if crowns > capacity + TOLERANCE:
        return False, {"source": f"cut:{lever}", "requested": round(amount, 3), "paid": 0.0,
                       "capacity": round(capacity / 1e6, 2),
                       "reason": (f"{lever} has {current:g} of its output value above its floor of "
                                  f"{low:g}, which can fund {capacity / 1e6:,.1f}M a month, not "
                                  f"{amount:g}M")}
    share = crowns / max(1.0, w.econ.gdp_nominal)
    held = round(current - share, 6)
    if not isinstance(hold, dict):
        hold = {"lever": lever, "prior": current,
                "prior_directive_set": lever in w.const.directives,
                "prior_directive": w.const.directives.get(lever),
                "prior_bounds_set": lever in w.const.directive_bounds,
                "prior_bounds": dict(w.const.directive_bounds.get(lever) or {}) or None}
        entry["cut"] = hold
    politics.set_lever(w, lever, held)
    # The value actually in force is what the hold restores and what supersession is tested against.
    hold["held"] = round(float(_lever_value(w, lever)), 6)
    w.const.directives[lever] = hold["held"]
    w.const.directive_bounds[lever] = {"min": hold["held"], "max": hold["held"]}
    return True, {"source": f"cut:{lever}", "requested": round(amount, 3), "paid": round(amount, 3),
                  "cut_share": round(share, 6), "prior": round(current, 6), "held": hold["held"]}


def _release_cut(w, entry: dict, reason: str) -> dict | None:
    """Restore the setting a cut funded, unless a later decision replaced the directive it wrote."""
    hold = entry.get("cut")
    if not isinstance(hold, dict):
        return None
    lever = hold["lever"]
    intact = lever in w.const.directives and _same(w.const.directives.get(lever), hold.get("held"))
    if intact:
        politics.set_lever(w, lever, hold["prior"])
        if hold.get("prior_directive_set"):
            w.const.directives[lever] = hold["prior_directive"]
        else:
            w.const.directives.pop(lever, None)
        if hold.get("prior_bounds_set"):
            w.const.directive_bounds[lever] = dict(hold.get("prior_bounds") or {})
        else:
            w.const.directive_bounds.pop(lever, None)
        summary = {"lever": lever, "restored": True, "reason": reason}
    else:
        summary = {"lever": lever, "restored": False, "superseded": True, "reason": reason,
                   "note": "a later decision changed the setting, so the cut was not restored"}
    entry.pop("cut", None)
    return summary


# ---- the monthly step ----------------------------------------------------------------------------
def monthly(w) -> None:
    """Pay this month's remaining charges once. Called by the council at the start of the month."""
    entries = w.institutions.get(CHARGES_KEY)
    if not isinstance(entries, list) or not entries:
        return
    keep = []
    for entry in entries:
        try:
            due = int(entry.get("next_month", 0))
            months_left = int(entry.get("months_left", 0))
            amount = float(entry.get("monthly", 0.0))
        except (TypeError, ValueError):
            continue                    # an unreadable entry is dropped rather than guessed at
        if months_left <= 0:
            _release_cut(w, entry, "its schedule ended")
            continue
        if w.month < due:
            keep.append(entry)
            continue
        paid, payment = _pay(w, amount, entry.get("funding"), entry)
        if not paid:
            reason = payment.get("reason") or "the money could not be found"
            _append(w, {"kind": "charge", "motion": entry.get("motion"),
                        "proposer": entry.get("proposer"), "month": w.month, "refused": True,
                        "code": "OPEN_ACT_UNFUNDED", "reason": reason, "charged": 0.0,
                        "funding": entry.get("funding")})
            errors.record(w, "OPEN_ACT_UNFUNDED", reason, member=entry.get("proposer"),
                          motion=entry.get("motion"), later_charge=True)
            _release_cut(w, entry, "its funding ran out")
            continue                    # the remaining charges stop; the effects already landed
        entry["months_left"] = months_left - 1
        entry["next_month"] = w.month + 1
        if entry["months_left"] > 0:
            keep.append(entry)
        else:
            _release_cut(w, entry, "its schedule ended")
    w.institutions[CHARGES_KEY] = keep
