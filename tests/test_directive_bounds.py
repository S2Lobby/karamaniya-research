"""What a directive permits, which is not the same as the number it names.

A directive carries a value, and the prose around it can widen that value into an interval: "at
least 0.035" and "capped at 0.035" name the same figure and mean opposite things. The engine kept
only the figure, so every directive was read as exactly it. That read was safe here, but by accident
rather than by rule, and it could not tell a floor from a ceiling.

The case that prompted this, verbatim from runs/20260930-090535-seed1: delegate C tabled a directive
reading "hold military spending at 3.5% of output as a floor ... This is the current level, not an
increase, and I renew my commitment not to press above it", amended down from a proposal to RAISE,
with two other delegates' demands attached saying "no increase" and "no increase beyond 0.035". The
word "floor" says >= 0.035. The words around it say = 0.035, and they are what was agreed.
"""
import copy
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import politics  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_RUN = os.path.join(ROOT, "runs", "20260930-090535-seed1", "log.jsonl")


def motion(text, value="0.035", subject="military", demands=None):
    return {"type": "set_policy", "subject": subject, "value": value, "text": text,
            "demands": demands or []}


class TheBoundIsTheIntersection(unittest.TestCase):
    """An agreement is the set of values all of its parts allow, so intersecting them is the whole
    mechanism: it resolves "floor" against "no increase" without a special case for either."""

    def setUp(self):
        self.w = new_world(1, member_ids=list("ABCDE"))

    def bound(self, *args, **kwargs):
        return politics.directive_bounds(self.w, motion(*args, **kwargs))[0]

    def test_the_real_military_compromise_resolves_to_exactly_its_value(self):
        if not os.path.exists(REAL_RUN):
            self.skipTest("the run this came from is not present")
        with open(REAL_RUN, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f]
        real = [m for r in rows if r.get("type") == "month" for m in (r.get("motions") or [])
                if m.get("subject") == "military"][0]
        bound, clashes = politics.directive_bounds(self.w, real)
        self.assertEqual(clashes, [], "the proposal agrees with itself; it needed no repair")
        self.assertEqual(bound, {"min": 0.035, "max": 0.035})
        self.assertEqual(politics.bound_kind(bound), politics.FIXED)

    def test_a_floor_word_alone_permits_more(self):
        bound = self.bound("Set military spending to at least 3.5% of output.")
        self.assertEqual(politics.bound_kind(bound), politics.FLOOR)
        self.assertTrue(politics.bound_allows(bound, 0.045))

    def test_a_ceiling_word_alone_permits_less(self):
        for text in ("Military spending no more than 3.5%.",
                     "Do not exceed 3.5% on military spending.",
                     "Set a ceiling of 3.5% on military spending."):
            with self.subTest(text=text):
                bound = self.bound(text)
                self.assertEqual(politics.bound_kind(bound), politics.CEILING)
                self.assertTrue(politics.bound_allows(bound, 0.030))
                self.assertFalse(politics.bound_allows(bound, 0.040))

    def test_an_explicit_range(self):
        bound = self.bound("Hold military spending between 3% and 4% of output.")
        self.assertEqual(politics.bound_kind(bound), politics.RANGE)
        self.assertTrue(politics.bound_allows(bound, 0.035))
        self.assertFalse(politics.bound_allows(bound, 0.045))

    def test_the_narrower_of_two_readings_is_the_one_that_holds(self):
        """A floor widened by the word "floor" is narrowed back by an undertaking not to raise."""
        bound = self.bound("Hold military spending at 3.5% as a floor; I will not press above it.")
        self.assertEqual(politics.bound_kind(bound), politics.FIXED)

    def test_a_demand_forbidding_an_increase_narrows_the_motion_it_is_attached_to(self):
        bound = self.bound("Set military spending to at least 3.5% of output.",
                           demands=[{"member": "D", "demand": "no increase beyond 0.035"}])
        self.assertEqual(politics.bound_kind(bound), politics.FIXED)

    def test_two_readings_that_allow_nothing_in_common_raise_a_mismatch(self):
        bound, clashes = politics.directive_bounds(self.w, motion(
            "Hold military spending at 3.5% of output.",
            demands=[{"member": "A", "demand": "raise it to at least 0.045 immediately"}]))
        self.assertEqual(len(clashes), 1)
        self.assertEqual(clashes[0]["code"], "DIRECTIVE_BOUND_MISMATCH")
        # A disagreement must never widen what an office may do: the voted value is kept exactly.
        self.assertEqual(bound, {"min": 0.035, "max": 0.035})

    def test_conditional_warning_about_later_rate_hike_does_not_conflict_with_lower_amendment(self):
        bound, clashes = politics.directive_bounds(self.w, motion(
            "Raise the policy rate to 10% as a measured step.", value="0.10", subject="rate",
            demands=[{"member": "C", "demand": "Do not raise the rate to 11% without evidence that the added tightening will reduce inflation; publish the basis for any later change."}]))
        self.assertEqual(clashes, [])
        self.assertEqual(bound, {"min": 0.10, "max": 0.10})

    def test_a_bare_directive_is_still_exactly_its_value(self):
        bound = self.bound("Directive: military = 3.5% of output.")
        self.assertEqual(politics.bound_kind(bound), politics.FIXED)


