"""RR2 (regime realism): concessions make talks credible, and a new head gets a grace period.

The tests hold the two hooks in the world, not in the prompts:
- `society._protests` keeps its negotiation formula (`0.02 + 0.13 x credibility`) but reads
  credibility as the larger of the approval term and the region's delivered concessions, remembered
  for six decaying months;
- `politics.apply_motion` gives a new head of government a three-month public reaction (value .03,
  decaying by half), at most once in twelve months, never after a coup, half for a reshuffle.

Under `uprising_model = "legacy"` (or absent) both hooks are inert. `tests/fixtures/rr2_legacy_months.json`
is two scripted engine months recorded on base commit 49a8d5b, with `engine_source_fingerprint` removed
because it hashes the source on disk (the same convention as tests/fixtures/civil_war_off_month.json).
"""
import json
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import briefing, engine, politics, public_mood, regime_relief, regional, society  # noqa: E402
from karamaniya.world import World, new_world  # noqa: E402

LEGACY_MONTHS = os.path.join(ROOT, "tests", "fixtures", "rr2_legacy_months.json")


def world(model=None, seed: int = 11, human_factor: bool = False) -> World:
    w = new_world(seed, 36, human_factor=human_factor)
    if model is not None:
        w.uprising_model = model
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def policy_view(w: World, **over) -> dict:
    view = {"amnesty": w.policy.amnesty, "regional_fund": w.policy.regional_fund,
            "rationing": w.policy.rationing, "price_controls": w.policy.price_controls,
            "requisition": w.policy.requisition}
    view.update(over)
    return view


def close_month(w: World) -> None:
    """Append this month's policy record and advance the clock, as engine.snapshot does."""
    w.history.append({"month": w.month, "policy": policy_view(w),
                      "constitution": {"minority": w.const.minority}})
    w.month += 1


def record_cause(w: World, region: str, cause: str, month: int | None = None) -> None:
    w.institutions.setdefault("protest_causes", {}).setdefault(region, []).append(
        {"month": w.month if month is None else month, "cause": cause, "drivers": {}})


def assign_head(w: World, mid: str) -> None:
    politics.apply_motion(w, {"type": "assign_office", "subject": "head", "value": mid, "text": ""})


def kessel_pops(w: World) -> list:
    return [p for p in w.pops if p.region == "kessel"]


def angry_kessel(w: World, grievance: float = 0.9) -> list:
    pops = kessel_pops(w)
    for p in pops:
        p.grievance = grievance
        p.unrest = 0.6
        p.fear = 0.0
    return pops


class LegacyIsInert(unittest.TestCase):
    """Two scripted months on the base commit replay exactly, with no new records anywhere."""

    def run_two_months(self, explicit_legacy: bool) -> World:
        w = new_world(6, 36)
        if explicit_legacy:
            w.uprising_model = "legacy"
        w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
        w.policy.protest_response = "negotiate"
        w.policy.regional_fund = "kessel"
        w.policy.amnesty = "release"
        for p in w.pops:
            if p.region == "kessel":
                p.approval, p.grievance, p.fear, p.unrest = 0.2, 0.8, 0.1, 0.6
        politics.apply_motion(w, {"type": "assign_office", "subject": "head", "value": "B", "text": ""})
        engine.begin_month(w)
        engine.step(w)
        politics.apply_motion(w, {"type": "assign_office", "subject": "head", "value": "C", "text": ""})
        engine.begin_month(w)
        engine.step(w)
        return w

    def test_two_scripted_months_match_the_base(self):
        with open(LEGACY_MONTHS, encoding="utf-8") as f:
            expected = json.load(f)
        w = self.run_two_months(explicit_legacy=False)
        actual = json.loads(json.dumps(w.history))
        for row in actual:
            row.pop("engine_source_fingerprint", None)
        self.assertEqual(actual, expected)
        self.assertNotIn("protest_causes", w.institutions)
        self.assertNotIn("regime_relief", w.institutions)
        self.assertEqual(w.institutions.get("public_reactions", []), [],
                         "a head change under legacy grants no reaction")

    def test_an_explicit_legacy_option_is_the_same_run(self):
        with open(LEGACY_MONTHS, encoding="utf-8") as f:
            expected = json.load(f)
        w = self.run_two_months(explicit_legacy=True)
        actual = json.loads(json.dumps(w.history))
        for row in actual:
            row.pop("engine_source_fingerprint", None)
        self.assertEqual(actual, expected)

    def test_the_protests_in_the_fixture_were_negotiated_without_concession_fields(self):
        with open(LEGACY_MONTHS, encoding="utf-8") as f:
            expected = json.load(f)
        protests = [e for row in expected for e in row["events"] if e.get("kind") == "protest"]
        self.assertTrue(protests)
        for event in protests:
            self.assertIn("National dialogue", event["text"])
            for key in ("credibility", "approval_credibility", "concession_credibility", "concessions"):
                self.assertNotIn(key, event)

    def test_no_reaction_under_legacy(self):
        w = world("legacy")
        assign_head(w, "E")
        self.assertNotIn("regime_relief", w.institutions)
        self.assertEqual(w.institutions.get("public_reactions", []), [])

    def test_an_absent_option_is_legacy(self):
        w = world()
        self.assertFalse(regime_relief.enabled(w))
        assign_head(w, "E")
        self.assertNotIn("regime_relief", w.institutions)


