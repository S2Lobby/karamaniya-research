"""Engine 22, foreign intake: the neighbours' acts the reader dropped, and never told them.

Run 20261011-105713-seed1 (world engine 21, eleven months, real models). Both cabinets named Kessel Valley, and
Dorsania also named Dorran March. The reader refused every such covert support ("region must be one of aster, kessel,
..."), so none took effect. Veleria listed several ultimatum terms, and each such ultimatum was refused ("terms must
be one of ..."). Veleria wrote the magnitude words "limited" and "moderate", and those acts were refused too. None of
these refusals reached the cabinet: they stayed in the month record.

Each test builds a cabinet's raw answer, reads it with foreign.normalize_cabinet_output, applies it as the month does
(foreign._apply_cabinet_decisions), and reads what the cabinet is shown the next month
(foreign_force.cabinet_view). Nothing here calls a model.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import foreign, foreign_force  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

ONE_DEMAND = "an ultimatum carries one demand: issued with status_talks; not sent: protect_imperial_citizens"


def world(month: int = 0):
    w = new_world(5, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    w.month = month
    return w


def answer(*actions):
    """A cabinet's raw answer: the given actions, and nothing else the reader can object to."""
    return {"public_statement": "", "strategic_assessment": "", "strategy": "", "union_position": None,
            "diplomatic_messages": [], "belief_updates": [], "decision_factors": [], "actions": list(actions)}


def read(actor, *actions):
    return foreign.normalize_cabinet_output(actor, answer(*actions))


def answer_month(w, actor, *actions):
    """The month's resolution of one cabinet's answer: read it, then apply it as the engine does."""
    out, _ = read(actor, *actions)
    foreign._apply_cabinet_decisions(w, foreign.positions(w), {actor: out})


def refused_next_month(w, actor="veleria"):
    return foreign_force.cabinet_view(w, actor)["your_acts_refused_last_month"]


class RegionNamesAreRead(unittest.TestCase):
    """A region named by its display name is the region it names. Run 20261011-105713-seed1: 18 covert supports
    named a region that way, and all 18 were refused."""

    def test_a_covert_support_named_by_display_name_keeps_the_region_id(self):
        out, _ = read("veleria", {"type": "covert_support", "region": "Kessel Valley", "magnitude": .4})
        self.assertEqual(out["actions"], [{"type": "covert_support", "magnitude": .4, "region": "kessel"}])

    def test_the_reading_of_a_name_is_reported(self):
        _, problems = read("veleria", {"type": "covert_support", "region": "Kessel Valley", "magnitude": .4})
        self.assertIn("region 'Kessel Valley' was read as kessel", problems)

    def test_names_are_read_in_any_case_and_spacing(self):
        cases = {"kessel valley": "kessel", "  KESSEL   VALLEY ": "kessel", "Kessel": "kessel", "kessel": "kessel",
                 "Dorran March": "dorran", "port aster": "aster", "Vell Highlands": "highlands",
                 "Lissen Coast": "lissen"}
        for name, rid in cases.items():
            with self.subTest(name=name):
                out, _ = read("dorsania", {"type": "covert_support", "region": name, "magnitude": .4})
                self.assertEqual(out["actions"][0]["region"], rid)

    def test_a_name_that_is_no_region_is_still_refused(self):
        out, problems = read("veleria", {"type": "covert_support", "region": "Atlantis", "magnitude": .4})
        self.assertEqual(out["actions"], [])
        self.assertTrue(any(p.startswith("region must be one of") for p in problems), problems)

    def test_a_covert_support_named_by_display_name_takes_effect(self):
        w = world(month=2)
        w.region("kessel").unrest = .5
        answer_month(w, "veleria", {"type": "covert_support", "region": "Kessel Valley", "magnitude": .4})
        self.assertEqual(w.foreign["covert_support"]["region"], "kessel")


