"""The engine watch (engine 17): what moved the crown's prices and national approval each month, and a flag when
the engine looks wrong or one mechanism dominates.

This is for the researcher reading a run. No delegate sees any of it, and nothing here goes into a prompt.

In run 20261010-070501-seed1 prices across the crown rose 42% in nine months and Karamaniya's approval fell from
0.45 to 0.33. The cause was an engine bug: every statement or offer of talks by a neighbour's cabinet was charged
against that neighbour's real output, so two shrinking neighbours inflated the shared crown. It took nine months and
a counterfactual run by hand to find it. A check on each neighbour's real output would have flagged it from Month 2:
a fall with no war, embargo or disaster to account for it. The price decomposition shows where the move comes from,
and its own dominance flag only fires when one mechanism holds on for three months running.

Recording (economy.money_and_prices and society.update) only writes into w.institutions["engine_watch"]. It reads the
values a month has already computed and changes none of them, so a run is the same with or without it. evaluate()
runs once a month after the snapshot and appends to the flags.
"""
from __future__ import annotations

import math

from .world import World

KEY = "engine_watch"
KEEP_MONTHS = 60        # month records kept; the flags are kept in full
DIGITS = 12             # records are for reading, so they are rounded; the economy never reads them

RIVAL_FALL = 0.02       # a rival's real output fell by more than this share in one month
INFLATION_LIMIT = 0.02  # zone inflation above this in one month ...
NO_PRINTING = 1e-4      # ... while no member printed more than this share of its money stock in a month
DOMINANT_SHARE = 0.6    # one contributor above this share of the absolute price contributions ...
DOMINANT_MONTHS = 3     # ... in this many consecutive months
APPROVAL_FALL = 0.005   # national approval fell by more than this in each of ...
APPROVAL_MONTHS = 3     # ... this many consecutive months

# The named terms of the opinion target in society.update, for the report. Each is what the term adds to the target.
OPINION_LABELS = {
    "baseline": "baseline", "income": "real income", "hunger": "hunger", "unemployment": "unemployment",
    "inflation_pain": "inflation", "savings_loss": "lost savings", "repression": "repression",
    "liberty": "lack of liberty", "legitimacy": "legitimacy", "rally": "rally round the flag",
    "war_weariness": "war weariness", "identity": "identity", "class": "class", "welfare": "welfare",
    "scandal": "scandal", "occupation": "occupation", "ownership": "ownership", "modifiers": "monthly modifiers",
}


# ---- recording (changes no value the simulation reads) ----------------------------------------
def state(w: World) -> dict:
    """The watch's record, created on first use. Plain JSON, so it saves and loads with the checkpoint."""
    return w.institutions.setdefault(KEY, {"last": None, "months": [], "flags": [], "rival_gdp": {}})


def _r(x: float) -> float:
    return round(float(x), DIGITS)


def _entry(rec: dict, month: int) -> dict:
    """This month's record, created at the end of the list if the month has none yet."""
    months = rec["months"]
    if months and months[-1]["month"] == month:
        return months[-1]
    entry = {"month": month}
    months.append(entry)
    del months[:-KEEP_MONTHS]
    return entry


def _find(months: list, month: int) -> dict | None:
    for entry in reversed(months):
        if entry["month"] == month:
            return entry
        if entry["month"] < month:
            return None
    return None


def record_price(w: World, z, v: float, target: float, capacity: dict) -> None:
    """One month of the zone that holds Karamaniya, after its money and prices have moved (recording only).

    The zone's target price is z.scale * m * v / y: m is the members' money, v the velocity and y their capacity.
    So the change in its log is the change in ln(m) plus the change in ln(v) minus the change in ln(y). Each
    member's money growth is its own change as a share of last month's total money, and each member's capacity
    contributes minus its change as a share of last month's total capacity. The shares add up to the change in the
    totals, and the change in a total is the change in its log to first order. The sum therefore matches
    target_change up to ln(1 + x) against x, which is a few hundredths of a per cent for monthly moves of a few per
    cent (the decomposition test allows 1e-3). The scale is constant between months, so it cancels; a currency
    launch changes the zone and starts a new record instead of a contribution.
    """
    rec = state(w)
    members = list(z.members)
    money = {n: float(z.money[n]) for n in members}
    cap = {n: float(capacity[n]) for n in members}
    last = rec["last"]
    if (last and last["month"] == w.month - 1 and last["zone"] == z.id and last["members"] == members
            and v > 0 and target > 0 and last["velocity"] > 0 and last["target"] > 0):
        m_prev = sum(last["money"][n] for n in members)
        y_prev = sum(last["capacity"][n] for n in members)
        if m_prev > 0 and y_prev > 0:
            entry = _entry(rec, w.month)
            entry["zone_inflation"] = _r(z.infl)
            entry["target_change"] = _r(math.log(target / last["target"]))
            entry["price"] = {
                "money": {n: _r((money[n] - last["money"][n]) / m_prev) for n in members},
                "output": {n: _r(-(cap[n] - last["capacity"][n]) / y_prev) for n in members},
                "velocity": _r(math.log(v / last["velocity"])),
            }
    rec["last"] = {"month": w.month, "zone": z.id, "members": members, "money": money, "capacity": cap,
                   "velocity": float(v), "target": float(target)}


