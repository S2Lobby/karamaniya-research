"""The effect bus (engine 30, Wave A W1): one bounded registry every new consequence passes through.

A policy, an open act or a neighbour's open act states what it changes in the world as a list of effects. This
module is the only place that turns such a list into state. It validates each effect against a channel registry
with measured caps, schedules the accepted ones, applies and ages them once a month, and records what was applied.

Channels and caps. Every cap is per entry and per month, and the per-month cap is summed over every entry on the
same channel and target. The figures are A0-recon section 5's measured table, adopted by the lead's decision 4; each
channel's `why` names the run that measured it or the engine instrument it is set below. Society channels are the
five kinds `public_mood.react` already folds into the society step; they are scheduled there, so existing behaviour
when nothing is scheduled is untouched. `income` and `hunger` are stored as capped modifiers that `society.update`
reads (A0-recon contradiction 1, resolved by decision 1). No random draw is made here: nothing on the bus is random.

Where the step runs. `engine.step` calls `effects.step(w)` after the economy has produced and priced the month
(`economy.money_and_prices`) and immediately before `society.update`. That point is chosen for four reasons:

* `dilemmas.apply_ongoing` runs at the top of `engine.step` and has already folded and aged the society reactions,
  so their applied values are known (public_mood appends them to a pending list for the bus) and are recorded here;
* the income and hunger modifiers must be in place before `society.update` reads them, which is the only step that
  can put a transfer in front of people in the month it is decided;
* damage, logistics, capacity and confidence are stocks whose own updaters run inside the fiscal step; applying the
  bus's deltas after that step keeps them from being recomputed away, so they persist into the next month's
  production, society and council session;
* the bus is not a second producer: it does not change the output or the prices of the month in which it is applied.

An entry holds `channel, target, value, months_left, decay, reason, month, source`. `step` applies it, records the
value actually applied (a later entry on the same channel and target is clipped to what is left of the month cap),
then ages it: one month off `months_left`, `value` multiplied by `decay`. Entries in `w.institutions["effects"]`;
society entries live in `w.institutions["public_reactions"]` with `bus: True` and their source attached.
"""
from __future__ import annotations

from . import errors, public_mood
from .world import CLASSES, IDENTITIES, OFFICES, World, clamp

# The longest an effect may run. The policy language's schedules run from 1 to 24 months (plan 4.2); one act held
# longer would shape most of a 36-month run, which is what the per-effect bound exists to prevent.
MAX_MONTHS = 24

# Who may schedule an effect. The source travels on every entry so outcomes can be attributed.
SOURCE_KINDS = ("policy", "open_act", "cabinet_open_act")
RELATIONS_ACTORS = ("veleria", "dorsania")
FORCES = ("army", "navy", "police")

SOCIETY_CHANNELS = ("approval", "grievance", "fear", "indep", "repression")
MONEY_CHANNELS = ("income", "hunger")

