"""Are the world's dynamics in plausible ranges across many seeds and councils? (engine 18)

The engine watch (watch.py) flags a broken month inside one run. A bias that every run shares does not show inside
any one of them: every seed's inflation creeping up, or the neighbours' economies shrinking with no war. It shows
across runs. So each check here is one figure taken from a finished world's history, and the range a plausible world
stays inside, with a one-line reason for that range. tools/calibrate.py plays seeds and simple councils (baseline.MODES;
no model is called) and reports where the figures leave their ranges. docs/CALIBRATION.md says what to do then.

The evidence is run 20261010-070501-seed1. An engine bug charged every statement and offer of talks by a neighbour's
cabinet against that neighbour's real output, and kept charging it. The neighbours lost about 30% of their output in
nine months and prices across the shared crown rose 42%. It took nine months and a counterfactual run by hand to find.
rival_output_drift is the check aimed at that bug: a neighbour whose output falls 4% a month for nine months ends at
about 69% of its start, outside the range, in a run without war (tests/test_engine18_calibration.py reproduces it).

The ranges are about plausibility, not snapshots of what this engine produces today. Other engine-18 features will move
the figures. A range is changed only with a written reason beside it here and in docs/CALIBRATION.md, never to make a
failing run pass.

Months: a check reads every month of the run's history, as baseline.summary does. A run that played past its configured
length to carry out a handover (engine.py) is judged over the extra month too, and a run that stopped early over the
months it has. rival_output_drift reads each neighbour's output at the end of the run, so a fall that recovered before
the end is not seen by it; the monthly figures are kept in the JSON report of tools/calibrate.py for that.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from . import baseline

REFERENCE_MONTHS = 36   # the run length the ranges are written for; a check marked scales is pro rata for other lengths
SEATS = 5               # the stand-in councils have five seats, as baseline.compute assumes for a run without seats
PRINTING = 1e-4         # a monthly printing share above this counts as printing (watch.NO_PRINTING)
EMIGRATION_SHARE_36M = .15            # emigrants over 36 months, as a share of the starting population
ARMY_LOW, ARMY_HIGH = 5000, 200000    # Karamaniya's soldiers at every month
RIVAL_LOW, RIVAL_HIGH = .75, 1.25     # a neighbour's real output at the end, against its start, in a run without war


# ---- what a figure is and how it is judged -----------------------------------------------------------------
def _margin(value: float, low, high) -> float:
    """How far a figure sits inside its range, in its own units: negative when it is outside. Every check has a bound."""
    sides = []
    if low is not None:
        sides.append(value - low)
    if high is not None:
        sides.append(high - value)
    return min(sides)


def _closest_to_edge(values: list, low, high) -> float:
    """The figure that decides a check over several months or several neighbours: the one nearest an edge of its
    range, or furthest outside it. A run passes exactly when this figure is inside the range."""
    return min(values, key=lambda v: _margin(v, low, high))


@dataclass(frozen=True)
class Check:
    """One check: its figure (measure(history, world), or None where it does not apply), its range and why."""
    name: str
    measure: Callable
    low: float | None
    high: float | None
    reason: str
    unit: str               # how the figure is shown: "pct", "ratio" or "soldiers"
    scales: bool = False    # the high bound is pro rata to the run's months, against REFERENCE_MONTHS

    def bounds(self, months: int) -> tuple:
        high = self.high
        if high is not None and self.scales:
            high = high * months / REFERENCE_MONTHS
        return self.low, high

    def run(self, history: list, world) -> dict:
        """The check on one finished world. A check that does not apply to the run reports applies=False."""
        low, high = self.bounds(len(history))
        value = self.measure(history, world) if history else None
        if value is None:
            return {"applies": False, "value": None, "low": low, "high": high, "margin": None, "ok": None}
        margin = _margin(value, low, high)
        return {"applies": True, "value": value, "low": low, "high": high, "margin": margin, "ok": margin >= 0}


# ---- the figures ----------------------------------------------------------------------------------------------
def _mean(rows: list, key: str) -> float:
    return sum(float(row[key]) for row in rows) / len(rows)


def _at_war(history: list, world) -> bool:
    """A war in the run, counted as batch.py counts one: now, or in any month."""
    return bool(world.dip.war) or any(bool(row.get("war")) for row in history)


def _printed(row: dict) -> bool:
    """Whether Karamaniya, or a member of the zone that holds it, printed money that month (as watch._printing)."""
    if float((row.get("policy") or {}).get("printing", 0.0)) > PRINTING:
        return True
    if row.get("currency") == "karam":
        return False        # on its own currency Karamaniya's zone holds no neighbour
    return any(float(nation.get("monthly_printing", 0.0)) > PRINTING
               for name, nation in (row.get("nations") or {}).items() if name != "karamaniya")


def _inflation_mean(history, world):
    """Yearly inflation, averaged over the months of the run (the infl_yoy rows)."""
    return _mean(history, "infl_yoy")


def _inflation_monthly_peak(history, world):
    """The largest one-month rise of the zone's price level, in months with neither war nor printing."""
    rises = [cur["zone_price"] / prev["zone_price"] - 1.0
             for prev, cur in zip(history, history[1:])
             if not cur.get("war") and not _printed(cur)]
    return max(rises) if rises else None


def _unemployment_mean(history, world):
    return _mean(history, "unemployment")


def _approval_final(history, world):
    return float(history[-1]["approval"])


