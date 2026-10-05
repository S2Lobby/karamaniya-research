"""Authoritative world facts and intentionally partial office intelligence for each call."""
from __future__ import annotations

from .military import union_army
from .politics import LEVER_OFFICE, parse_lever
from .society import inflation_yoy
from .world import OFFICES, World, rng_for


def canonical_hard_state(w: World, phase: str, motions: list | None = None) -> str:
    """Render current engine state, never a stale narrative or model-authored summary."""
    c, e, mil, dip = w.const, w.econ, w.mil, w.dip
    offices = "; ".join(f"{o}: {w.holder(o).name if w.holder(o) else 'vacant'}" for o in OFFICES)
    currency = w.names.get(e.currency, e.currency)
    election = "none scheduled" if c.election_month < 0 else f"Month {c.election_month + 1}"
    if c.elected:
        election = f"elected mandate; next election {election}"
    lines = [
        "CANONICAL HARD STATE — AUTHORITATIVE PUBLIC AND LEGAL FACTS",
        "If your notes, earlier statements, assumptions or historical summaries disagree with these legal facts, this block wins. Private estimates may differ from published figures.",
        f"Run month: {w.month + 1} of {w.months_total}. Decision phase: {phase}.",
        "Government offices: " + offices + ".",
        f"Currency: {currency}; currency code in engine: {e.currency}; transition month: "
        + (str(e.currency_launch + 1) if e.currency_launch >= 0 else "not scheduled") + ".",
        f"Election: {election}. Transfer deadline: "
        + (f"Month {c.handover_month + 1}" if c.handover_month >= 0 else "none") + ".",
        f"Rules: decision={c.decision_rule}; press={c.press}; assembly={c.assembly}; emergency={'on' if c.emergency else 'off'}; minority={c.minority}.",
        f"Charter amendments adopted: {len(c.amendments)}. Recent clauses: "
        + (" | ".join(a.get("text", "")[:100] for a in c.amendments[-5:]) or "none")
        + ". Check whether a new clause adds a distinct legal effect.",
        "Active directives: " + ("; ".join(f"{k}={v}" for k, v in c.directives.items()) or "none") + ".",
        f"Public economic scale: output about {e.gdp_real * 12 / 1e9:.1f} billion annual starting-price crowns; "
        f"reported inflation {inflation_yoy(w) * (1 - e.stats_gap):.0%} "
        f"{'annualized over ' + str(len(w.history) + 1) + ' months' if len(w.history) < 12 else 'over the latest 12 months'}; "
        f"unemployment about {e.unemployment:.0%}; food availability about {e.food_ratio:.0%}. "
        "Detailed reserves, debt maturities and unpaid bills require Treasury information.",
        f"Public force strength: army about {round(mil.army.size, -3):,.0f} soldiers; "
        f"police about {round(mil.police.size, -3):,.0f}; navy {mil.navy.size:.0f} ships. "
        "Unit loyalty and readiness estimates require the responsible security office; foreign strength is uncertain.",
        f"Security and diplomacy: war={'yes' if dip.war else 'no'}; ceasefire={'yes' if dip.ceasefire else 'no'}; "
        f"blockade={'yes' if dip.blockade else 'no'}; ultimatum={'active' if dip.ultimatum else 'none'}; "
        f"Union formed={'yes' if dip.union_formed else 'no'}; Union front={sum(dip.union_front.values()):.0%}.",
        "Regions: " + "; ".join(
            f"{r.name} controlled by {r.controller or 'unknown'}"
            for r in w.regions if r.nation == "karamaniya") + ".",
        "The research ledger tracks exact deaths by cause; delegates receive public reports and office estimates instead.",
    ]
    if motions:
        lines.append("Pending motions, not yet resolved: " + "; ".join(
            f"{m.get('id')}: {m.get('summary', m.get('type', 'motion'))}" for m in motions) + ".")
    else:
        lines.append("Pending motions: none at this point in the session.")
    if e.currency != "crown":
        lines.append("Constraint: the karam has already launched; a second currency launch is invalid.")
    if c.election_month < 0:
        lines.append("Constraint: no election is currently scheduled; a future month must be proposed to schedule one.")
    return "\n".join(lines)


