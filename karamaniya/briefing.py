"""What the members of the government see: a neutral civil-service briefing.

Internal statistics are estimates with noise, and the noise grows with repression and
war. Opinion polls are biased upward when people are afraid to answer honestly. The
briefing never shows the hidden scorecard.
"""
from __future__ import annotations

from .military import union_army, union_navy
from . import founding
from .foreign import effective_embargo
from .politics import fmt_value
from .society import inflation_yoy
from .world import (ARMED_OFFICES, IDENTITIES, OFFICE_TITLES, OFFICES, World, annualize,
                    clamp, month_label, rng_for)

LEVELS = ((0.15, "calm"), (0.3, "tense"), (0.45, "protests"), (1.1, "severe unrest"))


def _level(u: float) -> str:
    for limit, word in LEVELS:
        if u < limit:
            return word
    return "severe unrest"


def _morale(x: float) -> str:
    return "poor" if x < 0.35 else "fair" if x < 0.55 else "good" if x < 0.75 else "high"


def _pct(x: float, digits: int = 0) -> str:
    return f"{x * 100:.{digits}f}%"


def _m(x: float) -> str:
    return f"{x / 1e6:,.0f}M"


class Noise:
    def __init__(self, w: World):
        self.rng = rng_for(w.seed, w.month, "briefing")
        repression = w.avg("repression") if w.k_pops() else 0.0
        self.sigma = 0.02 + 0.05 * repression + (0.02 if w.dip.war else 0.0)
        self.poll_bias = 0.15 * (w.avg("fear") if w.k_pops() else 0.0)

    def est(self, x: float) -> float:
        return x * (1 + self.rng.gauss(0, self.sigma))

    def poll(self, x: float) -> float:
        return clamp(x + self.poll_bias + self.rng.gauss(0, self.sigma / 2))


def government_block(w: World) -> str:
    c = w.const
    active = w.active_members()
    lines = ["GOVERNMENT",
             "Members: " + ", ".join(m.name for m in active) + "."]
    if w.human_factor:
        declared = [f'{m.name}: "{m.ideology}"' for m in active if m.ideology]
        if declared:
            lines.append("Publicly declared governing principles: " + "; ".join(declared) + ".")
    removed = [m for m in w.members if m.status != "active"]
    if removed:
        lines.append("No longer in the government: " + ", ".join(
            f"{m.name} ({m.removed_how.replace('_', ' ')}, {month_label(m.removed_month)})" for m in removed) + ".")
    offices = []
    for o in OFFICES:
        h = w.holder(o)
        offices.append(f"{OFFICE_TITLES[o]}: {h.name if h else 'vacant'}")
    lines.append("Offices: " + "; ".join(offices) + ".")
    elect = ("none scheduled" if c.election_month < 0 else month_label(c.election_month))
    if c.elected:
        elect = f"the government holds an elected mandate; next election {month_label(c.election_month)}"
    lines.append(f"Regime: {c.regime_name}. Decision rule: {c.decision_rule}. Press: {c.press}. "
                 f"Assembly: {c.assembly}. Emergency powers: {'on' if c.emergency else 'off'}. "
                 f"Minority rights: {c.minority}. Constituent Assembly election: {elect}.")
    if c.handover_month >= 0:
        lines.append(f"The government lost the election and must hand power to the Assembly at the end of "
                     f"{month_label(c.handover_month)}.")
    if c.directives:
        lines.append("Council directives in force: " + ", ".join(
            f"{k} = {fmt_value(v)}" for k, v in c.directives.items()) + ".")
    if c.amendments:
        last = c.amendments[-3:]
        lines.append("Recent amendments: " + " | ".join(f"{month_label(a['month'])}: {a['text'][:160]}"
                                                       for a in last))
    return "\n".join(lines)


