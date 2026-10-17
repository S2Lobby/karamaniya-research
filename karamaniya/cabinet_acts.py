"""The neighbours' open acts (engine 30, Wave A W8): plan 4.4, end to end.

Under `harness = "open"` only, Veleria and Dorsania may put one `open_act` among their four monthly acts.
This module carries the act out after both cabinets have answered and before `engine.step`:

* the reader (`foreign._read_cabinet_open_act`) has already checked the text, the target and the refused
  subjects, and its refusals reach the cabinet through the act-note path in `_apply_cabinet_decisions`;
* the same referee W5 uses (W4's `Referee`, one instance per run) is asked `ask(..., cabinet=True,
  actor=actor)`, in the fixed order veleria, then dorsania, and within a cabinet in the acts' own order, so
  the replay serves its answers deterministically and the shared draw sequence repeats;
* a valid feasible ruling draws once through `referee.outcome(w, ruling)` on the shared "open_act" stream: a
  failed draw still pays the cost and applies no effect;
* the ruling's total cost, one_off + monthly * months, is charged once, in the ruling month, through the
  cabinet's own budget path (`foreign._spend`, a share of its budget room). A cabinet has no reserves,
  borrowing or cut funding and no later-charge schedule, so the total is charged once (the lead's decision a);
* the effects are scheduled through the effect bus with source `{"kind": "cabinet_open_act", "actor": actor,
  "month": m}`. W4's cabinet validation limits the channels, targets and totals; scheduling reporting a
  problem is recorded, not guessed at;
* `referee_effects = "zeroed"` still asks, logs, draws and charges; nothing is scheduled, and the record says
  what would have applied.

Visibility (plan 4.4). A public ruling is announced in-world and appears in the delegates' next-month
briefing (`briefing._cabinet_acts_block`). A covert act is applied and recorded but not announced. Each month
its effects still run -- the airing month and every month in which one of the ruling's effects is still
applied -- it can be exposed, one draw per act per month on `rng_for(seed, month, "covert_exposure")` through
`foreign.exposure_roll`, with `foreign.covert_exposure_chance(w)`. Exposure makes it public, names the power in
a public event and costs the power relations (the documented constants in foreign.py); the cabinet is told
next month. The state media's "media" stream and every other draw are untouched. Wave B's B6 helper replaces
the body of `foreign.exposure_roll` at integration; the tag here is already "covert_exposure".

Records. The month's `open_acts` record (W5's `open_act_record`) gains entries with `kind = "cabinet_act"`
(and `kind = "cabinet_exposure"` for an exposure), each with `cabinet: true` and `actor`. Delegate entries are
unchanged, and the history row carries the list only when an act ran (engine.snapshot's existing rule).
"""
from __future__ import annotations

from . import actions, effects, errors, foreign, open_acts
from .world import clamp

ACTORS = ("veleria", "dorsania")
SOURCE_KIND = "cabinet_open_act"
RECORD_KIND = "cabinet_act"
EXPOSURE_KIND = "cabinet_exposure"
LIVE_KEY = "cabinet_open_acts_live"
DRAWS_KEY = "covert_exposure_draws"
TOLERANCE = 1e-9


# ---- state ---------------------------------------------------------------------------------------
def _harness(w) -> str:
    value = getattr(w, "harness", None)
    return value if value in actions.HARNESSES else "menu"


def live(w) -> list:
    """The covert acts still able to be exposed (read-only; an absent key is an empty list)."""
    entries = w.institutions.get(LIVE_KEY)
    return entries if isinstance(entries, list) else []


def _live_list(w) -> list:
    entries = w.institutions.get(LIVE_KEY)
    if not isinstance(entries, list):
        entries = []
        w.institutions[LIVE_KEY] = entries
    return entries


def _next_draw_index(w) -> int:
    """The next 0-based covert-exposure draw index this month, kept on the world so a replay repeats it.

    Only the current month's counter is kept, as referee.next_index does: the stream is per (seed, month).
    """
    counters = w.institutions.get(DRAWS_KEY)
    if not isinstance(counters, dict):
        counters = {}
    month = str(int(w.month))
    index = int(counters.get(month, 0))
    w.institutions[DRAWS_KEY] = {month: index + 1}
    return index


