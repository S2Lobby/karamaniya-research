"""Engine 19, follow-ups A: the gaps the review left in the engine-19 fixes of the engine-18 audit.

Each class pins one follow-up (MI1-f, MO1-f, FO6-f, FO2-f, CO2-f). Each test was written to fail on the code the merged
fix left behind, and to pass once the follow-up is made. Nothing here calls a model.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import director, fine_print, foreign, foreign_force, military  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.council import Council  # noqa: E402
from karamaniya.runner import _seats  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

SCRIPTED = os.path.join(ROOT, "council.scripted.toml")

DEADLINE = 5
DEMAND = {"issued": 3, "deadline": DEADLINE, "terms": "Withdraw Karamaniyan forces from the regions on the border.",
          "terms_id": "demilitarize_border", "by": "veleria"}


def world(seed: int = 5):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def demanded(month: int = DEADLINE):
    """A world with Veleria's demand standing, the Union cohesive, and no cabinet answering this month."""
    w = world()
    w.month = month
    w.events = []
    w.dip.ultimatum = dict(DEMAND)
    w.foreign["union"]["cohesion"] = 0.85
    w.foreign["union"]["military_coordination"] = 0.80
    return w


def imposed_by_the_rule(month: int = DEADLINE):
    """The Union's rule has just enforced the expired demand with a blockade (director._deadline_policy)."""
    w = demanded(month)
    director._deadline_policy(w)
    assert w.dip.blockade and not w.dip.ultimatum, "the rule did not impose its blockade"
    return w


def fine_print_world(seed: int = 11):
    """fine_print reads a motion's offers only from agent architecture 2 (engine 17)."""
    w = world(seed)
    w.agent_architecture_version = 2
    return w


def standing_pay(w) -> float:
    """What military.update charges for the standing army and navy in a month, before any reserve."""
    pay = military.officer_pay(w)
    focus = military.training_intensity(w)
    return (w.mil.army.size * military.ARMY_COST * w.econ.cpi * pay["bill"] * focus["bill"]
            + w.mil.navy.size * military.SHIP_COST * w.econ.cpi)


def fiscal(mil_paid: float) -> dict:
    return {"mil_paid": mil_paid, "police_paid": 1e12}


class ReservePoolUpkeepIsNotCharged(unittest.TestCase):
    """MI1-f: the MI1 fix charged reserve_cost's monthly_total, which includes pool_monthly, the upkeep of the whole
    trained pool (about 5% of the army bill in a fresh world). No engine version charged it, so a month with no call-up
    went into arrears for reservists nobody called up. Only the embodied reservists' pay and this month's activation
    are charged; pool_monthly is still reported."""

    def test_a_month_with_no_call_up_is_paid_by_the_standing_force_alone(self):
        w = world()
        w.policy.mobilization = "none"
        w.policy.recruitment = "none"
        self.assertGreater(military.reserve_cost(w)["pool_monthly"], 0.0, "the pool's upkeep is still reported")
        military.update(w, fiscal(standing_pay(w) * 1.0001))
        self.assertEqual(w.mil.army.arrears, 0.0, "the trained pool's upkeep was charged with no call-up")

    def test_a_call_up_is_charged_its_pay_and_activation_and_not_the_pool_upkeep(self):
        w = world()
        w.policy.mobilization = "general"
        w.policy.recruitment = "none"
        pool = military.reserve_pool(w)
        embodied = pool * military.MOBILIZATION_SHARE["general"]
        bill = military.reserve_cost(w, pooled=pool, embodied=embodied)
        charged = standing_pay(w) + bill["embodied_monthly"] + bill["activation_one_off"]
        military.update(w, fiscal(charged * 1.0001))
        self.assertEqual(w.mil.army.arrears, 0.0, "the pool's upkeep was charged on top of the call-up's bill")


