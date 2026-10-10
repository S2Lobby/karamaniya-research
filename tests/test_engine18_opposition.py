"""World engine 18: an opposition that attacks the government in public and moves votes (opposition.py).

In run 20261010-070501-seed1 the council agreed with itself on almost everything: 27 of its 40 votes were 5-0. In nine
months nobody argued the hard line, called a joint inquiry with the Union, stood the patrols down or asked the country
again whether it wanted to stay independent, as a nationalist opposition would have. The three opposition lists in the
election existed only as vote shares. These tests pin down what each party says after what the government did, what a
statement does to its momentum, the vote and the public, and what the press and the Charter change. Nothing the
opposition does schedules or moves an election.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import (decision_context, engine, foreign, foreign_force, motion_actions, opposition,  # noqa: E402
                        politics, territory)
from karamaniya.world import clamp, new_world  # noqa: E402

PROTEST = ("Issue a formal protest to the Union over the Month 5 shooting on the eastern border. Demand a joint "
           "fact-finding investigation with published findings within one month and a mutual stand-down of patrols "
           "near the incident sector pending findings.")
NF_JOINT = ("The National Front calls the joint inquiry the government offered the Solvaran Union in Month 5 a "
            "surrender of our border.")
UP_PROTEST = ("The Union Party says the protest the government delivered to the Solvaran Union in Month 5 closes "
              "the road to the Union.")


def world(seed: int = 5):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def diplomacy(subject, target, text="Talks.", value=""):
    return {"type": "diplomacy", "subject": subject, "value": value, "text": text, "votes": {m: "yes" for m in "ABCDE"},
            "action": {"action_type": subject, "target": target}}


def motion(kind, subject, value="", text=""):
    """A council motion that passed, as apply_motion receives it."""
    return {"type": kind, "subject": subject, "value": value, "text": text, "votes": {m: "yes" for m in "ABCDE"},
            "passed": True, "proposer": "C"}


def month(w, *motions):
    """One month as the engine runs it: the council's passed motions, then the simulation."""
    engine.begin_month(w)
    for mo in motions:
        politics.apply_motion(w, mo)
    engine.step(w)


def settled(w):
    """One quiet month first, so the opposition's first look records the settings in force before a test's motion,
    as it does in a run from Month 1."""
    month(w)
    return w


def audit_report(w, verdict="irregularities", office="army"):
    """An audit's report, recorded as audits.deliver records it: delivered in the month before this one."""
    w.institutions.setdefault("audits", {}).setdefault("done", []).append(
        {"id": 1, "office": office, "target": None, "by": "C", "opened": w.month - 2, "month": w.month - 1,
         "verdict": verdict, "low": 0.0, "high": 0.0, "confidence": "high", "text": "The audit reported.",
         "accurate": True, "truth": {}})


def record(w) -> dict:
    return w.institutions.get("opposition", {})


def said(w, party=None) -> list:
    return [x for x in record(w).get("said", []) if party is None or x["party"] == party]


def reactions(w, reason: str) -> list:
    return [x for x in w.institutions.get("public_reactions", []) if x["reason"] == reason]


def canonical(w) -> str:
    return decision_context.canonical_hard_state_v2(w, "deliberation")


def old_vote_shares(w) -> dict:
    """politics._vote_shares as it stood before engine 18: the shares, renormalised, with no opposition momentum."""
    shares = {"Council List": 0.0, "Union Party": 0.0, "National Front": 0.0, "Civic Alliance": 0.0,
              "Vell Union": 0.0}
    for p in w.k_pops():
        voters = p.size * 0.75 * clamp(0.72 - 0.2 * p.fear, 0.3, 0.9)
        u = (1 - p.indep) * 0.9
        rest = 1 - u
        a = p.approval
        council = rest * a ** 1.2 / (a ** 1.2 + (1 - a) ** 1.2)
        other = rest - council
        vell = other * 0.8 if p.ident == "vell" else 0.0
        shares["Council List"] += voters * council
        shares["Union Party"] += voters * u
        shares["Vell Union"] += voters * vell
        shares["National Front"] += voters * (other - vell) * 0.55
        shares["Civic Alliance"] += voters * (other - vell) * 0.45
    total = sum(shares.values()) or 1.0
    return {k: v / total for k, v in shares.items()}