# channel -> state it reaches, the targets it may name, its unit, its caps, and why the cap is what it is. The cap
# figures are per entry and per month; the per-month cap is summed over every entry on the same channel and target.
#
# A0-recon section 5 measured the largest one-month change each existing instrument makes on each channel in a
# scripted sweep (seeds 1-6 x scripted/passive/hawk/dove, 36 months; reports/A0-caps.json). The ratios below are
# the plan's rule: an open act or policy is never stronger, on any channel, than the strongest existing instrument
# of its kind in one month.
CHANNELS: dict[str, dict] = {
    "approval": {
        "state": "the public reaction folded into each group's approval target by public_mood.react",
        "targets": "society",
        "unit": "monthly modifier (the society step multiplies it by 4 for the opinion target)",
        "cap": .03, "month_cap": .03, "max_months": MAX_MONTHS,
        "why": "public_mood.LIMIT is .03, below every measured event maximum (approval .157, grievance .065, "
               "fear .037, repression .100); a reaction on top of an event is a nudge, not a second event.",
    },
    "grievance": {
        "state": "the public reaction folded into each group's grievance target by public_mood.react",
        "targets": "society",
        "unit": "monthly modifier (the society step multiplies it by 4 for the grievance target)",
        "cap": .03, "month_cap": .03, "max_months": MAX_MONTHS,
        "why": "public_mood.LIMIT is .03, below the measured grievance maximum of .065.",
    },
    "fear": {
        "state": "the public reaction folded into each group's fear target by public_mood.react",
        "targets": "society",
        "unit": "monthly modifier (the society step multiplies it by 4 for the fear target)",
        "cap": .03, "month_cap": .03, "max_months": MAX_MONTHS,
        "why": "public_mood.LIMIT is .03, at the measured fear maximum of .037 but below the repression events "
               "that drive it.",
    },
    "indep": {
        "state": "the public reaction folded into each group's independence target by public_mood.react",
        "targets": "society",
        "unit": "monthly modifier (the society step multiplies it by 4 for the independence target)",
        "cap": .03, "month_cap": .03, "max_months": MAX_MONTHS,
        "why": "public_mood.LIMIT is .03, far above the measured maximum of .0056; the ceiling is the channel's "
               "own bound, not the measurement.",
    },
    "repression": {
        "state": "the public reaction folded into each group's felt repression by public_mood.react",
        "targets": "society",
        "unit": "monthly modifier (the society step multiplies it by 4 for the repression target)",
        "cap": .03, "month_cap": .03, "max_months": MAX_MONTHS,
        "why": "public_mood.LIMIT is .03, far below the measured .100 a lethal crackdown adds in a month.",
    },
    "income": {
        "state": "capped modifier read by society.update in the income target of each group it matches",
        "targets": "society",
        "unit": "index points of real income (1.0 is the starting level)",
        "cap": .02, "month_cap": .02, "max_months": MAX_MONTHS,
        "why": "a transfer's per-head money side (decision 1). UNVERIFIED: the A0 sweep did not capture income "
               "flows, so .02 is provisional until a targeted probe measures welfare and regional_fund.",
    },
    "hunger": {
        "state": "capped modifier added to each group's hunger by society.update before deaths and opinion read it",
        "targets": "society",
        "unit": "share of food need unmet (0 to 1; hunger is set each month by economy.trade_and_food)",
        "cap": .02, "month_cap": .02, "max_months": MAX_MONTHS,
        "why": "a transfer's food side (decision 1). UNVERIFIED: the A0 sweep did not capture hunger flows; .02 is "
               "provisional until a targeted probe measures the food allocation.",
    },
    "damage": {
        "state": "Region.damage",
        "targets": "region",
        "unit": "share of the region's capital stock destroyed (0 to 1)",
        "cap": .02, "month_cap": .02, "max_months": MAX_MONTHS,
        "why": "the Union's combat adds .02 per front-month (military.py:473); the A0 sweep measured .0102 from "
               "scripted play, and .02 is the instrument scale it observed.",
    },
    "logistics": {
        "state": "Region.logistics",
        "targets": "region",
        "unit": "freight throughput relative to normal capacity (the engine holds it at or below 1.1)",
        "cap": .05, "month_cap": .05, "max_months": MAX_MONTHS,
        "why": "the rail blockade cuts .10 and relief restores it; .05 is one instrument's monthly step.",
    },
    "admin_capacity": {
        "state": "Economy.admin_capacity for '*', or the named office's capability in w.institutions['capacity'] "
                 "(standing.update_capacity rebuilds that table at each council session, so an office effect "
                 "lasts until the rebuild)",
        "targets": "admin",
        "unit": "share of the administration working (0 to 1)",
        "cap": .02, "month_cap": .02, "max_months": MAX_MONTHS,
        "why": "operations add .01 a month; the measured .147 is the economy's own pull toward its target, not an "
               "instrument.",
    },
    "confidence": {
        "state": "Economy.confidence (economy.money_and_prices recomputes it each month, so an effect is visible "
                 "until the next fiscal step, which is why the bus applies it after that step)",
        "targets": "any",
        "unit": "lenders' confidence (0 to 1)",
        "cap": .01, "month_cap": .01, "max_months": MAX_MONTHS,
        "why": "the measured maximum was .0167; .01 keeps an effect below the month-to-month drift of the "
               "economy's own recomputation.",
    },
    "corruption": {
        "state": "w.institutions['corruption'][office]",
        "targets": "office",
        "unit": "share of the office's business diverted (0 to 1)",
        "cap": .02, "month_cap": .02, "max_months": MAX_MONTHS,
        "why": "self-dealing and audits move it by .04-.06 a month; an effect is half of one such move.",
    },
    "relations": {
        "state": "the named actor's trust and hostility toward Karamaniya in w.foreign['actors']",
        "targets": "actor",
        "unit": "points of trust (a positive value raises trust and lowers hostility by the same amount)",
        "cap": .03, "month_cap": .03, "max_months": MAX_MONTHS,
        "why": "the measured hostility maximum was .025; .03 is one diplomatic instrument's monthly step.",
    },
    "league_trust": {
        "state": "Dip.league_trust (mirrored to w.foreign['league']['trust_in_karamaniya'])",
        "targets": "league",
        "unit": "the League's trust in Karamaniya (0 to 1)",
        "cap": .05, "month_cap": .05, "max_months": MAX_MONTHS,
        "why": "the measured .481 is a coup and fraud event, not an instrument; .05 is the League's own monthly "
               "adjustment scale (foreign.py's .02-.05 terms).",
    },
    "morale": {
        "state": "Force.morale of the named service",
        "targets": "force",
        "unit": "the force's morale (0 to 1; the engine holds it between .05 and .95)",
        "cap": .02, "month_cap": .02, "max_months": MAX_MONTHS,
        "why": "the measured maxima were .018-.026 a month; .02 is below the police maximum.",
    },
}


