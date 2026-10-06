"""A storm is not a curfew: disaster relief is its own act, and it reports what it carried out.

Three delegates asked for coastal relief in one run — "direct immediate repair of ports, port
channels, fuel handling, navigable routes, roads and fields, and aid to affected households on the
Lissen Coast, targeting about 20M crowns financed by reallocation within existing appropriations with
no new printing" — and every one was refused as an unknown emergency measure. The delegates were not
misusing the vocabulary. The only act the engine had for a crisis was the on/off toggle for curfews
and detention powers, and it did not have the act they needed.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, politics  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

# The motion A tabled in Month 5, in the vocabulary that now exists for it.
REAL = {"type": "disaster_relief", "subject": "lissen", "value": "20", "proposer": "A",
        "text": "Coastal Reconstruction and Relief: direct immediate repair of ports, port channels, "
                "fuel handling, navigable routes, roads and fields, and aid to affected households on "
                "the Lissen Coast, targeting about 20M crowns financed by reallocation within existing "
                "appropriations with no new printing.",
        "action": {"region": "lissen", "amount": "20M", "funding": "reallocation",
                   "scope": "mixed", "military_engineers": True}}


class TheActExists(unittest.TestCase):
    def setUp(self):
        self.w = new_world(1, member_ids=list("ABCDE"))
        self.lissen = [r for r in self.w.regions if r.id == "lissen"][0]

    def test_it_is_offered_and_validates(self):
        self.assertIn("disaster_relief", actions.motion_schema(self.w, with_emergency=True)["properties"]["type"]["enum"])
        self.assertIn("funding_plan", actions.action_schema(self.w)["properties"])
        self.assertIsNone(politics.validate_motion_detail(self.w, dict(REAL)))

    def test_normalization_preserves_the_relief_payload(self):
        normalized = actions.normalize_motion_v2(self.w, dict(REAL))
        self.assertEqual(normalized["action"], REAL["action"])
        self.assertIsNone(politics.validate_motion_detail(self.w, normalized))

    def test_motion_summary_explains_the_relief_package(self):
        summary = actions.motion_summary(self.w, REAL)
        self.assertIn("relief for Lissen Coast", summary)
        self.assertIn("20M", summary)
        self.assertIn("reallocation", summary)

    def test_a_unique_region_name_in_a_long_subject_resolves(self):
        mo = {**REAL, "subject": "Lissen Coast storm recovery 20M",
              "action": {key: value for key, value in REAL["action"].items() if key != "region"}}
        self.assertIsNone(politics.validate_motion_detail(self.w, mo))

    def test_run_style_prose_fills_only_explicit_relief_fields(self):
        mo = actions.normalize_motion_v2(self.w, {
            "type": "disaster_relief", "subject": "Lissen Coast storm recovery", "value": "20M",
            "text": "Use reserves for ports, roads, fields, housing and food distribution with army engineers."})
        self.assertEqual(mo["action"]["region"], "lissen")
        self.assertEqual(mo["action"]["funding"], "reserves")
        self.assertEqual(mo["action"]["scope"], "mixed")
        self.assertTrue(mo["action"]["military_engineers"])
        self.assertIsNone(politics.validate_motion_detail(self.w, mo))

    def test_an_explicit_text_amount_is_used_when_value_is_empty(self):
        mo = actions.normalize_motion_v2(self.w, {
            "type": "disaster_relief", "subject": "Lissen Coast storm recovery", "value": "",
            "text": "Authorize up to 20M gold for Lissen Coast storm recovery, financed from reserves, "
                    "for ports, roads and housing."})
        self.assertEqual(mo["action"]["amount"], "20M")
        self.assertEqual(politics.validate_motion_detail(self.w, mo), None)

    def test_a_labeled_total_wins_over_individual_funding_components(self):
        mo = actions.normalize_motion_v2(self.w, {
            "type": "disaster_relief", "subject": "", "value": "",
            "text": "Total package 50M gold: 30M reallocation and 20M from reserves for Port Aster."})
        self.assertEqual(mo["action"]["amount"], "50M")
        self.assertEqual(mo["action"]["funding_plan"], [
            {"source": "reallocation", "amount": "30M"},
            {"source": "reserves", "amount": "20M"}])
        self.assertIsNone(politics.validate_motion_detail(self.w, mo))

    def test_mixed_funding_executes_and_records_each_source(self):
        self.w.econ.gdp_nominal = 500_000_000
        before_gold = self.w.econ.gold
        mo = actions.normalize_motion_v2(self.w, {
            "type": "disaster_relief", "subject": "", "value": "",
            "text": "Authorize Port Aster and Lissen Coast relief. Total package 50M gold: "
                    "30M reallocation within the existing budget, 20M from reserves. "
                    "Repair ports, roads and fields with army engineers."})
        self.assertIsNone(politics.validate_motion_detail(self.w, mo))
        politics.apply_motion(self.w, {**mo, "proposer": "B"})
        record = self.w.institutions["relief"][-1]
        self.assertEqual(record["funding"], "reallocation, reserves")
        self.assertEqual([part["source"] for part in record["funding_plan"]], ["reallocation", "reserves"])
        self.assertLess(self.w.econ.gold, before_gold)
        self.assertLessEqual(record["executed_amount"], record["approved_amount"])

    def test_mixed_funding_reserve_floor_checks_the_post_draw_balance(self):
        from karamaniya.motion_actions import evaluate_conditions, motion_conditions
        self.w.econ.gdp_nominal = 500_000_000
        self.w.econ.gold = 41_000_000
        mo = actions.normalize_motion_v2(self.w, {
            "type": "disaster_relief", "subject": "", "value": "",
            "text": "Total package 50M gold for Port Aster and Lissen Coast: 30M reallocation, "
                    "20M from reserves. Maintain reserve floor at 30M gold; mixed port and road relief."})
        mo["conditions"] = motion_conditions(mo)
        (result,) = evaluate_conditions(self.w, mo["conditions"], mo)
        self.assertFalse(result["met"])
        self.assertAlmostEqual(result["observed"], 21_000_000)

    def test_text_naming_two_regions_preserves_both_targets(self):
        mo = actions.normalize_motion_v2(self.w, {
            "type": "disaster_relief", "subject": "",
            "text": "Storm relief for ports and fields in Lissen Coast and Dorran March."})
        self.assertEqual(mo["action"]["regions"], ["lissen", "dorran"])
        self.assertEqual(politics.validate_motion_detail(self.w, mo)["reason_code"], "BAD_AMOUNT")

    def test_a_multi_region_package_reaches_each_named_region(self):
        dorran = next(region for region in self.w.regions if region.id == "dorran")
        self.lissen.damage = dorran.damage = 0.30
        mo = {**REAL, "action": {**REAL["action"], "region": None, "regions": ["lissen", "dorran"]}}
        politics.apply_motion(self.w, mo)
        record = self.w.institutions["relief"][-1]
        self.assertEqual(record["regions"], ["lissen", "dorran"])
        self.assertEqual(len(record["regional_effects"]), 2)
        self.assertLess(self.lissen.damage, 0.30)
        self.assertLess(dorran.damage, 0.30)

    def test_a_subject_naming_multiple_regions_resolves_both(self):
        mo = {**REAL, "action": {**REAL["action"], "region": "Lissen Coast and Port Aster"}}
        self.assertIsNone(politics.validate_motion_detail(self.w, mo))

    def test_the_real_motion_that_was_refused_now_runs(self):
        self.lissen.damage = 0.30
        self.lissen.logistics = 0.62
        self.assertIn("disaster relief", politics.apply_motion(self.w, dict(REAL)))
        self.assertLess(self.lissen.damage, 0.30)
        self.assertGreater(self.lissen.logistics, 0.62)
        self.assertTrue(self.w.institutions.get("relief"))

    def test_clearing_throughput_is_what_relief_actually_buys(self):
        """Roads and ports come back quickly and capital does not, so relief has to show up in
        throughput first — pricing both off one figure would make reconstruction instant or make
        clearing the roads worthless."""
        self.lissen.damage = 0.30
        self.lissen.logistics = 0.60
        politics.apply_motion(self.w, dict(REAL))
        self.assertGreater(self.lissen.logistics - 0.60, self.lissen.damage - 0.30)

    def test_it_is_not_an_emergency_measure(self):
        bad = {**REAL, "type": "emergency_measure", "subject": "coastal_relief",
               "action": {"region": "lissen", "amount": "20M", "funding": "reallocation", "scope": "mixed"}}
        detail = politics.validate_motion_detail(self.w, bad)
        self.assertEqual(detail["reason_code"], "UNKNOWN_MEASURE")

    def test_every_category_the_schema_offers_is_accepted(self):
        for funding in politics.RELIEF_FUNDING:
            for scope in politics.RELIEF_SCOPES:
                with self.subTest(funding=funding, scope=scope):
                    mo = {**REAL, "action": {**REAL["action"], "funding": funding, "scope": scope}}
                    self.assertIsNone(politics.validate_motion_detail(self.w, mo))

    def test_a_region_outside_karamaniya_is_not_a_relief_package(self):
        """Relief abroad is foreign aid: a different act with a different target, not a package
        aimed at someone else's province."""
        far = [r for r in self.w.regions if r.id not in {x.id for x in self.w.k_regions()}][0]
        mo = {**REAL, "action": {**REAL["action"], "region": far.id}}
        self.assertEqual(politics.validate_motion_detail(self.w, mo)["reason_code"], "UNKNOWN_REGION")

    def test_the_nonsense_is_still_refused(self):
        for field, value, code in (("region", "atlantis", "UNKNOWN_REGION"),
                                   ("funding", "printing", "UNKNOWN_FUNDING"),
                                   ("scope", "everything", "UNKNOWN_SCOPE"),
                                   ("amount", "0", "BAD_AMOUNT")):
            with self.subTest(field=field):
                mo = {**REAL, "action": {**REAL["action"], field: value}}
                self.assertEqual(politics.validate_motion_detail(self.w, mo)["reason_code"], code)


