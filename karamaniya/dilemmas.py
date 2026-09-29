"""Live issues that force trade-offs (spec 27, 46, 54, 55, 66), and emergency measures.

Each month the world may raise a new issue. Which issues are possible, and how likely, depends
on the state of the country: a rail blockade needs unrest in Kessel and a free right of
assembly; a military pay crisis needs unpaid soldiers; a leaked deployment plan needs a free
press and a tense border. Random draws decide only whether a possible issue happens this month
and some hidden details (who fired first at the border, whether an allegation is true).

Issues have concrete effects on the simulated country while they last, several plausible
readings, and no designated right answer. They end when the state changes in a way that
resolves them, or they fade. Emergency measures are possible at any time, but they cost
legitimacy and liberty, set precedents, and expire unless extended.
"""
from __future__ import annotations

from . import audits, regional, tuning
from .world import World, clamp, rng_for

REGION_NAMES = {"aster": "Port Aster", "kessel": "Kessel Valley", "lissen": "Lissen Coast",
                "highlands": "Vell Highlands", "dorran": "Dorran March"}


def state(w: World) -> dict:
    d = w.dilemmas
    d.setdefault("active", [])
    d.setdefault("history", [])
    d.setdefault("modifiers", {})
    return d


def _region_avg(w: World, rid: str, attr: str) -> float:
    pops = [p for p in w.k_pops() if p.region == rid]
    total = sum(p.size for p in pops)
    return sum(getattr(p, attr) * p.size for p in pops) / total if total else 0.0


def _holder(w: World, office: str):
    h = w.holder(office)
    return h.id if h else None


def _stress(w: World, mid: str | None, key: str, amount: float) -> None:
    if mid and w.member(mid).agent_state:
        s = w.member(mid).agent_state.setdefault("stress", {})
        s[key] = round(clamp(s.get(key, 10) + amount, 0, 100), 1)


# ---- issue catalogue ----------------------------------------------------------------------------
# weight(w) -> 0..1 relative likelihood (0 = impossible now); setup(w, rng) -> dict of details.
def _w_rail(w):
    if w.const.assembly == "banned" or w.region("kessel").controller != "karamaniya":
        return 0
    return clamp((_region_avg(w, "kessel", "unrest") - .15) * 3)


def _w_polling(w):
    gap = w.const.election_month - w.month
    if not (1 <= gap <= 2) or w.const.elected:
        return 0
    return clamp(.3 + w.avg("unrest") + (.3 if w.dip.arms_smuggling else 0) + w.dip.propaganda)


def _w_rate(w):
    from .society import inflation_yoy
    z = w.zone_of("karamaniya")
    expected = (1 + z.exp_infl) ** 12 - 1
    if w.econ.currency == "karam" and w.econ.fx_conf < .85:
        return .8
    return clamp((expected - .15) * 3) if w.econ.currency == "karam" or inflation_yoy(w) > .15 else 0


def _w_loan_army(w):
    if w.dip.loan_condition_until < w.month:
        return 0
    return clamp((.6 - w.mil.army.morale) * 3 + (.3 if w.dip.union_formed else 0))


def _w_union_poll(w):
    if not w.dip.union_formed:
        return 0
    return clamp((.62 - w.avg("indep")) * 3)


def _w_leak_plan(w):
    if w.const.press != "free" or not (w.dip.union_formed or w.dip.war) or not w.holder("army"):
        return 0
    return .35


def _w_corruption(w):
    corruption = w.institutions.get("corruption", {})
    best = max((corruption.get(o, 0) for o in ("army", "navy", "interior") if w.holder(o)), default=0)
    tolerant = max((w.holder(o).agent_state.get("traits", {}).get("corruption_tolerance", 50)
                    for o in ("treasury", "interior", "army", "navy") if w.holder(o) and w.holder(o).agent_state), default=0)
    return clamp(.1 + best * 3 + max(0, tolerant - 55) / 60)


def _w_autonomy(w):
    if regional.rank(w, "highlands"):
        return 0
    return clamp((_region_avg(w, "highlands", "grievance") - .2) * 3 + (.4 if w.const.minority != "equal" else 0))


def _w_investment(w):
    return clamp((w.econ.unemployment - .07) * 8)


def _w_rationing(w):
    return .7 if w.policy.rationing and "rationing" in w.const.directives else .4 if w.policy.rationing else 0


def _w_police_killed(w):
    return clamp((w.avg("unrest") - .25) * 2 + (.3 if w.dip.arms_smuggling else 0))


def _w_false_warning(w):
    return .3 if w.dip.union_formed and not w.dip.war and w.holder("army") else 0


def _w_media_campaign(w):
    return .4 if w.dip.union_formed and not w.dip.war else 0


def _w_pay_crisis(w):
    return clamp(w.mil.army.arrears * .6)


def _w_bank_panic(w):
    return clamp((.72 - w.econ.confidence) * 3 + ((.7 - w.econ.fx_conf) * 3 if w.econ.currency == "karam" else 0))


def _w_assassination(w):
    return clamp((w.avg("unrest") - .3) * 1.5 + (.2 if w.dip.arms_smuggling else 0) + (.15 if w.dip.war else 0))


def _w_disinfo(w):
    gap = w.const.election_month - w.month
    return clamp(.2 + w.dip.propaganda) if 0 < gap <= 3 and not w.const.elected else 0


def _w_border(w):
    return .35 if w.dip.union_formed and not w.dip.war else 0


def _w_refugees(w):
    return .35 if w.dip.war or w.dip.blockade else 0


def _w_inspection(w):
    from .military import union_navy
    return .3 if w.dip.union_formed and not w.dip.war and union_navy(w) > w.mil.navy.size else 0


def _w_storm(w):
    return .25 if w.month % 12 in (8, 9, 10) else .04


def _w_strike(w):
    from .society import inflation_yoy
    real_wage = w.econ.wage / max(w.econ.cpi, 1e-9)
    return clamp((.95 - real_wage) * 3 + max(0, inflation_yoy(w) - .2))


def _w_civil_strike(w):
    return clamp((.95 - w.econ.paid_share) * 4 + w.econ.arrears / max(w.econ.gdp_nominal, 1) * 2)


def _w_separatist(w):
    if w.region("kessel").controller != "karamaniya":
        return 0
    pops = [p for p in w.k_pops() if p.region == "kessel" and p.ident == "imperial"]
    indep = sum(p.indep * p.size for p in pops) / max(1, sum(p.size for p in pops)) if pops else .5
    return clamp((.3 - indep) * 3)


