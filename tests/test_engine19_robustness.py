"""Engine 19, robustness slice (audit CO2 and CO14).

CO2: no malformed answer ends a run. A delegate's answer, a ballot repair and a foreign cabinet's answer may
carry any JSON. The normalisers read it without raising; a field of the wrong type is recorded as a problem for
that delegate and read as empty. An exception that still escapes a normaliser is recorded as a problem and the
answer is treated as empty for its phase, so the month completes.

CO14: a third motion beyond the two-motion cap is refused on the record, with the cap as its reason, and the
delegate sees it in the next month's briefing.

Well-formed answers are checked against a golden record taken from the engine before these changes: a
well-formed answer must come out exactly as it did.
"""
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import actions, errors, foreign, standing  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.council import Council, _rejected_last_month  # noqa: E402
from karamaniya.runner import _seats  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

SCRIPTED = os.path.join(ROOT, "council.scripted.toml")

# Junk a connector that does not enforce the schema can send: scalars where a list belongs, objects where a
# list belongs, lists where an identifier or a text belongs, and non-finite numbers.
JUNK = {"None": None, "empty str": "", "str": "x", "zero": 0, "neg": -1, "float": 3.5, "huge float": 1e300,
        "nan": float("nan"), "empty list": [], "list of None": [None], "list mixed": [1, "a"], "empty dict": {},
        "dict": {"a": 1}, "bool": True, "list of dict with None": [{"motion_id": None}],
        "dict keyed by id": {"M1": None}, "list of dict None fields": [{"to": None, "text": None}],
        "list of lists": [["M1"]], "dict of dict": {"M1": {"x": 1}}, "list of dict with list id": [{"motion_id": ["M1"]}]}

# The answers of the audit's proof scripts, as the normalisers read them.
POSITION = {"main_problem": "a", "preferred_policy": "b", "unacceptable_outcome": "c", "would_support": "d",
            "would_oppose": "e"}
AUDIT_SESSION = {"private_position": POSITION, "statement": "A statement.", "motions": [], "promises": [],
                 "private_messages": [], "principles": "", "communications": [], "information_requests": [],
                 "share_reports": [], "agenda_priorities": [], "strategy": {}}
AUDIT_REVISION = {"response": "A response.", "stances": {}, "demands": [], "withdraw": [], "amend": [],
                  "communications": [], "share_reports": [], "private_messages": []}
AUDIT_DECISION = {"votes": {}, "vote_reasons": {}, "vote_conditions": [], "orders": {}, "coup": None,
                  "coup_stance": "resist", "resign": False, "private_messages": [], "notes": "",
                  "decision_factors": [], "operations": {}, "belief_updates": [], "forecasts": [],
                  "election_response": ""}

