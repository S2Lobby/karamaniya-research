"""The policy language's execution (engine 30, Wave A W3): four deterministic instruments.

A `policy` motion carries one to four canonical items (actions.policy_items_of). This module is the only
place that carries them out. It makes no random draw and calls no model: every month the same state
produces the same result.

Instruments
-----------
`set_lever` holds a setting at a value while its condition holds and its schedule runs. It uses the
programme path exactly (`politics.set_lever` plus `c.directives` and `c.directive_bounds` with an exact
bound), so an office order against it is recorded as defiance by `politics.apply_orders`. The value from
before the hold is kept; when the hold ends (the schedule runs out, or the condition stops holding, or a
later decision changes the setting) the prior value and the prior directive are put back, unless the
directive is no longer the one the hold wrote, which is recorded as superseded.

`transfer` pays a group each month. The money is charged through the engine's funding paths (reserves,
borrowing, or a cut to a spending setting) and reaches the people through the effect bus's `income` and
`hunger` channels and through `grievance` and `approval` reactions, all scaled per head on the target.
The money channels land in the month it is paid; the two public reactions are folded in by the next
month's society step, as every reaction scheduled after that step's fold is.
The scales are synthetic and documented below.

`public_works` spends money in one region. Each month's payment buys a repair that lands through the bus
with a one- to two-month lag: logistics and the local income it buys after one month, damage after two,
queued by this module because the bus has no delay of its own. The scales reuse disaster relief's own
cost formulas (`politics.RELIEF_DAMAGE_MONTHS`, `RELIEF_LOGISTICS_MONTHS`, `_region_output_share`). The
engine has no unemployment channel and derives unemployment from output, so a direct unemployment effect
cannot be expressed; that is recorded here rather than invented.

`commission` is a standing body with one mandate, a monthly budget and a duration. Each month it applies
one small effect on its mandate's channel, scaled by `Economy.admin_capacity` and by its budget against
a reference budget, and capped.

Schedules and conditions
------------------------
`start_in` delays the first month (0-6) and `months` bounds the run (1-24). An item's condition is tested
at the start of each month, on that month's opening state, with the evaluator conditional votes use
(`motion_actions.evaluate_conditions`). A false condition pauses the item for that month: a held setting
is released, no money is paid, and the item resumes (taking a fresh prior value) when the condition holds
again.

Funding
-------
- `reserves`: paid from gold above the item's own reserve floor (a `reserves` or `reserves_after_payment`
  `>=` condition), refused when the month's amount cannot be paid above it.
- `borrowing`: domestic bonds within the engine's own monthly capacity (`politics.borrowing_capacity`,
  which mirrors `economy.fiscal`), refused beyond it.
- `cut:<lever>`: lowers a spending setting by the amount (as a share of the month's output) and holds it
  there while the item runs, restoring it when the item stops, refused when the setting has no room above
  its lower bound. A later decision that changes the setting supersedes the cut; the item then stops and
  says so, because its funding is gone.
A spending item is refused for the month, with the reason, when its funding cannot cover it; the item
stays on its schedule and may be paid in a later month.

Records
-------
The month's history row carries `policies` (only when a policy is scheduled, running or touched that
month): `in_force`, `applied`, `ended` and `refused`, each entry naming the item and its reason. A hold's
prior value and any supersession are in the entry. Effects scheduled here travel the bus with
`source = {"kind": "policy", "actor": proposer, "motion": id, "month": month}`.
"""
from __future__ import annotations

from . import actions, effects, motion_actions, politics
from .world import OFFICES, clamp

# Where the module keeps its state on the world. An old checkpoint has neither key and reads as empty.
POLICY_KEY = "policies"
RECORD_KEY = "policy_record"