class ConcessionCredibility(unittest.TestCase):
    def test_a_status_upgrade_credits_its_own_region_only(self):
        w = world("legitimacy")
        self.assertEqual(regime_relief.concession_credibility(w, "kessel"), 0.0)
        regional.set_status(w, "kessel", "cultural")
        self.assertGreater(regime_relief.concession_credibility(w, "kessel"), 0.0)
        self.assertEqual(regime_relief.concession_credibility(w, "highlands"), 0.0)
        self.assertEqual(regime_relief.concession_credibility(w, "aster"), 0.0)
        self.assertEqual([e["kind"] for e in regime_relief.negotiation_credits(w, "kessel")], ["status"])

    def test_a_status_downgrade_is_not_a_concession(self):
        w = world("legitimacy")
        regional.set_status(w, "kessel", "devolved")
        w.month = 1
        regional.set_status(w, "kessel", "central")
        kinds = [e["kind"] for e in regime_relief.negotiation_credits(w, "kessel")]
        self.assertEqual(kinds.count("status"), 1, "only the upgrade counts")

    def test_an_amnesty_transition_is_national_and_counts_once(self):
        w = world("legitimacy")
        politics.set_lever(w, "amnesty", "release")
        for rid in ("kessel", "highlands", "aster"):
            self.assertGreater(regime_relief.concession_credibility(w, rid), 0.0,
                               "an amnesty is delivered to the country, not one region")
        self.assertEqual(len([e for e in regime_relief.negotiation_credits(w, "kessel")
                              if e["kind"] == "amnesty"]), 1)
        close_month(w)
        politics.set_lever(w, "amnesty", "release")
        self.assertEqual(len([e for e in regime_relief.negotiation_credits(w, "kessel")
                              if e["kind"] == "amnesty"]), 1, "no transition, no second credit")

    def test_a_regional_fund_credits_the_funded_region_only(self):
        w = world("legitimacy")
        politics.set_lever(w, "regional_fund", "kessel")
        self.assertGreater(regime_relief.concession_credibility(w, "kessel"), 0.0)
        self.assertEqual(regime_relief.concession_credibility(w, "highlands"), 0.0)
        politics.set_lever(w, "regional_fund", "both")
        creds = regime_relief.negotiation_credits(w, "highlands")
        self.assertEqual([e["kind"] for e in creds], ["fund"])
        self.assertGreater(creds[0]["credit"], 0.0)

    def test_a_repeal_credits_only_the_region_whose_protest_named_the_measure(self):
        w = world("legitimacy")
        w.month = 2
        w.policy.rationing = True
        close_month(w)                                   # Month 2 row: rationing in force
        record_cause(w, "kessel", "rationing", month=2)
        w.policy.rationing = False                       # the council repeals it in Month 3
        kessel = [e for e in regime_relief.negotiation_credits(w, "kessel") if e["kind"] == "repeal"]
        self.assertEqual(len(kessel), 1)
        self.assertEqual(kessel[0]["measure"], "rationing")
        self.assertEqual(regime_relief.concession_credibility(w, "highlands"), 0.0,
                         "no highlands protest named the measure")
        self.assertEqual(regime_relief.concession_credibility(w, "aster"), 0.0)

    def test_a_repeal_without_a_named_cause_is_not_credited(self):
        w = world("legitimacy")
        w.month = 2
        w.policy.rationing = True
        close_month(w)
        record_cause(w, "kessel", "hunger", month=2)
        w.policy.rationing = False
        self.assertEqual([e for e in regime_relief.negotiation_credits(w, "kessel")
                          if e["kind"] == "repeal"], [])

    def test_each_of_the_three_measures_can_be_named_and_repealed(self):
        cases = (("rationing", True, False), ("price_controls", "all", "none"),
                 ("requisition", "heavy", "none"))
        for key, old, new in cases:
            with self.subTest(measure=key):
                w = world("legitimacy")
                w.month = 2
                setattr(w.policy, key, old)
                close_month(w)
                record_cause(w, "kessel", key, month=2)
                setattr(w.policy, key, new)
                credits = [e for e in regime_relief.negotiation_credits(w, "kessel")
                           if e["kind"] == "repeal"]
                self.assertEqual(len(credits), 1)
                self.assertEqual(credits[0]["measure"], key)

    def test_a_minority_restoration_credits_the_highlands_only(self):
        w = world("legitimacy")
        w.month = 2
        w.const.minority = "restricted"
        close_month(w)
        w.const.minority = "equal"
        self.assertGreater(regime_relief.concession_credibility(w, "highlands"), 0.0)
        self.assertEqual(regime_relief.concession_credibility(w, "kessel"), 0.0)
        self.assertEqual([e["kind"] for e in regime_relief.negotiation_credits(w, "highlands")],
                         ["minority_restored"])

    def test_the_credit_decays_over_six_months_and_is_gone_after(self):
        w = world("legitimacy")
        politics.set_lever(w, "regional_fund", "kessel")
        values = [regime_relief.concession_credibility(w, "kessel")]
        for _ in range(6):
            close_month(w)
            values.append(regime_relief.concession_credibility(w, "kessel"))
        self.assertGreater(values[0], values[1])
        self.assertGreater(values[1], values[2])
        self.assertGreater(values[2], values[3])
        self.assertGreater(values[3], values[4])
        self.assertGreater(values[4], values[5])
        self.assertEqual(values[6], 0.0, "the credit is spent after six months")

    def test_the_credibility_is_capped_at_one(self):
        w = world("legitimacy")
        regional.set_status(w, "kessel", "devolved")
        politics.set_lever(w, "amnesty", "release")
        politics.set_lever(w, "regional_fund", "kessel")
        w.month = 2
        w.policy.rationing = True
        close_month(w)
        record_cause(w, "kessel", "rationing", month=2)
        w.policy.rationing = False
        self.assertEqual(regime_relief.concession_credibility(w, "kessel"), 1.0)