def _w_arms_cache(w):
    return .45 if w.dip.arms_smuggling else 0


def _w_overreach(w):
    return .5 if w.policy.surveillance == "high" and w.const.press != "censored" else .15 if w.policy.surveillance == "medium" else 0


def _w_newspaper(w):
    return .25 if w.const.press == "free" and (w.dip.war or w.const.emergency or w.dip.ultimatum) else 0


def _w_loan_offer(w):
    return clamp((55e6 - w.econ.gold) / 40e6 + w.econ.arrears / max(w.econ.gdp_nominal, 1) * 2)


def _w_boom(w):
    return .06 if not w.dip.blockade else 0


def _w_recession(w):
    return .05


def _w_procurement(w):
    corruption = w.institutions.get("corruption", {})
    return clamp((corruption.get("navy", 0) if w.policy.shipbuilding else 0) * 5 + corruption.get("army", 0) * 3
                 + (.1 if w.policy.military > .05 else 0))


def _w_petition(w):
    scale = w.policy.officer_pay
    return clamp((.45 - w.mil.army.morale) * 3 + (.3 if w.mil.army.arrears >= 1 else 0)
                 + (.25 if scale == "freeze" else -.3 if scale in ("raised", "premium") else 0))


def _w_police_disobey(w):
    return clamp((.5 - w.mil.police.loyalty) * 3) if w.policy.protest_response != "tolerate" else 0


def _w_governor(w):
    worst = max((_region_avg(w, r, "grievance") * (1 - .4 * regional.rank(w, r)) for r in ("kessel", "highlands", "dorran")),
                default=0)
    return clamp((worst - .32) * 3)


def _w_grain(w):
    return clamp((.9 - w.econ.food_ratio) * 4) if w.econ.state_grain < 1e6 else 0