# ---- transfer scales -----------------------------------------------------------------------------
# SYNTHETIC MODELING ASSUMPTION: a transfer pays amount / population crowns to each person it reaches.
# Income is an index with 1.0 at the start, so the per-head payment is expressed against average monthly
# output per head (Economy.gdp_nominal / population): a payment of one tenth of average income moves the
# income target by .10, capped at the bus's .02. Half the money is assumed to buy food; at the world food
# price a payment of one average-income month would cover far more than a person's monthly need, so the
# cap binds for any sizeable transfer. Grievance and approval are fractions of the income part, capped
# well below the bus's own limits: the plan keeps `welfare` as the main approval and grievance lever and
# gives the transfer the per-head money side.
TRANSFER_INCOME_CAP = .02
TRANSFER_HUNGER_CAP = .02
TRANSFER_GRIEVANCE_CAP = .015
TRANSFER_APPROVAL_CAP = .01
TRANSFER_FOOD_SHARE = .5
TRANSFER_GRIEVANCE_SHARE = .5
TRANSFER_APPROVAL_SHARE = .25

# ---- public works --------------------------------------------------------------------------------
# The lags are the plan's one to two months: freight and the local income the wage bill buys after one
# month; structural repair after two. A payment made in the schedule's last month still lands.
PUBLIC_WORKS_LOGISTICS_LAG = 1
PUBLIC_WORKS_DAMAGE_LAG = 2
PUBLIC_WORKS_DAMAGE_CAP = .02
PUBLIC_WORKS_LOGISTICS_CAP = .05
PUBLIC_WORKS_INCOME_CAP = .01
PUBLIC_WORKS_INCOME_SHARE = .25

# ---- commissions ---------------------------------------------------------------------------------
# A budget of 5M crowns a month counts as the reference; larger budgets do not scale past one, and the
# work is further scaled by how much of the administration is actually working. Each mandate's maximum
# monthly move is below the bus's per-entry cap on its channel.
COMMISSION_REFERENCE_BUDGET = 5.0
COMMISSION_MAX = {"anti_corruption": .015, "food_distribution": .015, "reconstruction": .015,
                  "minority_liaison": .015, "statistics": .01}
# Corruption is tracked by spending ministry; the head of government is not a ministry the body audits.
CORRUPTION_OFFICES = ("treasury", "interior", "army", "navy")

# Who carries each instrument out (plan 4.2). set_lever follows politics.LEVER_OFFICE instead.
INSTRUMENT_OFFICE = {"transfer": "treasury", "public_works": "treasury", "commission": "head"}

_MISSING = object()


# ---- state ---------------------------------------------------------------------------------------
def state(w) -> dict:
    """The policy store, created on first use. An old checkpoint has none and starts empty."""
    return w.institutions.setdefault(POLICY_KEY, {"active": [], "next_id": 1, "step_month": -1})


def active(w) -> list:
    """The live policy items, without creating any state."""
    return list((w.institutions.get(POLICY_KEY) or {}).get("active") or [])


def month_record(w):
    """This month's policy record, or None. `engine.snapshot` adds it to the history row when present."""
    record = w.institutions.get(RECORD_KEY)
    if not isinstance(record, dict) or record.get("month") != w.month:
        return None
    return record


def _source(w, entry: dict) -> dict:
    return {"kind": "policy", "actor": entry.get("proposer"), "motion": entry.get("motion"),
            "month": w.month}


def _gold_to_local(w) -> float:
    """Crowns one unit of gold buys, as the relief path reads it."""
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


# ---- adoption ------------------------------------------------------------------------------------
def _item_text(item: dict) -> str:
    instrument = item.get("instrument")
    condition = item.get("condition")
    tail = ""
    if condition:
        tail = f" while {condition['metric']} {condition['operator']} {condition['value']:g}"
    if instrument == "set_lever":
        return f"{item['lever']} = {politics.fmt_value(item['value'])}"
    if instrument == "transfer":
        return f"{item['amount']:g}M a month to {item['target']}"
    if instrument == "public_works":
        return f"public works in {item['target']} at {item['amount']:g}M a month"
    return f"a {item['mandate'].replace('_', ' ')} commission at {item['amount']:g}M a month" + tail


