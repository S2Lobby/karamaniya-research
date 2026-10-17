"""LegacySeam: the one place that drives the Karamaniya engine. Standard library only; no SocioVerse2 import.

Nothing in the legacy code is edited. The seam takes the steps of karamaniya.runner.new_run in the same order,
calling the legacy's own helpers, and runs one council month per call with the same checkpoint writes that
karamaniya.runner._loop makes. The SocioVerse2 providers (providers.py) call it.

The legacy checkout is found through $KARAMANIYA_ROOT (process environment only; no .env file is read) and
defaults to the repository this study sits in. Set KARAMANIYA_ROOT to run the study against another checkout.
"""

from __future__ import annotations

import datetime as dt
import os
import random
import sys
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_ROOT = Path(__file__).resolve().parents[3]
ROOT_ENV = "KARAMANIYA_ROOT"
# The keys runner._loop reports in its month_done event for each month; the seam reports the same ones.
STAT_KEYS = ("approval", "infl_yoy", "food_ratio", "army", "war", "unrest", "democracy")


def legacy_root() -> Path:
    """The checkout that holds the Karamaniya engine: $KARAMANIYA_ROOT when set, else the repository above this study."""
    raw = os.environ.get(ROOT_ENV, "").strip()
    root = Path(raw).resolve() if raw else _DEFAULT_ROOT
    if not (root / "karamaniya" / "runner.py").is_file():
        raise RuntimeError(f"{ROOT_ENV} is {root}, which does not hold the Karamaniya engine (karamaniya/runner.py)")
    return root


def _bootstrap() -> None:
    root = str(legacy_root())
    if root not in sys.path:
        sys.path.insert(0, root)


_bootstrap()

from karamaniya import manifest, naming, runner  # noqa: E402
from karamaniya.config import load_config  # noqa: E402
from karamaniya.council import Council, RunPaused  # noqa: E402
from karamaniya.engine import HANDOVER_EXTENSION  # noqa: E402
from karamaniya.society import inflation_yoy  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.versions import stamp  # noqa: E402
from karamaniya.world import month_label, new_world  # noqa: E402


def step_bound(months: int) -> int:
    """The most steps a run of `months` months can need.

    The legacy run ends at its own month count, but engine.step extends it by up to HANDOVER_EXTENSION months when a
    government owes a handover after an election (the month after the Charter's election, for example). Steps past
    the legacy end run no month and record month_ran = 0, so the trajectory keeps one row per step.
    """
    return int(months) + HANDOVER_EXTENSION


class SeamPaused(RuntimeError):
    """The legacy run stopped before a month finished: a seat hit a usage limit, or the spending cap was reached.

    The checkpoint is the last finished month, as the legacy loop leaves it. `python -m karamaniya resume <run_dir>`
    continues the same run folder with the legacy code.
    """


def _empty_facts() -> dict:
    return {"ran": 0, "exits": [], "motions_voted": 0, "motions_refused": 0, "mismatches": 0}