def _output_final(history, world):
    """Karamaniya's real output at the last month, against its start (gdp_idx)."""
    return float(history[-1]["gdp_idx"])


def _food_ratio_mean(history, world):
    return _mean(history, "food_ratio")


def _emigration_share(history, world):
    """People who emigrated over the run, as a share of the population at the first month (population_all)."""
    start = float(history[0]["population_all"])
    if start <= 0:
        return None
    return float(history[-1]["counters"].get("emigrated", 0.0)) / start


def _rival_output_drift(history, world):
    """Each neighbour's real output at the end against its start, the one furthest from its range's edge.

    Only a run without war is judged: a war moves a neighbour's output for reasons the ranges do not describe.
    """
    if _at_war(history, world):
        return None
    ratios = [rival.gdp_real / rival.gdp_real0 for rival in world.rivals.values() if rival.gdp_real0 > 0]
    return _closest_to_edge(ratios, RIVAL_LOW, RIVAL_HIGH) if ratios else None


def _army_size_bounds(history, world):
    """Karamaniya's army at every month: the month whose army is nearest an edge of the range, or furthest outside."""
    return _closest_to_edge([float(row["army"]) for row in history], ARMY_LOW, ARMY_HIGH)


CHECKS = {check.name: check for check in (
    Check("inflation_mean", _inflation_mean, low=-.02, high=.40, unit="pct",
          reason="Mean yearly inflation over the run: sustained deflation past -2%, or inflation above 40% a year, "
                 "means the price level has drifted rather than the economy moved."),
    Check("inflation_monthly_peak", _inflation_monthly_peak, low=None, high=.06, unit="pct",
          reason="The largest one-month rise of the zone's prices in a month with no war or printing: the watch "
                 "flags above 2% (watch.INFLATION_LIMIT), and 6% is the outer bound."),
    Check("unemployment_mean", _unemployment_mean, low=.02, high=.30, unit="pct",
          reason="Mean unemployment: the founding classes start at 2% to 6% (world.py), so an average outside 2% to "
                 "30% over years is a structural break, not a cycle."),
    Check("approval_final", _approval_final, low=.10, high=.85, unit="pct",
          reason="Approval in the last month: below 10% or above 85% is near-universal rejection or near-universal "
                 "acclaim, which a seed should not produce by default."),
    Check("output_final", _output_final, low=.55, high=1.50, unit="ratio",
          reason="Real output in the last month against the start: a fall to 55% or a rise to 150% in three years is "
                 "a structural break, not a business cycle."),
    Check("food_ratio_mean", _food_ratio_mean, low=.70, high=None, unit="ratio",
          reason="Food available over food needed, averaged over the run: under 70% for a whole run is a famine, not "
                 "a bad harvest."),
    Check("emigration_share", _emigration_share, low=None, high=EMIGRATION_SHARE_36M, scales=True, unit="pct",
          reason="People who emigrated over the run as a share of the starting population: 15% in 36 months is an "
                 "exodus; a shorter run gets the same rate pro rata."),
    Check("rival_output_drift", _rival_output_drift, low=RIVAL_LOW, high=RIVAL_HIGH, unit="ratio",
          reason="A neighbour's real output at the end against its start, in a run without war: the engine-15 bug "
                 "lost about 30% in nine months, so a move past 25% either way is more likely a charge the engine "
                 "made than a development."),
    Check("army_size_bounds", _army_size_bounds, low=ARMY_LOW, high=ARMY_HIGH, unit="soldiers",
          reason="Karamaniya's army at every month: 5,000 is a token force for a country of about 4.7 million, and "
                 "200,000 is about twice the 100,000 the evidence run set against its 28,000 (resolve.py)."),
)}


# ---- running a council and checking the world it made --------------------------------------------------------
def scripted_settings(council_path) -> dict:
    """The run settings of a council file, with survey and baseline off, as the baselines keep them."""
    from .config import load_config, normalize_config
    cfg = load_config(council_path)
    raw = {"run": {**cfg["run"], "survey": False, "baseline": False}, "seat": cfg["seats"]}
    return normalize_config(raw, str(council_path))["run"]


def simulate(settings: dict, seed: int, mode: str, months: int, runs_dir) -> tuple:
    """One council of stand-ins (a baseline.MODES mode) on one seed, played out under runs_dir: (world, seconds).

    No model is called. The run is made as baseline.compute makes its baselines, so the figures here are the ones a
    baseline of the same council would get.
    """
    from .config import normalize_config
    from .runner import new_run
    from .storage import RunStore
    if mode not in baseline.MODES:
        raise ValueError(f"unknown council mode {mode!r}; expected one of {', '.join(baseline.MODES)}")
    raw = baseline._config({**settings, "seed": seed}, SEATS, mode, months)
    cfg = normalize_config(raw, raw["source"])
    started = time.perf_counter()
    path = new_run(cfg, runs_dir=runs_dir, name=f"{mode}-seed{seed}-{months}m", quiet=True, check=False)
    seconds = time.perf_counter() - started
    world, _, _ = RunStore(path).load_checkpoint()
    return world, seconds


def evaluate(world) -> dict:
    """Every check on one finished world, by name (see Check.run). A world with no months cannot be checked."""
    history = list(world.history or [])
    if not history:
        raise ValueError("the world has no months to check")
    return {name: check.run(history, world) for name, check in CHECKS.items()}
