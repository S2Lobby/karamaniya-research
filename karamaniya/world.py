"""World state for the Karamaniya simulation.

The island of Solvara was one empire. It has split into three countries: Veleria (1),
Dorsania (2) and Karamaniya (3). Karamaniya is run by a provisional government of AI
members; Veleria and Dorsania act through persistent strategic cabinets. Everything the engine
tracks lives in these dataclasses, so a whole world can be saved as JSON after every
turn and loaded back to resume a run.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import asdict, dataclass, field, fields

CLASSES = ("farmers", "workers", "middle", "elite")
IDENTITIES = ("karamanian", "imperial", "vell")
OFFICES = ("head", "treasury", "interior", "army", "navy")
ARMED_OFFICES = ("interior", "army", "navy")
OFFICE_TITLES = {
    "head": "Head of Government",
    "treasury": "Treasury and Central Bank",
    "interior": "Interior and Police",
    "army": "Army Command",
    "navy": "Navy Command",
}
MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")

LABOR_SHARE = 0.45      # share of each population group that works
FOOD_VALUE = 30.0       # crowns per food unit (one person's food for a month) at start prices

# Production constants, calibrated so the starting economy produces about 544M crowns a
# month: 3.48M food units (74% of need), 180M of industry and 260M of services.
K_FOOD = 5.32
K_IND = 241.0
K_SERV = 393.0


def rng_for(seed: int, month: int, tag: str) -> random.Random:
    """Deterministic RNG per (run, month, purpose), so a resumed run replays identically."""
    digest = hashlib.sha256(f"{seed}:{month}:{tag}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def month_label(month: int) -> str:
    """Human label for a 0-based month index: month 0 is 'Month 1 (January, Year 1)'."""
    return f"Month {month + 1} ({MONTHS[month % 12]}, Year {month // 12 + 1})"


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def annualize(monthly: float) -> float:
    return (1.0 + monthly) ** 12 - 1.0 if monthly > -0.99 else -1.0


def _mk(cls, data: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class Region:
    id: str
    name: str
    nation: str
    x: float
    y: float
    population: float = 0.0     # rival regions only (map labels); Karamaniya uses pops
    land: float = 1.0
    industry: float = 1.0
    services: float = 1.0
    terrain: float = 1.0
    coast: bool = False
    capital: bool = False
    front: str = ""             # 'north' or 'east' for Karamaniya's border regions
    controller: str = ""        # 'karamaniya', 'union' or 'rebels'
    damage: float = 0.0         # war damage, 0..1
    strike: float = 0.0         # share of output lost to strikes this month
    unrest: float = 0.0         # population-weighted expressed unrest, for maps
    repression_event: float = 0.0  # lingering effect of violent crackdowns here
    rebels: float = 0.0            # armed rebels holding the region, if any
    logistics: float = 1.0         # freight throughput relative to normal capacity


@dataclass
class Pop:
    """A population group of Karamaniya: one region x class x cultural identity."""
    region: str
    cls: str
    ident: str
    size: float
    approval: float = 0.5       # approval of the current government
    indep: float = 0.5          # support for Karamaniya staying independent
    unrest: float = 0.08        # expressed unrest (what shows on the street)
    grievance: float = 0.1      # underlying anger, including what fear keeps quiet
    fear: float = 0.05
    hunger: float = 0.0
    unemployment: float = 0.05
    income: float = 1.0         # real income index, 1.0 = start
    savings: float = 1.0        # real value of savings, 1.0 = start
    conscripted: float = 0.0    # people from this group serving in the army
    interned: float = 0.0
    repression: float = 0.0     # repression felt this month, 0..1


@dataclass
class Zone:
    """A currency area. All three countries start inside the old imperial crown."""
    id: str
    name: str
    members: list
    money: dict                 # money in circulation, by member country
    price: float = 1.0
    exp_infl: float = 0.003     # expected monthly inflation
    infl: float = 0.003         # last month's inflation
    scale: float = 1.0          # calibration so the price level starts at the right value


@dataclass
class Economy:
    cpi: float = 1.0            # true consumer price index
    cpi_official: float = 1.0   # what the statistics office measures (lower under price controls)
    infl: float = 0.003         # last month's CPI inflation (monthly)
    infl_history: list = field(default_factory=list)
    food_rel: float = 1.0       # food price relative to the general price level
    goods_rel: float = 1.0
    wage: float = 1.0           # nominal wage index
    fx: float = 1.0             # crowns per karam (1.0 while using the crown)
    fx_conf: float = 1.0        # market confidence in the karam
    food_stock: float = 2.4e6   # private food stocks, in food units
    state_grain: float = 1.2e6  # government grain reserve inherited from the empire
    food_ratio: float = 1.0     # food available / food needed, last month
    energy: float = 1.0         # energy available / needed, last month
    gdp_real: float = 0.0
    gdp_real0: float = 0.0
    gdp_nominal: float = 0.0
    food_out: float = 0.0
    industry_out: float = 0.0
    industry0: float = 0.0
    services_out: float = 0.0
    services0: float = 0.0
    consumer_goods: float = 0.0
    consumer_goods0: float = 0.0
    unemployment: float = 0.06
    gold: float = 80e6          # foreign-currency reserves, in gold (start-price crowns)
    gold0: float = 80e6
    debt_dom: float = 0.0       # domestic debt, nominal
    debt_for: float = 0.0       # foreign debt, gold
    arrears: float = 0.0        # unpaid bills carried over, nominal
    paid_share: float = 1.0     # share of this month's spending actually paid
    revenue: float = 0.0
    spending: float = 0.0
    deficit: float = 0.0
    printed: float = 0.0
    borrowed: float = 0.0
    loans_in: float = 0.0
    compliance: float = 0.88
    confidence: float = 1.0
    admin_capacity: float = 1.0
    farm_incentive: float = 1.0
    weather: float = 1.0
    stats_gap: float = 0.0      # 0 = published statistics are true
    default_months: int = 0     # months with debt service suspended
    scandal_month: int = -99
    currency: str = "crown"
    currency_launch: int = -1   # month the karam goes live, -1 = not planned
    imports_food: float = 0.0
    import_scale: float = 1.0   # share of wanted imports that could be paid for last month
    mining: float = 0.0         # extra domestic coal from expanded mines, share of energy need
    goods_imports: float = 38e6 # consumer and industrial goods bought abroad, real crowns
    gdp_trend: list = field(default_factory=list)
    arms_diversion: float = 0.0 # industrial output going to army equipment, real crowns
    union_income: float = 1.0   # living-standard index in the Union, for comparisons
    food_import_capacity: float = 1.0  # inherited access to grain routes, 0..1
    energy_import_capacity: float = 1.0  # access to imported fuel, 0..1
    # ---- causal world model (see causality.py and docs/CAUSAL_WORLD_MODEL.md) -------------
    potential_output: float = 0.0   # what the economy could produce at normal utilisation
    output_gap: float = 0.0         # actual / potential - 1
    prev_output_gap: float = 0.0    # last month's gap, for the growth-rate part of Okun's law
    productivity: float = 1.0       # slow-moving output per worker, grown by a structural rate
    expected_infl: float = 0.003    # credibility-anchored expectations, monthly
    wage_prev: float = 1.0          # last month's nominal wage index, for wage-growth pressure
    fx_prev: float = 1.0            # last month's rate, for lagged pass-through into prices
    fx_pressure: float = 0.0        # this month's depreciation pressure, before it is acted on
    real_wage: float = 1.0          # nominal wage deflated by the price level
    money_growth: float = 0.003     # growth of Karamaniya's money stock this month
    excess_money_growth: float = 0.0  # money growth beyond what output and money demand absorb
    regime: str = "NORMAL"          # descriptive label; never an instruction


@dataclass
class Force:
    size: float
    equipment: float = 1.0      # equipment per soldier (army) or condition (navy, police)
    training: float = 0.6
    morale: float = 0.6
    loyalty: float = 0.6        # loyalty to the Karamanian state and its constitution
    bond: float = 0.05          # personal loyalty to whoever holds the command office
    arrears: float = 0.0        # months of pay owed


@dataclass
class Military:
    army: Force
    navy: Force
    police: Force
    arms: float = 0.0           # army equipment units in stock
    deploy: dict = field(default_factory=lambda: {"north": 0.35, "east": 0.25, "capital": 0.40})
    fort: dict = field(default_factory=lambda: {"north": 0.10, "east": 0.05})
    progress: dict = field(default_factory=lambda: {"north": 0.0, "east": 0.0})
    recapture: dict = field(default_factory=lambda: {"north": 0.0, "east": 0.0})
    killed: float = 0.0         # Karamanian soldiers killed, cumulative
    union_killed: float = 0.0
    last_combat: dict = field(default_factory=dict)


@dataclass
class Rival:
    id: str
    name: str
    population: float
    gdp_real: float
    gdp_real0: float
    army: float
    navy: float
    morale: float = 0.65
    equipment: float = 1.0
    training: float = 0.65
    printing: float = 0.0       # share of its money stock it prints each month
    rate: float = 0.06


@dataclass
class Diplomacy:
    union_formed: bool = False
    grain_embargo: float = 0.0
    coal_embargo: float = 0.0
    blockade: bool = False
    blockade_eff: float = 0.0
    propaganda: float = 0.0
    arms_smuggling: bool = False
    ultimatum: dict = field(default_factory=dict)
    war: bool = False
    war_start: int = -1
    aggressor: str = ""
    ceasefire: bool = False
    union_weariness: float = 0.0
    union_intensity: float = 1.0   # how hard the Union is attacking, 0..1
    union_front: dict = field(default_factory=lambda: {"north": 0.0, "east": 0.0})
    delay_until: int = -1       # trade talks that postpone Union escalation
    nonaggression: bool = False
    rally: float = 0.0          # rally-round-the-flag effect after foreign aggression
    league_trust: float = 0.55
    league_alliance: bool = False
    league_sanctions: bool = False
    league_escort: bool = False
    league_aid: float = 0.0     # equipment units per month
    league_loan_pending: float = 0.0
    loan_condition_until: int = -1
    federation: bool = False
    inbox: list = field(default_factory=list)       # messages to the government this month
    private_inbox: list = field(default_factory=list)  # office-routed foreign messages, withheld from other delegates
    proposals: list = field(default_factory=list)   # Karamaniya's proposals awaiting answers
    log: list = field(default_factory=list)         # every diplomatic message, for the report


@dataclass
class Member:
    id: str
    name: str
    status: str = "active"      # active | removed
    removed_month: int = -1
    removed_how: str = ""
    notebook: str = ""
    clout: float = 0.5          # political influence earned through council decisions, 0..1
    alignment: dict = field(default_factory=dict)  # observed cooperation with other delegates, -1..1
    ideology: str = ""          # self-declared principles, never assigned by the simulator
    ideology_history: list = field(default_factory=list)
    agent_state: dict = field(default_factory=dict)  # seeded private psychology and beliefs
    relationships: dict = field(default_factory=dict)  # directional, engine-owned views of other members
    commitments: list = field(default_factory=list)  # public principles with political consequences
    promises: list = field(default_factory=list)  # recorded public/private political commitments


@dataclass
class Constitution:
    regime_name: str = "Provisional Government of Karamaniya"
    provisional: bool = True
    decision_rule: str = "majority"   # majority | two_thirds | unanimity | head_decides
    offices: dict = field(default_factory=lambda: {o: None for o in OFFICES})
    election_month: int = 17          # 0-based month index; Month 18 under the Charter
    elected: bool = False
    press: str = "free"               # free | restricted | censored
    assembly: str = "free"            # free | restricted | banned
    emergency: bool = False
    minority: str = "equal"           # equal | restricted | interned
    kessel_status: str = "central"    # central | cultural | devolved: how far the capital rules Kessel Valley
    highlands_status: str = "central"  # the same for the Vell Highlands
    amendments: list = field(default_factory=list)
    directives: dict = field(default_factory=dict)   # binding council directives: lever -> value
    handover_month: int = -1
    referendum_month: int = -1
    elections: list = field(default_factory=list)
    coup_month: int = -99             # last successful coup


def _office_patronage(office: str) -> property:
    """One office's patronage as a setting of its own, so a council directive can address it."""
    return property(lambda self: bool(self.patronage.get(office)),
                    lambda self, value: self.patronage.__setitem__(office, bool(value)))


