"""Structured forecasts, and an honest score of them afterwards.

A delegate that says "inflation will be under 15% by winter" has made a claim that can be checked.
This module stores such claims in a form that can be, so the simulation can measure whether a
model's beliefs about how the economy works were borne out — which is a different and more
interesting question than whether it voted the way the engine's author would have.

Two things are scored, and they are not the same:

    CALIBRATION   when a delegate says 70% confident, does that happen about 70% of the time?
    ACCURACY      was the direction right at all?

A forecaster can be well calibrated and useless (always 50%), or accurate and badly calibrated
(right for the wrong reasons, overconfident). Both are reported, because collapsing them into one
number is how forecasting gets mistaken for wisdom.

**On the Brier score scale.** Two conventions circulate and differ by a factor of two. This module
uses the binomial convention, BS = mean((f - o)^2), which ranges 0 to 1 and scores 0.25 at the
no-information forecast of 0.5. The Good Judgment Project's widely quoted figures (0.25 for
superforecasters, 0.37 for others) are on the 0-2 scale and are frequently misreported as if they
were this one; they correspond to 0.125 and 0.185 here. The scale is stated on every score.
"""
from __future__ import annotations

from .world import World, clamp

# Metrics a delegate may forecast. These are read from the same canonical values that execution
# conditions use, so a forecast and a condition cannot disagree about what a number was.
FORECAST_METRICS = ("inflation", "food_ratio", "unemployment", "reserves", "arrears",
                    "approval", "army_morale", "deficit")
HORIZONS = (3, 6, 12)
DIRECTIONS = ("above", "below")
MAX_OPEN = 4


def record(w: World, mid: str, metric: str, horizon: int, direction: str, threshold: float,
           confidence: float, rationale: str = "") -> dict | None:
    """Store one forecast. Returns None if it is malformed, rather than raising."""
    if metric not in FORECAST_METRICS or direction not in DIRECTIONS:
        return None
    try:
        horizon = int(horizon)
        threshold = float(threshold)
        confidence = float(confidence)
    except (TypeError, ValueError):
        return None
    if horizon not in HORIZONS:
        return None
    # Read the numbers the way execution conditions read them: a threshold written in percent, or a
    # sum written in millions, means what the same figure means in a condition. A confidence above
    # 1 is a percentage; engine 5 clamped it, so "75" was recorded as certainty and the delegate
    # was later told it had been overconfident.
    from .motion_actions import canonical_metric_value
    threshold = canonical_metric_value(metric, threshold)
    if 1 < confidence <= 100:
        confidence /= 100.0
    entry = {"id": f"F{w.month}-{len(_ledger(w)) + 1}", "actor": mid, "month_created": w.month,
             "metric": metric, "direction": direction, "threshold": threshold,
             "confidence": round(clamp(confidence), 3), "rationale": str(rationale)[:300],
             "horizon": horizon, "due_month": w.month + horizon,
             "resolved_month": None, "actual": None, "outcome": None, "error": None,
             "correct": None, "brier": None}
    _ledger(w).append(entry)
    return entry


def _ledger(w: World) -> list:
    return w.institutions.setdefault("forecasts", [])


def ledger(w: World) -> list:
    return list(_ledger(w))


def open_for(w: World, mid: str) -> list:
    return [f for f in _ledger(w) if f["actor"] == mid and f["resolved_month"] is None]


def _actual(w: World, metric: str) -> float | None:
    """The realised value of a forecast metric, read from canonical state."""
    from .motion_actions import condition_values
    values = condition_values(w)
    value = values.get(metric)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_due(w: World) -> list:
    """Score every forecast whose horizon has elapsed. Called once a month, after the world moves.

    A forecast due this month is scored against the state at the end of the month, which is the
    state its author could not see when they made it.
    """
    resolved = []
    for entry in _ledger(w):
        if entry["resolved_month"] is not None or entry["due_month"] > w.month:
            continue
        value = _actual(w, entry["metric"])
        if value is None:
            continue
        happened = 1.0 if ((value > entry["threshold"]) if entry["direction"] == "above"
                           else (value < entry["threshold"])) else 0.0
        entry["resolved_month"] = w.month
        entry["actual"] = round(value, 4)
        entry["outcome"] = happened
        # Directional correctness is whether the SIDE the forecaster leaned to was the side that
        # happened. A forecast of "this will probably not occur", stated at 20%, is correct when it
        # does not occur — the event's non-occurrence is the forecaster being right, not wrong.
        entry["correct"] = bool(happened) == (entry["confidence"] >= 0.5)
        entry["error"] = round(entry["confidence"] - happened, 4)
        # Brier, binomial convention: (forecast - outcome)^2, where the forecast is the stated
        # confidence that the event would occur. 0 is a perfect certain call, 1 a certain miss,
        # and 0.25 is what always answering "50%" scores.
        entry["brier"] = round((entry["confidence"] - happened) ** 2, 4)
        # A wrong forecast is the delegate's only honest teacher about how the world works. The
        # revision is attributed to the mechanisms bearing on the subject, not to the true cause,
        # which the delegate cannot see.
        from . import causal_beliefs
        entry["revised"] = causal_beliefs.learn_from_forecast(w, entry)
        resolved.append(entry)
    return resolved


