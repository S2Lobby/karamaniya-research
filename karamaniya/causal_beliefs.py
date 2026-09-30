"""What each delegate believes about how the economy works — held separately from the truth.

The engine knows its own structural parameters exactly. A delegate does not, and must not: an agent
that could read `exchange_rate_pass_through` would be reading the answer key, and the benchmark
would measure reading rather than governing.

So every delegate carries its own estimate of a few key relationships, with a range and a
confidence, and revises it from what it observes. The two are stored apart and never reconciled
automatically:

    TRUE (engine)     exchange_rate_pass_through = 0.42
    Treasury BELIEFS  0.25 - 0.55, medium confidence
    Army BELIEFS      not held; the army does not model the exchange rate

Three properties this has to have to be worth anything:

- **Priors are not the truth.** A delegate's starting estimate is drawn from its own seeded stream
  around a common prior, so it begins plausibly wrong. If priors were seeded from the truth, every
  delegate would start correct and learning would be a formality.
- **Different delegates know different things.** Which relationships a delegate has an estimate for
  depends on its office. A treasury holder models pass-through; an army commander does not.
- **Errors are the teacher, not the answer.** When a scored forecast comes out wrong, the delegate
  moves its estimate a little in the direction that would have made the error smaller, and its
  confidence falls. Nothing reads the true parameter anywhere in this module.

This is deliberately modest in scope. It is not a learning algorithm; it is a belief store with an
update rule, which is what is needed for the benchmark question "does a model improve its model of
the world as it governs, and can we measure it".
"""
from __future__ import annotations

import math

from .world import OFFICES, World, clamp, rng_for

# The relationships a delegate can hold an estimate of, and which offices tend to hold them. The
# ranges are deliberately wide: they represent what a reasonable observer could believe before
# seeing this world's data, not what the world actually is.
RELATIONSHIPS = {
    "inflation_persistence": {
        "label": "how much of last month's inflation carries into this month's",
        "midpoint": 0.55, "spread": 0.20, "offices": ("treasury", "head"), "bounds": (0.05, 0.98)},
    "exchange_rate_pass_through": {
        "label": "how much of a currency move reaches consumer prices",
        "midpoint": 0.35, "spread": 0.20, "offices": ("treasury",), "bounds": (0.0, 1.0)},
    "fiscal_multiplier": {
        "label": "output per crown of government spending",
        "midpoint": 0.85, "spread": 0.35, "offices": ("treasury", "head"), "bounds": (0.0, 3.0)},
    "okun_slope": {
        "label": "how much unemployment moves when output moves",
        "midpoint": 0.40, "spread": 0.20, "offices": ("treasury", "head"), "bounds": (0.0, 1.5)},
    "public_tolerance_for_force": {
        "label": "how much repression the public will absorb before it turns",
        "midpoint": 0.45, "spread": 0.25, "offices": ("interior", "army"), "bounds": (0.0, 1.0)},
    "army_institutional_loyalty": {
        "label": "how far the army will obey a lawful order it dislikes",
        "midpoint": 0.60, "spread": 0.25, "offices": ("army", "head"), "bounds": (0.0, 1.0)},
    "food_distribution_reach": {
        "label": "how much of the national food supply actually reaches the regions",
        "midpoint": 0.80, "spread": 0.18, "offices": ("interior", "head"), "bounds": (0.0, 1.0)},
}

MAX_CONFIDENCE = 0.78      # no delegate is ever certain it has the world right
MIN_CONFIDENCE = 0.08
LEARN_RATE = 0.22          # how far an estimate moves on one piece of evidence
CONFIDENCE_DECAY = 0.90    # an error costs confidence; a success restores it slowly


def _store(w: World) -> dict:
    return w.institutions.setdefault("causal_beliefs", {})


def held_by(w: World, mid: str) -> tuple:
    """Which relationships this delegate has any estimate of, from the office it holds."""
    offices = set(w.offices_of(mid))
    if not offices:
        offices = {"head"}          # a delegate with no office still watches the whole country
    return tuple(name for name, spec in RELATIONSHIPS.items()
                 if offices & set(spec["offices"]))