class ComplianceReadsTheBound(unittest.TestCase):
    def setUp(self):
        self.w = new_world(1, member_ids=list("ABCDE"))
        self.w.const.offices.update({"treasury": "D", "interior": "C", "army": "B"})

    def order(self, lever, value):
        """Ordered through the office that holds the lever: an order for another office's setting is
        refused before compliance is ever reached, which is a different test."""
        office = politics.LEVER_OFFICE[lever]
        holder = self.w.const.offices[office]
        raised = []
        return politics.apply_orders(self.w, holder, {office: {lever: value}}, set(), [], raised)

    def test_a_raise_outside_the_bound_is_defiance(self):
        """The whole point: "floor 0.035" is not leave to raise spending when the same proposal
        also says no increase."""
        self.w.const.directives["military"] = 0.035
        self.w.const.directive_bounds["military"] = {"min": 0.035, "max": 0.035}
        self.assertEqual(len(self.order("military", 0.040)), 1)

    def test_an_order_inside_a_genuine_floor_is_not(self):
        self.w.const.directives["military"] = 0.035
        self.w.const.directive_bounds["military"] = {"min": 0.035, "max": None}
        self.assertEqual(self.order("military", 0.040), [])

    def test_a_rise_inside_a_ceiling_is_not(self):
        self.w.const.directives["military"] = 0.035
        self.w.const.directive_bounds["military"] = {"min": None, "max": 0.035}
        self.assertEqual(self.order("military", 0.030), [])

    def test_a_directive_recorded_before_bounds_existed_is_read_as_exactly_its_value(self):
        self.w.const.directives["military"] = 0.035
        self.w.const.directive_bounds.clear()
        self.assertEqual(len(self.order("military", 0.040)), 1)
        self.assertEqual(self.order("military", 0.035), [])

    def test_an_enum_lever_is_one_value_not_a_point_on_a_line(self):
        """Found by reading every set_policy motion in the corpus: enum levers carry strings, and
        asking whether "lethal" sits between two numbers raises rather than answers."""
        self.w.const.directives["protest_response"] = "lethal"
        self.assertEqual(len(self.order("protest_response", "lethal")), 0)
        self.assertEqual(len(self.order("protest_response", "tolerate")), 1)

    def test_a_boolean_lever_survives_the_same_path(self):
        self.w.const.directives["purge"] = True
        self.assertEqual(len(self.order("purge", True)), 0)
        self.assertEqual(len(self.order("purge", False)), 1)


class NothingInTheCorpusWidened(unittest.TestCase):
    def test_every_real_directive_keeps_the_reading_it_was_recorded_under(self):
        """The change must not quietly loosen a single existing directive: widening one means an
        office could move a setting the council thought it had fixed."""
        import glob
        w = new_world(1, member_ids=list("ABCDE"))
        read = widened = conflicts = 0
        unsupported_widening = []
        for path in glob.glob(os.path.join(ROOT, "runs", "*", "log.jsonl")):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if row.get("type") != "month":
                        continue
                    for mo in row.get("motions") or []:
                        if mo.get("type") != "set_policy":
                            continue
                        bound, clashes = politics.directive_bounds(w, mo)
                        if bound is None:
                            continue
                        read += 1
                        conflicts += len(clashes)
                        if politics.bound_kind(bound) != politics.FIXED:
                            widened += 1
                            wording = " ".join(str(mo.get(k, "")) for k in ("text", "description", "rationale"))
                            if not re.search(r"\b(minimum|floor|at least|no less than|not below)\b", wording, re.I):
                                unsupported_widening.append((path, row.get("month"), mo.get("id"), wording))
        if not read:
            self.skipTest("no recorded runs to check against")
        self.assertEqual(conflicts, 0, "a real directive was reported as disagreeing with itself")
        self.assertEqual(
            unsupported_widening, [],
            f"a real directive was widened without floor wording: {unsupported_widening[:1]}",
        )


if __name__ == "__main__":
    unittest.main()