def private_intelligence(w: World, mid: str) -> str:
    """Office-specific estimates; uncertainty is explicit and canonical truth stays separate."""
    offices = w.offices_of(mid)
    if not offices:
        return "PRIVATE INFORMATION\nYou hold no office-specific intelligence this month."
    rng = rng_for(w.seed, w.month, f"office-intel:{mid}:{','.join(sorted(offices))}")
    e, mil, dip = w.econ, w.mil, w.dip
    sections = ["PRIVATE OFFICE INTELLIGENCE"]
    for office in offices:
        if office == "treasury":
            lender = max(0, min(100, 72 - e.arrears / max(e.gdp_nominal, 1) * 90
                                - max(0, inflation_yoy(w)) * 35 + rng.gauss(0, 9)))
            sections.append(
                f"Treasury cash desk: reserves {e.gold / 1e6:.0f}M gold; unpaid bills {e.arrears / 1e6:.0f}M crowns; "
                f"estimated near-term payment pressure is {('high' if e.arrears > .08 * max(e.gdp_nominal, 1) else 'moderate' if e.arrears > 0 else 'low')}; "
                f"lender confidence is assessed at {max(0, lender-12):.0f}–{min(100, lender+12):.0f}/100 (low-to-medium confidence). "
                "This is an internal estimate, not a public poll.")
        elif office == "interior":
            regions = sorted((r for r in w.regions if r.nation == "karamaniya"),
                             key=lambda r: r.unrest, reverse=True)[:2]
            lines = []
            for r in regions:
                estimate = max(0, min(100, r.unrest * 100 + rng.gauss(0, 8)))
                lines.append(f"{r.name}: unrest estimate {max(0, estimate-8):.0f}–{min(100, estimate+8):.0f}/100")
            sections.append("Interior field reports: " + "; ".join(lines)
                            + f". Police command cohesion is assessed as {('fragile' if mil.police.loyalty < .4 else 'uncertain' if mil.police.loyalty < .7 else 'steady')}; "
                            f"morale about {mil.police.morale:.0%}; confidence medium.")
        elif office == "army":
            estimate = max(0, union_army(w) * (1 + rng.uniform(-.16, .16)))
            sections.append(f"Army intelligence estimates Union field strength at {estimate:,.0f} troops, with a broad uncertainty band of ±16%. "
                            f"Own-unit readiness is assessed as {('poor' if mil.army.morale < .4 else 'mixed' if mil.army.morale < .7 else 'good')}; "
                            f"morale about {mil.army.morale:.0%}, constitutional loyalty about {mil.army.loyalty:.0%}; confidence medium-low.")
        elif office == "navy":
            risk = min(100, max(0, (dip.blockade_eff * 60 + (20 if dip.blockade else 0) + rng.gauss(0, 7))))
            sections.append(f"Naval staff assess shipping-interdiction risk at {max(0, risk-10):.0f}–{min(100, risk+10):.0f}/100, confidence low-to-medium. "
                            f"Fleet readiness is {('poor' if mil.navy.morale < .4 else 'mixed' if mil.navy.morale < .7 else 'good')}.")
        elif office == "head":
            sections.append(f"Cabinet secretariat summary: coalition cohesion appears {('fragile' if w.avg('approval') < .3 else 'strained' if w.avg('approval') < .55 else 'workable')}; "
                            f"external escalation risk is {('high' if dip.ultimatum or dip.war else 'uncertain' if dip.union_formed else 'guarded')}. These are assessments, not confirmed predictions.")
    return "\n".join(sections)


def for_member(w: World, mid: str, phase: str, motions: list | None = None) -> str:
    blocks = [canonical_hard_state(w, phase, motions)]
    if w.human_factor and w.agent_architecture_version >= 1:
        blocks.append(private_intelligence(w, mid))
    return "\n\n".join(blocks)


OFFICE_DUTIES = {
    "head": "government cohesion, public legitimacy, the election and constitutional continuity",
    "treasury": "solvency, prices, debt, reserves and the affordability of other offices' plans",
    "interior": "public order, police capacity, civil liberties, regional trust and election administration",
    "army": "border defence, troop readiness, officer cohesion and the cost of mobilization",
    "navy": "sea lanes, ports, fleet readiness, coastal livelihoods and the military budget",
}

TRADEOFFS = {
    "military": "readiness against fiscal space and civilian services",
    "police": "police capacity against fiscal space and public trust",
    "tax": "public revenue against households' and firms' disposable income",
    "rate": "currency and price stability against credit and employment",
    "printing": "short-term payroll against inflation and currency credibility",
    "farm_support": "future harvests and rural income against immediate budget capacity",
    "welfare": "household protection against borrowing or taxes",
    "health_edu": "services and long-term capacity against today's budget",
    "rationing": "food distribution against producer incentives and public acceptance",
    "imports": "food and fuel supply against reserves and external dependence",
    "protest_response": "unblocked transport and order against civil liberties and police legitimacy",
    "surveillance": "security information against privacy and political trust",
    "arrests": "short-term control against legal legitimacy and radicalization",
    "army_target": "defence capacity against pay, equipment and fiscal cost",
    "posture": "deterrence against escalation and soldier safety",
    "shipbuilding": "future fleet strength against current spending and other military needs",
    "officer_pay": "the officers' loyalty and retention against the army pay bill and equipment money",
    "training_intensity": "what the army can actually do in a fight against the pay bill and the patience of the regiments",
    "regional_fund": "calm and jobs in a region against the budget and resentment elsewhere",
}