class OneDemandPerUltimatum(unittest.TestCase):
    """An ultimatum carries one demand (Run 20261011: Veleria's Month 2 and Month 10 ultimatums were refused)."""

    def test_the_month_ten_ultimatum_is_issued_with_its_first_term(self):
        out, problems = read("veleria", {"type": "ultimatum", "terms": ["status_talks", "protect_imperial_citizens"],
                                         "deadline_months": 2})
        self.assertEqual(out["actions"], [{"type": "ultimatum", "magnitude": .5, "terms": "status_talks",
                                           "deadline_months": 2}])
        self.assertIn(ONE_DEMAND, problems)

    def test_the_month_two_ultimatum_is_issued_though_it_names_a_front(self):
        out, problems = read("veleria", {"type": "ultimatum", "region": "north", "deadline_months": 3,
                                         "terms": ["status_talks", "cut_league_ties", "demilitarize_border",
                                                   "protect_imperial_citizens"]})
        self.assertEqual(out["actions"], [{"type": "ultimatum", "magnitude": .5, "terms": "status_talks",
                                           "deadline_months": 3}])
        self.assertIn("an ultimatum carries one demand: issued with status_talks; not sent: cut_league_ties, "
                      "demilitarize_border, protect_imperial_citizens", problems)
        self.assertTrue(any(p.startswith("region 'north' is not a region") for p in problems), problems)

    def test_the_month_two_ultimatum_is_issued_in_the_world(self):
        w = world(month=1)
        answer_month(w, "veleria", {"type": "ultimatum", "region": "north", "deadline_months": 3,
                                    "terms": ["status_talks", "cut_league_ties"]})
        self.assertEqual(w.dip.ultimatum.get("terms_id"), "status_talks")

    def test_a_list_with_no_valid_term_is_refused(self):
        out, problems = read("veleria", {"type": "ultimatum", "terms": ["cut_everything", "nuke"],
                                         "deadline_months": 2})
        self.assertEqual(out["actions"], [])
        self.assertTrue(any(p.startswith("terms must be one of") for p in problems), problems)

    def test_a_single_term_is_read_and_its_missing_size_reported(self):
        out, problems = read("veleria", {"type": "ultimatum", "terms": "status_talks", "deadline_months": 2})
        self.assertEqual(out["actions"][0]["terms"], "status_talks")
        # Engine 30 (T151): the act gave no size, so the reader read 0.5 and says so.
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("the size was taken as 0.5", problems[0])


class MagnitudeWords(unittest.TestCase):
    """A magnitude written as a word reads as the number in foreign.MAGNITUDE_WORDS (Run 20261011: "limited", "moderate")."""

    def test_limited_reads_as_a_quarter_and_the_reading_is_reported(self):
        out, problems = read("veleria", {"type": "partial_embargo", "magnitude": "limited"})
        self.assertEqual(out["actions"][0]["magnitude"], .25)
        self.assertIn("magnitude 'limited' was read as 0.25", problems)

    def test_moderate_reads_as_a_half(self):
        out, _ = read("veleria", {"type": "partial_embargo", "magnitude": "moderate"})
        self.assertEqual(out["actions"][0]["magnitude"], .5)

    def test_words_are_read_in_any_case_and_spacing(self):
        out, _ = read("veleria", {"type": "partial_embargo", "magnitude": " High "})
        self.assertEqual(out["actions"][0]["magnitude"], .75)

    def test_the_table_holds_the_documented_vocabulary(self):
        expected = {"minimal": .1, "token": .1, "low": .25, "limited": .25, "small": .25, "moderate": .5,
                    "medium": .5, "high": .75, "large": .75, "major": .75, "heavy": .75, "maximum": 1.0,
                    "full": 1.0, "total": 1.0}
        self.assertEqual(foreign.MAGNITUDE_WORDS, expected)

    def test_any_other_word_is_refused(self):
        out, problems = read("veleria", {"type": "partial_embargo", "magnitude": "considerable"})
        self.assertEqual(out["actions"], [])
        self.assertIn("action magnitude must be between 0 and 1", problems)


