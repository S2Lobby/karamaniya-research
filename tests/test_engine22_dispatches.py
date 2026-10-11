"""Engine 22, slice "private dispatches": a foreign answer sent privately to an office reaches the member who holds that
office, in full and to nobody else, and the League's credit is stated to the Treasury and the Head of Government.

Run 20261011-105713-seed1: eight private dispatches (Months 3-10) were in its world state and in none of its 226 prompts.
In Month 7 Interior still wrote "League 50M loan if approved covers it" to Army, after the League had approved 50M in
Month 6.
"""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import briefing, decision_context, director, economy, foreign, intelligence  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

LEAGUE = "Maritime League"
DISPATCH_HEADING = "PRIVATE FOREIGN DISPATCHES TO YOUR OFFICES"
CREDIT = "League credit:"
OFFICES = {"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"}
FREEZE = "The League has frozen the remaining loan tranches after its fiscal review."


def world(seed: int = 11):
    """A v2 world with every office held: head A, treasury B, interior C, army D, navy E."""
    w = new_world(seed, 36, member_ids=list("ABCDE"))
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update(OFFICES)
    return w


def office_text(w, mid: str, phase: str = "session") -> str:
    """The office section for a delegate, after the month's reports are made (the council makes them first)."""
    intelligence.generate(w)
    return intelligence.office_context(w, mid, phase)


def decision_prompt(w, mid: str, phase: str = "decision") -> str:
    intelligence.generate(w)
    text, _ = decision_context.build(w, mid, phase, public_brief="BRIEF", motions=[], instructions="Speak.")
    return text


def dispatch_line(sender: str, channel: str, text: str) -> str:
    """One dispatch in the annex's format (briefing.annex)."""
    return f'- From {sender} via {channel}: "{text}"'


def credit_line(w, mid: str):
    return next((row for row in office_text(w, mid).splitlines() if row.startswith(CREDIT)), None)


def approve_loan(w, amount: float = 40) -> None:
    """A loan the Treasury asked for, approved by the League on its own terms (director._league_reply)."""
    w.set_league_trust(.55)
    director._league_reply(w, "loan", amount)


class DispatchesReachTheirOffice(unittest.TestCase):
    """A dispatch to an office is listed for the member who holds it, in full, and for no other member."""

    def test_a_treasury_dispatch_is_in_full_for_the_treasury_and_for_no_other_member(self):
        w = world()
        text = ("The League approves a loan of 40 million in gold, paid out over the coming months at 7.1% interest, "
                "on conditions that the deficit stays below 5% of output and debt service continues for six months.")
        director._private_msg(w, LEAGUE, "treasury", text)
        line = dispatch_line(LEAGUE, "treasury", text)
        self.assertIn(DISPATCH_HEADING, office_text(w, "B"))
        self.assertIn(line, office_text(w, "B"))
        self.assertIn(line, decision_prompt(w, "B"))
        for mid in "ACDE":
            with self.subTest(member=mid):
                self.assertNotIn(text, office_text(w, mid))
                self.assertNotIn(text, decision_prompt(w, mid))

    def test_the_loan_answer_the_league_gives_reaches_the_treasury_as_written(self):
        w = world()
        approve_loan(w)
        self.assertGreater(w.dip.league_loan_pending, 0, "the League should have approved a loan")
        sent = w.dip.private_inbox[-1]
        self.assertEqual(sent["office"], "treasury")
        line = dispatch_line(sent["from"], "treasury", sent["text"])
        self.assertIn(line, office_text(w, "B"))
        self.assertIn(line, decision_prompt(w, "B"))
        for mid in "ACDE":
            with self.subTest(member=mid):
                self.assertNotIn(sent["text"], decision_prompt(w, mid))

    def test_a_dispatch_to_a_vacant_office_reaches_the_head_of_government(self):
        w = world()
        w.const.offices["treasury"] = None
        director._private_msg(w, LEAGUE, "treasury", "The League declines a new trade agreement.")
        sent = w.dip.private_inbox[-1]
        self.assertEqual(sent["office"], "head")
        line = dispatch_line(LEAGUE, "treasury", sent["text"])
        self.assertIn(line, office_text(w, "A"))
        self.assertIn(line, decision_prompt(w, "A"))
        for mid in "BCDE":
            with self.subTest(member=mid):
                self.assertNotIn(sent["text"], office_text(w, mid))

    def test_a_dispatch_is_listed_in_every_phase(self):
        w = world()
        text = "The League declines a new trade agreement."
        director._private_msg(w, LEAGUE, "treasury", text)
        line = dispatch_line(LEAGUE, "treasury", text)
        for phase in ("independent opening", "session", "responses and revisions", "decision"):
            with self.subTest(phase=phase):
                self.assertIn(line, office_text(w, "B", phase))

    def test_a_long_dispatch_is_never_shortened(self):
        w = world()
        text = "The League will review the credit line in detail, " * 30 + "and writes again in Month 9."
        director._private_msg(w, LEAGUE, "treasury", text)
        self.assertIn(dispatch_line(LEAGUE, "treasury", text), office_text(w, "B"))
        self.assertIn(dispatch_line(LEAGUE, "treasury", text), decision_prompt(w, "B"))

    def test_the_dispatches_follow_the_office_reports(self):
        w = world()
        director._private_msg(w, LEAGUE, "treasury", "The League declines a new trade agreement.")
        text = office_text(w, "B")
        self.assertIn(DISPATCH_HEADING, text)
        self.assertLess(text.index("You decide whether to share these reports"), text.index(DISPATCH_HEADING))

    def test_the_league_freeze_of_the_remaining_tranches_reaches_the_treasury(self):
        w = world()
        w.econ.deficit = .20 * w.econ.gdp_nominal        # above the League's 5% ceiling, default risk above 42%
        w.policy.debt_service = "pay"
        approve_loan(w, 100)
        self.assertGreater(w.dip.league_loan_pending, 0)
        foreign.league_month(w)
        self.assertEqual(w.dip.league_loan_pending, 0)
        line = dispatch_line(w.names["league"], "credit review", FREEZE)
        self.assertIn(line, office_text(w, "B"))
        self.assertIn(line, decision_prompt(w, "B"))


