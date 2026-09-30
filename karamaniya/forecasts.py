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


def summary(w: World) -> dict:
    """Council-wide forecast performance, for the report."""
    return {"per_actor": {m.id: score(w, m.id) for m in w.members},
            "council": score(w, None), "ledger_size": len(_ledger(w))}


def context_for(w: World, mid: str) -> str:
    """What a delegate is told about its own forecasting record, and nothing about anyone else's.

    Its own calibration is fair to show — a forecaster who is told it is overconfident can correct.
    Another delegate's record is not, because that would leak private reasoning.
    """
    own = score(w, mid)
    if not own.get("scored"):
        return ""
    d = own["directional"]
    line = (f"YOUR FORECAST RECORD: {own['scored']} scored, {own['open']} still open. "
            f"Brier {own['brier']:.3f} on the 0-1 scale (0.25 is what always saying 50% scores). "
            f"Direction right {d['hit_rate']:.0%} of the time against a {d['no_skill_baseline']:.0%} "
            f"do-nothing baseline.")
    if own["reliability"] > 0.05:
        line += " Your stated confidence has not matched outcomes well: you have been overconfident."
    elif own["reliability"] < 0.02 and own.get("n", 0) >= 4:
        line += " Your stated confidence has matched outcomes closely."
    return line
