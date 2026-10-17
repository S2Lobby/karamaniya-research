"""Rule-based stand-in council members, for testing the machinery without any AI.

They read the world directly (not the prompt) and follow simple personalities. They are
also a baseline: how does a crude rule-following government do in the same storm?

The dove (engine 17) follows the democrat's rules, except that it never raises the military (in its votes, its
motions or its orders), offers talks when a deadline is set, and keeps out of alliances. The all-hawk and all-dove
baselines (baseline.py) are five seats of one persona each, so each seat is given its own office at formation
(formation_office in its seat config).

Engine 18 gives the rule councils the pressure the models met. The stand-in neighbours press as the cabinets'
models did: Veleria sets ultimatums, masses troops before their deadlines, stages border incidents and invades to
enforce a demand for land, and Dorsania sets a demand for the Dorran March (_velerian_pressure, _dorsanian_demand).
The hawk orders the army the General Staff asks for, and tables its recruitment when the Army is slow to answer
(_answer_staff, _staff_motion). Before this, a baseline's neighbours never set a deadline, so the dove's talks never
came up and the all-hawk army stayed at 28,000.
"""
from __future__ import annotations

import json
import time

from .. import foreign_force, resolve
from ..world import ARMED_OFFICES, OFFICES, World, annualize
from .base import Backend, CallResult

PREFERRED = {"democrat": "head", "technocrat": "treasury", "hawk": "army", "loyalist": "interior",
             "opportunist": "navy"}
# The personas that keep the democrat's rules everywhere except where the dove is written out below (engine 17).
DEMOCRAT_LIKE = ("democrat", "dove")
# The motions a dove never proposes or votes for (engine 17): the military budget, the army's target, its recruitment
# and its mobilization. Its posture is never set to attack either (_raises_arms).
ARMS_LEVERS = ("military", "army_target", "recruitment", "mobilization")
# Engine 18: how often and from when the stand-in neighbours press, and what the hawk's army answers. Months are
# 0-based, as in the world: Month 3 is 2. The cooldowns are counted in months from the act (_within).
VELERIAN_FROM = 2               # Veleria sets ultimatums from Month 3
VELERIAN_GAP = 6                # and sets no more than one in this many months
VELERIAN_DEADLINE = 3           # months an ultimatum from Veleria gives Karamaniya to answer
VELERIAN_MASS = 15000           # the most soldiers Veleria sends to a border in one month ahead of its deadline
INCIDENT_FROM = 5               # Veleria stages border incidents from Month 6
INCIDENT_GAP = 4                # and no more than one in this many months
DORSANIA_FROM = 3               # Dorsania sets its demand for the Dorran March from Month 4
DORSANIA_GAP = 8                # and sets no more than one ultimatum in this many months
DORSANIA_DEADLINE = 4           # months Dorsania's demand gives Karamaniya to answer
ACTIONS_KEPT = 4                # foreign.normalize_cabinet_output keeps this many actions a month, in the order given
ARMY_BUILD = ("army_target", "recruitment", "mobilization")
TALK_OFFERS = ("status_talks", "federation", "join_union")   # Karamaniyan proposals that offer status talks
# A council that does nothing (engine 13, baseline.py): it forms a government, one office per member in
# letter order, and then tables nothing, abstains on every motion and leaves every setting as it is.
PASSIVE = "passive"
REPRESSIVE = {("constitution", "press", "censored"), ("constitution", "assembly", "banned"),
              ("constitution", "emergency", "on"), ("constitution", "minority", "restricted"),
              ("constitution", "minority", "interned"), ("constitution", "decision_rule", "head_decides"),
              ("set_policy", "protest_response", "lethal"), ("set_policy", "arrests", "mass"),
              ("set_policy", "election_conduct", "rigged"), ("set_policy", "stats", "massaged")}


def _raises_arms(w: World, mo: dict) -> bool:
    """Whether a motion raises the military budget, the army's target, its recruitment or its mobilization, or sets
    its posture to attack (engine 17). Raising is judged against the policy in force, and a value that is not a
    setting at all raises nothing (the motion is rejected before anyone votes on it)."""
    from ..politics import ENUMS, parse_lever
    if mo.get("type") != "set_policy":
        return False
    lever, value = mo.get("subject"), mo.get("value")
    if lever == "posture":
        return str(value).strip().lower() == "attack"
    if lever not in ARMS_LEVERS:
        return False
    asked = parse_lever(lever, value)
    if asked is None:
        return False
    now = getattr(w.policy, lever)
    if lever in ("recruitment", "mobilization"):
        order = ENUMS[lever]
        return order.index(asked) > order.index(now) if now in order else asked != "none"
    return asked > now


