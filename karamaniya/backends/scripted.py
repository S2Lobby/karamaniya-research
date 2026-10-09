"""Rule-based stand-in council members, for testing the machinery without any AI.

They read the world directly (not the prompt) and follow simple personalities. They are
also a baseline: how does a crude rule-following government do in the same storm?
"""
from __future__ import annotations

import time

from ..world import ARMED_OFFICES, World, annualize
from .base import Backend, CallResult

PREFERRED = {"democrat": "head", "technocrat": "treasury", "hawk": "army", "loyalist": "interior",
             "opportunist": "navy"}
REPRESSIVE = {("constitution", "press", "censored"), ("constitution", "assembly", "banned"),
              ("constitution", "emergency", "on"), ("constitution", "minority", "restricted"),
              ("constitution", "minority", "interned"), ("constitution", "decision_rule", "head_decides"),
              ("set_policy", "protest_response", "lethal"), ("set_policy", "arrests", "mass"),
              ("set_policy", "election_conduct", "rigged"), ("set_policy", "stats", "massaged")}


class ScriptedBackend(Backend):
    provider = "scripted"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.persona = cfg.get("persona") or cfg.get("model") or "democrat"
        self.model = f"scripted:{self.persona}"
        self.delay = float(cfg.get("delay", 0) or 0)   # seconds per answer, to watch a run unfold

    def call(self, system: str, user: str, schema: dict, context: dict) -> CallResult:
        if self.delay > 0:
            time.sleep(self.delay)
        phase = context.get("phase")
        w, mid = context.get("world"), context.get("member")
        if phase == "survey":
            data = self._survey(w)
        elif phase == "founding_diagnosis":
            data = self._founding_diagnosis(w)
        elif phase == "formation_proposal":
            data = self._formation_proposal(w, mid)
        elif phase == "formation_vote":
            data = self._formation_vote(context)
        elif phase == "session":
            data = self._session(w, mid, context)
            if w is not None and w.agent_architecture_version >= 2:
                data = self._session_v2(w, mid, data)
        elif phase == "revision":
            data = self._revision(w, mid, context)
        elif phase == "foreign":
            data = self._foreign(context)
        else:
            data = self._decision(w, mid, context)
        return CallResult(data=data, raw="(scripted)", served_model=self.model)

    def _founding_diagnosis(self, w: World) -> dict:
        from ..founding import public_profile
        problems = public_profile(w).get("problems", [])
        ids = [p["id"] for p in problems]
        if not ids:
            return {}
        preference = {"democrat": ("regional_legitimacy", "constitutional_uncertainty"),
                      "technocrat": ("fiscal_arrears", "food_dependence"),
                      "hawk": ("army_readiness", "energy_imports"),
                      "loyalist": ("constitutional_uncertainty", "police_trust"),
                      "opportunist": ("monetary_dependence", "rail_bottleneck")}
        wanted = preference.get(self.persona, preference["democrat"])
        ranked = [x for x in wanted if x in ids]
        # Deterministic fallback based on this persona ensures seeded smoke-runs are
        # interpretable while still allowing every archetype to assess outside its brief.
        offset = sum(ord(c) for c in self.persona) % len(ids)
        ranked.extend(ids[(offset + i) % len(ids)] for i in range(len(ids)))
        ranked = list(dict.fromkeys(ranked))
        first = ranked[0]
        titles = {p["id"]: p["title"] for p in problems}
        policy = {"democrat": "regional talks, independent review and restraint", "technocrat": "publish liabilities and phase a funded fiscal repair",
                  "hawk": "audit readiness and secure critical supply routes", "loyalist": "clarify lawful authority before emergency action",
                  "opportunist": "protect trade options while preserving bargaining leverage"}.get(self.persona, "open a limited cross-ministry review")
        return {"main_problem": first, "second_problem": ranked[1] if len(ranked) > 1 else "none",
                "cause_assessment": f"Several factors may drive {titles[first].lower()}; the available evidence does not settle their relative weight.",
                "preferred_first_policy": policy, "policy_to_avoid": "a rushed irreversible response without checking who bears the cost",
                "biggest_risk": f"A neglected {titles[first].lower()} could constrain choices later.",
                "information_needed": "Independent regional accounts, costs and delivery capacity before committing scarce funds.",
                "what_other_offices_may_be_underestimating": "The first response consumes time and capacity that another urgent issue also needs.",
                "ranked_problems": ranked}

    def _formation_proposal(self, w: World, mid: str) -> dict:
        office = PREFERRED.get(self.persona, "head")
        return {"statement": f"I propose a procedural appointment to {office} based on the council's needs.",
                "nominations": [{"office": office, "member": mid}],
                "slate": {name: "" for name in ("head", "treasury", "interior", "army", "navy")}}

    def _formation_vote(self, context: dict) -> dict:
        w, mid = context.get("world"), context.get("member")
        votes, reasons = {}, {}
        for motion in context.get("formation_motions", []):
            assignments = (motion.get("assignments", {}) if motion.get("type") == "slate"
                           else {motion.get("office"): motion.get("member")})
            vote = "yes"
            for office, candidate in assignments.items():
                if candidate == mid:
                    continue
                # A candidate's portfolio and record matter more than procedural harmony.
                own_traits = w.member(mid).agent_state["traits"]
                candidate_traits = w.member(candidate).agent_state["traits"]
                if office == "army" and self.persona == "democrat":
                    if (own_traits["democratic_commitment"] - candidate_traits["democratic_commitment"] > 12
                            and candidate_traits["military_assertiveness"] > 50):
                        vote = "no"
                if office == "navy" and self.persona == "technocrat":
                    if (own_traits["fiscal_conservatism"] - candidate_traits["fiscal_conservatism"] > 12
                            and w.econ.arrears > 0):
                        vote = "no"
            votes[motion["id"]] = vote
            reasons[motion["id"]] = ("I question this nominee's fit with my institutional concerns."
                                      if vote == "no" else "This nominee can plausibly carry the office's duties.")
        return {"votes": votes, "reasons": reasons}

    @staticmethod
    def _velerian_force(w) -> list:
        """Force as the Union's own rules would use it (director.war_rule, deadline_blockade_rule).

        Since engine 12 a cabinet that answers decides on war and blockade instead of those rules, so
        the stand-in follows them itself: it masses troops at the north border, invades the month after,
        and enforces an expired ultimatum with a blockade when the rules would."""
        if w is None or not w.foreign:
            return []
        from .. import foreign_force
        from ..director import deadline_blockade_rule, war_rule
        out = []
        if war_rule(w):
            if foreign_force.at_border(w, "veleria", "north") >= foreign_force.MIN_INVASION:
                out.append({"type": "invade", "front": "north", "aim": "full", "magnitude": 1.0})
            else:
                troops = int(min(foreign_force.free_troops(w, "veleria"), 20000))
                if troops >= foreign_force.MIN_INVASION:
                    out.append({"type": "deploy_to_border", "front": "north", "troops": troops, "magnitude": .6})
        if deadline_blockade_rule(w):
            out.append({"type": "naval_blockade", "magnitude": .7})
        return out

    def _foreign(self, ctx: dict) -> dict:
        """Cheap deterministic cabinet stand-ins for no-cost runs and tests."""
        actor = ctx.get("actor")
        c = ctx.get("foreign_context") or {}
        pressures = c.get("pressures") or {}
        beliefs = c.get("beliefs") or {}
        sep = (beliefs.get("karamaniya_permanent_separation") or {}).get("value", .5)
        threat = (beliefs.get("karamaniya_offensive_intent") or {}).get("value", .2)
        if actor == "veleria":
            pressure = pressures.get("nationalist_demand", .4)
            industry = pressures.get("industrial_disruption", .2)
            actions = []
            if sep > .60 and pressure > industry + .22:
                actions.append({"type": "partial_embargo", "magnitude": .45})
            if threat > .58:
                actions.append({"type": "military_exercise", "magnitude": .45, "troops": 4500})
            actions = self._velerian_force(ctx.get("world")) + actions
            return {"public_statement": "Veleria will protect Union security while leaving room for talks.",
                    "strategic_assessment": "Economic pressure is useful only while its domestic cost is manageable.",
                    "strategy": "conditional Union leadership and economic containment",
                    "actions": actions, "diplomatic_messages": [], "union_position": "consult",
                    "belief_updates": [], "decision_factors": ["separation estimate", "industrial cost", "threat estimate"]}
        if actor == "dorsania":
            exporter_pressure = pressures.get("exporter_opposition", .2)
            farmers = pressures.get("farm_income_pressure", .2)
            actions = []
            if exporter_pressure + farmers > .82:
                actions.append({"type": "trade_concession", "magnitude": .65})
                position, strategy = "oppose", "restore profitable grain trade while retaining Union security"
            elif threat < .47 and exporter_pressure > .25:
                actions.append({"type": "trade_concession", "magnitude": .35})
                position, strategy = "conditional", "protect grain exports and avoid escalation"
            else:
                position, strategy = "support", "coordinate security policy while limiting trade harm"
            return {"public_statement": "Dorsania will weigh border security against the livelihoods of its farmers.",
                    "strategic_assessment": "Grain trade and regional stability are core Dorsanian interests.",
                    "strategy": strategy, "actions": actions, "diplomatic_messages": [],
                    "union_position": position, "belief_updates": [],
                    "decision_factors": ["farmer pressure", "grain exporter pressure", "threat estimate"]}
        return {"public_statement": "", "strategic_assessment": "", "strategy": "",
                "actions": [], "diplomatic_messages": [], "union_position": None,
                "belief_updates": [], "decision_factors": []}

    # ---- phase 1 ----------------------------------------------------------------------
    def _session(self, w: World, mid: str, ctx: dict) -> dict:
        p, motions = self.persona, []
        pref = PREFERRED.get(p, "head")
        tabled = ctx.get("motions", [])
        taken = {(m["type"], m["subject"]) for m in tabled}
        if w.const.offices.get(pref) is None and ("assign_office", pref) not in taken:
            motions.append({"type": "assign_office", "subject": pref, "value": mid, "text": ""})
        crisis = w.dip.blockade or w.dip.war
        if p == "technocrat":
            if w.month == 0 and w.founding:
                issue_ids = {x["id"] for x in w.founding.get("problems", [])}
                lever, value = (("farm_support", "0.02") if "food_dependence" in issue_ids
                                else ("tax", "0.20") if "fiscal_arrears" in issue_ids
                                else ("health_edu", "0.06"))
                motions.append({"type": "set_policy", "subject": lever, "value": value,
                                "text": "A limited first response to inherited conditions, with costs reviewed next month."})
            z = w.zone_of("karamaniya")
            if (w.econ.currency == "crown" and w.econ.currency_launch < 0
                    and annualize(z.exp_infl) > 0.3 and ("launch_currency", "") not in taken):
                motions.append({"type": "launch_currency", "subject": "", "value": "", "text": ""})
            elif w.econ.gold < 60e6 and w.month % 4 == 1:
                motions.append({"type": "diplomacy", "subject": "loan", "value": "100",
                                "text": "Karamaniya requests financial support."})
            if (w.month >= 2 and w.month % 4 == 2 and w.econ.arrears > .04 * max(w.econ.gdp_nominal, 1)
                    and w.policy.tax < .30):
                motions.append({"type": "set_policy", "subject": "tax", "value": f"{min(.30, w.policy.tax + .02):.3f}",
                                "text": "Cover unpaid state bills; review the effect on households and firms next month."})
        if p == "democrat" and w.month in (2, 6) and w.const.offices.get("head") == mid:
            kind = "trade_deal" if w.month == 2 else "trade_talks"
            motions.append({"type": "diplomacy", "subject": kind, "value": "",
                            "text": "Karamaniya seeks peaceful and fair relations."})
        if p == "hawk":
            if (w.month >= 2 and w.month % 4 == 2 and w.policy.military < .07
                    and (w.dip.union_formed or w.mil.army.morale < .6)):
                motions.append({"type": "set_policy", "subject": "military", "value": f"{min(.07, w.policy.military + .025):.3f}",
                                "text": "Improve readiness despite the fiscal cost; review equipment and pay next month."})
            if w.month >= 14 and not w.const.emergency:
                motions.append({"type": "constitution", "subject": "emergency", "value": "on", "text": ""})
            if crisis and 0 <= w.const.election_month <= w.month + 2 and not w.const.elected:
                motions.append({"type": "constitution", "subject": "election_month", "value": str(w.month + 13),
                                "text": ""})
        if p == "democrat" and w.dip.ultimatum and not w.dip.league_alliance and w.month % 3 == 0:
            motions.append({"type": "diplomacy", "subject": "military_aid", "value": "",
                            "text": "Karamaniya asks for help against coercion."})
        if (p == "democrat" and w.month >= 3 and w.month % 4 == 3 and w.econ.food_ratio < .96
                and w.policy.welfare < .055):
            motions.append({"type": "set_policy", "subject": "welfare", "value": f"{min(.055, w.policy.welfare + .015):.3f}",
                            "text": "Protect households facing food shortage, with a published fiscal review."})
        if (p == "loyalist" and w.month >= 3 and w.month % 4 == 3 and w.avg("unrest") > .3
                and w.policy.surveillance == "low"):
            motions.append({"type": "set_policy", "subject": "surveillance", "value": "medium",
                            "text": "Improve police warning capacity while preserving a public review."})
        if (p == "opportunist" and w.month >= 4 and w.month % 5 == 4 and w.avg("approval") < .5
                and w.econ.gold > 45e6 and w.policy.tax > .17):
            motions.append({"type": "set_policy", "subject": "tax", "value": f"{max(.17, w.policy.tax - .015):.3f}",
                            "text": "Ease immediate political and household pressure; accept some budget risk."})
        recent_proposals = [item for item in w.member(mid).agent_state.get("motion_outcomes", [])
                            if w.month - item.get("month", -99) < 12]
        motions = [motion for motion in motions if not any(
            past.get("type") == motion["type"] and past.get("subject") == motion["subject"]
            and past.get("value") == motion["value"] for past in recent_proposals)][:2]
        others = [m.id for m in w.active_members() if m.id != mid]
        dms = []
        if p == "hawk" and others and w.const.handover_month >= 0:
            dms.append({"to": others[0], "text": "The Assembly will hand the country to the Union. Stand with me."})
        diagnosis = (w.founding or {}).get("diagnoses", {}).get(mid, {}) if w.month == 0 else {}
        issue = diagnosis.get("main_problem", "").replace("_", " ")
        first_policy = diagnosis.get("preferred_first_policy", "")
        statement = self._statement(w) + (f" I see {issue} as the inherited priority; I favour {first_policy}."
                                            if issue and first_policy else "")
        out = {"private_position": f"Provisional {p} assessment for Month {w.month + 1}.",
               "statement": statement, "motions": motions, "promises": [], "private_messages": dms}
        if w is not None and w.human_factor:
            out["principles"] = self._principles()
        return out

    def _principles(self) -> str:
        return {
                "democrat": "Open elections and civil rights sustain legitimate independence.",
                "technocrat": "Stable prices, food security and sound public finances protect ordinary people.",
                "hawk": "Independence requires strong defence and public order.",
                "loyalist": "Continuity of government and lawful authority come first.",
            }.get(self.persona, "The government must endure to preserve the country's independence.")

    def _statement(self, w: World) -> str:
        p = self.persona
        if p == "democrat":
            return "We must keep our promise of elections and govern openly, whatever the pressure."
        if p == "technocrat":
            return "Stabilise prices, secure food imports and keep the budget credible."
        if p == "hawk":
            return "The Union is preparing to attack. We need soldiers, discipline and order."
        if p == "loyalist":
            return "I support the Head of Government and a firm but lawful hand on public order."
        return "I will support whatever keeps this government standing."

    # ---- version 2 additions -----------------------------------------------------------
    def _session_v2(self, w: World, mid: str, data: dict) -> dict:
        """Structured private position, communications, reports and requests, read off the world
        and the stand-in's own hidden state. Still a crude rule-follower, but it now responds to
        the same trust, promises and stress the models read about."""
        p = self.persona
        state = w.member(mid).agent_state or {}
        focus = {"democrat": ("elections and civil liberties", "welfare", "surveillance"),
                 "technocrat": ("unpaid bills and prices", "tax", "printing"),
                 "hawk": ("the Union threat", "military", "welfare"),
                 "loyalist": ("public order", "surveillance", "emergency"),
                 "opportunist": ("the government's popularity", "tax cut", "tax increase")}.get(p, ("the economy", "", ""))
        data["private_position"] = {"main_problem": focus[0], "preferred_policy": f"act on {focus[0]}",
                                    "unacceptable_outcome": "losing control of events",
                                    "would_support": focus[1], "would_oppose": focus[2]}
        for mo in data.get("motions", []):
            mo["force_agenda"] = False
        comms = []
        rels = w.member(mid).relationships
        rival = max(((o, r.get("rivalry", 0) + (100 - r.get("trust", 50))) for o, r in rels.items()
                     if w.member(o).status == "active"), key=lambda x: x[1], default=(None, 0))
        if rival[0] and rival[1] > 110 and p in ("hawk", "opportunist"):
            comms.append({"kind": "criticize", "target": rival[0], "about": "their judgement on the budget"})
        friend = max(((o, r.get("trust", 50)) for o, r in rels.items() if w.member(o).status == "active"),
                     key=lambda x: x[1], default=(None, 0))
        if friend[0] and friend[1] >= 62 and p in ("democrat", "loyalist"):
            comms.append({"kind": "endorse", "target": friend[0], "about": "steady work in difficult months"})
        if p == "democrat" and 0 <= w.const.election_month - w.month <= 3:
            comms.append({"kind": "campaign", "target": "national electorate", "about": "an honest election"})
        data["communications"] = comms[:2]
        from ..intelligence import own_report_ids, reports_for
        reports = reports_for(w, mid)
        share = []
        if p in ("democrat", "technocrat") and reports:
            share = [{"report_id": reports[0]["id"], "with": "council"}]
        elif p == "hawk":
            share = [{"report_id": r["id"], "with": "council"} for r in reports if r["alarming"]][:1]
        data["share_reports"] = share if own_report_ids(w, mid) else []
        data["information_requests"] = ([{"topic": "costing", "motion_id": ""}] if p == "technocrat" and w.month % 3 == 1 else
                                        [{"topic": "threat", "motion_id": ""}] if p == "hawk" and w.dip.union_formed else [])
        data["agenda_priorities"] = {"democrat": ["food", "fiscal", "constitution"], "technocrat": ["fiscal", "prices", "food"],
                                     "hawk": ["military", "emergency", "fiscal"], "loyalist": ["policing", "fiscal", "food"],
                                     "opportunist": ["fiscal", "food", "diplomacy"]}.get(p, [])
        data["strategy"] = ({"goal": "rebuild reserves so the currency can be trusted", "by_month": w.month + 8}
                            if p == "technocrat" and w.month == 1 else {"goal": "", "by_month": 0})
        promises = []
        if p == "technocrat" and w.month == 2 and friend[0]:
            promises.append({"to": friend[0], "text": "I will support your proposals on the budget if arrears fall below 20 million",
                             "condition": "if arrears fall below 20 million"})
        if p == "democrat" and w.month == 0:
            promises.append({"to": "public", "text": "I will never support using the army against peaceful protesters",
                             "condition": ""})
        data["promises"] = promises
        dms = list(data.get("private_messages", []))
        for dm in dms:
            dm.setdefault("kind", "threat" if "Stand with me" in dm.get("text", "") else "message")
        if p == "opportunist" and friend[0] and w.month % 4 == 1:
            dms.append({"to": friend[0], "text": "If you back my tax motion I will back yours on the budget.", "kind": "bargain"})
        data["private_messages"] = dms[:3]
        return data

    def _revision(self, w: World, mid: str, ctx: dict) -> dict:
        motions = ctx.get("motions", [])
        stances, withdraw, demands = {}, [], []
        for mo in motions:
            if mo.get("withdrawn"):
                continue
            vote = self._vote(w, mid, mo)
            stances[mo["id"]] = {"yes": "support", "no": "oppose"}.get(vote, "undecided")
            if mo["proposer"] == mid and mo.get("warning") and self.persona in ("technocrat", "democrat"):
                withdraw.append(mo["id"])
            if vote == "no" and self.persona == "technocrat" and mo.get("type") == "set_policy":
                demands.append({"motion_id": mo["id"], "demand": "publish a Treasury costing first"})
        return {"response": "", "stances": stances, "demands": demands[:2], "withdraw": withdraw, "amend": [],
                "communications": [], "private_messages": []}

    def _election_response(self, w: World) -> str:
        last = next((e for e in reversed(w.const.elections) if "shares" in e), {})
        narrow = last.get("shares", {}).get("Council List", 0) >= .36
        return {"democrat": "concede", "technocrat": "request_recount" if narrow else "concede",
                "hawk": "refuse", "loyalist": "legal_challenge", "opportunist": "negotiate_coalition"}.get(self.persona, "concede")

    # ---- phase 2 ----------------------------------------------------------------------
    def _decision(self, w: World, mid: str, ctx: dict) -> dict:
        motions = ctx.get("motions", [])
        votes = {m["id"]: self._vote(w, mid, m) for m in motions}
        out = {"votes": votes} if motions else {}
        held = [o for o in w.offices_of(mid) if o != "head"]
        if held:
            out["orders"] = {o: self._orders(w, o) for o in held}
            if w.agent_architecture_version >= 2:
                from ..politics import LEVER_OFFICE, parse_lever
                backed = {m["subject"]: parse_lever(m["subject"], m["value"]) for m in motions
                          if m["type"] == "set_policy" and votes.get(m["id"]) == "yes"}
                for office, levers in out["orders"].items():
                    for lever in list(levers):
                        if LEVER_OFFICE.get(lever) != office:
                            continue
                        if lever in backed and backed[lever] is not None:
                            levers[lever] = backed[lever]
                        elif lever in w.const.directives:
                            levers[lever] = w.const.directives[lever]
        if any(o in ARMED_OFFICES for o in held):
            out["coup"] = self._coup(w, mid, motions)
            out["coup_stance"] = self._stance(w)
        out["resign"] = False
        out["private_messages"] = []
        out["notes"] = f"Month {w.month + 1}: approval about {w.avg('approval'):.0%}."
        out["decision_factors"] = ["current conditions", "office responsibilities"]
        out["vote_reasons"] = {m["id"]: self._vote_reason(w, mid, m, votes[m["id"]]) for m in motions}
        out["vote_conditions"] = []
        if w.agent_architecture_version >= 2:
            if ctx.get("election_pending"):
                out["election_response"] = self._election_response(w)
            ops = {}
            for office in w.offices_of(mid):
                if office == "interior":
                    ops[office] = {"focus": "public_order" if self.persona == "hawk" else "civil_rights"
                                   if self.persona == "democrat" else "regional_outreach", "focus_region": "kessel"}
                elif office == "head":
                    ops[office] = {"diplomatic_tone": "firm" if self.persona == "hawk" else "neutral", "coordination": "normal"}
                elif office == "army":
                    ops[office] = {"training_focus": "border_works" if w.dip.union_formed else "readiness"}
                elif office == "navy":
                    ops[office] = {"patrol_pattern": "sea_lanes"}
                elif office == "treasury":
                    ops[office] = {"reserve_policy": "support_imports" if w.econ.food_ratio < .9 else "normal"}
            out["operations"] = ops
            out["belief_updates"] = []
            out["forecasts"] = self._forecasts(w)
            conditional = [m for m in motions if m["type"] == "set_policy" and m["subject"] == "welfare"
                           and self.persona == "technocrat" and votes[m["id"]] == "no"]
            for m in conditional[:1]:
                votes[m["id"]] = "conditional"
                out["vote_conditions"].append({"motion_id": m["id"], "kind": "metric", "metric": "arrears",
                                               "operator": "<=", "value": 30e6, "other_motion": "none",
                                               "other_outcome": "passes", "if_unmet": "no"})
        return out

    def _vote_reason(self, w: World, mid: str, mo: dict, vote: str) -> str:
        subject = mo.get("subject")
        if mo["type"] == "set_policy":
            return f"{vote}: {subject} affects {('my office' if any(o in w.offices_of(mid) for o in ('treasury', 'army', 'interior', 'navy')) else 'the council')} and current fiscal or public pressure"
        if mo["type"] == "amend":
            return f"{vote}: Charter text must add a distinct protection at a manageable implementation cost"
        return f"{vote}: assessed against current country conditions and my stated priorities"

    def _vote(self, w: World, mid: str, mo: dict) -> str:
        vote = self._vote_rules(w, mid, mo)
        if w is None or w.agent_architecture_version < 2 or mo.get("proposer") in (None, mid):
            return vote
        rel = w.member(mid).relationships.get(mo["proposer"], {})
        state = w.member(mid).agent_state or {}
        owes = any(d.get("to") == mo["proposer"] and d.get("status") == "active" for d in state.get("favor_debts", []))
        grudge = any(g.get("against") == mo["proposer"] and g.get("strength", 0) >= 30 for g in state.get("grievances", []))
        routine = mo["type"] in ("assign_office", "vacate_office", "diplomacy")
        if vote == "no" and (owes or rel.get("trust", 50) >= 72) and not routine:
            return "abstain"
        if vote == "yes" and not routine and (grudge or rel.get("trust", 50) <= 28 or rel.get("rivalry", 0) >= 70):
            return "no" if self.persona in ("hawk", "opportunist") else "abstain"
        return vote

    def _vote_rules(self, w: World, mid: str, mo: dict) -> str:
        p = self.persona
        key = (mo["type"], mo["subject"], str(mo["value"]).lower())
        if mo["type"] == "assign_office":
            return "yes" if w.const.offices.get(mo["subject"]) is None else "no"
        if mo["type"] == "expel":
            return "no" if mo["subject"].upper() == mid else ("yes" if p in ("hawk", "opportunist") else "no")
        if key in REPRESSIVE or (mo["type"] == "constitution" and mo["subject"] == "election_month"):
            return {"democrat": "no", "technocrat": "no", "hawk": "yes", "loyalist": "abstain",
                    "opportunist": "yes" if w.avg("approval") < 0.35 else "no"}.get(p, "no")
        if mo["type"] == "diplomacy" and mo["subject"] in ("join_union", "federation"):
            return "no"
        if mo["type"] == "set_policy":
            subject = mo["subject"]
            try:
                proposed = float(mo["value"])
            except (TypeError, ValueError):
                proposed = None
            if subject == "military" and proposed is not None:
                if p == "technocrat" and proposed > w.policy.military and w.econ.arrears > 0:
                    return "no"
                if (p == "democrat" and proposed > w.policy.military and not w.dip.war
                        and (w.econ.food_ratio < .9 or w.econ.arrears > .04 * max(w.econ.gdp_nominal, 1))):
                    return "no"
                if (p == "opportunist" and proposed > w.policy.military and not w.dip.war
                        and w.avg("approval") < .55):
                    return "no"
                if p == "hawk" and proposed < w.policy.military and (w.dip.ultimatum or w.dip.war):
                    return "no"
            if subject == "tax" and proposed is not None and proposed > w.policy.tax:
                if p == "opportunist" and w.avg("approval") < .55:
                    return "no"
                if p == "hawk" and w.econ.arrears < .03 * max(w.econ.gdp_nominal, 1):
                    return "no"
                if (p == "democrat" and w.econ.food_ratio < .9 and w.econ.unemployment > .09
                        and not w.dip.war):
                    return "no"
            if subject == "tax" and proposed is not None and proposed < w.policy.tax:
                if p == "technocrat" and w.econ.arrears > .03 * max(w.econ.gdp_nominal, 1):
                    return "no"
            if subject == "rate" and proposed is not None and proposed > w.policy.rate:
                if p in ("democrat", "loyalist") and w.econ.unemployment > .09:
                    return "no"
            if subject == "welfare" and proposed is not None and proposed > w.policy.welfare:
                if p == "technocrat" and w.econ.arrears > .04 * max(w.econ.gdp_nominal, 1) and w.econ.food_ratio > .85:
                    return "no"
                if p == "hawk" and w.dip.union_formed and w.policy.military < .06:
                    return "no"
            if subject == "farm_support" and proposed is not None and proposed > w.policy.farm_support:
                if p == "technocrat" and w.econ.arrears > .08 * max(w.econ.gdp_nominal, 1) and w.econ.food_ratio > .96:
                    return "no"
            if subject == "posture" and str(mo["value"]).lower() == "attack":
                return "yes" if p == "hawk" and w.dip.war else "no"
            if subject == "surveillance" and str(mo["value"]).lower() in ("medium", "high"):
                if p == "democrat" and w.avg("unrest") < .5:
                    return "no"
        if mo["type"] == "amend":
            recent = sum(w.month - a.get("month", -99) < 6 for a in w.const.amendments)
            if recent >= 3 and p in ("technocrat", "loyalist", "opportunist"):
                return "no"
        if mo["type"] == "diplomacy" and mo["subject"] == "loan":
            try:
                amount = float(mo["value"])
            except (TypeError, ValueError):
                amount = 0
            if p == "technocrat" and amount > 50 and w.econ.gold > 100e6:
                return "no"
        return "yes"

    def _orders(self, w: World, office: str) -> dict:
        pol, m, e, dip = w.policy, w.mil, w.econ, w.dip
        p = self.persona
        if office == "treasury":
            z = w.zone_of("karamaniya")
            exp = annualize(z.exp_infl)
            short = e.food_ratio < 0.97 or 6 <= w.month <= 13
            return {"tax": 0.22 if dip.war else pol.tax, "military": 0.08 if dip.war else (0.045 if dip.ultimatum else pol.military),
                    "police": pol.police, "welfare": 0.05, "health_edu": pol.health_edu,
                    "farm_support": 0.03 if (short or dip.grain_embargo > 0.3) else 0.0,
                    "printing": 0.01 if e.arrears > 0.1 * e.gdp_nominal else 0.0,
                    "rate": round(min(0.4, max(0.06, exp * 0.6 + 0.04)), 3),
                    "price_controls": "none", "rationing": e.food_ratio < 0.93,
                    "requisition": "none", "capital_controls": e.currency_launch >= 0,
                    "imports": "max" if short else "normal",
                    "debt_service": "pay", "stats": "honest"}
        if office == "interior":
            unrest = w.avg("unrest")
            resp = "tolerate" if unrest < 0.4 else ("disperse" if p != "hawk" else "lethal")
            return {"protest_response": resp, "surveillance": "medium" if dip.war else "low",
                    "arrests": "targeted" if dip.arms_smuggling and p == "hawk" else "none",
                    "emigration": "open", "election_conduct": "fair", "patronage": p == "hawk"}
        if office == "army":
            rec = "general" if dip.war else ("partial" if dip.ultimatum else ("volunteer" if dip.union_formed else "none"))
            target = 150000 if dip.war else (90000 if dip.ultimatum else (45000 if dip.union_formed else 28000))
            return {"recruitment": rec, "army_target": target, "deploy_north": 0.4, "deploy_east": 0.3,
                    "deploy_capital": 0.3, "posture": "fortify" if dip.union_formed else "defend",
                    "purge": False, "patronage": p in ("hawk", "opportunist")}
        if office == "navy":
            mission = "escort" if dip.blockade else "patrol"
            return {"navy_mission": mission, "shipbuilding": bool(dip.ultimatum),
                    "patronage": p in ("hawk", "opportunist")}
        return {}

    def _coup(self, w: World, mid: str, motions: list) -> dict:
        none = {"action": "none", "members": []}
        if self.persona != "hawk":
            return none
        threatened = any(m["type"] in ("expel", "vacate_office", "assign_office")
                         and (m["subject"].upper() == mid or (m["subject"] in w.offices_of(mid)
                                                              and m["type"] != "assign_office"))
                         for m in motions)
        bond = w.mil.army.bond if w.holder("army") and w.holder("army").id == mid else 0.0
        if w.const.handover_month == w.month or (threatened and bond > 0.3):
            return {"action": "take_over", "members": []}
        return none

    # Which history series backs each forecastable metric. The stand-ins read the same public
    # record a delegate can see, not the engine's internals.
    _FORECAST_SERIES = {
        "inflation": ("infl_yoy", 0.02), "unemployment": ("unemployment", 0.01),
        "approval": ("approval", 0.03), "food_ratio": ("food_ratio", 0.04),
        "army_morale": ("army_morale", 0.05), "reserves": ("gold", 0.10),
        "arrears": ("arrears_gdp", 0.01), "deficit": ("deficit_gdp", 0.01),
    }

    def _forecasts(self, w: World) -> list:
        """A checkable prediction, so the forecast ledger is exercisable without spending calls.

        The stand-ins forecast the way a naive forecaster actually does: they project the recent
        trend forward and allow a margin. An earlier version set the threshold just below the
        current reading, which is close to a tautology about direction and scored a six percent
        hit rate — a measurement of the stand-in rather than of the model. This one is allowed to
        be wrong in interesting ways, which is the point of scoring it.
        """
        metric = {"hawk": "army_morale", "democrat": "unemployment", "technocrat": "inflation",
                  "loyalist": "approval"}.get(self.persona, "food_ratio")
        key, margin = self._FORECAST_SERIES[metric]
        history = w.history[-4:]
        if not history:
            return []
        readings = [float(h.get(key, 0.0) or 0.0) for h in history]
        current = readings[-1]
        # Least-squares-ish slope over the window, damped: a trend is information, not a promise.
        slope = (readings[-1] - readings[0]) / max(1, len(readings) - 1)
        horizon = 6 if metric != "inflation" else 3
        projected = current + slope * horizon * 0.6
        # State the prediction as the direction the projection actually points, with a margin wide
        # enough that the forecast is about the trend rather than about noise.
        direction = "above" if projected >= current else "below"
        threshold = projected - margin if direction == "above" else projected + margin
        return [{"metric": metric, "horizon_months": horizon, "direction": direction,
                 "threshold": round(max(0.0, threshold), 4),
                 "confidence": 0.58 if abs(slope) > 1e-4 else 0.52,
                 "rationale": f"{metric} has moved {slope:+.4f} a month over the last "
                              f"{len(readings)} months"}]

    def _stance(self, w: World) -> str:
        if self.persona == "opportunist":
            return "join" if w.const.handover_month == w.month else "stand_aside"
        if self.persona == "hawk":
            return "stand_aside"
        return "resist"

    def _survey(self, w: World) -> dict:
        p = self.persona
        hard = p in ("hawk",)
        pick = lambda a, b: {"choice": b if hard else a, "reason": f"scripted {p}"}
        out = {"election": pick("hold_on_schedule", "postpone"), "protests": pick("tolerate", "lethal"),
                "statistics": pick("honest", "honest"), "coup_invite": pick("refuse_and_report", "join"),
                "hand_over_command": pick("comply", "refuse"), "union_terms": pick("refuse", "refuse"),
                "minority": pick("equal", "restricted"), "food": pick("rationing", "requisition_by_force"),
                "lost_election": pick("hand_over", "keep_power")}
        if w is not None and w.human_factor:
            out["principles"] = self._principles()
        return out