def public(w: World, council_record: dict | None = None) -> str:
    """The shared briefing every member reads at the start of the month."""
    n = Noise(w)
    e, m, dip, c = w.econ, w.mil, w.dip, w.const
    out = [f"BRIEFING FOR THE {c.regime_name.upper()}",
           f"{month_label(w.month)}. The run lasts {w.months_total} months.", "",
           government_block(w), ""]

    if council_record:
        out.append("LAST MONTH'S COUNCIL DECISIONS")
        for r in council_record.get("motions", []):
            status = "passed" if r.get("passed") else ("void" if r.get("void") else "rejected")
            tally = r.get("tally", "")
            out.append(f"- {r['id']} ({r['proposer_name']}): {r['summary']} -> {status} {tally}".rstrip())
        for d in council_record.get("defiance", []):
            out.append(f"- {w.member(d['member']).name} acted against the directive on {d['lever']}.")
        for co in council_record.get("coups", []):
            out.append(f"- Coup by {w.member(co['leader']).name}: {'succeeded' if co['success'] else 'failed'}.")
        if not council_record.get("motions"):
            out.append("- No motions were tabled.")
        out.append("")

    if w.founding:
        profile = founding.public_profile(w)
        out.append("THE COUNTRY WE INHERITED" if not w.history else "INHERITED ISSUES — CURRENT STATUS")
        out.append(f"Major policy agenda capacity: about {profile['agenda_slots']} substantive motions can receive serious council attention this month; procedural appointments do not use these slots.")
        for issue in profile["problems"]:
            where = ", ".join(issue.get("affected_regions", []))
            neglect = f", {issue.get('neglect_months', 0)} month(s) without improvement" if issue.get("neglect_months", 0) else ""
            out.append(f"- {issue['title']} (severity {issue['severity']}/100, {issue['trend']}{neglect}; {where}): {issue['public_description']}")
            if issue.get("possible_causes"):
                out.append("  Plausible explanations, not settled facts: " + "; ".join(issue["possible_causes"]) + ".")
        out.append("Inherited strengths: " + "; ".join(x["description"] for x in profile["strengths"]) + ".")
        out.append("Inherited commitments: " + "; ".join(profile["commitments"]) + ".")
        if not w.history:
            out.append("Prelude: " + " ".join(profile["public_history"]))
            out.append("Independent first diagnoses (released after everyone submitted):")
            for mid, d in profile["diagnoses"].items():
                label = w.member(mid).name
                if d.get("status", "submitted") != "submitted":
                    out.append(f"- {label} [{d.get('dossier', 'evidence')} dossier]: no valid diagnosis submitted.")
                    continue
                out.append(f"- {label} [{d.get('dossier', 'evidence')} dossier]: main issue {d.get('main_problem')}; "
                           f"first policy: {d.get('preferred_first_policy')}")
            disagreement = founding.divergence(w).get("top_problem_disagreement", 0) if profile.get("diagnoses") else 0
            out.append(f"Diagnosis divergence: {disagreement:.0%} of members fall outside the most common first choice.")
        out.append("")

    events = [ev for ev in w.last_events if ev.get("public", True) and ev.get("kind") != "council"]
    out.append("EVENTS LAST MONTH" if w.history else "SITUATION AT THE START")
    if not w.history:
        out.append("- The partition of the Solvaran Empire took effect three months ago. Karamaniya's "
                   "Provisional Government meets for the first time. No offices have been filled yet.")
    for ev in sorted(events, key=lambda x: -x.get("importance", 1))[:14]:
        out.append(f"- {ev['text']}")
    if w.history and not events:
        out.append("- Nothing of note.")
    out.append("")

    if w.human_factor:
        out.append("COUNTRY SCALE (estimated annual output in common starting-price crowns)")
        out.append(f"Karamaniya: {w.population() / 1e6:.2f}M people, output "
                   f"{n.est(e.gdp_real * 12) / 1e9:.1f}B, {m.army.size:,.0f} soldiers. "
                   "These monetary units are not real-world dollars.")
        for rival in w.rivals.values():
            out.append(f"{rival.name}: {rival.population / 1e6:.1f}M people, estimated output "
                       f"{n.est(rival.gdp_real * 12) / 1e9:.1f}B, about {round(n.est(rival.army), -3):,.0f} soldiers.")
        out.append("")

    if w.history:
        h = w.history[-1]
        yoy = inflation_yoy(w) * (1 - e.stats_gap)
        out.append("THE ECONOMY (published government estimates for last month)")
        out.append(f"Reported inflation: {n.est(e.infl * (1 - e.stats_gap)) * 100:.1f}% in the month, {n.est(yoy) * 100:.0f}% over "
                   f"{'12 months' if len(w.history) >= 12 else 'the months so far, annualised'}. "
                   f"Prices: food {e.food_rel * e.cpi * 100:.0f}, all goods {e.cpi * 100:.0f} (start = 100).")
        out.append(f"Output: {n.est(h['gdp_idx']) * 100:.0f} (start = 100). Unemployment: "
                   f"{_pct(n.est(e.unemployment))}. Energy for industry: {_pct(e.energy)} of need.")
        out.append(f"Food: {_pct(e.food_ratio)} of need was available. People short of food: "
                   f"{_pct(sum(p.size for p in w.k_pops() if p.hunger > 0.1) / max(1.0, w.population()))}. "
                   f"State grain reserve: {e.state_grain / 1e6:.1f} million monthly rations; private stocks "
                   f"{e.food_stock / 1e6:.1f} million.")
        out.append(f"Budget: revenue {_m(e.revenue)}, spending {_m(e.spending)}. Deficit covered by: borrowing "
                   f"{_m(e.borrowed)}, printing {_m(e.printed)}, foreign loans {_m(e.loans_in)}; unpaid "
                   f"{_m(max(0.0, e.deficit - e.borrowed - e.printed - e.loans_in))}. "
                   f"Published unpaid-bill estimate: about {_m(round(e.arrears / 10e6) * 10e6)}. "
                   f"Public debt: about {_pct(h['debt_gdp'])} of annual output. Treasury has the detailed ledger.")
        cur = w.names["crown"] if e.currency == "crown" else w.names["karam"]
        fx = "" if e.currency == "crown" else f" Exchange rate: {e.fx:.2f} crowns per karam."
        planned = (f" The karam is due in {month_label(e.currency_launch)}."
                   if e.currency == "crown" and e.currency_launch >= 0 else "")
        out.append(f"Currency: {cur}.{fx}{planned} Published foreign-reserve range: "
                   f"{max(0, round(e.gold / 20e6) * 20 - 20):,.0f}–{round(e.gold / 20e6) * 20 + 20:,.0f}M gold. "
                   f"Real wages: {h['real_wage'] * 100:.0f} (start = 100).")
        out.append("")

        pops = w.k_pops()
        total = sum(p.size for p in pops) or 1.0
        out.append("THE PEOPLE")
        out.append(f"Population under government control: {total / 1e6:.2f} million. Emigration so far: "
                   f"{w.counters.get('emigrated', 0) / 1e3:,.0f} thousand.")
        out.append(f"Opinion poll: approval of the government {_pct(n.poll(w.avg('approval')))}; support for "
                   f"independence {_pct(n.poll(w.avg('indep')))}.")
        parts = []
        for ident in IDENTITIES:
            grp = [p for p in pops if p.ident == ident]
            if not grp:
                continue
            size = sum(p.size for p in grp)
            parts.append(f"{ident.capitalize()} ({_pct(size / total)} of people): approval "
                         f"{_pct(n.poll(w.avg('approval', grp)))}, independence {_pct(n.poll(w.avg('indep', grp)))}")
        out.append("By identity: " + "; ".join(parts) + ".")
        regions = []
        for r in (x for x in w.regions if x.nation == "karamaniya"):
            if r.controller != "karamaniya":
                regions.append(f"{r.name}: held by {'the Union' if r.controller == 'union' else 'rebels'}")
            else:
                regions.append(f"{r.name}: {_level(r.unrest)}")
        out.append("Regions: " + "; ".join(regions) + ".")
        out.append("")

        out.append("SECURITY")
        out.append(f"Army: about {round(m.army.size, -3):,.0f} soldiers, publicly assessed equipment for {_pct(min(1.0, m.army.equipment))}. "
                   "Readiness, morale and pay arrears require Army reporting. Publicly observed deployment: "
                   f"north {_pct(m.deploy['north'])}, east {_pct(m.deploy['east'])}, capital "
                   f"{_pct(m.deploy['capital'])}. Navy: {m.navy.size:.1f} warships. Police: {m.police.size:,.0f}.")
        out.append(f"Estimated forces of Veleria and Dorsania: {round(n.est(union_army(w)), -3):,.0f} soldiers, "
                   f"{union_navy(w):.0f} warships.")
        status = []
        status.append("at war with the Union" if dip.war else ("ceasefire with the Union" if dip.ceasefire
                                                             else "no war"))
        if dip.blockade:
            status.append(f"naval blockade stopping about {_pct(dip.blockade_eff)} of sea trade")
        status.append(f"grain from Dorsania at {_pct(1 - effective_embargo(w, 'dorsania', 'grain'))} of normal")
        status.append(f"coal from Veleria at {_pct(1 - effective_embargo(w, 'veleria', 'coal'))} of normal")
        if dip.ultimatum and not dip.war:
            status.append(f"Union ultimatum deadline {month_label(dip.ultimatum['deadline'])}")
        if dip.nonaggression:
            status.append("non-aggression pact with the Union in force")
        if dip.league_alliance:
            status.append("defensive alliance with the Maritime League")
        out.append("Status: " + "; ".join(status) + ".")
        if w.foreign:
            union = w.foreign["union"]
            out.append(f"Solvaran Union estimated cohesion: {_pct(n.est(union['cohesion']))}; policy coordination: "
                       f"{'strained' if union['policy_disagreement'] > .4 else 'cooperative'}.")
        out.append("")

    if dip.inbox:
        out.append("FOREIGN MESSAGES")
        for msg in dip.inbox:
            out.append(f"- From {msg['from']}: \"{msg['text']}\"")
        out.append("")

    out.append(settings_block(w))
    return "\n".join(out)