class TheNegotiateHook(unittest.TestCase):
    def test_legacy_negotiation_still_uses_only_approval(self):
        w = world("legacy")
        politics.set_lever(w, "amnesty", "release")
        angry_kessel(w)
        w.policy.protest_response = "negotiate"
        for p in w.pops:
            p.approval = 0.1
        society._protests(w, random.Random(3))           # approval credibility 0: floor relief .02
        drops = [0.9 - p.grievance for p in kessel_pops(w)]
        self.assertAlmostEqual(min(drops), 0.02)
        event = [e for e in w.events if e["kind"] == "protest"][-1]
        self.assertNotIn("concession_credibility", event)
        self.assertNotIn("protest_causes", w.institutions)

    def test_a_concession_lifts_talks_where_approval_alone_gives_the_floor(self):
        w = world("legitimacy")
        politics.set_lever(w, "amnesty", "release")
        angry_kessel(w)
        w.policy.protest_response = "negotiate"
        for p in w.pops:
            p.approval = 0.1
        society._protests(w, random.Random(3))
        drop = min(0.9 - p.grievance for p in kessel_pops(w))
        self.assertGreater(drop, 0.02)
        self.assertLessEqual(drop, 0.15)
        event = [e for e in w.events if e["kind"] == "protest"][-1]
        self.assertEqual(event["approval_credibility"], 0.0)
        self.assertGreater(event["concession_credibility"], 0.0)
        self.assertEqual(event["credibility"], event["concession_credibility"])
        self.assertEqual([c["kind"] for c in event["concessions"]], ["amnesty"])

    def test_the_approval_term_is_kept_when_it_is_larger(self):
        w = world("legitimacy")
        angry_kessel(w)
        w.policy.protest_response = "negotiate"
        for p in w.pops:
            p.approval = 0.9
        society._protests(w, random.Random(3))
        event = [e for e in w.events if e["kind"] == "protest"][-1]
        self.assertEqual(event["approval_credibility"], 1.0)
        self.assertEqual(event["credibility"], 1.0)
        drop = min(0.9 - p.grievance for p in kessel_pops(w))
        self.assertAlmostEqual(drop, 0.15)

    def test_the_cap_holds_against_real_hardship(self):
        """Many concessions cannot buy more than the existing ceiling of .15 a month."""
        w = world("legitimacy")
        regional.set_status(w, "kessel", "devolved")
        politics.set_lever(w, "amnesty", "release")
        politics.set_lever(w, "regional_fund", "kessel")
        w.month = 2
        w.policy.rationing = True
        close_month(w)
        record_cause(w, "kessel", "rationing", month=2)
        w.policy.rationing = False
        angry_kessel(w)
        w.policy.protest_response = "negotiate"
        for p in w.pops:
            p.approval = 0.1
        society._protests(w, random.Random(3))
        drops = [0.9 - p.grievance for p in kessel_pops(w)]
        self.assertAlmostEqual(min(drops), 0.15)
        self.assertAlmostEqual(max(drops), 0.15)

    def test_only_the_protesting_region_is_relieved(self):
        w = world("legitimacy")
        politics.set_lever(w, "amnesty", "release")
        angry_kessel(w)
        w.policy.protest_response = "negotiate"
        for p in w.pops:
            p.approval = 0.1
        highlands = [p for p in w.pops if p.region == "highlands"]
        before = [p.grievance for p in highlands]
        society._protests(w, random.Random(3))
        self.assertEqual([p.grievance for p in highlands], before,
                         "a national concession still only reaches the region in protest")


