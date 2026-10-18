"""The legitimacy factor on the national uprising, and the crackdown gamble (RR1).

Today the national uprising rule (``politics._revolution``) fires from approval and unrest alone:
a provisional government that keeps every democratic promise falls exactly as a junta does, and a
lethal crackdown is a certain win whenever security clears .55. This module adds the two missing
pieces behind the run option ``uprising_model``:

- under ``"legitimacy"`` the chance is multiplied by ``L``, a legitimacy factor that reads the
  democracy index, whether the government won an election, and a credible scheduled vote within
  12 months (plan 4.1; decisions file section 3);
- when the roll fires through the lethal gate, obedience is drawn separately for the police and
  the army instead of assumed (plan 4.2; decisions file sections 1-2). Both obey is the old
  massacre plus a 3-month backlash; one refusal is a split (a civil war when the arm is on,
  otherwise the uprising succeeds); both refusals are an uprising success.

Under ``"legacy"`` (the default) ``politics._revolution`` does not call any of this except
``massacre()``, whose body moved here unchanged: no new draw, no new history key, and a scripted
run's history rows are identical to the base commit 274ad98. The option is read defensively from
``w.uprising_model`` or ``w.institutions["uprising_model"]``; the lead wires the run option into
``config.py``/``runner.py``/``manifest.py`` at RR5.

Constants cite their source. The legitimacy constants are the plan's starting values, kept by the
lead's RR-1 decision (a provisional government gets the modest cut; concessions and the grace
period in RR2 do the rest). The crackdown formula is the lead's national one (decisions section
1): the regional ``society._protests`` base of .35 is for a single local force, and the national
case needs each force near .77-.89 to fail in the agreed 20-40% band at security .55-.65.
"""
from __future__ import annotations

from . import public_mood
from .military import _kill_civilians
from .world import clamp, democracy_index, rng_for

MODELS = ("legacy", "legitimacy")
DEFAULT_MODEL = "legacy"
OPTION_KEY = "uprising_model"
RECORD_KEY = "uprising_check"

# ---- legitimacy (plan 4.1; lead's RR-1 decision 3) -------------------------------------------
# L = max(L_MIN, 1 - a * D * (1 + elected) / 2 - b * D * near), a multiplier on the existing chance.
# A provisional government far from its vote gets about a 13.5-15% cut; the near-vote term adds up
# to a further 30% in the last year, and a won election doubles the base term. L can halve the
# odds at most (the user's decision 2): it never removes the chance.
A = 0.30                    # democracy protection, far from a vote (plan 4.1; lead decision 3)
B = 0.30                    # near-vote protection (plan 4.1; lead decision 3)
L_MIN = 0.50                # the factor's floor: at most half the odds (user's decision 2)
NEAR_MONTHS = 12            # a credible vote within this many months gives the near-vote term
COUP_MONTHS = 12            # a coup this recent makes every scheduled vote non-credible

# ---- the national crackdown draw (plan 4.2; lead's RR-1 decision 1) --------------------------
# obey(force) = clamp(.62 + .45*loyalty + .20*bond - .25*[unrest > .6] - .15 - arrears, .05, .98).
# The .15 is the lethal-order penalty the regional formula already carries: this branch is lethal
# by definition. The arrears penalty is .03 a month of pay owed, capped at .15. At loyalty .55-.65
# and bond .2-.3 each force sits near .76-.84 and both obey near .58-.71 (failure 29-42%); RR5's
# sweep calibrates the constants to the agreed 20-40% at security .55-.65.
CRACKDOWN_BASE = 0.62
CRACKDOWN_LOYALTY = 0.45
CRACKDOWN_BOND = 0.20
CRACKDOWN_UNREST = 0.25     # when national unrest is above .6
CRACKDOWN_LETHAL = 0.15     # the lethal-order penalty, as in society._protests
ARREARS_RATE = 0.03         # per month of pay owed ...
ARREARS_CAP = 0.15          # ... up to this
OBEY_MIN = 0.05
OBEY_MAX = 0.98

# ---- the backlash after a massacre (plan 4.2; Francisco 2004) --------------------------------
# Three months, as the plan says. `public_mood.KINDS` has no "unrest" kind; unrest is derived in
# society.update as `unrest = grievance * (1 - .75 * fear)`, so the unrest-side push is a second
# grievance reaction. The grievance channel multiplies a reaction by 4 into the target, so .03 is
# the strongest monthly push the channel allows (public_mood.LIMIT).
BACKLASH_MONTHS = 3
BACKLASH_GRIEVANCE = 0.03
BACKLASH_DECAY = 0.90       # most of the push survives each month: grievance decays more slowly
BACKLASH_UNREST = 0.01      # the unrest-side push, through its grievance driver
BACKLASH_REGION_UNREST = 0.33   # the region threshold society._protests uses for a protest