# ---- scoring ---------------------------------------------------------------------------------
def murphy(w: World, entries: list) -> dict:
    """Decompose the Brier score: BS = REL - RES + UNC.

    Reliability is calibration (lower is better); resolution is how much the forecasts varied
    from the base rate (higher is better); uncertainty is a property of the outcomes, not the
    forecaster, and is included so the decomposition adds up.
    """
    scored = [e for e in entries if e.get("brier") is not None]
    if not scored:
        return {"n": 0}
    n = len(scored)
    base = sum(e["outcome"] for e in scored) / n
    bins: dict[int, list] = {}
    for e in scored:
        bins.setdefault(min(9, int(e["confidence"] * 10)), []).append(e)
    reliability = 0.0
    resolution = 0.0
    for bucket in bins.values():
        share = len(bucket) / n
        mean_forecast = sum(e["confidence"] for e in bucket) / len(bucket)
        mean_outcome = sum(e["outcome"] for e in bucket) / len(bucket)
        reliability += share * (mean_forecast - mean_outcome) ** 2
        resolution += share * (mean_outcome - base) ** 2
    uncertainty = base * (1 - base)
    return {"n": n, "reliability": round(reliability, 4), "resolution": round(resolution, 4),
            "uncertainty": round(uncertainty, 4),
            "brier": round(sum(e["brier"] for e in scored) / n, 4),
            "base_rate": round(base, 4),
            "decomposition_sums": round(reliability - resolution + uncertainty, 4)}


def directional_accuracy(w: World, entries: list) -> dict:
    """Hit rate, beside the baseline a forecaster has to beat to be worth listening to.

    The no-skill baseline is NOT 50%. It is the frequency of simply always predicting whichever
    direction turned out to be more common — the Pesaran-Timmermann point. A hit rate below that
    baseline is worse than saying the same thing every month.
    """
    scored = [e for e in entries if e.get("correct") is not None]
    if not scored:
        return {"n": 0}
    hits = sum(1 for e in scored if e["correct"])
    happened = sum(e["outcome"] for e in scored) / len(scored)
    # The no-skill rule answers "the event will occur" every time when events are common, and
    # "it will not" every time when they are rare.
    naive = max(happened, 1 - happened)
    return {"n": len(scored), "hit_rate": round(hits / len(scored), 4),
            "no_skill_baseline": round(naive, 4),
            "beats_no_skill": round(hits / len(scored), 4) > naive,
            "event_rate": round(happened, 4)}


def calibration_curve(w: World, entries: list, buckets: int = 5) -> list:
    """For each stated-confidence bucket, how often the event actually happened."""
    scored = [e for e in entries if e.get("brier") is not None]
    out = []
    for i in range(buckets):
        lo, hi = i / buckets, (i + 1) / buckets
        bucket = [e for e in scored if lo <= e["confidence"] < hi or (i == buckets - 1 and e["confidence"] == 1.0)]
        if not bucket:
            continue
        out.append({"stated": round((lo + hi) / 2, 2), "n": len(bucket),
                    "observed": round(sum(e["outcome"] for e in bucket) / len(bucket), 3)})
    return out


def score(w: World, mid: str | None = None) -> dict:
    """Every scored metric for one delegate, or for the whole council."""
    entries = [f for f in _ledger(w) if mid is None or f["actor"] == mid]
    result = {"actor": mid, "recorded": len(entries),
              "open": sum(1 for f in entries if f["resolved_month"] is None),
              "scored": sum(1 for f in entries if f["brier"] is not None),
              "brier_scale": "binomial, 0-1 (not the 0-2 Good Judgment scale)"}
    result.update(murphy(w, entries))
    result["directional"] = directional_accuracy(w, entries)
    result["calibration_curve"] = calibration_curve(w, entries)
    return result