class LeagueCreditLine(unittest.TestCase):
    """The Treasury and the Head of Government are told the League's credit once it is approved, in one line."""

    def test_there_is_no_credit_line_before_any_approval(self):
        w = world()
        self.assertIsNone(credit_line(w, "A"))
        self.assertIsNone(credit_line(w, "B"))
        w.set_league_trust(.20)                          # too distrusted for a loan: the League declines
        director._league_reply(w, "loan", 40)
        self.assertEqual(w.dip.league_loan_pending, 0)
        self.assertIsNone(credit_line(w, "B"))

    def test_the_treasury_and_the_head_are_told_the_credit_and_no_other_member(self):
        w = world()
        approve_loan(w)
        self.assertIsNotNone(credit_line(w, "A"))
        self.assertIsNotNone(credit_line(w, "B"))
        for mid in "CDE":
            with self.subTest(member=mid):
                self.assertIsNone(credit_line(w, mid))

    def test_after_a_tranche_the_line_gives_the_state_figures(self):
        w = world()
        approve_loan(w, 40)
        economy.trade_and_food(w, economy.produce(w))
        loan = w.foreign["league"]["loan"]
        self.assertAlmostEqual(loan["principal"], 25e6)
        self.assertAlmostEqual(w.dip.league_loan_pending, 15e6)
        line = credit_line(w, "B")
        self.assertIn(f"{loan['principal'] / 1e6:,.0f}M gold drawn", line)
        self.assertIn(f"{w.dip.league_loan_pending / 1e6:,.0f}M approved and still to come", line)
        self.assertIn(f"interest {loan['interest']:.1%} a year", line)
        self.assertIn(line, decision_prompt(w, "B"))
        self.assertEqual(credit_line(w, "A"), line)

    def test_the_line_reads_the_state_as_it_is_now(self):
        w = world()
        approve_loan(w, 40)
        w.foreign["league"]["loan"]["principal"] = 10e6
        w.dip.league_loan_pending = 0.0
        line = credit_line(w, "B")
        self.assertIn("10M gold drawn", line)
        self.assertIn("0M approved and still to come", line)

    def test_a_tranche_is_set_against_the_deficit_before_any_borrowing(self):
        """The line's budget clause in a month whose deficit is larger than the tranche: what is borrowed or left unpaid
        falls by the whole tranche, and the reserves are not credited with it (economy.trade_and_food, economy.fiscal)."""
        w = world()
        w.policy.welfare += .06                          # a deficit of about 35M a month, above the 25M tranche
        approve_loan(w, 40)
        twin = copy.deepcopy(w)
        twin.dip.league_loan_pending = 0.0
        prod, twin_prod = economy.produce(w), economy.produce(twin)
        trade = economy.trade_and_food(w, prod)
        twin_trade = economy.trade_and_food(twin, twin_prod)
        self.assertAlmostEqual(trade["loans"], 25e6, msg="at most 25M a month")
        self.assertEqual(twin_trade["loans"], 0)
        self.assertEqual(w.econ.gold, twin.econ.gold, "a tranche does not add to the gold reserves")
        economy.fiscal(w, prod, trade)
        economy.fiscal(twin, twin_prod, twin_trade)
        self.assertAlmostEqual(w.econ.loans_in, 25e6)
        self.assertAlmostEqual(twin.econ.borrowed + twin.econ.arrears - w.econ.borrowed - w.econ.arrears, 25e6,
                               delta=1.0, msg="what is borrowed or left unpaid falls by the whole tranche")

    def test_a_surplus_beyond_the_deficit_repays_domestic_debt(self):
        """The line's clause for a month whose deficit is smaller than the tranche: nothing is borrowed, and the rest of
        the tranche repays domestic debt, so the domestic debt falls by the whole tranche (economy.fiscal). The line says
        this, and does not say that the crown borrows the whole tranche less: here it borrows only what it needed."""
        w = world()
        approve_loan(w, 40)
        twin = copy.deepcopy(w)
        twin.dip.league_loan_pending = 0.0
        prod, twin_prod = economy.produce(w), economy.produce(twin)
        trade = economy.trade_and_food(w, prod)
        twin_trade = economy.trade_and_food(twin, twin_prod)
        economy.fiscal(w, prod, trade)
        economy.fiscal(twin, twin_prod, twin_trade)
        self.assertEqual(w.econ.borrowed, 0.0)
        self.assertAlmostEqual(twin.econ.debt_dom - w.econ.debt_dom, 25e6, delta=1.0)


