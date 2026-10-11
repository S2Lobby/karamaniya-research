"""Engine 19, infrastructure slice: the human factor switched off, the baselines, the scorecard and the tools.

Audit findings RU1, RU5 and MI5 (human_factor = false: the scripted stand-ins form a government, no psychology is
written, audits and public reactions still run), RU2 and RU4/FO6 (a baseline that stopped is not "ok"; the baselines'
neighbours always run as stand-in cabinets), RU7 (matrix --compare skips stopped runs), EC11 (the monthly-peak
calibration check says when it does not apply), CO9 (one unanimity rule everywhere), RU3 (secret-ballot runs record no
vote costs) and RU6 (bargain follow-through reads the month records as the engine writes them).
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import audits, baseline, calibration, convergence, engine, foreign, public_mood, runner, scorecard  # noqa: E402
from tools import matrix  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")


def scripted(human_factor: bool = True, months: int = 3, **run):
    """The five scripted seats of council.scripted.toml, with survey and baseline off, as the test suite builds them."""
    cfg = load_config(CONFIG)
    raw = {"run": {**cfg["run"], "survey": False, "baseline": False, "human_factor": human_factor,
                   "months": months, **run}, "seat": cfg["seats"]}
    return normalize_config(raw, "test")


class ScriptedFormationWithoutTraits(unittest.TestCase):
    """RU1: with the human factor off no delegate has traits, so the scripted formation vote must still be cast."""

    def test_the_formation_vote_is_cast_when_no_delegate_has_traits(self):
        w = new_world(1, 4, human_factor=False, member_ids=("A", "B", "C", "D", "E"))
        motions = [{"id": "F1", "type": "appointment", "office": "head", "member": "B"}]
        backend = ScriptedBackend({"provider": "scripted", "persona": "democrat"})
        res = backend.complete("system", "user", {"type": "object"},
                               {"world": w, "member": "A", "phase": "formation_vote", "formation_motions": motions})
        self.assertFalse(res.error, res.error)
        self.assertEqual(res.data["votes"], {"F1": "yes"})

    def test_a_run_without_the_human_factor_forms_a_government_and_plays_its_months(self):
        tmp = tempfile.mkdtemp(prefix="karamaniya-engine19-")
        self.addCleanup(shutil.rmtree, tmp, True)
        path = new_run(scripted(human_factor=False, months=3), runs_dir=tmp, name="nohf", quiet=True, check=False)
        world, _, meta = RunStore(path).load_checkpoint()
        self.assertEqual(meta.get("stopped"), "", meta.get("stopped"))
        self.assertEqual(len(world.history), 3)


def armed_world(human_factor: bool):
    """An architecture-2 world of the five seats, the army and navy offices held, as the engine's own checks build them."""
    w = new_world(5, 36, human_factor=human_factor)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


class InstitutionsWithoutTheHumanFactor(unittest.TestCase):
    """MI5: audits deliver and the public's reactions apply on the architecture version alone (engine.step)."""

    def test_an_audit_ordered_without_the_human_factor_reports_when_due(self):
        w = armed_world(human_factor=False)
        audits.open_audit(w, "army", "B", "Investigate the army procurement office.", {"B": "yes"})
        due = audits.open_for(w, "army")["due"]
        while w.month <= due:
            engine.begin_month(w)
            engine.step(w)
        self.assertIsNone(audits.open_for(w, "army"))
        self.assertEqual([r["office"] for r in audits.state(w)["done"]], ["army"])

    def test_a_public_reaction_reaches_the_society_without_the_human_factor(self):
        w = armed_world(human_factor=False)
        public_mood.react(w, "approval", "*", -0.03, 3, "poc:test")
        engine.begin_month(w)
        engine.step(w)
        self.assertAlmostEqual(w.dilemmas["modifiers"]["approval"]["*"], -0.03, places=4)
        self.assertEqual(len(public_mood.active(w)), 1)