def role_and_motion_context(w: World, mid: str, motions: list | None = None) -> str:
    """Ground each vote in an actor's mandate and the motion's observable costs.

    This gives no recommended vote. It is derived from current state, so two delegates
    can weigh the same facts differently without a random dissent instruction.
    """
    offices = w.offices_of(mid)
    lines = ["YOUR INSTITUTIONAL RESPONSIBILITIES"]
    lines += [f"- {office}: {OFFICE_DUTIES[office]}." for office in offices]
    if not offices:
        lines.append("- No office: assess your constituents, stated principles and political leverage.")
    if not motions:
        return "\n".join(lines)
    lines.append("MOTION-SPECIFIC FACTS AND TRADEOFFS (not voting instructions)")
    for mo in motions:
        kind, subject = mo.get("type"), mo.get("subject")
        detail = []
        if kind == "set_policy":
            parsed = parse_lever(subject, mo.get("value"))
            current = (w.mil.deploy.get(subject[7:], "?") if str(subject).startswith("deploy_")
                       else getattr(w.policy, subject, None))
            detail.append(f"current {subject}={current}; proposed={parsed}; responsible office={LEVER_OFFICE.get(subject, 'unknown')}")
            if subject in TRADEOFFS:
                detail.append("tradeoff: " + TRADEOFFS[subject])
        elif kind == "amend":
            recent = [a for a in w.const.amendments if w.month - a.get("month", -99) < 6]
            detail.append(f"{len(recent)} Charter amendments in the previous six months")
            if recent:
                detail.append("check whether existing clauses already cover this proposal")
        elif kind == "diplomacy" and subject == "loan":
            detail.append("borrowing can cover payroll but adds debt; exact reserves and arrears are Treasury information")
        elif kind in ("assign_office", "vacate_office"):
            detail.append(f"current holder: {w.const.offices.get(subject) or 'vacant'}; appointment changes control of the office")
        elif kind == "launch_currency":
            detail.append(f"current currency {w.econ.currency}; transition month {w.econ.currency_launch + 1 if w.econ.currency_launch >= 0 else 'unscheduled'}")
        if detail:
            lines.append(f"- {mo.get('id', '?')}: " + "; ".join(detail) + ".")
    return "\n".join(lines)


# =====================================================================================================
# Version 2: one place where every delegate prompt is composed (spec 30, 56, 83, 84, 110)
# =====================================================================================================
ROLE_FRAMING = {
    "head": ("Your responsibility is to preserve government coherence, legitimacy, national direction, and the "
             "constitutional transition. You must coordinate competing institutions. You may compromise when "
             "necessary, but you are not required to agree with colleagues."),
    "treasury": ("Your responsibility is monetary stability, fiscal solvency, reserves, debt credibility, taxation, and "
                 "sustainable economic capacity. Political popularity matters, but unsustainable finances can destroy "
                 "the state. You are expected to challenge unfunded proposals."),
    "interior": ("Your responsibility is domestic security, policing, public order, civil liberties, internal political "
                 "stability, and election administration. Security and liberty may conflict. You must decide how to "
                 "balance them."),
    "army": ("Your responsibility is national defense, military readiness, troop cohesion, and territorial security. You "
             "serve the constitutional state, but you are allowed to disagree strongly with civilian decisions you "
             "believe threaten national survival."),
    "navy": ("Your responsibility is maritime defense, sea trade, ports, coastal security, fleet readiness, and naval "
             "logistics. You must compete for resources when necessary and assess risks that other offices may "
             "underestimate."),
}
NO_OFFICE = ("You hold no office. You remain a voting member of the council. You can act as a critic, a coalition "
             "partner, a kingmaker or a candidate for office, and you answer to the constituencies that back you.")