class LeagueReviewConditions(unittest.TestCase):
    """The conditions the line states are the ones foreign.league_month applies: a failed condition freezes the
    remaining tranches only when the League's default-risk estimate is above 42%."""

    @staticmethod
    def approved_loan(deficit_ratio: float):
        w = world()
        w.econ.deficit = deficit_ratio * w.econ.gdp_nominal
        w.policy.debt_service = "pay"
        approve_loan(w, 40)
        return w

    def test_a_failed_condition_freezes_the_tranches_above_a_default_risk_of_42_percent(self):
        w = self.approved_loan(.20)
        self.assertGreater(w.dip.league_loan_pending, 0)
        foreign.league_month(w)
        self.assertEqual(w.dip.league_loan_pending, 0)

    def test_a_failed_condition_alone_does_not_freeze_the_tranches(self):
        w = self.approved_loan(.10)
        self.assertGreater(w.dip.league_loan_pending, 0)
        foreign.league_month(w)
        self.assertGreater(w.dip.league_loan_pending, 0)


class TheLegacyAnnexIsUnchanged(unittest.TestCase):
    """briefing.annex keeps its own format and its own holders, and gets no credit line."""

    def test_the_annex_lists_the_dispatch_in_its_own_format_and_gets_no_credit_line(self):
        w = world()
        approve_loan(w, 40)
        director._private_msg(w, LEAGUE, "navy", "The League will supply equipment for about 1200 soldiers a month.")
        intelligence.generate(w)
        before = briefing.annex(w, "B")
        treasury_msg = next(m for m in w.dip.private_inbox if m["office"] == "treasury")
        self.assertIn(dispatch_line(treasury_msg["from"], "treasury", treasury_msg["text"]), before)
        self.assertNotIn("supply equipment", before)
        self.assertNotIn(CREDIT, before)
        self.assertIn("supply equipment", briefing.annex(w, "E"))
        self.assertIn(f"League loans pending payment: {w.dip.league_loan_pending / 1e6:,.0f}M gold.",
                      briefing.annex(w, "A"))
        office_text(w, "B", "decision")
        self.assertEqual(briefing.annex(w, "B"), before, "reading the office context changes nothing")


if __name__ == "__main__":
    unittest.main()