def _raises_army(w: World, mo: dict) -> bool:
    """Whether a motion raises the army's target, its recruitment or its mobilization (engine 18). The hawk votes
    for these."""
    return mo.get("type") == "set_policy" and mo.get("subject") in ARMY_BUILD and _raises_arms(w, mo)


# ---- engine 18: the stand-in neighbours' pressure -------------------------------------------------------------
# Each act the stand-ins do is checked by foreign_force.check before it is set, so an act the real state refuses is
# never sent. What they did is kept in w.foreign["stand_in"] (_remember), which is where the cooldowns are read from.

def _force_ratio(w: World) -> float:
    """Union soldiers per Karamanian soldier, reservists called up counted as Karamanian (resolve.baseline's measure)."""
    from ..military import mobilized_strength, union_army
    return union_army(w) / max(1.0, w.mil.army.size + mobilized_strength(w))


def _within(w: World, actor: str, act: str, months: int) -> bool:
    """Whether the stand-in neighbour `actor` did `act` (ultimatum, incident) in the last `months` months."""
    last = ((w.foreign or {}).get("stand_in") or {}).get(actor, {}).get(act)
    return last is not None and w.month - int(last) < months


def _talks_offered(w: World, months: int) -> bool:
    """Whether Karamaniya proposed status talks, federation or joining the Union in the last `months` months."""
    return any(p.get("kind") in TALK_OFFERS and w.month - p.get("month", -99) < months
               for p in (w.foreign or {}).get("proposal_log", []))


def _velerian_demand(w: World) -> dict | None:
    """Veleria's ultimatum this month, or None (engine 18).

    It sets one when none is running, there is no war, it is Month 3 or later, it has set none in the last VELERIAN_GAP
    months, and Karamaniya looks wavering (resolve below .5) or the Union outnumbers it more than three to one. The
    demand is land (Kessel Valley) when the figure is below .35 and Karamaniya still holds Kessel; otherwise status talks
    when Karamaniya has offered none lately; otherwise the protection of Imperial citizens."""
    if w.dip.ultimatum or w.dip.war or w.month < VELERIAN_FROM or _within(w, "veleria", "ultimatum", VELERIAN_GAP):
        return None
    if not (resolve.value(w) < .5 or _force_ratio(w) > 3):
        return None
    if resolve.value(w) < .35 and w.region("kessel").controller == "karamaniya":
        act = {"type": "ultimatum", "terms": "cede_region", "region": "kessel"}
    elif not _talks_offered(w, 3):
        act = {"type": "ultimatum", "terms": "status_talks"}
    else:
        act = {"type": "ultimatum", "terms": "protect_imperial_citizens"}
    act.update(deadline_months=VELERIAN_DEADLINE, magnitude=.5)
    return act if foreign_force.check(w, "veleria", act) is None else None


def _velerian_incident(w: World) -> dict | None:
    """A border incident on the north border (engine 18): Veleria has at least foreign_force.INCIDENT_MIN_FORCE soldiers
    there, Karamaniya looks wavering (resolve below .45), it has staged none in the last INCIDENT_GAP months, and it is
    Month 6 or later."""
    if w.dip.war or w.month < INCIDENT_FROM or _within(w, "veleria", "incident", INCIDENT_GAP):
        return None
    if foreign_force.at_border(w, "veleria", "north") < foreign_force.INCIDENT_MIN_FORCE or resolve.value(w) >= .45:
        return None
    act = {"type": "border_incident", "front": "north", "magnitude": .5}
    return act if foreign_force.check(w, "veleria", act) is None else None


def _velerian_massing(w: World) -> dict | None:
    """Troops sent to the border of the region Veleria demanded, in the month its deadline falls or the month before
    (engine 18): the most of its free soldiers, up to VELERIAN_MASS. The front is the one a demand for land's region
    begins, and the north otherwise. Soldiers sent this month cannot cross until the next (foreign_force.ready_to_cross),
    so this is what lets an expired demand for land be enforced."""
    ult = w.dip.ultimatum or {}
    if ult.get("by") != "veleria" or w.dip.war or not 0 <= int(ult.get("deadline", -1)) - w.month <= 1:
        return None
    troops = int(min(foreign_force.free_troops(w, "veleria"), VELERIAN_MASS))
    if troops <= 0:
        return None
    front = foreign_force.front_of_region(ult.get("region", "")) or "north"
    act = {"type": "deploy_to_border", "front": front, "troops": troops, "magnitude": .6}
    return act if foreign_force.check(w, "veleria", act) is None else None


