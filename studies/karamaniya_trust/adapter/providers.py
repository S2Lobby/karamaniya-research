"""SocioVerse2 providers over the legacy seam: the four core interfaces, one council month per step.

A study migrates into SocioVerse2 by implementing EnvironmentProvider, PopulationProvider, DecisionModel and
MetricCollector (socioverse/abc). Here they are implemented through LegacySeam (engine_seam.py), which holds the
Karamaniya run. The legacy code is not edited; the seam takes the steps karamaniya.runner.new_run takes.

What one SocioVerse step means:
  build (population)  opens the run: the seats take the letters A-E, the questionnaire, the founding diagnoses.
  reset (environment) forms the government: the Month-0 vote gives the offices. This is E_0.
  step t, t = 1..n:
    advance_to        fires nothing. The engine draws its own shocks inside the month.
    observe_batch      reads the country as the delegates last saw it (the state before the month).
    decide_batch       runs ONE whole council month: openings, responses, votes, the world step, the foreign
                       cabinets. It keeps the legacy call pattern and reads what the month did into one Action
                       per delegate. A month never runs after the legacy loop would stop.
    apply              checks the legacy clock. The world step already ran inside decide_batch, so nothing is
                       folded in here.
    record             the panel and the metrics are read after the month.
"""

from __future__ import annotations

from pathlib import Path

from socioverse.abc import DecisionModel, EnvironmentProvider, MetricCollector, PopulationProvider
from socioverse.engine import LongitudinalSimulator
from socioverse.io import DuckDbTrajectoryStore
from socioverse.schemas import (
    Action,
    EnvironmentBundle,
    Observation,
    Persona,
    PopulationBundle,
    SimulationConfig,
)
from socioverse.validation import validate_handoff

from .engine_seam import STUDY_DIR, LegacySeam, step_bound

AGENT_PREFIX = "kar-"  # persistent ids: kar-A .. kar-E, the seat letters of the legacy run
METRIC_COLUMNS = (
    "approval", "inflation_yoy", "unrest", "food_ratio", "army",
    "active_members", "exits", "motions_voted", "motions_refused",
    "invalid_action_rate", "execution_mismatch_rate", "month_ran",
)


def member_of(agent_id: str) -> str:
    """The legacy seat letter of a persistent agent id (kar-A -> A)."""
    if not agent_id.startswith(AGENT_PREFIX):
        raise ValueError(f"not a delegate id: {agent_id!r}")
    return agent_id[len(AGENT_PREFIX):]


def _same_seed(seed: int, seam: LegacySeam) -> None:
    if int(seed) != seam.seed:
        raise ValueError(f"the simulator seed {seed} is not the legacy run's seed {seam.seed}")


class DelegatePopulation(PopulationProvider):
    """The five delegates, with persistent ids. build() opens the legacy run, which fixes who holds which letter."""

    def __init__(self, bundle: PopulationBundle, seam: LegacySeam):
        self.bundle = bundle
        self.seam = seam

    def build(self, seed: int) -> list[Persona]:
        _same_seed(seed, self.seam)
        self.seam.open()
        return [
            Persona(agent_id=AGENT_PREFIX + mid, attributes={"member": mid, **self.seam.seat(mid)},
                    init_state={"status": "active"})
            for mid in self.seam.member_ids()
        ]

    def interaction_structure(self):
        return self.bundle.interaction


class CouncilEnvironment(EnvironmentProvider):
    """The country and the offices. The legacy month changes the world in place, so E_t is read from the engine."""

    def __init__(self, bundle: EnvironmentBundle, seam: LegacySeam):
        self.bundle = bundle
        self.seam = seam

    def reset(self, seed: int) -> None:
        _same_seed(seed, self.seam)
        self.seam.form_government()

    def advance_to(self, t: int) -> list:
        return []

    def apply(self, actions: list[Action]) -> None:
        self.seam.check_clock()

    def observe_batch(self, agent_ids: list[str], t: int, round_idx: int = 0) -> list[Observation]:
        if round_idx:
            raise ValueError("a council month has one round (interaction_rounds = 1)")
        state = self.seam.country_state()
        out = []
        for aid in agent_ids:
            mid = member_of(aid)
            out.append(Observation(
                agent_id=aid, step=t, macro_physical=dict(state),
                local_information={"office": self.seam.office_of(mid), "status": self.seam.status_of(mid)},
            ))
        return out

    def agent_state(self, agent_id: str) -> dict:
        mid = member_of(agent_id)
        return {
            "member": mid,
            "seat": self.seam.seat(mid)["label"],
            "office": self.seam.office_of(mid),
            "status": self.seam.status_of(mid),
            "removed_how": self.seam.removed_how(mid),
        }

    def snapshot(self) -> dict:
        return self.seam.country_state()


