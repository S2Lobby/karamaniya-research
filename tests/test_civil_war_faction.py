"""Civil war (Wave C, C3): the faction month.

While a war runs, the rebels get one call a month, made by their leader, with the phase name
``faction`` and the leader's member id; the government's opening, response and decision sessions
skip the rebels but keep their seats, offices and status. The call travels the delegate call path,
so ``backends/replay.py``'s (month, phase, member) key finds it and a run with a war replays from
its own log.

Every refusal the faction reader makes is in words and carries a registered ``FACTION_*`` code.
Offers are validated and handed to C4's own API when the base carries it (``civil_war.running``,
``ceasefire``, ``offer``, ``orders_break_ceasefire``); this module never settles or ends a war.

    python -m unittest tests.test_civil_war_faction
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, civil_war, errors, prompts  # noqa: E402
from karamaniya.backends import CallResult  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.council import Council  # noqa: E402
from karamaniya.runner import _seats  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import World, new_world  # noqa: E402
from tests.test_engine29_immersion import found  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTED = os.path.join(ROOT, "council.scripted.toml")
OFFICES = {"head": "A", "treasury": "B", "interior": "D", "army": "C", "navy": "E"}
GOVERNMENT = ["B", "D", "E"]
REBELS = ["A", "C"]
LEADER = "A"


class RecordingBackend(ScriptedBackend):
    """The engine's stand-in, recording each call, and able to answer the faction phase as a test asks."""

    def __init__(self, cfg: dict, faction_answer=None):
        super().__init__(cfg)
        self.calls = []
        self.faction_answer = faction_answer

    def call(self, system: str, user: str, schema: dict, context: dict) -> CallResult:
        res = super().call(system, user, schema, context)
        if context.get("phase") == "faction" and self.faction_answer is not None:
            data = self.faction_answer
            res = CallResult(data=data, raw=json.dumps(data, ensure_ascii=False),
                             served_model=res.served_model)
        world = context.get("world")
        self.calls.append({"month": world.month if world is not None else None,
                           "phase": context.get("phase"), "member": context.get("member"),
                           "prompt": user})
        return res


def scripted_council(tmp: str, months: int = 3, seed: int = 1, option: str = "on",
                     war: bool = True, faction_answer=None, architecture: int = 2):
    """A scripted council with its government formed, beside a civil war when asked for."""
    cfg = load_config(SCRIPTED)
    cfg = {**cfg, "run": {**cfg["run"], "tokens": {}, "foreign_cabinets": False, "seed": seed}}
    cfg = normalize_config({"run": cfg["run"], "seat": cfg["seats"]})
    mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
    w = new_world(seed, months, member_ids=list(mapping), civil_war_option=option,
                  founding_scenario=cfg["run"].get("founding_scenario", "random"),
                  founding_severity=cfg["run"].get("founding_severity", "default"),
                  agent_architecture_version=architecture)
    seats = _seats(cfg, mapping)
    for seat in seats.values():
        seat.backend = RecordingBackend(seat.cfg, faction_answer=faction_answer)
    council = Council(w, seats, cfg["run"], RunStore(os.path.join(tmp, "r")))
    council.store.save_config(cfg)
    council.survey()
    council.diagnose_founding()
    council.form_government()
    if war:
        start_war(w)
    return council, w


def start_war(w: World, plotters=("C",), joiners=("A",)) -> dict:
    """A war the C1 state builder can make from any world: the army plotter, the head joining."""
    return civil_war.start(w, "failed_coup", plotters=list(plotters),
                           stances={mid: "join" for mid in joiners})