def ledger_score(entries: list, mid: str | None = None) -> dict:
    """score() from a saved ledger rather than a live world, for the scorecard."""
    own = [f for f in entries if mid is None or f.get("actor") == mid]
    result = {"actor": mid, "recorded": len(own), "open": sum(1 for f in own if f.get("resolved_month") is None),
              "scored": sum(1 for f in own if f.get("brier") is not None),
              "brier_scale": "binomial, 0-1 (not the 0-2 Good Judgment scale)"}
    result.update(murphy(None, own))
    result["directional"] = directional_accuracy(None, own)
    return result


def summary(w: World) -> dict:
    """Council-wide forecast performance, for the report."""
    return {"per_actor": {m.id: score(w, m.id) for m in w.members},
            "council": score(w, None), "ledger_size": len(_ledger(w))}


def _confidence_side(entries: list) -> str:
    """'overconfident' or 'underconfident': whether the side a forecaster leaned to came true less or more
    often than it said. Reliability alone measures the mismatch, not its direction."""
    scored = [e for e in entries if e.get("correct") is not None]
    if not scored:
        return "overconfident"
    stated = sum(max(e["confidence"], 1 - e["confidence"]) for e in scored) / len(scored)
    hits = sum(1 for e in scored if e["correct"]) / len(scored)
    return "overconfident" if hits < stated else "underconfident"


def context_for(w: World, mid: str) -> str:
    """What a delegate is told about its own forecasting record, and nothing about anyone else's.

    Its own calibration is fair to show — a forecaster who is told it is overconfident can correct.
    Another delegate's record is not, because that would leak private reasoning.
    """
    own = score(w, mid)
    lines = []
    if own.get("scored"):
        d = own["directional"]
        line = (f"YOUR FORECAST RECORD: {own['scored']} scored, {own['open']} still open. "
                f"Brier {own['brier']:.3f} on the 0-1 scale (0.25 is what always saying 50% scores). "
                f"Direction right {d['hit_rate']:.0%} of the time against a {d['no_skill_baseline']:.0%} "
                f"do-nothing baseline.")
        # Engine 12 called any mismatch overconfidence, an underconfident forecaster included.
        if own["reliability"] > 0.05:
            side = _confidence_side([f for f in _ledger(w) if f["actor"] == mid])
            line += f" Your stated confidence has not matched outcomes well: you have been {side}."
        elif own["reliability"] < 0.02 and own.get("n", 0) >= 4:
            line += " Your stated confidence has matched outcomes closely."
        lines.append(line)
    panel = panel_score(panel_ledger(w), mid)
    if panel.get("scored"):
        lines.append(f"YOUR MONTHLY PANEL: {panel['scored']} answers scored, Brier {panel['brier']:.3f} "
                     "(always answering 50% scores 0.250).")
    return "\n".join(lines)


# ---- the monthly panel (engine 13) -----------------------------------------------------------
# The forecasts above are each delegate's own choice of question, so two delegates' scores answer
# different questions and cannot be compared. The panel asks every delegate the same questions every
# month, as probabilities, and scores every answer the same way. Each question names its month and
# the figure it starts from, which the delegate is already shown (reported inflation, not the true
# figure the statistics office may be hiding); the answers change nothing in the world.
PANEL_HORIZON = 3
PANEL_KEYS = ("inflation_up", "approval_up", "war", "own_seat")


def _reported_inflation(w: World) -> float:
    from .society import inflation_yoy
    return inflation_yoy(w) * (1 - w.econ.stats_gap)


def _approval(w: World) -> float:
    return w.avg("approval") if w.k_pops() else 0.0


def _seat_question(w: World, mid: str) -> bool:
    c = w.const
    return bool(getattr(c, "personal_mandates", False)) and not c.elected and c.election_month >= w.month \
        and w.member(mid).status == "active"


def panel_questions(w: World, mid: str) -> dict:
    """This month's panel for one delegate: key -> (question, starting figure). The same for every
    delegate except own_seat, asked only while the delegate stands for its own seat at an election
    still to come."""
    due = w.month + PANEL_HORIZON - 1          # the panel asks about the end of the third month from now
    out = {"inflation_up": (f"reported annual inflation will be higher at the end of Month {due + 1} than its "
                            f"{_reported_inflation(w):.1%} now", round(_reported_inflation(w), 5)),
           "approval_up": (f"the government's approval will be higher at the end of Month {due + 1} than its "
                           f"{_approval(w):.0%} now", round(_approval(w), 5)),
           "war": (f"Karamaniya will be at war at the end of Month {due + 1}", None)}
    if _seat_question(w, mid):
        out["own_seat"] = (f"you will keep your own seat at the Assembly election (Month "
                           f"{w.const.election_month + 1})", None)
    return out