class StoppedBaselines(unittest.TestCase):
    """RU2: a baseline mode that stopped is recorded as failed, with its stop reason, and the file is not "ok"."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-engine19-")
        cls.run_dir = new_run(scripted(human_factor=True, months=3), runs_dir=cls.tmp, name="finished", quiet=True,
                              check=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def compute_with_stopped_baselines(self):
        """baseline.compute where every baseline run is stopped before its first month, as the control room would."""
        real_new_run = runner.new_run

        def stopped(config, **kwargs):
            stop = threading.Event()
            stop.set()
            return real_new_run(config, stop_event=stop, **kwargs)

        with mock.patch.object(runner, "new_run", stopped):
            return baseline.compute(self.run_dir, modes=("passive",), force=True)

    def test_a_stopped_baseline_is_recorded_as_failed_with_its_stop_reason(self):
        out = self.compute_with_stopped_baselines()
        mode = out["modes"]["passive"]
        self.assertEqual(mode["status"], "failed", mode)
        self.assertIn("control room", mode["reason"])
        self.assertEqual(mode["months"], 0)

    def test_a_file_with_a_failed_baseline_is_not_ok(self):
        out = self.compute_with_stopped_baselines()
        self.assertNotEqual(out["status"], "ok")
        self.assertNotEqual(baseline.read(self.run_dir).get("status"), "ok")

    def test_a_failed_file_is_computed_again_rather_than_reused(self):
        self.compute_with_stopped_baselines()
        out = baseline.compute(self.run_dir, modes=("passive",))
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["modes"]["passive"]["status"], "ok")
        self.assertEqual(out["modes"]["passive"]["summary"]["months"], 3)


class BaselineNeighbours(unittest.TestCase):
    """RU4/FO6: the baselines' neighbours are the stand-in cabinets, whatever the run's foreign_cabinets setting."""

    def test_the_baseline_config_keeps_the_stand_in_cabinets_on(self):
        for setting in (True, False):
            run = baseline._config({"seed": 1, "human_factor": True, "foreign_cabinets": setting}, 5, "passive", 36)["run"]
            self.assertIs(run["foreign_cabinets"], True, f"run setting {setting}")

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-engine19-")
        settings = {"seed": 1, "human_factor": True, "foreign_cabinets": False}
        cfg = normalize_config(baseline._config(settings, 5, "passive", 36), "baseline:passive")
        path = new_run(cfg, runs_dir=cls.tmp, name="passive-beside-no-cabinets", quiet=True, check=False)
        cls.world, _, _ = RunStore(path).load_checkpoint()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_baseline_beside_a_run_without_cabinets_still_gets_veleria_ultimatums(self):
        self.assertTrue(self.world.foreign.get("stand_in"), self.world.foreign.get("stand_in"))


class MatrixCompareSkipsStoppedRuns(unittest.TestCase):
    """RU7: tools/matrix.py --compare averages finished runs only. A stopped run has no outcome, whatever its scorecard says."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-engine19-")
        cls.finished = Path(new_run(scripted(human_factor=True, months=3), runs_dir=cls.tmp, name="finished", quiet=True,
                                    check=False))
        stop = threading.Event()
        stop.set()
        cls.stopped = Path(new_run(scripted(human_factor=True, months=3), runs_dir=cls.tmp, name="stopped", quiet=True,
                                   check=False, stop_event=stop))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_stopped_run_is_not_read_even_though_it_has_a_scorecard(self):
        self.assertTrue((self.stopped / "scorecard.json").exists())
        self.assertIsNone(matrix.read_run(self.stopped))

    def test_compare_averages_only_the_finished_runs_and_skips_the_stopped_one(self):
        table, skipped = matrix.compare([self.stopped, self.finished])
        self.assertEqual(table[0]["runs"], 1)
        self.assertEqual(table[0]["outcomes"], "survived 1")
        self.assertEqual(skipped, [self.stopped])


def printing_history(readable: int, months: int = 12) -> list:
    """A history in which only `readable` month-on-month rises fall in a month with neither war nor printing."""
    return [{"zone_price": 100.0 * (1.01 ** i), "war": False, "currency": "karam",
             "policy": {"printing": 0.0 if 1 <= i <= readable else 0.01}} for i in range(months)]


class CalibrationPeakNeedsMonths(unittest.TestCase):
    """EC11: the monthly-peak check does not apply to a run in which too few months can be read, and says why."""

    def test_a_peak_read_from_two_months_does_not_apply_and_gives_the_reason(self):
        res = calibration.CHECKS["inflation_monthly_peak"].run(printing_history(readable=2), None)
        self.assertFalse(res["applies"])
        self.assertIsNone(res["value"])
        self.assertIn("2", res["reason"])

    def test_a_peak_read_from_the_minimum_number_of_months_applies(self):
        res = calibration.CHECKS["inflation_monthly_peak"].run(
            printing_history(readable=calibration.PEAK_MIN_MONTHS), None)
        self.assertTrue(res["applies"])
        self.assertAlmostEqual(res["value"], 0.01, places=6)