SESSION = {
    "private_position": {"main_problem": "Bread prices.", "preferred_policy": "Lower the bread tax.",
                         "unacceptable_outcome": "Famine.", "would_support": "Imports.",
                         "would_oppose": "Price caps."},
    "statement": "We must act on food now.",
    "motions": [
        {"type": "set_policy", "subject": "welfare", "value": "0.02", "text": "Raise welfare support.",
         "force_agenda": True},
        {"type": "set_policy", "subject": "military", "value": "0.05", "text": "Raise the military budget.",
         "force_agenda": False},
    ],
    "promises": [{"to": "public", "text": "Bread will not rise.", "condition": "if the harvest holds"}],
    "communications": [{"kind": "endorse", "target": "public", "about": "the food plan"}],
    "information_requests": [{"topic": "food", "motion_id": ""}, {"topic": "reserves", "motion_id": "M1"}],
    "share_reports": [],
    "private_messages": [{"to": "C", "text": "Let us meet.", "kind": "request"}],
    "strategy": {"goal": "food", "by_month": 4},
    "agenda_priorities": ["food", "fiscal"],
    "principles": "",
}
REVISION = {
    "response": "I will support the welfare motion if the demand is met.",
    "stances": {"M1": "support", "M2": "oppose", "M9": "support"},
    "demands": [{"motion_id": "M1", "demand": "Index it to bread prices."}, {"motion_id": "M7", "demand": "x"}],
    "withdraw": [{"motion_id": "M1", "reason": "Replaced by a better one.", "replaced_by": "M2"}],
    "amend": [{"motion_id": "M1", "value": "0.03", "text": "Raise welfare support by three points."}],
    "communications": [{"kind": "endorse", "target": "public", "about": "the welfare plan"}],
    "share_reports": [],
    "private_messages": [{"to": "C", "text": "Your vote matters.", "kind": "message"}],
}
DECISION = {
    "votes": {"M1": "yes", "M2": "conditional"},
    "vote_reasons": {"M1": "It feeds the poor.", "M2": "Only if the reserves hold."},
    "vote_conditions": [{"motion_id": "M2", "kind": "metric", "metric": "reserves", "operator": ">=",
                         "value": 1000, "other_motion": "none", "other_outcome": "none", "if_unmet": "abstain"}],
    "orders": {},
    "operations": {},
    "coup": {"action": "remove", "members": ["C", "A"]},
    "coup_stance": "resist",
    "resign": False,
    "election_response": "",
    "belief_updates": [{"proposition": "food_shortage", "direction": "more_likely", "reason": "Prices rose."}],
    "forecasts": [{"question": "bread price", "probability": 0.6}],
    "forecast_panel": {"inflation_up": 0.4, "approval_up": 0.3},
    "private_messages": [{"to": "D", "text": "Stand with me.", "kind": "request"}],
    "notes": "Watch the reserves.",
    "decision_factors": ["food", "reserves"],
}
MOTIONS = [
    {"id": "M1", "proposer": "A", "type": "set_policy", "subject": "welfare", "value": "0.02", "text": "Raise welfare."},
    {"id": "M2", "proposer": "B", "type": "set_policy", "subject": "tax", "value": "0.20", "text": "Raise tax.",
     "cosponsors": ["A"]},
]

# Recorded from the engine before the engine 19 changes (scratch/golden_gen.py): the normalised output and
# the problems of each well-formed answer. Session is read for B (the head), revision and decision for A.
GOLDEN = json.loads(
    '{"decision":[{"belief_updates":[{"direction":"more_likely","proposition":"food_shortage","reason":"Prices rose."}],'
    '"coup":{"action":"remove","members":["C"]},"coup_stance":"resist","decision_factors":["food","reserves"],'
    '"election_response":"","forecast_panel":{"approval_up":0.3,"inflation_up":0.4},'
    '"forecasts":[{"probability":0.6,"question":"bread price"}],"notes":"Watch the reserves.","operations":{},'
    '"orders":{},"private_messages":[{"from":"A","kind":"request","text":"Stand with me.","to":"D"}],"resign":false,'
    '"vote_conditions":{"M2":{"if_unmet":"abstain","kind":"metric","metric":"reserves","operator":">=",'
    '"value":1000000000.0}},"vote_reasons":{"M1":"It feeds the poor.","M2":"Only if the reserves hold."},'
    '"vote_reasons_full":{},"votes":{"M1":"yes","M2":"conditional"}},[]],'
    '"revision":[{"amend":[{"motion_id":"M1","text":"Raise welfare support by three points.","value":"0.03"}],'
    '"communications":[{"about":"the welfare plan","kind":"endorse","target":"public"}],'
    '"demands":[{"demand":"Index it to bread prices.","member":"A","motion_id":"M1"}],'
    '"private_messages":[{"from":"A","kind":"message","text":"Your vote matters.","to":"C"}],'
    '"response":"I will support the welfare motion if the demand is met.","share_reports":[],'
    '"stances":{"M1":"support","M2":"oppose"},'
    '"withdraw":[{"motion_id":"M1","reason":"Replaced by a better one.","replaced_by":"M2"}]},[]],'
    '"session":[{"agenda_priorities":["food","fiscal"],'
    '"communications":[{"about":"the food plan","kind":"endorse","target":"public"}],'
    '"information_requests":[{"motion_id":"","topic":"food"},{"motion_id":"M1","topic":"reserves"}],'
    '"motions":[{"action":{},"force_agenda":true,"subject":"welfare","text":"Raise welfare support.",'
    '"type":"set_policy","value":"0.02"},{"action":{},"force_agenda":false,"subject":"military",'
    '"text":"Raise the military budget.","type":"set_policy","value":"0.05"}],"principles":"",'
    '"private_messages":[{"from":"B","kind":"request","text":"Let us meet.","to":"C"}],'
    '"private_position":{"main_problem":"Bread prices.","preferred_policy":"Lower the bread tax.",'
    '"unacceptable_outcome":"Famine.","would_oppose":"Price caps.","would_support":"Imports."},'
    '"promises":[{"condition":"if the harvest holds","text":"Bread will not rise.","to":"public"}],'
    '"share_reports":[],"statement":"We must act on food now.","strategy":{"by_month":4,"goal":"food"}},[]]}')


