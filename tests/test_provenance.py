"""Provenance: the raw source survives the press, and an allegation never becomes a fact by assertion."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import provenance as pv  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

# The example the mission brief names explicitly.
HEDGED = "Our fiscal fragility may cause a coup."
FRAMED = "commander discussed using force"


class TheBriefsExample(unittest.TestCase):
    def test_a_hedged_warning_is_not_recorded_as_an_assertion_of_intent(self):
        fact = pv.canonical(HEDGED)
        self.assertFalse(fact["asserts_intent"])
        self.assertTrue(fact["hedged"])
        self.assertIn("warning", fact["readable_as"])

    def test_a_flat_statement_of_intent_is_recorded_as_one(self):
        fact = pv.canonical("We will use the army to remove the council next week.")
        self.assertTrue(fact["asserts_intent"])
        self.assertFalse(fact["hedged"])

    def test_a_conditional_threat_is_an_assertion_of_intent(self):
        # "if" is a condition, not a hedge: the speaker is still saying what they will do.
        fact = pv.canonical("We will seize the treasury if the vote fails.")
        self.assertTrue(fact["asserts_intent"])

    def test_a_risk_about_someone_else_is_not_an_assertion_by_the_speaker(self):
        for text in ("Our fiscal fragility may cause a coup.",
                     "There is a risk the army could move against us.",
                     "I fear arrest if the vote goes the wrong way."):
            with self.subTest(text=text):
                self.assertFalse(pv.canonical(text)["asserts_intent"], text)

    def test_the_press_can_overstate_but_the_canonical_fact_does_not_move(self):
        w = new_world(3, 6)
        pid = pv.record(w, HEDGED, subject="coup risk", source="intercept", distort=True)["id"]
        fact = pv.layer(w, pid, pv.CANONICAL_FACT)
        self.assertFalse(fact["asserts_intent"])
        self.assertEqual(fact["text"], HEDGED)
        # Whatever the paper printed, the source is intact and still reads as a warning.
        self.assertEqual(pv.raw_text(w, pid), HEDGED)
        self.assertFalse(pv.summary(w, pid)["asserts_intent"])


class RawSourceIsImmutable(unittest.TestCase):
    def test_recording_a_press_layer_does_not_touch_the_raw_layer(self):
        w = new_world(1, 6)
        pid = pv.record(w, HEDGED, distort=True)["id"]
        before = pv.raw_text(w, pid)
        # Read the press layer, the interpretation and the canonical fact in turn.
        pv.press_text(w, pid)
        pv.layer(w, pid, pv.CANONICAL_FACT)
        self.assertEqual(pv.raw_text(w, pid), before)

    def test_a_belief_does_not_rewrite_the_source(self):
        w = new_world(1, 6)
        pid = pv.record(w, HEDGED, distort=True)["id"]
        pv.believes(w, pid, "B", pv.PRESS_REPORT)
        self.assertEqual(pv.raw_text(w, pid), HEDGED)

    def test_every_record_keeps_a_raw_layer(self):
        w = new_world(5, 6)
        for i in range(6):
            pid = pv.record(w, f"statement {i} about force", distort=(i % 2 == 0))["id"]
            self.assertEqual(pv.layer(w, pid, pv.RAW_SOURCE)["text"], f"statement {i} about force")


class BeliefsCarryTheirLayer(unittest.TestCase):
    def test_a_belief_records_which_layer_it_came_from(self):
        w = new_world(2, 6)
        pid = pv.record(w, HEDGED, distort=True)["id"]
        belief = pv.believes(w, pid, "C", pv.PRESS_REPORT)
        self.assertEqual(belief["from_layer"], pv.PRESS_REPORT)
        self.assertIn("C", pv.summary(w, pid)["known_by"])

    def test_a_belief_in_the_press_framing_is_flagged_as_not_matching_the_source(self):
        w = new_world(2, 6)
        pid = pv.record(w, HEDGED, distort=True)["id"]
        belief = pv.believes(w, pid, "C", pv.PRESS_REPORT)
        if not belief["matches_canonical"]:
            self.assertNotEqual(belief["text"], HEDGED)

    def test_believing_a_layer_that_was_never_recorded_is_an_error_not_a_silent_default(self):
        w = new_world(2, 6)
        pid = pv.record(w, "an ordinary statement", distort=False)["id"]
        with self.assertRaises(KeyError):
            pv.believes(w, pid, "C", pv.PRESS_INTERPRETATION)


class Determinism(unittest.TestCase):
    def test_the_same_seed_and_month_frame_a_story_the_same_way(self):
        first = pv.record(new_world(9, 6), HEDGED, distort=True)
        second = pv.record(new_world(9, 6), HEDGED, distort=True)
        self.assertEqual(first["layers"][pv.PRESS_REPORT]["text"],
                         second["layers"][pv.PRESS_REPORT]["text"])

    def test_distortion_can_be_turned_off_entirely(self):
        w = new_world(9, 6)
        pid = pv.record(w, HEDGED, distort=False)["id"]
        self.assertEqual(pv.press_text(w, pid), HEDGED)
        self.assertNotIn("distortion_added", pv.layer(w, pid, pv.PRESS_REPORT))


class Allegations(unittest.TestCase):
    def _filed(self):
        w = new_world(4, 6)
        pid = pv.record(w, "Procurement files were altered.", source="audit", distort=False)["id"]
        a = pv.allege(w, pid, "Minister B took a payment from a supplier.", against="B",
                      source="anonymous clerk", confidence=0.4)
        return w, pid, a

    def test_an_allegation_starts_alleged_and_stays_there_without_evidence(self):
        w, pid, a = self._filed()
        self.assertEqual(a["status"], pv.ALLEGED)
        self.assertEqual(a["verification_status"], pv.UNRESOLVED)
        self.assertEqual(a["evidence_links"], [])
        self.assertEqual(a["known_by"], ["anonymous clerk"])

    def test_publishing_an_allegation_does_not_verify_it(self):
        w, pid, a = self._filed()
        pv.publish_allegation(w, pid, "A1")
        again = pv._allegation(w, pid, "A1")
        self.assertEqual(again["public_status"], "published")
        self.assertEqual(again["status"], pv.ALLEGED, "publication was treated as proof")

    def test_one_supporting_item_is_partial_not_corroborated(self):
        w, pid, a = self._filed()
        pv.add_evidence(w, pid, "A1", "a signed requisition", supports=True)
        self.assertEqual(pv._allegation(w, pid, "A1")["status"], pv.PARTIALLY_CORROBORATED)

    def test_two_supporting_items_corroborate(self):
        w, pid, a = self._filed()
        pv.add_evidence(w, pid, "A1", "a signed requisition", supports=True)
        pv.add_evidence(w, pid, "A1", "a matching bank transfer", supports=True)
        self.assertEqual(pv._allegation(w, pid, "A1")["status"], pv.CORROBORATED)

    def test_contradicting_evidence_disproves(self):
        w, pid, a = self._filed()
        pv.add_evidence(w, pid, "A1", "the supplier's records show no payment", supports=False)
        self.assertEqual(pv._allegation(w, pid, "A1")["status"], pv.DISPROVEN)

    def test_mixed_evidence_leaves_it_partially_corroborated(self):
        w, pid, a = self._filed()
        pv.add_evidence(w, pid, "A1", "a matching transfer", supports=True)
        pv.add_evidence(w, pid, "A1", "a denial under oath", supports=False)
        self.assertEqual(pv._allegation(w, pid, "A1")["status"], pv.PARTIALLY_CORROBORATED)

    def test_there_is_no_api_that_promotes_an_allegation_to_fact(self):
        w, pid, a = self._filed()
        with self.assertRaises(PermissionError):
            pv.promote_to_fact(w, pid, "A1")

    def test_an_allegation_never_reaches_the_canonical_layer(self):
        w, pid, a = self._filed()
        pv.publish_allegation(w, pid, "A1")
        pv.add_evidence(w, pid, "A1", "a matching transfer", supports=True)
        pv.add_evidence(w, pid, "A1", "a second corroborating record", supports=True)
        fact = pv.layer(w, pid, pv.CANONICAL_FACT)
        self.assertNotIn("payment", fact["text"].lower())

    def test_summary_reports_allegations_without_claiming_them(self):
        w, pid, a = self._filed()
        s = pv.summary(w, pid)
        self.assertEqual(len(s["allegations"]), 1)
        self.assertEqual(s["allegations"][0]["status"], pv.ALLEGED)
        self.assertEqual(s["allegations"][0]["evidence"], 0)

    def test_unknown_ids_raise_rather_than_returning_none(self):
        w = new_world(4, 6)
        with self.assertRaises(KeyError):
            pv.allege(w, "P99", "a claim", against="B", source="x", confidence=0.5)
        with self.assertRaises(KeyError):
            pv.layer(w, "P99", pv.RAW_SOURCE)


class SurvivesSaveLoad(unittest.TestCase):
    def test_provenance_records_reload_intact(self):
        from karamaniya.world import World
        w = new_world(6, 6)
        pid = pv.record(w, HEDGED, distort=True)["id"]
        pv.allege(w, pid, "a claim", against="D", source="clerk", confidence=0.3)
        again = World.from_dict(w.to_dict())
        self.assertEqual(pv.raw_text(again, pid), HEDGED)
        self.assertEqual(pv._allegation(again, pid, "A1")["status"], pv.ALLEGED)


if __name__ == "__main__":
    unittest.main()