def _targets_text(family: str) -> str:
    return {
        "society": "everyone ('*'), a Karamaniya region id, an identity ('ident:vell') or a class "
                   "('class:farmers')",
        "region": "a Karamaniya region id",
        "office": "an office (" + ", ".join(OFFICES) + ")",
        "admin": "everyone ('*') or an office (" + ", ".join(OFFICES) + ")",
        "force": "a force (" + ", ".join(FORCES) + ")",
        "actor": "an actor (" + ", ".join(RELATIONS_ACTORS) + ")",
        "league": "the League ('league' or '*')",
        "any": "everyone ('*')",
    }[family]


def _valid_target(w: World, family: str, target: str) -> bool:
    if family == "society":
        if target == "*":
            return True
        if target.startswith("class:"):
            return target[6:] in CLASSES
        if target.startswith("ident:"):
            return target[6:] in IDENTITIES
        return any(r.id == target and r.nation == "karamaniya" for r in w.regions)
    if family == "region":
        return any(r.id == target and r.nation == "karamaniya" for r in w.regions)
    if family == "office":
        return target in OFFICES
    if family == "admin":
        return target == "*" or target in OFFICES
    if family == "force":
        return target in FORCES
    if family == "actor":
        return target in RELATIONS_ACTORS
    if family == "league":
        return target in ("league", "*")
    if family == "any":
        return target == "*"
    return False


def _problem(code: str, index: int, message: str) -> dict:
    return {"code": code, "index": index, "problem": message}


