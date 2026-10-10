"""The officers' plot: a bitter Army Command plots against the government, and the special branch can find it (engine 18).

In run 20261010-070501-seed1 the army stayed at 28,000 against a Union army of 100,000, the Army minister volunteered
his border post's records to a joint inquiry with the Union, and army loyalty rose all the same. Engine 17 gave the
ministries grievances that drag loyalty and morale, but a bitter Army Command still never plotted: the officers' coup
in politics._officers needs the soldiers unpaid for three months or the army office vacant for three, and a resentful
police carried out every order as before. Governments that humiliated or ignored their officer corps were often
overthrown by them, and the warning signs reached the security services first.

So a plot forms while the army's grievance is high and its loyalty to the state is low. Its strength builds while both
hold and fades when either lapses, so a grievance the government answers (the General Staff's request, the army paid,
its loyalty raised) defuses the plot without a rule of its own. The Interior's special branch can find it, and what it
finds reaches the Interior holder as an office report (intelligence.py). A plot strong enough may act, and a purge the
government has found the plot under disrupts it. No delegate is told what to decide: the plot is the world reacting to
how the government has treated its officers.
"""
from __future__ import annotations

from . import ministries
from .world import World, clamp, rng_for

PLOT_GRIEVANCE = .18        # the army's grievance (ministries.py) at which officers start to plot
PLOT_LOYALTY = .5           # the army's loyalty to the state below which they do
GROWTH = .15                # what a month of plotting adds to the plot's strength
GROWTH_GRIEVANCE = .25      # what a full step of grievance above PLOT_GRIEVANCE adds on top
GRIEVANCE_SPAN = .12        # the grievance above PLOT_GRIEVANCE that is a full step (ministries.MAX is .3)
FADE = .6                   # the share of its strength a plot keeps each month that one condition lapses
DISSOLVE_BELOW = .05        # a plot this weak has come to nothing
DETECT_BASE = .25           # the special branch's chance of finding a plot in a month, before the rest
DETECT_POLICE = .4          # ... plus this times the police's loyalty: the branch works through the police
DETECT_SURVEILLANCE = {"low": 0.0, "medium": .1, "high": .2}   # the policy's surveillance setting
COUP_STRENGTH = .8          # the strength at which the officers may act
COUP_CHANCE = .5            # the chance that they do, in a month when they may
PURGED_COUP_CHANCE = .15    # the chance once the plot is detected and the government runs a purge


def current(w: World) -> dict | None:
    """The plot this run has, or None."""
    return w.institutions.get("plot") or None


def strength(w: World) -> float:
    """The plot's strength from 0 to 1, or 0 when there is none."""
    plot = current(w)
    return float(plot["strength"]) if plot else 0.0


def detected(w: World) -> bool:
    """Whether the special branch has found the plot that exists now."""
    plot = current(w)
    return bool(plot and plot.get("detected"))


def detection_chance(police_loyalty: float, surveillance: str) -> float:
    """The special branch's chance of finding a plot this month."""
    return DETECT_BASE + DETECT_POLICE * police_loyalty + DETECT_SURVEILLANCE.get(surveillance, 0.0)


def coup_chance(found: bool, purge: bool) -> float:
    """The officers' chance of acting in a month when their plot is strong enough. A purge that the
    government runs after finding the plot disrupts it."""
    return PURGED_COUP_CHANCE if found and purge else COUP_CHANCE


def monthly(w: World) -> None:
    """A month passes: the plot forms, grows or fades, may be found, and may act. politics._officers calls this
    before the army's own checks. A world from before agent architecture 2 has no plots."""
    if w.agent_architecture_version < 2 or w.ended():
        return
    grievance = ministries.grievance(w, "army")
    plot = current(w)
    if grievance >= PLOT_GRIEVANCE and w.mil.army.loyalty < PLOT_LOYALTY:
        if plot is None:
            plot = {"since": w.month, "strength": 0.0, "detected": False, "months_detected": 0}
            w.institutions["plot"] = plot
            w.event("officers_plot", "Officers in Army Command have begun to plan against the government.",
                    public=False, importance=1)
        growth = GROWTH + GROWTH_GRIEVANCE * (grievance - PLOT_GRIEVANCE) / GRIEVANCE_SPAN
        plot["strength"] = round(clamp(plot["strength"] + growth), 4)
    elif plot is not None:
        plot["strength"] = round(plot["strength"] * FADE, 4)
    if plot is None:
        return
    if plot["strength"] < DISSOLVE_BELOW:
        w.institutions.pop("plot", None)
        return
    if not plot["detected"]:
        rng = rng_for(w.seed, w.month, "plot-detection")
        if rng.random() < detection_chance(w.mil.police.loyalty, w.policy.surveillance):
            plot["detected"] = True
            w.event("officers_plot_detected", "The Interior's special branch has learned of the officers' plot "
                    "against the government.", public=False, importance=2)
    if plot["detected"]:
        plot["months_detected"] += 1
    if plot["strength"] >= COUP_STRENGTH:
        rng = rng_for(w.seed, w.month, "plot-coup")
        if rng.random() < coup_chance(plot["detected"], w.policy.purge):
            _coup(w)


def _coup(w: World) -> None:
    """The officers seize power: the existing officers_coup outcome (politics._officers) with the plot's own text."""
    from .politics import remove_member     # imported here: politics reaches this module only through _officers
    w.outcome = {"type": "officers_coup", "month": w.month,
                 "text": "Army officers who had lost faith in the government seized power."}
    for mem in w.active_members():
        remove_member(w, mem.id, "officers_coup")
    w.count("coups_succeeded", 1)
    w.event("officers_coup", w.outcome["text"], importance=3)