# ---- the run option ---------------------------------------------------------------------------
def model(w) -> str:
    """The run option in force. Absent reads as ``legacy``, so an old checkpoint is unchanged."""
    value = getattr(w, OPTION_KEY, None)
    if value is None:
        value = (getattr(w, "institutions", None) or {}).get(OPTION_KEY)
    if value is None:
        return DEFAULT_MODEL
    value = str(value).strip().lower()
    if value not in MODELS:
        raise ValueError(f"uprising_model must be 'legacy' or 'legitimacy', got {value!r}")
    return value


def enabled(w) -> bool:
    return model(w) == "legitimacy"


# ---- the legitimacy factor --------------------------------------------------------------------
def _near(w) -> float:
    """The near-vote term: 1 - months_left/12 for a credible vote within 12 months, else 0.

    A vote is not credible when it has been postponed past its Charter date (or, for an elected
    government, past the due date the win recorded), cancelled, rigged at the last count, or when
    a coup fell within the last 12 months. The lead's RR-1 decision 3 names all four.
    """
    c = w.const
    if w.policy.election_conduct == "rigged":
        return 0.0
    if w.month - c.coup_month < COUP_MONTHS:
        return 0.0
    if c.election_month < 0:
        return 0.0
    if c.elected:
        due = getattr(c, "election_due_month", -1)
        # A won election with no due date (an old checkpoint) reads as on time, as democracy_index does.
        if due >= 0 and c.election_month > due:
            return 0.0
    elif c.election_month > c.charter_election_month:
        return 0.0
    months_left = c.election_month - w.month
    if months_left < 0 or months_left > NEAR_MONTHS:
        return 0.0
    return clamp(1.0 - months_left / NEAR_MONTHS)


def legitimacy_factor(w) -> dict:
    """``D``, whether the government is elected, ``near`` and the multiplier ``L`` for this month."""
    D = democracy_index(w)
    elected = bool(w.const.elected)
    near = _near(w)
    L = max(L_MIN, 1.0 - A * D * (1 + (1 if elected else 0)) / 2.0 - B * D * near)
    return {"D": D, "elected": elected, "near": near, "L": L}


# ---- the month record -------------------------------------------------------------------------
def _record(w, approval: float, unrest: float, security: float, war_factor: float, factor: dict) -> dict:
    return {
        "month": w.month,
        "approval": round(approval, 9),
        "unrest": round(unrest, 9),
        "security": round(security, 9),
        "war_factor": round(war_factor, 9),
        "D": round(factor["D"], 9),
        "elected": factor["elected"],
        "near": round(factor["near"], 9),
        "L": round(factor["L"], 9),
    }


def record_idle(w, approval: float, unrest: float, security: float, war_factor: float) -> dict:
    """The month's check when the thresholds were not met: chance 0, no draw, recorded all the same.

    No draw is taken, so the month's ``"politics"`` stream is exactly the base's.
    """
    record = _record(w, approval, unrest, security, war_factor, legitimacy_factor(w))
    record.update({"thresholds_met": False, "base_chance": 0.0, "chance": 0.0,
                   "draw": None, "fired": False})
    w.institutions[RECORD_KEY] = record
    return record


def check(w, rng, approval: float, unrest: float, security: float, base_chance: float,
          war_factor: float) -> dict:
    """Apply the legitimacy factor and take the month's existing politics draw.

    ``rng`` is the month's ``"politics"`` stream and exactly one draw is taken from it, in the same
    place the legacy rule takes its draw. The record is stored on the world for the month row.
    """
    factor = legitimacy_factor(w)
    chance = clamp(base_chance * factor["L"])
    draw = rng.random()
    record = _record(w, approval, unrest, security, war_factor=war_factor, factor=factor)
    record.update({"thresholds_met": True, "base_chance": round(base_chance, 9),
                   "chance": round(chance, 9), "draw": round(draw, 9),
                   "fired": draw < chance})
    w.institutions[RECORD_KEY] = record
    return record


def month_record(w):
    """The check stored for the month just simulated, or None (legacy, or no check this month)."""
    if not enabled(w):
        return None
    record = (getattr(w, "institutions", None) or {}).get(RECORD_KEY)
    if not isinstance(record, dict) or record.get("month") != w.month:
        return None
    return record


# ---- the massacre and the backlash ------------------------------------------------------------
def massacre(w) -> None:
    """The existing massacre, unchanged: .08% of the population killed, grievance and fear up."""
    pop = w.population()
    dead = pop * 0.0008
    for r in w.k_regions():
        rp = [x for x in w.pops if x.region == r.id]
        share = sum(x.size for x in rp) / max(1.0, pop)
        _kill_civilians(w, r.id, dead * share, "deaths_state_violence")
    for x in w.k_pops():
        x.grievance = min(1.2, x.grievance + 0.15)
        x.fear = clamp(x.fear + 0.2)
    w.adjust_league_trust(-0.3)
    w.event("massacre", f"A nationwide uprising was crushed by force. About {dead:,.0f} people were "
            "killed.", importance=3)


