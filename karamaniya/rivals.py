"""The rivals as living states: money, upkeep, mobilization and visible troop movement.

`director._union_forces` decides *what the Union wants* (growth, front splits, war pressure).
This module decides *what the rivals can actually sustain*: an army costs money every month,
a fiscally stressed government cannot keep mobilising, reserves run down when soldiers are
called up, and every movement of troops leaves a visible trace Karamaniya's intelligence can
see. Nothing here reads private Karamaniya state except what is publicly observable.

Deterministic: all randomness comes from `rng_for(seed, month, tag)`.
"""
from __future__ import annotations

from . import foreign_force
from .world import World, clamp, rng_for

# What one soldier costs a month, in crowns at founding prices. The burden is this money over the country's current
# monthly output, so a big army on a small economy is a heavy burden, which is the pressure that shapes rival
# behaviour (Audit FO10: the cost used to be a share of output, which cancelled out the economy). Calibrated so that
# Veleria's founding army of 65,000 sits near 70% of the cap.
UPKEEP_PER_SOLDIER = 815.0
# A rival cannot spend more of its output on defence than this before readiness falls.
DEFENCE_BURDEN_CAP = 0.065
# The share of the cap at which readiness holds in peace (Audit FO10). A founding army starts near 70% of the cap and,
# once the treasury has recovered in peace, settles at about this share (Veleria 0.769 of the cap after 36 peaceful
# months). Below it money buys training and readiness rises; above it readiness erodes. The engine used to erode it
# every peacetime month from the cap.
READINESS_HOLD = 0.77
# Readiness drift: the most readiness gains in a month (at no burden) or loses (at the cap).
READINESS_DRIFT = 0.012
# How fast a rival replaces battlefield losses from its reserve pool.
REPLACEMENT_RATE = 0.06


def _monthly_output(actor: dict) -> float:
    """That country's output this month, from its own economy block (never Karamaniya's)."""
    annual = float(actor["economy"].get("gdp") or 0.0) * max(0.0, 1 + float(actor["economy"].get("growth") or 0.0))
    return max(1.0, annual / 12.0)


def _readiness_drift(burden: float) -> float:
    """What one month's burden does to readiness (Audit FO10): a burden below READINESS_HOLD of the cap buys training,
    up to READINESS_DRIFT a month at no burden; above it readiness erodes, down to READINESS_DRIFT a month at the cap."""
    hold = READINESS_HOLD * DEFENCE_BURDEN_CAP
    if burden <= hold:
        return READINESS_DRIFT * (1 - burden / hold)
    return -READINESS_DRIFT * (burden - hold) / (DEFENCE_BURDEN_CAP - hold)


def _defence_budget(w: World, actor_id: str) -> tuple[float, float, str]:
    """(spend, burden, mood) for one rival this month. The army is priced in money and the burden is that money over the
    country's current output (Audit FO10)."""
    actor = w.foreign["actors"][actor_id]
    rival = w.rivals[actor_id]
    dom, econ = actor["domestic"], actor["economy"]
    output = _monthly_output(actor)
    want = rival.army * UPKEEP_PER_SOLDIER
    if w.dip.war:
        want *= 1.25
    want *= 1 + 0.2 * float(actor["threat_perception"].get("karamaniya", 0.45))
    strain = (0.55 * float(dom.get("fiscal_stress", 0.18))
              + 0.35 * float(econ.get("inflation", 0.03))
              + 0.45 * float(dom.get("war_weariness", 0.0)))
    spend = want * clamp(1 - strain, 0.45, 1.0)
    burden = spend / output
    if burden > DEFENCE_BURDEN_CAP:
        spend = DEFENCE_BURDEN_CAP * output
        burden = DEFENCE_BURDEN_CAP
        mood = "overstretched"
    elif strain > 0.5:
        mood = "strained"
    elif strain < 0.22 and spend >= want * 0.98:
        mood = "comfortable"
    else:
        mood = "manageable"
    return spend, burden, mood


def _union_losses(w: World, actor_id: str) -> float:
    """The Union's soldiers this neighbour's army killed this month, from military.update's combat record. That record
    is keyed by front, not by actor (Audit FO4), so each front's losses go to the neighbours that hold it, in proportion
    to their armies: the ones whose border reaches the front, among the armies at war."""
    combat = w.mil.last_combat if isinstance(w.mil.last_combat, dict) else {}
    participants = (w.dip.war_aim or {}).get("participants") or list(w.rivals)
    losses = 0.0
    for front in foreign_force.FRONTS:
        record = combat.get(front)
        if not isinstance(record, dict):
            continue
        holders = [p for p in participants if p in w.rivals and front in foreign_force.FRONTS_OF.get(p, ())]
        if actor_id not in holders:
            continue
        total = sum(w.rivals[p].army for p in holders) or 1.0
        losses += float(record.get("u_loss", 0.0) or 0.0) * w.rivals[actor_id].army / total
    return losses