class TheCabinetIsToldTheNextMonth(unittest.TestCase):
    """An act the reader drops or changes is listed once in the cabinet's view, in the month after it was answered."""

    def test_an_unknown_region_is_dropped_and_shown_exactly_once_the_next_month(self):
        w = world(month=2)
        answer_month(w, "veleria", {"type": "covert_support", "region": "Atlantis", "magnitude": .5})
        self.assertEqual(foreign.applied_effects(w), [])
        self.assertEqual(refused_next_month(w), [], "a refusal must not show in the month it was answered")
        w.month += 1
        shown = refused_next_month(w)
        self.assertEqual(len(shown), 1, shown)
        self.assertEqual(shown[0]["action"], "covert_support")
        self.assertTrue(shown[0]["reason"].startswith("region must be one of"), shown)
        w.month += 1
        self.assertEqual(refused_next_month(w), [], "a refusal is shown the month after and no later")

    def test_a_changed_act_is_shown_the_next_month_with_what_changed(self):
        w = world(month=0)
        answer_month(w, "veleria", {"type": "ultimatum", "terms": ["status_talks", "protect_imperial_citizens"],
                                    "deadline_months": 2})
        w.month += 1
        # Engine 30 (T151): the act gave no size, so its note also says the size was taken as 0.5; engine 23's note
        # for the dropped terms is still there.
        shown = refused_next_month(w)
        self.assertEqual(len(shown), 1, shown)
        self.assertEqual(shown[0]["action"], "ultimatum")
        self.assertTrue(shown[0]["reason"].startswith("carried out; "), shown)
        self.assertIn(ONE_DEMAND, shown[0]["reason"])
        self.assertIn("the size was taken as 0.5 because none was given", shown[0]["reason"])

    def test_a_name_or_a_word_read_as_meant_is_not_shown_as_a_refusal(self):
        # Engine 23: engine 22 sent "region 'Kessel Valley' was read as kessel" to the cabinet under
        # your_acts_refused_last_month, for a covert support that took effect. The reading stays in the month's record.
        w = world(month=2)
        w.region("kessel").unrest = .45
        out, problems = foreign.normalize_cabinet_output(
            "veleria", {"actions": [{"type": "covert_support", "region": "Kessel Valley", "magnitude": "limited"}]})
        self.assertEqual(out["act_notes"], [])
        self.assertIn("region 'Kessel Valley' was read as kessel", problems)
        foreign._apply_cabinet_decisions(w, foreign.positions(w), {"veleria": out})
        w.month += 1
        self.assertEqual(refused_next_month(w), [])

    def test_acts_filed_under_another_key_are_shown_once(self):
        # Run 20261011-105713-seed1, Month 1: Veleria's four acts sat under "this_month_actions", none was read, and
        # Veleria was never told.
        w = world(month=2)
        out, problems = foreign.normalize_cabinet_output("veleria", {"this_month_actions": [
            {"type": "partial_embargo", "magnitude": .5}, {"type": "offer_talks", "magnitude": .3}]})
        self.assertEqual(out["actions"], [])
        foreign._apply_cabinet_decisions(w, foreign.positions(w), {"veleria": out})
        w.month += 1
        shown = refused_next_month(w)
        self.assertEqual(len(shown), 1, shown)
        self.assertIn("'this_month_actions' were not read", shown[0]["reason"])

    def test_acts_a_cabinet_holds_back_are_not_shown(self):
        # Dorsania's Month 11 answer listed the acts it chose not to take under "actions_held", beside its "actions".
        out, _ = foreign.normalize_cabinet_output("dorsania", {
            "actions": [{"type": "intelligence_collection", "magnitude": .5}],
            "actions_held": [{"type": "grain_embargo", "magnitude": .5}]})
        self.assertEqual(out["act_notes"], [])
        out, _ = foreign.normalize_cabinet_output("dorsania", {
            "actions": [], "actions_held": [{"type": "grain_embargo", "magnitude": .5}]})
        self.assertEqual(out["act_notes"], [])

    def test_two_refusals_in_one_month_are_two_lines(self):
        w = world(month=2)
        answer_month(w, "dorsania", {"type": "covert_support", "region": "Atlantis", "magnitude": .5},
                     {"type": "grain_embargo", "magnitude": "considerable"})
        w.month += 1
        shown = refused_next_month(w, "dorsania")
        self.assertEqual([s["action"] for s in shown], ["covert_support", "grain_embargo"], shown)

    def test_a_valid_answer_shows_nothing(self):
        w = world(month=2)
        answer_month(w, "veleria", {"type": "partial_embargo", "magnitude": .5}, {"type": "offer_talks", "magnitude": .3})
        w.month += 1
        self.assertEqual(refused_next_month(w), [])

    def test_an_act_past_the_fourth_is_not_read_and_is_shown(self):
        w = world(month=2)
        answer_month(w, "veleria", *([{"type": "offer_talks", "magnitude": .3}] * 4
                                     + [{"type": "propaganda", "magnitude": .3}]))
        w.month += 1
        shown = refused_next_month(w)
        self.assertEqual([s["action"] for s in shown], ["propaganda"], shown)
        self.assertIn("only the first 4", shown[0]["reason"])

    def test_an_answer_whose_actions_are_not_a_list_is_shown_once(self):
        w = world(month=2)
        out, problems = foreign.normalize_cabinet_output("veleria", {"actions": {"type": "partial_embargo"}})
        self.assertEqual(out["actions"], [])
        self.assertIn("actions must be a list", problems)
        foreign._apply_cabinet_decisions(w, foreign.positions(w), {"veleria": out})
        w.month += 1
        shown = refused_next_month(w)
        self.assertEqual(len(shown), 1, shown)
        self.assertEqual(shown[0]["reason"], "actions must be a list; the acts were not read")


if __name__ == "__main__":
    unittest.main()