def _number(value) -> float | None:
    """A finite float from a number or a numeric string; None otherwise. Booleans are not numbers here."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):   # NaN and infinities
        return None
    return number


def _months(value) -> int | None:
    number = _number(value)
    if number is None or number < 1 or number != int(number):
        return None
    return int(number)


def _normalize_source(w: World, source: dict | None) -> tuple[dict, dict | None]:
    source = dict(source or {})
    if source.get("kind") not in SOURCE_KINDS:
        return {}, _problem("EFFECT_UNKNOWN_SOURCE", -1,
                            "An effect must come from a policy, an open act or a neighbour's open act.")
    month = _number(source.get("month", w.month))
    if month is None or month < 0 or month != int(month):
        month = w.month
    return {"kind": source["kind"], "actor": source.get("actor"), "motion": source.get("motion"),
            "month": int(month)}, None


def _stacking(w: World, channel: str, target: str, value: float) -> float:
    """The largest total this effect and the live bus reactions on the same target would make in one month.

    Decay only shrinks a reaction, so the current values added at full strength are an upper bound; that is
    deliberately conservative, because a society reaction cannot be clipped once public_mood has folded it in.
    """
    total = abs(value)
    for entry in w.institutions.get("public_reactions") or []:
        if not entry.get("bus") or entry.get("kind") != channel or entry.get("where") != target:
            continue
        if int(entry.get("months_left", 0)) <= 0:
            continue
        total += abs(float(entry.get("value", 0.0)))
    return round(total, 5)


def validate(w: World, effects: list, source: dict | None) -> tuple[list, list]:
    """Check a list of effects against the registry. Returns (accepted, problems).

    Each problem is a dict with a registered code, the index of the effect in the list, and a sentence saying what
    is wrong (engine-29 style: no codes or engine words in the sentence itself). Accepted effects are normalized:
    numeric value and months, default decay, a reason cut to the public-reaction length.
    """
    accepted, problems = [], []
    if not isinstance(effects, (list, tuple)):
        return [], [_problem("EFFECT_BAD_VALUE", -1, "The effects must be a list.")]
    _, source_problem = _normalize_source(w, source)
    if source_problem:
        problems.append(source_problem)
    monthly: dict[tuple[str, str], float] = {}
    for index, item in enumerate(effects):
        if not isinstance(item, dict):
            problems.append(_problem("EFFECT_BAD_VALUE", index, "An effect must be a named change."))
            continue
        channel = item.get("channel")
        if not isinstance(channel, str) or channel not in CHANNELS:
            problems.append(_problem("EFFECT_UNKNOWN_CHANNEL", index,
                                     f"There is no effect channel called '{channel}'."))
            continue
        spec = CHANNELS[channel]
        target = str(item.get("target") or "")
        if not _valid_target(w, spec["targets"], target):
            problems.append(_problem("EFFECT_UNKNOWN_TARGET", index,
                                     f"The {channel} channel cannot be aimed at '{target}'; it takes "
                                     f"{_targets_text(spec['targets'])}."))
            continue
        value = _number(item.get("value"))
        if value is None or abs(value) < 1e-9:
            problems.append(_problem("EFFECT_BAD_VALUE", index,
                                     "An effect's value must be a finite number other than zero."))
            continue
        months = _months(item.get("months", 1))
        if months is None:
            problems.append(_problem("EFFECT_BAD_MONTHS", index,
                                     "The number of months an effect lasts must be a whole number of at least 1."))
            continue
        if months > spec["max_months"]:
            problems.append(_problem("EFFECT_TOO_MANY_MONTHS", index,
                                     f"An effect on {channel} may last at most {spec['max_months']} months; "
                                     f"this one asks for {months}."))
            continue
        decay = _number(item.get("decay", 1.0))
        if decay is None or decay <= 0 or decay > 1:
            problems.append(_problem("EFFECT_BAD_VALUE", index,
                                     "The decay must be greater than 0 and at most 1."))
            continue
        if abs(value) > spec["cap"] + 1e-9:
            problems.append(_problem("EFFECT_OVER_CAP", index,
                                     f"A single {channel} effect may move its state by at most {spec['cap']:g} "
                                     f"a month; this one asks for {abs(value):g}."))
            continue
        key = (channel, target)
        monthly[key] = round(monthly.get(key, 0.0) + abs(value), 5)
        if monthly[key] > spec["month_cap"] + 1e-9:
            problems.append(_problem("EFFECT_MONTH_CAP", index,
                                     f"Effects on {channel} at '{target}' would sum to {monthly[key]:g} in one "
                                     f"month; the limit is {spec['month_cap']:g}."))
            continue
        if channel in SOCIETY_CHANNELS:
            total = _stacking(w, channel, target, value)
            if total > spec["month_cap"] + 1e-9:
                problems.append(_problem("EFFECT_MONTH_CAP", index,
                                         f"Effects on {channel} at '{target}' would sum to {total:g} in a month "
                                         f"the existing reactions still run; the limit is {spec['month_cap']:g}."))
                continue
        accepted.append({"channel": channel, "target": target, "value": round(value, 5),
                         "months": months, "decay": round(decay, 5),
                         "reason": str(item.get("reason", ""))[:160]})
    return accepted, problems


def state(w: World) -> list:
    """The bus's live non-society entries (an old checkpoint has none and starts empty)."""
    return w.institutions.setdefault("effects", [])


def schedule(w: World, accepted: list, source: dict | None) -> list:
    """Store accepted effects: society kinds in public_mood, the rest in w.institutions['effects'].

    The caller validates first (`validate`); an unknown source stores nothing rather than a half-attributed entry.
    Returns the stored entries, each carrying its source.
    """
    src, source_problem = _normalize_source(w, source)
    if source_problem:
        return []
    stored = []
    for item in accepted:
        if item["channel"] in SOCIETY_CHANNELS:
            entry = public_mood.react(w, item["channel"], item["target"], item["value"],
                                      item["months"], item["reason"], item.get("decay", 1.0))
            if entry is None:
                continue
            entry.update({"bus": True, "source": dict(src), "target": item["target"]})
            stored.append(entry)
        else:
            entry = {"channel": item["channel"], "target": item["target"], "value": item["value"],
                     "months_left": item["months"], "decay": item.get("decay", 1.0),
                     "reason": item.get("reason", ""), "month": w.month, "source": dict(src)}
            state(w).append(entry)
            stored.append(entry)
    return stored