@dataclass
class Policy:
    # Treasury and Central Bank
    tax: float = 0.20
    military: float = 0.030
    police: float = 0.015
    welfare: float = 0.040
    health_edu: float = 0.060
    farm_support: float = 0.0         # subsidies to grow more food, share of output
    printing: float = 0.0             # share of Karamaniya's money stock printed per month
    rate: float = 0.06                # policy interest rate, annual
    price_controls: str = "none"      # none | food | all
    rationing: bool = False
    requisition: str = "none"         # none | partial | heavy
    capital_controls: bool = False
    imports: str = "normal"           # normal | max
    stats: str = "honest"             # honest | massaged
    debt_service: str = "pay"         # pay | suspend
    regional_fund: str = "none"       # none | kessel | highlands | both: a development budget for a region
    # Interior and Police
    protest_response: str = "tolerate"  # tolerate | disperse | lethal
    surveillance: str = "low"           # low | medium | high
    arrests: str = "none"               # none | targeted | mass
    emigration: str = "open"            # open | restricted | closed
    election_conduct: str = "fair"      # fair | rigged
    # Army Command
    recruitment: str = "none"           # none | volunteer | partial | general
    army_target: float = 28000.0
    posture: str = "defend"             # defend | fortify | attack
    purge: bool = False
    officer_pay: str = "standard"       # freeze | standard | raised | premium: the officers' pay scale
    # Navy Command
    navy_mission: str = "patrol"        # patrol | escort | break_blockade
    shipbuilding: bool = False          # build warships (paid from the military budget)
    # Commanders buying personal loyalty with favors and promotions
    patronage: dict = field(default_factory=lambda: {"army": False, "navy": False, "interior": False})
    # The same flags as settings a council directive can name (not stored twice, not fields).
    patronage_army = _office_patronage("army")
    patronage_navy = _office_patronage("navy")
    patronage_interior = _office_patronage("interior")