def adopt(w, motion: dict) -> str:
    """Schedule a carried policy motion's items. Called by politics.apply_motion; changes no state yet.

    The monthly hook (engine.step, via `monthly`) carries the items out, so a start_in of 0 applies in
    the same month the council passed it.
    """
    items = actions.policy_items_of(w, motion)
    if not items:
        return "no policy item could be read from the motion; nothing was adopted"
    conflict = motion_actions._policy_conflict(items)
    if conflict:
        # The tabling reader has already refused the shapes it owns; a direct call (a scripted stand-in, a
        # replay) reaches the same verdict rather than adopting a contradictory policy.
        return f"policy not adopted: {conflict['detail']}"
    store = state(w)
    parts = []
    for index, raw in enumerate(items):
        item = dict(raw)
        start = w.month + int(item.get("start_in", 0))
        months = int(item.get("months", 1))
        end = start + months - 1
        instrument = item.get("instrument")
        office = (politics.LEVER_OFFICE.get(item.get("lever")) if instrument == "set_lever"
                  else INSTRUMENT_OFFICE.get(instrument))
        entry = {"id": f"{motion.get('id') or 'policy'}#{index + 1}",
                 "motion": motion.get("id"), "proposer": motion.get("proposer"),
                 "instrument": instrument, "item": item, "office": office,
                 "start": start, "end": end, "holds": [], "pending": [], "created": w.month}
        store["active"].append(entry)
        parts.append(f"{_item_text(item)} from Month {start + 1} for {months} month"
                     + ("s" if months != 1 else ""))
    return "policy adopted: " + "; ".join(parts)


# ---- holds ---------------------------------------------------------------------------------------
def _hold(entry: dict, role: str):
    for hold in entry.get("holds") or []:
        if hold.get("role") == role:
            return hold
    return None


def _hold_summaries(entry: dict) -> list:
    return [{"lever": hold["lever"], "role": hold["role"], "prior": hold["prior"], "held": hold["held"]}
            for hold in entry.get("holds") or []]


def _hold_intact(w, hold: dict) -> bool:
    """Whether the council directive this hold wrote is still the one in force on that setting."""
    directive = w.const.directives.get(hold["lever"], _MISSING)
    return directive is not _MISSING and _same(directive, hold["held"])


def _establish(w, entry: dict, lever: str, value, role: str) -> dict:
    """Set a setting to `value` through the programme's directive path and remember what was there."""
    entry["holds"] = [hold for hold in entry.get("holds") or []
                      if (hold.get("role"), hold.get("lever")) != (role, lever)]
    hold = {"lever": lever, "role": role,
            "prior": _lever_value(w, lever),
            "prior_directive_set": lever in w.const.directives,
            "prior_directive": w.const.directives.get(lever),
            "prior_bounds_set": lever in w.const.directive_bounds,
            "prior_bounds": dict(w.const.directive_bounds.get(lever) or {}) or None,
            "held": value, "month": w.month}
    politics.set_lever(w, lever, value)
    # A deployment share is normalised against the others; the value actually in force is what the hold
    # restores and what supersession is tested against.
    hold["held"] = _lever_value(w, lever)
    w.const.directives[lever] = hold["held"]
    w.const.directive_bounds[lever] = {"min": hold["held"], "max": hold["held"]}
    entry["holds"].append(hold)
    return hold