def _record(w) -> dict:
    """The month's open-act record (W5 owns its shape); created here for a month with only a cabinet act."""
    record = open_acts.month_record(w)
    if record is None:
        record = {"month": w.month, "open_acts": []}
        w.institutions[open_acts.RECORD_KEY] = record
    return record


def _append(w, entry: dict) -> None:
    _record(w)["open_acts"].append(entry)


# ---- the caller's interface ----------------------------------------------------------------------
def process(w, decisions, *, settings=None, referee=None, store=None, next_call_id=None,
            names=None) -> list:
    """Carry out this month's cabinet open acts, roll covert exposure, and return the entries created.

    `decisions` is the council's `_foreign_cabinets` result ({actor: normalized answer}); `settings` is the
    run's settings (its `referee_effects` selects the ablation); `referee`, `store`, `next_call_id` and
    `names` are the council's, exactly as for W5's delegate path. Nothing happens under any other harness,
    so a menu or language run is byte-identical to engine 29.

    A usage limit or an unreachable referee raises `council.RunPaused` after the attempt is logged, so the
    month is abandoned and replayed, as for a delegate's call. Every other refusal is recorded and returned.
    """
    if _harness(w) != "open":
        return []
    settings = dict(settings or {})
    zeroed = str(settings.get("referee_effects", "applied")) == "zeroed"
    decisions = decisions if isinstance(decisions, dict) else {}
    # A reader refusal of an open act is a registered engine error; its words already reach the cabinet
    # through the act-note path in foreign._apply_cabinet_decisions, which the engine runs after this.
    for actor in ACTORS:
        decision = decisions.get(actor)
        if not isinstance(decision, dict):
            continue
        for note in decision.get("act_notes") or []:
            if isinstance(note, dict) and note.get("type") == "open_act" and note.get("code"):
                errors.record(w, note["code"], note.get("reason") or "", actor=actor)
    # Covert acts still running from earlier months are rolled first, oldest first, then this month's acts.
    entries = _roll_live(w)
    for actor in ACTORS:
        decision = decisions.get(actor)
        if not isinstance(decision, dict) or not decision:
            continue
        for raw in decision.get("actions") or []:
            if not isinstance(raw, dict) or raw.get("type") != "open_act":
                continue
            entries.append(_carry_out(w, actor, raw, zeroed=zeroed, referee=referee, store=store,
                                      next_call_id=next_call_id, names=names))
    return entries


