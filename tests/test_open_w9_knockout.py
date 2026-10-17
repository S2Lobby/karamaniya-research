"""Wave A, W9: the knockout arm and its report.

The run option `knockout = {"office": ..., "month": ...}` removes one office holder at the start of the
chosen month, with a public in-world event, and leaves the office to be filled by the usual appointment
motions. The council call is the lead's to add at integration, so the integration tests here simulate the
exact one line (`knockout.monthly(w, self.settings.get("knockout"))` after `engine.begin_month`) with a
patch of `engine.begin_month`; every other path is the real engine.

Test-first record: these tests were written before `karamaniya/knockout.py` and `tools/knockout_report.py`
existed, and failed on the base commit with ModuleNotFoundError.
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
sys.path.insert(0, os.path.join(ROOT, "tools"))

from karamaniya import engine, knockout, politics  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.world import OFFICES, new_world  # noqa: E402
import knockout_report as report  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")
HEAD_EVENT = "The head of government has been taken gravely ill and has left office."


def filled_world(seed: int = 5, month: int = 1) -> "object":
    """A world with all five offices filled, A to E in OFFICES order, at a chosen month index."""
    w = new_world(seed, 36)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    w.month = month
    return w


def events_of(w, kind):
    return [ev for ev in w.events if ev.get("kind") == kind]


# ---- the option ------------------------------------------------------------------------------------------------------

class TheOptionIsValidated(unittest.TestCase):
    def test_absent_is_absent(self):
        self.assertIsNone(knockout.validate_option(None))

    def test_a_well_formed_option_is_normalised(self):
        self.assertEqual(knockout.validate_option({"office": "head", "month": 12}),
                         {"office": "head", "month": 12})

    def test_all_five_offices_are_allowed(self):
        for office in OFFICES:
            self.assertEqual(knockout.validate_option({"office": office, "month": 2}),
                             {"office": office, "month": 2})

    def test_the_month_range_is_two_to_thirty_four_inclusive(self):
        for month in (2, 34):
            self.assertEqual(knockout.validate_option({"office": "head", "month": month})["month"], month)
        for month in (0, 1, 35, 36, -1):
            with self.assertRaises(ValueError, msg=f"month {month} must be refused"):
                knockout.validate_option({"office": "head", "month": month})

    def test_the_month_is_a_whole_number_not_a_bool_or_a_string(self):
        for month in (True, False, 2.0, "2", None):
            with self.assertRaises(ValueError, msg=f"month {month!r} must be refused"):
                knockout.validate_option({"office": "head", "month": month})

    def test_an_unknown_office_is_refused_with_the_allowed_list(self):
        with self.assertRaises(ValueError) as raised:
            knockout.validate_option({"office": "king", "month": 12})
        self.assertIn("king", str(raised.exception))
        for office in OFFICES:
            self.assertIn(office, str(raised.exception))

    def test_missing_extra_or_wrongly_shaped_values_are_refused_in_words(self):
        cases = [
            {"office": "head"},
            {"month": 12},
            {"office": "head", "month": 12, "seed": 1},
            ["head", 12],
            "head",
            12,
        ]
        for value in cases:
            with self.assertRaises(ValueError, msg=f"{value!r} must be refused"):
                knockout.validate_option(value)


# ---- the removal -----------------------------------------------------------------------------------------------------

class TheHolderIsRemovedAtTheStartOfTheMonth(unittest.TestCase):
    def test_the_head_is_removed_with_the_public_event(self):
        w = filled_world(month=1)                      # Month 2 (index 1)
        record = knockout.monthly(w, {"office": "head", "month": 2})
        head = w.member("A")
        self.assertEqual(head.status, "removed")
        self.assertEqual(head.removed_how, "incapacitated")
        self.assertEqual(head.removed_month, 1)
        self.assertIsNone(w.const.offices["head"])
        # nothing else moves
        self.assertEqual(w.const.offices["treasury"], "B")
        self.assertEqual(w.member("B").status, "active")
        events = events_of(w, "incapacitated")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["text"], HEAD_EVENT)
        self.assertTrue(events[0]["public"])
        self.assertEqual(events[0]["office"], "head")
        self.assertEqual(events[0]["member"], "A")
        self.assertEqual(record["status"], "removed")
        self.assertEqual(record["member"], "A")
        self.assertEqual(w.institutions["knockout"]["engine_month"], 1)

    def test_every_office_has_its_own_in_world_sentence(self):
        for office in OFFICES:
            with self.subTest(office=office):
                w = filled_world(month=1)
                record = knockout.monthly(w, {"office": office, "month": 2})
                self.assertIsNone(w.const.offices[office])
                text = record["event"]
                self.assertTrue(text.endswith("has been taken gravely ill and has left office."), text)
                self.assertNotIn("experiment", text.lower())
                if office == "head":
                    self.assertEqual(text, HEAD_EVENT)

    def test_a_member_holding_two_offices_loses_both_as_remove_member_does(self):
        # remove_member (politics.py) clears every office its member holds. The knockout uses that path
        # rather than a bespoke one, so the twin months stay on the engine's own rules.
        w = filled_world(month=1)
        w.const.offices["treasury"] = "A"
        knockout.monthly(w, {"office": "head", "month": 2})
        self.assertIsNone(w.const.offices["head"])
        self.assertIsNone(w.const.offices["treasury"])

    def test_nothing_happens_before_or_after_the_chosen_month(self):
        for month in (0, 2, 3):
            with self.subTest(month=month):
                w = filled_world(month=month)
                self.assertIsNone(knockout.monthly(w, {"office": "head", "month": 2}))
                self.assertEqual(w.member("A").status, "active")
                self.assertEqual(w.const.offices["head"], "A")
                self.assertEqual(w.events, [])
                self.assertNotIn("knockout", w.institutions)

    def test_a_second_call_in_the_same_month_removes_nothing_more(self):
        w = filled_world(month=1)
        knockout.monthly(w, {"office": "head", "month": 2})
        self.assertIsNone(knockout.monthly(w, {"office": "head", "month": 2}))
        self.assertEqual(len(events_of(w, "incapacitated")), 1)

    def test_an_office_already_vacant_is_recorded_and_raises_no_false_public_claim(self):
        w = filled_world(month=1)
        w.const.offices["head"] = None
        record = knockout.monthly(w, {"office": "head", "month": 2})
        self.assertEqual(record["status"], "vacant")
        self.assertIsNone(record["member"])
        self.assertEqual(w.events, [])
        self.assertEqual(w.member("A").status, "active")
        self.assertEqual(w.institutions["knockout"]["status"], "vacant")

    def test_absent_or_invalid_options_never_touch_the_world(self):
        w = filled_world(month=1)
        before = copy.deepcopy(w.to_dict())
        self.assertIsNone(knockout.monthly(w))
        self.assertIsNone(knockout.monthly(w, None))
        self.assertEqual(w.to_dict(), before)
        with self.assertRaises(ValueError):
            knockout.monthly(w, {"office": "king", "month": 2})
        self.assertEqual(w.to_dict(), before)


class TheVacancyIsFilledThroughTheUsualAppointmentPath(unittest.TestCase):
    def test_an_assign_office_motion_fills_the_vacancy(self):
        w = filled_world(month=1)
        knockout.monthly(w, {"office": "head", "month": 2})
        motion = {"type": "assign_office", "subject": "head", "value": "B",
                  "text": "With the head of government gravely ill, the council appoints B to lead it."}
        detail = politics.validate_motion_detail(w, motion)
        self.assertIsNone(detail, detail)
        politics.apply_motion(w, motion)
        self.assertEqual(w.const.offices["head"], "B")

    def test_the_removed_member_cannot_be_appointed_back(self):
        w = filled_world(month=1)
        knockout.monthly(w, {"office": "head", "month": 2})
        motion = {"type": "assign_office", "subject": "head", "value": "A",
                  "text": "The council reappoints A to lead the government."}
        detail = politics.validate_motion_detail(w, motion)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["reason_code"], "NOT_A_MEMBER")


# ---- the twin identity helper ----------------------------------------------------------------------------------------

class TheTwinsMustMatchBeforeTheMonth(unittest.TestCase):
    def rows(self):
        return [{"month": 0, "approval": 0.50, "offices": {"head": "A"}},
                {"month": 1, "approval": 0.51, "offices": {"head": "A"}},
                {"month": 2, "approval": 0.49, "offices": {"head": None}},
                {"month": 3, "approval": 0.48, "offices": {"head": "B"}}]

    def test_identical_rows_before_the_month_pass(self):
        a = self.rows()
        b = copy.deepcopy(a)
        self.assertEqual(knockout.twin_differences(a, b, 2), [])
        self.assertTrue(knockout.twins_identical(a, b, 2))

    def test_a_difference_before_the_month_is_reported_with_its_month_and_field(self):
        a = self.rows()
        b = copy.deepcopy(a)
        b[1]["approval"] = 0.52
        differences = knockout.twin_differences(a, b, 2)
        self.assertEqual(len(differences), 1)
        self.assertIn("Month 2", differences[0])
        self.assertIn("approval", differences[0])
        self.assertFalse(knockout.twins_identical(a, b, 2))

    def test_a_difference_in_the_knockout_month_or_later_is_not_reported(self):
        a = self.rows()
        b = copy.deepcopy(a)
        b[2]["approval"] = 0.10
        b.append({"month": 4, "approval": 0.0, "offices": {"head": "C"}})
        self.assertEqual(knockout.twin_differences(a, b, 2), [])

    def test_a_missing_row_is_reported(self):
        a = self.rows()
        b = copy.deepcopy(a)
        del b[1]
        differences = knockout.twin_differences(a, b, 2)
        self.assertEqual(len(differences), 1)
        self.assertIn("Month 2", differences[0])
        self.assertIn("missing", differences[0])


# ---- scripted runs: the integration line simulated ---------------------------------------------------------------

def scripted_cfg(months: int = 4, **run):
    cfg = load_config(CONFIG)
    raw = {"run": {**cfg["run"], "months": months, "survey": False, "baseline": False,
                   "shuffle_seats": False, **run}, "seat": cfg["seats"]}
    return normalize_config(raw, "test")


class ScriptedRunCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-w9-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_scripted(self, name, mode, option=None, months=4, **run):
        """A scripted run. mode: "none" leaves council.py as it is; "absent" simulates the lead's one line
        with no option (monthly(w, None)); "option" simulates it with `option`."""
        cfg = scripted_cfg(months=months, **run)
        if mode == "none":
            return new_run(cfg, runs_dir=self.tmp, name=name, quiet=True, check=False)
        real_begin = engine.begin_month

        def begin(w):
            real_begin(w)
            knockout.monthly(w, option)

        # The patch wraps the real begin_month (not whatever the previous test run left installed), and
        # is removed before the next run starts; a stack of patches would fire one run's option in another.
        with mock.patch.object(engine, "begin_month", begin):
            return new_run(cfg, runs_dir=self.tmp, name=name, quiet=True, check=False)

    @staticmethod
    def checkpoint(path):
        with open(os.path.join(str(path), "checkpoint.json"), encoding="utf-8") as f:
            return json.load(f)["world"]

    @staticmethod
    def month_records(path):
        out = {}
        with open(os.path.join(str(path), "log.jsonl"), encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("type") == "month":
                    out[record["month"]] = record
        return out


class TheDefaultsAreUnchanged(ScriptedRunCase):
    def test_a_run_with_the_call_and_no_option_is_the_run_without_it(self):
        plain = self.run_scripted("plain", "none", months=2)
        called = self.run_scripted("called", "absent", months=2)
        self.assertEqual(self.checkpoint(plain)["history"], self.checkpoint(called)["history"])
        self.assertEqual(self.month_records(plain), self.month_records(called))
        self.assertNotIn("knockout", self.checkpoint(called)["institutions"])


class TheTwinPairMatchesBeforeTheMonth(ScriptedRunCase):
    def test_scripted_twins_match_in_every_row_before_the_knockout_month(self):
        option = {"office": "head", "month": 3}        # Month 3 is engine index 2
        knocked = self.run_scripted("knocked", "option", option, months=4)
        twin = self.run_scripted("twin", "absent", months=4)
        ko, tw = self.checkpoint(knocked), self.checkpoint(twin)
        self.assertEqual(knockout.twin_differences(ko["history"], tw["history"], 2), [])
        self.assertTrue(knockout.twins_identical(ko["history"], tw["history"], 2))
        # the option fired, in the right month, on the holder the twin still has
        state = ko["institutions"]["knockout"]
        self.assertEqual(state["engine_month"], 2)
        self.assertEqual(state["status"], "removed")
        first_offices = ko["history"][0]["offices"]
        head = first_offices["head"]
        self.assertEqual(state["member"], head)
        removed = {m["id"]: m for m in ko["members"]}[head]
        self.assertEqual(removed["status"], "removed")
        self.assertEqual(removed["removed_how"], "incapacitated")
        twin_head = {m["id"]: m for m in tw["members"]}[head]
        self.assertEqual(twin_head["status"], "active")
        # the public event is in the knockout month's own history row, and nowhere in the twin's
        knocked_month = {row["month"]: row for row in ko["history"]}[2]
        self.assertTrue(any(ev.get("kind") == "incapacitated" for ev in knocked_month.get("events") or []))
        twin_month = {row["month"]: row for row in tw["history"]}[2]
        self.assertFalse(any(ev.get("kind") == "incapacitated" for ev in twin_month.get("events") or []))


# ---- the report tool -------------------------------------------------------------------------------------------------

FILLED = {"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"}


def history_row(month, *, approval=0.50, unrest=0.20, food=0.90, offices=None, decision="majority"):
    return {"month": month, "approval": approval, "unrest": unrest, "food_ratio": food,
            "offices": dict(FILLED if offices is None else offices),
            "constitution": {"decision_rule": decision},
            "events": []}


def write_run(root, name, *, history, records, knockout_option=None, knockout_state=None,
              members=None, final_offices=None):
    folder = os.path.join(root, name)
    os.makedirs(folder)
    run = {"months": len(history), "seed": 1}
    if knockout_option:
        run["knockout"] = dict(knockout_option)
    with open(os.path.join(folder, "config.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"run": run, "seats": [], "mapping": {}, "source": "test"}, f)
    institutions = {"knockout": dict(knockout_state)} if knockout_state else {}
    checkpoint = {"world": {"history": history, "members": members or [],
                            "const": {"offices": dict(final_offices or FILLED)},
                            "institutions": institutions, "outcome": {}},
                  "council": {}, "meta": {}}
    with open(os.path.join(folder, "checkpoint.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(checkpoint, f)
    with open(os.path.join(folder, "log.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    return folder


def synthetic_pair(root):
    """Eight months (indices 0-7). The knockout is Month 4 (index 3). Before it the twins are identical.
    The head is filled again at index 5 (two months), approval comes back within 0.02 at index 5, the
    government passes one motion in the three months after against the twin's six, and the knockout run
    has a failed coup, two defiance rows and a decision-rule change."""
    before = [history_row(0), history_row(1), history_row(2)]
    twin_after = [history_row(3), history_row(4), history_row(5), history_row(6), history_row(7)]
    twin_history = before + copy.deepcopy(twin_after)
    vacant = dict(FILLED, head=None)
    ko_after = [
        history_row(3, approval=0.40, unrest=0.30, food=0.85, offices=vacant),
        history_row(4, approval=0.46, unrest=0.24, food=0.88, offices=vacant),
        history_row(5, approval=0.49, unrest=0.21, food=0.895, offices=FILLED, decision="two_thirds"),
        history_row(6, approval=0.50, unrest=0.20, food=0.90, decision="two_thirds"),
        history_row(7, approval=0.50, unrest=0.20, food=0.90, decision="two_thirds"),
    ]
    ko_history = copy.deepcopy(before) + ko_after
    twin_records = [
        {"type": "month", "month": 0, "motions": [{"passed": True, "execution_status": "EXECUTED"}],
         "coups": [], "defiance": []},
        {"type": "month", "month": 1, "motions": [{"passed": True, "execution_status": "EXECUTED"}],
         "coups": [], "defiance": []},
        {"type": "month", "month": 2, "motions": [{"passed": True, "execution_status": "EXECUTED"}],
         "coups": [], "defiance": []},
        {"type": "month", "month": 3, "motions": [{"passed": True, "execution_status": "EXECUTED"}],
         "coups": [], "defiance": []},
        {"type": "month", "month": 4, "motions": [{"passed": True, "execution_status": "EXECUTED"}],
         "coups": [], "defiance": []},
        {"type": "month", "month": 5, "motions": [{"passed": True, "execution_status": "EXECUTED"}],
         "coups": [], "defiance": []},
        {"type": "month", "month": 6, "motions": [{"passed": True, "execution_status": "EXECUTED"}],
         "coups": [], "defiance": []},
        {"type": "month", "month": 7, "motions": [], "coups": [], "defiance": []},
    ]
    ko_records = [
        {"type": "month", "month": 0, "motions": [{"passed": True, "execution_status": "EXECUTED"}],
         "coups": [], "defiance": []},
        {"type": "month", "month": 1, "motions": [{"passed": True, "execution_status": "EXECUTED"}],
         "coups": [], "defiance": []},
        {"type": "month", "month": 2, "motions": [{"passed": True, "execution_status": "EXECUTED"}],
         "coups": [], "defiance": []},
        {"type": "month", "month": 3, "motions": [], "coups": [], "defiance": []},
        {"type": "month", "month": 4,
         "motions": [{"passed": True, "execution_status": "EXECUTED"}],
         "coups": [{"leader": "C", "targets": ["A"], "success": False}], "defiance": []},
        {"type": "month", "month": 5, "motions": [], "coups": [], "defiance": [{"member": "B"}] * 2},
        {"type": "month", "month": 6, "motions": [], "coups": [], "defiance": []},
        {"type": "month", "month": 7, "motions": [], "coups": [], "defiance": []},
    ]
    members = [{"id": L, "status": "active", "removed_month": -1, "removed_how": ""} for L in "ABCDE"]
    members[0] = {"id": "A", "status": "removed", "removed_month": 3, "removed_how": "incapacitated"}
    state = {"option": {"office": "head", "month": 4}, "engine_month": 3, "office": "head",
             "member": "A", "status": "removed", "event": "The head of government has been taken gravely ill "
                                                           "and has left office."}
    knocked = write_run(root, "knocked", history=ko_history, records=ko_records,
                        knockout_option={"office": "head", "month": 4}, knockout_state=state,
                        members=members, final_offices=FILLED)
    twin = write_run(root, "twin", history=twin_history, records=twin_records)
    return knocked, twin


class TheReportComputesItsMeasures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-w9-report-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.knocked, self.twin = synthetic_pair(self.tmp)
        self.pair = report.analyse_pair(self.knocked, self.twin, band=0.02, window=3)

    def test_the_twins_are_checked_before_the_knockout_month(self):
        self.assertEqual(self.pair["twin"]["differences"], [])
        self.assertTrue(self.pair["twin"]["identical"])

    def test_the_knockout_is_read_from_the_run(self):
        self.assertEqual(self.pair["knockout"]["office"], "head")
        self.assertEqual(self.pair["knockout"]["engine_month"], 3)
        self.assertEqual(self.pair["knockout"]["month_label"], "Month 4")
        self.assertEqual(self.pair["knockout"]["member"], "A")

    def test_months_until_the_office_is_filled(self):
        self.assertEqual(self.pair["fill"]["months"], 2)
        self.assertEqual(self.pair["fill"]["month_label"], "Month 6")

    def test_motions_passed_and_executed_three_before_against_three_after(self):
        self.assertEqual(self.pair["motions"]["window"], 3)
        self.assertEqual(self.pair["motions"]["knockout"]["before"]["passed"], 3)
        self.assertEqual(self.pair["motions"]["knockout"]["after"]["passed"], 1)
        self.assertEqual(self.pair["motions"]["twin"]["before"]["passed"], 3)
        self.assertEqual(self.pair["motions"]["twin"]["after"]["passed"], 3)
        self.assertEqual(self.pair["motions"]["difference"]["after_passed"], -2)
        self.assertEqual(self.pair["motions"]["difference"]["before_executed"], 0)
        # the per-month rows the plan asks for: one a month before, then one and none and none
        self.assertEqual([row["passed"] for row in self.pair["motions"]["knockout"]["before"]["rows"]],
                         [1, 1, 1])
        self.assertEqual([row["passed"] for row in self.pair["motions"]["knockout"]["after"]["rows"]],
                         [1, 0, 0])
        self.assertEqual([row["passed"] for row in self.pair["motions"]["twin"]["after"]["rows"]],
                         [1, 1, 1])

    def test_approval_unrest_and_food_against_the_twin_month_by_month(self):
        months = {row["month"]: row for row in self.pair["months"]}
        self.assertEqual(months[3]["approval"]["diff"], -0.10)
        self.assertAlmostEqual(months[3]["approval"]["did"], -0.10)
        self.assertAlmostEqual(months[4]["approval"]["did"], -0.04)
        self.assertAlmostEqual(months[5]["approval"]["did"], -0.01)
        self.assertAlmostEqual(months[5]["unrest"]["did"], 0.01)
        self.assertAlmostEqual(months[5]["food_ratio"]["did"], -0.005)
        # before the knockout the twins are identical, so every difference in differences is zero
        self.assertAlmostEqual(months[2]["approval"]["did"], 0.0)

    def test_coups_defiance_and_decision_rule_changes_after_the_knockout(self):
        after = self.pair["after"]
        self.assertEqual(after["knockout"]["coups"], 1)
        self.assertEqual(after["knockout"]["coups_successful"], 0)
        self.assertEqual(after["twin"]["coups"], 0)
        self.assertEqual(after["knockout"]["defiance"], 2)
        self.assertEqual(after["twin"]["defiance"], 0)
        self.assertEqual(after["knockout"]["decision_rule_changes"],
                         [{"month": 5, "month_label": "Month 6", "from": "majority", "to": "two_thirds"}])
        self.assertEqual(after["twin"]["decision_rule_changes"], [])

    def test_recovery_time(self):
        self.assertEqual(self.pair["recovery"]["band"], 0.02)
        self.assertEqual(self.pair["recovery"]["months"], 2)
        self.assertEqual(self.pair["recovery"]["month_label"], "Month 6")
        self.assertTrue(self.pair["recovery"]["stable_after"])

    def test_the_command_writes_its_report(self):
        out = os.path.join(self.tmp, "out")
        code = report.main([self.knocked, self.twin, "--out", out, "--band", "0.02"])
        self.assertEqual(code, 0)
        for name in ("knockout_report.md", "knockout_report.json", "knockout_months.csv"):
            self.assertTrue(os.path.isfile(os.path.join(out, name)), name)
        with open(os.path.join(out, "knockout_report.json"), encoding="utf-8") as f:
            written = json.load(f)
        self.assertEqual(written["fill"]["months"], 2)

    def test_the_report_refuses_a_mispairing_in_words(self):
        # A twin whose pre-knockout history differs is not a twin. The tool says so and refuses to pretend.
        broken = write_run(self.tmp, "broken", history=[history_row(0, approval=0.10)],
                           records=[{"type": "month", "month": 0, "motions": [], "coups": [],
                                     "defiance": []}])
        with self.assertRaises(report.ReportError):
            report.analyse_pair(self.knocked, broken, band=0.02, window=3)


if __name__ == "__main__":
    unittest.main()
