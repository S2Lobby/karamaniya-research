"""RR1: uprising legitimacy and the crackdown gamble.

Entering the branch, every test here failed on the base (49a8d5b) except the legacy-identity test,
which passes there by construction. The fixture ``tests/fixtures/uprising_legacy_36m.json`` is the
history of a 36-month scripted run (``council.scripted.toml``) recorded on the base before any
change; ``python -m tests.test_rr1_uprising --record`` regenerates it on a base checkout.

What is tested:

- under ``uprising_model = "legacy"`` the engine is byte-identical: the same history rows as the
  base, and no ``uprising_check`` key anywhere;
- the legitimacy factor ``L``: it falls as the democracy index rises, as an election is won and as
  a credible vote comes near; it never falls below ``L_MIN``; a postponed, cancelled or rigged vote,
  or a coup within 12 months, removes the near-vote term;
- the crackdown draw: both obey is the massacre plus the 3-month backlash; one refusal starts a
  civil war only with ``civil_war = "on"`` and otherwise succeeds; both refusals succeed even with
  the arm on; a split whose refusing office is vacant succeeds and says so;
- the crackdown draws sit on ``rng_for(seed, month, "uprising_crackdown")`` and the month's
  ``"politics"`` stream is identical with and without the new model;
- the month row carries ``uprising_check`` under ``legitimacy`` only, including a zero-chance month,
  with the draws, the outcome and the refusing forces recorded.

    python -m unittest tests.test_rr1_uprising
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import engine, politics, public_mood  # noqa: E402
from karamaniya.world import clamp, new_world, rng_for  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTED = os.path.join(ROOT, "council.scripted.toml")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "uprising_legacy_36m.json")


# ---- worlds -----------------------------------------------------------------------------------
def uprising_world(seed: int = 1, month: int = 0, model: str | None = None, approval: float = 0.10,
                   unrest: float = 0.50, civil_war_option: str = "off"):
    """A world already in the uprising zone, with a lethal setting and a security above the gate."""
    w = new_world(seed, 36, civil_war_option=civil_war_option)
    w.month = month
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    for p in w.pops:
        p.approval = approval
        p.unrest = unrest
    w.policy.protest_response = "lethal"
    w.mil.police.loyalty = 0.6
    w.mil.army.loyalty = 0.6
    w.mil.police.bond = 0.2
    w.mil.army.bond = 0.2
    if model is not None:
        w.uprising_model = model
    return w


class Fires:
    """A politics stream whose draw always lands under the chance (p < 0.6 always)."""

    def random(self) -> float:
        return 0.0


class NoDraw:
    """A politics stream that fails the test if the check draws from it."""

    def random(self) -> float:
        raise AssertionError("the uprising check drew from the politics stream when it should not")


def crackdown_draws(seed: int, month: int) -> tuple:
    """The two draws the crackdown takes, in order: police, then army."""
    rng = rng_for(seed, month, "uprising_crackdown")
    return rng.random(), rng.random()


def month_matching(predicate, seed: int = 1) -> int:
    """The first month whose crackdown draws meet the predicate; the test states its own regime."""
    for month in range(36):
        if predicate(*crackdown_draws(seed, month)):
            return month
    raise AssertionError("no month in 0..35 has the draw shape this test needs")


def both_obey_month(seed: int = 1) -> int:
    # loyalty .95 and bond .9 put each force at the .98 cap.
    return month_matching(lambda police, army: police < 0.98 and army < 0.98, seed)


def both_refuse_month(seed: int = 1) -> int:
    # loyalty .6 with five months of arrears puts each force at .59 while security stays .6
    # (above the lethal gate's .55): the gate and a double refusal can hold at once.
    return month_matching(lambda police, army: police > 0.59 and army > 0.59, seed)


def police_refuses_month(seed: int = 1) -> int:
    return month_matching(lambda police, army: police > 0.59 and army < 0.98, seed)


def force_regime(w, police: tuple, army: tuple) -> None:
    for force, values in ((w.mil.police, police), (w.mil.army, army)):
        force.loyalty, force.bond = values[0], values[1]
        force.arrears = values[2] if len(values) > 2 else 0.0


# ---- the 36-month scripted run ----------------------------------------------------------------
def scripted_run(tmp: str, months: int = 36, seed: int = 1, model: str | None = None):
    """A scripted council (no model calls) run to its end or to ``months``; returns the world."""
    from karamaniya.backends.scripted import ScriptedBackend
    from karamaniya.config import load_config, normalize_config
    from karamaniya.council import Council
    from karamaniya.runner import _seats
    from karamaniya.storage import RunStore

    cfg = load_config(SCRIPTED)
    cfg = {**cfg, "run": {**cfg["run"], "tokens": {}, "foreign_cabinets": False,
                          "seed": seed, "months": months}}
    cfg = normalize_config({"run": cfg["run"], "seat": cfg["seats"]})
    mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
    cfg["mapping"] = mapping
    w = new_world(seed, months, member_ids=list(mapping),
                  founding_scenario=cfg["run"].get("founding_scenario", "random"),
                  founding_severity=cfg["run"].get("founding_severity", "default"))
    if model is not None:
        w.uprising_model = model
    seats = _seats(cfg, mapping)
    for seat in seats.values():
        seat.backend = ScriptedBackend(seat.cfg)
    os.makedirs(tmp, exist_ok=True)
    council = Council(w, seats, cfg["run"], RunStore(os.path.join(tmp, "r")))
    council.store.save_config(cfg)
    (council.store.path / "system_prompt.txt").write_text(council.system, encoding="utf-8")
    council.survey()
    council.diagnose_founding()
    council.form_government()
    while not w.ended() and w.month < months:
        council.run_month()
    return w


def row_digest(row: dict) -> str:
    """A row's hash, without the fingerprint that names the code version rather than the run."""
    data = {k: v for k, v in row.items() if k != "engine_source_fingerprint"}
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def record_fixture() -> dict:
    tmp = tempfile.mkdtemp(prefix="rr1-base-")
    try:
        w = scripted_run(tmp)
        return {"seed": 1, "months": 36, "row_count": len(w.history),
                "rows": [row_digest(row) for row in w.history],
                "outcome": json.loads(json.dumps(w.outcome))}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class LegacyIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rr1-legacy-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_legacy_36_month_scripted_run_matches_the_base(self):
        with open(FIXTURE, encoding="utf-8") as f:
            expected = json.load(f)
        w = scripted_run(self.tmp)
        self.assertEqual(len(w.history), expected["row_count"])
        self.assertEqual([row_digest(row) for row in w.history], expected["rows"])
        self.assertEqual(json.loads(json.dumps(w.outcome)), expected["outcome"])
        for row in w.history:
            self.assertNotIn("uprising_check", row)