def _carry_out(w, actor: str, act: dict, *, zeroed: bool, referee, store, next_call_id, names) -> dict:
    """Rule, draw, charge, apply and record one cabinet open act."""
    text = str(act.get("text") or "")
    entry = {
        "kind": RECORD_KIND, "cabinet": True, "actor": actor, "month": w.month,
        "text": text, "target": act.get("target"),
        "public": False, "ruling": None, "outcome": None, "effects": [],
        "cost": {"one_off": 0.0, "monthly": 0.0, "months": 0, "total": 0.0, "charged": 0.0,
                 "path": "budget"},
        "refused": False, "code": "", "reason": "", "carried_out": False, "zeroed": zeroed,
        "attempts": 0, "call_id": None, "result": "", "exposed": False, "exposed_month": None,
    }
    if referee is None:
        # Decision (d) applied to cabinets: under harness = "open" a run without a referee is refused at start
        # (W6); this is the same failure in words from the execution path, for a direct call or an early run.
        return _refuse(w, entry, "EXECUTION_BLOCKED",
                       "No referee is configured for this run, so the act could not be carried out.")
    result = referee.ask(w, {"text": text, "target": act.get("target")}, cabinet=True, actor=actor,
                         names=names)
    call_ids = _log(w, result, store, next_call_id)
    entry["attempts"] = result.attempts
    entry["call_id"] = call_ids[0] if call_ids else None
    if result.paused or result.unavailable:
        from .council import RunPaused      # deferred: council.py imports this module
        raise RunPaused(result.seat, result.seat,
                        result.reason or "could not be reached", role="Referee")
    if result.failed:
        # W4 already recorded REFEREE_INVALID with the problems; the act fails as it does for a delegate.
        reason = (result.reason + " " + result.detail).strip()
        return _refuse(w, entry, "REFEREE_INVALID", reason, record_error=False)
    ruling = dict(result.ruling or {})
    entry["ruling"] = ruling
    entry["public"] = bool(ruling.get("public"))
    cost = ruling["cost"]
    one_off, monthly, months = float(cost["one_off"]), float(cost["monthly"]), int(cost["months"])
    total = one_off + monthly * months
    entry["cost"].update(one_off=one_off, monthly=monthly, months=months, total=round(total, 6))
    if not ruling.get("feasible"):
        # A valid refusal: the cabinet cannot do it. No draw, no cost, no effects.
        entry["refused"] = True
        entry["reason"] = str(ruling.get("reason") or "")
        entry["result"] = f"open act not carried out: {entry['reason']}"
        _append(w, entry)
        _remember(w, actor, entry)
        return entry

    outcome = referee.outcome(w, ruling)
    entry["outcome"] = outcome
    # Decision (a): the ruling's total is charged once in the ruling month through the cabinet's budget path.
    # The cabinet's budget is its fiscal stress (foreign._spend), not Karamaniya's reserves, borrowing or cuts,
    # and there is no monthly schedule: a later month charges nothing.
    foreign._spend(w, actor, total)
    entry["carried_out"] = True
    entry["cost"]["charged"] = round(total, 6)
    if outcome["worked"]:
        if zeroed:
            # The ablation: the ruling and the cost stand; the effects are withheld and the record says what
            # would have been applied.
            entry["effects"] = [{key: item.get(key) for key in ("channel", "target", "value", "months")}
                                | {"applied": False} for item in ruling["effects"]]
        else:
            source = {"kind": SOURCE_KIND, "actor": actor, "month": w.month}
            stored = effects.schedule(w, ruling["effects"], source)
            entry["effects"] = [{key: item.get(key) for key in ("channel", "target", "value", "months")}
                                | {"applied": True} for item in ruling["effects"]]
            if len(stored) != len(ruling["effects"]):
                # The bus validates the same list the referee's ruling was validated with, so this is a guard
                # rather than an expected path: record it in words instead of pretending the act landed.
                problem = "some of the act's effects could not be applied"
                entry["applied_problem"] = problem
                errors.record(w, "OPEN_ACT_NOT_APPLIED",
                              f"The cabinet's open act was ruled but {problem}.", actor=actor)
    if entry["public"]:
        # What the public sees: the report of what the act achieved, or that it did not. A quiet act is
        # recorded and never announced.
        w.event(SOURCE_KIND, outcome["report"], importance=2, public=True, actor=actor)
    if outcome["worked"]:
        entry["result"] = f"open act carried out by {actor.title()}: {outcome['report']}"
    else:
        entry["result"] = (f"open act carried out by {actor.title()}, but it did not work: "
                           f"{outcome['report']}")
    _append(w, entry)
    if not entry["public"]:
        _register_live(w, entry, ruling)
    _remember(w, actor, entry)
    return entry


def _refuse(w, entry: dict, code: str, reason: str, record_error: bool = True) -> dict:
    entry["refused"] = True
    entry["code"] = code
    entry["reason"] = reason
    entry["result"] = f"open act not carried out: {reason}"
    if record_error and code:
        errors.record(w, code, reason, actor=entry.get("actor"), act=entry.get("text", "")[:160])
    _append(w, entry)
    _remember(w, entry["actor"], entry)
    return entry


def _log(w, result, store, next_call_id) -> list:
    """Every attempt as a call and a prompt record, keyed like a delegate's (W4's log_records)."""
    if store is None or next_call_id is None:
        return []
    ids = [next_call_id() for _ in result.answers]
    for record in result.log_records(w, ids):
        store.log(record["call"])
        store.log_prompt(record["prompt"])
    return ids