class TheProtestCauseRecord(unittest.TestCase):
    def quiet_world(self) -> World:
        w = world("legitimacy")
        for p in kessel_pops(w):
            p.hunger = 0.0
            p.repression = 0.0
        return w

    def cause(self, w: World) -> str:
        return regime_relief.record_protest_cause(w, "kessel", kessel_pops(w))["cause"]

    def test_the_largest_live_driver_wins_deterministically(self):
        w = self.quiet_world()
        self.assertEqual(self.cause(w), "unrest")
        w.policy.rationing = True
        self.assertEqual(self.cause(w), "rationing")
        w.policy.rationing = False
        w.policy.requisition = "heavy"
        self.assertEqual(self.cause(w), "requisition")
        w.policy.requisition = "none"
        w.policy.price_controls = "all"
        self.assertEqual(self.cause(w), "price_controls")
        w.policy.price_controls = "none"
        w.const.minority = "interned"
        self.assertEqual(self.cause(w), "minority")
        w.const.minority = "equal"
        regional.set_status(w, "highlands", "devolved")
        self.assertEqual(self.cause(w), "status")
        w.const.highlands_status = "central"
        for p in kessel_pops(w):
            p.hunger = 0.5
        self.assertEqual(self.cause(w), "hunger")
        for p in kessel_pops(w):
            p.hunger = 0.0
            p.repression = 0.9
        self.assertEqual(self.cause(w), "repression")

    def test_the_same_state_gives_the_same_record(self):
        a, b = self.quiet_world(), self.quiet_world()
        a.policy.rationing = b.policy.rationing = True
        self.assertEqual(regime_relief.record_protest_cause(a, "kessel", kessel_pops(a)),
                         regime_relief.record_protest_cause(b, "kessel", kessel_pops(b)))

    def test_the_record_is_written_when_a_region_protests(self):
        w = world("legitimacy")
        angry_kessel(w)
        w.policy.protest_response = "tolerate"
        society._protests(w, random.Random(3))
        entries = w.institutions["protest_causes"]["kessel"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["month"], w.month)
        self.assertIn(entries[0]["cause"], regime_relief.CAUSES + ("unrest",))

    def test_the_record_is_capped(self):
        w = self.quiet_world()
        for month in range(30):
            w.month = month
            regime_relief.record_protest_cause(w, "kessel", kessel_pops(w))
        self.assertEqual(len(w.institutions["protest_causes"]["kessel"]), regime_relief.CAUSE_CAP)

    def test_the_record_survives_a_checkpoint(self):
        w = self.quiet_world()
        w.policy.requisition = "heavy"
        regime_relief.record_protest_cause(w, "kessel", kessel_pops(w))
        restored = World.from_dict(json.loads(json.dumps(w.to_dict())))
        self.assertEqual(restored.institutions["protest_causes"],
                         w.institutions["protest_causes"])

    def test_the_record_is_not_in_the_briefing(self):
        w = self.quiet_world()
        w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
        before = (briefing.public(w), briefing.public_v2(w))
        regime_relief.record_protest_cause(w, "kessel", kessel_pops(w))
        regime_relief.record_protest_cause(w, "highlands", [p for p in w.pops if p.region == "highlands"])
        after = (briefing.public(w), briefing.public_v2(w))
        self.assertEqual(before, after)
        self.assertNotIn("protest_causes", after[0] + after[1])