class ClauseAfterACommaIsAClause(unittest.TestCase):
    """MO1-f: a negator anywhere from the start of a clause rules out an offer, and a comma did not start a clause.
    So "Since the Union rejected our offer, we propose a joint inquiry" offered no inquiry. A comma or "and" before a
    new subject now starts a clause; a refusal in the same clause still rules out what it governs."""

    def test_an_offer_after_a_comma_that_rejects_something_else_is_an_offer(self):
        self.assertEqual(fine_print.clauses(
            fine_print_world(), "Since the Union rejected our offer, we propose a joint inquiry into the shooting.",
            "union"), ["joint_inquiry"])

    def test_an_offer_joined_by_and_after_a_refusal_is_an_offer(self):
        self.assertEqual(fine_print.clauses(
            fine_print_world(), "We will not cede land, and we propose a joint inquiry into the border shooting.",
            "union"), ["joint_inquiry"])

    def test_refusals_stay_refusals(self):
        for text in ("We reject the Union's call for a joint inquiry",
                     "We reject any joint inquiry, any stand-down and any inspection",
                     "The council rejects the ultimatum and refuses a stand-down"):
            with self.subTest(text=text):
                self.assertEqual(fine_print.clauses(fine_print_world(), text, "union"), [])


class TheUnionsRuleLiftsItsBlockade(unittest.TestCase):
    """FO6-f: a blockade the Union's rule imposed on an expired demand was lifted by nothing but a ceasefire or a
    cabinet's own lift, so a run without cabinets kept it for good (a reproduction held it for 24 months with the Union
    cohesive and no talks). The rule now lifts it in a month it decides for its actor, with no war, once Karamaniya has
    opened status talks since it began, after four months, or when the Union's cohesion is at or below .55. A cabinet's
    blockade and a war's blockade are not the rule's to lift."""

    def test_the_rule_records_its_blockade_as_its_own(self):
        w = imposed_by_the_rule()
        self.assertEqual(w.foreign["rule_blockade"], {"month": DEADLINE, "by": "veleria"})

    def test_a_blockade_is_not_lifted_in_the_month_the_rule_imposes_it(self):
        w = demanded()
        director._union_reply(w, "status_talks")      # talks opened earlier in the same month, before the imposition
        director._deadline_policy(w)
        self.assertTrue(w.dip.blockade)
        director._foreign_cabinets(w)
        self.assertTrue(w.dip.blockade, "a blockade lifted in the month it was imposed")

    def test_status_talks_opened_since_the_imposition_lift_it(self):
        w = imposed_by_the_rule()
        w.month = DEADLINE + 1
        director._union_reply(w, "status_talks")      # the path a proposal of Karamaniya's takes
        w.month = DEADLINE + 2
        director._foreign_cabinets(w)
        self.assertFalse(w.dip.blockade)
        self.assertNotIn("rule_blockade", w.foreign)
        self.assertIn("The Union lifts its blockade of Karamaniya's ports.", [e["text"] for e in w.events])

    def test_a_blockade_that_has_run_four_months_is_lifted(self):
        w = imposed_by_the_rule()
        for month in range(DEADLINE + 1, DEADLINE + 4):
            w.month = month
            director._foreign_cabinets(w)
            self.assertTrue(w.dip.blockade, f"lifted early, in Month {month + 1}")
        w.month = DEADLINE + 4
        director._foreign_cabinets(w)
        self.assertFalse(w.dip.blockade)
        self.assertNotIn("rule_blockade", w.foreign)

    def test_a_union_at_or_below_cohesion_point_fifty_five_lifts_it(self):
        w = imposed_by_the_rule()
        w.month = DEADLINE + 1
        with mock.patch.object(foreign, "resolve_union"):      # hold the Union's cohesion where the test sets it
            w.foreign["union"]["cohesion"] = .56
            director._foreign_cabinets(w)
            self.assertTrue(w.dip.blockade, "lifted above the cohesion line")
            w.foreign["union"]["cohesion"] = .55
            director._foreign_cabinets(w)
        self.assertFalse(w.dip.blockade)
        self.assertNotIn("rule_blockade", w.foreign)

    def test_the_monthly_path_lifts_it_when_the_union_is_weak(self):
        w = imposed_by_the_rule()
        w.month = DEADLINE + 1
        w.foreign["union"]["cohesion"] = .50      # resolve_union moves cohesion by a few hundredths in a month
        director._foreign_cabinets(w)
        self.assertFalse(w.dip.blockade)

    def test_a_month_a_cabinet_decides_leaves_the_rules_blockade_alone(self):
        w = imposed_by_the_rule()
        w.month = DEADLINE + 1
        director._union_reply(w, "status_talks")
        w.foreign.setdefault("cabinet_month", {})["veleria"] = w.month
        director._foreign_cabinets(w)
        self.assertTrue(w.dip.blockade, "the rule lifted a blockade in a month a cabinet decided")
        w.month = DEADLINE + 2
        director._foreign_cabinets(w)
        self.assertFalse(w.dip.blockade)

    def test_a_cabinets_blockade_is_never_lifted_by_the_rule(self):
        w = demanded(DEADLINE + 1)
        w.foreign.setdefault("cabinet_month", {})["veleria"] = w.month
        foreign_force.apply(w, "veleria", {"type": "naval_blockade", "magnitude": .5})
        self.assertNotIn("rule_blockade", w.foreign)
        # Each of the rule's three conditions holds for several months: talks, time, and a weak Union.
        w.foreign["status_talks"] = [DEADLINE + 1]
        w.foreign["union"]["cohesion"] = .50
        for month in range(DEADLINE + 2, DEADLINE + 9):
            w.month = month
            director._foreign_cabinets(w)
        self.assertTrue(w.dip.blockade)

    def test_a_war_keeps_the_rules_blockade_until_the_ceasefire(self):
        w = imposed_by_the_rule()
        w.dip.war, w.dip.aggressor, w.dip.war_start = True, "union", DEADLINE + 1
        w.month = DEADLINE + 5
        w.foreign["status_talks"] = [DEADLINE + 4]
        director._foreign_cabinets(w)
        self.assertTrue(w.dip.blockade, "the rule lifted a blockade during a war")
        self.assertIn("rule_blockade", w.foreign)
        director._end_war(w, "a ceasefire for the test")
        self.assertFalse(w.dip.blockade)
        self.assertNotIn("rule_blockade", w.foreign)

    def test_a_cabinet_that_lifts_the_rules_blockade_clears_the_record(self):
        w = imposed_by_the_rule()
        w.month = DEADLINE + 1
        w.foreign.setdefault("cabinet_month", {})["veleria"] = w.month
        foreign_force.apply(w, "veleria", {"type": "lift_blockade", "magnitude": .5})
        self.assertFalse(w.dip.blockade)
        self.assertNotIn("rule_blockade", w.foreign)

    def test_a_blockade_a_cabinet_imposes_after_the_rules_is_lifted_has_no_record(self):
        w = imposed_by_the_rule()
        w.month = DEADLINE + 1
        w.foreign.setdefault("cabinet_month", {})["veleria"] = w.month
        foreign_force.apply(w, "veleria", {"type": "lift_blockade", "magnitude": .5})
        w.month = DEADLINE + 2
        w.foreign["cabinet_month"]["veleria"] = w.month
        foreign_force.apply(w, "veleria", {"type": "naval_blockade", "magnitude": .5})
        self.assertNotIn("rule_blockade", w.foreign)
        w.month = DEADLINE + 6
        w.foreign["status_talks"] = [DEADLINE + 5]
        director._foreign_cabinets(w)
        self.assertTrue(w.dip.blockade)

    def test_a_record_of_a_blockade_that_has_ended_some_other_way_is_dropped(self):
        w = imposed_by_the_rule()
        w.dip.blockade = False
        w.month = DEADLINE + 1
        director._foreign_cabinets(w)
        self.assertNotIn("rule_blockade", w.foreign)