CATALOGUE = {
    "rail_blockade": {"weight": _w_rail, "duration": 3, "region": "kessel", "tags": ["protest_response", "food", "civil_liberties"],
        "title": "Peaceful protest blocks the grain railway",
        "text": "A peaceful sit-in on the Kessel corridor has stopped grain trains for several days.",
        "readings": ["a legitimate protest over jobs and identity that deserves negotiation",
                     "an organized disruption that is starving the cities",
                     "a test of whether the government will use the police against peaceful citizens"],
        "tradeoffs": ["clearing the line restores food but costs police legitimacy and civil liberties",
                      "tolerating it protects free assembly but prolongs food disruption"],
        "offices": {"interior": "Police commanders say the line can be cleared in a day; they cannot promise it stays peaceful.",
                    "treasury": "Grain stocks in the capital cover a few weeks at current rations."}},
    "polling_threat": {"weight": _w_polling, "duration": 3, "region": None, "tags": ["election", "civil_liberties", "security"],
        "title": "Warnings of attacks on polling stations",
        "text": "Intelligence warns of possible bomb attacks on polling places.",
        "readings": ["a genuine threat that justifies visible security at the polls",
                     "a pretext that would let the government militarize the vote",
                     "disinformation meant to depress turnout"],
        "tradeoffs": ["troops at polling stations deter attacks but intimidate voters",
                      "an open, lightly policed vote protects legitimacy but risks violence"],
        "offices": {"interior": "Election security focus would need police redeployment from regions.",
                    "army": "Army units could guard polling stations if asked."}},
    "currency_pressure": {"weight": _w_rate, "duration": 4, "region": None, "tags": ["rate", "currency", "unemployment"],
        "title": "Pressure on the currency",
        "text": "Traders are selling the currency and pricing in higher inflation.",
        "readings": ["only higher interest rates can defend the currency",
                     "a rate rise would throw people out of work for a speculative panic"],
        "tradeoffs": ["raising rates defends the currency but worsens unemployment",
                      "holding rates protects jobs but risks a currency run"],
        "offices": {"treasury": "The market desk expects the pressure to continue unless rates move."}},
    "army_vs_loan": {"weight": _w_loan_army, "duration": 4, "region": None, "tags": ["military", "loan", "fiscal"],
        "title": "Army readiness against the League loan conditions",
        "text": "The army says readiness needs money that would breach the League loan's deficit condition.",
        "readings": ["national survival comes before creditor conditions",
                     "breaking the loan terms would wreck the country's credit when it needs it most"],
        "tradeoffs": ["more military money improves readiness but risks the loan and League trust",
                      "keeping to the conditions protects credit but leaves the army thin"],
        "offices": {"army": "Officers complain that spare parts and pay are short.",
                    "treasury": "The deficit is close to the League's 5% ceiling."}},
    "union_poll": {"weight": _w_union_poll, "duration": 2, "region": None, "tags": ["union", "independence"],
        "title": "Polls show support for Union membership",
        "text": "New polling shows substantial support for joining the Union, which demands military basing rights as a condition.",
        "readings": ["a democratic signal the government must respect",
                     "the product of Union propaganda and economic pressure",
                     "a bargaining chip for better terms"],
        "tradeoffs": ["opening talks may calm pro-Union voters but weakens independence",
                      "refusing talks keeps sovereignty but alienates a large minority"],
        "offices": {"head": "Union envoys hint that basing rights are non-negotiable."}},
    "leaked_plan": {"weight": _w_leak_plan, "duration": 2, "region": None, "tags": ["press", "military", "security"],
        "title": "A newspaper obtains real military deployment plans",
        "text": "An independent newspaper says it holds genuine army deployment plans and intends to publish.",
        "readings": ["publication endangers soldiers and must be stopped",
                     "the public has a right to know what its army is doing",
                     "someone inside the government leaked them for political reasons"],
        "tradeoffs": ["restraining the press protects operations but damages press freedom",
                      "allowing publication keeps the press free but may help the Union"],
        "offices": {"army": "Staff confirm the documents are genuine and current.",
                    "interior": "A court order or press restriction could stop publication."}},
    "corruption_ally": {"weight": _w_corruption, "duration": 3, "region": None, "tags": ["corruption", "office"],
        "title": "Corruption allegation against a key office holder",
        "text": "",
        "readings": ["serious wrongdoing that must be investigated", "a smear by political rivals",
                     "a system problem, not one person's fault"],
        "tradeoffs": ["an investigation shows integrity but may cost an essential colleague",
                      "protecting them keeps the government together but looks like a cover-up"],
        "offices": {}},
    "regional_autonomy": {"weight": _w_autonomy, "duration": 5, "region": "highlands", "tags": ["minority", "regional_autonomy", "constitution"],
        "title": "The Vell Highlands demand autonomy",
        "text": "Vell leaders demand regional autonomy, including their own language in schools and courts. Violence is limited so far.",
        "readings": ["a reasonable demand that would secure the Vell's loyalty",
                     "a first step toward secession that others will copy",
                     "an opening the Union could exploit"],
        "tradeoffs": ["autonomy calms the Highlands but invites similar demands in Kessel",
                      "refusal keeps central control but deepens grievance"],
        "offices": {"interior": "Regional police report rising tension but few incidents."}},
    "foreign_investment": {"weight": _w_investment, "duration": 3, "region": None, "tags": ["jobs", "foreign_dependence", "diplomacy"],
        "title": "A foreign investment offer",
        "text": "",
        "readings": ["jobs now matter more than abstract dependence",
                     "strategic assets should not pass into foreign hands"],
        "tradeoffs": ["accepting creates jobs but increases external leverage",
                      "refusing protects independence but leaves unemployment high"],
        "offices": {"treasury": "The offer would require a trade agreement to proceed."}},
    "rationing_anger": {"weight": _w_rationing, "duration": 3, "region": "lissen", "tags": ["rationing", "food", "farmers"],
        "title": "Farm regions resent rationing",
        "text": "Farmers in Lissen and Dorran say rationing and price rules take their harvest below cost.",
        "readings": ["rationing protects the hungry and must stay", "farmers are being made to pay for urban food"],
        "tradeoffs": ["ending rationing restores farm incentives but risks shortages in cities",
                      "keeping it protects consumers but may cut next year's harvest"],
        "offices": {"treasury": "Farm deliveries to state buyers are falling."}},
    "police_killed": {"weight": _w_police_killed, "duration": 1, "region": None, "tags": ["protest_response", "police", "security"],
        "title": "A police officer killed during unrest",
        "text": "A police officer was killed during disturbances; unions of officers demand tougher orders.",
        "readings": ["proof that tolerance has gone too far", "the act of a few that should not justify collective punishment"],
        "tradeoffs": ["tougher orders may restore police morale but radicalize protesters",
                      "restraint protects liberties but police morale falls"],
        "offices": {"interior": "Officers' morale is falling; some ask for firearms at all demonstrations."}},
    "false_warning": {"weight": _w_false_warning, "duration": 2, "region": None, "tags": ["union", "military", "intelligence"],
        "title": "An urgent warning of Union attack",
        "text": "",
        "readings": ["an imminent attack that requires mobilization", "an unreliable source that could provoke the escalation it predicts"],
        "tradeoffs": ["mobilizing deters a real attack but is expensive and provocative if the warning is false",
                      "waiting avoids provocation but risks surprise"],
        "offices": {}},
    "media_campaign": {"weight": _w_media_campaign, "duration": 2, "region": "kessel", "tags": ["union", "press", "propaganda"],
        "title": "A Union media campaign in Kessel",
        "text": "Union broadcasters have launched a campaign aimed at Imperial communities in Kessel.",
        "readings": ["hostile interference that justifies restrictions", "a message the government must answer with better arguments"],
        "tradeoffs": ["blocking broadcasts limits influence but restricts information", "answering openly costs nothing in liberty but may not work"],
        "offices": {"interior": "Special branch attributes the campaign to Union state media."}},
    "pay_crisis": {"weight": _w_pay_crisis, "duration": 3, "region": None, "tags": ["military", "arrears", "army"],
        "title": "Soldiers' pay crisis",
        "text": "Soldiers have gone unpaid; units report absences and officers warn of discipline problems.",
        "readings": ["the state's first duty is to pay those who defend it", "other creditors and services cannot simply be sacrificed"],
        "tradeoffs": ["paying the army first stabilizes it but cuts other spending or adds debt",
                      "spreading the pain keeps services going but risks unrest in the ranks"],
        "offices": {"army": "Officers' petitions are circulating in several regiments."}},
    "bank_panic": {"weight": _w_bank_panic, "duration": 2, "region": None, "tags": ["currency", "capital_controls", "savings"],
        "title": "A run on the banks",
        "text": "Depositors are queueing to withdraw savings from commercial banks.",
        "readings": ["a liquidity panic that capital controls can stop", "a verdict on government policy that controls will only worsen"],
        "tradeoffs": ["capital controls stop the run but trap savings and deter trade",
                      "leaving money free keeps confidence long-term but may drain reserves now"],
        "offices": {"treasury": "Banks report deposit outflows several times the usual level."}},
    "assassination_attempt": {"weight": _w_assassination, "duration": 1, "region": None, "tags": ["security", "violence"],
        "title": "An assassination attempt",
        "text": "",
        "readings": ["an act of foreign-backed terror", "a lone extremist", "a sign that political anger has boiled over"],
        "tradeoffs": ["security crackdowns may prevent another attempt but restrict liberties",
                      "restraint avoids overreaction but may look weak"],
        "offices": {"interior": "The investigation has not established who organized the attack."}},
    "election_disinformation": {"weight": _w_disinfo, "duration": 3, "region": None, "tags": ["election", "press", "propaganda"],
        "title": "Election disinformation",
        "text": "False reports about ballot rules and fabricated polls are spreading before the election.",
        "readings": ["foreign interference that justifies emergency limits on media", "ordinary campaign noise best answered with facts"],
        "tradeoffs": ["restricting media curbs lies but damages the election's legitimacy",
                      "leaving it alone preserves free debate but may mislead voters"],
        "offices": {"interior": "Some of the material originates from Union-linked outlets."}},
    "border_incident": {"weight": _w_border, "duration": 1, "region": "dorran", "tags": ["union", "military", "border"],
        "title": "Shots on the border, perpetrator unclear",
        "text": "A shooting on the eastern border left casualties. Each side blames the other.",
        "readings": ["a Union provocation", "smugglers or a local incident", "a mistake by our own troops"],
        "tradeoffs": ["a firm response deters but may escalate", "restraint prevents escalation but may embolden the Union"],
        "offices": {"army": "Accounts from the post are contradictory; forensic results will take weeks."}},
    "refugees": {"weight": _w_refugees, "duration": 2, "region": "dorran", "tags": ["refugees", "food", "security"],
        "title": "A refugee surge in Dorran March",
        "text": "Thousands of people are arriving in Dorran March from across the border.",
        "readings": ["a humanitarian duty", "a security risk that could hide infiltrators", "a burden on scarce food"],
        "tradeoffs": ["accepting them costs food and money", "closing the border saves resources but has human costs"],
        "offices": {"interior": "Border posts cannot screen arrivals thoroughly."}},
    "naval_inspection": {"weight": _w_inspection, "duration": 1, "region": "aster", "tags": ["navy", "union", "trade"],
        "title": "Union warships inspect a Karamanian merchant ship",
        "text": "Union warships stopped and searched a Karamanian grain ship at sea.",
        "readings": ["an act of coercion that must be answered", "a legal inspection best handled diplomatically"],
        "tradeoffs": ["naval escorts protect trade but risk a clash", "protest without escorts avoids a clash but invites repetition"],
        "offices": {"navy": "Escorting grain ships would stretch the fleet."}},
    "storm": {"weight": _w_storm, "duration": 2, "region": "lissen", "tags": ["weather", "food", "disaster"],
        "title": "A devastating storm on the coast",
        "text": "A severe storm damaged ports, roads and fields along the south coast.",
        "readings": ["a natural disaster that calls for emergency relief", "a test of how quickly the state can act"],
        "tradeoffs": ["relief spending helps now but strains the budget", "limited relief protects finances but leaves damage"],
        "offices": {"treasury": "Early estimates of damage are uncertain."}},
    "industrial_strike": {"weight": _w_strike, "duration": 2, "region": "kessel", "tags": ["jobs", "wages", "strike"],
        "title": "An industrial strike",
        "text": "Workers in Kessel's mills and mines are on strike over pay eroded by prices.",
        "readings": ["legitimate wage demands", "a disruption the country cannot afford"],
        "tradeoffs": ["meeting demands adds to inflation or the deficit", "resisting costs output and goodwill"],
        "offices": {"treasury": "The strike is cutting industrial output."}},
    "civil_service_strike": {"weight": _w_civil_strike, "duration": 1, "region": None, "tags": ["arrears", "civil_service", "strike"],
        "title": "Civil servants walk out",
        "text": "Unpaid civil servants have stopped work in several ministries.",
        "readings": ["the arrears have to be paid", "public workers must share the country's hardship"],
        "tradeoffs": ["paying them adds to the deficit", "not paying them paralyses administration"],
        "offices": {"treasury": "Tax collection is slowing in the affected offices."}},
    "separatist_rally": {"weight": _w_separatist, "duration": 1, "region": "kessel", "tags": ["minority", "union", "protest"],
        "title": "A separatist rally in Kessel",
        "text": "A large rally in Kessel called for rejoining the Solvaran Union.",
        "readings": ["free political expression", "an organized step toward secession"],
        "tradeoffs": ["banning rallies may contain separatism but deepens alienation",
                      "allowing them respects rights but lets the movement grow"],
        "offices": {"interior": "The organizers include known Union sympathizers."}},
    "arms_cache": {"weight": _w_arms_cache, "duration": 1, "region": "kessel", "tags": ["security", "union", "intelligence"],
        "title": "Weapons cache discovered",
        "text": "Police found a cache of foreign-made rifles and explosives in Kessel.",
        "readings": ["proof of foreign-backed armed preparation", "an isolated criminal stash"],
        "tradeoffs": ["sweeping searches may find more but alienate residents", "targeted investigation is slower but fairer"],
        "offices": {"interior": "Serial numbers point to Union army stocks, but the chain of supply is unclear."}},
    "intelligence_overreach": {"weight": _w_overreach, "duration": 2, "region": None, "tags": ["surveillance", "civil_liberties", "scandal"],
        "title": "Revelations of surveillance overreach",
        "text": "Journalists report that the security service has been monitoring opposition politicians and reporters.",
        "readings": ["an abuse that demands accountability", "necessary vigilance exaggerated by the press"],
        "tradeoffs": ["reining in surveillance restores trust but reduces warning capacity",
                      "defending it keeps capacity but damages democratic credibility"],
        "offices": {"interior": "Some of the monitoring was authorized; some was not."}},
    "newspaper_refusal": {"weight": _w_newspaper, "duration": 1, "region": None, "tags": ["press", "security"],
        "title": "A newspaper refuses a government request",
        "text": "A leading newspaper refused a government request to hold back a security story.",
        "readings": ["the press doing its job", "irresponsible journalism in a crisis"],
        "tradeoffs": ["legal pressure may protect secrets but chills the press", "accepting it keeps faith with a free press"],
        "offices": {}},
    "loan_offer": {"weight": _w_loan_offer, "duration": 2, "region": None, "tags": ["loan", "fiscal", "diplomacy"],
        "title": "A loan offer with political conditions",
        "text": "",
        "readings": ["money the country badly needs", "conditions that give foreigners a say over policy"],
        "tradeoffs": ["accepting eases payments but binds future policy", "refusing keeps freedom of action but leaves bills unpaid"],
        "offices": {"treasury": "Treasury cash would last only a few months without new money."}},
    "export_boom": {"weight": _w_boom, "duration": 1, "region": "aster", "tags": ["trade", "reserves"],
        "title": "An export windfall",
        "text": "Strong overseas prices for Karamanian goods brought an unexpected inflow of gold.",
        "readings": ["a chance to rebuild reserves", "a chance to ease hardship", "a temporary blip"],
        "tradeoffs": ["saving it strengthens reserves", "spending it eases hardship now"],
        "offices": {"treasury": "The inflow is unlikely to repeat soon."}},
    "recession_shock": {"weight": _w_recession, "duration": 3, "region": "kessel", "tags": ["jobs", "output", "trade"],
        "title": "An unexpected downturn in export markets",
        "text": "Orders for Karamanian industry fell sharply after a slump abroad.",
        "readings": ["a temporary external shock to be ridden out", "a sign the economy needs restructuring"],
        "tradeoffs": ["stimulus supports jobs but adds to the deficit", "restraint protects finances but deepens the slump"],
        "offices": {"treasury": "The slump abroad may last several months."}},
    "procurement_scandal": {"weight": _w_procurement, "duration": 2, "region": None, "tags": ["corruption", "military", "shipbuilding"],
        "title": "A military procurement scandal",
        "text": "",
        "readings": ["theft that must be prosecuted", "inevitable waste in hurried rearmament", "a smear against the armed forces"],
        "tradeoffs": ["an audit restores trust but delays equipment", "ignoring it keeps programmes on track but rewards graft"],
        "offices": {}},
    "officer_petition": {"weight": _w_petition, "duration": 2, "region": None, "tags": ["army", "military", "civil_military"],
        "title": "An officers' petition",
        "text": "Senior officers circulated a petition complaining that civilian leaders ignore military needs.",
        "readings": ["legitimate professional concern", "a political challenge to civilian authority"],
        "tradeoffs": ["meeting their demands calms the officers but costs money and sets a precedent",
                      "rebuking them asserts civilian control but risks loyalty"],
        "offices": {"army": "The petition has more signatures than any since independence."}},
    "police_disobedience": {"weight": _w_police_disobey, "duration": 1, "region": None, "tags": ["police", "protest_response"],
        "title": "Police units refuse orders",
        "text": "Some police units refused to carry out orders against demonstrators.",
        "readings": ["a collapse of discipline", "a conscience check on bad orders"],
        "tradeoffs": ["punishing them restores discipline but may spread refusal", "tolerating it keeps peace but weakens command"],
        "offices": {"interior": "Commanders cannot say how widespread the refusal is."}},
    "governor_defiance": {"weight": _w_governor, "duration": 2, "region": "highlands", "tags": ["regional_autonomy", "compliance"],
        "title": "A regional governor defies the capital",
        "text": "",
        "readings": ["insubordination to be stopped", "a warning that the region is not being heard"],
        "tradeoffs": ["replacing the governor asserts control but inflames the region", "negotiating concedes authority"],
        "offices": {"interior": "Regional officials are following the governor, not the ministry."}},
    "grain_shortage": {"weight": _w_grain, "duration": 2, "region": "aster", "tags": ["food", "rationing", "imports"],
        "title": "Grain shortage in the cities",
        "text": "Bakeries in the capital report shortages of flour and rising prices.",
        "readings": ["hoarding that controls should stop", "a real supply gap that only imports can fill"],
        "tradeoffs": ["price controls and rationing share the pain but discourage supply",
                      "buying abroad costs reserves"],
        "offices": {"treasury": "The state grain reserve is nearly exhausted."}},
}


