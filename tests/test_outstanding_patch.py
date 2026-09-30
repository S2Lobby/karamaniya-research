"""Outstanding integrity + action-vocabulary patch, part 1 of 2."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import motion_actions, politics  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def world():
    return new_world(11)


def arrears_world():
    w = world()
    w.econ.arrears = 100e6
    w.econ.arrears_by = {"army": 10e6, "police": 10e6, "foreign_debt": 10e6,
                         "civil_service": 20e6, "contractors": 50e6}
    return w


def grain_world():
    w = world()
    actors = w.foreign.setdefault("actors", {})
    actors.setdefault("dorsania", {}).setdefault("diplomacy", {}).setdefault(
        "commitments", []).append({"partner": "karamaniya", "until": 99, "kind": "grain_deal"})
    return w


class CanonicalForeignActors(unittest.TestCase):
    def test_maritime_league_prose_with_union_target_is_a_named_mismatch(self):
        clash = motion_actions.conflict(world(), {
            "type": "diplomacy", "subject": "trade_deal", "value": "",
            "text": "To the Maritime League: protest the inspections.",
            "action": {"action_type": "diplomatic_protest", "target": "SOLVARAN_UNION"}})
        self.assertIsNotNone(clash)
        self.assertIn("FOREIGN_TARGET_MISMATCH", {r["code"] for r in clash["reasons"]})

    def test_veleria_is_a_valid_canonical_actor(self):
        w = world()
        for spelling in ("VELERIA", "Veleria", "veleria"):
            self.assertEqual(motion_actions._canonical_actor(w, spelling), "VELERIA")
        act = motion_actions.structured_action(w, {
            "type": "diplomacy", "subject": "trade_talks", "value": "",
            "text": "To Veleria: trade talks.",
            "action": {"action_type": "trade_talks", "target": "VELERIA"}})
        self.assertEqual(act["target"], "VELERIA")
        self.assertEqual(motion_actions.party_of("VELERIA"), "veleria")

    def test_a_display_name_target_is_canonicalised_not_flagged(self):
        w = world()
        from karamaniya import actions as _actions
        mo = _actions.normalize_motion_v2(w, {
            "type": "diplomacy", "subject": "trade_deal", "value": "",
            "text": "To the Maritime League: a standing trade arrangement.",
            "action": {"action_type": "trade_deal", "target": "Maritime League"}})
        self.assertEqual(mo["action"]["target"], "MARITIME_LEAGUE")
        self.assertIsNone(motion_actions.conflict(w, mo))

    def test_provenance_never_retargets_an_old_action(self):
        # A recorded "union" addressed the Solvaran Union when it was written, and still does:
        # canonicalising its spelling must not move it to another actor.
        w = world()
        self.assertEqual(motion_actions._canonical_actor(w, "union"), "SOLVARAN_UNION")
        self.assertEqual(motion_actions._canonical_actor(w, "league"), "MARITIME_LEAGUE")

    def test_a_veleria_motion_routes_to_veleria_not_the_league(self):
        w = world()
        politics.apply_motion(w, {"type": "diplomacy", "subject": "trade_talks", "value": "",
                                  "text": "To Veleria: trade talks.", "proposer": "A",
                                  "action": {"action_type": "trade_talks", "target": "VELERIA"}})
        self.assertEqual([p["party"] for p in w.dip.proposals], ["veleria"])


class NegotiatedAmountRevision(unittest.TestCase):
    def test_the_concession_is_preserved_with_both_ends_and_a_reason(self):
        w = world()
        entry = politics.record_revision(w, {
            "id": "M1", "type": "diplomacy", "subject": "loan", "value": "50M",
            "text": "compromise after debate, settle for 50M", "proposer": "A",
            "revisions": [{"value": "150M", "text": "ask for a 150M credit facility"}]})
        self.assertIsNotNone(entry)
        self.assertAlmostEqual(entry["initial_position"], 150e6)
        self.assertAlmostEqual(entry["final_position"], 50e6)
        self.assertEqual(entry["revision_reason"], "accepted compromise after debate")
        self.assertEqual(entry["phase"], "revision")
        self.assertEqual(w.institutions["negotiated_revisions"][-1], entry)

    def test_an_unmoved_figure_records_nothing(self):
        w = world()
        self.assertIsNone(politics.record_revision(w, {
            "id": "M1", "subject": "loan", "value": "50M", "text": "ask 50M",
            "revisions": [{"value": "50M", "text": "ask 50M"}]}))


class ExistingDealSemantics(unittest.TestCase):
    def test_a_bare_new_deal_against_a_live_one_names_the_verbs(self):
        detail = politics.validate_motion_detail(grain_world(), {
            "type": "diplomacy", "subject": "grain_deal", "value": "",
            "text": "propose another grain deal with Dorsania",
            "action": {"action_type": "grain_deal", "target": "DORSANIA"}})
        self.assertIsNotNone(detail)
        self.assertIn(detail["reason_code"], ("DEAL_ALREADY_EXISTS", "UNKNOWN_DEAL_INTENT"))
        self.assertIn("EXPAND_VOLUME", detail["related_state"]["allowed"])