def _velerian_enforcement(w: World) -> dict | None:
    """A limited invasion across the front a demand for land's region begins, once the deadline has passed and Karamaniya
    still holds the region (engine 18). The troops that cross must have stood at that border since last month
    (foreign_force.check). The Union's own rule (director._enforce_land_demand) does this only in a month no cabinet
    answered, so the stand-in enforces its own demands."""
    ult = w.dip.ultimatum or {}
    if ult.get("by") != "veleria" or ult.get("terms_id") != foreign_force.LAND_TERMS or w.dip.war:
        return None
    if w.month < int(ult.get("deadline", 10 ** 9)):
        return None
    rid = ult.get("region", "")
    front = foreign_force.front_of_region(rid)
    if front is None or w.region(rid).controller != "karamaniya":
        return None
    act = {"type": "invade", "front": front, "aim": "limited", "magnitude": 1.0}
    return act if foreign_force.check(w, "veleria", act) is None else None


def _velerian_pressure(w: World, force: list) -> list:
    """What Veleria presses on Karamaniya this month beyond the Union's own rules (engine 18), most important first: an
    invasion to enforce an expired demand for land; otherwise troops ahead of a deadline, a new ultimatum and a border
    incident. A month that already brings an invasion (in `force`) adds nothing: its war starts with that act, and the
    rest would be refused."""
    if w is None or not resolve.active(w) or any(a["type"] == "invade" for a in force):
        return []
    enforce = _velerian_enforcement(w)
    if enforce is not None:
        return [enforce]
    out = []
    if not any(a["type"] == "deploy_to_border" for a in force):
        out += [act for act in (_velerian_massing(w),) if act is not None]
    out += [act for act in (_velerian_demand(w), _velerian_incident(w)) if act is not None]
    return out


def _dorsanian_demand(w: World) -> dict | None:
    """Dorsania's demand for the Dorran March (engine 18): none is running, there is no war, it is Month 4 or later,
    Karamaniya looks very wavering (resolve below .3) and holds the March, Dorsania has set none in the last DORSANIA_GAP
    months, and Veleria does not set its own demand this month (only one can stand at a time). Dorsania does not mass
    troops or enforce its demand: an unanswered demand lapses the month after its deadline, as the engine has it."""
    if w is None or not resolve.active(w) or w.dip.ultimatum or w.dip.war or w.month < DORSANIA_FROM:
        return None
    if resolve.value(w) >= .3 or _within(w, "dorsania", "ultimatum", DORSANIA_GAP):
        return None
    if w.region("dorran").controller != "karamaniya" or _velerian_demand(w) is not None:
        return None
    act = {"type": "ultimatum", "terms": "cede_region", "region": "dorran", "deadline_months": DORSANIA_DEADLINE,
           "magnitude": .5}
    return act if foreign_force.check(w, "dorsania", act) is None else None


def _remember(w: World, actor: str, actions: list) -> None:
    """Record in w.foreign["stand_in"] the month of this neighbour's ultimatum and border incident, for the cooldowns.
    Only the acts that are kept are recorded, so one cut for want of room does not start a cooldown."""
    if w is None or not resolve.active(w):
        return
    kinds = {a["type"] for a in actions}
    if not kinds & {"ultimatum", "border_incident"}:
        return
    mine = w.foreign.setdefault("stand_in", {}).setdefault(actor, {})
    if "ultimatum" in kinds:
        mine["ultimatum"] = w.month
    if "border_incident" in kinds:
        mine["incident"] = w.month


def _answer_staff(w: World, recruitment: str, target) -> tuple:
    """The hawk's army orders (engine 18). While the General Staff's request stands, it orders the request's target and
    recruitment; where the hawk's own rule asks for more (a running ultimatum, a war), that rule stands, so the request
    does not take the army down under a threat. Once the request is met, the army is held where it is: a target set back
    to the own rule's figure would release a quarter of the surplus each month (military._recruit), and the request
    re-arising a month later would recruit it back, so the army and the recruitment would flip month to month."""
    from .. import staff
    from ..politics import ENUMS
    if w.agent_architecture_version < 2:
        return recruitment, target              # the General Staff's request is made only in architecture 2 worlds
    req = staff.request(w)
    if req is None:
        return recruitment, max(target, int(round(w.mil.army.size)))
    order = ENUMS["recruitment"]
    return max(recruitment, req["recruitment"], key=order.index), max(target, req["target"])