def world_with_offices():
    w = new_world(1, 12, member_ids=list("ABCDE"))
    w.const.offices["head"] = "B"
    w.const.offices["army"] = "A"
    return w


def session_answer():
    """A well-formed opening answer, rich enough that every field has something to read."""
    return {
        "private_position": dict(POSITION),
        "statement": "A statement.",
        "motions": [{"type": "diplomacy", "subject": "trade_talks", "value": "", "text": "Open trade talks with the Union.",
                     "force_agenda": False,
                     "conditions": [{"metric": "reserves", "operator": ">=", "value": 1000}],
                     "action": {"action_type": "trade_talks", "target": "SOLVARAN_UNION", "issue": "grain",
                                "terms": ["a grain deal"], "regions": ["north"], "amount": "5m",
                                "funding_plan": [{"source": "reserves", "amount": "5m"}], "scope": "ports",
                                "military_engineers": True, "measures": [{"lever": "tax", "value": "0.2"}],
                                "region": "north", "funding": "reserves", "deal_action": "trade_talks"}}],
        "promises": [{"to": "public", "text": "Bread will not rise.", "condition": "if the harvest holds"}],
        "communications": [{"kind": "endorse", "target": "public", "about": "the food plan"}],
        "information_requests": [{"topic": "food", "motion_id": "M1"}],
        "share_reports": [{"report_id": "R1", "with": "council"}],
        "private_messages": [{"to": "C", "text": "Hi.", "kind": "request"}],
        "strategy": {"goal": "food", "by_month": 4},
        "agenda_priorities": ["food"],
        "principles": "",
    }


def revision_answer():
    return {"response": "A response.",
            "stances": {"M1": "support"},
            "demands": [{"motion_id": "M1", "demand": "Index it."}],
            "withdraw": [{"motion_id": "M1", "reason": "Replaced.", "replaced_by": "M2"}],
            "amend": [{"motion_id": "M1", "value": "0.03", "text": "Raise it.",
                       "measures": [{"lever": "tax", "value": "0.2"}]}],
            "communications": [{"kind": "endorse", "target": "public", "about": "the plan"}],
            "share_reports": [{"report_id": "R1", "with": "council"}],
            "private_messages": [{"to": "C", "text": "Hi.", "kind": "message"}]}


def decision_answer():
    return {"votes": {"M1": "yes", "M2": "conditional"},
            "vote_reasons": {"M1": "It helps.", "M2": "If reserves hold."},
            "vote_conditions": [{"motion_id": "M2", "kind": "metric", "metric": "reserves", "operator": ">=",
                                 "value": 1000, "other_motion": "none", "other_outcome": "none",
                                 "if_unmet": "abstain"}],
            "orders": {},
            "operations": {},
            "coup": {"action": "remove", "members": ["C"]},
            "coup_stance": "resist",
            "resign": False,
            "election_response": "",
            "belief_updates": [{"proposition": "food_shortage", "direction": "more_likely", "reason": "Prices rose."}],
            "forecasts": [{"question": "bread price", "probability": 0.6}],
            "forecast_panel": {"inflation_up": 0.4},
            "private_messages": [{"to": "D", "text": "Stand with me.", "kind": "request"}],
            "notes": "A note.",
            "decision_factors": ["food", "reserves"]}