class CouncilMonthDecision(DecisionModel):
    """One step is one legacy council month, run whole. Each delegate gets one Action for it."""

    def __init__(self, seam: LegacySeam):
        self.seam = seam

    def decide_batch(self, obs: list[Observation], memories: dict) -> list[Action]:
        seam = self.seam
        seam.begin_step()
        if not seam.may_run():
            return []  # the legacy loop has ended or stopped: no month runs and no action is recorded
        start = seam.statuses()
        start_office = {mid: seam.office_of(mid) for mid in seam.member_ids()}
        seam.run_month()  # the whole legacy month; a SeamPaused from a usage limit propagates
        end = seam.statuses()
        actions = []
        for ob in obs:
            mid = member_of(ob.agent_id)
            if start[mid] != "active":
                continue
            # Scripted seats are rule-following stand-ins; every other provider is a model.
            source = "rule" if seam.seat(mid)["provider"] == "scripted" else "llm"
            if end[mid] != "active":
                kind = "exit"
                payload = {"removed_how": seam.removed_how(mid), "office": start_office[mid]}
            else:
                kind = "council_month"
                payload = {"office": start_office[mid], **seam.member_acts(mid)}
            actions.append(Action(agent_id=ob.agent_id, step=ob.step, kind=kind, payload=payload, source=source))
        return actions


class CouncilMetrics(MetricCollector):
    """The per-step metrics, read from the engine's own month records (see LegacySeam.metrics_row)."""

    def __init__(self, seam: LegacySeam):
        self.seam = seam

    def collect(self, env, actions: list[Action], t: int) -> dict:
        return self.seam.metrics_row()

    def columns(self) -> list[str]:
        return list(METRIC_COLUMNS)


def load_bundles(study_dir: Path = STUDY_DIR):
    """The study's three JSON artifacts, validated against the SocioVerse2 schemas."""
    env = validate_handoff(study_dir / "environment" / "environment.json", EnvironmentBundle)
    pop = validate_handoff(study_dir / "population" / "population.json", PopulationBundle)
    sim = validate_handoff(study_dir / "simulation" / "simulation.json", SimulationConfig)
    return env, pop, sim


def build_karamaniya_simulator(*, config, runs_dir, name, months: int, seed: int, trajectory_dir,
                               check: bool = True):
    """Wire the four providers around one legacy run and return (LongitudinalSimulator, LegacySeam).

    The legacy run folder is runs_dir/name (the legacy's own layout). The panel, metrics and events go to
    trajectory_dir/study.duckdb. months and seed are the legacy run's values. The simulator runs step_bound(months)
    steps: the legacy run can extend past its month count after an election (see step_bound), and the steps it does
    not run record month_ran = 0.
    """
    env_b, pop_b, sim_b = load_bundles()
    seam = LegacySeam(config, runs_dir=runs_dir, name=name, months=months, seed=seed, check=check)
    store = DuckDbTrajectoryStore(Path(trajectory_dir) / "study.duckdb", study_id=sim_b.study_id)
    sim = LongitudinalSimulator(
        env=CouncilEnvironment(env_b, seam),
        population=DelegatePopulation(pop_b, seam),
        decision=CouncilMonthDecision(seam),
        store=store,
        collector=CouncilMetrics(seam),
        n_steps=step_bound(months),
        seed=int(seed),
        interaction_rounds=sim_b.interaction_rounds,
        memory_window=int(sim_b.engine_args.get("memory_window", 8)),
        metric_columns=["step", *METRIC_COLUMNS],
        study_id=sim_b.study_id,
    )
    return sim, seam