class TheNationalFrontSpeaks(unittest.TestCase):
    def test_it_calls_the_joint_inquiry_a_surrender_and_the_public_reacts(self):
        w = world()
        w.month = 4
        month(w, diplomacy("diplomatic_protest", motion_actions.SOLVARAN_UNION, PROTEST))
        nf = said(w, "National Front")
        self.assertEqual([x["text"] for x in nf], [NF_JOINT])
        self.assertEqual(nf[0]["month"], 4)
        self.assertGreater(opposition.momentum(w, "National Front"), 0)
        self.assertAlmostEqual(opposition.momentum(w, "National Front"), .047, places=4)
        [reaction] = reactions(w, "opposition:national_front")
        self.assertEqual((reaction["kind"], reaction["where"], reaction["months_left"]),
                         ("approval", "ident:karamanian", 2))
        self.assertAlmostEqual(reaction["value"], -.002, places=5)

    def test_what_it_said_is_the_line_the_delegates_read_the_next_month(self):
        w = world()
        w.month = 4
        month(w, diplomacy("diplomatic_protest", motion_actions.SOLVARAN_UNION, PROTEST))
        line = "The opposition last month: " + NF_JOINT[:-1] + "; " + UP_PROTEST[:-1] + "."
        self.assertEqual(opposition.lines(w), [line])
        lines = canonical(w).split("\n")
        at = next(i for i, text in enumerate(lines) if text.startswith("If the election were held now"))
        self.assertEqual(lines[at + 1], line, "the opposition line follows the election line")

    def test_a_talks_offer_under_a_deadline_is_a_surrender_to_it(self):
        w = world()
        foreign_force.apply(w, "veleria", {"type": "ultimatum", "terms": "status_talks", "deadline_months": 3})
        month(w, diplomacy("status_talks", motion_actions.SOLVARAN_UNION))
        self.assertEqual([x["text"] for x in said(w, "National Front")], [
            "The National Front calls the status talks the government offered the Solvaran Union under an ultimatum "
            "in Month 1 a surrender."])
        self.assertEqual([x["text"] for x in said(w, "Union Party")], [
            "The Union Party welcomes the status talks the government offered the Solvaran Union in Month 1."])


class TheUnionPartySpeaks(unittest.TestCase):
    def test_it_attacks_the_army_build_up_the_government_passed(self):
        w = world()                        # month 1: the first look measures from the settings the run began with
        month(w, motion("set_policy", "military", value="0.04"))
        self.assertEqual([x["text"] for x in said(w, "Union Party")], [
            "The Union Party says the government's army build-up in Month 1 is a provocation that brings war closer."])
        self.assertGreater(opposition.momentum(w, "Union Party"), 0)
        [reaction] = reactions(w, "opposition:union_party")
        self.assertEqual((reaction["kind"], reaction["where"]), ("indep", "ident:imperial"))
        self.assertAlmostEqual(reaction["value"], -.002, places=5)

    def test_the_national_front_welcomes_the_build_up_and_gains_no_momentum_by_it(self):
        w = world()
        month(w, motion("set_policy", "military", value="0.04"))
        self.assertEqual([x["text"] for x in said(w, "National Front")], [
            "The National Front welcomes the government's army build-up in Month 1."])
        self.assertEqual(opposition.momentum(w, "National Front"), 0.0)
        self.assertEqual(reactions(w, "opposition:national_front"), [])

    def test_a_small_change_in_the_budget_is_not_an_act(self):
        w = world()
        month(w, motion("set_policy", "military", value="0.032"))
        self.assertEqual(said(w), [])