# Paths into each answer: every field a normaliser reads, and what sits inside the list and object fields.
SESSION_PATHS = [
    ("statement",), ("principles",), ("private_position",), ("private_position", "main_problem"),
    ("motions",), ("motions", 0), ("motions", 0, "type"), ("motions", 0, "subject"), ("motions", 0, "value"),
    ("motions", 0, "text"), ("motions", 0, "force_agenda"), ("motions", 0, "conditions"),
    ("motions", 0, "conditions", 0, "metric"), ("motions", 0, "conditions", 0, "operator"),
    ("motions", 0, "conditions", 0, "value"), ("motions", 0, "action"),
    ("motions", 0, "action", "action_type"), ("motions", 0, "action", "target"), ("motions", 0, "action", "issue"),
    ("motions", 0, "action", "terms"), ("motions", 0, "action", "demands"), ("motions", 0, "action", "regions"),
    ("motions", 0, "action", "region"), ("motions", 0, "action", "amount"), ("motions", 0, "action", "funding"),
    ("motions", 0, "action", "funding_plan"), ("motions", 0, "action", "scope"),
    ("motions", 0, "action", "military_engineers"), ("motions", 0, "action", "measures"),
    ("motions", 0, "action", "deal_action"),
    ("promises",), ("promises", 0), ("promises", 0, "to"), ("promises", 0, "text"), ("promises", 0, "condition"),
    ("communications",), ("communications", 0), ("communications", 0, "kind"), ("communications", 0, "target"),
    ("communications", 0, "about"),
    ("information_requests",), ("information_requests", 0), ("information_requests", 0, "topic"),
    ("information_requests", 0, "motion_id"),
    ("share_reports",), ("share_reports", 0), ("share_reports", 0, "report_id"), ("share_reports", 0, "with"),
    ("private_messages",), ("private_messages", 0), ("private_messages", 0, "to"), ("private_messages", 0, "text"),
    ("private_messages", 0, "kind"),
    ("agenda_priorities",), ("agenda_priorities", 0),
    ("strategy",), ("strategy", "goal"), ("strategy", "by_month"),
]
REVISION_PATHS = [
    ("response",), ("stances",), ("stances", "M1"), ("demands",), ("demands", 0), ("demands", 0, "motion_id"),
    ("demands", 0, "demand"), ("withdraw",), ("withdraw", 0), ("withdraw", 0, "motion_id"),
    ("withdraw", 0, "reason"), ("withdraw", 0, "replaced_by"), ("amend",), ("amend", 0), ("amend", 0, "motion_id"),
    ("amend", 0, "value"), ("amend", 0, "text"), ("amend", 0, "measures"), ("amend", 0, "measures", 0),
    ("amend", 0, "measures", 0, "lever"), ("communications",), ("communications", 0, "kind"),
    ("communications", 0, "target"), ("share_reports",), ("share_reports", 0, "report_id"),
    ("private_messages",), ("private_messages", 0, "to"), ("private_messages", 0, "kind"),
]
DECISION_PATHS = [
    ("votes",), ("votes", "M1"), ("vote_reasons",), ("vote_reasons", "M1"), ("vote_conditions",),
    ("vote_conditions", 0), ("vote_conditions", 0, "motion_id"), ("vote_conditions", 0, "kind"),
    ("vote_conditions", 0, "metric"), ("vote_conditions", 0, "operator"), ("vote_conditions", 0, "value"),
    ("vote_conditions", 0, "other_motion"), ("vote_conditions", 0, "other_outcome"),
    ("vote_conditions", 0, "if_unmet"), ("orders",), ("orders", "army"), ("operations",), ("operations", "army"),
    ("coup",), ("coup", "action"), ("coup", "members"), ("coup", "members", 0), ("coup_stance",), ("resign",),
    ("election_response",), ("belief_updates",), ("belief_updates", 0), ("belief_updates", 0, "direction"),
    ("belief_updates", 0, "proposition"), ("belief_updates", 0, "reason"), ("forecasts",), ("forecasts", 0),
    ("forecast_panel",), ("forecast_panel", "inflation_up"), ("private_messages",), ("private_messages", 0),
    ("private_messages", 0, "to"), ("private_messages", 0, "kind"), ("notes",), ("decision_factors",),
    ("decision_factors", 0),
]


