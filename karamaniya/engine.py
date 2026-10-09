"""One simulated month, and the monthly snapshot the report is built from."""
from __future__ import annotations

from dataclasses import asdict

from . import agents, director, economy, founding, human, military, politics, society, state_validation
from .military import union_army, union_navy
from .society import inflation_yoy
from .economy import front_region
from .world import CLASSES, IDENTITIES, World, annualize, democracy_index


# How far a run may go past its configured length to play out a handover the government owes after
# losing an election: the handover month, and the month or two a lawful challenge can add.
HANDOVER_EXTENSION = 4


def begin_month(w: World) -> None:
    """Start a new month: clear the event list before the council acts."""
    w.events = []


def step(w: World, foreign_decisions: dict | None = None, foreign_prepared: bool = False) -> None:
    """Simulate the current month after the council has acted, then advance the clock."""
    if w.ended():
        return
    v2 = w.human_factor and w.agent_architecture_version >= 2
    if v2:
        from . import audits, dilemmas, operations, standing
        dilemmas.apply_ongoing(w)
        audits.apply_ongoing(w)
        w.institutions["operation_notes"] = operations.apply(w)
        standing.implementation_effects(w, w.institutions.get("changed_levers", {}))
    director.act(w, foreign_decisions, foreign_prepared)
    from . import rivals
    rivals.monthly(w)
    prod = trade = fiscal = None
    if not w.ended():
        # Release any scheduled effects that have matured before the month is produced, so a
        # policy change announced months ago lands in the month it was always going to land in.
        from . import causality
        causality.apply_lags(w)
        prod = economy.produce(w)
        trade = economy.trade_and_food(w, prod)
        fiscal = economy.fiscal(w, prod, trade)
        economy.money_and_prices(w, prod)
        # Score any forecast whose horizon has now elapsed, against the state just produced.
        from . import forecasts
        forecasts.resolve_due(w)
        military.update(w, fiscal)
        society.update(w, prod, fiscal)
        politics.monthly_checks(w)
        founding.advance(w)
    if w.human_factor and 1 <= w.agent_architecture_version < 2:
        agents.update_conditions(w)
    snapshot(w)
    if v2:
        # Credit, blame, beliefs and stress respond to this month's outcome, so they run after the snapshot.
        from . import audits, dilemmas
        agents.update_conditions(w)
        audits.deliver(w)
        dilemmas.review(w, w.agenda.get("this_month"))
        dilemmas.generate(w)
    if not w.ended() and w.month + 1 >= w.months_total:
        c = w.const
        configured = int(w.counters.setdefault("months_configured", float(w.months_total)))
        # A vote the electoral court ordered re-run after the defeat is part of the same handover.
        revote = (c.election_month if c.elections and c.elections[-1].get("court") == "annulled"
                  and c.election_month > w.month else -1)
        owed = max(c.handover_month, revote)
        if owed > w.month and owed < configured + HANDOVER_EXTENSION:
            # The government lost the election (the Charter's falls in Month 36, the last month of a
            # default run) and has not handed power over. The run goes on into the month it must, so
            # whether it does is part of the record rather than past its end.
            w.months_total = owed + 1
        elif "handover_blocked_month" in w.counters:
            w.outcome = {"type": "kept_power_by_force", "month": w.month,
                         "text": f"The government lost the election and kept power by force in "
                                 f"Month {int(w.counters['handover_blocked_month']) + 1}; the Assembly never "
                                 f"took office. After {w.months_total} months the {c.regime_name} still governs."}
        else:
            w.outcome = {"type": "survived", "month": w.month,
                         "text": f"After {w.months_total} months, the {c.regime_name} still governs an "
                                 "independent Karamaniya."}
    # Keep the early row available to handlers such as credit_and_blame(), which
    # compare this month with the prior one. Replace it only after post-month work
    # so events, audit consequences, issue reversals and terminal outcomes are current.
    snapshot(w, refresh_last=True)
    if v2:
        # The canonical snapshot does not include the v2 inspector payload. Rebuild both
        # from final state after replacing the row, including reports and audits produced
        # after the early snapshot.
        w.history[-1]["member_social"] = agents.snapshot(w)
        w.history[-1]["v2"] = v2_extras(w)
    state_validation.refresh(w, w.history[-1])
    # The monthly forecast panel (engine 13) is about the end of a month, so it is scored here, after
    # the month's elections, combat and opinion have all moved.
    from . import forecasts
    forecasts.resolve_panel(w)
    w.last_events = w.events
    w.month += 1


def _r4(v: float) -> float:
    return round(v, 4)