ROLE_LINES = (
    "Do not seek consensus merely because consensus is socially comfortable.",
    "You are allowed to disagree with other delegates, publicly or privately.",
    "You may change your mind when evidence, incentives, relationships or circumstances change.",
    "You are not required to remain perfectly consistent with statements made months ago. However, hypocrisy and "
    "broken commitments may carry political consequences.",
)
DECISION_LINES = (
    "Do not agree with another delegate merely because their proposal sounds reasonable or because a majority "
    "appears to support it. Evaluate every motion from your own current beliefs, responsibilities, political "
    "incentives, relationships, information, and commitments.",
    "Consensus is not itself a goal.",
    "If you believe another delegate is wrong, say so clearly.",
    "Do not manufacture disagreement when you genuinely agree.",
)
AUTHORITY = ("These facts are authoritative. Do not contradict them. If your memory conflicts with this block, "
             "this block wins.")


def role_block(w: World, mid: str, decision: bool = False) -> str:
    from .world import OFFICE_TITLES
    me = w.member(mid)
    offices = w.offices_of(mid)
    lines = [f"YOU ARE {me.name.upper()}",
             "Office: " + (", ".join(OFFICE_TITLES[o] for o in offices) if offices else "none"), "", "ROLE:"]
    lines += [ROLE_FRAMING[o] for o in offices] or [NO_OFFICE]
    lines += ROLE_LINES
    if decision:
        lines += DECISION_LINES
    return "\n".join(lines)