class SecretBallotCosts(unittest.TestCase):
    """RU3: a secret ballot costs no vote, so its scorecard says the costs were not recorded, not "0 of 0"."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-engine19-")
        cls.secret = Path(new_run(scripted(human_factor=True, months=6, ballot="secret"), runs_dir=cls.tmp,
                                  name="secret", quiet=True, check=False))
        cls.open = Path(new_run(scripted(human_factor=True, months=6), runs_dir=cls.tmp, name="open", quiet=True,
                                check=False))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_secret_ballot_run_reports_its_costs_as_not_recorded(self):
        members = scorecard.compute(RunStore(self.secret))["members"]
        for mid, member in members.items():
            self.assertIsNone(member["consensus"]["costly_of"], mid)
            self.assertIsNone(member["consensus"]["costly"], mid)

    def test_an_open_ballot_run_still_counts_its_costs(self):
        consensus = scorecard.compute(RunStore(self.open))["members"]["A"]["consensus"]
        self.assertIsInstance(consensus["costly_of"], int)


class CareerRecordReportedOnlyWithTheHumanFactor(unittest.TestCase):
    """A career record that an audit wrote into a delegate with no human factor is not reported as psychology."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-engine19-")
        cls.runs = {}
        for human in (True, False):
            path = Path(new_run(scripted(human_factor=human, months=3), runs_dir=cls.tmp, name=f"career-{human}",
                                quiet=True, check=False))
            checkpoint_file = path / "checkpoint.json"
            checkpoint = json.loads(checkpoint_file.read_text(encoding="utf-8"))
            member = next(m for m in checkpoint["world"]["members"] if m["id"] == "A")
            member["agent_state"]["standing"] = {"reputation": {"competent": 30.0}, "personal_approval": 0.2,
                                                 "influence": 0.3, "office_performance": {}}
            member["agent_state"]["grievances"] = [{"against": "B", "reason": "called an audit of your office",
                                                    "strength": 40.0, "month": 1}]
            checkpoint_file.write_text(json.dumps(checkpoint), encoding="utf-8")
            cls.runs[human] = path

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def card(self, human: bool) -> dict:
        return scorecard.compute(RunStore(self.runs[human]))["analytics"]["report_cards"]["A"]

    def member(self, human: bool) -> dict:
        return scorecard.compute(RunStore(self.runs[human]))["members"]["A"]

    def test_with_the_human_factor_the_career_record_is_reported(self):
        card = self.card(True)
        self.assertEqual(card["reputation"], {"competent": 30})
        self.assertEqual(card["personal_approval"], 0.2)
        self.assertEqual(len(self.member(True)["grievances"]), 1)

    def test_without_the_human_factor_no_career_record_is_reported(self):
        card = self.card(False)
        self.assertEqual(card["reputation"], {})
        self.assertIsNone(card["personal_approval"])
        self.assertIsNone(card["influence"])

    def test_without_the_human_factor_no_grievance_is_reported(self):
        self.assertEqual(self.member(False)["grievances"], [])


class BargainFollowthrough(unittest.TestCase):
    """RU6: a month record's social is keyed by member id, as the engine writes it, and the favours owed are read from it."""

    def test_a_favour_owed_in_the_engines_shape_is_listed(self):
        rec = {"month": 2, "social": {
            "A": {"favor_debts": [{"to": "B", "motion": "trade talks", "status": "active", "importance": 1}]},
            "B": {"favor_debts": []}}}
        self.assertEqual(convergence.bargain_followthrough([rec]),
                         [{"month": 2, "member": "A", "to": "B", "what": "trade talks", "status": "ACTIVE",
                           "importance": 1}])


def month_with_vote(votes: dict) -> dict:
    """One month's record holding one passed motion, as the council writes it (every eligible voter has a vote)."""
    motion = {"id": "M1", "type": "set_policy", "subject": "tax", "value": "0.2", "proposer": "A", "passed": True,
              "votes": votes, "eligible_voters": list(votes), "tally": "", "status": "PASSED",
              "result": "council directive: tax = 0.2", "execution_status": "EXECUTED"}
    return {"month": 0, "motions": [motion], "deferred_motions": [], "lapsed_motions": [], "agenda_notes": []}