class LegacySeam:
    """One Karamaniya run, opened and driven one month at a time with the legacy's own steps.

    open()             the front of new_run: config, seat letters, world, council, questionnaire, diagnoses
    form_government()  the Month-0 vote, then the checkpoint before Month 1
    may_run()          False once the legacy loop would stop (an outcome, or a spending cap)
    run_month()        one whole council month and the checkpoint _loop writes after it
    finish()           the end of _loop and of new_run (_end: manifest refresh and report)
    """

    def __init__(self, config, *, runs_dir, name=None, months=None, seed=None, framing=None, survey=None,
                 check=True):
        cfg = config if isinstance(config, dict) else load_config(config)
        self.cfg = {**cfg, "run": dict(cfg["run"])}
        self._overrides = {"months": months, "seed": seed, "framing": framing, "survey": survey}
        self.runs_dir = Path(runs_dir)
        self.name = name
        self.check = check
        self.run_dir = None
        self.run_id = None
        self.store = None
        self.world = None
        self.council = None
        self.run = None
        self.mapping = {}
        # The seed is known before open(): the SocioVerse2 simulator asks for it first (population.build).
        self.seed = int(seed) if seed is not None else int(self.cfg["run"]["seed"])
        self.months_done = 0
        self.last_record = None
        self.step_facts = _empty_facts()
        self.stopped = ""
        self.trace = []
        self._phase = "new"
        self._paused_month = False

    # ---- opening ----------------------------------------------------------------------------

    def open(self) -> None:
        """new_run's front: the config, the seat letters, the world, the council, the questionnaire and diagnoses."""
        if self._phase != "new":
            raise RuntimeError("open() runs once per seam")
        cfg = self.cfg
        if self.check:
            runner._require_seats(cfg, None, "started")
        run = cfg["run"]
        for key, val in self._overrides.items():
            if val is not None:
                run[key] = val
        try:
            run["months"] = int(run["months"])
        except (TypeError, ValueError) as exc:
            raise ValueError("months must be between 1 and 120") from exc
        if not 1 <= run["months"] <= 120:
            raise ValueError("months must be between 1 and 120")
        if run.get("judge"):
            raise NotImplementedError("the wrap does not run judges: set judge = false in the council file")
        self.run, self.seed = run, int(run["seed"])
        labels = [s["label"] for s in cfg["seats"]]
        order = list(range(len(labels)))
        if run["shuffle_seats"]:
            random.Random(f"seats:{run['seed']}").shuffle(order)
        self.mapping = {runner.LETTERS[i]: labels[j] for i, j in enumerate(order)}
        created = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.run_id = self.name or f"{created}-seed{run['seed']}"
        self.store = RunStore(self.runs_dir / self.run_id)
        self.run_dir = self.store.path
        if self.store.exists("checkpoint.json"):
            raise FileExistsError(f"{self.store.path} already has a run; use resume")
        architecture = int(run.get("agent_architecture_version", 2))
        self.store.save_config({**cfg, "mapping": self.mapping, "created": created,
                                "architecture": stamp(architecture)})
        by_label = {s["label"]: s for s in cfg["seats"]}
        baselines = {letter: by_label[label].get("trait_baseline") for letter, label in self.mapping.items()
                     if by_label[label].get("trait_baseline")}
        self.world = new_world(run["seed"], run["months"], run["framing"], member_ids=list(self.mapping),
                               human_factor=run.get("human_factor", True),
                               founding_scenario=run.get("founding_scenario", "random"),
                               founding_severity=run.get("founding_severity", "default"),
                               founding_problems=run.get("founding_problems"),
                               agent_architecture_version=architecture, tuning=run.get("tuning"),
                               trait_baselines=baselines, ballot=run.get("ballot", "open"))
        self.store._write_json("manifest.json", manifest.build(self.world, {**cfg, "mapping": self.mapping}))
        self.council = Council(self.world, runner._seats(cfg, self.mapping), run, self.store, observer=None)
        if self.council.names:
            naming.save(self.store, self.council.names)
        prompt = self.council.names.out(self.council.system) if self.council.names else self.council.system
        (self.store.path / "system_prompt.txt").write_text(prompt, encoding="utf-8")
        self._phase = "open"
        self._save(survey_pending=bool(run["survey"]), founding_diagnosis_pending=True,
                   government_formation_pending=True)
        paused = runner._survey(self.store, self.council, None, True) if run["survey"] else ""
        if not paused:
            self._save(survey_pending=False, founding_diagnosis_pending=True, government_formation_pending=True)
        diagnosis_pending = False
        if not paused:
            paused = runner._diagnose(self.store, self.council, None, True)
            diagnosis_pending = bool(paused)
            if not paused:
                self._save(survey_pending=False, founding_diagnosis_pending=False,
                           government_formation_pending=True)
        if paused:
            self._stop_at_setup(paused, survey_pending=bool(run["survey"] and not diagnosis_pending),
                                diagnosis_pending=diagnosis_pending)

    def _save(self, **flags) -> None:
        self.store.save_checkpoint(self.world, self.council.state(),
                                   {"run_id": self.run_id, "stopped": "", "log_mark": self.store.mark(), **flags})

    def _stop_at_setup(self, paused: str, *, survey_pending: bool, diagnosis_pending: bool) -> None:
        self.store.save_checkpoint(self.world, self.council.state(), {
            "run_id": self.run_id, "stopped": paused, "log_mark": self.store.mark(),
            "survey_pending": survey_pending, "founding_diagnosis_pending": diagnosis_pending,
            "government_formation_pending": False})
        self.stopped = paused
        self._phase = "setup_paused"
        raise SeamPaused(paused)

    def form_government(self) -> None:
        """new_run's Month-0 step: the formation vote, the test scenario if one is set, the checkpoint before Month 1."""
        if self._phase != "open":
            raise RuntimeError("form_government() follows open()")
        paused = runner._form_government(self.store, self.council, None, True)
        if paused:
            self.store.save_checkpoint(self.world, self.council.state(), {
                "run_id": self.run_id, "stopped": paused, "log_mark": self.store.mark(),
                "survey_pending": False, "founding_diagnosis_pending": False,
                "government_formation_pending": True})
            self.stopped = paused
            self._phase = "setup_paused"
            raise SeamPaused(paused)
        runner._apply_scenario(self.world, self.run)
        self._save(survey_pending=False, founding_diagnosis_pending=False, government_formation_pending=False)
        self._phase = "formed"

    # ---- running months ---------------------------------------------------------------------

    def may_run(self) -> bool:
        """False once the legacy loop would stop: the run has an outcome, a pause was recorded, or the cap is reached."""
        if self.stopped or self.world.ended():
            return False
        cap = float(self.run.get("max_cost_usd") or 0.0)
        if cap and self.council.spend >= cap:
            self.stopped = f"spending cap of ${cap:.2f} reached"
            return False
        return True

    def run_month(self) -> dict:
        """One whole council month (the legacy's own council.run_month), then _loop's checkpoint for it."""
        if self._phase != "formed":
            raise RuntimeError("run_month() needs form_government() first")
        if not self.may_run():
            raise RuntimeError("the legacy loop has stopped; check may_run() before calling run_month()")
        if self.world.month != self.months_done:
            raise RuntimeError(f"legacy clock out of step: world month {self.world.month}, months run {self.months_done}")
        mark = self.store.mark()
        before = self.statuses()
        try:
            record = self.council.run_month()
        except RunPaused as exc:
            # _loop's own pause handling: the unfinished month's log lines go, and the checkpoint stays at the
            # last finished month. Not exercised by scripted seats; mirrors runner._loop lines 407-426.
            stopped = (f"paused in {month_label(self.world.month)}: {exc}. Resume when the limit resets; "
                       "the month will be replayed.")
            saved_world, saved_council_state, saved_meta = self.store.load_checkpoint()
            saved_council_state = dict(saved_council_state)
            saved_meta = dict(saved_meta or {})
            saved_spend = float(saved_council_state.get("spend", 0.0) or 0.0)
            attempt_spend = max(0.0, float(self.council.spend) - saved_spend)
            saved_meta = runner._stage_spend_recovery(self.store, saved_meta, attempt_spend)
            self.store.rollback(mark)
            saved_council_state["spend"] = saved_spend + attempt_spend
            saved_meta.pop("_pending_call_spend_recovery", None)
            saved_meta.update({"stopped": stopped, "log_mark": self.store.mark()})
            self.store.save_checkpoint(saved_world, saved_council_state, saved_meta)
            self.stopped = stopped
            self._paused_month = True
            raise SeamPaused(stopped) from exc
        self.store.save_checkpoint(self.world, self.council.state(), {"stopped": "", "log_mark": self.store.mark()})
        self.months_done += 1
        self.last_record = record
        after = self.statuses()
        voted = record.get("motions") or []
        refused = record.get("rejected_motions") or []
        self.step_facts = {
            "ran": 1,
            "exits": sorted(m for m, status in after.items() if before.get(m) == "active" and status != "active"),
            "motions_voted": len(voted),
            "motions_refused": len(refused),
            "mismatches": sum(1 for m in voted if m.get("condition_execution_mismatch")),
        }
        self.trace.append(self.month_state())
        return record

    def begin_step(self) -> None:
        """Clear the per-step facts before a step; a step with no month leaves them empty."""
        self.step_facts = _empty_facts()

    def finish(self):
        """The end of new_run: _loop's last checkpoint (or the pause's), then _end (manifest refresh and report)."""
        if self.store is None or self._phase in ("new", "open", "finished"):
            return self.run_dir
        if self._phase != "setup_paused":
            if self._paused_month:
                self.store.set_meta({"stopped": self.stopped})
            else:
                self.store.save_checkpoint(self.world, self.council.state(),
                                           {"stopped": self.stopped, "log_mark": self.store.mark()})
        self._phase = "finished"
        return runner._end(self.store, self.world, self.council, self.stopped, True, None)

    # ---- reading the legacy state (every legacy read goes through here) --------------------

    def month_state(self) -> dict:
        """The per-month state runner._loop reports in its month_done event: stats, members, offices, removed."""
        h = self.world.history[-1] if self.world.history else {}
        return {"stats": {k: h.get(k) for k in STAT_KEYS},
                "members": {m.id: m.status for m in self.world.members},
                "offices": dict(self.world.const.offices),
                "removed": {m.id: m.removed_how for m in self.world.members if m.status != "active"}}

    def check_clock(self) -> None:
        """The legacy clock and the study's steps move together: world.month counts the months run."""
        if self.world.month != self.months_done:
            raise RuntimeError(f"legacy clock out of step: world month {self.world.month}, months run {self.months_done}")

    def member_ids(self) -> list[str]:
        return list(self.mapping)

    def seat(self, mid: str) -> dict:
        label = self.mapping[mid]
        cfg = next(s for s in self.cfg["seats"] if s["label"] == label)
        return {"label": label, "provider": str(cfg.get("provider", "")), "model": str(cfg.get("model") or ""),
                "persona": str(cfg.get("persona") or "")}

    def statuses(self) -> dict:
        return {m.id: m.status for m in self.world.members}

    def status_of(self, mid: str) -> str:
        return self.world.member(mid).status

    def removed_how(self, mid: str) -> str:
        return self.world.member(mid).removed_how or ""

    def office_of(self, mid: str):
        for office, holder in self.world.const.offices.items():
            if holder == mid:
                return office
        return None

    def offices(self) -> dict:
        return dict(self.world.const.offices)

    def member_acts(self, mid: str) -> dict:
        """What one member did in the month that just ran, counted from the legacy month record."""
        record = self.last_record or {}
        return {"motions_tabled": sum(1 for m in record.get("motions") or [] if m.get("proposer") == mid),
                "motions_refused": sum(1 for r in record.get("rejected_motions") or [] if r.get("member") == mid)}

    def country_state(self) -> dict:
        """The country as the delegates last saw it: the latest finished month, or the founding state before Month 1."""
        w = self.world
        if not w.history:
            return {"approval": float(w.avg("approval")), "inflation_yoy": float(inflation_yoy(w)),
                    "unrest": float(w.avg("unrest")), "food_ratio": float(w.econ.food_ratio),
                    "army": float(w.mil.army.size)}
        h = w.history[-1]
        return {"approval": float(h["approval"]), "inflation_yoy": float(h["infl_yoy"]),
                "unrest": float(h["unrest"]), "food_ratio": float(h["food_ratio"]), "army": float(h["army"])}

    def metrics_row(self) -> dict:
        """One step's metrics, read from the engine's own records.

        invalid_action_rate: motions refused / (motions voted + refused), the refusals being the legacy's
        rejected_motions. execution_mismatch_rate: voted motions carrying condition_execution_mismatch (the legacy's
        own check that an executed condition differs from the accepted one) / motions voted. Both are 0.0 when
        the denominator is 0. Exits are members whose status went from active to removed during the step.
        """
        facts = self.step_facts
        voted, refused = facts["motions_voted"], facts["motions_refused"]
        active = sum(1 for m in self.world.members if m.status == "active")
        row = dict(self.country_state())
        row.update({
            "active_members": active,
            "exits": len(facts["exits"]),
            "motions_voted": voted,
            "motions_refused": refused,
            "invalid_action_rate": refused / (voted + refused) if voted + refused else 0.0,
            "execution_mismatch_rate": facts["mismatches"] / voted if voted else 0.0,
            "month_ran": facts["ran"],
        })
        return row