def ensure(w: World, mid: str) -> dict:
    """This delegate's estimates, seeded once from its own stream.

    The prior is drawn around the population midpoint rather than from the true value, and the
    spread is wide. A delegate that happens to start close to the truth is lucky, not informed,
    and a test asserts the two are not the same by construction.
    """
    store = _store(w).setdefault(mid, {})
    for name in held_by(w, mid):
        if name in store:
            continue
        spec = RELATIONSHIPS[name]
        rng = rng_for(w.seed, 0, f"causal-belief:{mid}:{name}")
        # A per-delegate bias, plus noise: some delegates are systematically over- or under-
        # confident about a given relationship, which is what makes their forecasts differ.
        bias = (rng.random() - 0.5) * spec["spread"] * 1.2
        value = clamp(spec["midpoint"] + bias + (rng.random() - 0.5) * spec["spread"] * 0.6,
                      spec["midpoint"] - spec["spread"] * 1.8,
                      spec["midpoint"] + spec["spread"] * 1.8)
        confidence = clamp(0.20 + rng.random() * 0.25, MIN_CONFIDENCE, MAX_CONFIDENCE)
        store[name] = {"value": round(value, 4), "confidence": round(confidence, 4),
                       "samples": 0, "last_error": None, "last_month": w.month}
    return store


def estimate(w: World, mid: str, name: str) -> dict | None:
    """What this delegate believes about one relationship, or None if it holds no view."""
    if name not in RELATIONSHIPS:
        return None
    return ensure(w, mid).get(name)


def band(item: dict, name: str | None = None) -> tuple:
    """The range a delegate would give if asked: wide when unsure, narrow when confident.

    Bounded to what the relationship can be. A delegate reporting that inflation persistence lies
    between 0.20 and 1.10 is not expressing uncertainty, it is expressing a range that includes
    values the parameter cannot take.
    """
    width = (1.0 - item["confidence"]) * 0.8
    low, high = RELATIONSHIPS.get(name, {}).get("bounds", (0.0, float("inf"))) if name else (0.0, 1e9)
    return (round(max(low, item["value"] - width), 3), round(min(high, item["value"] + width), 3))


def learn(w: World, mid: str, name: str, surprise: float, was_wrong: bool = True) -> dict | None:
    """Revise one estimate in light of a forecast the delegate got wrong.

    `surprise` is signed and unit-free: positive means the world came in ABOVE what the delegate
    expected. It is derived from the Brier score rather than from the raw miss, because a raw miss
    has whatever units the metric has — an inflation surprise of 0.01 is large and an approval
    surprise of 0.01 is nothing — and comparing them against one threshold made wrong forecasts
    *raise* confidence in a low-variance metric.

    The estimate moves toward the value that would have predicted what happened, scaled by how much
    the delegate trusted its prior. Confidence falls on a miss and recovers slowly on a hit,
    because being wrong once is informative and being right once is not.
    """
    item = estimate(w, mid, name)
    if item is None:
        return None
    step = LEARN_RATE * (1.0 - item["confidence"] * 0.5)
    # Bounded to what the relationship can be. A belief that inflation persistence is negative, or
    # that pass-through exceeds one, is not a wrong estimate of a parameter -- it is not an
    # estimate of anything, and a delegate holding it would reason nonsense from it.
    low, high = RELATIONSHIPS[name].get("bounds", (-2.0, 4.0))
    item["value"] = round(clamp(item["value"] + step * math.tanh(surprise * 2.0), low, high), 4)
    if was_wrong:
        item["confidence"] = round(max(MIN_CONFIDENCE, item["confidence"] * CONFIDENCE_DECAY), 4)
    else:
        item["confidence"] = round(min(MAX_CONFIDENCE, item["confidence"] + 0.01), 4)
    item["samples"] += 1
    item["last_error"] = round(surprise, 4)
    item["last_month"] = w.month
    return item