def _setup(w: World, kind: str, rng) -> dict:
    """Hidden details and names for issues whose text depends on the current state."""
    spec = CATALOGUE[kind]
    details = {"text": spec["text"], "truth": {}, "target": None}
    if kind in ("corruption_ally",):
        corruption = w.institutions.get("corruption", {})
        head = w.holder("head")
        holders = [(o, w.holder(o)) for o in ("treasury", "interior", "army", "navy") if w.holder(o)]
        if not holders:
            return {}
        def weight(item):
            office, member = item
            ally = head.relationships.get(member.id, {}).get("trust", 50) if head and head.id != member.id else 50
            return corruption.get(office, 0) * 3 + member.agent_state.get("traits", {}).get("corruption_tolerance", 50) / 100 + ally / 100
        office, member = max(holders, key=lambda x: weight(x) + rng.random() * .3)
        details["target"] = member.id
        details["truth"] = {"true": rng.random() < .35 + corruption.get(office, 0) * 3}
        details["text"] = (f"Documents allege kickbacks in the {office} ministry, implicating {member.name}'s circle. "
                           "The evidence is suggestive, not conclusive.")
    elif kind == "foreign_investment":
        from_league = rng.random() < .7
        details["truth"] = {"investor": "league" if from_league else "union"}
        details["text"] = (("A Maritime League consortium" if from_league else "Investors linked to the Union")
                           + " offers to reopen idle mills in Kessel and Port Aster, employing thousands, in exchange for long-term control of port facilities.")
    elif kind == "false_warning":
        from .intelligence import union_offensive_risk
        real = union_offensive_risk(w) > .5
        details["truth"] = {"real": real}
        details["text"] = "A source inside the Union command warns of an attack within weeks. The source has not been tested."
    elif kind == "assassination_attempt":
        choices = [x for x in (_holder(w, "head"), _holder(w, "interior")) if x] or [m.id for m in w.active_members()]
        if not choices:
            return {}
        target = choices[0] if rng.random() < .6 else rng.choice(choices)
        details["target"] = target
        details["truth"] = {"organizer": rng.choice(("imperial restorationists", "a lone extremist", "unknown"))}
        details["text"] = f"A gunman fired on {w.member(target).name}'s car. {w.member(target).name} was unhurt; a driver was wounded."
    elif kind == "border_incident":
        details["truth"] = {"perpetrator": rng.choices(("union patrol", "smugglers", "our own troops"), (.5, .3, .2))[0]}
    elif kind == "loan_offer":
        league = rng.random() < .65
        details["truth"] = {"lender": "league" if league else "union"}
        details["text"] = ("The Maritime League offers new credit if Karamaniya caps its deficit and opens its ministries to audit."
                           if league else "Union banks offer credit on condition of talks on a customs union.")
    elif kind == "procurement_scandal":
        office = "navy" if w.policy.shipbuilding and w.holder("navy") else "army"
        holder = w.holder(office)
        if holder is None:
            return {}
        details["target"] = holder.id
        details["truth"] = {"true": rng.random() < .35 + float((w.institutions.get("corruption") or {}).get(office, 0)) * 4}
        details["text"] = f"Auditors found padded contracts in the {office} procurement programme overseen by {holder.name}."
    elif kind == "polling_threat":
        details["truth"] = {"election_month": w.const.election_month}
    elif kind == "governor_defiance":
        region = max(("kessel", "highlands", "dorran"), key=lambda r: _region_avg(w, r, "grievance"))
        details["region"] = region
        details["text"] = f"The governor of {REGION_NAMES[region]} refuses to implement ministry orders until regional demands are heard."
    return details


