"""World engine 27 (wave 3, D): the six wider-diplomacy pairs and the demand/warning kinds.

The proposal in docs/DIPLOMACY_TARGETS_PROPOSAL.md section 4 names six pairs that the act-target table refused in
the recorded runs:

  status_talks to Dorsania and to Veleria;
  trade_talks to Veleria, to the Maritime League and to Dorsania;
  trade_deal to Dorsania.

The wave-3 plan widens those six and no others. A widened pair is a routing change first: each one needs a handler
that answers in the right party's voice, moves a small documented amount of state, and leaves a message, so an act
does not vanish after the table accepts it. The pairs the proposal keeps refused stay refused, and their refusal
still names the acts their target accepts (engine 24).

The second half pins the two new public communication kinds, `demand` and `warning`: the schema accepts them, the
prompt describes them neutrally, and each moves the world a little.

The sizes of the widened pairs' effects were left open by the proposal ("a design choice", "small"); the constants
and the reasons are in foreign.py and director.py, and the table is in docs/WIDER_DIPLOMACY.md.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, director, foreign, motion_actions as ma, politics, prompts, standing  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

SIX_PAIRS = (
    ("status_talks", ma.DORSANIA),
    ("status_talks", ma.VELERIA),
    ("trade_talks", ma.VELERIA),
    ("trade_talks", ma.MARITIME_LEAGUE),
    ("trade_talks", ma.DORSANIA),
    ("trade_deal", ma.DORSANIA),
)


def world(month: int = 4, human_factor: bool = True):
    w = new_world(11, 36, human_factor=human_factor)
    w.foreign = foreign.initial_state(w.seed)
    w.agent_architecture_version = 2
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    w.month = month
    return w


def motion(text: str, subject: str, action_type: str | None = None, target: str | None = None,
           value: str = "", **action) -> dict:
    payload = {"action_type": action_type or subject, "target": target, **action}
    return {"id": "M1", "proposer": "B", "type": "diplomacy", "subject": subject, "value": value,
            "text": text, "action": payload}


def answer(w, mo: dict) -> str:
    """Table and execute one motion as the council would after a vote, then let the power answer it."""
    result = politics.apply_motion(w, mo)
    director._answer_proposals(w)
    return result


def messages_from(w, name: str) -> list:
    return [m for m in (*w.dip.inbox, *w.dip.private_inbox) if m.get("from") == name]


class TheSixPairsAreInTheTable(unittest.TestCase):
    def test_the_six_census_pairs_are_received(self):
        for act, actor in SIX_PAIRS:
            with self.subTest(act=act, actor=actor):
                self.assertIn(actor, ma.DIPLOMATIC_TARGETS[act])

    def test_the_pairs_the_proposal_keeps_refused_stay_refused(self):
        # Section 4 recommends keeping every other widening out, and section 5 lists what stays refused: a ceasefire
        # to Veleria would end the Union's war, and join_union to Veleria would end the run.
        for act, actor in (("status_talks", ma.MARITIME_LEAGUE), ("trade_deal", ma.VELERIA),
                           ("ceasefire", ma.VELERIA), ("join_union", ma.VELERIA),
                           ("federation", ma.DORSANIA), ("grain_deal", ma.VELERIA),
                           ("alliance", ma.DORSANIA), ("military_aid", ma.DORSANIA)):
            with self.subTest(act=act, actor=actor):
                self.assertNotIn(actor, ma.DIPLOMATIC_TARGETS[act])
                clash = ma.conflict(world(), motion("", act, act, actor))
                reason = next(r for r in clash["reasons"] if r["code"] == "ACTION_NOT_VALID_FOR_TARGET")
                self.assertIn(". " + ma.ACTOR_NAMES[actor] + " accepts: ", reason["detail"])

    def test_a_refusal_names_the_widened_acts_too(self):
        w = world()
        detail = ma.validate_diplomatic_action(w, motion("", "trade_deal", "trade_deal", "VELERIA"))["detail"]
        self.assertEqual(detail, "a trade_deal can be addressed to Dorsania, Maritime League, not the Veleria. "
                                 "Veleria accepts: " + ", ".join(ma._accepted_acts(ma.VELERIA)))

    def test_the_six_pairs_are_records_with_the_right_party_and_no_refusal(self):
        for act, actor in SIX_PAIRS:
            with self.subTest(act=act, actor=actor):
                w = world()
                mo = motion("", act, act, actor)
                self.assertIsNone(ma.conflict(w, mo))
                politics.apply_motion(w, mo)
                self.assertEqual(w.dip.proposals[-1]["kind"], act)
                self.assertEqual(w.dip.proposals[-1]["party"], ma.party_of(actor))


class VeleriaAnswersItsOwnTwoPairs(unittest.TestCase):
    def test_trade_talks_to_veleria_ease_the_coal_embargo(self):
        w = world()
        w.dip.coal_embargo = .20
        gdp = w.rivals["veleria"].gdp_real
        answer(w, motion("Open trade talks with Veleria to secure reliable coal deliveries for our industry.",
                         "trade_talks", "trade_talks", "VELERIA"))
        self.assertAlmostEqual(w.dip.coal_embargo, .20 - director.VELERIA_TRADE_TALKS_RELIEF, places=6)
        self.assertGreater(w.rivals["veleria"].gdp_real, gdp, "easing the embargo gives Veleria its trade back")
        said = messages_from(w, w.names["veleria"])
        self.assertTrue(said, "Veleria does not answer its own trade talks")
        self.assertIn("coal", said[-1]["text"])
        self.assertEqual(w.foreign["actors"]["veleria"]["relations"]["karamaniya"]["trust"],
                         round(.20 + director.VELERIA_TALKS_TRUST, 3))

    def test_trade_talks_to_veleria_are_refused_in_a_war_and_change_nothing(self):
        w = world()
        w.dip.coal_embargo = .20
        w.dip.war = True
        answer(w, motion("Open trade talks with Veleria while the war runs.", "trade_talks", "trade_talks", "VELERIA"))
        self.assertEqual(w.dip.coal_embargo, .20)
        self.assertIn("war", messages_from(w, w.names["veleria"])[-1]["text"])

    def test_status_talks_to_veleria_are_answered_by_veleria_and_count_as_status_talks(self):
        w = world()
        answer(w, motion("Open talks on our status with Veleria.", "status_talks", "status_talks", "VELERIA"))
        self.assertEqual(w.foreign["status_talks"], [w.month])
        said = messages_from(w, w.names["veleria"])
        self.assertTrue(said, "Veleria does not answer a status talk addressed to it")
        self.assertNotIn(w.names["union"], {m["from"] for m in said},
                         "a talk addressed to Veleria is not answered in the Union's voice")
        self.assertEqual(w.foreign["actors"]["veleria"]["relations"]["karamaniya"]["trust"],
                         round(.20 + director.VELERIA_STATUS_TALKS_TRUST, 3))

    def test_a_rule_issued_status_demand_is_met_by_status_talks_to_veleria(self):
        w = world(month=4)
        w.dip.ultimatum = {"issued": 1, "deadline": 5, "terms": "Open negotiations on Karamaniya's status.",
                           "terms_id": "status_talks", "by": "veleria"}
        answer(w, motion("Open talks on our status with Veleria.", "status_talks", "status_talks", "VELERIA"))
        self.assertEqual(w.dip.ultimatum, {}, "the rule's status demand is met by the talks")

    def test_a_land_demand_is_not_met_by_status_talks_to_veleria(self):
        w = world(month=4)
        w.dip.ultimatum = {"issued": 1, "deadline": 5, "terms": "Cede Kessel Valley.",
                           "terms_id": "cede_region", "region": "kessel", "by": "veleria"}
        answer(w, motion("Open talks on our status with Veleria.", "status_talks", "status_talks", "VELERIA"))
        self.assertTrue(w.dip.ultimatum, "status talks do not answer a demand for land")
        self.assertIn("land", messages_from(w, w.names["veleria"])[-1]["text"].lower())

    def test_a_cabinet_issued_status_demand_is_left_for_its_cabinet_to_judge(self):
        w = world(month=4)
        w.dip.ultimatum = {"issued": 1, "deadline": 5, "terms": "Open negotiations on Karamaniya's status.",
                           "terms_id": "status_talks", "by": "veleria"}
        w.foreign["cabinet_month"] = {"veleria": 4}
        answer(w, motion("Open talks on our status with Veleria.", "status_talks", "status_talks", "VELERIA"))
        self.assertTrue(w.dip.ultimatum, "the issuing cabinet, not the engine, judges its own demand")


class DorsaniaAnswersItsOwnThreePairs(unittest.TestCase):
    def test_status_talks_to_dorsania_are_no_longer_no_standing(self):
        w = world()
        answer(w, motion("Open talks on our status with Dorsania.", "status_talks", "status_talks", "DORSANIA"))
        said = messages_from(w, w.names["dorsania"])
        self.assertTrue(said)
        self.assertNotIn("no standing", said[-1]["text"])
        self.assertIn("Union", said[-1]["text"])
        self.assertNotIn("status_talks", w.foreign, "Dorsania does not answer for the Union's status talks")

    def test_trade_talks_to_dorsania_are_answered_and_are_not_a_deal(self):
        w = world()
        w.dip.grain_embargo = .30
        before = w.foreign["actors"]["dorsania"]["relations"]["karamaniya"]["trust"]
        answer(w, motion("Renegotiate terms with Dorsania to secure grain imports.", "trade_talks", "trade_talks",
                         "DORSANIA"))
        said = messages_from(w, w.names["dorsania"])
        self.assertTrue(said)
        self.assertNotIn("no standing", said[-1]["text"])
        self.assertIn("grain", said[-1]["text"].lower())
        self.assertEqual(w.dip.grain_embargo, .30, "a talk is not a deal and does not move the embargo")
        self.assertEqual(w.foreign["actors"]["dorsania"]["relations"]["karamaniya"]["trust"],
                         round(before + foreign.DORSANIA_TALKS_TRUST, 3))

    def test_trade_deal_to_dorsania_is_the_grain_agreement_it_can_sign(self):
        w = world()
        w.dip.grain_embargo = .50
        answer(w, motion("Secure the Dorsania grain deal immediately.", "trade_deal", "trade_deal", "DORSANIA"))
        said = messages_from(w, w.names["dorsania"])
        self.assertTrue(said)
        self.assertNotIn("no standing", said[-1]["text"])
        self.assertIn("grain", said[-1]["text"].lower())
        self.assertAlmostEqual(w.dip.grain_embargo, .38, places=6)
        self.assertEqual(w.counters.get("dorsania_trade"), 1.0)

    def test_trade_deal_to_dorsania_is_declined_at_war(self):
        w = world()
        w.dip.grain_embargo = .50
        w.dip.war = True
        answer(w, motion("Secure the Dorsania grain deal immediately.", "trade_deal", "trade_deal", "DORSANIA"))
        self.assertEqual(w.dip.grain_embargo, .50)
        self.assertIn("decline", messages_from(w, w.names["dorsania"])[-1]["text"].lower())


class TheLeagueAnswersTradeTalks(unittest.TestCase):
    def test_trade_talks_to_the_league_move_its_trust(self):
        w = world()
        trust = w.dip.league_trust
        answer(w, motion("Open trade talks with the Maritime League for a standing supply arrangement.",
                         "trade_talks", "trade_talks", "MARITIME_LEAGUE"))
        said = messages_from(w, w.names["league"])
        self.assertTrue(said, "the League answers the talks instead of dropping them silently")
        self.assertAlmostEqual(w.dip.league_trust, trust + director.LEAGUE_TALKS_TRUST, places=6)

    def test_trade_talks_to_the_league_are_declined_below_its_floor(self):
        w = world()
        w.adjust_league_trust(director.LEAGUE_TALKS_FLOOR - w.dip.league_trust - .01)
        trust = w.dip.league_trust
        answer(w, motion("Open trade talks with the Maritime League.", "trade_talks", "trade_talks",
                         "MARITIME_LEAGUE"))
        self.assertEqual(w.dip.league_trust, trust)
        self.assertIn("declin", messages_from(w, w.names["league"])[-1]["text"].lower())


class EveryAcceptedPairLeavesAnAnswer(unittest.TestCase):
    """No pair the table accepts may vanish after the vote: each of the six gets a message from its target."""

    def test_each_of_the_six_pairs_is_answered_by_the_power_it_names(self):
        for act, actor in SIX_PAIRS:
            with self.subTest(act=act, actor=actor):
                w = world()
                if act == "trade_talks" and actor == ma.VELERIA:
                    w.dip.coal_embargo = .10
                if act == "trade_deal" and actor == ma.DORSANIA:
                    w.dip.grain_embargo = .20
                answer(w, motion("", act, act, actor))
                sender = w.names[ma.party_of(actor)]
                self.assertTrue(messages_from(w, sender), f"{act} to {actor} was answered by nobody")


class DemandAndWarningAreCommunicationKinds(unittest.TestCase):
    def test_both_kinds_are_registered(self):
        self.assertIn("demand", standing.COMM_KINDS)
        self.assertIn("warning", standing.COMM_KINDS)

    def test_the_schema_accepts_both(self):
        w = world()
        enum = actions._comm_schema(w, "A", ["B"])["items"]["properties"]["kind"]["enum"]
        self.assertIn("demand", enum)
        self.assertIn("warning", enum)

    def test_the_reader_keeps_both(self):
        w = world()
        out, problems = actions.normalize_session_v2(w, "A", {"communications": [
            {"kind": "demand", "target": "veleria", "about": "coal deliveries"},
            {"kind": "warning", "target": "public", "about": "the border"}]}, 3)
        self.assertEqual([c["kind"] for c in out["communications"]], ["demand", "warning"])
        self.assertEqual(problems, [])

    def test_the_prompt_describes_both_neutrally(self):
        w = world()
        text = prompts.opening_instructions_v2(w, "A", 3, ["A", "B", "C", "D", "E"], 2)
        self.assertIn("demand (a public demand addressed to a power, a colleague or the public)", text)
        self.assertIn("warning (a public warning)", text)

    def test_a_demand_on_a_power_hardens_it(self):
        w = world()
        before = w.foreign["actors"]["veleria"]["relations"]["karamaniya"]["hostility"]
        applied = standing.apply_communications(
            w, "A", [{"kind": "demand", "target": "veleria", "about": "coal deliveries"}], {})
        self.assertEqual([c["kind"] for c in applied], ["demand"])
        self.assertEqual(w.foreign["actors"]["veleria"]["relations"]["karamaniya"]["hostility"],
                         round(before + standing.COMM_DEMAND_HOSTILITY, 3))

    def test_a_demand_on_the_union_is_read_by_both_of_its_governments(self):
        w = world()
        before = {aid: w.foreign["actors"][aid]["relations"]["karamaniya"]["hostility"]
                  for aid in ("veleria", "dorsania")}
        standing.apply_communications(w, "A", [{"kind": "demand", "target": "union", "about": "status"}], {})
        for aid in ("veleria", "dorsania"):
            self.assertEqual(w.foreign["actors"][aid]["relations"]["karamaniya"]["hostility"],
                             round(before[aid] + standing.COMM_DEMAND_HOSTILITY / 2, 3))

    def test_a_demand_on_the_league_costs_a_little_trust(self):
        w = world()
        trust = w.dip.league_trust
        standing.apply_communications(w, "A", [{"kind": "demand", "target": "league", "about": "shipping"}], {})
        self.assertAlmostEqual(w.dip.league_trust, trust + standing.COMM_DEMAND_LEAGUE_TRUST, places=6)

    def test_a_warning_hardens_its_target_and_reads_as_firmness_at_home(self):
        w = world()
        s = standing.ensure(w, "A")
        strong = s["reputation"]["strong"]
        before = w.foreign["actors"]["dorsania"]["relations"]["karamaniya"]["hostility"]
        standing.apply_communications(w, "A", [{"kind": "warning", "target": "dorsania", "about": "the border"}], {})
        self.assertEqual(w.foreign["actors"]["dorsania"]["relations"]["karamaniya"]["hostility"],
                         round(before + standing.COMM_WARNING_HOSTILITY, 3))
        self.assertGreater(s["reputation"]["strong"], strong, "a public warning is seen as firmness")

    def test_a_demand_on_a_colleague_has_no_foreign_effect(self):
        w = world()
        before = w.foreign["actors"]["veleria"]["relations"]["karamaniya"]["hostility"]
        standing.apply_communications(w, "A", [{"kind": "demand", "target": "B", "about": "my support"}], {})
        self.assertEqual(w.foreign["actors"]["veleria"]["relations"]["karamaniya"]["hostility"], before)


class TheMotionListNamesTheWidenedTargets(unittest.TestCase):
    def test_the_diplomacy_line_names_who_receives_each_widened_act(self):
        self.assertIn("trade_talks (to the Union, the Maritime League, Dorsania or Veleria)", prompts.RULES)
        self.assertIn("status_talks (talks on Karamaniya's status, committing to nothing) to the Union, Dorsania "
                      "or Veleria", prompts.RULES)
        self.assertIn("trade_deal (to the Maritime League or Dorsania)", prompts.RULES)


if __name__ == "__main__":
    unittest.main()