# ---- the legitimacy factor --------------------------------------------------------------------
class LegitimacyFactor(unittest.TestCase):
    def setUp(self):
        from karamaniya import uprising
        self.uprising = uprising

    def test_l_falls_as_the_democracy_index_rises(self):
        w = new_world(1, 36)
        free = self.uprising.legitimacy_factor(w)
        w.const.press = "censored"
        w.const.assembly = "banned"
        w.const.emergency = True
        repressed = self.uprising.legitimacy_factor(w)
        self.assertGreater(free["D"], repressed["D"])
        # L multiplies the chance: a more democratic government gets the LOWER factor, i.e. fewer
        # uprisings; repression lowers D and gives the protection back.
        self.assertLess(free["L"], repressed["L"])

    def test_l_falls_with_a_won_election(self):
        w = new_world(1, 36)
        provisional = self.uprising.legitimacy_factor(w)
        w.const.elected = True
        elected = self.uprising.legitimacy_factor(w)
        self.assertEqual(provisional["elected"], False)
        self.assertTrue(elected["elected"])
        self.assertLess(elected["L"], provisional["L"])

    def test_l_falls_with_a_credible_vote_near(self):
        w = new_world(1, 36)
        far = self.uprising.legitimacy_factor(w)       # the vote is 35 months away
        self.assertEqual(far["near"], 0.0)
        w.month = 30                                    # five months to the Charter's Month 36
        near = self.uprising.legitimacy_factor(w)
        self.assertAlmostEqual(near["near"], 1 - 5 / 12, places=6)
        self.assertLess(near["L"], far["L"])

    def test_near_reads_the_months_left(self):
        w = new_world(1, 36)
        w.month = 29
        month_7 = self.uprising.legitimacy_factor(w)["near"]
        w.month = 35
        month_1 = self.uprising.legitimacy_factor(w)["near"]
        self.assertAlmostEqual(month_7, 1 - 6 / 12, places=6)
        self.assertAlmostEqual(month_1, 1.0, places=6)

    def test_a_rigged_win_does_not_count_as_an_election(self):
        w = new_world(1, 36)
        w.const.elected = True
        w.const.election_month = 40
        w.const.elections = [{"month": 0, "shares": {"Council List": 0.5}, "rigged": True,
                              "exposed": False}]
        rigged = self.uprising.legitimacy_factor(w)
        self.assertFalse(rigged["elected"])
        w.const.elections[0]["rigged"] = False
        fair = self.uprising.legitimacy_factor(w)
        self.assertTrue(fair["elected"])
        self.assertLess(fair["L"], rigged["L"])

    def test_l_never_falls_below_the_minimum(self):
        w = new_world(1, 36)
        w.const.elected = True
        w.const.election_month = w.month       # a near vote and a won election at once
        factor = self.uprising.legitimacy_factor(w)
        self.assertAlmostEqual(factor["L"], self.uprising.L_MIN, places=6)
        self.assertGreaterEqual(factor["L"], self.uprising.L_MIN)

    def test_postponed_cancelled_rigged_and_coup_remove_the_election_terms(self):
        from karamaniya import uprising
        cases = {
            "postponed": lambda w: setattr(w.const, "election_month", w.const.charter_election_month + 6),
            "cancelled": lambda w: setattr(w.const, "election_month", -1),
            "rigged": lambda w: setattr(w.policy, "election_conduct", "rigged"),
            "coup": lambda w: setattr(w.const, "coup_month", w.month),
        }
        for name, spoil in cases.items():
            with self.subTest(case=name):
                w = uprising_world(model="legitimacy")
                w.month = 30
                credible = uprising.legitimacy_factor(w)
                self.assertGreater(credible["near"], 0.0, "the near-vote term must be live first")
                spoil(w)
                spoiled = uprising.legitimacy_factor(w)
                self.assertEqual(spoiled["near"], 0.0)
                self.assertGreater(spoiled["L"], credible["L"], "the protection must be removed")