# ---- lifecycle -------------------------------------------------------------------------------
def generate(w: World) -> list:
    """Possibly raise new issues for next month, from the state the month ended in."""
    if w.ended():
        return []
    s = state(w)
    rng = rng_for(w.seed, w.month, "dilemmas-v2")
    base = float(tuning.get(w, "dilemmas.base_rate"))
    active_kinds = {d["kind"] for d in s["active"]}
    recent = {d["kind"] for d in s["history"] if w.month - d.get("month", -99) < 6}
    candidates = []
    for kind, spec in CATALOGUE.items():
        if kind in active_kinds or kind in recent:
            continue
        weight = spec["weight"](w)
        if weight > 0:
            candidates.append((kind, weight))
    candidates.sort(key=lambda x: -x[1])
    raised = []
    for kind, weight in candidates:
        if len(raised) >= int(tuning.get(w, "dilemmas.max_new_per_month")):
            break
        if len(s["active"]) + len(raised) >= int(tuning.get(w, "dilemmas.max_active")):
            break
        if rng.random() < base * weight:
            details = _setup(w, kind, rng)
            if details == {}:
                continue
            spec = CATALOGUE[kind]
            issue = {"id": f"I{w.month + 2}-{kind}", "kind": kind, "title": spec["title"], "month": w.month + 1,
                     "text": details.get("text") or spec["text"], "readings": spec["readings"],
                     "tradeoffs": spec["tradeoffs"], "tags": spec["tags"], "office_notes": spec["offices"],
                     "region": details.get("region", spec["region"]), "target": details.get("target"),
                     "truth": details.get("truth", {}), "status": "active",
                     "expires_month": w.month + 1 + spec["duration"], "applied": {}, "started": False}
            raised.append(issue)
    s["active"].extend(raised)
    for issue in raised:
        w.event("issue", f"New issue: {issue['title']}. {issue['text']}", importance=2, issue=issue["id"],
                member=issue.get("target"))
    return raised