def monthly(w: World) -> dict:
    """Pay the rivals' armies, move the balance of their reserves, and log what was visible."""
    if not w.foreign or not w.rivals:
        return {}
    rng = rng_for(w.seed, w.month, "rival-mobilisation")
    out = {}
    for actor_id in ("veleria", "dorsania"):
        actor = w.foreign["actors"].get(actor_id)
        if actor is None or actor_id not in w.rivals:
            continue
        rival = w.rivals[actor_id]
        dom, econ, mil = actor["domestic"], actor["economy"], actor["military"]
        spend, burden, mood = _defence_budget(w, actor_id)

        # Paying for the army is a domestic burden: it shows up as fiscal stress, lower approval
        # and slower growth, not as a book-keeping cut to this month's output. Output is left to
        # foreign._domestic so the two cannot compound, and the burden is written to the record.
        from .foreign import _remember
        _remember(w.foreign, actor_id, "action_cost",
                  f"Army upkeep cost about {burden:.1%} of monthly output.", w.month,
                  gdp_share=round(burden, 4), mood=mood)
        dom["fiscal_stress"] = round(clamp(float(dom.get("fiscal_stress", 0.18)) + burden * 0.12), 3)
        # Peacetime lets a treasury recover; war and mobilisation do not.
        if not w.dip.war:
            dom["fiscal_stress"] = round(max(0.04, dom["fiscal_stress"] - 0.012), 3)
        dom["approval"] = round(clamp(float(dom["approval"])
                                      - 0.004 * (burden / max(DEFENCE_BURDEN_CAP, 1e-9))), 3)

        # Reserves: losses are replaced from the trained pool; peace lets the pool grow.
        loss = _union_losses(w, actor_id)
        pool = float(mil.get("reserves", 0.0))
        if loss > 0 and pool > 0:
            replaced = min(loss * REPLACEMENT_RATE * (0.5 + 0.5 * float(mil.get("readiness", 0.5))),
                           pool * 0.05)
            mil["reserves"] = round(pool - replaced, 1)
            # Audit FO4: one soldier for each reserve drawn. The engine used to add 0.4 of them to the army.
            rival.army += replaced
        elif not w.dip.war and burden < DEFENCE_BURDEN_CAP * READINESS_HOLD:
            mil["reserves"] = round(pool + rival.army * 0.01 * (1 - burden / DEFENCE_BURDEN_CAP), 1)

        # Readiness follows money, continuously: a light burden buys training, a crushing one
        # hollows the force out. A sustained war erodes it further.
        readiness = float(mil.get("readiness", 0.5))
        drift = _readiness_drift(burden)
        if w.dip.war:
            drift -= 0.008 * (1 + float(dom.get("war_weariness", 0.0)))
        mil["readiness"] = round(clamp(readiness + drift, 0.05, 0.95), 3)
        mil["supply"] = round(clamp(0.9 - 0.5 * float(dom.get("war_weariness", 0.0)) - 0.2 * burden,
                                    0.25, 1.0), 3)
        mil["active"] = rival.army
        out[actor_id] = {"spend": round(spend, 1), "burden": round(burden, 4), "mood": mood,
                         "readiness": mil["readiness"], "reserves": mil["reserves"],
                         "active": mil["active"]}

    _visible_movements(w, rng, out)
    return out


def _visible_movements(w: World, rng, out: dict) -> None:
    """Log troop movements an observer could see, and let them harden alertness."""
    watch = list(w.foreign.get("rival_watch") or [])
    last = watch[-1] if watch else {}
    marks = []
    for actor_id, now in out.items():
        before = last.get(actor_id) or {}
        move = float(now["reserves"]) - float(before.get("reserves", now["reserves"]))
        callup = float(now["active"]) - float(before.get("active", now["active"]))
        if abs(move) > 400:
            marks.append((actor_id, "called up reserve units" if move < 0 else "released units back to the reserve",
                          round(abs(move))))
        if callup > 2500:
            marks.append((actor_id, "massed units", round(callup)))
    if marks:
        w.foreign.setdefault("escalation_chains", [])
        for actor_id, what, n in marks:
            w.foreign["escalation_chains"].append({"month": w.month, "actor": actor_id, "signal": what,
                                                   "magnitude": n, "observed": True})
        w.foreign["escalation_chains"] = w.foreign["escalation_chains"][-60:]
    watch.append({a: {"readiness": v["readiness"], "reserves": v["reserves"], "active": v["active"],
                      "burden": v["burden"]} for a, v in out.items()})
    w.foreign["rival_watch"] = watch[-24:]


def observation_text(w: World) -> str:
    """What a staff officer could report this month about the neighbours' forces."""
    watch = (w.foreign.get("rival_watch") or []) if w.foreign else []
    if not watch:
        return ""
    latest, prior = watch[-1], (watch[-2] if len(watch) >= 2 else {})
    lines = []
    for actor_id in sorted(latest):
        v = latest[actor_id]
        name = (w.names or {}).get(actor_id, actor_id)
        trends = []
        was = prior.get(actor_id)
        if was:
            if v["readiness"] - was["readiness"] > 0.02:
                trends.append("training activity up")
            elif was["readiness"] - v["readiness"] > 0.02:
                trends.append("training activity falling off")
            if was["reserves"] - v["reserves"] > 400:
                trends.append("reservists called up")
            elif v["reserves"] - was["reserves"] > 400:
                trends.append("units released back to the reserve")
        burden = v["burden"]
        strain = ("defence spending is a heavy burden on its economy" if burden > DEFENCE_BURDEN_CAP * 0.85
                  else "defence spending is moderate" if burden > DEFENCE_BURDEN_CAP * 0.5
                  else "defence spending is light")
        line = f"- {name}: readiness about {v['readiness']:.0%}, reserves about {v['reserves']:,.0f}; {strain}"
        if trends:
            line += "; " + ", ".join(trends)
        lines.append(line + ".")
    return ("NEIGHBOURS' FORCES (estimates; movements are visible, intentions are not)\n"
            + "\n".join(lines))