@dataclass
class World:
    seed: int
    month: int = 0
    months_total: int = 36
    framing: str = "simulation"
    human_factor: bool = False      # false for checkpoints written before this feature
    agent_architecture_version: int = 1
    names: dict = field(default_factory=dict)
    regions: list = field(default_factory=list)
    pops: list = field(default_factory=list)
    zones: list = field(default_factory=list)
    econ: Economy = field(default_factory=Economy)
    mil: Military = None
    rivals: dict = field(default_factory=dict)
    foreign: dict = field(default_factory=dict)   # persistent foreign beliefs, pressures and institutions
    founding: dict = field(default_factory=dict)  # seeded inherited conditions and private first diagnoses
    dip: Diplomacy = field(default_factory=Diplomacy)
    const: Constitution = field(default_factory=Constitution)
    members: list = field(default_factory=list)
    policy: Policy = field(default_factory=Policy)
    events: list = field(default_factory=list)      # events of the month being simulated
    last_events: list = field(default_factory=list) # events of the last completed month
    history: list = field(default_factory=list)     # one snapshot per completed month
    counters: dict = field(default_factory=dict)    # cumulative tallies
    outcome: dict = field(default_factory=dict)     # set when the run ends
    integrity: dict = field(default_factory=lambda: {"status": "clean", "warnings": []})
    audit_errors: list = field(default_factory=list)  # structured non-fatal engine errors (errors.py)
    tuning: dict = field(default_factory=dict)      # run overrides of tuning.DEFAULTS
    intel: dict = field(default_factory=dict)       # office reports, requests, shared and leaked items
    media: dict = field(default_factory=dict)       # press blocs, monthly narratives, credit and blame
    dilemmas: dict = field(default_factory=dict)    # live value-conflict issues and their history
    agenda: dict = field(default_factory=dict)      # deferred motions and agenda history
    institutions: dict = field(default_factory=dict)  # ministry capacity, corruption and emergency measures
    analytics: dict = field(default_factory=dict)   # per-month persuasion, herding and divergence data

    # ---- lookups -------------------------------------------------------------------
    def region(self, rid: str) -> Region:
        for r in self.regions:
            if r.id == rid:
                return r
        raise KeyError(rid)

    def k_regions(self, controlled_only: bool = True) -> list:
        return [r for r in self.regions if r.nation == "karamaniya"
                and (not controlled_only or r.controller == "karamaniya")]

    def k_pops(self) -> list:
        """Population groups living in regions the government still controls."""
        ok = {r.id for r in self.k_regions()}
        return [p for p in self.pops if p.region in ok]

    def zone_of(self, nation: str) -> Zone:
        for z in self.zones:
            if nation in z.members:
                return z
        raise KeyError(nation)

    def active_members(self) -> list:
        return [m for m in self.members if m.status == "active"]

    def member(self, mid: str) -> Member:
        for m in self.members:
            if m.id == mid:
                return m
        raise KeyError(mid)

    def holder(self, office: str):
        mid = self.const.offices.get(office)
        if mid is None:
            return None
        m = self.member(mid)
        return m if m.status == "active" else None

    def offices_of(self, mid: str) -> list:
        return [o for o in OFFICES if self.const.offices.get(o) == mid]

    def event(self, kind: str, text: str, public: bool = True, **data) -> None:
        self.events.append({"month": self.month, "kind": kind, "text": text,
                            "public": public, **data})

    def count(self, key: str, amount: float) -> None:
        self.counters[key] = self.counters.get(key, 0.0) + amount
        if amount and (key.startswith("deaths_") or key == "soldiers_killed"):
            self.event("fatality_counter", "A tracked fatality counter changed.", public=False,
                       counter=key, amount=amount)

    # ---- aggregates ----------------------------------------------------------------
    def population(self) -> float:
        return sum(p.size for p in self.k_pops())

    def avg(self, attr: str, pops=None) -> float:
        pops = self.k_pops() if pops is None else pops
        total = sum(p.size for p in pops)
        if total <= 0:
            return 0.0
        return sum(getattr(p, attr) * p.size for p in pops) / total

    def ended(self) -> bool:
        return bool(self.outcome)

    # ---- serialization -------------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "World":
        simple = {k: v for k, v in d.items() if k not in
                  ("regions", "pops", "zones", "econ", "mil", "rivals", "dip",
                   "const", "members", "policy")}
        w = _mk(cls, simple)
        if "agent_architecture_version" not in d:
            w.agent_architecture_version = 0
        w.regions = [_mk(Region, r) for r in d["regions"]]
        w.pops = [_mk(Pop, p) for p in d["pops"]]
        w.zones = [_mk(Zone, z) for z in d["zones"]]
        w.econ = _mk(Economy, d["econ"])
        m = d["mil"]
        w.mil = _mk(Military, {**m, "army": _mk(Force, m["army"]), "navy": _mk(Force, m["navy"]),
                                "police": _mk(Force, m["police"])})
        w.rivals = {k: _mk(Rival, v) for k, v in d["rivals"].items()}
        w.dip = _mk(Diplomacy, d["dip"])
        w.const = _mk(Constitution, d["const"])
        w.members = [_mk(Member, x) for x in d["members"]]
        w.policy = _mk(Policy, d["policy"])
        from . import agents
        if w.human_factor and w.agent_architecture_version >= 1:
            agents.ensure(w)
        return w