def build_world(month: int = 6):
    """A world in Month 7 with the Union's forces as the scenario starts them (foreign.initial_state)."""
    w = world()
    w.month = month
    return w


def build_forces(w, veleria: float = 9000.0, dorsania: float = 0.0) -> None:
    """One month of the Union's rules' force build, as foreign.resolve_union calls it, with no union formed."""
    foreign._build_forces(w, {"military_build": veleria, "union": "consult"},
                          {"military_build": dorsania, "union": "consult"}, 1.0)


class TheUnionsBuildDrawsTheReservePool(unittest.TestCase):
    """FO2-f: the Union's rules' force build (foreign._build_forces) added soldiers to the active army without drawing the
    reserve pool and without counting against the month's call-up cap, which a cabinet's mobilize is held to (FO1, FO2).
    The build is a call-up too: it draws the pool one for one, is capped by what the month has left, and is recorded."""

    def test_the_build_draws_the_reserve_pool_one_for_one(self):
        w = build_world()
        mil = w.foreign["actors"]["veleria"]["military"]
        reserves, active = mil["reserves"], mil["active"]
        build_forces(w, 9000.0)
        increase = mil["active"] - active
        self.assertEqual(increase, 9000.0)
        self.assertAlmostEqual(mil["reserves"], reserves - increase, msg="the reserve pool was not drawn")

    def test_a_cabinets_mobilize_in_the_same_month_sees_the_build_in_the_cap(self):
        w = build_world()
        build_forces(w, 9000.0)
        self.assertEqual(foreign_force.called_up_this_month(w, "veleria"), 9000.0,
                         "the build is not recorded against the month's call-up cap")
        self.assertIn("3,000", foreign_force.check(w, "veleria", {"type": "mobilize", "troops": 4000,
                                                                  "magnitude": .5}) or "")
        self.assertIsNone(foreign_force.check(w, "veleria", {"type": "mobilize", "troops": 3000, "magnitude": .5}))

    def test_a_full_cap_means_no_build(self):
        w = build_world()
        w.foreign["callups"] = {"month": w.month, "by": {"veleria": 12000.0}}
        mil = w.foreign["actors"]["veleria"]["military"]
        active, reserves = mil["active"], mil["reserves"]
        build_forces(w, 9000.0)
        self.assertEqual(mil["active"], active, "soldiers were built past the month's call-up cap")
        self.assertEqual(mil["reserves"], reserves)

    def test_a_build_is_capped_at_what_the_month_has_left(self):
        w = build_world()
        w.foreign["callups"] = {"month": w.month, "by": {"veleria": 5000.0}}
        mil = w.foreign["actors"]["veleria"]["military"]
        active, reserves = mil["active"], mil["reserves"]
        build_forces(w, 9000.0)
        self.assertEqual(mil["active"] - active, 7000.0, "12,000 cap less 5,000 already called up")
        self.assertAlmostEqual(mil["reserves"], reserves - 7000.0)
        self.assertEqual(foreign_force.called_up_this_month(w, "veleria"), 12000.0)

    def test_the_reserve_room_still_limits_the_build(self):
        w = build_world()
        mil = w.foreign["actors"]["veleria"]["military"]
        mil["reserves"] = 35000.0            # room = 35,000 less 45% of the 65,000 active = 5,750
        build_forces(w, 9000.0)
        self.assertEqual(mil["active"] - 65000.0, 5750.0)
        self.assertAlmostEqual(mil["reserves"], 35000.0 - 5750.0)