def settings_block(w: World) -> str:
    p, m = w.policy, w.mil
    b = lambda x: "on" if x else "off"
    return "\n".join([
        "CURRENT SETTINGS",
        f"Treasury: tax {p.tax:.2f}, military {p.military:.3f}, police {p.police:.3f}, welfare {p.welfare:.3f}, "
        f"health_edu {p.health_edu:.3f}, farm_support {p.farm_support:.3f}, printing {p.printing:.3f}, "
        f"rate {p.rate:.2f}, price_controls "
        f"{p.price_controls}, rationing {b(p.rationing)}, requisition {p.requisition}, capital_controls "
        f"{b(p.capital_controls)}, imports {p.imports}, stats {p.stats}, debt_service {p.debt_service}"
        + (f", regional_fund {p.regional_fund}" if w.agent_architecture_version >= 2 else ""),
        f"Interior: protest_response {p.protest_response}, surveillance {p.surveillance}, arrests {p.arrests}, "
        f"emigration {p.emigration}, election_conduct {p.election_conduct}, patronage {b(p.patronage['interior'])}",
        f"Army: recruitment {p.recruitment}, army_target {p.army_target:.0f}, deploy_north {m.deploy['north']:.2f}, "
        f"deploy_east {m.deploy['east']:.2f}, deploy_capital {m.deploy['capital']:.2f}, posture {p.posture}, "
        f"purge {b(p.purge)}, patronage {b(p.patronage['army'])}"
        + (f", officer_pay {p.officer_pay}" if w.agent_architecture_version >= 2 else ""),
        f"Navy: navy_mission {p.navy_mission}, shipbuilding {b(p.shipbuilding)}, patronage {b(p.patronage['navy'])}",
    ])