# ---- the crackdown gamble ---------------------------------------------------------------------
class Crackdown(unittest.TestCase):
    def setUp(self):
        from karamaniya import uprising
        self.uprising = uprising

    def legitimate_world(self, month: int, option: str = "off", police=(0.6, 0.0, 5.0),
                         army=(0.95, 0.9)):
        # Default regime: the police refuse (.59 obey after five months of arrears) while the army
        # obeys and security stays .775, above the lethal gate.
        w = uprising_world(month=month, model="legitimacy", civil_war_option=option)
        force_regime(w, police, army)
        return w

    def test_both_obey_is_the_massacre_plus_the_backlash(self):
        month = both_obey_month()
        w = self.legitimate_world(month, police=(0.95, 0.9))
        before = [(p.grievance, p.fear) for p in w.pops]
        politics._revolution(w, Fires())
        self.assertEqual(w.outcome, {}, "a massacre leaves the government in office")
        self.assertGreater(w.counters["deaths_state_violence"], 0)
        for p, (grievance, fear) in zip(w.pops, before):
            self.assertAlmostEqual(p.grievance, min(1.2, grievance + 0.15), places=9)
            self.assertAlmostEqual(p.fear, clamp(fear + 0.2), places=9)
        reactions = [entry for entry in public_mood.state(w)
                     if str(entry.get("reason", "")).startswith("uprising:backlash")]
        self.assertTrue(reactions, "the massacre must schedule the 3-month backlash")
        self.assertTrue(all(entry["kind"] == "grievance" for entry in reactions))
        record = w.institutions["uprising_check"]["crackdown"]
        self.assertEqual(record["outcome"], "massacre")
        self.assertEqual(record["refusing"], [])
        self.assertTrue(record["police"]["obeyed"])
        self.assertTrue(record["army"]["obeyed"])

    def test_one_refusal_with_the_arm_on_starts_a_civil_war(self):
        month = police_refuses_month()
        w = self.legitimate_world(month, option="on")
        politics._revolution(w, Fires())
        self.assertEqual(w.outcome, {}, "a split war leaves the run going")
        self.assertIsNotNone(w.civil_war)
        self.assertEqual(w.civil_war["cause"], "crackdown_split")
        self.assertEqual(w.civil_war["factions"]["rebels"]["leader"], "C")
        self.assertEqual(w.civil_war["factions"]["rebels"]["members"], ["C"])
        self.assertIn("A", w.civil_war["factions"]["government"]["members"])
        self.assertIn("D", w.civil_war["factions"]["government"]["members"])
        share = w.civil_war["factions"]["rebels"]["forces"]["interior"]["share"]
        self.assertAlmostEqual(share, 1 - self.uprising.obey_probability(
            w.mil.police, w.avg("unrest")), places=4)
        record = w.institutions["uprising_check"]["crackdown"]
        self.assertEqual(record["outcome"], "civil_war")
        self.assertEqual(record["refusing"], ["police"])
        self.assertEqual(record["civil_war"]["cause"], "crackdown_split")
        self.assertEqual(record["civil_war"]["leader"], "C")

    def test_one_refusal_with_the_arm_off_succeeds(self):
        month = police_refuses_month()
        w = self.legitimate_world(month, option="off")
        politics._revolution(w, Fires())
        self.assertIsNone(w.civil_war)
        self.assertIn(w.outcome.get("type"), ("revolution", "revolution_union"))
        self.assertEqual(w.active_members(), [])
        record = w.institutions["uprising_check"]["crackdown"]
        self.assertEqual(record["outcome"], "uprising_succeeds")
        self.assertEqual(record["refusing"], ["police"])

    def test_both_refuse_succeeds_even_with_the_arm_on(self):
        month = both_refuse_month()
        w = self.legitimate_world(month, option="on", police=(0.6, 0.0, 5.0),
                                  army=(0.6, 0.0, 5.0))
        politics._revolution(w, Fires())
        self.assertIsNone(w.civil_war, "there is no government force to fight a war with")
        self.assertIn(w.outcome.get("type"), ("revolution", "revolution_union"))
        record = w.institutions["uprising_check"]["crackdown"]
        self.assertEqual(record["outcome"], "uprising_succeeds")
        self.assertEqual(record["refusing"], ["police", "army"])

    def test_a_split_with_a_vacant_holder_succeeds_and_says_so(self):
        month = police_refuses_month()
        w = self.legitimate_world(month, option="on")
        w.const.offices["interior"] = None
        politics._revolution(w, Fires())
        self.assertIsNone(w.civil_war, "no commander means no faction to lead")
        self.assertIn(w.outcome.get("type"), ("revolution", "revolution_union"))
        record = w.institutions["uprising_check"]["crackdown"]
        self.assertEqual(record["outcome"], "uprising_succeeds")
        self.assertIn("interior", record["vacant"])
        self.assertTrue(record.get("reason"))

    def test_the_draws_are_on_the_uprising_crackdown_stream(self):
        month = both_obey_month()
        w = self.legitimate_world(month)
        police_draw, army_draw = crackdown_draws(w.seed, month)
        politics._revolution(w, Fires())
        record = w.institutions["uprising_check"]["crackdown"]
        self.assertAlmostEqual(record["police"]["draw"], police_draw, places=6)
        self.assertAlmostEqual(record["army"]["draw"], army_draw, places=6)

    def test_the_politics_stream_is_identical_with_and_without_the_model(self):
        # A month where the uprising fires in both twins (the politics draw lands under p) and both
        # forces obey, so the crackdown draws run under the new model.
        month = next(m for m in range(36)
                     if crackdown_draws(1, m)[0] < 0.98 and crackdown_draws(1, m)[1] < 0.98
                     and rng_for(1, m, "politics").random() < 0.12)
        legacy = uprising_world(month=month)
        force_regime(legacy, (0.95, 0.9), (0.95, 0.9))
        legitimate = uprising_world(month=month, model="legitimacy")
        force_regime(legitimate, (0.95, 0.9), (0.95, 0.9))
        legacy_rng = rng_for(legacy.seed, month, "politics")
        legitimate_rng = rng_for(legitimate.seed, month, "politics")
        politics._revolution(legacy, legacy_rng)
        politics._revolution(legitimate, legitimate_rng)
        self.assertEqual(legacy_rng.getstate(), legitimate_rng.getstate())
        self.assertEqual([legacy_rng.random() for _ in range(5)],
                         [legitimate_rng.random() for _ in range(5)])

    def test_the_obey_formula_is_the_leads_national_one(self):
        from karamaniya import uprising
        force = new_world(1, 36).mil.police
        force.loyalty, force.bond, force.arrears = 0.6, 0.2, 0.0
        expected = uprising.CRACKDOWN_BASE + 0.45 * 0.6 + 0.20 * 0.2 - 0.15
        self.assertAlmostEqual(uprising.obey_probability(force, 0.5), expected, places=9)
        # The terms the lead named: unrest above .6, the lethal penalty and the arrears cap.
        self.assertAlmostEqual(uprising.obey_probability(force, 0.7), expected - 0.25, places=9)
        force.arrears = 10.0
        penalised = uprising.CRACKDOWN_BASE + 0.45 * 0.6 + 0.20 * 0.2 - 0.15 - 0.15
        self.assertAlmostEqual(uprising.obey_probability(force, 0.5), penalised, places=9)
        force.loyalty, force.bond, force.arrears = 1.0, 1.0, 0.0
        self.assertAlmostEqual(uprising.obey_probability(force, 0.5), 0.98, places=9)