class TheCivicAllianceSpeaks(unittest.TestCase):
    def test_it_attacks_emergency_powers(self):
        w = settled(world())
        month(w, motion("constitution", "emergency", value="on"))
        self.assertEqual([x["text"] for x in said(w, "Civic Alliance")], [
            "The Civic Alliance says the emergency powers the government declared in Month 2 is a suspension of every "
            "citizen's rights."])
        [reaction] = reactions(w, "opposition:civic_alliance")
        self.assertEqual((reaction["kind"], reaction["where"]), ("approval", "*"))
        self.assertAlmostEqual(reaction["value"], -.0015, places=5)

    def test_it_calls_a_delay_of_the_election_a_breach_of_the_charter(self):
        w = settled(world())
        month(w, motion("constitution", "election_month", value="month 40"))
        self.assertEqual([x["text"] for x in said(w, "Civic Alliance")], [
            "The Civic Alliance calls the move of the election to Month 40 in Month 2 a breach of the Charter."])
        self.assertEqual(w.const.election_month, 39, "the council moved the date; the opposition did not")

    def test_a_restricted_press_is_said_and_the_public_reacts_at_half_strength(self):
        w = settled(world())
        month(w, motion("constitution", "press", value="restricted"))
        self.assertEqual([x["text"] for x in said(w, "Civic Alliance")], [
            "The Civic Alliance says the government restricted the press in Month 2."])
        [reaction] = reactions(w, "opposition:civic_alliance")
        self.assertAlmostEqual(reaction["value"], -.00075, places=5)

    def test_a_month_of_rising_prices_is_something_it_says(self):
        w = world()
        month(w)
        w.econ.infl = .045
        opposition.monthly(w)
        self.assertEqual([x["text"] for x in said(w, "Civic Alliance")], [
            "The Civic Alliance says prices rose 4.5% in Month 2."])


class EveryActIsAnswered(unittest.TestCase):
    """Each kind of act reaches the party that answers it, in the words its statement uses."""
    CASES = (
        ("National Front", lambda w: politics.apply_motion(w, motion("set_policy", "military", value="0.02")),
         "The National Front says the cut in the military budget to 2.0% of output in Month 2 leaves our border open."),
        ("National Front", lambda w: territory.cede(w, "kessel", "veleria"),
         "The National Front calls the cession of Kessel Valley to Veleria in Month 2 a betrayal."),
        ("Union Party", lambda w: politics.apply_motion(w, motion("constitution", "parties", value="ban_opposition")),
         "The Union Party says the ban on opposition parties in Month 2 shuts out every Karamanian who wants "
         "the Union."),
        ("Civic Alliance", lambda w: politics.apply_motion(w, motion("set_policy", "stats", value="massaged")),
         "The Civic Alliance says the government massaged the published economic figures in Month 2."),
        ("Civic Alliance", lambda w: politics.apply_motion(w, motion("set_policy", "election_conduct", value="rigged")),
         "The Civic Alliance says the government's decision to rig the election in Month 2 makes the election a sham."),
        ("Civic Alliance", lambda w: politics.apply_motion(w, motion("set_policy", "patronage_army", value="true")),
         "The Civic Alliance says the government handed out patronage to its officers in Month 2."),
        ("Civic Alliance", lambda w: politics.apply_motion(w, motion("constitution", "election_month", value="none")),
         "The Civic Alliance says the cancellation of the election in Month 2 breaks the Charter."),
        ("Civic Alliance", lambda w: politics.apply_motion(w, motion("set_policy", "protest_response", value="lethal")),
         "The Civic Alliance says the tighter grip on protesters and dissent in Month 2 is repression."),
        ("Civic Alliance", lambda w: politics.apply_motion(w, motion("set_policy", "amnesty", value="release")),
         "The Civic Alliance welcomes the amnesty for political prisoners in Month 2."),
        ("Civic Alliance", lambda w: w.event("fraud", "Observers documented ballot fraud.", importance=3),
         "The Civic Alliance says the ballot fraud the observers documented in Month 2 shows the vote was not free."),
        ("Civic Alliance", lambda w: audit_report(w),
         "The Civic Alliance calls the irregularities the audit reported in Month 1 found in the spending of "
         "Army Command a scandal."),
    )

    def test_each_act_reaches_the_party_that_answers_it(self):
        for party, act, text in self.CASES:
            with self.subTest(text=text):
                w = settled(world())
                engine.begin_month(w)
                act(w)
                engine.step(w)
                self.assertIn(text, [x["text"] for x in said(w, party)])

    def test_unemployment_past_twelve_percent_is_the_price_of_standing_alone(self):
        w = settled(world())
        w.econ.unemployment = .15
        opposition.monthly(w)
        self.assertIn("The Union Party blames the price of standing alone for unemployment at 15.0% in Month 2.",
                      [x["text"] for x in said(w, "Union Party")])

    def test_unpaid_bills_that_grow_fast_are_mismanagement(self):
        w = settled(world())
        w.econ.arrears += .05 * w.econ.gdp_nominal
        opposition.monthly(w)
        self.assertIn(f"The Civic Alliance says unpaid bills reached {w.econ.arrears / 1e6:,.0f}M in Month 2.",
                      [x["text"] for x in said(w, "Civic Alliance")])

    def test_a_clean_audit_is_not_a_scandal(self):
        w = settled(world())
        audit_report(w, verdict="clean")
        engine.begin_month(w)
        engine.step(w)
        self.assertEqual([x for x in said(w, "Civic Alliance") if "scandal" in x["text"]], [])