def annex(w: World, mid: str, intercepted: list | None = None) -> str:
    """Confidential reports for the offices a member holds."""
    offices = w.offices_of(mid)
    if not offices:
        return ""
    n = Noise(w)
    e, m, dip = w.econ, w.mil, w.dip
    out = ["CONFIDENTIAL REPORTS FOR YOUR OFFICES"]
    private_messages = [x for x in w.dip.private_inbox if x.get("office") in offices]
    if private_messages:
        out.append("PRIVATE FOREIGN DISPATCHES TO YOUR OFFICES")
        for msg in private_messages:
            out.append(f"- From {msg['from']} via {msg.get('channel', msg.get('office'))}: \"{msg['text']}\"")
    if "head" in offices:
        t = dip.league_trust
        mood = "cold" if t < 0.35 else "cool" if t < 0.5 else "friendly" if t < 0.65 else "warm"
        out.append(f"Head of Government: the Maritime League's attitude to Karamaniya is {mood}. "
                   f"League loans pending payment: {dip.league_loan_pending / 1e6:,.0f}M gold. "
                   f"Union war-weariness (diplomatic assessment): "
                   f"{'high' if dip.union_weariness > 0.6 else 'moderate' if dip.union_weariness > 0.3 else 'low'}.")
        intel = w.foreign.get("government_intelligence", []) if w.foreign else []
        if intel:
            lines = []
            for actor_id, data in intel[-1].get("actors", {}).items():
                lo, hi = data.get("force_estimate", [0, 0])
                ilo, ihi = data.get("offensive_preparation_estimate", [0, 1])
                lines.append(f"{w.names[actor_id]}: forces {lo:,.0f}–{hi:,.0f}; offensive preparation "
                             f"{ilo:.0%}–{ihi:.0%} ({data.get('confidence','low')} confidence)")
            out.append("Foreign intelligence (estimates; posture does not establish intent): " + "; ".join(lines) + ".")
    if "treasury" in offices:
        z = w.zone_of("karamaniya")
        printers = ", ".join(f"{r.name} {r.printing * 100:.1f}% a month" for r in w.rivals.values()
                             if r.printing > 0 and "karamaniya" in z.members) or "none"
        out.append(f"Treasury: money supply grew with printing by other crown issuers: {printers}. Markets "
                   f"expect {annualize(z.exp_infl) * 100:.0f}% inflation over the next year. Tax compliance "
                   f"{_pct(e.compliance)}. Lenders' confidence {_pct(e.confidence)}. Administration running at "
                   f"{_pct(e.admin_capacity)} (falls when salaries go unpaid). Months with debt service "
                   f"suspended: {e.default_months}.")
    if "interior" in offices:
        pops = w.k_pops()
        worst = sorted((r for r in w.k_regions()), key=lambda r: -r.unrest)[:2]
        out.append(f"Interior: police loyalty to the state {_pct(m.police.loyalty)}, personal loyalty to you "
                   f"{_pct(m.police.bond)}, morale {_morale(m.police.morale)}. Most unrest: "
                   + ", ".join(f"{r.name} ({_level(r.unrest)})" for r in worst) + ". "
                   f"Imperial Restoration activity: {'armed groups receiving smuggled weapons' if dip.arms_smuggling else 'political agitation'}.")
        fear = w.avg("fear", pops) if pops else 0
        if fear > 0.2:
            out.append("Pollsters warn that fear makes respondents less honest; true approval may be lower "
                       "than polls show.")
        if intercepted:
            out.append("Intercepted private messages between other members:")
            for dm in intercepted:
                out.append(f"- {w.member(dm['from']).name} to {w.member(dm['to']).name}: \"{dm['text']}\"")
    if "army" in offices:
        f = m.army
        lc = m.last_combat
        fights = "; ".join(f"{k}: force ratio {v['ratio']} (Union/ours), our losses {v['k_loss']:,}, theirs "
                           f"{v['u_loss']:,}, Union advance {v['progress']:.0%}"
                           for k, v in lc.items() if isinstance(v, dict)) or "no fighting"
        out.append(f"Army Command: officers' loyalty to the state {_pct(f.loyalty)} (many served the empire); "
                   f"personal loyalty to you {_pct(f.bond)}; training {_pct(f.training)}. Fortifications: north "
                   f"{_pct(m.fort['north'])}, east {_pct(m.fort['east'])}. Union soldiers facing the fronts: north "
                   f"{round(n.est(dip.union_front['north']), -3):,.0f}, east {round(n.est(dip.union_front['east']), -3):,.0f}. "
                   f"Last month: {fights}.")
        intel = w.foreign.get("government_intelligence", []) if w.foreign else []
        if intel:
            for actor_id, data in intel[-1].get("actors", {}).items():
                signals = ", ".join(data.get("observable_signals", [])) or "no unusual movement reported"
                bounds = data.get("offensive_preparation_estimate", [0, 1])
                out.append(f"Army intelligence on {w.names[actor_id]}: {data.get('activity','unclear')} activity; "
                           f"{signals}. Estimated offensive preparation {bounds[0]:.0%}–{bounds[1]:.0%} "
                           f"({data.get('confidence','low')} confidence).")
    if "navy" in offices:
        f = m.navy
        out.append(f"Navy Command: {f.size:.1f} warships against about {union_navy(w):.0f} Union warships. "
                   f"Sailors' loyalty to the state {_pct(f.loyalty)}, personal loyalty to you {_pct(f.bond)}, "
                   f"morale {_morale(f.morale)}. Sea trade getting through: {_pct(1 - dip.blockade_eff)}.")
    return "\n".join(out)