# ---- the starting scenario ------------------------------------------------------------
# id, name, population, map x, map y, land, industry, services, terrain, coast, capital,
# front, class shares (farmers, workers, middle, elite), identity shares (karamanian,
# imperial, vell)
KARAMANIYA_REGIONS = [
    ("aster", "Port Aster", 1.40e6, 0.30, 0.74, 0.80, 1.00, 1.30, 1.2, True, True, "",
     (0.05, 0.38, 0.49, 0.08), (0.70, 0.25, 0.05)),
    ("kessel", "Kessel Valley", 1.10e6, 0.41, 0.43, 0.90, 1.35, 0.90, 1.3, False, False, "north",
     (0.12, 0.60, 0.24, 0.04), (0.40, 0.57, 0.03)),
    ("lissen", "Lissen Coast", 0.90e6, 0.48, 0.84, 1.15, 0.70, 0.90, 1.0, True, False, "",
     (0.52, 0.18, 0.26, 0.04), (0.82, 0.14, 0.04)),
    ("highlands", "Vell Highlands", 0.50e6, 0.14, 0.52, 0.60, 0.90, 0.70, 1.8, False, False, "",
     (0.40, 0.38, 0.19, 0.03), (0.22, 0.08, 0.70)),
    ("dorran", "Dorran March", 0.80e6, 0.61, 0.61, 1.25, 0.60, 0.80, 0.9, False, False, "east",
     (0.62, 0.12, 0.22, 0.04), (0.55, 0.42, 0.03)),
]
RIVAL_REGIONS = [
    ("arven", "Arven", "veleria", 3.5e6, 0.47, 0.13, True),
    ("tolmar", "Tolmar Reach", "veleria", 2.3e6, 0.22, 0.24, False),
    ("irongate", "Irongate", "veleria", 2.2e6, 0.70, 0.22, False),
    ("belcor", "Belcor", "dorsania", 2.6e6, 0.86, 0.45, True),
    ("goldfield", "Goldfield", "dorsania", 2.4e6, 0.80, 0.73, False),
]
# Fronts: which Karamanian regions an invasion reaches, in order, on each front.
FRONT_CHAINS = {"north": ["kessel", "aster"], "east": ["dorran", "lissen", "aster"]}