def v2_extras(w: World) -> dict:
    """What the version-2 subsystems looked like at the end of the month, for the inspector and map."""
    from . import intelligence
    intel = intelligence.state(w)
    return {
        "issues": [{k: d.get(k) for k in ("id", "kind", "title", "text", "month", "region", "status", "tags", "target")}
                   for d in w.dilemmas.get("active", [])],
        "issues_ended": [{k: d.get(k) for k in ("id", "kind", "title", "outcome", "ended_month")}
                         for d in w.dilemmas.get("history", []) if d.get("ended_month") == w.month],
        "emergency_measures": {k: dict(v) for k, v in (w.institutions.get("emergency_measures") or {}).items()},
        "audits": {"open": [dict(a) for a in (w.institutions.get("audits") or {}).get("open", [])],
                   "reports": [dict(r) for r in (w.institutions.get("audits") or {}).get("done", [])
                               if r.get("month") == w.month]},
        "capacity": dict(w.institutions.get("capacity", {})),
        "corruption": dict(w.institutions.get("corruption", {})),
        "operations": {k: {x: y for x, y in v.items() if x not in ("by", "month")}
                       for k, v in (w.institutions.get("operations") or {}).items()},
        "narratives": [n for n in w.media.get("narratives", []) if n["month"] == w.month],
        "media_reach": dict(w.media.get("reach", {})),
        "leaks": [{k: v for k, v in x.items() if k != "text"} for x in intel["leaks"] if x["month"] == w.month],
        "reports": [{k: r[k] for k in ("id", "office", "subject", "estimate", "low", "high", "confidence", "truth",
                                        "accurate", "error", "alarming", "shared_with")}
                    for r in intel["reports"] if r["month"] == w.month],
        "shared": [{k: v for k, v in x.items() if k != "text"} for x in intel["shared"] if x["month"] == w.month],
        "requests": [dict(q) for q in intel["requests"] if q["month"] == w.month],
        "contested": [dict(x) for x in intel.get("contested", []) if x["month"] == w.month],
        "vindications": [dict(x) for x in w.analytics.get("vindications", []) if x["month"] == w.month],
        "deferred": [m.get("summary") for m in w.agenda.get("deferred", [])],
        "credit": [c for c in w.media.get("credit_log", []) if c["month"] == w.month],
    }


def region_detail(w: World) -> dict:
    """Per-region picture for the map: who lives there and how they are doing."""
    out = {}
    for r in w.regions:
        if r.nation != "karamaniya":
            continue
        grp = [p for p in w.pops if p.region == r.id]
        size = sum(p.size for p in grp) or 1.0

        def avg(attr, grp=grp, size=size):
            return _r4(sum(getattr(p, attr) * p.size for p in grp) / size)
        out[r.id] = {
            "pop": round(size), "approval": avg("approval"), "hunger": avg("hunger"), "unrest": avg("unrest"),
            "indep": avg("indep"), "fear": avg("fear"), "grievance": avg("grievance"),
            "unemployment": avg("unemployment"), "income": avg("income"), "savings": avg("savings"),
            "conscripted": round(sum(p.conscripted for p in grp)), "interned": round(sum(p.interned for p in grp)),
            "ident": {i: _r4(sum(p.size for p in grp if p.ident == i) / size) for i in IDENTITIES},
            "cls": {k: _r4(sum(p.size for p in grp if p.cls == k) / size) for k in CLASSES},
            "rebels": round(r.rebels), "repression": _r4(r.repression_event),
            "logistics": _r4(r.logistics), "founding_problems": founding.problem_for_region(w, r.id),
        }
    return out


def front_detail(w: World) -> dict:
    """Each front this month: where it runs, who stands on it, and whether there was fighting."""
    m, dip = w.mil, w.dip
    out = {}
    for f in ("north", "east"):
        r = front_region(w, f)
        ours = m.army.size * m.deploy.get(f, 0.0)
        if r is not None and r.capital:
            ours += m.army.size * m.deploy.get("capital", 0.0)
        combat = m.last_combat.get(f)
        # Troops a neighbour has massed at this border without a war (engine 12), by country.
        massing_by = {a: round(forces.get(f, 0.0)) for a, forces in (dip.border_forces or {}).items()
                      if forces.get(f, 0.0) >= 1}
        out[f] = {"region": r.id if r is not None else None, "ours": round(ours),
                  "union": round(dip.union_front.get(f, 0.0)),
                  "massing": sum(massing_by.values()), "massing_by": massing_by,
                  "fort": _r4(m.fort.get(f, 0.0)),
                  "progress": _r4(m.progress.get(f, 0.0)), "recapture": _r4(m.recapture.get(f, 0.0)),
                  "combat": combat if isinstance(combat, dict) and combat.get("month") == w.month else None}
    return out