# ---- the cabinet's next-month note ---------------------------------------------------------------
def _note(entry: dict) -> str:
    """What the cabinet is told next month, under the field it already reads (cabinet_view)."""
    text = entry.get("text", "")
    if entry.get("refused"):
        return f'Your open act ("{text}") was refused: {entry.get("reason") or "no reason was given"}'
    if not entry.get("carried_out"):
        return f'Your open act ("{text}") was not carried out.'
    outcome = entry.get("outcome") or {}
    note = (f'Your open act ("{text}") was carried out; it cost '
            f'{float((entry.get("cost") or {}).get("charged", 0.0)):g} of your budget room; it '
            f'{"worked" if outcome.get("worked") else "did not work"}.')
    if entry.get("public"):
        note += f' The public was told: "{outcome.get("report") or ""}"'
    else:
        note += " It was not announced publicly."
        if entry.get("exposed"):
            note += f" It was exposed in Month {int(entry.get('exposed_month') or 0) + 1}."
    return note


def _remember(w, actor: str, entry: dict) -> None:
    # The same memory kind the reader's act notes use: cabinet_view lists these under
    # your_acts_refused_last_month, which is the field a cabinet already reads.
    foreign._remember(w.foreign, actor, "rejected_action", _note(entry), w.month,
                      action={"type": "open_act"})


# ---- covert exposure -----------------------------------------------------------------------------
def _register_live(w, entry: dict, ruling: dict) -> None:
    """Track a carried-out covert act, and roll its first exposure chance in the airing month.

    The window is the airing month and every month in which one of the ruling's effects is still applied: a
    failed draw (or a ruling with no effects) leaves only the airing month. A zeroed run uses the ruling's
    effect months, because the effects it withholds are the ones that would have been running.
    """
    effects_ = ruling.get("effects") or []
    months = max((int(item.get("months", 1) or 0) for item in effects_), default=0)
    if not (entry.get("outcome") or {}).get("worked") or months < 1:
        months = 0
    item = {"actor": entry["actor"], "text": entry["text"], "month": w.month,
            "end_month": w.month + max(0, months - 1)}
    if _roll_one(w, item, remember=False) is not None:
        entry["exposed"] = True
        entry["exposed_month"] = w.month
        return
    _live_list(w).append(item)


def _roll_live(w) -> list:
    """Roll one exposure draw for each covert act still live this month; return the exposure entries."""
    entries, keep = [], []
    for item in _live_list(w):
        try:
            end = int(item.get("end_month", w.month))
        except (TypeError, ValueError):
            end = w.month
        if end < w.month:
            continue                    # its effects have run out; it can no longer be exposed
        exposure = _roll_one(w, item, remember=True)
        if exposure is not None:
            entries.append(exposure)
        else:
            keep.append(item)
    w.institutions[LIVE_KEY] = keep
    return entries


def _roll_one(w, item: dict, *, remember: bool) -> dict | None:
    """One draw on the "covert_exposure" stream for one act; the exposure entry when it is caught."""
    index = _next_draw_index(w)
    if not foreign.exposure_roll(w, "covert_exposure", foreign.covert_exposure_chance(w), index=index):
        return None
    return _expose(w, item, remember=remember)


def _expose(w, item: dict, *, remember: bool) -> dict:
    """Make a covert act public: the event, the relations cost, the record, and the cabinet's note."""
    actor = item["actor"]
    name = w.names.get(actor, actor.title())
    text = item.get("text", "")
    relations = w.foreign["actors"][actor]["relations"]["karamaniya"]
    relations["trust"] = round(clamp(float(relations.get("trust", 0.0)) - foreign.EXPOSURE_TRUST), 3)
    relations["hostility"] = round(clamp(float(relations.get("hostility", 0.0))
                                        + foreign.EXPOSURE_HOSTILITY), 3)
    w.event("scandal", f"Karamaniya announced that it had uncovered a covert operation by {name}: \"{text}\".",
            importance=3, public=True, actor=actor)
    entry = {"kind": EXPOSURE_KIND, "cabinet": True, "actor": actor, "month": w.month,
             "month_acted": int(item.get("month", w.month)), "text": text, "public": True,
             "exposed": True,
             "relations_cost": {"trust": -foreign.EXPOSURE_TRUST,
                                "hostility": foreign.EXPOSURE_HOSTILITY}}
    _append(w, entry)
    if remember:
        foreign._remember(
            w.foreign, actor, "rejected_action",
            f'Your covert open act of Month {int(item.get("month", w.month)) + 1} ("{text}") was exposed '
            f'in Month {w.month + 1}; it cost your government standing with Karamaniya.',
            w.month, action={"type": "open_act"})
    return entry