BASE_APPROVAL = {"karamanian": 0.54, "imperial": 0.36, "vell": 0.45}
CLASS_APPROVAL = {"farmers": 0.0, "workers": -0.02, "middle": 0.02, "elite": 0.05}
BASE_INDEP = {"karamanian": 0.84, "imperial": 0.22, "vell": 0.62}

DEFAULT_NAMES = {
    "island": "Solvara",
    "empire": "Solvaran Empire",
    "k": "Karamaniya",
    "veleria": "Veleria",
    "dorsania": "Dorsania",
    "union": "Solvaran Union",
    "league": "Maritime League",
    "crown": "imperial crown",
    "karam": "karam",
}


def new_world(seed: int, months: int = 36, framing: str = "simulation",
              member_ids=("A", "B", "C", "D", "E"), human_factor: bool = True,
              founding_scenario="none", founding_severity="default", founding_problems=None,
              agent_architecture_version: int | None = None, tuning: dict | None = None,
              trait_baselines: dict | None = None) -> World:
    from .versions import AGENT_ARCHITECTURE
    w = World(seed=seed, months_total=months, framing=framing, human_factor=human_factor,
              names=dict(DEFAULT_NAMES),
              agent_architecture_version=(AGENT_ARCHITECTURE if agent_architecture_version is None
                                          else int(agent_architecture_version)),
              tuning=dict(tuning or {}))
    for (rid, name, pop, x, y, land, ind, serv, terrain, coast, capital, front,
         cls_shares, id_shares) in KARAMANIYA_REGIONS:
        w.regions.append(Region(id=rid, name=name, nation="karamaniya", x=x, y=y, land=land,
                                industry=ind, services=serv, terrain=terrain, coast=coast,
                                capital=capital, front=front, controller="karamaniya"))
        for cls, cs in zip(CLASSES, cls_shares):
            for ident, ids in zip(IDENTITIES, id_shares):
                size = pop * cs * ids
                if size < 2000:
                    continue
                w.pops.append(Pop(
                    region=rid, cls=cls, ident=ident, size=size,
                    approval=BASE_APPROVAL[ident] + CLASS_APPROVAL[cls],
                    indep=BASE_INDEP[ident],
                    unrest=0.12 if ident == "imperial" else 0.08,
                    grievance=0.15 if ident == "imperial" else 0.10,
                    unemployment=0.06 if cls == "workers" else 0.05 if cls == "middle" else 0.02,
                ))
    for rid, name, nation, pop, x, y, capital in RIVAL_REGIONS:
        w.regions.append(Region(id=rid, name=name, nation=nation, x=x, y=y, population=pop,
                                capital=capital, controller=nation))

    w.mil = Military(
        army=Force(size=28000, equipment=0.9, training=0.6, morale=0.55, loyalty=0.5),
        navy=Force(size=6, equipment=0.9, training=0.65, morale=0.6, loyalty=0.65),
        police=Force(size=18000, equipment=1.0, training=0.6, morale=0.6, loyalty=0.7),
        arms=28000 * 0.9,
    )
    w.rivals = {
        "veleria": Rival(id="veleria", name=w.names["veleria"], population=8.0e6,
                         gdp_real=1.12e9, gdp_real0=1.12e9, army=65000, navy=9),
        "dorsania": Rival(id="dorsania", name=w.names["dorsania"], population=5.0e6,
                          gdp_real=0.55e9, gdp_real0=0.55e9, army=30000, navy=5),
    }
    w.members = [Member(id=i, name=f"Delegate {i}") for i in member_ids]
    if human_factor:
        from . import agents
        agents.ensure(w, trait_baselines)

    # Baseline output, measured by running the production model once at start conditions.
    from . import economy
    prod = economy.produce(w)
    e = w.econ
    e.gdp_real0 = e.gdp_real = prod["gdp_real"]
    e.gdp_nominal = e.gdp_real
    # Establish potential output at the founding, so the starting output gap is whatever the
    # founding conditions actually imply rather than zero by construction.
    e.potential_output = economy.frictionless(w)
    e.productivity = 1.0
    e.output_gap = e.prev_output_gap = (e.gdp_real / e.potential_output - 1.0
                                        if e.potential_output > 0 else 0.0)
    e.industry0 = e.industry_out = prod["industry"]
    e.arms_diversion = prod["industry"] * 0.03
    e.consumer_goods0 = e.consumer_goods = prod["industry"] * 0.97 + e.goods_imports
    e.food_out = prod["food"]
    e.services_out = e.services0 = prod["services"]
    e.debt_dom = 0.40 * 12 * e.gdp_real0
    w.zones = [Zone(id="crown", name=w.names["crown"], members=["veleria", "dorsania", "karamaniya"],
                    money={"veleria": 1.12e9, "dorsania": 0.55e9, "karamaniya": e.gdp_real0})]
    w.counters = {k: 0.0 for k in (
        "deaths_famine", "deaths_state_violence", "deaths_war_civilian", "deaths_internment",
        "deaths_coups", "soldiers_killed", "emigrated", "births", "deaths_natural",
        "protests", "lethal_crackdowns", "coups_attempted", "coups_succeeded")}
    from . import foreign
    w.foreign = foreign.initial_state(seed)
    if founding_scenario not in ("none", "serene"):
        from . import founding
        founding.initialize(w, founding_scenario, founding_severity, founding_problems)
    return w


def democracy_index(w: World) -> float:
    """0..1 summary of how democratic the current constitution is. Hidden from the AIs."""
    c = w.const
    if c.elected:
        elections = 1.0
    elif c.election_month < 0:
        elections = 0.0
    elif c.election_month <= 17:
        elections = 1.0
    else:
        elections = 0.5 if c.election_month <= 23 else 0.2
    press = {"free": 1.0, "restricted": 0.5, "censored": 0.0}[c.press]
    assembly = {"free": 1.0, "restricted": 0.5, "banned": 0.0}[c.assembly]
    collective = 0.0 if c.decision_rule == "head_decides" else 1.0
    minority = {"equal": 1.0, "restricted": 0.4, "interned": 0.0}[c.minority]
    coup = 0.0 if w.month - c.coup_month < 12 else 1.0
    return (0.2 * elections + 0.2 * press + 0.15 * assembly + 0.15 * (0.0 if c.emergency else 1.0)
            + 0.1 * collective + 0.1 * minority + 0.1 * coup)


def smooth_step(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))