def jsonl(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def calls(council: Council, month: int | None = None, phase: str | None = None) -> list:
    out = [call for seat in council.seats.values() for call in seat.backend.calls]
    return [call for call in out
            if (month is None or call["month"] == month) and (phase is None or call["phase"] == phase)]


def faction_calls(council: Council) -> list:
    return calls(council, phase="faction")


def by_member(council: Council, month: int, phase: str) -> list:
    return sorted(call["member"] for call in calls(council, month=month, phase=phase))


class TheFactionCall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cw-faction-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_one_faction_call_a_month_by_the_leader(self):
        council, w = scripted_council(self.tmp)
        council.run_month()
        council.run_month()
        made = faction_calls(council)
        self.assertEqual([(c["month"], c["member"]) for c in made], [(0, LEADER), (1, LEADER)])

    def test_no_faction_call_when_the_arm_is_off(self):
        council, _ = scripted_council(self.tmp, option="off", war=False)
        council.run_month()
        self.assertEqual(faction_calls(council), [])
        self.assertEqual(by_member(council, 0, "session"), list("ABCDE"))

    def test_no_faction_call_before_a_war_starts(self):
        council, _ = scripted_council(self.tmp, option="on", war=False)
        council.run_month()
        self.assertEqual(faction_calls(council), [])
        self.assertEqual(by_member(council, 0, "decision"), list("ABCDE"))

    def test_no_faction_call_once_the_war_has_an_outcome(self):
        council, w = scripted_council(self.tmp)
        w.civil_war["outcome"] = {"type": "partitioned", "month": 0}
        council.run_month()
        self.assertEqual(faction_calls(council), [])
        # A settled or won war is over: the rebels are no longer excluded from the sessions.
        self.assertEqual(by_member(council, 0, "session"), list("ABCDE"))

    def test_the_stored_leader_is_called(self):
        council, w = scripted_council(self.tmp)
        self.assertEqual(w.civil_war["factions"]["rebels"]["leader"], LEADER)
        council.run_month()
        self.assertEqual([c["member"] for c in faction_calls(council)], [LEADER])

    def test_a_missing_leader_falls_back_to_the_highest_office_then_power(self):
        council, w = scripted_council(self.tmp)
        w.civil_war["factions"]["rebels"]["leader"] = None
        council.run_month()
        self.assertEqual([c["member"] for c in faction_calls(council)], ["A"])

    def test_an_inactive_leader_falls_back_to_the_next_rebel(self):
        council, w = scripted_council(self.tmp)
        w.member("A").status = "removed"
        w.member("A").removed_how = "coup"
        council.run_month()
        self.assertEqual([c["member"] for c in faction_calls(council)], ["C"])

    def test_the_replay_key_is_month_phase_and_leader(self):
        council, _ = scripted_council(self.tmp)
        council.run_month()
        log = jsonl(os.path.join(council.store.path, "log.jsonl"))
        self.assertTrue(any(row.get("type") == "call" and row.get("month") == 0
                            and row.get("phase") == "faction" and row.get("member") == LEADER
                            for row in log))


class TheGovernmentSessionsExcludeRebels(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cw-faction-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rebels_are_not_called_in_the_opening_revision_or_decision(self):
        council, _ = scripted_council(self.tmp)
        council.run_month()
        for phase in ("session", "revision", "decision"):
            with self.subTest(phase=phase):
                members = by_member(council, 0, phase)
                self.assertEqual(members, GOVERNMENT)
                self.assertNotIn("A", members)
                self.assertNotIn("C", members)

    def test_every_government_member_is_called_once_a_phase(self):
        council, _ = scripted_council(self.tmp)
        council.run_month()
        for phase in ("session", "revision", "decision"):
            with self.subTest(phase=phase):
                self.assertEqual(by_member(council, 0, phase), GOVERNMENT)

    def test_rebels_keep_their_seats_offices_and_status(self):
        council, w = scripted_council(self.tmp)
        council.run_month()
        for mid in REBELS:
            self.assertEqual(w.member(mid).status, "active")
            self.assertEqual(w.member(mid).removed_how, "")
        self.assertEqual(w.const.offices, OFFICES)
        self.assertEqual(sorted(m.id for m in w.active_members()), list("ABCDE"))

    def test_the_record_names_the_government_only(self):
        council, _ = scripted_council(self.tmp)
        record = council.run_month()
        self.assertEqual(sorted(record["order"]), GOVERNMENT)
        self.assertEqual(sorted(s["member"] for s in record["statements"]), GOVERNMENT)
        self.assertEqual(sorted(record["decisions"]), GOVERNMENT)

    def test_without_a_war_everyone_is_called(self):
        council, _ = scripted_council(self.tmp, option="off", war=False)
        council.run_month()
        for phase in ("session", "revision", "decision"):
            self.assertEqual(by_member(council, 0, phase), list("ABCDE"))

    def test_the_v1_month_filters_the_same_way(self):
        council, w = scripted_council(self.tmp, architecture=1)
        record = council.run_month()
        self.assertEqual(by_member(council, 0, "session"), GOVERNMENT)
        self.assertEqual(by_member(council, 0, "decision"), GOVERNMENT)
        self.assertEqual([c["member"] for c in faction_calls(council)], [LEADER])
        self.assertEqual(sorted(record["decisions"]), GOVERNMENT)
        for mid in REBELS:
            self.assertEqual(w.member(mid).status, "active")


class TheAnswerReader(unittest.TestCase):
    def setUp(self):
        self.w = new_world(1, 36, civil_war_option="on")
        self.w.const.offices.update(OFFICES)
        self.state = start_war(self.w)
        self.fronts = actions.faction_fronts(self.w, self.state)
        self.others = ["B", "C", "D", "E"]

    def read(self, data):
        return actions.normalize_faction(self.w, "A", data, self.fronts, self.others)

    def codes(self, out):
        return [entry["code"] for entry in out["refused"]]

    def test_the_fronts_are_the_two_borders_the_capital_and_each_contested_region(self):
        self.assertEqual(self.fronts[:3], ["north", "east", "capital"])
        self.state["contested"] = ["kessel", {"region": "dorran"}]
        self.assertEqual(actions.faction_fronts(self.w, self.state), ["north", "east", "capital", "dorran", "kessel"])

    def test_a_complete_answer_is_read(self):
        out, problems = self.read({
            "fronts": {"north": "attack", "east": "defend", "capital": "withdraw"},
            "offer": {"ceasefire": True},
            "statement": "We hold the line.",
            "messages": [{"to": "B", "text": "The offer stands."}],
            "appeal": "league"})
        self.assertEqual(problems, [])
        self.assertEqual(out["fronts"], {"north": "attack", "east": "defend", "capital": "withdraw"})
        self.assertEqual(out["offer"], {"ceasefire": True})
        self.assertEqual(out["statement"], "We hold the line.")
        self.assertEqual(out["messages"], [{"from": "A", "to": "B", "text": "The offer stands."}])
        self.assertEqual(out["appeal"], "league")
        self.assertEqual(out["refused"], [])

    def test_canonical_settlement_terms_are_read(self):
        out, problems = self.read({
            "fronts": {"north": "defend"},
            "offer": {"terms": [{"amnesty": True},
                                {"power_sharing": {"treasury": "rebels"}},
                                {"regional_autonomy": "kessel"},
                                {"forces": "disarm"},
                                {"election_date": 36}]},
            "statement": "",
            "messages": [],
            "appeal": None})
        self.assertEqual(problems, [])
        self.assertEqual(out["offer"]["terms"], [
            {"amnesty": True}, {"power_sharing": {"treasury": "rebels"}},
            {"regional_autonomy": "kessel"}, {"forces": "disarm"}, {"election_date": 36}])

    def test_null_offer_and_appeal_are_no_offer(self):
        out, problems = self.read({"fronts": {"north": "defend"}, "offer": None,
                                   "statement": "", "messages": [], "appeal": None})
        self.assertEqual(problems, [])
        self.assertIsNone(out["offer"])
        self.assertIsNone(out["appeal"])

    def test_an_unknown_front_is_refused_in_words(self):
        out, problems = self.read({"fronts": {"south": "attack"}, "offer": None,
                                   "statement": "", "messages": [], "appeal": None})
        self.assertEqual(self.codes(out), ["FACTION_UNKNOWN_FRONT"])
        self.assertIn("unknown front 'south'", problems[0])
        self.assertTrue(errors.is_registered("FACTION_UNKNOWN_FRONT"))
        self.assertEqual(out["fronts"], {})

    def test_a_bad_stance_is_refused_in_words(self):
        out, problems = self.read({"fronts": {"north": "charge"}, "offer": None,
                                   "statement": "", "messages": [], "appeal": None})
        self.assertEqual(self.codes(out), ["FACTION_BAD_STANCE"])
        self.assertIn("charge", problems[0])
        self.assertTrue(errors.is_registered("FACTION_BAD_STANCE"))

    def test_an_unknown_term_is_refused_in_words(self):
        out, problems = self.read({"fronts": {"north": "defend"},
                                   "offer": {"terms": [{"amnesty": True}, {"reparations": 10}]},
                                   "statement": "", "messages": [], "appeal": None})
        self.assertEqual(self.codes(out), ["FACTION_UNKNOWN_TERM"])
        self.assertIn("reparations", problems[0])
        self.assertTrue(errors.is_registered("FACTION_UNKNOWN_TERM"))
        # The valid term is kept; C4 validates the offer itself.
        self.assertEqual(out["offer"], {"terms": [{"amnesty": True}]})

    def test_an_election_before_month_36_is_refused_in_words(self):
        out, problems = self.read({"fronts": {"north": "defend"},
                                   "offer": {"terms": [{"election_date": 20}]},
                                   "statement": "", "messages": [], "appeal": None})
        self.assertIn("FACTION_BAD_OFFER", self.codes(out))
        self.assertIn("Month 36", problems[0])
        self.assertIsNone(out["offer"])

    def test_a_bad_term_value_is_refused_in_words(self):
        for terms in ([{"forces": "merge"}], [{"regional_autonomy": "arven"}],
                      [{"power_sharing": {"head": "nobody"}}], [{"amnesty": False}]):
            with self.subTest(terms=terms):
                out, problems = self.read({"fronts": {"north": "defend"},
                                           "offer": {"terms": terms},
                                           "statement": "", "messages": [], "appeal": None})
                self.assertTrue(problems)
                self.assertTrue(set(self.codes(out)) <= set(errors.TAXONOMY))
                self.assertIsNone(out["offer"])

    def test_a_duplicate_term_is_refused(self):
        out, problems = self.read({"fronts": {"north": "defend"},
                                   "offer": {"terms": [{"amnesty": True}, {"amnesty": True}]},
                                   "statement": "", "messages": [], "appeal": None})
        self.assertIn("FACTION_BAD_OFFER", self.codes(out))
        self.assertIn("twice", problems[0])

    def test_an_over_long_statement_is_refused_and_kept_cut(self):
        out, problems = self.read({"fronts": {"north": "defend"}, "offer": None,
                                   "statement": "word " * (actions.FACTION_STATEMENT_WORDS + 5),
                                   "messages": [], "appeal": None})
        self.assertEqual(self.codes(out), ["FACTION_STATEMENT_TOO_LONG"])
        self.assertIn(str(actions.FACTION_STATEMENT_WORDS), problems[0])
        self.assertTrue(out["statement"].endswith(actions.CUT_MARK))
        self.assertTrue(errors.is_registered("FACTION_STATEMENT_TOO_LONG"))

    def test_an_unknown_field_is_refused(self):
        out, problems = self.read({"fronts": {"north": "defend"}, "offer": None, "statement": "",
                                   "messages": [], "appeal": None, "surrender": True})
        self.assertEqual(self.codes(out), ["FACTION_UNKNOWN_FIELD"])
        self.assertIn("surrender", problems[0])
        self.assertTrue(errors.is_registered("FACTION_UNKNOWN_FIELD"))

    def test_a_bad_message_is_refused_and_others_are_kept(self):
        out, problems = self.read({"fronts": {"north": "defend"}, "offer": None, "statement": "",
                                   "messages": [{"to": "A", "text": "myself"},
                                                {"to": "Z", "text": "nobody"},
                                                {"to": "B", "text": ""},
                                                {"to": "C", "text": "kept"}],
                                   "appeal": "union"})
        self.assertEqual(out["messages"], [{"from": "A", "to": "C", "text": "kept"}])
        self.assertEqual(self.codes(out), ["FACTION_BAD_MESSAGE"] * 3)
        self.assertTrue(errors.is_registered("FACTION_BAD_MESSAGE"))

    def test_a_bad_appeal_is_refused(self):
        out, problems = self.read({"fronts": {"north": "defend"}, "offer": None, "statement": "",
                                   "messages": [], "appeal": "mars"})
        self.assertEqual(self.codes(out), ["FACTION_BAD_APPEAL"])
        self.assertTrue(errors.is_registered("FACTION_BAD_APPEAL"))

    def test_a_ceasefire_and_terms_together_are_refused(self):
        out, problems = self.read({"fronts": {"north": "defend"},
                                   "offer": {"ceasefire": True, "terms": [{"amnesty": True}]},
                                   "statement": "", "messages": [], "appeal": None})
        self.assertIn("FACTION_BAD_OFFER", self.codes(out))
        self.assertIsNone(out["offer"])

    def test_the_reader_refuses_rather_than_raises_on_a_malformed_answer(self):
        out, problems = actions.read_answer(actions.normalize_faction, self.w, "A", ["not an object"],
                                            self.fronts, self.others)
        self.assertEqual(problems, ["no answer"])
        self.assertEqual(out["fronts"], {})


class TheFactionAnswerReachesTheState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cw-faction-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_fronts_are_written_to_the_rebels_orders_verbatim(self):
        answer = {"fronts": {"north": "attack", "east": "withdraw", "capital": "defend"},
                  "offer": None, "statement": "Orders.", "messages": [], "appeal": None}
        council, w = scripted_council(self.tmp, faction_answer=answer)
        council.run_month()
        self.assertEqual(w.civil_war["orders"]["rebels"],
                         {"north": "attack", "east": "withdraw", "capital": "defend"})
        self.assertIsNone(w.civil_war["orders"].get("government"))

    def test_orders_the_answer_omits_are_not_invented(self):
        answer = {"fronts": {"north": "defend"}, "offer": None, "statement": "",
                  "messages": [], "appeal": None}
        council, w = scripted_council(self.tmp, faction_answer=answer)
        council.run_month()
        self.assertEqual(w.civil_war["orders"]["rebels"], {"north": "defend"})

    def test_an_attack_order_breaks_a_ceasefire_through_c4(self):
        answer = {"fronts": {"north": "attack"}, "offer": None, "statement": "",
                  "messages": [], "appeal": None}
        council, w = scripted_council(self.tmp, faction_answer=answer)
        seen = {}

        def break_it(world):
            seen["orders"] = json.loads(json.dumps(world.civil_war["orders"]))
            return {"ok": True, "kind": "ceasefire", "action": "broken",
                    "breach": {"side": "rebels", "month": world.month, "reason": "attack"}}

        with mock.patch.object(civil_war, "orders_break_ceasefire", create=True, side_effect=break_it):
            council.run_month()
        self.assertEqual(seen["orders"]["rebels"], {"north": "attack"})
        self.assertEqual(w.history[-1]["civil_war"]["ceasefire_breach"]["action"], "broken")
        self.assertEqual(w.history[-1]["civil_war"]["ceasefire_breach"]["breach"]["side"], "rebels")

    def test_a_ceasefire_offer_goes_to_c4(self):
        answer = {"fronts": {"north": "defend"}, "offer": {"ceasefire": True},
                  "statement": "", "messages": [], "appeal": None}
        council, w = scripted_council(self.tmp, faction_answer=answer)
        result = {"ok": True, "kind": "ceasefire", "action": "offered", "side": "rebels",
                  "active": False, "problems": []}
        with mock.patch.object(civil_war, "ceasefire", create=True, return_value=result) as called:
            council.run_month()
        called.assert_called_once_with(w, "rebels")
        self.assertEqual(w.history[-1]["civil_war"]["ceasefire"], result)

    def test_settlement_terms_go_to_c4(self):
        answer = {"fronts": {"north": "defend"},
                  "offer": {"terms": [{"amnesty": True}, {"election_date": 36}]},
                  "statement": "", "messages": [], "appeal": None}
        council, w = scripted_council(self.tmp, faction_answer=answer)
        result = {"ok": True, "kind": "settlement", "action": "offered", "side": "rebels",
                  "terms": {"amnesty": True, "election_date": 36}, "problems": []}
        with mock.patch.object(civil_war, "offer", create=True, return_value=result) as called:
            council.run_month()
        called.assert_called_once_with(w, "rebels", [{"amnesty": True}, {"election_date": 36}])
        self.assertEqual(w.history[-1]["civil_war"]["offer"], result)

    def test_c4_running_gates_the_phase(self):
        council, w = scripted_council(self.tmp)
        with mock.patch.object(civil_war, "running", create=True, return_value=False):
            council.run_month()
        self.assertEqual(faction_calls(council), [])
        with mock.patch.object(civil_war, "running", create=True, return_value=True):
            council.run_month()
        self.assertEqual(len(faction_calls(council)), 1)

    def test_the_answer_is_recorded_on_the_month(self):
        answer = {"fronts": {"north": "defend", "east": "attack", "capital": "defend"},
                  "offer": None, "statement": "We stand.", "messages": [], "appeal": "union"}
        council, w = scripted_council(self.tmp, faction_answer=answer)
        council.run_month()
        record = w.history[-1]["civil_war"]
        self.assertEqual(record["leader"], LEADER)
        self.assertEqual(record["spoke"], [LEADER])
        self.assertEqual(record["answer"]["statement"], "We stand.")
        self.assertEqual(record["answer"]["appeal"], "union")
        self.assertEqual(record["orders"], answer["fronts"])
        self.assertEqual(record["refused"], [])

    def test_a_refusal_is_recorded_with_its_registered_code(self):
        answer = {"fronts": {"south": "attack"}, "offer": None, "statement": "",
                  "messages": [], "appeal": None}
        council, w = scripted_council(self.tmp, faction_answer=answer)
        council.run_month()
        record = w.history[-1]["civil_war"]
        self.assertEqual([entry["code"] for entry in record["refused"]], ["FACTION_UNKNOWN_FRONT"])
        self.assertTrue(any(e.get("code") == "FACTION_UNKNOWN_FRONT" for e in w.audit_errors))
        self.assertEqual(w.audit_errors[-1]["code"], "FACTION_UNKNOWN_FRONT")
        self.assertIn("south", w.audit_errors[-1]["message"])

    def test_messages_are_logged_and_delivered_next_month(self):
        answer = {"fronts": {"north": "defend"}, "offer": None, "statement": "",
                  "messages": [{"to": "B", "text": "Think again."}], "appeal": None}
        council, _ = scripted_council(self.tmp, faction_answer=answer)
        council.run_month()
        self.assertEqual([(dm["from"], dm["to"], dm["text"]) for dm in council.pending_dms],
                         [("A", "B", "Think again.")])
        log = jsonl(os.path.join(council.store.path, "log.jsonl"))
        self.assertTrue(any(row.get("type") == "dm" and row.get("phase") == "faction"
                            and row.get("from") == "A" and row.get("to") == "B" for row in log))

    def test_no_war_leaves_the_history_key_out(self):
        council, w = scripted_council(self.tmp, option="off", war=False)
        council.run_month()
        self.assertNotIn("civil_war", w.history[-1])


class OffNeverReadsAPresentState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cw-faction-off-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_council_month_is_identical_with_a_loaded_state(self):
        plain, _ = scripted_council(self.tmp, option="off", war=False)
        loaded, w = scripted_council(self.tmp, option="off", war=False)
        donor, donor_w = scripted_council(self.tmp, option="on")
        w.civil_war = json.loads(json.dumps(donor_w.civil_war))
        before = json.loads(json.dumps(w.civil_war))
        plain_record = plain.run_month()
        loaded_record = loaded.run_month()
        self.assertEqual(faction_calls(loaded), [])
        self.assertEqual([(c["phase"], c["member"]) for c in calls(plain)],
                         [(c["phase"], c["member"]) for c in calls(loaded)])
        self.assertEqual(json.loads(json.dumps(loaded_record)), json.loads(json.dumps(plain_record)))
        self.assertEqual(w.civil_war, before)

    def test_an_old_checkpoint_without_a_war_loads(self):
        w = new_world(3, 36)
        data = w.to_dict()
        self.assertNotIn("civil_war", data)
        self.assertNotIn("civil_war_option", data)
        restored = World.from_dict(data)
        self.assertIsNone(restored.civil_war)
        self.assertEqual(restored.civil_war_option, "off")

    def test_a_war_and_its_faction_record_round_trip(self):
        council, w = scripted_council(self.tmp)
        answer = {"fronts": {"north": "defend"}, "offer": {"ceasefire": True},
                  "statement": "Hold.", "messages": [], "appeal": None}
        council.seats["A"].backend.faction_answer = answer
        council.run_month()
        data = w.to_dict()
        self.assertEqual(data["civil_war"], json.loads(json.dumps(w.civil_war)))
        self.assertIn("last_faction", data["civil_war"])
        restored = World.from_dict(data)
        self.assertEqual(restored.civil_war["orders"]["rebels"], {"north": "defend"})
        self.assertEqual(restored.civil_war["last_faction"]["leader"], LEADER)


class TheScriptedFactionAnswer(unittest.TestCase):
    def test_the_stand_in_defends_every_front_and_offers_nothing(self):
        w = new_world(1, 36, civil_war_option="on")
        w.const.offices.update(OFFICES)
        start_war(w)
        backend = ScriptedBackend({"provider": "scripted", "persona": "hawk"})
        res = backend.call("", "", {}, {"phase": "faction", "world": w, "member": "A",
                                        "fronts": ["north", "east", "capital"]})
        self.assertEqual(res.data, {"fronts": {"north": "defend", "east": "defend", "capital": "defend"},
                                    "offer": None, "statement": "", "messages": [], "appeal": None})
        again = backend.call("", "", {}, {"phase": "faction", "world": w, "member": "A",
                                          "fronts": ["north", "east", "capital"]})
        self.assertEqual(res.data, again.data)

    def test_the_existing_phases_are_untouched(self):
        w = new_world(1, 36)
        w.const.offices.update(OFFICES)
        backend = ScriptedBackend({"provider": "scripted", "persona": "democrat"})
        survey = backend.call("", "", prompts.survey_schema(),
                              {"phase": "survey", "world": w, "member": "A"})
        self.assertEqual(survey.data["election"]["choice"], "hold_on_schedule")
        self.assertNotIn("fronts", survey.data)


class ThePrompt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cw-faction-prompt-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_faction_prompt_gives_nothing_away(self):
        council, _ = scripted_council(self.tmp)
        council.run_month()
        prompt = next(c["prompt"] for c in faction_calls(council))
        self.assertEqual(found(prompt), {})

    def test_the_prompt_states_the_closed_list_and_the_election_rule(self):
        council, _ = scripted_council(self.tmp)
        council.run_month()
        prompt = next(c["prompt"] for c in faction_calls(council))
        for phrase in ("amnesty", "power sharing", "regional autonomy", "integrate", "disarm",
                       "Month 36", "ceasefire", "attack", "defend", "withdraw"):
            self.assertIn(phrase, prompt)


class TheRunOption(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cw-faction-option-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _config(self, arm: str | None) -> dict:
        cfg = load_config(SCRIPTED)
        run = {**cfg["run"], "tokens": {}, "foreign_cabinets": False}
        if arm is not None:
            run["civil_war"] = arm
        return {"run": run, "seats": cfg["seats"]}

    def test_a_bad_arm_is_refused_before_the_run_folder_is_written(self):
        from karamaniya import runner
        with self.assertRaises(ValueError):
            runner.new_run(self._config("maybe"), runs_dir=self.tmp, name="bad", months=1, seed=1,
                           quiet=True, check=False)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "bad")))

    def test_the_manifest_records_the_arm_only_when_it_is_on(self):
        from karamaniya import manifest
        cfg = self._config("on")
        on = new_world(1, 1, civil_war_option="on")
        self.assertEqual(manifest.build(on, cfg).get("civil_war"), "on")
        off = new_world(1, 1)
        self.assertNotIn("civil_war", manifest.build(off, cfg))