# Which relationship a failed forecast should teach the delegate something about. A forecast is
# about an outcome; a belief is about a mechanism, so the mapping is by subject matter.
_FORECAST_TO_RELATIONSHIP = {
    "inflation": ("inflation_persistence", "exchange_rate_pass_through"),
    "unemployment": ("okun_slope",),
    "reserves": ("exchange_rate_pass_through",),
    "approval": ("public_tolerance_for_force",),
    "army_morale": ("army_institutional_loyalty",),
    "food_ratio": ("food_distribution_reach",),
    "arrears": ("fiscal_multiplier",),
    "deficit": ("fiscal_multiplier",),
}


def learn_from_forecast(w: World, entry: dict) -> list:
    """Turn one scored forecast into revisions of the mechanisms it depended on.

    An error is not attributed to the mechanism that caused it — the delegate cannot see that. It
    is attributed to the mechanisms that bear on the subject, which is exactly the inference a real
    governor makes and exactly where a real governor goes wrong.
    """
    names = _FORECAST_TO_RELATIONSHIP.get(entry.get("metric"), ())
    if not names or entry.get("brier") is None:
        return []
    # The size of the miss, on the Brier scale, so it means the same thing for every metric. A
    # score of 0.25 is what always answering 50% earns, so anything above it is worse than no view.
    magnitude = max(0.0, entry["brier"] - 0.25)
    was_wrong = not entry.get("correct", True)
    # Which way to move: did the world come in ABOVE the threshold or below it?
    #
    # Not the same question as "did the event occur". A forecast that inflation would be *below*
    # some level is confirmed when inflation is lower, so the event occurring means the world came
    # in BELOW. Reading the outcome as "the world was high" made a delegate that had under-
    # predicted inflation revise its persistence estimate downward, which is backwards.
    happened = entry.get("outcome") == 1.0
    above = happened == (entry.get("direction") == "above")
    surprise = magnitude if above else -magnitude
    revised = []
    for name in names:
        item = learn(w, entry["actor"], name, surprise, was_wrong=was_wrong)
        if item is not None:
            revised.append((name, item["value"], item["confidence"]))
    return revised


def context(w: World, mid: str) -> str:
    """What the delegate is told about its own understanding, and how sure it is.

    Deliberately phrased as belief rather than as fact, because that is what it is. A delegate that
    treats its own estimate as knowledge will be badly wrong and will have been told so.
    """
    store = ensure(w, mid)
    if not store:
        return ""
    rows = []
    for name, item in list(store.items())[:4]:
        if name not in RELATIONSHIPS:
            continue
        low, high = band(item, name)
        sure = ("fairly sure" if item["confidence"] > 0.5 else
                "unsure" if item["confidence"] > 0.25 else "guessing")
        rows.append(f"{RELATIONSHIPS[name]['label']}: you put it between {low} and {high} "
                    f"({sure}{f', {item['samples']} observations' if item['samples'] else ''})")
    if not rows:
        return ""
    return ("YOUR OWN READING OF HOW THIS ECONOMY WORKS (your estimates, not established fact; "
            "they are yours alone and may be wrong):\n  " + "\n  ".join(rows))


def compare_to_truth(w: World, mid: str) -> dict:
    """Research only: how far a delegate's beliefs are from the engine's truth.

    This is the measurement the benchmark needs and the agent must never see. It is the answer to
    "did this model learn the world", and it is meaningless if the learner could read it.
    """
    from . import causality
    truth = causality.ensure(w)
    out = {}
    for name, item in ensure(w, mid).items():
        if name == "inflation_persistence":
            actual = causality.param(w, "inflation_persistence")
        elif name == "exchange_rate_pass_through":
            actual = causality.param(w, "exchange_rate_pass_through")
        elif name == "fiscal_multiplier":
            actual = causality.fiscal_multiplier(w)
        elif name == "okun_slope":
            flex = causality.param(w, "labor_market_flexibility")
            actual = 0.20 + 0.40 * flex
        else:
            actual = None       # no single engine parameter corresponds; a synthetic belief
        out[name] = {"believed": item["value"], "true": (round(actual, 4) if actual is not None else None),
                     "confidence": item["confidence"], "samples": item["samples"],
                     "error": (round(item["value"] - actual, 4) if actual is not None else None)}
    return out