class OpinionTally:
    """Population-weighted means of the named opinion terms over one month's population groups (recording only)."""

    def __init__(self) -> None:
        self.size = 0.0
        self.sums: dict = {}
        self.target = 0.0

    def add(self, size: float, terms: dict, target: float) -> None:
        self.size += size
        for name, value in terms.items():
            self.sums[name] = self.sums.get(name, 0.0) + size * value
        self.target += size * target

    def means(self) -> tuple[dict, float]:
        if self.size <= 0:
            return {}, 0.0
        return ({name: _r(total / self.size) for name, total in self.sums.items()}, _r(self.target / self.size))


def record_opinion(w: World, tally: OpinionTally) -> None:
    """The month's population-weighted opinion terms. Their sum is opinion_target, the mean target itself."""
    means, target = tally.means()
    if not means:
        return
    entry = _entry(state(w), w.month)
    entry["opinion"] = means
    entry["opinion_target"] = target


# ---- flags (once a month, after the snapshot) -------------------------------------------------
def evaluate(w: World) -> None:
    """Append this month's flags. A flag of the same kind is never repeated within one month."""
    rec = state(w)
    _rival_falls(w, rec)
    _unexplained_inflation(w, rec)
    _dominant_driver(w, rec)
    _approval_slide(w, rec)


def _flag(rec: dict, month: int, kind: str, text: str) -> None:
    if any(f["month"] == month and f["kind"] == kind for f in rec["flags"]):
        return
    rec["flags"].append({"month": month, "kind": kind, "text": text})


def _rival_falls(w: World, rec: dict) -> None:
    """A rival's real output fell by more than RIVAL_FALL in the month, and nothing in the engine accounts for it.

    Those things do move a rival's output: a war (the Union's drag on every rival), an embargo or sanctions (the
    exporter loses the trade it holds back, and the League's sanctions drag every rival) and a disaster. Any other
    fall is a charge the engine made against output, which is what this check is for.
    """
    m = w.month
    before = rec["rival_gdp"]
    now = {rid: float(r.gdp_real) for rid, r in w.rivals.items()}
    rec["rival_gdp"] = now
    fallen = []
    for rid in now:
        if before.get(rid, 0.0) <= 0.0:
            continue          # the first month only sets the baseline
        fall = (before[rid] - now[rid]) / before[rid]
        if fall > RIVAL_FALL and not _explained(w, rid):
            fallen.append(f"{_name(w.names, rid)}'s output fell {fall:.1%}")
    if fallen:
        _flag(rec, m, "rival_output_fall",
              " and ".join(fallen) + f" in Month {m + 1} with no war, embargo or disaster: check the engine.")


def _explained(w: World, rid: str) -> bool:
    """Whether a war, an embargo, sanctions or a disaster touches this rival this month."""
    if w.dip.war or w.dip.league_sanctions:
        return True
    # The issuer of each embargo, as foreign.sync_embargoes keys them: Veleria's coal, Dorsania's grain.
    if {"veleria": w.dip.coal_embargo, "dorsania": w.dip.grain_embargo}.get(rid, 0.0) > 0.0:
        return True
    if any(obj.get("issuer") == rid and float(obj.get("severity") or 0.0) > 0.0
           for obj in ((w.foreign or {}).get("embargoes") or {}).values()):
        return True
    regions = {r.id for r in w.regions if r.nation == rid}
    return any(d.get("region") in regions and "disaster" in (d.get("tags") or [])
               for d in (w.dilemmas or {}).get("active", []))


def _printing(w: World, nid: str) -> float:
    return abs(w.rivals[nid].printing) if nid in w.rivals else abs(w.policy.printing)


def _unexplained_inflation(w: World, rec: dict) -> None:
    """The zone that holds Karamaniya rose more than INFLATION_LIMIT with no member printing money."""
    m = w.month
    entry = _find(rec["months"], m)
    if entry is None or entry.get("zone_inflation") is None or entry["zone_inflation"] <= INFLATION_LIMIT:
        return
    zone = w.zone_of("karamaniya")
    if any(_printing(w, n) > NO_PRINTING for n in zone.members):
        return
    text = f"Prices in the {zone.name} zone rose {entry['zone_inflation']:.1%} in Month {m + 1} with no member printing money."
    top = _top(entry.get("price"), w.names, 1)
    if top:
        text += f" The largest contributor was {top[0]['label']} ({top[0]['value']:+.2%} of the change in the target)."
    _flag(rec, m, "unexplained_zone_inflation", text)