def with_value(answer, path, value):
    data = copy.deepcopy(answer)
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = copy.deepcopy(value)
    return data


SCRIPTED_TOP_LEVEL_CASES = (
    ("session", AUDIT_SESSION, lambda w, data: actions.normalize_session_v2(w, "A", data, 3)),
    ("revision", AUDIT_REVISION, lambda w, data: actions.normalize_revision(w, "A", data, [], 3)),
    ("decision", AUDIT_DECISION, lambda w, data: actions.normalize_decision_v2(w, "A", data, ["M1", "M2"], 3)),
)


class NoWronglyTypedFieldRaises(unittest.TestCase):
    """CO2: no field of the wrong type raises in a normaliser, at any depth."""

    def test_no_top_level_junk_field_raises(self):
        """The audit's 47 (normaliser, field, junk) combinations: none may raise."""
        w = new_world(1, 12, member_ids=list("ABCDE"))
        crashes = []
        for name, base, normalise in SCRIPTED_TOP_LEVEL_CASES:
            for key in base:
                for label, value in JUNK.items():
                    try:
                        normalise(w, {**base, key: value})
                    except Exception as exc:  # noqa: BLE001 - the point is to list what escapes
                        crashes.append((name, key, label, type(exc).__name__, str(exc)[:60]))
        self.assertEqual(crashes, [])

    def test_no_nested_junk_raises(self):
        w = world_with_offices()
        cases = (
            ("session", session_answer(), SESSION_PATHS, lambda d: actions.normalize_session_v2(w, "B", d, 3)),
            ("revision", revision_answer(), REVISION_PATHS,
             lambda d: actions.normalize_revision(w, "A", d, MOTIONS, 3)),
            ("decision", decision_answer(), DECISION_PATHS,
             lambda d: actions.normalize_decision_v2(w, "A", d, ["M1", "M2"], 3)),
        )
        crashes = []
        for name, base, paths, normalise in cases:
            for path in paths:
                for label, value in JUNK.items():
                    try:
                        normalise(with_value(base, path, value))
                    except Exception as exc:  # noqa: BLE001
                        crashes.append((name, path, label, type(exc).__name__, str(exc)[:60]))
        self.assertEqual(crashes, [])

    def test_a_motion_action_with_junk_regions_still_summarises(self):
        """A relief motion whose action names regions as a number must not break the motion summary the
        council prints for it (motion_summary iterates the regions)."""
        w = world_with_offices()
        data = session_answer()
        data["motions"] = [{"type": "disaster_relief", "subject": "ports", "value": "",
                            "text": "Relief for the ports.",
                            "action": {"regions": 3, "amount": "5m", "scope": "ports"}}]
        out, _ = actions.normalize_session_v2(w, "B", data, 3)
        for motion in out["motions"]:
            actions.motion_summary(w, motion)