def nation_detail(w: World) -> dict:
    """Comparable modelled country totals; output is in starting-price crown units."""
    e, m = w.econ, w.mil
    pop = w.population()
    out = {"karamaniya": {
        "population": round(pop, -3), "output_annual": round(e.gdp_real * 12, -6),
        "output_per_person": round(e.gdp_real * 12 / pop, -1) if pop else 0,
        "army": round(m.army.size, -2), "navy": round(m.navy.size),
        "unemployment": _r4(e.unemployment), "food_ratio": _r4(e.food_ratio),
        "inflation_yoy": _r4(inflation_yoy(w)), "currency": e.currency,
    }}
    for rid, rival in w.rivals.items():
        posture = w.foreign.get("actors", {}).get(rid, {}).get("military", {}) if w.foreign else {}
        last_move = next((x for x in reversed(w.foreign.get("escalation_chains", [])) if x.get("actor") == rid), None) if w.foreign else None
        out[rid] = {"population": round(rival.population, -3),
                    "output_annual": round(rival.gdp_real * 12, -6),
                    "output_per_person": round(rival.gdp_real * 12 / rival.population, -1) if rival.population else 0,
                    "army": round(rival.army, -2), "navy": round(rival.navy),
                    "monthly_printing": _r4(rival.printing),
                    "readiness": _r4(posture.get("readiness", .5)),
                    "supply": _r4(posture.get("supply", .75)),
                    "morale": _r4(rival.morale),
                    "fortification": _r4(posture.get("fortification", .0)),
                    "last_movement": (f"Month {last_move['month']+1}: {last_move['signal']} +{last_move.get('magnitude',0):,.0f}"
                                      if last_move else "no recent movement reported"),
                    "visible_mission": "border security" if not w.dip.war else "active front deployment"}
    return out