def _apply(w: World, channel: str, target: str, amount: float) -> None:
    """Apply one non-society effect to its state. The registry's targets were checked by `validate`."""
    if channel == "damage":
        region = w.region(target)
        region.damage = round(clamp(region.damage + amount), 4)
    elif channel == "logistics":
        region = w.region(target)
        region.logistics = round(clamp(region.logistics + amount, 0.0, 1.1), 4)
    elif channel == "admin_capacity":
        if target == "*":
            w.econ.admin_capacity = round(clamp(w.econ.admin_capacity + amount, 0.2, 1.0), 4)
        else:
            capacity = w.institutions.setdefault("capacity", {})
            capacity[target] = round(clamp(float(capacity.get(target, 1.0)) + amount), 4)
    elif channel == "confidence":
        w.econ.confidence = round(clamp(w.econ.confidence + amount, 0.05, 1.0), 4)
    elif channel == "corruption":
        corruption = w.institutions.setdefault("corruption", {})
        corruption[target] = round(clamp(float(corruption.get(target, 0.0)) + amount), 3)
    elif channel == "relations":
        if not w.foreign or "actors" not in w.foreign:
            from .foreign import initial_state
            w.foreign = initial_state(w.seed)
        relation = (w.foreign.get("actors", {}).get(target, {}).get("relations", {})
                    .get("karamaniya"))
        if relation is not None:
            relation["trust"] = round(clamp(float(relation.get("trust", 0.0)) + amount), 3)
            relation["hostility"] = round(clamp(float(relation.get("hostility", 0.0)) - amount), 3)
    elif channel == "league_trust":
        w.adjust_league_trust(amount)
    elif channel == "morale":
        force = {"army": w.mil.army, "navy": w.mil.navy, "police": w.mil.police}[target]
        force.morale = round(clamp(force.morale + amount, 0.05, 0.95), 4)


def step(w: World) -> None:
    """Apply and age this month's effects once. Called from engine.step (see the module docstring for where)."""
    entries = w.institutions.get("effects") or []
    pending = w.institutions.get("effects_society_applied") or []
    if w.institutions.get("effects_step_month") == w.month:
        return
    if not entries and not pending:
        # A bus that has been used before clears last month's table and record even when nothing applies now:
        # otherwise a stale income modifier or a stale month record would be read as this month's.
        if "effects_modifiers" in w.institutions:
            w.institutions["effects_modifiers"] = {}
        if "effects_applied" in w.institutions:
            w.institutions["effects_applied"] = []
        w.institutions.pop("effects_society_applied", None)
        if "effects_step_month" in w.institutions:
            w.institutions["effects_step_month"] = w.month
        return
    w.institutions["effects_step_month"] = w.month

    applied = [dict(record) for record in pending]
    w.institutions.pop("effects_society_applied", None)
    used: dict[tuple[str, str], float] = {}
    for record in applied:
        key = (record.get("channel"), record.get("target"))
        used[key] = used.get(key, 0.0) + abs(float(record.get("value", 0.0)))

    modifiers = {"income": {}, "hunger": {}}
    live = []
    for entry in entries:
        channel, target = entry.get("channel"), entry.get("target")
        months_left = int(entry.get("months_left", 0))
        if months_left <= 0:
            continue
        spec = CHANNELS.get(channel)
        if spec is None:
            # A checkpoint from a registry this build does not know: fail closed, do not guess a channel, but
            # leave the fact in the run's error log rather than dropping it silently.
            errors.record(w, "EFFECT_UNKNOWN_CHANNEL",
                          f"A scheduled effect on the unknown channel '{channel}' was dropped.")
            continue
        value = float(entry.get("value", 0.0))
        key = (channel, target)
        remaining = max(0.0, spec["month_cap"] - used.get(key, 0.0))
        take = min(abs(value), remaining)
        if take > 1e-9:
            amount = round(take if value > 0 else -take, 5)
            if channel in MONEY_CHANNELS:
                table = modifiers[channel]
                table[target] = round(table.get(target, 0.0) + amount, 5)
            else:
                _apply(w, channel, target, amount)
            used[key] = round(used.get(key, 0.0) + abs(amount), 5)
            applied.append({"channel": channel, "target": target, "value": amount,
                            "source": dict(entry.get("source") or {})})
        entry["months_left"] = months_left - 1
        entry["value"] = round(value * float(entry.get("decay", 1.0)), 5)
        if entry["months_left"] > 0 and abs(entry["value"]) >= 1e-6:
            live.append(entry)

    w.institutions["effects"] = live
    w.institutions["effects_modifiers"] = modifiers
    w.institutions["effects_applied"] = applied


def modifiers(w: World, kind: str) -> dict:
    """This month's live income or hunger modifiers by target, for society.update to read."""
    return dict((w.institutions.get("effects_modifiers") or {}).get(kind) or {})


def applied(w: World) -> list:
    """This month's applied effects, by channel, target and source, for the history row."""
    return [{**record, "source": dict(record.get("source") or {})}
            for record in (w.institutions.get("effects_applied") or [])]
