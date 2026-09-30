"""A condition the whole council accepted must constrain what the engine executes.

Found on run 20260930-173547-seed1, Month 6. Motion D1 (pay half of the arrears from reserves) passed
5-0 after every delegate put the same safeguard on the table: reserves must not fall below 50M. The
Treasury had said so in structured form; the other four said so in their response-round demands; two of
them voted conditionally on it. The engine executed "paid 108.0M crowns" and left reserves at 4.0M.

Why the accepted condition never reached execution (traced by replaying the month from its clean
checkpoint with the recorded model answers; two defects, each enough on its own):

  1. The Treasury tabled its own D1, with `conditions: [reserves_after_payment >= 50]`. D's carried-over
     D1 was the same act, so the Treasury became a co-sponsor, and a co-sponsor's text and conditions
     were thrown away (`COSPONSORED_CARRIED`). Only the proposer could change what the motion carried.
  2. Even kept, the value was 50, not 50,000,000. The prose parser reads a bare "55" beside reserves as
     55M; the structured path did not, so the floor was a floor of 50 crowns and was met by any reserves.

And behind both: the response-round demands are free text and were never read as anything but text, and
a floor that a payment would breach blocked the whole motion (a "hold") rather than limiting the payment,
which is what "cap the payment at the floor" means and what all five delegates said.

The fix follows the brief exactly: a floor the voting coalition accepted is attached to the executable
motion, and the payment is min(requested payment, reserves - floor). Reserves never end below it. Where
nothing was accepted the engine behaves as it always did.
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, commitments, deliberation, errors, motion_actions, politics  # noqa: E402
from karamaniya.council import Council  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

# The economy at the start of Month 6, from the clean checkpoint of run 20260930-173547-seed1.
GOLD = 96624358.11926338
ARREARS = 215995437.6811962
ARREARS_BY = {"army": 4271626.2956594955, "police": 7749133.019984842, "civil_service": 113535561.26904356,
              "contractors": 90369244.73772174, "foreign_debt": 69872.35878658832}
PRICE = 1.1661284780214534
FLOOR = 50e6

# Verbatim from the run: D's own motion text (log.jsonl line 160), Treasury's motion (line 202) and the
# five response-round demands recorded on D1.
D1_TEXT = ("Set aside half current reserves immediately to create a sovereign buffer, pairing with Delegate C's "
           "promised repayment schedule. This reduces reliance on the Maritime League and secures imports against "
           "external pressure.")
RAW_D_MOTION = {"type": "settle_arrears", "subject": "reserves", "value": "half", "text": D1_TEXT, "action": {},
                "conditions": [], "force_agenda": False}
RAW_C_MOTION = {"type": "settle_arrears", "subject": "reserves", "value": "half",
                "text": ("Pay half of the inherited unpaid bills from reserves, as queued from last month, with the "
                         "actual payment limited so that foreign reserves remain at or above 50 million crowns after "
                         "payment. This continues the published arrears schedule: named funding for every payment, no "
                         "printing, no new foreign debt."),
                "conditions": [{"metric": "reserves_after_payment", "operator": ">=", "value": 50,
                                "source": "Treasury cash desk, report R6-TRE1"}], "force_agenda": False}
REAL_DEMANDS = [
    {"motion_id": "D1", "member": "D", "demand": "Ensure reserves do not fall below 50M gold; Treasury must confirm "
                                                  "payment capacity before execution."},
    {"motion_id": "D1", "member": "B", "demand": "Cap payment at the 50M reserve floor and pair it with Delegate C's "
                                                  "published repayment schedule; do not drain reserves needed for "
                                                  "grain and fuel imports."},
    {"motion_id": "D1", "member": "E", "demand": "Limit payment so foreign reserves do not fall below 50M gold, as "
                                                  "Treasury requires; publish the amount paid and resulting reserve "
                                                  "balance."},
    {"motion_id": "D1", "member": "A", "demand": "Payment must respect C's hard 50M reserve floor and be covered "
                                                  "without any resumption of printing; reserve levels published "
                                                  "monthly."},
    {"motion_id": "D1", "member": "C", "demand": "Cap the actual payment so foreign reserves remain at or above 50M "
                                                  "gold after settlement; with current reserves near 97M and arrears "
                                                  "near 222M, that implies roughly 47M paid this [cut]"},
]
# A and B voted conditionally (log: conditional_votes). The value is 50.0, written as a number of millions.
CONDITIONAL_A = {"D1": {"kind": "metric", "metric": "reserves", "operator": ">=", "value": 50.0, "if_unmet": "abstain"}}
CONDITIONAL_B = {"D1": {"kind": "metric", "metric": "reserves", "operator": ">=", "value": 50.0, "if_unmet": "no"}}


def world():
    w = new_world(3, 12, member_ids=list("ABCDE"))
    w.const.offices.update({"head": "B", "treasury": "C", "interior": "E", "army": "D", "navy": "A"})
    e = w.econ
    e.gold, e.arrears, e.arrears_by = GOLD, ARREARS, dict(ARREARS_BY)
    w.zone_of("karamaniya").price = PRICE
    w.month = 5
    return w


def carried_d1(w, with_cosponsor_motion=True):
    """D's carried-over D1, and the Treasury's identical motion folded into it, by the real merge code."""
    d1 = {**actions.normalize_motion_v2(w, RAW_D_MOTION), "id": "D1", "proposer": "D", "carried_over": True,
          "summary": "pay half of inherited unpaid bills using reserves", "revisions": [], "amended": False,
          "warning": None, "forced": False, "previous_proposer": None, "withdrawn_by": None,
          "withdrawal_reason": "", "replaced_by": "", "cosponsors": [], "demands": [dict(d) for d in REAL_DEMANDS]}
    if with_cosponsor_motion:
        candidate = {**actions.normalize_motion_v2(w, RAW_C_MOTION), "proposer": "C"}
        note = deliberation.coalesce_carried(w, candidate, [d1], "C")
        assert note["code"] == "COSPONSORED_CARRIED", note
    return d1


def resolve(w, motions, votes=None, conditional=None):
    council = Council.__new__(Council)
    council.w, council.pending_dms, council.observer, council._lock, council.spend = \
        w, [], None, threading.Lock(), 0.0
    votes = votes or {mid: {"D1": "yes"} for mid in "ABCDE"}
    conditional = conditional or {}
    decisions = {mid: {"votes": dict(votes.get(mid, {})), "vote_reasons": {}, "vote_conditions": conditional.get(mid, {}),
                       "resign": False, "coup": None, "coup_stance": "resist", "orders": {}, "operations": {},
                       "private_messages": [], "notes": "", "belief_updates": [], "decision_factors": []}
                 for mid in "ABCDE"}
    opening = commitments.condition_metrics(w)
    return council._resolve_v2(decisions, motions, motions, [], list("ABCDE"), [], opening, {}, [], False)


REAL_VOTES = {"A": {"D1": "conditional"}, "B": {"D1": "conditional"}, "C": {"D1": "yes"},
              "D": {"D1": "yes"}, "E": {"D1": "yes"}}
REAL_CONDITIONAL = {"A": CONDITIONAL_A, "B": CONDITIONAL_B}


class TheExactCaseFromTheRun(unittest.TestCase):
    def test_the_demands_alone_bind_when_the_whole_council_made_them(self):
        """Even with the Treasury's own motion absent, five matching demands from five yes votes are an
        accepted condition: this is the second route by which the floor reaches execution."""
        w = world()
        record = resolve(w, [carried_d1(w, with_cosponsor_motion=False)], REAL_VOTES, REAL_CONDITIONAL)
        entry = record["motions"][0]
        self.assertEqual(entry["status"], "PASSED_CONDITIONALLY")
        self.assertEqual(entry["accepted_conditions"][0]["accepted_by"], list("ABCDE"))
        self.assertAlmostEqual(w.econ.gold, FLOOR, places=2)

    def test_the_payment_is_capped_at_the_accepted_floor(self):
        w = world()
        record = resolve(w, [carried_d1(w)], REAL_VOTES, REAL_CONDITIONAL)
        entry = record["motions"][0]
        self.assertEqual((entry["execution_status"], entry["passed"]), ("EXECUTED", True))
        # payment = min(requested, reserves - floor), in the engine's units: reserves are gold, payments crowns.
        allowed_crowns = (GOLD - FLOOR) * PRICE
        self.assertAlmostEqual(w.econ.gold, FLOOR, places=2, msg="reserves must end exactly at the floor")
        self.assertAlmostEqual(w.econ.arrears, ARREARS - allowed_crowns, places=0)
        self.assertIn("paid 54.4M crowns", entry["execution_result"])
        self.assertIn("108.0M was requested", entry["execution_result"])
        self.assertIn("reserve floor of 50.0M", entry["execution_result"])
        self.assertNotIn("paid 108.0M", entry["execution_result"])

    def test_reserves_never_fall_below_the_accepted_floor(self):
        for gold in (FLOOR + 1.0, FLOOR + 5e6, 60e6, 80e6, GOLD, 200e6, 900e6):
            with self.subTest(gold=gold):
                w = world()
                w.econ.gold = gold
                resolve(w, [carried_d1(w)], REAL_VOTES, REAL_CONDITIONAL)
                self.assertGreaterEqual(w.econ.gold, FLOOR - 1e-3)

    def test_with_no_room_above_the_floor_nothing_is_paid_and_the_reason_is_recorded(self):
        for gold in (FLOOR, 40e6):
            with self.subTest(gold=gold):
                w = world()
                w.econ.gold = gold
                entry = resolve(w, [carried_d1(w)], REAL_VOTES, REAL_CONDITIONAL)["motions"][0]
                self.assertEqual(entry["execution_status"], "EXECUTION_BLOCKED_CONDITION")
                self.assertTrue(entry["passed"], "the vote stands")
                self.assertIn("floor", entry["blocking_reason"])
                self.assertEqual((w.econ.gold, w.econ.arrears), (gold, ARREARS))

    def test_a_small_payment_is_not_reduced(self):
        """min(requested, headroom): with reserves far above the floor the requested payment stands."""
        w = world()
        w.econ.gold = 900e6
        record = resolve(w, [carried_d1(w)], REAL_VOTES, REAL_CONDITIONAL)
        self.assertIn("paid 108.0M crowns", record["motions"][0]["execution_result"])
        self.assertNotIn("limited", record["motions"][0]["execution_result"])

    def test_the_motion_records_what_was_accepted_and_by_whom(self):
        w = world()
        entry = resolve(w, [carried_d1(w)], REAL_VOTES, REAL_CONDITIONAL)["motions"][0]
        accepted = entry["accepted_conditions"]
        self.assertEqual(len(accepted), 1)
        self.assertEqual((accepted[0]["metric"], accepted[0]["operator"], accepted[0]["value"]),
                         ("reserves_after_payment", ">=", FLOOR))
        self.assertEqual(accepted[0]["accepted_by"], list("ABCDE"))
        self.assertIn(("reserves_after_payment", ">=", FLOOR),
                      {(c["metric"], c["operator"], c["value"]) for c in entry["conditions"]})
        self.assertEqual(entry["vote_status"], "PASSED_CONDITIONALLY")
        result = next(r for r in entry["condition_results"] if r["metric"] == "reserves_after_payment")
        self.assertTrue(result["met"])
        self.assertTrue(result["capped"])
        self.assertAlmostEqual(result["allowed_cost"], GOLD - FLOOR, places=2)

    def test_the_motion_is_flagged_as_a_condition_execution_mismatch(self):
        w = world()
        record = resolve(w, [carried_d1(w)], REAL_VOTES, REAL_CONDITIONAL)
        entry = record["motions"][0]
        mismatch = entry["condition_execution_mismatch"]
        self.assertEqual(mismatch["code"], "CONDITION_EXECUTION_MISMATCH")
        self.assertTrue(mismatch["would_violate"], "executed as recorded it would have breached the floor")
        self.assertAlmostEqual(mismatch["violations"][0]["reserves_after_unconstrained"], GOLD - 92612196.0, delta=5e3)
        ledger = [e for e in errors.since(w, 5) if e["code"] == "CONDITION_EXECUTION_MISMATCH"]
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["details"]["motion"], "D1")

    def test_the_recorded_votes_are_untouched(self):
        w = world()
        entry = resolve(w, [carried_d1(w)], REAL_VOTES, REAL_CONDITIONAL)["motions"][0]
        self.assertEqual(entry["tally"], "(5 yes, 0 no, 0 abstain)")
        self.assertEqual({m: entry["votes"][m] for m in "ABCDE"}, dict.fromkeys("ABCDE", "yes"))


class WhereNothingWasAcceptedTheEngineIsAsItWas(unittest.TestCase):
    def test_no_floor_no_limit(self):
        w = world()
        d1 = carried_d1(w, with_cosponsor_motion=False)
        d1["demands"] = []
        record = resolve(w, [d1])
        entry = record["motions"][0]
        self.assertIn("paid 108.0M crowns", entry["execution_result"])
        self.assertAlmostEqual(w.econ.gold, GOLD - 92612196.0, delta=5e3)
        self.assertNotIn("accepted_conditions", entry)
        self.assertNotIn("condition_execution_mismatch", entry)
        self.assertEqual(entry["conditions"], [])
        self.assertEqual([e for e in errors.since(w, 5) if e["code"] == "CONDITION_EXECUTION_MISMATCH"], [])

    def test_a_floor_only_a_minority_asked_for_does_not_bind(self):
        w = world()
        d1 = carried_d1(w, with_cosponsor_motion=False)
        d1["demands"] = [d for d in REAL_DEMANDS if d["member"] in "AB"]
        record = resolve(w, [d1])
        self.assertIn("paid 108.0M crowns", record["motions"][0]["execution_result"])

    def test_a_motion_of_another_kind_is_not_touched(self):
        w = world()
        tax = {"id": "D1", "proposer": "C", "type": "set_policy", "subject": "tax", "value": "0.24", "text": "",
               "summary": "tax", "cosponsors": [], "demands": [dict(d) for d in REAL_DEMANDS], "revisions": []}
        record = resolve(w, [tax])
        self.assertNotIn("accepted_conditions", record["motions"][0])


class TheSafeguardSurvivesTheMerge(unittest.TestCase):
    def test_a_carried_motion_keeps_the_cosponsors_safeguard(self):
        w = world()
        d1 = carried_d1(w)
        self.assertEqual(d1["cosponsors"], ["C"])
        kept = d1["sponsor_conditions"]["C"]
        self.assertEqual([(c["metric"], c["operator"], c["value"]) for c in kept],
                         [("reserves_after_payment", ">=", FLOOR)])

    def test_the_proposers_own_renewal_is_unchanged(self):
        w = world()
        d1 = carried_d1(w, with_cosponsor_motion=False)
        candidate = {**actions.normalize_motion_v2(w, RAW_D_MOTION), "proposer": "D",
                     "text": "Set aside half current reserves, limited so that reserves stay above 55 million."}
        self.assertEqual(deliberation.coalesce_carried(w, candidate, [d1], "D")["code"], "RENEWED_CARRIED")
        self.assertNotIn("sponsor_conditions", d1)

    def test_a_same_month_cosponsor_is_held_to_the_same_rule(self):
        w = world()
        first = {**actions.normalize_motion_v2(w, RAW_D_MOTION), "id": "M1", "proposer": "D", "cosponsors": []}
        second = {**actions.normalize_motion_v2(w, RAW_C_MOTION), "proposer": "C"}
        rejection, warning = deliberation.check(w, second, [first], "C")
        self.assertEqual(warning["code"], "COSPONSOR")
        deliberation.attach_sponsor_conditions(first, "C", second)
        self.assertEqual(first["sponsor_conditions"]["C"][0]["value"], FLOOR)

    def test_a_cosponsor_with_no_safeguard_adds_nothing(self):
        w = world()
        d1 = carried_d1(w, with_cosponsor_motion=False)
        plain = {**actions.normalize_motion_v2(w, {**RAW_C_MOTION, "conditions": [], "text": "Pay half from reserves."}),
                 "proposer": "C"}
        deliberation.coalesce_carried(w, plain, [d1], "C")
        self.assertNotIn("sponsor_conditions", d1)


class AFloorIsInTheUnitsTheDelegateMeant(unittest.TestCase):
    def test_fifty_beside_reserves_is_fifty_million(self):
        for metric in ("reserves", "reserves_after_payment", "arrears"):
            with self.subTest(metric=metric):
                got = motion_actions.motion_conditions({"conditions": [
                    {"metric": metric, "operator": ">=", "value": 50, "source": "x"}]})
                self.assertEqual(got[0]["value"], 50e6)

    def test_what_is_already_in_full_units_is_not_scaled_again(self):
        for value in (50e6, 55e6, 100000.0, 1.2e9):
            with self.subTest(value=value):
                got = motion_actions.motion_conditions({"conditions": [
                    {"metric": "reserves_after_payment", "operator": ">=", "value": value}]})
                self.assertEqual(got[0]["value"], value)
                again = motion_actions.motion_conditions({"conditions": got})
                self.assertEqual(again[0]["value"], value, "normalising twice must not change it")

    def test_ratios_and_counts_are_never_scaled(self):
        for metric, value in (("food_ratio", 0.9), ("unemployment", 0.08), ("army_morale", 0.5), ("inflation", 0.3),
                              ("deficit", 0.05), ("approval", 0.4)):
            with self.subTest(metric=metric):
                got = motion_actions.motion_conditions({"conditions": [
                    {"metric": metric, "operator": ">=", "value": value}]})
                self.assertEqual(got[0]["value"], value)

    def test_the_trivial_floor_the_old_reading_produced(self):
        """50 crowns is met by any reserves; 50M is not. The exact numbers of the run."""
        w = world()
        mo = {**carried_d1(w), "passed": True}
        old_reading = [{"metric": "reserves_after_payment", "operator": ">=", "value": 50.0, "source": "x"}]
        self.assertTrue(motion_actions.evaluate_conditions(w, old_reading, mo)[0]["met"])
        fixed = motion_actions.motion_conditions({"conditions": [dict(old_reading[0])]})
        result = motion_actions.evaluate_conditions(w, fixed, mo)[0]
        self.assertEqual(result["value"], FLOOR)
        self.assertTrue(result["met"], "a floor below reserves is met by capping the payment")
        self.assertTrue(result["capped"])


class ReadingADemand(unittest.TestCase):
    def test_the_five_demands_from_the_run(self):
        for demand in REAL_DEMANDS:
            with self.subTest(member=demand["member"]):
                self.assertEqual(motion_actions.floor_from_demand(demand["demand"]), FLOOR)

    def test_other_ways_of_saying_it(self):
        for text, want in (("Reserves must stay at or above 50 million.", 50e6),
                           ("Do not let reserves fall below 60M gold.", 60e6),
                           ("Keep a 45M reserve floor.", 45e6),
                           ("Payment limited so reserves remain >= 50M.", 50e6),
                           ("Hold reserves at least 55 million after the payment.", 55e6),
                           ("Ensure reserves never fall below 50,000,000.", 50e6),
                           ("Reserves should not drop under 1.5bn.", 1.5e9)):
            with self.subTest(text=text):
                self.assertEqual(motion_actions.floor_from_demand(text), want)

    def test_a_floor_as_other_recorded_demands_put_it(self):
        """Wording taken from demands recorded in other runs (the same floor, said differently)."""
        for text, want in (("Treasury certification of the audited register; no payment that reduces reserves "
                            "below 55M gold.", 55e6),
                           ("Payment must be funded strictly from reserves with no printing, and must not push "
                            "reserves below roughly 50M gold so food imports remain protected.", 50e6),
                           ("Execute only against the audited register and preserve at least 55M gold for food "
                            "and fuel imports.", 55e6),
                           ("Total reserve draw capped so reserves stay at or above 45M after execution.", 45e6)):
            with self.subTest(text=text):
                self.assertEqual(motion_actions.floor_from_demand(text), want)

    def test_a_figure_that_is_not_money_is_never_a_floor(self):
        """A troop count in the same sentence as 'reserves' must not become a floor of 28,000 million."""
        for text in ("Keep the army at or above 28,000 and reserves stable.",
                     "Reserves are stable, and the army must not go below 28,000 troops.",
                     "Keep reserves and the army at or above 28,000.",
                     "Keep reserves above 6 months of imports.",
                     "Keep reserves above 50%."):
            with self.subTest(text=text):
                self.assertIsNone(motion_actions.floor_from_demand(text))

    def test_a_bare_figure_is_money_only_when_it_is_written_as_money(self):
        self.assertEqual(motion_actions.floor_from_demand("Reserves must stay above 50 gold."), 50e6)
        self.assertEqual(motion_actions.floor_from_demand("Keep a 50 reserve floor."), 50e6)
        self.assertEqual(motion_actions.floor_from_demand("Reserves must not fall below 50,000,000."), 50e6)
        self.assertIsNone(motion_actions.floor_from_demand("Reserves must stay above 50."))

    def test_what_is_not_a_floor(self):
        for text in ("Publish the amount paid and resulting reserve balance.",
                     "Reserves are above 97M, so we can pay in full.",
                     "Pay 47M now.",
                     "Cap payment at 47M.",
                     "Reserves near 97M and arrears near 222M.",
                     "Do not drain reserves needed for grain and fuel imports.",
                     "",
                     "A floor would be wise."):
            with self.subTest(text=text):
                self.assertIsNone(motion_actions.floor_from_demand(text))


class WhenACoalitionAcceptedIt(unittest.TestCase):
    """The floor binds when the votes that carried the motion are votes that asked for it."""

    def motion(self, floors):
        demands = [{"motion_id": "D1", "member": m, "demand": f"Keep reserves above {f}M."}
                   for m, f in floors.items()]
        return {"id": "D1", "proposer": "D", "type": "settle_arrears", "subject": "reserves", "value": "half",
                "text": "", "demands": demands}

    def accepted(self, floors, votes=None, rule=None):
        w = world()
        if rule:
            w.const.decision_rule = rule
        votes = votes or dict.fromkeys("ABCDE", "yes")
        return motion_actions.accepted_conditions(w, self.motion(floors), votes)

    def test_three_of_five_is_a_majority(self):
        got = self.accepted({"A": 50, "B": 50, "C": 50})
        self.assertEqual([(c["value"], c["accepted_by"]) for c in got], [(50e6, ["A", "B", "C"])])

    def test_two_of_five_is_not(self):
        self.assertEqual(self.accepted({"A": 50, "B": 50}), [])

    def test_the_highest_floor_a_winning_coalition_asked_for(self):
        got = self.accepted({"A": 60, "B": 50, "C": 50, "D": 50, "E": 40})
        self.assertEqual([(c["value"], c["accepted_by"]) for c in got], [(50e6, ["A", "B", "C", "D"])])

    def test_someone_who_voted_no_does_not_count(self):
        votes = {"A": "yes", "B": "yes", "C": "no", "D": "no", "E": "no"}
        self.assertEqual(self.accepted({"A": 50, "B": 50, "C": 50, "D": 50}, votes), [])
        votes = dict.fromkeys("ABCDE", "yes")
        votes.update(C="no", D="no")
        self.assertEqual(self.accepted({"C": 50, "D": 50, "E": 50}, votes), [])

    def test_the_decision_rule_in_force_decides_what_a_majority_is(self):
        floors = {"A": 50, "B": 50, "C": 50, "D": 50}
        self.assertEqual(self.accepted(floors, rule="unanimity"), [])
        self.assertEqual(len(self.accepted({m: 50 for m in "ABCDE"}, rule="unanimity")), 1)
        self.assertEqual(len(self.accepted({"B": 50}, rule="head_decides")), 1, "B is the Head of Government")
        self.assertEqual(self.accepted({"A": 50}, rule="head_decides"), [])

    def test_only_an_arrears_payment_from_reserves_carries_a_reserve_floor(self):
        w = world()
        for mo in ({"type": "settle_arrears", "subject": "domestic_bonds"}, {"type": "set_policy", "subject": "tax"}):
            with self.subTest(mo=mo):
                motion = {**self.motion({m: 50 for m in "ABCDE"}), **mo}
                self.assertEqual(motion_actions.accepted_conditions(w, motion, dict.fromkeys("ABCDE", "yes")), [])


class TheCapItself(unittest.TestCase):
    def pay(self, w, conditions, **kw):
        mo = {"id": "M1", "type": "settle_arrears", "subject": "reserves", "value": "half", "text": "",
              "proposer": "A", "passed": True, "conditions": conditions, **kw}
        return mo

    FLOOR_CONDITION = [{"metric": "reserves_after_payment", "operator": ">=", "value": FLOOR, "source": "floor"}]

    def test_payment_is_min_of_requested_and_reserves_minus_floor(self):
        w = world()
        mo = self.pay(w, self.FLOOR_CONDITION)
        self.assertIsNone(motion_actions.validate_execution(w, mo))
        politics.apply_motion(w, {**mo, "proposer": "A"})
        self.assertAlmostEqual(w.econ.gold, FLOOR, places=2)

    def test_the_floor_is_the_only_limit_when_it_binds(self):
        w = world()
        mo = self.pay(w, [{**self.FLOOR_CONDITION[0], "value": 80e6}])
        politics.apply_motion(w, {**mo, "proposer": "A"})
        self.assertAlmostEqual(w.econ.gold, 80e6, places=2)

    def test_no_headroom_means_no_payment_and_a_reason(self):
        for gold in (FLOOR, FLOOR - 1e6, 10e6):
            with self.subTest(gold=gold):
                w = world()
                w.econ.gold = gold
                mo = self.pay(w, self.FLOOR_CONDITION)
                gate = motion_actions.validate_execution(w, mo)
                self.assertEqual(gate["code"], "EXECUTION_BLOCKED_CONDITION")
                self.assertIn("floor", gate["blocking_reason"])
                self.assertEqual(w.econ.gold, gold)

    def test_the_strictest_of_several_floors_wins(self):
        w = world()
        conditions = self.FLOOR_CONDITION + [{**self.FLOOR_CONDITION[0], "value": 70e6}]
        politics.apply_motion(w, {**self.pay(w, conditions), "proposer": "A"})
        self.assertAlmostEqual(w.econ.gold, 70e6, places=2)

    def test_the_cost_the_gate_projects_is_the_cost_that_is_executed(self):
        w = world()
        mo = self.pay(w, self.FLOOR_CONDITION)
        projected = motion_actions.evaluate_conditions(w, motion_actions.motion_conditions(mo), mo)[0]
        before = w.econ.gold
        politics.apply_motion(w, {**mo, "proposer": "A"})
        self.assertAlmostEqual(before - w.econ.gold, projected["allowed_cost"], places=2)
        self.assertAlmostEqual(w.econ.gold, projected["observed"], places=2)

    def test_bonds_are_not_limited_by_a_reserve_floor(self):
        w = world()
        w.econ.gold = 10e6
        mo = self.pay(w, self.FLOOR_CONDITION, subject="domestic_bonds")
        before = w.econ.gold
        politics.apply_motion(w, {**mo, "proposer": "A"})
        self.assertEqual(w.econ.gold, before)

    def test_other_conditions_are_still_gates(self):
        """League credit and the audited register block, as before: only the reserve floor became a limit."""
        w = world()
        gate = motion_actions.validate_execution(w, self.pay(w, [
            {"metric": "league_credit_received", "operator": "==", "value": 1.0, "source": "gate"}]))
        self.assertEqual(gate["code"], "EXECUTION_BLOCKED_CONDITION")

    def test_a_motion_with_no_floor_pays_in_full(self):
        w = world()
        politics.apply_motion(w, {**self.pay(w, []), "proposer": "A"})
        self.assertAlmostEqual(w.econ.gold, GOLD - 92612196.0, delta=5e3)


class TheInvariantGuard(unittest.TestCase):
    def test_a_breach_after_execution_is_reported(self):
        w = world()
        floor = [{"metric": "reserves_after_payment", "operator": ">=", "value": FLOOR, "source": "f"}]
        w.econ.gold = FLOOR + 1e6
        self.assertEqual(motion_actions.condition_execution_violation(w, floor), [])
        w.econ.gold = FLOOR - 5e6
        self.assertEqual([v["value"] for v in motion_actions.condition_execution_violation(w, floor)], [FLOOR])

    def test_the_mismatch_is_not_raised_when_the_motion_already_carried_the_floor(self):
        w = world()
        mo = carried_d1(w, with_cosponsor_motion=False)
        stored = [{"metric": "reserves_after_payment", "operator": ">=", "value": 55e6, "source": "own"}]
        accepted = [{"metric": "reserves_after_payment", "operator": ">=", "value": FLOOR, "source": "accepted",
                     "accepted_by": list("ABCDE")}]
        self.assertIsNone(motion_actions.condition_execution_mismatch(w, mo, accepted, stored))
        self.assertIsNotNone(motion_actions.condition_execution_mismatch(w, mo, accepted, []))

    def test_the_mismatch_says_whether_it_would_have_breached_the_floor(self):
        w = world()
        mo = carried_d1(w, with_cosponsor_motion=False)
        accepted = [{"metric": "reserves_after_payment", "operator": ">=", "value": FLOOR, "source": "a",
                     "accepted_by": list("ABCDE")}]
        self.assertTrue(motion_actions.condition_execution_mismatch(w, mo, accepted, [])["would_violate"])
        w.econ.gold = 900e6
        self.assertFalse(motion_actions.condition_execution_mismatch(w, mo, accepted, [])["would_violate"])

    def test_the_code_is_in_the_taxonomy(self):
        self.assertTrue(errors.is_registered("CONDITION_EXECUTION_MISMATCH"))


class TheTitleAndTheDescriptionOfD1(unittest.TestCase):
    """title = "pay half of arrears", description = "set aside half current reserves".

    Neither canonicalization nor rendering did this. D wrote a settle_arrears motion whose value was
    "half" (of the arrears, in the engine's grammar) and whose prose described setting aside half of
    the RESERVES, in the same answer. The title is an exact rendering of the structured fields; the
    description is the delegate's own text, carried through unchanged. The divergence is the model's."""

    def test_canonicalization_changes_neither_field(self):
        w = world()
        canonical = actions.normalize_motion_v2(w, RAW_D_MOTION)
        self.assertEqual((canonical["type"], canonical["subject"], canonical["value"], canonical["text"]),
                         ("settle_arrears", "reserves", "half", D1_TEXT))

    def test_the_title_is_a_faithful_rendering_of_the_structured_fields(self):
        w = world()
        canonical = actions.normalize_motion_v2(w, RAW_D_MOTION)
        self.assertEqual(actions.motion_summary(w, canonical), "pay half of inherited unpaid bills using reserves")

    def test_the_two_different_amounts_the_words_and_the_fields_describe(self):
        """Half the arrears is 108.0M crowns; half the reserves is 48.3M gold. The safeguard mattered
        because the structured reading was the larger of the two."""
        half_of_arrears = ARREARS * 0.5
        half_of_reserves = GOLD * 0.5
        self.assertAlmostEqual(half_of_arrears / 1e6, 108.0, places=1)
        self.assertAlmostEqual(half_of_reserves / 1e6, 48.3, places=1)


class EndToEndThroughARealCouncilMonth(unittest.TestCase):
    """Tabling, co-sponsorship, the response round, the vote and the execution, in one real month.

    Delegate A tables a payment of half the arrears from reserves. Delegate B tables the same payment
    with a reserve floor of 80M, which folds B in as a co-sponsor of A's motion (the floor-less
    motion is first on the table and is heard once). Whoever is listed in `demanders` states the floor
    in the response round, and all five vote yes. The world holds 84M in reserves and owes 20M, so half
    the arrears (10M) breaches an 80M floor and is limited to what sits above it."""

    FLOOR = 80e6

    def month(self, demanders):
        import shutil
        import tempfile
        from karamaniya.backends.scripted import ScriptedBackend
        from karamaniya.config import load_config
        from karamaniya.runner import _seats
        from karamaniya.storage import RunStore

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg = load_config(os.path.join(root, "council.scripted.toml"))
        mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
        cfg = {**cfg, "mapping": mapping}
        tmp = tempfile.mkdtemp(prefix="karamaniya-floor-")
        self.addCleanup(shutil.rmtree, tmp, True)
        w = new_world(cfg["run"]["seed"], 12, member_ids=list(mapping))
        w.econ.gold, w.econ.arrears = 84e6, 20e6
        w.econ.arrears_by = {"civil_service": 12e6, "contractors": 8e6}
        seats = _seats(cfg, mapping)
        plain ={"type": "settle_arrears", "subject": "reserves", "value": "half", "action": {}, "force_agenda": False,
                 "text": "Pay half of the inherited unpaid bills from reserves.", "conditions": []}
        with_floor = {**plain, "conditions": [{"metric": "reserves_after_payment", "operator": ">=", "value": 80,
                                               "source": "Treasury cash desk"}]}

        class Backend(ScriptedBackend):
            def call(self, system, user, schema, context):
                res = super().call(system, user, schema, context)
                member, phase, data = context.get("member"), context.get("phase"), res.data
                if not isinstance(data, dict):
                    return res
                payment = next((m["id"] for m in context.get("motions") or [] if m.get("type") == "settle_arrears"), None)
                if phase == "session" and member in ("A", "B"):
                    data["motions"] = [dict(plain if member == "A" else with_floor)]
                elif phase == "revision" and payment and member in demanders:
                    data["demands"] = [{"motion_id": payment, "demand": "Cap the payment at the 80M reserve floor."}]
                elif phase == "decision" and payment and payment in (data.get("votes") or {}):
                    data["votes"][payment] = "yes"
                return res

        for seat in seats.values():
            seat.backend = Backend(seat.cfg)
        council = Council(w, seats, cfg["run"], RunStore(os.path.join(tmp, "r")))
        council.store.save_config(cfg)
        council.survey()
        council.diagnose_founding()
        council.form_government()
        record = council.run_month()
        return record, w, next(m for m in record["motions"] if m["type"] == "settle_arrears")

    def test_the_floor_the_whole_council_asked_for_limits_the_payment(self):
        record, w, entry = self.month(demanders="ABCDE")
        self.assertEqual(entry["cosponsors"], ["B"])
        self.assertEqual(entry["sponsor_conditions"]["B"][0]["value"], self.FLOOR)
        self.assertEqual((entry["status"], entry["execution_status"]), ("PASSED_CONDITIONALLY", "EXECUTED"))
        self.assertEqual(entry["accepted_conditions"][0]["accepted_by"], list("ABCDE"))
        self.assertIn("limited to keep reserves at the reserve floor of 80.0M", entry["execution_result"])
        self.assertAlmostEqual(entry["world_state_after"]["reserves"], self.FLOOR, delta=1.0)
        self.assertTrue(entry["condition_execution_mismatch"]["would_violate"])
        self.assertEqual(entry["condition_results"][0]["capped"], True)
        self.assertEqual([e["code"] for e in errors.since(w, 0) if e["code"] == "CONDITION_EXECUTION_MISMATCH"],
                         ["CONDITION_EXECUTION_MISMATCH"])

    def test_a_floor_only_the_cosponsor_asked_for_does_not_bind(self):
        record, w, entry = self.month(demanders="")
        self.assertEqual(entry["cosponsors"], ["B"])
        self.assertNotIn("accepted_conditions", entry)
        self.assertEqual(entry["execution_status"], "EXECUTED")
        self.assertNotIn("reserve floor", entry["execution_result"])
        self.assertLess(entry["world_state_after"]["reserves"], self.FLOOR - 5e6, "paid in full, as before")

    def test_a_floor_three_of_five_asked_for_binds(self):
        record, w, entry = self.month(demanders="ABC")
        self.assertEqual(entry["accepted_conditions"][0]["accepted_by"], list("ABC"))
        self.assertAlmostEqual(entry["world_state_after"]["reserves"], self.FLOOR, delta=1.0)


if __name__ == "__main__":
    unittest.main()