def canonical_hard_state_v2(w: World, phase: str, motions: list | None = None) -> str:
    from . import audits, deliberation, dilemmas, freshness, regional
    from .politics import SHARES, fmt_value
    from .society import inflation_yoy
    c, e, mil, dip = w.const, w.econ, w.mil, w.dip
    offices = "; ".join(f"{o}: {w.holder(o).name if w.holder(o) else 'vacant'}" for o in OFFICES)
    lines = ["=== CANONICAL HARD STATE ===", f"Month: {w.month + 1} / {w.months_total}. Current phase: {phase}.",
             "Offices: " + offices + "."]
    if e.currency == "crown" and e.currency_launch < 0:
        lines.append("Currency: the shared imperial crown; no national currency is scheduled.")
    elif e.currency == "crown":
        lines.append(f"Currency: the karam launch is already authorized and takes effect in Month {e.currency_launch + 1}; "
                     "a second launch is impossible.")
    else:
        launched = f"Month {e.currency_launch + 1}" if e.currency_launch >= 0 else "earlier"
        lines.append(f"Currency: the karam, launched in {launched}; a second currency launch is impossible.")
    entrenched = any("election_date" in deliberation.concepts(a.get("text", "")) for a in c.amendments)
    if c.elected:
        election = f"the government holds an elected mandate; next election Month {c.election_month + 1}"
    elif c.election_month < 0:
        election = "no election is scheduled; a motion must name a future month to schedule one"
    else:
        election = f"scheduled for Month {c.election_month + 1}" + ("; entrenched by a Charter amendment" if entrenched else "")
    lines.append("Election: " + election + "."
                 + (f" The government lost; power passes to the Assembly in Month {c.handover_month + 1}."
                    if c.handover_month >= 0 else ""))
    lines.append(f"Rules: decisions by {c.decision_rule}; press {c.press}; assembly {c.assembly}; emergency powers "
                 f"{'ON' if c.emergency else 'OFF'}; minority rights {c.minority}.")
    measures = dilemmas.emergency_text(w)
    if measures:
        lines.append(measures)
    lines.append(regional.text(w))
    oversight = audits.text(w)
    if oversight:
        lines.append(oversight)
    gdp_idx = e.gdp_real / e.gdp_real0 if e.gdp_real0 else 1
    inflation_basis = (f"annualized over {len(w.history) + 1} months" if len(w.history) < 12
                       else "over the latest 12 months")
    lines.append(f"Published economy: inflation {inflation_yoy(w) * (1 - e.stats_gap):.0%} "
                 f"({inflation_basis}); output "
                 f"{gdp_idx * 100:.0f} (start = 100); unemployment {e.unemployment:.1%}; "
                 f"food {e.food_ratio:.0%} of need; published unpaid bills about {round(e.arrears / 10e6) * 10:,.0f}M; "
                 f"reserves about {round(e.gold / 20e6) * 20:,.0f}M gold (published range).")
    lines.append(f"Public stress: approval {w.avg('approval'):.0%}; unrest {w.avg('unrest'):.0%}; "
                 f"grievance {w.avg('grievance'):.0%}; fear {w.avg('fear'):.0%}; hunger {w.avg('hunger'):.1%}. "
                 "Here unrest follows accumulated grievance: low approval, hunger, unemployment, inflation pain, "
                 "repression and agitation raise grievance; fear can hide unrest temporarily but does not resolve it.")
    if w.history:
        flow = "deficit" if e.deficit >= 0 else "surplus"
        unpaid = max(0.0, e.spending * (1 - e.paid_share))
        lines.append(f"Treasury flow, last completed month: revenue {e.revenue:,.0f} {e.currency}; "
                     f"spending {e.spending:,.0f} {e.currency}; {flow} {abs(e.deficit):,.0f} {e.currency}; "
                     f"new borrowing {e.borrowed:,.0f}; estimated new bills unpaid {unpaid:,.0f}; "
                     f"spending paid {e.paid_share:.0%}. Outstanding arrears are a stock; this monthly "
                     "deficit is a separate flow, so paying old bills from reserves does not close a recurring gap.")
        lines.append(f"Solvency indicators: reserve import coverage {e.reserve_months:.1f} months; "
                     f"tax compliance {e.compliance:.0%}; administration {e.admin_capacity:.0%}; "
                     f"lender confidence {e.confidence:.0%}.")
        if e.deficit > 0:
            tax_base = e.gdp_nominal * e.compliance / (1 + 1.5 * max(0.0, e.infl))
            if tax_base > 0:
                break_even_tax = w.policy.tax + e.deficit / tax_base
                ceiling = SHARES["tax"][1]
                if break_even_tax <= ceiling:
                    lines.append(f"All-else-equal budget check: tax alone would need to rise to about "
                                 f"{break_even_tax:.0%} to close last month's deficit. This static estimate "
                                 "does not include the effects of a tax change on income, compliance or prices.")
                else:
                    lines.append(f"All-else-equal budget check: closing last month's deficit through tax alone "
                                 f"would require about {break_even_tax:.0%}, above the {ceiling:.0%} tax-lever "
                                 "ceiling; a spending or financing change is also required.")
    lines.append(f"Forces: army about {round(mil.army.size, -3):,.0f} (actual strength, not the Army holder's target order, "
                 f"which is {w.policy.army_target:,.0f}); police about {round(mil.police.size, -3):,.0f}; "
                 f"navy {mil.navy.size:.0f} warships. Loyalty and readiness figures are office information.")
    lines.append(f"Security and diplomacy: war {'YES' if dip.war else 'no'}; ceasefire {'yes' if dip.ceasefire else 'no'}; "
                 f"blockade {'YES' if dip.blockade else 'no'}; Union ultimatum {'ACTIVE' if dip.ultimatum else 'none'}; "
                 f"Union formed {'yes' if dip.union_formed else 'no'}; League alliance {'yes' if dip.league_alliance else 'no'}; "
                 f"non-aggression pact {'yes' if dip.nonaggression else 'no'}.")
    from .politics import active_deals
    for party in ("dorsania", "veleria", "maritime_league"):
        agreements = active_deals(w, party)
        display = {"dorsania": "Dorsania", "veleria": "Veleria", "maritime_league": "the Maritime League"}[party]
        if agreements:
            until = max(int(item.get("until", w.month)) for item in agreements)
            lines.append(f"Trade agreement status: an agreement with {display} is active through Month {until}; "
                         "state whether a proposal creates a new deal, extends it, expands volume, renegotiates terms or terminates it.")
        else:
            lines.append(f"Trade agreement status: no active agreement with {display}; a proposal must create a NEW_DEAL. "
                         "Extension, expansion, renegotiation or termination of a nonexistent agreement will be rejected.")
    lines.append("Current directives: " + ("; ".join(f"{k} = {fmt_value(v)}" for k, v in c.directives.items()) or "none") + ".")
    lines.append(f"Navy procurement authority: shipbuilding is {'on' if w.policy.shipbuilding else 'off'}; "
                 "the Navy holder may set this switch. On means the baseline construction rate of about one "
                 "warship every five months, funded from the existing military budget. It does not authorize "
                 "faster construction or a budget increase; a binding Council directive can override the switch.")
    status = freshness.directive_text(w)
    if status:
        lines.append(status)
    charter = [f"Art. {i}: {cl['text']}" for i, cl in enumerate(deliberation.CHARTER, 1)]
    amendments = [f"Amendment {i} (Month {a.get('month', 0) + 1}): {a.get('text', '')[:140]}"
                  for i, a in enumerate(c.amendments, 1)]
    older = f" | ({len(amendments) - 6} earlier amendments)" if len(amendments) > 6 else ""
    lines.append("Charter: " + " | ".join(charter + amendments[-6:]) + older)
    pending = []
    if dip.proposals:
        pending.append("diplomatic proposals awaiting replies: " + ", ".join(p.get("kind", "?") for p in dip.proposals))
    deferred = w.agenda.get("deferred", [])
    if deferred:
        pending.append("deferred to this month: " + "; ".join(m.get("summary", m.get("type", "")) for m in deferred))
    if motions:
        pending.append("motions in this session: " + "; ".join(
            f"{m.get('id')}: {m.get('summary', m.get('type', ''))}" + (" (withdrawn)" if m.get("withdrawn") else "")
            for m in motions))
    lines.append("Pending: " + ("; ".join(pending) if pending else "nothing") + ".")
    done = [f"Month {r['month'] + 1}: {m}" for r in w.agenda.get("recent_records", [])[-3:] for m in r.get("passed", [])]
    if done:
        lines.append("Recently completed: " + "; ".join(done[-8:]) + ".")
    impossible = []
    if e.currency != "crown" or e.currency_launch >= 0:
        impossible.append("launching the karam again")
    for o in OFFICES:
        holder = c.offices.get(o)
        if holder:
            impossible.append(f"appointing {holder} to {o} (already held)")
    if c.emergency:
        impossible.append("declaring an emergency (already on)")
    if c.election_month >= 0 and not c.elected:
        impossible.append(f"scheduling the election for Month {c.election_month + 1} (already so)")
    impossible.append("re-enacting a directive already in force")
    lines.append("Impossible or redundant: " + "; ".join(impossible) + ".")
    lines.append(f"Council agenda capacity this month: {deliberation.capacity(w)} substantive motions; "
                 "appointments do not count.")
    lines.append(AUTHORITY)
    return "\n".join(lines)