class WrongTypeIsRecordedNotSilent(unittest.TestCase):
    """CO2: a field of the wrong type is a recorded problem for that delegate, and is read as empty."""

    def test_a_list_field_holding_a_number_is_a_problem_and_read_as_empty(self):
        w = world_with_offices()
        data = {**SESSION, "information_requests": 3.5}
        out, problems = actions.normalize_session_v2(w, "B", data, 3)
        self.assertEqual(out["information_requests"], [])
        self.assertIn("information_requests is not a list", problems)

    def test_an_object_field_holding_a_list_is_a_problem_and_read_as_empty(self):
        w = world_with_offices()
        data = {**decision_answer(), "votes": [{"motion_id": "M1", "vote": "yes"}]}
        out, problems = actions.normalize_decision_v2(w, "A", data, ["M1"], 3)
        self.assertEqual(out["votes"], {"M1": "abstain"})
        self.assertIn("votes is not an object", problems)

    def test_a_vote_condition_list_holding_a_number_is_a_problem(self):
        w = world_with_offices()
        out, problems = actions.normalize_decision_v2(w, "A", {**decision_answer(), "vote_conditions": 3},
                                                      ["M1", "M2"], 3)
        self.assertIn("vote_conditions is not a list", problems)
        self.assertIn("conditional vote missing valid condition for M2", problems)


class WellFormedAnswersAreReadAsBefore(unittest.TestCase):
    """The golden record: a well-formed answer comes out of the normalisers exactly as before the change."""

    def test_the_three_phases_come_out_as_recorded(self):
        w = world_with_offices()
        got = {
            "session": actions.normalize_session_v2(w, "B", SESSION, 3),
            "revision": actions.normalize_revision(w, "A", REVISION, MOTIONS, 3),
            "decision": actions.normalize_decision_v2(w, "A", DECISION, ["M1", "M2"], 3),
        }
        for phase, (out, problems) in got.items():
            out = json.loads(json.dumps(out, sort_keys=True, default=repr))
            out.pop("over_cap", None)           # the cap record (CO14) is empty for a well-formed answer
            with self.subTest(phase=phase):
                self.assertEqual(out, GOLDEN[phase][0])
                self.assertEqual(problems, GOLDEN[phase][1])


class ReadAnswerSafetyNet(unittest.TestCase):
    """CO2: an exception that escapes a normaliser is a problem for that delegate, not an ended month."""

    def test_read_answer_turns_an_exception_into_a_problem_and_an_empty_answer(self):
        w = world_with_offices()

        def broken(world, mid, data, dm_quota):
            if data is None:
                return actions.normalize_session_v2(world, mid, None, dm_quota)
            raise RuntimeError("boom")

        out, problems = actions.read_answer(broken, w, "B", {"statement": "x"}, 3)
        self.assertEqual(problems, ["answer could not be read (RuntimeError: boom)"])
        self.assertEqual(out["statement"], "")
        self.assertEqual(set(out["private_position"]), set(actions.POSITION_FIELDS))

    def test_read_answer_passes_a_good_answer_through_unchanged(self):
        w = world_with_offices()
        direct = actions.normalize_session_v2(w, "B", SESSION, 3)
        self.assertEqual(actions.read_answer(actions.normalize_session_v2, w, "B", SESSION, 3), direct)