def backlash(w) -> dict:
    """Three months of slower grievance decay and a monthly unrest push, in the regions that rose.

    ``public_mood`` has no unrest kind: unrest is derived from grievance (see the module docstring),
    so the unrest-side push is a second grievance reaction with its own reason. The regions are the
    ones above the protest threshold ``society._protests`` uses; if a unit world has no regional
    detail, the national uprising is treated as nationwide.
    """
    regions = [r.id for r in w.k_regions() if r.unrest > BACKLASH_REGION_UNREST] or ["*"]
    for where in regions:
        public_mood.react(w, "grievance", where, BACKLASH_GRIEVANCE, BACKLASH_MONTHS,
                          "uprising:backlash", decay=BACKLASH_DECAY)
        public_mood.react(w, "grievance", where, BACKLASH_UNREST, BACKLASH_MONTHS,
                          "uprising:backlash_unrest")
    return {"regions": regions, "months": BACKLASH_MONTHS,
            "grievance": BACKLASH_GRIEVANCE, "unrest_push": BACKLASH_UNREST,
            "decay": BACKLASH_DECAY}


# ---- the crackdown draw -----------------------------------------------------------------------
def obey_probability(force, unrest: float) -> float:
    """One force's chance of obeying a national lethal order, by the lead's national formula."""
    arrears = min(ARREARS_CAP, max(0.0, float(getattr(force, "arrears", 0.0) or 0.0)) * ARREARS_RATE)
    return clamp(CRACKDOWN_BASE + CRACKDOWN_LOYALTY * force.loyalty + CRACKDOWN_BOND * force.bond
                 - (CRACKDOWN_UNREST if unrest > 0.6 else 0.0) - CRACKDOWN_LETHAL - arrears,
                 OBEY_MIN, OBEY_MAX)


def _split_divisions(w, refusing_office: str, police_obey: float, army_obey: float) -> dict:
    """The armed split a refusing force hands ``civil_war.start``.

    The refusing force's refusal share (1 - obey) is its rebel share; the force that obeyed holds
    its whole share for the government; the other armed office keeps its anticipated-response split
    (``civil_war.armed_divisions``), as the lead's RR-1 decision 2 says.
    """
    from . import civil_war
    divisions = civil_war.armed_divisions(w)
    for office, obey in (("interior", police_obey), ("army", army_obey)):
        division = divisions[office]
        if office == refusing_office:
            division["obey_commander"] = round(1.0 - obey, 6)
            division["obey_government"] = round(obey, 6)
        else:
            division["obey_commander"] = 0.0
            division["obey_government"] = 1.0
        division["split"] = 0.0
        division["neutral"] = 0.0
    return divisions


def crackdown(w) -> dict:
    """Draw police and army obedience and apply the outcome. Returns the record for the month row.

    Every draw is on ``rng_for(seed, month, "uprising_crackdown")``, police first, so no other
    stream moves. Outcomes: ``massacre`` (both obey, the old effects plus the backlash),
    ``uprising_succeeds`` (both refuse; one refusal with the arm off; or a split whose refusing
    office is vacant and so has no commander to lead a faction), and ``civil_war`` (one refusal
    with ``civil_war = "on"``).
    """
    from . import civil_war
    police, army = w.mil.police, w.mil.army
    unrest = w.avg("unrest")
    police_obey = obey_probability(police, unrest)
    army_obey = obey_probability(army, unrest)
    rng = rng_for(w.seed, w.month, "uprising_crackdown")
    police_draw = rng.random()
    army_draw = rng.random()
    police_obeys = police_draw < police_obey
    army_obeys = army_draw < army_obey
    record = {
        "police": {"obey": round(police_obey, 9), "draw": round(police_draw, 9),
                   "obeyed": police_obeys},
        "army": {"obey": round(army_obey, 9), "draw": round(army_draw, 9), "obeyed": army_obeys},
        "refusing": [name for name, obeyed in (("police", police_obeys), ("army", army_obeys))
                     if not obeyed],
    }
    if police_obeys and army_obeys:
        massacre(w)
        record["backlash"] = backlash(w)
        record["outcome"] = "massacre"
        return record
    if not police_obeys and not army_obeys:
        # There is no government force left to fight a war with, so the arm changes nothing.
        record["outcome"] = "uprising_succeeds"
        return record
    office = "interior" if not police_obeys else "army"
    holder = w.holder(office)
    obey = police_obey if office == "interior" else army_obey
    if holder is None:
        # No commander, no faction: do not invent a leader (lead's RR-1 decision 2).
        record["vacant"] = [office]
        record["reason"] = f"the {office} office was vacant, so no commander could lead a faction"
        record["outcome"] = "uprising_succeeds"
        return record
    if not civil_war.enabled(w):
        record["outcome"] = "uprising_succeeds"
        return record
    state = civil_war.start(w, "crackdown_split", plotters=[holder.id],
                            divisions=_split_divisions(w, office, police_obey, army_obey))
    record["outcome"] = "civil_war" if state is not None else "uprising_succeeds"
    if state is not None:
        record["civil_war"] = {"cause": "crackdown_split", "leader": holder.id,
                               "rebel_share": round(1.0 - obey, 6)}
    return record