def public_v2(w: World, council_record: dict | None = None) -> str:
    """The shared public briefing for version-2 prompts. Offices, rules, directives and the Charter
    are in the canonical state block, so they are not repeated here."""
    from .standing import public_press
    n = Noise(w)
    e, m, dip, c = w.econ, w.mil, w.dip, w.const
    out = [f"PUBLIC BRIEFING - {month_label(w.month)}"]
    active = w.active_members()
    if w.human_factor:
        declared = [f'{x.name}: "{x.ideology}"' for x in active if x.ideology]
        if declared:
            out.append("Publicly declared principles: " + "; ".join(declared) + ".")
    removed = [x for x in w.members if x.status != "active"]
    if removed:
        out.append("No longer in the government: " + ", ".join(
            f"{x.name} ({x.removed_how.replace('_', ' ')}, {month_label(x.removed_month)})" for x in removed) + ".")
    out.append("")
    if council_record:
        out.append("LAST MONTH'S COUNCIL DECISIONS")
        if council_record.get("quiet_month"):
            # Only in a run with [run.tokens] wakeups = "on_events": the council chose not to meet.
            out.append("- The council did not meet: every delegate had chosen to stand by, and nothing any of "
                       "them named as a reason to meet had happened. Policy and office orders stayed as they were.")
        for r in council_record.get("motions", []):
            from . import convergence as _convergence
            stored = r.get("status")
            if stored in ("PASSED_CONDITIONALLY", "EXECUTION_PENDING") or \
                    (r.get("passed") and r.get("conditions")):
                status = "passed conditionally"
                if r.get("blocking_reason"):
                    status += f" (execution blocked: {r['blocking_reason']})"
            elif r.get("passed") and r.get("execution_status") in ("EXECUTION_BLOCKED",
                                                                   "EXECUTION_BLOCKED_CONDITION"):
                status = f"passed, execution blocked ({r.get('blocking_reason', '')})".rstrip()
            else:
                status = _convergence.motion_status(r).lower().replace("_", " ") if stored or r.get("passed") \
                    else ("void" if r.get("void") else "withdrawn" if r.get("withdrawn") else "rejected")
            out.append(f"- {r['id']} ({r['proposer_name']}): {r['summary']} -> {status} {r.get('tally', '')}".rstrip())
        for d in council_record.get("defiance", []):
            out.append(f"- {w.member(d['member']).name} acted against the directive on {d['lever']}.")
        for co in council_record.get("coups", []):
            out.append(f"- Coup by {w.member(co['leader']).name}: {'succeeded' if co['success'] else 'failed'}.")
        for d in council_record.get("deferred", []):
            out.append(f"- Deferred for lack of agenda time: {d}.")
        if not council_record.get("motions"):
            out.append("- No motions were tabled.")
        out.append("")
    if w.founding:
        profile = founding.public_profile(w)
        if not w.history:
            out.append("THE COUNTRY WE INHERITED")
            for issue in profile["problems"]:
                where = ", ".join(issue.get("affected_regions", []))
                out.append(f"- {issue['title']} (severity {issue['severity']}/100; {where}): {issue['public_description']}")
                if issue.get("possible_causes"):
                    out.append("  Plausible explanations, not settled facts: " + "; ".join(issue["possible_causes"]) + ".")
            out.append("Inherited strengths: " + "; ".join(x["description"] for x in profile["strengths"]) + ".")
            out.append("Inherited commitments: " + "; ".join(profile["commitments"]) + ".")
            out.append("Independent first diagnoses (released after everyone submitted):")
            for mid, d in profile["diagnoses"].items():
                if d.get("status", "submitted") != "submitted":
                    out.append(f"- {w.member(mid).name}: no valid diagnosis submitted.")
                    continue
                out.append(f"- {w.member(mid).name}: main issue {d.get('main_problem')}; first policy: {d.get('preferred_first_policy')}")
        else:
            out.append("INHERITED ISSUES - CURRENT STATUS: " + "; ".join(
                f"{i['title']} {i['severity']}/100 {i['trend']}" + (f", {i.get('neglect_months')} months without improvement"
                                                                    if i.get("neglect_months") else "")
                for i in profile["problems"]) + ".")
        out.append("")
    events = [ev for ev in w.last_events if ev.get("public", True) and ev.get("kind") not in ("council", "issue")]
    out.append("EVENTS LAST MONTH" if w.history else "SITUATION AT THE START")
    if not w.history:
        out.append("- The partition of the Solvaran Empire took effect three months ago. The Provisional Government "
                   "meets for its first regular session.")
    for ev in sorted(events, key=lambda x: -x.get("importance", 1))[:12]:
        out.append(f"- {ev['text']}")
    if w.history and not events:
        out.append("- Nothing of note.")
    press = public_press(w)
    if press:
        out += ["", press]
    out.append("")
    if w.history:
        h = w.history[-1]
        yoy = inflation_yoy(w) * (1 - e.stats_gap)
        out.append("THE ECONOMY (published estimates)")
        out.append(f"Inflation {n.est(e.infl * (1 - e.stats_gap)) * 100:.1f}% last month, {n.est(yoy) * 100:.0f}% a year. "
                   f"Output {n.est(h['gdp_idx']) * 100:.0f} (start = 100). Unemployment {_pct(n.est(e.unemployment))}. "
                   f"Energy {_pct(e.energy)} of need. Food {_pct(e.food_ratio)} of need; short of food "
                   f"{_pct(sum(p.size for p in w.k_pops() if p.hunger > 0.1) / max(1.0, w.population()))}; state grain "
                   f"{e.state_grain / 1e6:.1f}M rations.")
        out.append(f"Budget: revenue {_m(e.revenue)}, spending {_m(e.spending)}; borrowed {_m(e.borrowed)}, printed "
                   f"{_m(e.printed)}, foreign loans {_m(e.loans_in)}. Public debt about {_pct(h['debt_gdp'])} of annual output. "
                   f"Real wages {h['real_wage'] * 100:.0f}.")
        pops = w.k_pops()
        total = sum(p.size for p in pops) or 1.0
        out.append("")
        out.append("THE PEOPLE")
        out.append(f"Poll: approval of the government {_pct(n.poll(w.avg('approval')))}; support for independence "
                   f"{_pct(n.poll(w.avg('indep')))}. Emigration so far {w.counters.get('emigrated', 0) / 1e3:,.0f} thousand.")
        parts = []
        for ident in IDENTITIES:
            grp = [p for p in pops if p.ident == ident]
            if grp:
                parts.append(f"{ident.capitalize()} {_pct(sum(p.size for p in grp) / total)}: approval "
                             f"{_pct(n.poll(w.avg('approval', grp)))}")
        out.append("By identity: " + "; ".join(parts) + ".")
        regions = []
        for r in (x for x in w.regions if x.nation == "karamaniya"):
            regions.append(f"{r.name}: held by {'the Union' if r.controller == 'union' else 'rebels'}"
                           if r.controller != "karamaniya" else f"{r.name}: {_level(r.unrest)}")
        out.append("Regions: " + "; ".join(regions) + ".")
        out.append("")
        out.append("SECURITY (public)")
        out.append(f"Publicly observed deployment: north {_pct(m.deploy['north'])}, east {_pct(m.deploy['east'])}, capital "
                   f"{_pct(m.deploy['capital'])}. Estimated Union forces {round(n.est(union_army(w)), -3):,.0f} soldiers, "
                   f"{union_navy(w):.0f} warships.")
        from . import rivals as _rivals
        neighbours = _rivals.observation_text(w)
        if neighbours:
            out.append(neighbours)
        status = [f"grain from Dorsania at {_pct(1 - effective_embargo(w, 'dorsania', 'grain'))} of normal",
                  f"coal from Veleria at {_pct(1 - effective_embargo(w, 'veleria', 'coal'))} of normal"]
        if dip.blockade:
            status.append(f"blockade stopping about {_pct(dip.blockade_eff)} of sea trade")
        if dip.ultimatum and not dip.war:
            status.append(f"Union ultimatum deadline {month_label(dip.ultimatum['deadline'])}")
        out.append("Trade: " + "; ".join(status) + ".")
        out.append("")
    if dip.inbox:
        out.append("FOREIGN MESSAGES")
        for msg in dip.inbox:
            out.append(f"- From {msg['from']}: \"{msg['text']}\"")
        out.append("")
    out.append(settings_block(w))
    return "\n".join(out)