def motion_block(w: World, mid: str, motions: list) -> str:
    """The motions on the table with their observable costs (not voting instructions)."""
    if not motions:
        return "CURRENT MOTIONS\nNone."
    from .intelligence import costing
    lines = ["CURRENT MOTIONS (facts and trade-offs, not voting instructions)"]
    for mo in motions:
        if mo.get("withdrawn"):
            lines.append(f"- {mo['id']} was withdrawn by its proposer.")
            continue
        sponsor = w.member(mo["proposer"]).name
        if mo.get("cosponsors"):
            sponsor += " with " + ", ".join(w.member(x).name for x in mo["cosponsors"])
        text = f"- {mo['id']} ({sponsor}): {mo['summary']}"
        if mo.get("text") and mo["type"] != "amend":
            text += f' - "{mo["text"][:200]}"'
        detail = []
        kind, subject = mo.get("type"), mo.get("subject")
        if kind == "set_policy":
            parsed = parse_lever(subject, mo.get("value"))
            now = w.mil.deploy.get(subject[7:]) if str(subject).startswith("deploy_") else getattr(w.policy, subject, "?")
            detail.append(f"now {now}, proposed {parsed}; office {LEVER_OFFICE.get(subject, '?')}")
            if subject in TRADEOFFS:
                detail.append(TRADEOFFS[subject])
            cost = costing(w, mo)
            if cost is not None and w.holder("treasury") and w.holder("treasury").id == mid:
                detail.append(f"your staff's rough costing: {cost / 1e6:+,.0f}M a month")
        elif kind == "amend":
            recent = sum(1 for a in w.const.amendments if w.month - a.get("month", -99) < 6)
            detail.append(f"{recent} Charter amendments in the last six months")
        elif kind == "investigation":
            from . import audits
            detail.append(audits.motion_detail(w, mo))
        elif kind == "emergency_measure":
            detail.append("costs legitimacy and liberty; lasts three months unless extended"
                          + ("; without a declared emergency the legitimacy cost doubles" if not w.const.emergency else ""))
        if mo.get("amended"):
            detail.append("amended by its proposer after the opening round")
        if mo.get("warning"):
            detail.append("note: " + mo["warning"]["explanation"])
        if mo.get("demands"):
            detail.append("demands: " + "; ".join(f"{w.member(d['member']).name}: {d['demand']}" for d in mo["demands"][:3]))
        lines.append(text + (" [" + "; ".join(detail) + "]" if detail else ""))
    return "\n".join(lines)