class MonthsCompleteWithJunkAnswers(unittest.TestCase):
    """CO2 at the level of a run: a month with a junk answer in it still finishes, and the run goes on."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="engine19-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def council(self, backend_cls=ScriptedBackend, months=4, foreign_cabinets=False):
        os.makedirs(self.tmp, exist_ok=True)
        cfg = load_config(SCRIPTED)
        run = {"tokens": {}, "foreign_cabinets": foreign_cabinets, "months": months, "seed": 1}
        cfg = {**cfg, "run": {**cfg["run"], **run}}
        cfg = normalize_config({"run": cfg["run"], "seat": cfg["seats"]})
        mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
        cfg["mapping"] = mapping
        w = new_world(cfg["run"]["seed"], months, member_ids=list(mapping),
                      founding_scenario=cfg["run"].get("founding_scenario", "random"),
                      founding_severity=cfg["run"].get("founding_severity", "default"))
        seats = _seats(cfg, mapping)
        for seat in seats.values():
            seat.backend = backend_cls(seat.cfg)
        council = Council(w, seats, cfg["run"], RunStore(os.path.join(self.tmp, "r")))
        council.store.save_config(cfg)
        (council.store.path / "system_prompt.txt").write_text(council.system, encoding="utf-8")
        council.survey()
        council.diagnose_founding()
        council.form_government()
        return council, w

    def test_a_wrongly_typed_session_field_does_not_stop_the_run(self):
        class OneBadAnswer(ScriptedBackend):
            def call(self, system, user, schema, context):
                res = super().call(system, user, schema, context)
                world = context.get("world")
                if (context.get("phase") == "session" and context.get("member") == "C" and world is not None
                        and world.month == 1 and isinstance(res.data, dict)):
                    res.data["information_requests"] = 3.5
                return res

        council, w = self.council(OneBadAnswer)
        for _ in range(3):
            council.run_month()
        self.assertEqual(w.month, 3)

    def test_a_wrongly_typed_ballot_repair_does_not_stop_the_run(self):
        """A ballot whose reason is missing is repaired; the repair answer lists its votes as objects."""
        class Scenario(ScriptedBackend):
            def call(self, system, user, schema, context):
                res = super().call(system, user, schema, context)
                w, mid, phase = context.get("world"), context.get("member"), context.get("phase")
                if w is None or w.month != 1 or not isinstance(res.data, dict):
                    return res
                if phase == "session":
                    res.data["agenda_priorities"] = []
                    res.data["motions"] = ([{"type": "set_policy", "subject": "welfare", "value": "0.02",
                                             "text": "Raise welfare support."}] if mid == "B" else [])
                    return res
                if phase != "decision":
                    return res
                motions = context.get("motions") or []
                if mid == "C" and not context.get("ballot_validation_repair"):
                    res.data["votes"] = {m["id"]: "yes" for m in motions}
                    res.data["vote_reasons"] = {}
                    res.data["vote_conditions"] = []
                elif mid == "C":
                    res.data["votes"] = [{"motion_id": m["id"], "vote": "yes"} for m in motions]
                else:
                    res.data["votes"] = {m["id"]: "yes" for m in motions}
                    res.data["vote_reasons"] = {m["id"]: "yes" for m in motions}
                    res.data["vote_conditions"] = []
                return res

        council, w = self.council(Scenario, months=4)
        council.run_month()
        council.run_month()
        self.assertEqual(w.month, 2)

    def test_a_foreign_cabinet_union_position_as_a_list_does_not_stop_the_run(self):
        class Scenario(ScriptedBackend):
            def call(self, system, user, schema, context):
                res = super().call(system, user, schema, context)
                w, phase = context.get("world"), context.get("phase")
                if (w is not None and w.month == 1 and phase == "foreign" and context.get("actor") == "dorsania"
                        and isinstance(res.data, dict)):
                    res.data["union_position"] = []
                return res

        council, w = self.council(Scenario, months=4, foreign_cabinets=True)
        council.run_month()
        council.run_month()
        self.assertEqual(w.month, 2)

    def test_a_normaliser_that_raises_is_a_problem_for_that_delegate_only(self):
        council, w = self.council(months=4)
        real = actions.normalize_session_v2

        def broken(world, mid, data, dm_quota):
            if mid == "B" and isinstance(data, dict):
                raise RuntimeError("boom")
            return real(world, mid, data, dm_quota)

        with mock.patch.object(actions, "normalize_session_v2", broken):
            record = council.run_month()
        self.assertEqual(w.month, 1)
        calls = [c for c in record["calls"] if c["member"] == "B" and c["phase"] == "session"]
        self.assertEqual(len(calls), 1)
        self.assertIn("answer could not be read (RuntimeError: boom)", calls[0]["problems"])
        others = [c for c in record["calls"] if c["member"] == "A" and c["phase"] == "session"]
        self.assertNotIn("answer could not be read (RuntimeError: boom)", others[0]["problems"])


class ForeignUnionPosition(unittest.TestCase):
    """CO2: a foreign cabinet's union_position is read as text or as no position, never as a crash."""

    def test_a_list_or_an_object_is_no_position_and_a_problem(self):
        for junk in ([], {"a": 1}, 3):
            with self.subTest(junk=junk):
                out, problems = foreign.normalize_cabinet_output("veleria", {"union_position": junk})
                self.assertIsNone(out["union_position"])
                self.assertIn("union_position must be text", problems)

    def test_a_known_position_is_kept(self):
        out, problems = foreign.normalize_cabinet_output("veleria", {"union_position": "support"})
        self.assertEqual(out["union_position"], "support")
        self.assertNotIn("union_position must be text", problems)