class AuthorisedIsNotCarriedOut(unittest.TestCase):
    """A council that votes 20M against a treasury that can raise 14M has authorised 20M and rebuilt
    what 14M buys. Reporting the authorised figure as the achievement is how partial execution comes
    to look like full compliance."""

    def setUp(self):
        self.w = new_world(1, member_ids=list("ABCDE"))
        self.lissen = [r for r in self.w.regions if r.id == "lissen"][0]

    def test_both_figures_are_kept_and_the_gap_is_named(self):
        politics.apply_motion(self.w, dict(REAL))
        record = self.w.institutions["relief"][-1]
        self.assertEqual(record["approved_amount"], 20_000_000)
        capacity = politics.relief_funding_capacity(self.w, "reallocation")
        self.assertAlmostEqual(record["executed_amount"], capacity, places=2)
        self.assertAlmostEqual(record["remaining_amount"], 20_000_000 - capacity, places=2)
        self.assertGreater(record["remaining_amount"], 0)
        self.assertTrue(any(e.get("kind") == "relief_underfunded" for e in self.w.events),
                        "a package that could not be carried out was announced as if it had been")

    def test_the_repair_stops_where_the_money_stops(self):
        """A vote for 200M does not rebuild 100 times what a vote for 2M does: it rebuilds what the
        treasury can raise, which is the same as voting for exactly that figure."""
        damage = {}
        for label, amount in (("small", "2M"), ("at-capacity", "15M"), ("over-voted", "200M")):
            w = new_world(1, member_ids=list("ABCDE"))
            [x for x in w.regions if x.id == "lissen"][0].damage = 0.30
            politics.apply_motion(w, {**REAL, "action": {**REAL["action"], "amount": amount}})
            damage[label] = [r for r in w.regions if r.id == "lissen"][0].damage
        self.assertLess(damage["at-capacity"], damage["small"], "a larger package repaired no more")
        self.assertAlmostEqual(damage["over-voted"], damage["at-capacity"], places=9,
                               msg="a vote of 200M rebuilt more than the treasury could raise")

    def test_a_fully_funded_package_reports_nothing_outstanding(self):
        self.lissen.damage = 0.30
        politics.apply_motion(self.w, {**REAL, "action": {**REAL["action"], "amount": "1M"}})
        self.assertEqual(self.w.institutions["relief"][-1]["remaining_amount"], 0)
        self.assertFalse(any(e.get("kind") == "relief_underfunded" for e in self.w.events))

    def test_engineers_add_labour_not_money(self):
        plain = new_world(1, member_ids=list("ABCDE"))
        helped = new_world(1, member_ids=list("ABCDE"))
        for w, engineers in ((plain, False), (helped, True)):
            [x for x in w.regions if x.id == "lissen"][0].damage = 0.30
            politics.apply_motion(w, {**REAL, "action": {**REAL["action"], "military_engineers": engineers}})
        self.assertLess([r for r in helped.regions if r.id == "lissen"][0].damage,
                        [r for r in plain.regions if r.id == "lissen"][0].damage)


class MoneyAsDelegatesWriteIt(unittest.TestCase):
    def test_the_forms_that_appear_in_real_motions(self):
        for written, want in (("20", 20.0), ("20M", 2e7), ("20 million", 2e7), ("20,000,000", 2e7),
                              ("about 20M crowns", 2e7), ("1,5M", 1.5e6), ("500k", 5e5), (None, None),
                              ("", None)):
            with self.subTest(written=written):
                self.assertEqual(politics.parse_money(written), want)

    def test_a_comma_is_a_thousands_separator_only_in_that_shape(self):
        self.assertEqual(politics.parse_money("20,000,000"), 20_000_000)
        self.assertEqual(politics.parse_money("1,5"), 1.5)


if __name__ == "__main__":
    unittest.main()