def _end_hold(w, entry: dict, hold: dict, reason: str) -> dict:
    """End one hold: restore the prior value and ledger unless a later decision replaced the directive."""
    lever = hold["lever"]
    current = _lever_value(w, lever)
    summary = {"lever": lever, "role": hold["role"], "prior": hold["prior"], "held": hold["held"],
               "reason": reason}
    if not _hold_intact(w, hold):
        directive = w.const.directives.get(lever, _MISSING)
        summary.update(restored=False, superseded=True,
                       current=current,
                       directive=None if directive is _MISSING else directive,
                       note="a later decision changed the setting, so the hold was superseded")
        return summary
    politics.set_lever(w, lever, hold["prior"])
    if hold.get("prior_directive_set"):
        w.const.directives[lever] = hold["prior_directive"]
    else:
        w.const.directives.pop(lever, None)
    if hold.get("prior_bounds_set"):
        w.const.directive_bounds[lever] = dict(hold.get("prior_bounds") or {})
    else:
        w.const.directive_bounds.pop(lever, None)
    summary.update(restored=True, superseded=False, current=_lever_value(w, lever),
                   office_order_during_hold=None if _same(current, hold["held"]) else current)
    return summary


def _end_holds(w, entry: dict, reason: str) -> list:
    summaries = []
    for hold in list(entry.get("holds") or []):
        summaries.append(_end_hold(w, entry, hold, reason))
    entry["holds"] = []
    return summaries


# ---- records -------------------------------------------------------------------------------------
def _in_force(entry: dict, status: str, reason: str = "") -> dict:
    out = {"id": entry["id"], "motion": entry.get("motion"), "instrument": entry["instrument"],
           "office": entry.get("office"), "item": entry.get("item"),
           "start_month": entry["start"], "end_month": entry["end"],
           "status": status, "holds": _hold_summaries(entry)}
    if reason:
        out["reason"] = reason
    return out


def _applied(entry: dict, detail: dict, funding: dict | None = None, scheduled=None) -> dict:
    return {"id": entry["id"], "motion": entry.get("motion"), "instrument": entry["instrument"],
            "office": entry.get("office"), "item": entry.get("item"), "detail": detail,
            "funding": dict(funding or {}), "holds": _hold_summaries(entry),
            "effects": [{"channel": item.get("channel"), "target": item.get("target"),
                         "value": item.get("value")} for item in (scheduled or [])]}


def _refuse(entry: dict, record: dict, code: str, reason: str) -> None:
    record["refused"].append({"id": entry["id"], "motion": entry.get("motion"),
                              "instrument": entry["instrument"], "office": entry.get("office"),
                              "item": entry.get("item"), "code": code, "reason": reason})