def panel_probability(raw) -> float | None:
    """A probability from 0 to 1; a figure from 1 to 100 is a percentage. Anything else is no answer."""
    if isinstance(raw, bool):
        return None
    try:
        p = float(raw)
    except (TypeError, ValueError):
        return None
    if p != p:              # NaN
        return None
    if 1 < p <= 100:
        p /= 100.0
    return round(p, 4) if 0 <= p <= 1 else None


def panel_ledger(w: World) -> list:
    """The panel's answers so far (read only: a run without the panel keeps no ledger)."""
    return list(w.institutions.get("forecast_panel") or [])


def panel_record(w: World, mid: str, answers: dict) -> list:
    """Store one delegate's answers to this month's panel. Unanswered questions are kept as such."""
    questions = panel_questions(w, mid)
    added = []
    for key, (_, start) in questions.items():
        p = panel_probability((answers or {}).get(key))
        entry = {"id": f"P{w.month}-{mid}-{key}", "actor": mid, "key": key, "month_created": w.month,
                 "due_month": None if key == "own_seat" else w.month + PANEL_HORIZON - 1,
                 "start": start, "p": p, "resolved_month": None, "outcome": None, "brier": None}
        w.institutions.setdefault("forecast_panel", []).append(entry)
        added.append(entry)
    return added


def _seat_results(w: World) -> dict:
    """member -> kept, from the latest election that decided members' own seats."""
    for election in reversed(w.const.elections or []):
        if election.get("seats"):
            return {mid: bool(s.get("kept")) for mid, s in election["seats"].items()}
    return {}


def resolve_panel(w: World) -> list:
    """Score the panel answers that fall due at the end of this month (engine.step, after the month)."""
    resolved, seats = [], None
    for entry in w.institutions.get("forecast_panel") or []:
        if entry["resolved_month"] is not None:
            continue
        key = entry["key"]
        if key == "own_seat":
            if seats is None:
                seats = _seat_results(w)
            member = w.member(entry["actor"])
            if entry["actor"] in seats:
                outcome = 1.0 if seats[entry["actor"]] else 0.0
            elif member.status != "active" and member.removed_month >= 0:
                outcome = 0.0      # gone before the election: there is no seat to keep
            else:
                continue
        else:
            if entry["due_month"] is None or entry["due_month"] > w.month:
                continue
            if key == "inflation_up":
                outcome = 1.0 if _reported_inflation(w) > entry["start"] else 0.0
            elif key == "approval_up":
                outcome = 1.0 if _approval(w) > entry["start"] else 0.0
            else:
                outcome = 1.0 if w.dip.war else 0.0
        entry["resolved_month"] = w.month
        entry["outcome"] = outcome
        if entry["p"] is not None:
            entry["brier"] = round((entry["p"] - outcome) ** 2, 4)
        resolved.append(entry)
    return resolved


def panel_score(entries: list, mid: str | None = None) -> dict:
    """One delegate's panel (or the council's): Brier overall and by question, beside two references.

    "always 50%" scores 0.25 on every question; "base rate" is what answering each question with how
    often it came true in this run would have scored, which no delegate could know in advance."""
    own = [e for e in entries if mid is None or e["actor"] == mid]
    scored = [e for e in own if e.get("brier") is not None]
    out = {"actor": mid, "asked": len(own), "answered": sum(1 for e in own if e.get("p") is not None),
           "scored": len(scored), "open": sum(1 for e in own if e.get("resolved_month") is None)}
    if not scored:
        return out
    by_key = {}
    for key in PANEL_KEYS:
        rows = [e for e in scored if e["key"] == key]
        if not rows:
            continue
        rate = sum(e["outcome"] for e in rows) / len(rows)
        by_key[key] = {"n": len(rows), "brier": round(sum(e["brier"] for e in rows) / len(rows), 4),
                       "base_rate": round(rate, 4), "base_rate_brier": round(rate * (1 - rate), 4),
                       "mean_p": round(sum(e["p"] for e in rows) / len(rows), 4)}
    brier = sum(e["brier"] for e in scored) / len(scored)
    reference = sum(v["base_rate_brier"] * v["n"] for v in by_key.values()) / len(scored)
    out.update(brier=round(brier, 4), by_question=by_key, base_rate_brier=round(reference, 4),
               skill_vs_half=round(1 - brier / .25, 4),
               scale="binomial Brier, 0-1; 0.25 is always answering 50%")
    return out