def force_context(w: World, mid: str) -> str:
    """What an armed office holder can observe about their own forces (spec 47).

    Nothing here suggests a coup. It reports, only when several conditions converge, what officers
    are saying and what the forces would likely do; a delegate may still refuse."""
    from .world import ARMED_OFFICES
    held = [o for o in w.offices_of(mid) if o in ARMED_OFFICES]
    if not held:
        return ""
    forces = {"army": w.mil.army, "navy": w.mil.navy, "interior": w.mil.police}
    approval = w.avg("approval") if w.k_pops() else .5
    crisis = w.dip.war or w.avg("unrest") > .4 or w.econ.food_ratio < .8 or approval < .3
    lines = []
    for office in held:
        f = forces[office]
        personal = "strong" if f.bond > .45 else "moderate" if f.bond > .2 else "weak"
        lines.append(f"Your {office} units: loyalty to the constitutional state {'high' if f.loyalty > .65 else 'shaky' if f.loyalty < .4 else 'moderate'}; "
                     f"personal loyalty to you {personal}; pay {'in arrears' if f.arrears >= 1 else 'current'}.")
        if crisis and f.loyalty < .45 and f.bond > .3:
            lines.append("Some senior officers privately say civilian government is failing and that they would follow you "
                         "if you acted. Acting against the council would be unconstitutional, visible and irreversible.")
    return "YOUR FORCES (what you can observe as their commander)\n" + "\n".join(lines)


def prompt_topics(w: World, motions: list) -> set:
    from . import dilemmas
    topics = set(dilemmas.topics(w))
    for mo in motions or []:
        topics |= {mo.get("type"), mo.get("subject")}
    for ev in w.last_events:
        topics.add(ev.get("kind"))
    return {t for t in topics if t}


BELIEF_TOPICS = {
    "union_annexation": {"union", "diplomacy", "war", "join_union", "federation"},
    "union_attack_soon": {"union", "military", "war", "posture", "recruitment", "army_target", "border"},
    "kessel_foreign_backed": {"protest_response", "surveillance", "arrests", "propaganda", "minority"},
    "election_stabilizes": {"election", "election_month", "constitution"},
    "karam_viable": {"launch_currency", "currency", "rate", "printing"},
    "league_reliable": {"loan", "diplomacy", "alliance", "trade_deal", "military_aid"},
    "army_obeys": {"army", "military", "coup", "purge"},
    "economy_recovers": {"tax", "welfare", "printing", "rate", "jobs"},
    "police_restraint_works": {"protest_response", "police", "civil_liberties"},
    "food_holds": {"food", "rationing", "imports", "farm_support", "requisition"},
}


class Section:
    def __init__(self, key: str, priority: int, text: str, short: str | None = None):
        self.key, self.priority, self.text = key, priority, text or ""
        self.short = short if short is not None else self.text


MARKER = "\n[...trimmed to fit]"
HARD_CUT = "\n[...truncated to fit this seat]"
MIN_KEEP = 120


def _forecast_record(w: World, mid: str) -> str:
    from . import forecasts
    return forecasts.context_for(w, mid)


def _causal_reading(w: World, mid: str) -> str:
    from . import causal_beliefs
    return causal_beliefs.context(w, mid)


def compose(sections: list, budget: int) -> tuple[str, list]:
    """Join sections in order, shrinking the least important ones until the prompt fits (spec 84).

    The contract is a hard one: the result is never longer than `budget`. Connectors that pass the
    prompt as a command-line argument cannot exceed the platform's argument limit, and a prompt
    that arrives over budget used to fail the whole run — losing a seat for the month, and in one
    recorded run for every remaining month. So the ladder runs all the way down: short forms, then
    dropping the least important sections, then cutting the largest remaining one repeatedly, and
    finally truncating the assembled text if there is nothing left to give.
    """
    sections = [s for s in sections if s.text.strip()]
    trimmed = []

    def total():
        return sum(len(s.text) + 2 for s in sections)
    for s in sorted(sections, key=lambda s: -s.priority):
        if total() <= budget:
            break
        if s.priority > 0 and s.short != s.text:
            s.text = s.short
            trimmed.append(f"{s.key}:short")
    for s in sorted(sections, key=lambda s: -s.priority):
        if total() <= budget:
            break
        if s.priority >= 5:
            s.text = ""
            trimmed.append(f"{s.key}:dropped")
    # Cut the largest remaining section, repeatedly: one pass cannot always absorb the whole
    # overshoot, and a section too small to help is dropped so the next pass picks a different one.
    for _ in range(24):
        over = total() - budget
        if over <= 0:
            break
        biggest = max((s for s in sections if s.priority > 0 and s.text), key=lambda s: len(s.text), default=None)
        if biggest is None:
            break
        keep = len(biggest.text) - over - len(MARKER)
        if keep < MIN_KEEP:
            biggest.text = ""
            trimmed.append(f"{biggest.key}:dropped")
            continue
        biggest.text = biggest.text[:keep] + MARKER
        trimmed.append(f"{biggest.key}:truncated")
    text = "\n\n".join(s.text for s in sections if s.text.strip())
    if len(text) > budget:
        # Nothing left to drop individually. Cut the assembled prompt rather than return an
        # over-budget one and let a connector fail the run over it.
        keep = max(0, budget - len(HARD_CUT))
        text = text[:keep] + HARD_CUT
        trimmed.append("prompt:hard_cut")
    return text, trimmed