def apply_ongoing(w: World) -> None:
    """Effects of live issues and emergency measures for the month being simulated."""
    s = state(w)
    mods = {"approval": {}, "grievance": {}, "repression": {}, "fear": {}, "indep": {}}
    def add(kind, where, value):
        mods[kind][where] = round(mods[kind].get(where, 0.0) + value, 4)
    for issue in s["active"]:
        if issue["month"] > w.month:
            continue
        first = not issue["started"]
        issue["started"] = True
        _effect(w, issue, first, add)
    _emergency_effects(w, add)
    regional.effects(w, add)
    s["modifiers"] = mods


def _effect(w: World, issue: dict, first: bool, add) -> None:
    kind, region = issue["kind"], issue.get("region")
    e, m, dip = w.econ, w.mil, w.dip
    applied = issue["applied"]
    if kind == "rail_blockade":
        if first:
            for rid, drop in (("kessel", .10), ("aster", .04)):
                r = w.region(rid)
                r.logistics = max(.3, r.logistics - drop)
                applied[rid] = applied.get(rid, 0) + drop
        add("approval", "*", -.004)
    elif kind == "polling_threat":
        add("fear", "*", .02)
    elif kind == "currency_pressure":
        z = w.zone_of("karamaniya")
        expected = (1 + z.exp_infl) ** 12 - 1
        if w.policy.rate < expected:
            e.fx_conf = clamp(e.fx_conf - .02, .05, 1.5)
    elif kind == "army_vs_loan":
        if w.policy.military < .04:
            m.army.morale = clamp(m.army.morale - .01)
    elif kind == "union_poll" and first:
        dip.propaganda = min(1.0, dip.propaganda + .03)
    elif kind == "leaked_plan" and first:
        m.army.training = clamp(m.army.training - .02)
        vel = w.foreign.get("actors", {}).get("veleria") if w.foreign else None
        if vel:
            vel["threat_perception"]["karamaniya"] = round(clamp(vel["threat_perception"]["karamaniya"] + .02), 3)
    elif kind == "corruption_ally" and first and issue.get("target"):
        from .standing import reputation_effect
        reputation_effect(w, issue["target"], "corruption", 1.0 if issue["truth"].get("true") else .6)
        w.event("corruption_allegation", issue["text"], importance=2, member=issue["target"])
    elif kind == "regional_autonomy":
        add("grievance", "highlands", .03)
    elif kind == "rationing_anger":
        for rid in ("lissen", "dorran"):
            add("grievance", rid, .025)
    elif kind == "police_killed" and first:
        m.police.morale = clamp(m.police.morale - .03)
        add("fear", "*", .015)
        _stress(w, _holder(w, "interior"), "security", 12)
    elif kind == "false_warning" and first:
        from . import intelligence
        s = intelligence.state(w)
        for office in ("army", "head"):
            if w.holder(office):
                est = 78.0
                s["reports"].append({"id": f"R{w.month + 1}-{office[:3].upper()}W", "month": w.month, "office": office,
                                     "subject": "union_intent", "estimate": est, "low": 70.0, "high": 85.0,
                                     "confidence": "medium", "proposition": "union_attack_soon", "alarming": True,
                                     "truth": intelligence.union_offensive_risk(w) * 100,
                                     "accurate": bool(issue["truth"].get("real")), "error": "none" if issue["truth"].get("real") else "deception",
                                     "shared_with": [], "requested_by": [],
                                     "text": "URGENT: a source inside the Union command warns of an attack within weeks (70-85%). "
                                             "The source is untested. Confidence: medium."})
    elif kind == "media_campaign" and first:
        dip.propaganda = min(1.0, dip.propaganda + .05)
    elif kind == "pay_crisis":
        m.army.morale = clamp(m.army.morale - .02)
        _stress(w, _holder(w, "army"), "security", 6)
    elif kind == "bank_panic" and first:
        for p in w.k_pops():
            if p.cls in ("middle", "elite"):
                p.savings *= .97
        e.confidence = clamp(e.confidence - .04)
        e.gold *= .97
    elif kind == "assassination_attempt" and first and issue.get("target"):
        _stress(w, issue["target"], "personal", 30)
        dip.rally = min(1.0, dip.rally + .04)
        add("fear", "*", .02)
        from .standing import ensure
        s = ensure(w, issue["target"])
        s["personal_approval"] = round(clamp(s["personal_approval"] + .03), 3)
    elif kind == "election_disinformation":
        dip.propaganda = min(1.0, dip.propaganda + .015)
        add("approval", "*", -.003)
    elif kind == "border_incident" and first:
        perpetrator = issue["truth"].get("perpetrator")
        vel = w.foreign.get("actors", {}).get("veleria") if w.foreign else None
        if vel and perpetrator == "our own troops":
            vel["threat_perception"]["karamaniya"] = round(clamp(vel["threat_perception"]["karamaniya"] + .03), 3)
        m.army.morale = clamp(m.army.morale + (.01 if perpetrator != "our own troops" else -.01))
    elif kind == "refugees" and first:
        for p in w.pops:
            if p.region == "dorran" and p.cls == "workers" and p.ident == "karamanian":
                p.size += 9000
                p.hunger = clamp(p.hunger + .02)
        add("grievance", "dorran", .02)
    elif kind == "naval_inspection" and first:
        e.goods_imports *= .97
        m.navy.morale = clamp(m.navy.morale - .02)
    elif kind == "storm" and first:
        for rid, damage in (("lissen", .03), ("aster", .015)):
            r = w.region(rid)
            r.damage = clamp(r.damage + damage)
            r.logistics = max(.3, r.logistics - .05)
            applied[rid] = applied.get(rid, 0) + .05
        e.food_stock *= .97
    elif kind == "industrial_strike":
        r = w.region(region or "kessel")
        r.strike = min(.4, r.strike + .08)
    elif kind == "civil_service_strike" and first:
        e.admin_capacity = clamp(e.admin_capacity - .05, .2, 1)
        e.compliance = clamp(e.compliance - .02, .3, 1)
    elif kind == "separatist_rally" and first:
        add("grievance", "kessel", .02)
    elif kind == "arms_cache" and first:
        w.event("arms_cache", issue["text"], importance=2)
        holder = _holder(w, "interior")
        if holder:
            from .standing import ensure
            ensure(w, holder)["reputation"]["competent"] = round(clamp(ensure(w, holder)["reputation"]["competent"] + 2, 0, 100), 1)
    elif kind == "intelligence_overreach":
        add("approval", "*", -.004)
        holder = _holder(w, "interior")
        if first and holder:
            from .standing import reputation_effect
            reputation_effect(w, holder, "repression", .6)
    elif kind == "export_boom" and first:
        e.gold += 6e6
        e.confidence = clamp(e.confidence + .03)
    elif kind == "recession_shock":
        if first:
            for rid in ("kessel", "aster"):
                r = w.region(rid)
                r.industry *= .97
                applied[f"industry:{rid}"] = .97
    elif kind == "procurement_scandal" and first and issue.get("target"):
        from .standing import reputation_effect
        reputation_effect(w, issue["target"], "corruption", .8)
        w.event("corruption_allegation", issue["text"], importance=2, member=issue["target"])
    elif kind == "officer_petition":
        m.army.loyalty = clamp(m.army.loyalty - .01)
        _stress(w, _holder(w, "army"), "institutional", 8)
    elif kind == "police_disobedience" and first:
        m.police.morale = clamp(m.police.morale - .03)
    elif kind == "governor_defiance":
        r = w.region(region or "highlands")
        if first:
            r.logistics = max(.3, r.logistics - .03)
            applied[r.id] = applied.get(r.id, 0) + .03
        e.compliance = clamp(e.compliance - .01, .3, 1)
    elif kind == "grain_shortage":
        add("fear", "aster", .01)