def turn_one_yes_into_an_abstention(run_dir: Path) -> None:
    """Change one yes in a unanimous vote of three or more, in the run's own log, to an abstention."""
    log = run_dir / "log.jsonl"
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    for rec in records:
        for mo in (rec.get("motions", []) if rec.get("type") == "month" else []):
            votes = mo.get("votes") or {}
            if len(votes) >= 3 and set(votes.values()) == {"yes"}:
                votes[next(iter(votes))] = "abstain"
                log.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
                return
    raise AssertionError("the run has no unanimous vote of three or more to change")


class ScorecardAndAnalyticsAgree(unittest.TestCase):
    """CO9 on a real run: an abstention takes a vote out of the unanimous count in the scorecard and in the analytics."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-engine19-")
        cls.path = Path(new_run(scripted(human_factor=True, months=6), runs_dir=cls.tmp, name="votes", quiet=True,
                                check=False))
        cls.before = cls.counts()
        turn_one_yes_into_an_abstention(cls.path)
        cls.after = cls.counts()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def counts(cls) -> dict:
        division = scorecard.compute(RunStore(cls.path))["country"]["vote_division"]
        month_records = [r for r in RunStore(cls.path).read_log("month")]
        analytics = sum(convergence.month_analytics(r)["unanimous_votes"] for r in month_records)
        return {"scorecard_unanimous": division["unanimous"], "scorecard_contested": division["contested"],
                "analytics_unanimous": analytics}

    def test_the_abstention_takes_one_vote_out_of_the_scorecards_unanimous_count(self):
        self.assertEqual(self.after["scorecard_unanimous"], self.before["scorecard_unanimous"] - 1)
        self.assertEqual(self.after["scorecard_contested"], self.before["scorecard_contested"] + 1)

    def test_the_analytics_and_the_scorecard_count_the_same_unanimous_votes(self):
        self.assertEqual(self.after["analytics_unanimous"], self.after["scorecard_unanimous"])
        self.assertEqual(self.before["analytics_unanimous"], self.before["scorecard_unanimous"])


class OneUnanimityRule(unittest.TestCase):
    """CO9: a vote is unanimous when every member who could vote cast the same vote. An abstention breaks it."""

    def test_an_abstention_or_an_absence_breaks_unanimity(self):
        self.assertFalse(convergence.is_unanimous({"votes": {"A": "yes", "B": "yes", "C": "yes", "D": "abstain",
                                                             "E": "abstain"}}))
        self.assertTrue(convergence.is_unanimous({"votes": {"A": "no", "B": "no"}}))
        self.assertFalse(convergence.is_unanimous({"votes": {"A": "yes", "B": "no"}}))
        self.assertFalse(convergence.is_unanimous({"votes": {"A": "yes"}, "eligible_voters": ["A", "B"]}))
        self.assertFalse(convergence.is_unanimous({"votes": {}}))

    def test_the_monthly_analytics_do_not_call_three_yes_with_two_abstentions_unanimous(self):
        analytics = convergence.month_analytics(month_with_vote({"A": "yes", "B": "yes", "C": "yes",
                                                                 "D": "abstain", "E": "abstain"}))
        self.assertEqual(analytics["votes_cast"], 1)
        self.assertEqual(analytics["unanimous_votes"], 0)
        self.assertEqual(analytics["final_vote_unanimity"], 0.0)

    def test_the_monthly_analytics_still_call_five_yes_unanimous(self):
        analytics = convergence.month_analytics(month_with_vote({"A": "yes", "B": "yes", "C": "yes", "D": "yes",
                                                                 "E": "yes"}))
        self.assertEqual(analytics["unanimous_votes"], 1)


class NoPsychologyWithoutTheHumanFactor(unittest.TestCase):
    """RU5: a twelve-month run without the human factor writes no delegate psychology and reports none."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-engine19-")
        path = new_run(scripted(human_factor=False, months=12), runs_dir=cls.tmp, name="nohf12", quiet=True,
                       check=False)
        cls.world, _, cls.meta = RunStore(path).load_checkpoint()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_run_plays_all_twelve_months(self):
        self.assertEqual(self.meta.get("stopped"), "")
        self.assertEqual(len(self.world.history), 12)

    def test_no_delegate_acquires_traits_agendas_bases_or_relationships(self):
        for m in self.world.members:
            self.assertEqual(m.agent_state, {}, m.id)
            self.assertEqual(m.relationships, {}, m.id)

    def test_the_month_records_carry_no_member_psychology(self):
        self.assertTrue(all(row.get("member_social") == {} for row in self.world.history),
                        [sorted(row.get("member_social") or {}) for row in self.world.history][:3])


if __name__ == "__main__":
    unittest.main()