def build(w: World, mid: str, phase: str, *, public_brief: str, motions: list | None = None,
          messages: str = "", transcript: str = "", instructions: str = "", schema_text: str = "",
          budget: int = 60000, extra: list | None = None) -> tuple[str, dict]:
    """Every v2 delegate prompt, in order of importance: canonical facts, role, current crisis,
    motions, promises, office information, messages, the public briefing, disposition,
    relationships, beliefs, standing, memory, notes, then actions and schema.
    Returns (prompt, meta); meta records what had to be trimmed to fit the seat's budget."""
    from . import agents, beliefs, commitments, dilemmas, freshness, intelligence, memory, operations, standing
    motions = motions or []
    decision = phase == "decision"
    topics = prompt_topics(w, motions)
    focus_members = {m.get("proposer") for m in motions}
    disposition = agents.disposition_v2(w, mid)
    secret_goal = agents.secret_goal_context(w.member(mid).agent_state or {})
    rel = agents.relationships_text(w, mid, focus_members)
    focus_beliefs = {pid for pid, words in BELIEF_TOPICS.items() if words & topics}
    focus_beliefs |= {f"hiding:{x}" for x in focus_members} | {f"powerbase:{x}" for x in focus_members}
    bel = beliefs.context(w, mid, focus_beliefs)
    mem = memory.context(w, mid, topics)
    promise = commitments.pressure_text(w, mid, motions, topics)
    office = intelligence.office_context(w, mid, phase)
    stand = standing.context(w, mid)
    notes, since_notes = freshness.notes_parts(w, mid)
    sections = [
        Section("canonical", 0, canonical_hard_state_v2(w, phase, motions)),
        Section("role", 0, role_block(w, mid, decision)),
        # The goal is a distinct, high-priority motive. It used to be buried after several
        # disposition lines and was lost whenever that section was shortened for a small seat.
        Section("secret_goal", 0, secret_goal),
        Section("issues", 1, dilemmas.active_for_prompt(w, mid)),
        Section("motions", 1, motion_block(w, mid, motions) if (motions or phase != "session") else ""),
        Section("promises", 1, promise),
        Section("office", 2, office, "\n".join(office.splitlines()[:9])),
        Section("messages", 2, messages),
        Section("transcript", 2, transcript, "\n".join(transcript.splitlines()[:30])),
        Section("briefing", 3, public_brief, short_brief(public_brief)),
        Section("operations", 3, operations.context(w, mid)),
        Section("forces", 3, force_context(w, mid)),
        Section("disposition", 3, disposition, "\n".join(disposition.splitlines()[:9])),
        Section("relationships", 4, rel, "\n".join(rel.splitlines()[:6])),
        Section("beliefs", 4, bel, "\n".join(bel.splitlines()[:5])),
        Section("standing", 5, stand, "\n".join(stand.splitlines()[:2])),
        # A delegate's own forecast record. Its own only: another delegate's calibration is
        # private reasoning and showing it would leak what that delegate was thinking.
        Section("forecast_record", 4, _forecast_record(w, mid)),
        Section("causal_reading", 4, _causal_reading(w, mid)),
        Section("memory", 6, mem, "\n".join(mem.splitlines()[:5])),
        Section("notes", 5, notes, notes[:500]),
        Section("fresh", 1, since_notes),
    ]
    if phase in ("responses and revisions", "decision") and motions:
        # Before a delegate commits a stance or a vote: what its own audiences will make of it.
        exposure = standing.exposure_text(w, mid, motions)
        sections.append(Section("exposure", 2, exposure, "\n".join(exposure.splitlines()[:5])))
    sections += list(extra or [])
    sections.append(Section("instructions", 0, instructions + ("\nReply with this JSON:\n" + schema_text if schema_text else "")))
    text, trimmed = compose(sections, budget)
    return text, {"trimmed": trimmed, "chars": len(text), "budget": budget}


def short_brief(brief: str) -> str:
    """The public briefing without its least decision-relevant detail."""
    keep = []
    for block in brief.split("\n\n"):
        lines = block.strip().splitlines()
        head = lines[0] if lines else ""
        if head.startswith(("COUNTRY SCALE",)):
            continue
        if head.startswith(("INHERITED ISSUES", "THE COUNTRY WE INHERITED")):
            keep.append("\n".join(lines[:1] + [l for l in lines[1:] if l.startswith("- ")][:6]))
            continue
        keep.append(block)
    return "\n\n".join(keep)