class TheRunReplays(unittest.TestCase):
    """A scripted run recorded with a war replays from its own log, faction calls and all."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cw-faction-replay-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _config(self, civil_war_option: str) -> dict:
        cfg = load_config(SCRIPTED)
        run = {**cfg["run"], "tokens": {}, "foreign_cabinets": False, "survey": True}
        if civil_war_option == "on":
            run["civil_war"] = "on"
        return {"run": run, "seats": cfg["seats"]}

    def _replay(self, name: str, cfg: dict, war_at: int | None, months: int = 6):
        from karamaniya import runner
        from tools import replay_run
        original = Council._run_month_v2

        def patched(council):
            if war_at is not None and council.w.month == war_at and civil_war.state(council.w) is None:
                start_war(council.w)
            return original(council)

        with mock.patch.object(Council, "_run_month_v2", patched):
            runner.new_run(cfg, runs_dir=self.tmp, name=name, months=months, seed=1, quiet=True,
                           check=False)
            return replay_run.replay(os.path.join(self.tmp, name))

    def test_a_six_month_off_run_replays_identically(self):
        from karamaniya import runner
        from tools import replay_run
        runner.new_run(self._config("off"), runs_dir=self.tmp, name="off", months=6, seed=1,
                       quiet=True, check=False)
        verdict = replay_run.replay(os.path.join(self.tmp, "off"))
        self.assertTrue(verdict["identical"], verdict.get("message"))

    def test_a_war_run_replays_identically_and_logs_the_faction_call(self):
        verdict = self._replay("war", self._config("on"), war_at=1)
        self.assertTrue(verdict["identical"], verdict.get("message"))
        with open(os.path.join(self.tmp, "war", "checkpoint.json"), encoding="utf-8") as f:
            leader = json.load(f)["world"]["civil_war"]["factions"]["rebels"]["leader"]
        log = jsonl(os.path.join(self.tmp, "war", "log.jsonl"))
        self.assertTrue(any(row.get("type") == "call" and row.get("phase") == "faction"
                            and row.get("month") == 1 and row.get("member") == leader for row in log))


if __name__ == "__main__":
    unittest.main()