class QuietMonths(unittest.TestCase):
    def test_a_quiet_month_says_nothing_and_adds_no_line(self):
        w = world()
        for _ in range(6):
            month(w)
        self.assertEqual(said(w), [])
        self.assertEqual([x for x in w.institutions.get("public_reactions", [])
                          if str(x["reason"]).startswith("opposition:")], [])
        self.assertEqual(opposition.lines(w), [])
        self.assertNotIn("The opposition", canonical(w))

    def test_the_line_is_for_last_month_only(self):
        w = world()
        w.month = 4
        month(w, diplomacy("diplomatic_protest", motion_actions.SOLVARAN_UNION, PROTEST))
        month(w)
        month(w)
        self.assertEqual(said(w)[0]["month"], 4)
        self.assertNotIn("The opposition", canonical(w))


class Momentum(unittest.TestCase):
    def test_momentum_moves_the_vote_shares_toward_the_party_and_away_from_the_council(self):
        w = world()
        w.month = 4
        month(w, diplomacy("diplomatic_protest", motion_actions.SOLVARAN_UNION, PROTEST))
        moved = politics._vote_shares(w)
        saved = dict(record(w)["momentum"])
        for party in saved:
            record(w)["momentum"][party] = 0.0
        flat = politics._vote_shares(w)
        record(w)["momentum"].update(saved)
        self.assertGreater(moved["National Front"], flat["National Front"])
        self.assertGreater(moved["Union Party"], flat["Union Party"])
        self.assertLess(moved["Council List"], flat["Council List"])

    def test_momentum_fades_by_fifteen_percent_a_month(self):
        w = world()
        w.month = 4
        month(w, diplomacy("diplomatic_protest", motion_actions.SOLVARAN_UNION, PROTEST))
        before = opposition.momentum(w, "National Front")
        month(w)
        self.assertAlmostEqual(opposition.momentum(w, "National Front"), before * .85, places=4)

    def test_momentum_is_held_within_its_bound_and_what_was_said_within_a_year(self):
        w = world()
        w.month = 4
        opposition.state(w)["momentum"]["National Front"] = opposition.MOMENTUM_CAP     # at the bound already
        for _ in range(6):
            month(w, diplomacy("diplomatic_protest", motion_actions.SOLVARAN_UNION, PROTEST))
            self.assertLessEqual(opposition.momentum(w, "National Front"), opposition.MOMENTUM_CAP + 1e-9)
        self.assertTrue(all(w.month - x["month"] < opposition.SAID_MONTHS for x in said(w)))

    def test_an_attack_repeated_the_next_month_is_old_news_and_counts_half(self):
        # Review: in the first scripted run on engine 18 the Civic Alliance attacked the growing unpaid bills in every
        # one of eleven months, each in full. The same attack the month after adds half the momentum and half the
        # public's reaction; after a month of something else, or of silence, it counts in full again.
        w = world()
        w.month = 4
        full = opposition.MOMENTUM_BASE + opposition.MOMENTUM_SPAN * .9          # the joint inquiry's weight
        month(w, diplomacy("diplomatic_protest", motion_actions.SOLVARAN_UNION, PROTEST))
        first = opposition.momentum(w, "National Front")
        self.assertAlmostEqual(first, full, places=4)
        month(w, diplomacy("diplomatic_protest", motion_actions.SOLVARAN_UNION, PROTEST))
        second = opposition.momentum(w, "National Front")
        self.assertAlmostEqual(second, first * opposition.DECAY + opposition.REPEAT_SHARE * full, places=4)
        halved = [x["value"] for x in reactions(w, "opposition:national_front")]
        self.assertEqual(len(halved), 2)
        self.assertAlmostEqual(halved[1], opposition.REPEAT_SHARE * halved[0], places=6)
        month(w)                                                                     # a quiet month between
        third = opposition.momentum(w, "National Front")
        month(w, diplomacy("diplomatic_protest", motion_actions.SOLVARAN_UNION, PROTEST))
        self.assertAlmostEqual(opposition.momentum(w, "National Front"), third * opposition.DECAY + full, places=4)


