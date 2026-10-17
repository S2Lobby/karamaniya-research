"""Engine 24, cabinet limits (backlog T139 and T142): what a neighbour's cabinet is told of its limits, and a size it did not give.

T139. A cabinet acts on at most four things a month, and its strategy is kept to 180 characters. The reader enforced both
and the cabinet's prompt said neither: in the recorded answers, 8 acts came after the fourth and were not read, and a
strategy over 180 characters was cut in 94 of 200 readable answers (replayed over every foreign_call of the runs). The
cabinet's system prompt now states both limits, with the numbers the reader enforces.

T142. A null magnitude was refused outright: 31 acts in runs 20261010-002051-seed1, 20261010-070501-seed1 and
20261011-094417-seed1, 7 of them ultimatums. A missing magnitude was always read as the default 0.5. A null one is read the
same way now, and the cabinet is told the next month that its size was taken as 0.5 because none was given. The size is
one the cabinet did not choose. A missing size is still read silently: whether to tell the cabinet of those too is the
user's decision (report 23-cabinet-prompt).

Each test reads a cabinet's raw answer with foreign.normalize_cabinet_output, applies it as the month does
(foreign._apply_cabinet_decisions), and reads what the cabinet is shown the next month (foreign_force.cabinet_view).
Nothing here calls a model.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import foreign, foreign_force  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

ACTORS = ("veleria", "dorsania")
TEMPERAMENTS = ("", "hawk", "calculating")


def world(month: int = 0):
    w = new_world(5, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    w.month = month
    return w


def cabinet_answer(**fields):
    """A cabinet's raw answer with every field the reader looks at, and the given fields over it."""
    base = {"public_statement": "", "strategic_assessment": "", "strategy": "", "union_position": None,
            "diplomatic_messages": [], "belief_updates": [], "decision_factors": [], "actions": []}
    return {**base, **fields}


def read(actor, *acts):
    return foreign.normalize_cabinet_output(actor, cabinet_answer(actions=list(acts)))


def answer_month(w, actor, *acts):
    """The month's resolution of one cabinet's answer: read it, then apply it as the engine does."""
    out, _ = read(actor, *acts)
    foreign._apply_cabinet_decisions(w, foreign.positions(w), {actor: out})


def refused_next_month(w, actor="veleria"):
    return foreign_force.cabinet_view(w, actor)["your_acts_refused_last_month"]


class TheCabinetIsToldItsLimits(unittest.TestCase):
    """The prompt states the act cap and the strategy limit, with the numbers the reader enforces."""

    def test_the_prompt_states_the_act_cap_the_reader_enforces(self):
        out, _ = read("veleria", *([{"type": "offer_talks", "magnitude": .3}] * 5))
        kept = len(out["actions"])
        self.assertEqual(kept, 4, "the reader is expected to keep four acts a month")
        for actor in ACTORS:
            for temperament in TEMPERAMENTS:
                with self.subTest(actor=actor, temperament=temperament):
                    text = foreign.cabinet_system_prompt(actor, temperament)
                    self.assertIn(f"at most {kept} acts a month", text)
                    self.assertIn("an act after the fourth is not read", text)

    def test_the_prompt_states_the_strategy_limit_the_reader_enforces(self):
        out, _ = foreign.normalize_cabinet_output("dorsania", cabinet_answer(strategy="s" * 400))
        cut = len(out["strategy"])
        self.assertEqual(cut, 180, "the reader is expected to cut a strategy to 180 characters")
        for actor in ACTORS:
            for temperament in TEMPERAMENTS:
                with self.subTest(actor=actor, temperament=temperament):
                    self.assertIn(f"Your strategy is kept to {cut} characters",
                                  foreign.cabinet_system_prompt(actor, temperament))


class ANullSizeIsReadAsTheDefault(unittest.TestCase):
    """A null magnitude is read the way a missing one always was: as 0.5."""

    def test_a_null_magnitude_is_read_as_one_half(self):
        out, problems = read("dorsania", {"type": "offer_talks", "magnitude": None})
        self.assertEqual(out["actions"], [{"type": "offer_talks", "magnitude": .5}])
        self.assertNotIn("action magnitude must be between 0 and 1", problems)

    def test_a_null_magnitude_on_an_ultimatum_is_read_as_one_half(self):
        out, problems = read("veleria", {"type": "ultimatum", "terms": "status_talks", "deadline_months": 2,
                                         "magnitude": None})
        self.assertEqual(out["actions"], [{"type": "ultimatum", "magnitude": .5, "terms": "status_talks",
                                           "deadline_months": 2}])
        self.assertNotIn("action magnitude must be between 0 and 1", problems)

    def test_a_missing_magnitude_is_read_as_one_half_as_before(self):
        out, _ = read("dorsania", {"type": "offer_talks"})
        self.assertEqual(out["actions"], [{"type": "offer_talks", "magnitude": .5}])

    def test_a_null_magnitude_on_an_act_refused_for_another_reason_is_still_refused(self):
        out, problems = read("dorsania", {"type": "border_incident", "front": "west", "magnitude": None})
        self.assertEqual(out["actions"], [])
        self.assertIn("front must be one of north, east", problems)


class TheCabinetIsToldTheSizeWasNotChosen(unittest.TestCase):
    """The next month's cabinet view shows the reading, so the cabinet learns its size was not its own choice."""

    def test_the_next_month_note_says_the_size_was_taken_as_one_half(self):
        w = world(month=2)
        answer_month(w, "dorsania", {"type": "offer_talks", "magnitude": None})
        self.assertEqual(refused_next_month(w, "dorsania"), [], "a note is shown the month after, not in the month")
        w.month += 1
        shown = refused_next_month(w, "dorsania")
        self.assertEqual(len(shown), 1, shown)
        self.assertEqual(shown[0]["action"], "offer_talks")
        self.assertTrue(shown[0]["reason"].startswith("carried out; "), shown)
        self.assertIn("the size was taken as 0.5 because none was given", shown[0]["reason"])

    def test_an_ultimatum_with_a_null_size_is_issued_and_the_cabinet_is_told(self):
        w = world(month=0)
        answer_month(w, "veleria", {"type": "ultimatum", "terms": "status_talks", "deadline_months": 2,
                                    "magnitude": None})
        self.assertIsNotNone(w.dip.ultimatum, "the ultimatum with a null size is carried out")
        w.month += 1
        shown = refused_next_month(w)
        self.assertEqual([s["action"] for s in shown], ["ultimatum"], shown)
        self.assertIn("the size was taken as 0.5 because none was given", shown[0]["reason"])

    def test_a_missing_size_is_still_read_without_a_note_pending_the_users_decision(self):
        # Recorded runs: 139 acts the reader reads have no "magnitude" key (142 are written), in 10 runs, against 31 with a
        # null one. They are read as 0.5 with no note,
        # as they always were. Whether the cabinet is told of them is for the user (report 23-cabinet-prompt).
        out, _ = read("dorsania", {"type": "offer_talks"})
        self.assertEqual(out["act_notes"], [])


if __name__ == "__main__":
    unittest.main()