def foreign_council(tmp: str, backend_cls=ScriptedBackend, months: int = 4):
    """A council with scripted seats and its foreign cabinets on, built as tests/test_engine19_robustness.py builds one."""
    cfg = load_config(SCRIPTED)
    run = {"tokens": {}, "foreign_cabinets": True, "months": months, "seed": 1}
    cfg = {**cfg, "run": {**cfg["run"], **run}}
    cfg = normalize_config({"run": cfg["run"], "seat": cfg["seats"]})
    mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
    cfg["mapping"] = mapping
    w = new_world(cfg["run"]["seed"], months, member_ids=list(mapping),
                  founding_scenario=cfg["run"].get("founding_scenario", "random"),
                  founding_severity=cfg["run"].get("founding_severity", "default"))
    seats = _seats(cfg, mapping)
    for seat in seats.values():
        seat.backend = backend_cls(seat.cfg)
    os.makedirs(tmp, exist_ok=True)
    council = Council(w, seats, cfg["run"], RunStore(os.path.join(tmp, "r")))
    council.store.save_config(cfg)
    (council.store.path / "system_prompt.txt").write_text(council.system, encoding="utf-8")
    council.survey()
    council.diagnose_founding()
    council.form_government()
    return council, w


class ACabinetAnswerCannotEndTheMonth(unittest.TestCase):
    """CO2-f: a foreign cabinet's answer that puts a list where a name belongs ended the month with a TypeError (the
    normaliser tested the list against a set), and an exception inside the normaliser ended it too. A list is now a
    problem in the answer, and an exception is a problem string for that cabinet, which is read as empty, as a failed
    call is."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="engine19-followups-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_an_action_whose_type_is_a_list_is_a_problem(self):
        out, problems = foreign.normalize_cabinet_output(
            "veleria", {"actions": [{"type": ["mobilize"], "troops": 100}]})
        self.assertEqual(out["actions"], [])
        self.assertIn("unsupported cabinet action", problems)

    def test_a_belief_whose_name_is_a_list_is_a_problem(self):
        out, problems = foreign.normalize_cabinet_output("veleria", {"belief_updates": [
            {"belief": ["karamaniya_permanent_separation"], "value": .5, "confidence": .5}]})
        self.assertEqual(out["belief_updates"], [])
        self.assertIn("invalid belief update", problems)

    def test_a_list_for_any_other_name_is_a_problem_too(self):
        cases = (({"actions": [{"type": "deploy_to_border", "front": ["north"], "troops": 10}]}, "front must be one of"),
                 ({"actions": [{"type": "covert_support", "region": ["kessel"], "magnitude": .5}]},
                  "region must be one of"))
        for data, problem in cases:
            with self.subTest(problem=problem):
                out, problems = foreign.normalize_cabinet_output("veleria", data)
                self.assertEqual(out["actions"], [])
                self.assertTrue(any(p.startswith(problem) for p in problems), problems)
        out, problems = foreign.normalize_cabinet_output(
            "veleria", {"diplomatic_messages": [{"recipient": ["union"], "text": "hello"}]})
        self.assertEqual(out["diplomatic_messages"], [])
        self.assertIn("invalid diplomatic message", problems)

    def test_a_list_type_and_a_list_belief_do_not_end_the_month(self):
        class ListAnswers(ScriptedBackend):
            def call(self, system, user, schema, context):
                res = super().call(system, user, schema, context)
                w = context.get("world")
                if w is not None and w.month == 0 and context.get("phase") == "foreign" and isinstance(res.data, dict):
                    if context.get("actor") == "veleria":
                        res.data["actions"] = [{"type": ["mobilize"], "troops": 100}]
                    res.data["belief_updates"] = [{"belief": ["karamaniya_permanent_separation"],
                                                   "value": .5, "confidence": .5}]
                return res

        council, w = foreign_council(self.tmp, ListAnswers)
        record = council.run_month()
        self.assertEqual(w.month, 1)
        problems = {call["actor"]: call["problems"] for call in record["foreign_calls"]}
        self.assertIn("unsupported cabinet action", problems["veleria"])
        for actor in ("veleria", "dorsania"):
            self.assertIn("invalid belief update", problems[actor])

    def test_an_exception_inside_the_normaliser_is_a_problem_for_that_cabinet_only(self):
        council, w = foreign_council(self.tmp)
        real = foreign.normalize_cabinet_output

        def broken(actor_id, data):
            if actor_id == "dorsania" and isinstance(data, dict):
                raise RuntimeError("boom")
            return real(actor_id, data)

        with mock.patch.object(foreign, "normalize_cabinet_output", broken):
            record = council.run_month()
        self.assertEqual(w.month, 1)
        problems = {call["actor"]: call["problems"] for call in record["foreign_calls"]}
        self.assertIn("answer could not be read (RuntimeError: boom)", problems["dorsania"])
        self.assertNotIn("answer could not be read (RuntimeError: boom)", problems["veleria"])


class AnEmptyCabinetDecisionLeavesTheRules(unittest.TestCase):
    """A failed cabinet call, or an answer that could not be read, is an empty decision. It used to mark the cabinet as
    having decided, which kept the Union's rules from deciding on war and a blockade that month, though
    director.cabinet_decides says the rules remain for a call that failed."""

    def test_an_empty_decision_is_no_decision(self):
        w = world()
        positions = foreign.positions(w)
        foreign._apply_cabinet_decisions(w, positions, {"veleria": {}, "dorsania": {}})
        self.assertFalse(director.cabinet_decides(w, "veleria"))
        self.assertFalse(director.cabinet_decides(w, "dorsania"))

    def test_an_answer_with_no_actions_is_still_a_decision(self):
        w = world()
        positions = foreign.positions(w)
        foreign._apply_cabinet_decisions(w, positions, {"veleria": {"actions": [], "strategy": "wait"}})
        self.assertTrue(director.cabinet_decides(w, "veleria"))


if __name__ == "__main__":
    unittest.main()