# ---- the month row ----------------------------------------------------------------------------
class MonthRow(unittest.TestCase):
    def setUp(self):
        from karamaniya import uprising
        self.uprising = uprising

    def test_the_legitimacy_row_carries_the_check_and_the_crackdown(self):
        month = both_obey_month()
        w = uprising_world(month=month, model="legitimacy")
        force_regime(w, (0.95, 0.9), (0.95, 0.9))
        politics._revolution(w, Fires())
        engine.snapshot(w)
        check = w.history[-1]["uprising_check"]
        self.assertAlmostEqual(check["approval"], 0.10, places=9)
        self.assertAlmostEqual(check["unrest"], 0.50, places=9)
        self.assertAlmostEqual(check["security"], 0.95, places=9)
        self.assertTrue(check["thresholds_met"])
        self.assertEqual(check["draw"], 0.0)
        self.assertGreater(check["chance"], 0.0)
        self.assertEqual(check["crackdown"]["outcome"], "massacre")

    def test_a_zero_chance_month_is_recorded_without_a_draw(self):
        w = uprising_world(model="legitimacy", approval=0.50, unrest=0.10)
        politics._revolution(w, NoDraw())
        engine.snapshot(w)
        check = w.history[-1]["uprising_check"]
        self.assertFalse(check["thresholds_met"])
        self.assertEqual(check["chance"], 0.0)
        self.assertIsNone(check["draw"])
        self.assertGreater(check["L"], 0.0)

    def test_legacy_rows_have_no_check_key(self):
        w = uprising_world(approval=0.50, unrest=0.10)
        politics._revolution(w, NoDraw())
        engine.snapshot(w)
        self.assertNotIn("uprising_check", w.history[-1])

    def test_a_real_engine_month_carries_the_zero_chance_record_only_under_legitimacy(self):
        w = new_world(1, 36)
        w.uprising_model = "legitimacy"
        engine.begin_month(w)
        engine.step(w)
        check = w.history[-1]["uprising_check"]
        self.assertFalse(check["thresholds_met"])
        self.assertEqual(check["chance"], 0.0)
        self.assertIsNone(check["draw"])
        legacy = new_world(1, 36)
        engine.begin_month(legacy)
        engine.step(legacy)
        self.assertNotIn("uprising_check", legacy.history[-1])


if __name__ == "__main__":
    if "--record" in sys.argv:
        data = record_fixture()
        os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
        with open(FIXTURE, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=1, sort_keys=True)
            f.write("\n")
        print(f"recorded {data['row_count']} rows to {FIXTURE}")
    else:
        unittest.main()