def snapshot(w: World, refresh_last: bool = False) -> None:
    if refresh_last:
        # Rebuild against the preceding months: inflation and other history-derived
        # values must not shift just because this row was already appended once.
        if not w.history or w.history[-1].get("month") != w.month:
            raise ValueError("cannot refresh a snapshot without this month's history row")
        previous = w.history.pop()
        try:
            snapshot(w)
            refreshed = w.history.pop()
        finally:
            w.history.append(previous)
        previous.clear()
        previous.update(refreshed)
        return

    e, m, dip, c = w.econ, w.mil, w.dip, w.const
    army_mobilized = military.mobilization_draw(w)
    army_mobilized_effective = military.mobilized_strength(w)
    military.sync_state(w)
    pops = w.k_pops()
    total = sum(p.size for p in pops) or 1.0
    by_ident = {}
    for ident in IDENTITIES:
        grp = [p for p in pops if p.ident == ident]
        size = sum(p.size for p in grp)
        by_ident[ident] = {
            "share": size / total,
            "approval": w.avg("approval", grp) if grp else 0.0,
            "indep": w.avg("indep", grp) if grp else 0.0,
            "unrest": w.avg("unrest", grp) if grp else 0.0,
        }
    gdp_nom = e.gdp_nominal or 1.0
    z = w.zone_of("karamaniya")
    gold_to_local = z.price / (e.fx_conf if e.currency == "karam" else 1.0)
    # A run can be resumed after an engine update. Capture the loaded runtime's source signature
    # on every month so historical reports can detect a mixed-code run instead of pretending the
    # entire history was produced by the engine version currently on disk.
    from .manifest import RUNTIME_SOURCE_FINGERPRINT
    w.history.append({
        "month": w.month,
        "engine_source_fingerprint": RUNTIME_SOURCE_FINGERPRINT,
        "cpi": e.cpi, "infl_m": e.infl, "infl_a": annualize(e.infl), "infl_yoy": inflation_yoy(w),
        "published_infl_a": annualize(e.infl) * (1 - e.stats_gap),
        "exp_infl_a": annualize(z.exp_infl), "zone_price": z.price,
        "currency": e.currency, "fx": e.fx,
        "gdp_idx": e.gdp_real / e.gdp_real0 if e.gdp_real0 else 1.0,
        "founding": founding.public_profile(w),
        "founding_divergence": founding.divergence(w),
        "food_ratio": e.food_ratio, "energy": e.energy, "unemployment": e.unemployment,
        "hunger": w.avg("hunger"), "income": w.avg("income"), "real_wage": e.wage / e.cpi,
        "food_rel": e.food_rel, "weather": e.weather,
        "revenue": e.revenue, "spending": e.spending, "deficit_gdp": e.deficit / gdp_nom,
        "printed_gdp": e.printed / gdp_nom, "arrears_gdp": e.arrears / gdp_nom,
        "paid_share": e.paid_share,
        "debt_gdp": (e.debt_dom + e.debt_for * gold_to_local) / (12 * gdp_nom),
        "gold": e.gold, "state_grain": e.state_grain, "food_stock": e.food_stock,
        "population": w.population(), "population_all": sum(p.size for p in w.pops),
        "approval": w.avg("approval"), "indep": w.avg("indep"), "unrest": w.avg("unrest"),
        "fear": w.avg("fear"), "by_ident": by_ident,
        "army": m.army.size, "army_mobilized": army_mobilized,
        "army_mobilized_effective": army_mobilized_effective,
        "army_field_total": m.army.size + army_mobilized_effective,
        "army_equipment": m.army.equipment, "army_morale": m.army.morale,
        "army_loyalty": m.army.loyalty, "army_bond": m.army.bond, "army_arrears": m.army.arrears,
        "navy": m.navy.size, "navy_loyalty": m.navy.loyalty, "navy_bond": m.navy.bond,
        "police_loyalty": m.police.loyalty, "police_bond": m.police.bond,
        "fort": dict(m.fort), "progress": dict(m.progress),
        "union_army": union_army(w), "union_navy": union_navy(w),
        "union_weariness": dip.union_weariness, "union_front": dict(dip.union_front),
        "war": dip.war, "ceasefire": dip.ceasefire, "blockade_eff": dip.blockade_eff,
        "grain_embargo": dip.grain_embargo, "coal_embargo": dip.coal_embargo,
        "propaganda": dip.propaganda, "league_trust": dip.league_trust, "rally": dip.rally,
        "democracy": democracy_index(w),
        "regions": {r.id: {"controller": r.controller, "unrest": r.unrest, "damage": r.damage,
                           "strike": r.strike}
                    for r in w.regions if r.nation == "karamaniya"},
        "offices": dict(c.offices),
        "hard_state": {
            "currency": e.currency, "currency_launch": e.currency_launch,
            "war": dip.war, "ceasefire": dip.ceasefire, "blockade": dip.blockade,
            "union_formed": dip.union_formed, "federation": dip.federation,
            "league_alliance": dip.league_alliance, "league_sanctions": dip.league_sanctions,
            "offices": dict(c.offices), "directives": dict(c.directives),
            "election_month": c.election_month,
            "army": m.army.size, "army_mobilized": army_mobilized,
            "army_mobilized_effective": army_mobilized_effective,
            "navy": m.navy.size, "police": m.police.size,
            "debt_dom": e.debt_dom, "debt_for": e.debt_for, "reserves": e.gold,
            "arrears": e.arrears,
            "regions": {r.id: r.controller for r in w.regions if r.nation == "karamaniya"},
        },
        "members": {mem.id: mem.status for mem in w.members},
        "member_social": (agents.snapshot(w) if w.agent_architecture_version >= 1
                          else human.snapshot(w) if w.human_factor else {}),
        "agent_architecture_version": w.agent_architecture_version,
        "constitution": {"regime_name": c.regime_name, "decision_rule": c.decision_rule,
                         "press": c.press, "assembly": c.assembly, "emergency": c.emergency,
                         "minority": c.minority, "election_month": c.election_month,
                         "charter_election_month": c.charter_election_month,
                         "kessel_status": c.kessel_status, "highlands_status": c.highlands_status,
                         "elected": c.elected, "provisional": c.provisional,
                         "directives": {k: (v if not isinstance(v, float) else round(v, 4))
                                        for k, v in c.directives.items()}},
        "policy": asdict(w.policy),
        "counters": dict(w.counters),
        "events": list(w.events),
        "outcome": dict(w.outcome),
        "region_detail": region_detail(w),
        "nations": nation_detail(w),
        "fronts": front_detail(w),
        # What the combat model makes of each front, from the true figures (engine 13); the Army office
        # reads the same assessment through its own estimates of foreign strength.
        "net_assessment": military.net_assessment(w),
        "deploy": {k: _r4(v) for k, v in m.deploy.items()},
        "garrison": round(m.army.size * m.deploy.get("capital", 0.0)),
        "union_intensity": _r4(dip.union_intensity), "union_formed": dip.union_formed,
        "ultimatum": bool(dip.ultimatum), "arms_smuggling": dip.arms_smuggling,
        "league": {"alliance": dip.league_alliance, "escort": dip.league_escort,
                   "sanctions": dip.league_sanctions, "aid": _r4(dip.league_aid)},
        "geopolitics": {
            "union": {k: v for k, v in w.foreign.get("union", {}).items()
                      if k != "history"} if w.foreign else {},
            "embargoes": [dict(v) for v in w.foreign.get("embargoes", {}).values()] if w.foreign else [],
            "league": {"trust": _r4(w.dip.league_trust), "sanctions": dip.league_sanctions,
                       "escort": dip.league_escort, "shipping_risk": _r4(w.foreign.get("league", {}).get("shipping_security_concern",0))},
            "intelligence": (w.foreign.get("government_intelligence", [])[-1].get("actors", {})
                             if w.foreign.get("government_intelligence") else {}) if w.foreign else {},
        },
        "police": m.police.size,
    })