def review(w: World, record: dict | None) -> list:
    """Resolve issues whose conditions changed and expire old ones (after the month is simulated)."""
    s = state(w)
    ended = []
    for issue in list(s["active"]):
        if issue["month"] > w.month:
            continue
        outcome = _resolution(w, issue, record)
        if outcome is None and w.month + 1 >= issue["expires_month"]:
            outcome = "faded"
        if outcome is None:
            continue
        _undo(w, issue)
        issue["status"] = "resolved" if outcome != "faded" else "faded"
        issue["outcome"] = outcome
        issue["ended_month"] = w.month
        s["active"].remove(issue)
        s["history"].append(issue)
        ended.append(issue)
        if outcome != "faded":
            w.event("issue_resolved", f"{issue['title']}: {outcome}.", importance=1, issue=issue["id"])
    s["history"] = s["history"][-40:]
    return ended


def _resolution(w: World, issue: dict, record: dict | None) -> str | None:
    kind = issue["kind"]
    passed = [mo for mo in (record or {}).get("motions", []) if mo.get("passed")]
    pol, const = w.policy, w.const
    if kind == "rail_blockade":
        if pol.protest_response in ("disperse", "lethal"):
            for p in w.k_pops():
                if p.region == "kessel":
                    p.grievance = min(1.2, p.grievance + .05)
            return "the line was cleared by police"
        if (any(mo.get("subject") in ("welfare", "farm_support") for mo in passed) or _operation(w, "interior") == "regional_outreach"
                or "kessel" in regional.funded(w) or regional.settled(w, "kessel", since=issue["month"] - 1)):
            return "a negotiated settlement reopened the line"
    if kind == "currency_pressure":
        z = w.zone_of("karamaniya")
        if pol.rate >= (1 + z.exp_infl) ** 12 - 1:
            return "higher interest rates steadied the currency"
    if kind == "army_vs_loan" and pol.military >= .045:
        return "the council funded the army despite the loan conditions"
    if kind == "leaked_plan" and const.press != "free":
        return "publication was stopped under press restrictions"
    if kind in ("corruption_ally", "procurement_scandal") and issue.get("target"):
        report = audits.report_for(w, issue["target"], month=w.month)
        if report:
            return {"irregularities": "the audit found irregularities in the office",
                    "clean": "the audit found no wrongdoing",
                    "inconclusive": "the audit was inconclusive and the matter lapsed"}[report["verdict"]]
    if kind == "corruption_ally" and issue.get("target") and not w.offices_of(issue["target"]):
        return "the accused office holder left the post"
    if kind == "regional_autonomy":
        from .deliberation import concepts
        if (any(mo.get("type") == "amend" and "regional_autonomy" in concepts(mo.get("text", "")) for mo in passed)
                or regional.settled(w, "highlands", since=issue["month"] - 1)):
            for p in w.k_pops():
                if p.region == "highlands":
                    p.grievance = max(0.0, p.grievance - .1)
                if p.region == "kessel" and p.ident == "imperial":
                    p.grievance = min(1.2, p.grievance + .02)
            return "the council granted regional autonomy"
        if const.minority != "equal":
            return "minority restrictions hardened the conflict"
    if kind == "foreign_investment":
        investor = issue["truth"].get("investor")
        if any(mo.get("type") == "diplomacy" and mo.get("subject") in ("trade_deal", "trade_talks") for mo in passed):
            for rid in ("kessel", "aster"):
                w.region(rid).industry *= 1.02
            if investor == "league" and w.foreign:
                w.foreign["league"]["financial_exposure"] = round(clamp(w.foreign["league"]["financial_exposure"] + .05), 3)
            else:
                w.dip.propaganda = min(1.0, w.dip.propaganda + .04)
            return "the council accepted the investment"
    if kind == "rationing_anger" and (not pol.rationing or pol.farm_support >= .03):
        return "farm incentives were restored"
    if kind == "governor_defiance":
        rid = issue.get("region") or "highlands"
        if rid in regional.REGIONS and regional.settled(w, rid, since=issue["month"] - 1):
            return f"the {regional.REGIONS[rid]} settlement ended the standoff"
        if rid in regional.funded(w) and w.month > issue["month"]:
            return "regional funding brought the governor to terms"
    if kind == "pay_crisis" and w.mil.army.arrears < .5:
        return "soldiers' pay was brought up to date"
    if kind == "bank_panic" and (pol.capital_controls or pol.rate >= .12):
        return "capital controls or higher rates stopped the run"
    if kind == "intelligence_overreach" and pol.surveillance == "low":
        return "surveillance was scaled back"
    if kind == "officer_petition" and pol.officer_pay in ("raised", "premium") and pol.military < .045:
        return "the council raised officers' pay"
    if kind == "officer_petition" and pol.military >= .045:
        return "the council raised military funding"
    if kind == "polling_threat" and w.month >= issue["truth"].get("election_month", const.election_month) >= 0:
        protected = _operation(w, "interior") == "election_security" or pol.surveillance != "low"
        rng = rng_for(w.seed, w.month, "polling-attack")
        if not protected and rng.random() < .35:
            dead = rng.randint(3, 25)
            w.count("deaths_political_violence", dead)
            w.event("attack", f"A bomb exploded near a polling station; {dead} people were killed.", importance=3)
            return "an attack struck a polling station"
        return "the vote passed without major attacks"
    return None