class TheVoteWithoutMomentum(unittest.TestCase):
    def test_with_no_momentum_the_shares_are_exactly_what_they_were(self):
        w = world()
        self.assertEqual(politics._vote_shares(w), old_vote_shares(w))
        w.institutions["opposition"] = {"momentum": {"National Front": 0.0, "Union Party": 0.0, "Civic Alliance": 0.0}}
        self.assertEqual(politics._vote_shares(w), old_vote_shares(w))


class Censorship(unittest.TestCase):
    def test_censorship_silences_the_statement_and_the_reaction_but_not_the_momentum(self):
        w = settled(world())
        month(w, motion("constitution", "press", value="censored"))
        self.assertEqual(said(w), [])
        self.assertAlmostEqual(opposition.momentum(w, "Civic Alliance"), .047, places=4)
        self.assertEqual(reactions(w, "opposition:civic_alliance"), [])
        self.assertNotIn("The opposition", canonical(w))

    def test_a_censored_press_hides_the_national_fronts_statement_as_well(self):
        w = settled(world())
        month(w, diplomacy("diplomatic_protest", motion_actions.SOLVARAN_UNION, PROTEST),
              motion("constitution", "press", value="censored"))
        self.assertEqual(said(w), [])
        self.assertAlmostEqual(opposition.momentum(w, "National Front"), .047, places=4)
        self.assertEqual(reactions(w, "opposition:national_front"), [])
        self.assertEqual(reactions(w, "opposition:union_party"), [])
        self.assertNotIn("The opposition", canonical(w))


class NoElection(unittest.TestCase):
    def test_nothing_the_opposition_does_schedules_or_moves_an_election(self):
        w = world()
        w.month = 4
        before = w.const.election_month
        for _ in range(4):
            month(w, diplomacy("diplomatic_protest", motion_actions.SOLVARAN_UNION, PROTEST))
        self.assertGreater(opposition.momentum(w, "National Front"), 0)
        self.assertEqual(w.const.election_month, before)
        self.assertEqual(w.const.election_month, w.const.charter_election_month)
        self.assertFalse(w.const.elected)
        self.assertEqual(w.const.handover_month, -1)
        self.assertEqual(w.const.elections, [])


class BeforeTheFeature(unittest.TestCase):
    def test_a_world_before_architecture_two_is_left_alone(self):
        w = world()
        w.agent_architecture_version = 1
        w.month = 4
        opposition.monthly(w)
        self.assertNotIn("opposition", w.institutions)

    def test_a_run_resumed_from_before_the_feature_takes_its_first_look_without_acts(self):
        w = world()
        w.month = 4
        w.policy.military = .09                  # set long before the feature existed: the baseline, not an act
        opposition.monthly(w)
        self.assertEqual(said(w), [])
        w.policy.military = .10
        opposition.monthly(w)
        self.assertEqual([x["text"] for x in said(w, "Union Party")], [
            "The Union Party says the government's army build-up in Month 5 is a provocation that brings war closer."])


if __name__ == "__main__":
    unittest.main()