def _dominant_driver(w: World, rec: dict) -> None:
    """The same contributor was more than DOMINANT_SHARE of the absolute price contributions in each of the last months."""
    m = w.month
    spans = [_find(rec["months"], m - k) for k in range(DOMINANT_MONTHS - 1, -1, -1)]
    if any(e is None or "price" not in e for e in spans):
        return
    tops = []
    for e in spans:
        contributions = _contributions(e["price"], w.names)
        total = sum(abs(value) for _, _, value in contributions)
        if total <= 0.0:
            return
        key, label, value = max(contributions, key=lambda c: abs(c[2]))
        tops.append((key, label, abs(value) / total))
    key, label, _ = tops[0]
    if all(k == key and share > DOMINANT_SHARE for k, _, share in tops):
        share = min(s for _, _, s in tops)
        first = m - DOMINANT_MONTHS + 2
        _flag(rec, m, "dominant_driver",
              f"{label} was at least {share:.0%} of the price move in each of Months {first} to {m + 1}: "
              "one mechanism is dominating prices.")


def _approval_slide(w: World, rec: dict) -> None:
    """National approval fell in each of the last APPROVAL_MONTHS months, by more than APPROVAL_FALL each time."""
    m = w.month
    h = w.history or []
    if len(h) < APPROVAL_MONTHS + 1:
        return
    levels = [row.get("approval") for row in h[-(APPROVAL_MONTHS + 1):]]
    if any(x is None for x in levels):
        return
    if not all(levels[i] - levels[i + 1] > APPROVAL_FALL for i in range(APPROVAL_MONTHS)):
        return
    text = (f"National approval fell in each of Months {m - APPROVAL_MONTHS + 2} to {m + 1}, "
            f"from {levels[0]:.1%} to {levels[-1]:.1%}.")
    term, delta = _worst_term(rec["months"], m)
    if term is not None:
        text += f" The opinion term that worsened most was {OPINION_LABELS.get(term, term)} ({delta:+.3f})."
    _flag(rec, m, "approval_slide", text)


def _worst_term(months: list, m: int) -> tuple[str | None, float]:
    """The opinion term that fell most between the month before the slide and this month, if any fell."""
    now = _opinion(months, m)
    before = _opinion(months, m - APPROVAL_MONTHS)
    if before is None:
        before = _opinion(months, m - APPROVAL_MONTHS + 1)
    if now is None or before is None:
        return None, 0.0
    changes = {t: now[t] - before[t] for t in now if t in before}
    if not changes:
        return None, 0.0
    term = min(changes, key=changes.get)
    return (term, changes[term]) if changes[term] < 0.0 else (None, 0.0)


def _opinion(months: list, month: int) -> dict | None:
    entry = _find(months, month)
    return entry.get("opinion") if entry else None


# ---- what the analytics and the report show ---------------------------------------------------
def _name(names: dict, key: str) -> str:
    return (names or {}).get("k" if key == "karamaniya" else key) or key


def _contributions(price: dict, names: dict) -> list:
    """(key, label, value) for every price contribution of one month."""
    out = [(("money", n), f"{_name(names, n)}'s money growth", v) for n, v in (price.get("money") or {}).items()]
    out += [(("output", n), f"{_name(names, n)}'s output", v) for n, v in (price.get("output") or {}).items()]
    if price.get("velocity") is not None:
        out.append((("velocity", None), "money velocity", price["velocity"]))
    return out


def _top(price: dict | None, names: dict, n: int) -> list:
    """The n largest price contributions of a month, by absolute size."""
    if not price:
        return []
    rows = [{"kind": key[0], "country": key[1], "label": label, "value": value}
            for key, label, value in _contributions(price, names)]
    rows.sort(key=lambda r: -abs(r["value"]))
    return rows[:n]


def _moves(now: dict | None, before: dict | None, n: int) -> list:
    """The n opinion terms that moved most between two months, by absolute size."""
    if not now or not before:
        return []
    rows = [{"term": t, "label": OPINION_LABELS.get(t, t), "before": before[t], "now": now[t],
             "change": _r(now[t] - before[t])} for t in now if t in before]
    rows.sort(key=lambda r: -abs(r["change"]))
    return rows[:n]


def summary_of(rec: dict, names: dict) -> dict:
    """The flags, and for the last recorded month its three largest price contributions and the three opinion terms
    that moved most since the month before. Plain data: analytics.json carries it."""
    out = {"flags": [dict(f) for f in rec.get("flags") or []], "last_month": None}
    months = rec.get("months") or []
    if not months:
        return out
    last = months[-1]
    before = _find(months, last["month"] - 1)
    out["last_month"] = {
        "month": last["month"], "zone_inflation": last.get("zone_inflation"),
        "target_change": last.get("target_change"),
        "price": _top(last.get("price"), names, 3),
        "opinion": _moves(last.get("opinion"), before.get("opinion") if before else None, 3),
    }
    return out


def summary(w: World) -> dict:
    return summary_of(w.institutions.get(KEY) or {}, w.names)


def report_view(rec: dict, names: dict) -> dict:
    """What the report's Engine watch section reads: the flags newest first, and one compact row per recorded month."""
    months = rec.get("months") or []
    rows = []
    for entry in months:
        before = _find(months, entry["month"] - 1)
        rows.append({
            "month": entry["month"], "zone_inflation": entry.get("zone_inflation"),
            "target_change": entry.get("target_change"),
            "price": _top(entry.get("price"), names, 3),
            "opinion": _moves(entry.get("opinion"), before.get("opinion") if before else None, 3),
        })
    return {"flags": list(reversed(rec.get("flags") or [])), "months": rows}