# ---- funding -------------------------------------------------------------------------------------
def _reserve_floor(entry: dict) -> float:
    """The reserve floor the item's own condition puts on a payment from reserves.

    `politics.payment_floor` reads a motion's `reserves_after_payment` floor; here the floor is the item's
    condition when it is a `>=` on `reserves` (today's balance, the reading engine 22 gave a structured
    reserves condition) or on `reserves_after_payment`. Both are in the gold reserves are held in.
    """
    condition = entry.get("item", {}).get("condition") or {}
    if condition.get("operator") == ">=" and condition.get("metric") in ("reserves",
                                                                         "reserves_after_payment"):
        try:
            return float(condition.get("value") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _cut_capacity(w, lever: str) -> tuple:
    """(room above the setting's lower bound, in crowns, the current value) for a cut."""
    bounds = politics.lever_bounds(lever)
    low = bounds[0] if bounds else 0.0
    current = float(_lever_value(w, lever) or 0.0)
    return max(0.0, (current - low) * max(1.0, w.econ.gdp_nominal)), current, low


def _fund(w, entry: dict, record: dict):
    """Charge this month's amount through the item's funding source, or record the refusal."""
    item = entry["item"]
    amount = float(item.get("amount") or 0.0)
    source = str(item.get("funding") or "")
    crowns = amount * 1e6
    if source == "reserves":
        floor = _reserve_floor(entry)
        rate = _gold_to_local(w)
        capacity = max(0.0, (float(w.econ.gold) - floor) * rate)
        if crowns > capacity + 1e-6:
            _refuse(entry, record, "POLICY_UNFUNDED",
                    f"the reserves hold {w.econ.gold / 1e6:,.1f}M against a floor of {floor / 1e6:,.1f}M, "
                    f"which can pay {capacity / 1e6:,.1f}M this month, not {amount:g}M")
            return None
        w.econ.gold = max(0.0, w.econ.gold - crowns / max(rate, .01))
        return {"source": "reserves", "requested": round(amount, 3), "paid": round(amount, 3),
                "capacity": round(capacity / 1e6, 2)}
    if source == "borrowing":
        capacity = politics.borrowing_capacity(w)
        if crowns > capacity + 1e-6:
            _refuse(entry, record, "POLICY_UNFUNDED",
                    f"the domestic market can lend {capacity / 1e6:,.1f}M crowns this month, "
                    f"not {amount:g}M")
            return None
        w.econ.debt_dom += crowns
        # The same-month issuance registry economy.fiscal reads: it subtracts what was already issued
        # this month from the market's capacity, so a policy's borrowing competes with the budget's.
        issued = w.institutions.setdefault("arrears_bonds", {"month": w.month, "amount": 0.0})
        if issued.get("month") != w.month:
            issued.update(month=w.month, amount=0.0)
        issued["amount"] = float(issued.get("amount", 0.0)) + crowns
        return {"source": "borrowing", "requested": round(amount, 3), "paid": round(amount, 3),
                "capacity": round(capacity / 1e6, 2)}
    if source.startswith("cut:"):
        lever = source[len("cut:"):]
        if lever not in actions.SPENDING_LEVERS:
            _refuse(entry, record, "POLICY_UNFUNDED",
                    f"a policy can cut only a spending setting ({', '.join(actions.SPENDING_LEVERS)}); "
                    f"'{lever}' is not one")
            return None
        hold = _hold(entry, "funding")
        if hold is not None:
            if not _hold_intact(w, hold):
                summary = _end_hold(w, entry, hold, "its funding cut no longer held")
                entry["holds"] = [h for h in entry["holds"] if h is not hold]
                entry["done"] = True
                record["ended"].append({"id": entry["id"], "motion": entry.get("motion"),
                                        "instrument": entry["instrument"], "office": entry.get("office"),
                                        "item": entry.get("item"),
                                        "reason": "its funding cut was superseded by a later decision",
                                        "holds": [summary]})
                _refuse(entry, record, "POLICY_UNFUNDED",
                        "the setting its funding came from was changed by a later decision, so the cut "
                        "no longer funds it")
                return None
            return {"source": source, "requested": round(amount, 3), "paid": round(amount, 3),
                    "cut_share": round(float(hold["prior"]) - float(hold["held"]), 6),
                    "saved": round((float(hold["prior"]) - float(hold["held"]))
                                   * max(1.0, w.econ.gdp_nominal) / 1e6, 2)}
        capacity, current, low = _cut_capacity(w, lever)
        if crowns > capacity + 1e-6:
            _refuse(entry, record, "POLICY_UNFUNDED",
                    f"{lever} has {current:g} of its output value above its floor of {low:g}, which can "
                    f"fund {capacity / 1e6:,.1f}M a month, not {amount:g}M")
            return None
        share = crowns / max(1.0, w.econ.gdp_nominal)
        held = round(current - share, 6)
        _establish(w, entry, lever, held, "funding")
        return {"source": source, "requested": round(amount, 3), "paid": round(amount, 3),
                "cut_share": round(share, 6), "saved": round(amount, 3),
                "prior": round(current, 6), "held": held}
    _refuse(entry, record, "POLICY_UNFUNDED", f"'{source}' is not a funding source a policy can use")
    return None


# ---- effect builders -----------------------------------------------------------------------------
def _target_population(w, target: str) -> float:
    pops = w.k_pops()
    if target == "*":
        return sum(p.size for p in pops)
    if target.startswith("ident:"):
        return sum(p.size for p in pops if p.ident == target[len("ident:"):])
    if target.startswith("class:"):
        return sum(p.size for p in pops if p.cls == target[len("class:"):])
    return sum(p.size for p in pops if p.region == target)


def _transfer_effects(w, item: dict) -> tuple:
    """The per-head monthly effects of one payment. `(effects, problem)`."""
    target = str(item.get("target") or "")
    population = _target_population(w, target)
    if population <= 0:
        return None, f"no one lives in {target} under this government"
    amount = float(item.get("amount") or 0.0) * 1e6
    per_head = amount / population
    average_income = max(1.0, w.econ.gdp_nominal) / max(1.0, w.population() or 1.0)
    income = min(TRANSFER_INCOME_CAP, per_head / max(1e-9, average_income))
    per_head_gold = per_head / max(0.01, _gold_to_local(w))
    from .economy import WORLD_FOOD_PRICE
    hunger = min(TRANSFER_HUNGER_CAP, TRANSFER_FOOD_SHARE * per_head_gold / WORLD_FOOD_PRICE)
    grievance = min(TRANSFER_GRIEVANCE_CAP, TRANSFER_GRIEVANCE_SHARE * income)
    approval = min(TRANSFER_APPROVAL_CAP, TRANSFER_APPROVAL_SHARE * income)
    out = [{"channel": "income", "target": target, "value": round(income, 5), "months": 1,
            "reason": "a transfer's per-head payment"},
           {"channel": "hunger", "target": target, "value": -round(hunger, 5), "months": 1,
            "reason": "a transfer's food share"},
           {"channel": "grievance", "target": target, "value": -round(grievance, 5), "months": 1,
            "reason": "a transfer eased the cost of living"},
           {"channel": "approval", "target": target, "value": round(approval, 5), "months": 1,
            "reason": "a transfer was felt as the government's help"}]
    return [entry for entry in out if abs(float(entry["value"])) >= 1e-6], None


def _works_effects(w, item: dict) -> tuple:
    """The repairs one month's public-works payment buys: (flat effects, queued work, problem)."""
    region = w.region(str(item.get("target") or ""))
    amount = float(item.get("amount") or 0.0) * 1e6
    output = max(1.0, w.econ.gdp_nominal) * politics._region_output_share(w, region)
    base = amount / output
    damage = min(PUBLIC_WORKS_DAMAGE_CAP, base / politics.RELIEF_DAMAGE_MONTHS)
    logistics = min(PUBLIC_WORKS_LOGISTICS_CAP,
                    base / politics.RELIEF_LOGISTICS_MONTHS * max(0.0, 1.0 - region.logistics))
    income = min(PUBLIC_WORKS_INCOME_CAP, PUBLIC_WORKS_INCOME_SHARE * base)
    early = [{"channel": "logistics", "target": region.id, "value": round(logistics, 5), "months": 1,
              "reason": "public works restored freight"},
             {"channel": "income", "target": region.id, "value": round(income, 5), "months": 1,
              "reason": "public works bought labour in the region"}]
    late = [{"channel": "damage", "target": region.id, "value": -round(damage, 5), "months": 1,
             "reason": "public works repaired structural damage"}]
    early = [entry for entry in early if abs(float(entry["value"])) >= 1e-6]
    late = [entry for entry in late if abs(float(entry["value"])) >= 1e-6]
    queued = []
    if early:
        queued.append({"due": w.month + PUBLIC_WORKS_LOGISTICS_LAG, "label": "freight and wages",
                       "effects": early})
    if late:
        queued.append({"due": w.month + PUBLIC_WORKS_DAMAGE_LAG, "label": "structural repair",
                       "effects": late})
    return early + late, queued, None


def _commission_effects(w, item: dict) -> tuple:
    """The mandate's one small monthly effect, scaled by budget and administration, capped."""
    mandate = str(item.get("mandate") or "")
    if mandate not in COMMISSION_MAX:
        return None, f"'{mandate}' is not a commission mandate"
    budget = min(1.0, float(item.get("amount") or 0.0) / COMMISSION_REFERENCE_BUDGET)
    factor = budget * clamp(float(w.econ.admin_capacity), 0.0, 1.0)
    value = COMMISSION_MAX[mandate] * factor
    if value < 1e-6:
        return None, "with this budget and administration the body would move nothing"
    if mandate == "anti_corruption":
        corruption = w.institutions.get("corruption") or {}
        target = max(CORRUPTION_OFFICES,
                     key=lambda office: (float(corruption.get(office, 0.0)),
                                         -CORRUPTION_OFFICES.index(office)))
        effect = {"channel": "corruption", "target": target, "value": -round(value, 5), "months": 1,
                  "reason": "an anti-corruption commission's work"}
    elif mandate == "food_distribution":
        effect = {"channel": "hunger", "target": "*", "value": -round(value, 5), "months": 1,
                  "reason": "a food-distribution commission's work"}
    elif mandate == "reconstruction":
        regions = w.k_regions()
        if not regions:
            return None, "there is no region left to rebuild"
        region = max(regions, key=lambda r: (float(r.damage), -regions.index(r)))
        effect = {"channel": "damage", "target": region.id, "value": -round(value, 5), "months": 1,
                  "reason": "a reconstruction commission's work"}
    elif mandate == "minority_liaison":
        effect = {"channel": "grievance", "target": "ident:vell", "value": -round(value, 5),
                  "months": 1, "reason": "a minority-liaison commission's work"}
    else:   # statistics
        effect = {"channel": "admin_capacity", "target": "*", "value": round(value, 5), "months": 1,
                  "reason": "a statistics commission's work"}
    return [effect], None


# ---- the monthly step ----------------------------------------------------------------------------
def _release_pending(w, entry: dict, record: dict) -> None:
    """Release repairs whose lag has elapsed. The bus has no delay, so this module keeps the queue."""
    pending = entry.get("pending") or []
    if not pending:
        return
    due = [p for p in pending if int(p.get("due", 0)) <= w.month]
    if not due:
        return
    entry["pending"] = [p for p in pending if int(p.get("due", 0)) > w.month]
    for work in due:
        accepted, problems = effects.validate(w, work.get("effects") or [], _source(w, entry))
        if problems:
            first = problems[0]
            _refuse(entry, record, first["code"],
                    f"the {work.get('label')} bought in Month {int(work['due']) + 1} could not land: "
                    f"{first['problem']}")
            continue
        stored = effects.schedule(w, accepted, _source(w, entry))
        record["applied"].append(_applied(
            entry, {"works": work.get("label"), "due_month": int(work.get("due", w.month)),
                    "paid_in_month": w.month - int(work.get("due", w.month))},
            funding={}, scheduled=stored))


def _pause(w, entry: dict, record: dict) -> None:
    summaries = _end_holds(w, entry, "its condition stopped holding")
    if summaries:
        record["ended"].append({"id": entry["id"], "motion": entry.get("motion"),
                                "instrument": entry["instrument"], "office": entry.get("office"),
                                "item": entry.get("item"), "reason": "its condition stopped holding",
                                "holds": summaries})


def _finalize(w, entry: dict, record: dict, reason: str) -> None:
    summaries = _end_holds(w, entry, reason)
    entry["done"] = True
    record["ended"].append({"id": entry["id"], "motion": entry.get("motion"),
                            "instrument": entry["instrument"], "office": entry.get("office"),
                            "item": entry.get("item"), "reason": reason, "holds": summaries})


def _apply_set_lever(w, entry: dict, record: dict) -> None:
    item = entry["item"]
    lever = str(item.get("lever") or "")
    hold = _hold(entry, "lever")
    if hold is not None and not _hold_intact(w, hold):
        summary = _end_hold(w, entry, hold, "a later decision changed the setting")
        entry["holds"] = [h for h in entry["holds"] if h is not hold]
        entry["done"] = True
        record["ended"].append({"id": entry["id"], "motion": entry.get("motion"),
                                "instrument": entry["instrument"], "office": entry.get("office"),
                                "item": item, "reason": "a later decision changed the setting",
                                "holds": [summary]})
        return
    if hold is None:
        _establish(w, entry, lever, item.get("value"), "lever")
    record["applied"].append(_applied(
        entry, {"lever": lever, "value": item.get("value"),
                "held": _hold(entry, "lever")["held"] if _hold(entry, "lever") else item.get("value")}))


def _apply_spending(w, entry: dict, record: dict) -> None:
    item = entry["item"]
    instrument = entry["instrument"]
    if instrument == "transfer":
        proposed, problem = _transfer_effects(w, item)
        queued = None
    elif instrument == "public_works":
        proposed, queued, problem = _works_effects(w, item)
    else:
        proposed, problem = _commission_effects(w, item)
        queued = None
    if problem:
        _refuse(entry, record, "POLICY_BAD_TARGET", problem)
        return
    accepted, problems = effects.validate(w, proposed, _source(w, entry))
    if problems:
        first = problems[0]
        _refuse(entry, record, first["code"], first["problem"])
        return
    funding = _fund(w, entry, record)
    if funding is None:
        return
    if queued is not None:
        # Public works: the same accepted effects are released after their lag (see _release_pending).
        entry["pending"] = (entry.get("pending") or []) + queued
        record["applied"].append(_applied(entry, {"works": "paid for; work under way"}, funding=funding,
                                          scheduled=accepted))
    else:
        stored = effects.schedule(w, accepted, _source(w, entry))
        record["applied"].append(_applied(entry, {"paid": True}, funding=funding, scheduled=stored))


def _run_entry(w, entry: dict, record: dict) -> None:
    _release_pending(w, entry, record)
    if entry.get("done"):
        return
    start, end = int(entry["start"]), int(entry["end"])
    if w.month > end:
        # The last scheduled month has run; the hold is released at the start of the month after it, so
        # the setting was in force through the whole month the council ordered it for.
        if entry.get("pending"):
            record["in_force"].append(_in_force(entry, "finishing", "paid work is still under way"))
            return
        _finalize(w, entry, record, "its schedule ended")
        return
    if w.month < start:
        record["in_force"].append(_in_force(entry, "scheduled", f"it starts in Month {start + 1}"))
        return
    condition = entry["item"].get("condition")
    if condition:
        result = motion_actions.evaluate_conditions(w, [condition])[0]
        if not result.get("met"):
            reason = result.get("reason") or f"condition {condition['metric']} is not met"
            _pause(w, entry, record)
            record["in_force"].append(_in_force(entry, "paused", f"its condition is not met: {reason}"))
            return
    if entry["instrument"] == "set_lever":
        _apply_set_lever(w, entry, record)
    else:
        _apply_spending(w, entry, record)
    record["in_force"].append(_in_force(entry, "running" if not entry.get("done") else "ended"))


def monthly(w) -> None:
    """Carry out every live policy item once for this month. Called at the start of engine.step."""
    store = w.institutions.get(POLICY_KEY)
    if not isinstance(store, dict):
        return
    if store.get("step_month") == w.month:
        return
    store["step_month"] = w.month
    record = {"month": w.month, "in_force": [], "applied": [], "ended": [], "refused": []}
    keep = []
    for entry in list(store.get("active") or []):
        _run_entry(w, entry, record)
        if not entry.get("done"):
            keep.append(entry)
    store["active"] = keep
    if any(record[section] for section in ("in_force", "applied", "ended", "refused")):
        w.institutions[RECORD_KEY] = record
    else:
        w.institutions.pop(RECORD_KEY, None)