class MotionCapIsRecorded(unittest.TestCase):
    """CO14: the motions past the two-motion cap are kept for the record and refused with the cap as the reason."""

    THREE = [
        {"type": "set_policy", "subject": "welfare", "value": "0.02", "text": "Raise welfare support."},
        {"type": "set_policy", "subject": "military", "value": "0.05", "text": "Raise the military budget."},
        {"type": "set_policy", "subject": "surveillance", "value": "medium",
         "text": "Improve police warning capacity."},
    ]

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="engine19-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_normaliser_keeps_the_motions_past_the_cap(self):
        w = world_with_offices()
        out, problems = actions.normalize_session_v2(w, "A", {**session_answer(), "motions": list(self.THREE)}, 3)
        self.assertEqual([m["subject"] for m in out["motions"]], ["welfare", "military"])
        self.assertEqual([m["text"] for m in out["over_cap"]], ["Improve police warning capacity."])
        self.assertIn("too many motions", problems)

    def test_a_refused_third_motion_is_on_the_record_with_the_cap_as_its_reason(self):
        council = MotionCapIsRecorded.council_for(self)
        rec_month0 = council.run_month()
        self.assertEqual(rec_month0["rejected_motions"], [])
        record = council.run_month()
        refused = [r for r in record["rejected_motions"] if r.get("member") == "A"]
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]["reason_code"], "MOTION_CAP_REACHED")
        self.assertIn("Improve police warning capacity.", refused[0]["motion"]["text"])
        self.assertIn("cap", refused[0]["explanation"].lower())
        self.assertEqual(refused[0]["motion"]["type"], "set_policy")

    def test_the_refusal_is_in_the_next_months_briefing(self):
        council = MotionCapIsRecorded.council_for(self)
        council.run_month()
        council.run_month()
        sections = _rejected_last_month(council.last_record, "A")
        self.assertEqual([s.key for s in sections], ["rejected_last_month"])
        self.assertIn("MOTION_CAP_REACHED", sections[0].text)

    def test_the_code_is_registered(self):
        self.assertTrue(errors.is_registered("MOTION_CAP_REACHED"))
        self.assertEqual(errors.describe("MOTION_CAP_REACHED")["registered"], True)

    @staticmethod
    def council_for(test):
        """A scripted run in which Delegate A offers three motions in Month 1; the others offer none."""
        class ThreeMotions(ScriptedBackend):
            def call(self, system, user, schema, context):
                res = super().call(system, user, schema, context)
                w, mid, phase = context.get("world"), context.get("member"), context.get("phase")
                if w is None or w.month != 1:
                    return res
                if phase == "session" and isinstance(res.data, dict):
                    res.data["agenda_priorities"] = []
                    res.data["motions"] = [dict(m) for m in MotionCapIsRecorded.THREE] if mid == "A" else []
                if phase == "decision" and isinstance(res.data, dict):
                    motions = context.get("motions") or []
                    res.data["votes"] = {m["id"]: "yes" for m in motions}
                    res.data["vote_reasons"] = {m["id"]: "yes" for m in motions}
                    res.data["vote_conditions"] = []
                return res

        helper = MonthsCompleteWithJunkAnswers()
        helper.tmp = tempfile.mkdtemp(prefix="engine19-cap-")
        test.addCleanup(shutil.rmtree, helper.tmp, True)
        council, w = helper.council(ThreeMotions, months=4)
        w.tuning = {"agenda": {"fiscal_extra": 0, "emergency_extra": 0}}
        for mid in "ABCDE":
            standing.ensure(w, mid)["capital"] = 0.5
        return council


if __name__ == "__main__":
    unittest.main()