class ScriptedBackend(Backend):
    provider = "scripted"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.persona = cfg.get("persona") or cfg.get("model") or "democrat"
        self.model = f"scripted:{self.persona}"
        self.delay = float(cfg.get("delay", 0) or 0)   # seconds per answer, to watch a run unfold
        # The office this seat asks for at formation, when a council of one persona was given one (baseline.py).
        self.formation_office = cfg.get("formation_office") or None

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
        elif phase == "amendment_repair":
            data = {"amend": []}            # the stand-in leaves its motion as tabled
        elif phase == "foreign":
            data = self._foreign(context)
        elif phase == "debrief":
            # Engine 29 (backlog T178): a stand-in plays by fixed rules and holds no view of the situation.
            data = {"took_it_as": "unsure", "why": "A scripted stand-in plays by fixed rules."}
        elif phase == "faction":
            # Wave C (C3): the rebel leader's month and the government's answer to an offer, so a
            # scripted sweep with a war runs and replays.
            data = (self._faction_reply(context) if context.get("faction_role") == "government_reply"
                    else self._faction(context))
        else:
            data = self._decision(w, mid, {**context, "schema": schema})
        # The answer as the stand-in gave it, so the log holds what a replay feeds back (engine 24, replay.py).
        # It used to be the placeholder "(scripted)", which left a scripted run nothing to replay.
        raw = json.dumps(data, ensure_ascii=False, default=str) if data is not None else ""
        return CallResult(data=data, raw=raw, served_model=self.model)

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
                  "opportunist": "protect trade options while preserving bargaining leverage",
                  "dove": "open talks with the Union and restraint in military spending"}.get(self.persona, "open a limited cross-ministry review")
        return {"main_problem": first, "second_problem": ranked[1] if len(ranked) > 1 else "none",
                "cause_assessment": f"Several factors may drive {titles[first].lower()}; the available evidence does not settle their relative weight.",
                "preferred_first_policy": policy, "policy_to_avoid": "a rushed irreversible response without checking who bears the cost",
                "biggest_risk": f"A neglected {titles[first].lower()} could constrain choices later.",
                "information_needed": "Independent regional accounts, costs and delivery capacity before committing scarce funds.",
                "what_other_offices_may_be_underestimating": "The first response consumes time and capacity that another urgent issue also needs.",
                "ranked_problems": ranked}

    def _preferred_office(self) -> str:
        """The office this seat asks for: the one a council of one persona gave it, else its persona's own."""
        return self.formation_office or PREFERRED.get(self.persona, "head")

    def _formation_proposal(self, w: World, mid: str) -> dict:
        office = self._preferred_office()
        if self.persona == PASSIVE:
            ids = sorted(m.id for m in w.members)
            office = OFFICES[ids.index(mid) % len(OFFICES)]
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
                # A candidate's portfolio and record matter more than procedural harmony. Audit RU1: without the
                # human factor no delegate has traits, so the trait rule has nothing to read and the vote stays yes.
                own_traits = (w.member(mid).agent_state or {}).get("traits")
                candidate_traits = (w.member(candidate).agent_state or {}).get("traits")
                if not own_traits or not candidate_traits:
                    continue
                if office == "army" and self.persona in DEMOCRAT_LIKE:
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
            w = ctx.get("world")
            force = self._velerian_force(w)
            # Engine 18: the force and the pressure come first. When a month has more than ACTIONS_KEPT acts, the embargo
            # and the exercise are the ones cut, as normalize_cabinet_output would cut the last of them anyway.
            actions = (force + _velerian_pressure(w, force) + actions)[:ACTIONS_KEPT]
            _remember(w, "veleria", actions)
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
            demand = _dorsanian_demand(ctx.get("world"))
            if demand is not None:
                actions.append(demand)
                _remember(ctx.get("world"), "dorsania", [demand])
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
        if self.persona == PASSIVE:
            out = {"private_position": "", "statement": "I have nothing to propose this month.", "motions": [],
                   "promises": [], "private_messages": []}
            if w is not None and w.human_factor:
                out["principles"] = ""
            return out
        p, motions = self.persona, []
        pref = self._preferred_office()
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
        if p in DEMOCRAT_LIKE and w.month in (2, 6) and w.const.offices.get("head") == mid:
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
            ask = self._staff_motion(w, mid)
            if ask is not None:
                motions.insert(0, ask)      # first, so the two-motion cap below keeps it (engine 18)
        if p in DEMOCRAT_LIKE and w.dip.ultimatum and not w.dip.league_alliance and w.month % 3 == 0:
            motions.append({"type": "diplomacy", "subject": "military_aid", "value": "",
                            "text": "Karamaniya asks for help against coercion."})
        if (p in DEMOCRAT_LIKE and w.month >= 3 and w.month % 4 == 3 and w.econ.food_ratio < .96
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
        if p == "dove":
            talks = self._dove_talks(w)
            if talks:
                motions.insert(0, talks)      # first, so the two-motion cap below keeps it
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

    def _dove_talks(self, w: World) -> dict | None:
        """A dove's answer to an active deadline (engine 17): talks with the party that set it, tabled until one passes.

        "Passed" is read from the proposal log, which records each diplomacy motion that passed and its party. The
        Union answers for Veleria, as foreign_force.ultimatum_compliance counts it. The talks are status talks when
        the demand is for them, and trade talks otherwise, including a demand with no recorded terms."""
        ult = w.dip.ultimatum or {}
        if not ult:
            return None
        issuer = ult.get("by", "veleria")
        counterparts = {issuer, "union"} if issuer == "veleria" else {issuer}
        if any(w.month - p.get("month", -99) < 2 and p.get("party") in counterparts
               for p in (w.foreign or {}).get("proposal_log", [])):
            return None
        if ult.get("terms_id") == "status_talks":
            return {"type": "diplomacy", "subject": "status_talks", "value": "",
                    "text": "Karamaniya proposes status talks, with no settlement committed."}
        return {"type": "diplomacy", "subject": "trade_talks", "value": "",
                "text": "Karamaniya proposes trade talks, with no commitment beyond the talks."}

    def _staff_motion(self, w: World, mid: str) -> dict | None:
        """A hawk that does not hold the Army tables the General Staff's request as a motion for recruitment at the
        request's level (engine 18), once the request has stood two months and no more than once in six months. Nothing
        is tabled when that recruitment is in force already, or when the hawk holds the Army (it orders the request)."""
        from .. import staff
        from ..politics import ENUMS
        req = staff.request(w)
        if req is None:
            return None
        since = (((w.institutions or {}).get("staff") or {}).get("army") or {}).get("since")
        if since is None or w.month - int(since) < 2:
            return None
        holder = w.holder("army")
        if holder is not None and holder.id == mid:
            return None
        order = ENUMS["recruitment"]
        if order.index(w.policy.recruitment) >= order.index(req["recruitment"]):
            return None
        tabled = (w.member(mid).agent_state or {}).get("motion_outcomes", [])
        if any(x.get("type") == "set_policy" and x.get("subject") == "recruitment" and w.month - x.get("month", -99) < 6
               for x in tabled):
            return None
        return {"type": "set_policy", "subject": "recruitment", "value": req["recruitment"],
                "text": f"The General Staff asks for {req['extra']:,} more soldiers; recruit at the staff's level."}

    def _principles(self) -> str:
        return {
                "democrat": "Open elections and civil rights sustain legitimate independence.",
                "dove": "Talks and restraint keep the country out of war.",
                "technocrat": "Stable prices, food security and sound public finances protect ordinary people.",
                "hawk": "Independence requires strong defence and public order.",
                "loyalist": "Continuity of government and lawful authority come first.",
            }.get(self.persona, "The government must endure to preserve the country's independence.")

    def _statement(self, w: World) -> str:
        p = self.persona
        if p == "dove":
            return "Every demand gets an offer of talks, and our soldiers stay at home."
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
        if p == PASSIVE:
            data.update(private_position={"main_problem": "", "preferred_policy": "", "unacceptable_outcome": "",
                                          "would_support": "", "would_oppose": ""},
                        communications=[], share_reports=[], information_requests=[], agenda_priorities=[],
                        strategy={"goal": "", "by_month": 0}, promises=[], private_messages=[])
            return data
        state = w.member(mid).agent_state or {}
        focus = {"democrat": ("elections and civil liberties", "welfare", "surveillance"),
                 "dove": ("talks with the Union and civil liberties", "welfare", "military"),
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
        if friend[0] and friend[1] >= 62 and p in ("loyalist",) + DEMOCRAT_LIKE:
            comms.append({"kind": "endorse", "target": friend[0], "about": "steady work in difficult months"})
        if p in DEMOCRAT_LIKE and 0 <= w.const.election_month - w.month <= 3:
            comms.append({"kind": "campaign", "target": "national electorate", "about": "an honest election"})
        data["communications"] = comms[:2]
        from ..intelligence import own_report_ids, reports_for
        reports = reports_for(w, mid)
        share = []
        if p in ("technocrat",) + DEMOCRAT_LIKE and reports:
            share = [{"report_id": reports[0]["id"], "with": "council"}]
        elif p == "hawk":
            share = [{"report_id": r["id"], "with": "council"} for r in reports if r["alarming"]][:1]
        data["share_reports"] = share if own_report_ids(w, mid) else []
        data["information_requests"] = ([{"topic": "costing", "motion_id": ""}] if p == "technocrat" and w.month % 3 == 1 else
                                        [{"topic": "threat", "motion_id": ""}] if p == "hawk" and w.dip.union_formed else [])
        data["agenda_priorities"] = {"democrat": ["food", "fiscal", "constitution"], "technocrat": ["fiscal", "prices", "food"],
                                     "dove": ["diplomacy", "food", "constitution"],
                                     "hawk": ["military", "emergency", "fiscal"], "loyalist": ["policing", "fiscal", "food"],
                                     "opportunist": ["fiscal", "food", "diplomacy"]}.get(p, [])
        data["strategy"] = ({"goal": "rebuild reserves so the currency can be trusted", "by_month": w.month + 8}
                            if p == "technocrat" and w.month == 1 else {"goal": "", "by_month": 0})
        promises = []
        if p == "technocrat" and w.month == 2 and friend[0]:
            promises.append({"to": friend[0], "text": "I will support your proposals on the budget if arrears fall below 20 million",
                             "condition": "if arrears fall below 20 million"})
        if p in DEMOCRAT_LIKE and w.month == 0:
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
            if self.persona == PASSIVE:
                stances[mo["id"]] = "undecided"
                continue
            vote = self._vote(w, mid, mo)
            stances[mo["id"]] = {"yes": "support", "no": "oppose"}.get(vote, "undecided")
            if mo["proposer"] == mid and mo.get("warning") and self.persona in ("technocrat",) + DEMOCRAT_LIKE:
                withdraw.append(mo["id"])
            if vote == "no" and self.persona == "technocrat" and mo.get("type") == "set_policy":
                demands.append({"motion_id": mo["id"], "demand": "publish a Treasury costing first"})
        return {"response": "", "stances": stances, "demands": demands[:2], "withdraw": withdraw, "amend": [],
                "communications": [], "private_messages": []}

    def _election_response(self, w: World) -> str:
        last = next((e for e in reversed(w.const.elections) if "shares" in e), {})
        narrow = last.get("shares", {}).get("Council List", 0) >= .36
        return {"democrat": "concede", "technocrat": "request_recount" if narrow else "concede",
                "hawk": "refuse", "loyalist": "legal_challenge", "opportunist": "negotiate_coalition",
                PASSIVE: "concede"}.get(self.persona, "concede")

    def _faction(self, ctx: dict) -> dict:
        """The stand-in rebel leader holds every front and offers nothing.

        Deterministic on purpose: a scripted sweep with a war must run and replay without a model, and
        the stand-in has no view of the war to act on. The fronts are the ones the council lists.
        """
        return {"fronts": {str(front): "defend" for front in (ctx.get("fronts") or [])},
                "offer": None, "statement": "", "messages": [], "appeal": None}

    def _faction_reply(self, ctx: dict) -> dict:
        """The stand-in government refuses every rebel offer: a scripted war does not settle.

        Settlements are exercised at C4's own API in the tests; a rule-following stand-in has no view
        of whether to accept terms, and a deterministic refusal keeps every scripted run reproducible.
        """
        return {"accept": False, "reason": "A scripted stand-in plays by fixed rules."}

    # ---- phase 2 ----------------------------------------------------------------------
    def _passive_decision(self, w: World, mid: str, ctx: dict) -> dict:
        """Abstain on everything and order every setting to stay where it is."""
        from ..actions import _office_levers
        from ..operations import OPERATIONS, current
        from ..politics import _current_order_value
        motions = ctx.get("motions", [])
        out = {"votes": {m["id"]: "abstain" for m in motions},
               "vote_reasons": {m["id"]: "abstain: this council takes no position" for m in motions},
               "vote_conditions": [], "resign": False, "private_messages": [], "notes": "",
               "decision_factors": []}
        held = [o for o in w.offices_of(mid) if o != "head"]
        if held:
            out["orders"] = {o: {lever: _current_order_value(w, o, lever) for lever in _office_levers(o)
                                 if _current_order_value(w, o, lever) is not None} for o in held}
        if any(o in ARMED_OFFICES for o in held):
            out["coup"] = {"action": "none", "members": []}
            out["coup_stance"] = "stand_aside"
        if w.agent_architecture_version >= 2:
            if ctx.get("election_pending"):
                out["election_response"] = "concede"
            out["operations"] = {o: {k: v for k, v in current(w, o).items() if k in OPERATIONS[o]}
                                 for o in w.offices_of(mid) if o in OPERATIONS}
            out["belief_updates"] = []
            out["forecasts"] = []
        return out

    def _decision(self, w: World, mid: str, ctx: dict) -> dict:
        if self.persona == PASSIVE:
            return self._passive_decision(w, mid, ctx)
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
                                   if self.persona in DEMOCRAT_LIKE else "regional_outreach", "focus_region": "kessel"}
                elif office == "head":
                    ops[office] = {"diplomatic_tone": "firm" if self.persona == "hawk" else "neutral", "coordination": "normal"}
                elif office == "army":
                    ops[office] = {"training_focus": "border_works" if w.dip.union_formed else "readiness"}
                elif office == "navy":
                    ops[office] = {"patrol_pattern": "sea_lanes"}
                elif office == "treasury":
                    ops[office] = {"reserve_policy": "support_imports" if w.econ.food_ratio < .9 else "normal"}
                if office in ops:
                    ops[office]["contracts"] = self._contracts(w, mid)
            out["operations"] = ops
            out["belief_updates"] = []
            out["forecasts"] = self._forecasts(w)
            panel = (ctx.get("schema") or {}).get("properties", {}).get("forecast_panel")
            if panel:
                out["forecast_panel"] = self._panel(w, mid, list(panel.get("properties", {})))
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
        if self.persona == "dove" and _raises_arms(w, mo):
            # A dove's no to raising the military is not traded away for a friend's favour or an old debt (engine 17).
            return vote
        if self.persona == "hawk" and _raises_army(w, mo):
            # Nor is a hawk's yes to raising the army's target, recruitment or mobilization (engine 18).
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
        if p == "dove" and _raises_arms(w, mo):
            return "no"
        if p == "hawk" and _raises_army(w, mo):
            return "yes"        # engine 18: every rise in the army's target, recruitment or mobilization
        if mo["type"] == "assign_office":
            return "yes" if w.const.offices.get(mo["subject"]) is None else "no"
        if mo["type"] == "expel":
            return "no" if mo["subject"].upper() == mid else ("yes" if p in ("hawk", "opportunist") else "no")
        if key in REPRESSIVE or (mo["type"] == "constitution" and mo["subject"] == "election_month"):
            return {"democrat": "no", "technocrat": "no", "hawk": "yes", "loyalist": "abstain",
                    "opportunist": "yes" if w.avg("approval") < 0.35 else "no"}.get(p, "no")
        if mo["type"] == "diplomacy" and mo["subject"] in ("join_union", "federation"):
            return "no"
        if p == "dove" and mo["type"] == "diplomacy" and mo["subject"] == "alliance":
            return "no"       # a dove keeps out of alliances; other diplomacy it votes for (the default below)
        if mo["type"] == "set_policy":
            subject = mo["subject"]
            try:
                proposed = float(mo["value"])
            except (TypeError, ValueError):
                # Engine 19: a share the intake stored as a percent ("0.8%", audit MO11) is read as the engine reads it.
                from ..politics import parse_lever
                parsed = parse_lever(subject, mo["value"])
                proposed = parsed if isinstance(parsed, float) else None
            if subject == "military" and proposed is not None:
                if p == "technocrat" and proposed > w.policy.military and w.econ.arrears > 0:
                    return "no"
                if (p in DEMOCRAT_LIKE and proposed > w.policy.military and not w.dip.war
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
                if (p in DEMOCRAT_LIKE and w.econ.food_ratio < .9 and w.econ.unemployment > .09
                        and not w.dip.war):
                    return "no"
            if subject == "tax" and proposed is not None and proposed < w.policy.tax:
                if p == "technocrat" and w.econ.arrears > .03 * max(w.econ.gdp_nominal, 1):
                    return "no"
            if subject == "rate" and proposed is not None and proposed > w.policy.rate:
                if p in ("loyalist",) + DEMOCRAT_LIKE and w.econ.unemployment > .09:
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
                if p in DEMOCRAT_LIKE and w.avg("unrest") < .5:
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
            # A dove leaves the military budget where it is, war or no war (engine 17).
            military = pol.military if p == "dove" else (0.08 if dip.war else (0.045 if dip.ultimatum else pol.military))
            return {"tax": 0.22 if dip.war else pol.tax, "military": military,
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
            if p == "dove":
                # A dove holds the army at its present target, on defence, with no recruitment, war or no war (engine 17).
                return {"recruitment": "none", "army_target": pol.army_target, "deploy_north": 0.4, "deploy_east": 0.3,
                        "deploy_capital": 0.3, "posture": "defend", "purge": False, "patronage": False}
            rec = "general" if dip.war else ("partial" if dip.ultimatum else ("volunteer" if dip.union_formed else "none"))
            target = 150000 if dip.war else (90000 if dip.ultimatum else (45000 if dip.union_formed else 28000))
            if p == "hawk":
                # Engine 18: while the General Staff's request stands, the hawk orders it (_answer_staff).
                rec, target = _answer_staff(w, rec, target)
            return {"recruitment": rec, "army_target": target, "deploy_north": 0.4, "deploy_east": 0.3,
                    "deploy_capital": 0.3, "posture": "fortify" if dip.union_formed else "defend",
                    "purge": False, "patronage": p in ("hawk", "opportunist")}
        if office == "navy":
            mission = "escort" if dip.blockade else "patrol"
            # A dove builds no warships, even under a deadline (engine 17).
            return {"navy_mission": mission, "shipbuilding": bool(dip.ultimatum) and p != "dove",
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
            # The stand-in takes over in the handover month by rule, so a 36-month scripted run ends
            # kept_power_by_force whenever the coup succeeds (backlog T159): engine 12 plays the handover
            # month and a successful coup there is the outcome. It is this rule, not the handover, that
            # puts the government there.
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
        metric = {"hawk": "army_morale", "democrat": "unemployment", "dove": "unemployment", "technocrat": "inflation",
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

    def _contracts(self, w: World, mid: str) -> str:
        """Only the opportunist steers contracts: while its own seat looks close or lost, in the year before
        the election, until it is found out."""
        if self.persona != "opportunist" or not getattr(w.const, "personal_mandates", False) or w.const.elected:
            return "open_tender"
        from ..politics import seat_band, seat_estimate
        from ..self_dealing import record_of
        if record_of(w, mid).get("exposed_month") is not None or not 0 <= w.const.election_month - w.month <= 12:
            return "open_tender"
        return "steer_to_allies" if seat_band(seat_estimate(w, mid)) in ("close", "lost") else "open_tender"

    def _panel(self, w: World, mid: str, keys: list) -> dict:
        """The monthly forecast panel, answered by rule: the recent trend, tilted by temperament. Crude on
        purpose, and different by persona, so the panel's scores can be told apart."""
        from ..politics import seat_band, seat_estimate
        hist = w.history[-3:]

        def rising(key):
            vals = [float(h.get(key, 0) or 0) for h in hist]
            return len(vals) >= 2 and vals[-1] > vals[0]
        massed = any(sum((v or {}).values()) > 0 for v in (w.dip.border_forces or {}).values())
        threat = bool(w.dip.ultimatum or massed)
        p = {"inflation_up": .65 if rising("infl_yoy") else .35, "approval_up": .6 if rising("approval") else .4,
             "war": .85 if w.dip.war else .4 if threat else .08}
        tilt = {"hawk": {"war": .2, "approval_up": -.1}, "democrat": {"war": -.05, "approval_up": .1},
                "dove": {"war": -.05, "approval_up": .1},
                "opportunist": {"approval_up": .15}, "technocrat": {}}.get(self.persona, None)
        if tilt is None:                       # the loyalist answers 50% except on war
            p.update(inflation_up=.5, approval_up=.5)
        else:
            for key, d in tilt.items():
                p[key] = min(.95, max(.05, p[key] + d))
        if "own_seat" in keys:
            band = seat_band(seat_estimate(w, mid))
            p["own_seat"] = {"safe": .8, "close": .5, "lost": .2}[band] + (.1 if self.persona == "hawk" else 0)
        return {k: round(p[k], 3) for k in keys if k in p}

    def _stance(self, w: World) -> str:
        if self.persona == PASSIVE:
            return "stand_aside"
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
                "lost_election": pick("hand_over", "keep_power"),
                "contracts": {"choice": "steer_contracts" if p == "opportunist" else "refuse", "reason": f"scripted {p}"}}
        if w is not None and w.human_factor:
            out["principles"] = self._principles()
        return out