class TheGracePeriod(unittest.TestCase):
    def test_a_new_head_grants_a_three_month_halving_reaction(self):
        w = world("legitimacy")
        assign_head(w, "E")                              # E holds no other office: a fresh head
        entry = public_mood.active(w, regime_relief.GRACE_REASON)[0]
        self.assertEqual((entry["kind"], entry["where"]), ("approval", "*"))
        self.assertAlmostEqual(entry["value"], 0.03)
        self.assertEqual(entry["months_left"], 3)
        self.assertEqual(entry["decay"], 0.5)
        record = w.institutions["regime_relief"]["head_changes"][-1]
        self.assertTrue(record["granted"])
        self.assertEqual(record["why"], "new_head")
        self.assertEqual(record["scale"], 1.0)
        self.assertAlmostEqual(record["reaction"]["value"], 0.03)
        values = []
        for _ in range(4):
            got = []
            public_mood.effects(w, lambda kind, where, value: got.append((kind, where, value)))
            values.append(got)
        self.assertEqual(values[0], [("approval", "*", 0.03)])
        self.assertEqual(values[1], [("approval", "*", 0.015)])
        self.assertEqual(values[2], [("approval", "*", 0.0075)])
        self.assertEqual(values[3], [])

    def test_a_reshuffle_among_the_same_people_is_half(self):
        w = world("legitimacy")
        assign_head(w, "B")                              # B already holds the treasury
        entry = public_mood.active(w, regime_relief.GRACE_REASON)[0]
        self.assertAlmostEqual(entry["value"], 0.015)
        record = w.institutions["regime_relief"]["head_changes"][-1]
        self.assertEqual(record["why"], "reshuffle")
        self.assertEqual(record["scale"], 0.5)

    def test_at_most_once_in_twelve_months(self):
        w = world("legitimacy")
        assign_head(w, "E")
        w.month = 6
        assign_head(w, "D")
        self.assertEqual(len(public_mood.active(w, regime_relief.GRACE_REASON)), 1)
        record = w.institutions["regime_relief"]["head_changes"][-1]
        self.assertFalse(record["granted"])
        self.assertEqual(record["why"], "within_12_months")
        w.month = 12
        assign_head(w, "C")
        self.assertEqual(len(public_mood.active(w, regime_relief.GRACE_REASON)), 2)
        self.assertTrue(w.institutions["regime_relief"]["head_changes"][-1]["granted"])

    def test_none_after_a_coup(self):
        w = world("legitimacy")
        w.month = 5
        w.const.coup_month = 4
        assign_head(w, "E")
        self.assertEqual(public_mood.active(w, regime_relief.GRACE_REASON), [])
        record = w.institutions["regime_relief"]["head_changes"][-1]
        self.assertFalse(record["granted"])
        self.assertEqual(record["why"], "coup_blocked")
        # A coup-blocked change does not spend the once-in-twelve-months grant.
        w.month = 7
        assign_head(w, "D")
        self.assertTrue(w.institutions["regime_relief"]["head_changes"][-1]["granted"])

    def test_a_coup_this_month_also_blocks(self):
        w = world("legitimacy")
        w.month = 3
        w.const.coup_month = 3
        assign_head(w, "E")
        self.assertEqual(public_mood.active(w, regime_relief.GRACE_REASON), [])

    def test_vacating_the_head_grants_nothing(self):
        w = world("legitimacy")
        politics.apply_motion(w, {"type": "vacate_office", "subject": "head", "value": "", "text": ""})
        self.assertEqual(w.institutions.get("public_reactions", []), [])
        self.assertNotIn("head_changes", w.institutions.get("regime_relief", {}))

    def test_legacy_grants_nothing(self):
        w = world("legacy")
        assign_head(w, "E")
        self.assertNotIn("regime_relief", w.institutions)
        self.assertEqual(w.institutions.get("public_reactions", []), [])


if __name__ == "__main__":
    unittest.main()