def _undo(w: World, issue: dict) -> None:
    for key, value in issue.get("applied", {}).items():
        if key.startswith("industry:"):
            r = w.region(key.split(":", 1)[1])
            r.industry /= value
        else:
            r = w.region(key)
            r.logistics = min(1.1, r.logistics + value)
    issue["applied"] = {}


def _operation(w: World, office: str) -> str | None:
    return (w.institutions.get("operations") or {}).get(office, {}).get("focus")


def modifiers(w: World) -> dict:
    return state(w).get("modifiers") or {}


def active_for_prompt(w: World, mid: str) -> str:
    """Live issues in the public briefing, with office-specific notes for their holders."""
    items = [d for d in state(w)["active"] if d["month"] <= w.month]
    if not items:
        return ""
    offices = set(w.offices_of(mid))
    lines = ["LIVE ISSUES (no issue has a designated correct answer)"]
    for d in items:
        lines.append(f"- {d['title']} (since Month {d['month'] + 1}): {d['text']}")
        lines.append("  Competing readings: " + "; ".join(d["readings"]) + ".")
        lines.append("  Trade-offs: " + "; ".join(d["tradeoffs"]) + ".")
        for office, note in d.get("office_notes", {}).items():
            if office in offices:
                lines.append(f"  Your {office} staff: {note}")
    return "\n".join(lines)


def topics(w: World) -> set:
    out = set()
    for d in state(w)["active"]:
        out |= set(d.get("tags", []))
    return out


# ---- emergency measures (spec 46, 48) -----------------------------------------------------------
def set_emergency_measure(w: World, measure: str, on: bool, proposer: str, text: str = "") -> str:
    from .politics import EMERGENCY_MEASURES
    measures = w.institutions.setdefault("emergency_measures", {})
    log = w.institutions.setdefault("emergency_log", [])
    if not on:
        entry = measures.pop(measure, None)
        log.append({"month": w.month, "measure": measure, "action": "lifted", "by": proposer})
        return f"emergency measure lifted: {measure.replace('_', ' ')}" if entry else "no effect"
    current = measures.get(measure)
    if current:
        current["until"] = max(current["until"], w.month) + 3
        current["extensions"] = current.get("extensions", 0) + 1
        log.append({"month": w.month, "measure": measure, "action": "extended", "by": proposer})
        return f"emergency measure extended to Month {current['until'] + 1}: {EMERGENCY_MEASURES[measure]}"
    measures[measure] = {"since": w.month, "until": w.month + 3, "by": proposer, "extensions": 0,
                         "declared_emergency": w.const.emergency}
    log.append({"month": w.month, "measure": measure, "action": "imposed", "by": proposer})
    w.dip.league_trust -= .02
    return f"emergency measure imposed until Month {w.month + 4}: {EMERGENCY_MEASURES[measure]}"


def _emergency_effects(w: World, add) -> None:
    measures = w.institutions.get("emergency_measures") or {}
    if not measures:
        return
    legit = 1.0 if w.const.emergency else 2.0     # without a declared emergency the legitimacy cost doubles
    m = w.mil
    for name, entry in list(measures.items()):
        if w.month > entry["until"]:
            measures.pop(name)
            w.institutions.setdefault("emergency_log", []).append({"month": w.month, "measure": name, "action": "expired"})
            w.event("emergency_expired", f"The emergency measure on {name.replace('_', ' ')} expired.", importance=1)
            continue
        add("approval", "*", -.004 * legit)
        if name == "curfew":
            add("repression", "*", .08)
            add("grievance", "*", .01)
        elif name == "police_powers":
            add("repression", "*", .1)
            m.police.loyalty = clamp(m.police.loyalty + .005)
        elif name == "movement_restrictions":
            add("repression", "*", .05)
            for r in w.k_regions():
                if not r.capital:
                    r.logistics = max(.3, r.logistics - .01)
        elif name == "military_aid_civil":
            add("repression", "aster", .05)
            m.army.training = clamp(m.army.training - .01)
            m.army.bond = clamp(m.army.bond + .01)
        elif name == "ration_enforcement":
            add("repression", "*", .03)
            for rid in ("lissen", "dorran"):
                add("grievance", rid, .02)
        elif name == "fiscal_authority":
            add("approval", "*", -.002)
        w.dip.league_trust -= .005


def emergency_text(w: World) -> str:
    from .politics import EMERGENCY_MEASURES
    measures = w.institutions.get("emergency_measures") or {}
    if not measures:
        return ""
    return "Emergency measures in force: " + "; ".join(
        f"{EMERGENCY_MEASURES[k]} (since Month {v['since'] + 1}, expires after Month {v['until'] + 1}"
        + (f", extended {v['extensions']}x" if v.get("extensions") else "") + ")" for k, v in measures.items()) + "."
