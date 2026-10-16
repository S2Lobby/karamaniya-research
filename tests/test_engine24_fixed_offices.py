"""Engine 24, item S1 (HANDOFF-PROMPT section 9.S): offices fixed by letter.

With `office_assignment = "by_letter"` the Month-0 formation vote is skipped, and in every run A holds the head of
government, B the treasury, C the interior, D the army and E the navy. The SocioVerse study needs every model to hold
every office across its rotations, and a vote cannot promise that. The default, "formation", is today's behaviour:
tests/test_prompt_freeze.py checks that a default run still sends the recorded prompts.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import manifest, politics  # noqa: E402
from karamaniya.config import normalize_config  # noqa: E402
from karamaniya.runner import new_run, resume_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import OFFICE_TITLES, OFFICES  # noqa: E402

LETTER_OFFICE = {"A": "head", "B": "treasury", "C": "interior", "D": "army", "E": "navy"}
OFFICE_LETTER = {office: letter for letter, office in LETTER_OFFICE.items()}
PERSONAS = ("democrat", "technocrat", "hawk", "loyalist", "opportunist")
FORMATION_CALLS = ("formation_proposal", "formation_vote")
SESSION_LINE = ("Offices: head: Delegate A; treasury: Delegate B; interior: Delegate C; army: Delegate D; "
                "navy: Delegate E.")


def write_config(path, option=None, seats=5, months=2):
    """A scripted council modelled on council.scripted.toml, with the option written the way a config file has it."""
    lines = ["[run]", f"months = {months}", "seed = 1", "survey = true"]
    if option is not None:
        lines.append(f'office_assignment = "{option}"')
    for i, persona in enumerate(PERSONAS[:seats]):
        lines += ["", "[[seat]]", f'label = "scripted-{i + 1}-{persona}"', 'provider = "scripted"',
                  f'persona = "{persona}"']
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class Crash(BaseException):
    """Stands in for a process that dies mid-run: a BaseException, so no handler in the engine catches it."""


def scripted_seats(count):
    return [{"label": f"s{i}", "provider": "scripted", "persona": PERSONAS[i % len(PERSONAS)]}
            for i in range(count)]


class OptionValidationTests(unittest.TestCase):
    """The option is checked in config.py, next to foreign_cabinet_backend, and refused with a clear error."""

    def normalized(self, option=None, seats=5):
        run = {} if option is None else {"office_assignment": option}
        return normalize_config({"run": run, "seat": scripted_seats(seats)}, "test")

    def test_the_default_is_the_formation_vote(self):
        self.assertEqual(self.normalized()["run"]["office_assignment"], "formation")

    def test_by_letter_is_accepted_for_five_members(self):
        self.assertEqual(self.normalized("by_letter")["run"]["office_assignment"], "by_letter")

    def test_any_other_value_is_refused(self):
        with self.assertRaisesRegex(ValueError, "office_assignment"):
            self.normalized("random")

    def test_by_letter_needs_exactly_five_members(self):
        for seats in (3, 4, 6, 12):
            with self.subTest(seats=seats), self.assertRaisesRegex(ValueError, "five"):
                self.normalized("by_letter", seats=seats)

    def test_the_formation_vote_is_not_limited_to_five_members(self):
        self.assertEqual(self.normalized("formation", seats=3)["run"]["office_assignment"], "formation")

    def test_new_run_refuses_an_unnormalized_config_before_it_writes_anything(self):
        tmp = tempfile.mkdtemp(prefix="karamaniya-s1-refuse-")
        try:
            cfg = {"run": {"months": 2, "seed": 1, "office_assignment": "by_letter"}, "seats": scripted_seats(3)}
            with self.assertRaisesRegex(ValueError, "five"):
                new_run(cfg, runs_dir=tmp, name="refused", quiet=True, check=False)
            self.assertFalse(os.path.exists(os.path.join(tmp, "refused")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ManifestComparisonTests(unittest.TestCase):
    """Two runs that filled their offices differently are not like-for-like, and the comparison names the difference."""

    def test_different_office_assignments_are_named_as_a_difference(self):
        by_letter = {"office_assignment": {"option": "by_letter", "formation_vote": False}}
        formation = {"office_assignment": {"option": "formation", "formation_vote": True}}
        self.assertIn("office_assignment", manifest.divergences(by_letter, formation))

    def test_an_older_manifest_without_the_option_is_a_formation_run(self):
        formation = {"office_assignment": {"option": "formation", "formation_vote": True}}
        self.assertNotIn("office_assignment", manifest.divergences({}, formation))


class ByLetterRunTests(unittest.TestCase):
    """A two-month scripted run with the offices fixed by letter, and a stop before Month 1 for the resume test."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-s1-")
        cls.config = os.path.join(cls.tmp, "by_letter.toml")
        write_config(cls.config, option="by_letter")
        with mock.patch.object(politics, "reset_bond", wraps=politics.reset_bond) as reset:
            cls.path = new_run(cls.config, runs_dir=cls.tmp, name="by-letter", months=2, quiet=True, check=False)
        cls.reset_offices = [call.args[1] for call in reset.call_args_list]
        cls.store = RunStore(cls.path)
        cls.world, _, _ = cls.store.load_checkpoint()
        cls.prompts = read_jsonl(os.path.join(cls.path, "prompts.jsonl"))
        with open(os.path.join(cls.path, "system_prompt.txt"), encoding="utf-8") as f:
            cls.system = f.read()
        cls.config_json = cls.store.read_json("config.json")
        cls.manifest = cls.store.read_json("manifest.json")
        with open(os.path.join(cls.path, "scorecard.json"), encoding="utf-8") as f:
            cls.scorecard = json.load(f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def month_prompt(self, letter, phase, month=0):
        for rec in self.prompts:
            if rec.get("member") == letter and rec.get("month") == month and rec.get("phase") == phase:
                return rec["prompt"]
        self.fail(f"no {phase} prompt for {letter} in month {month}")

    def test_each_letter_holds_its_office_from_month_one(self):
        self.assertEqual(self.world.history[0]["offices"], OFFICE_LETTER)
        self.assertEqual(self.world.history[1]["offices"], OFFICE_LETTER)
        self.assertEqual(self.world.const.offices, OFFICE_LETTER)

    def test_no_formation_call_is_made_and_the_diagnoses_still_are(self):
        phases = {rec.get("phase") for rec in self.prompts}
        self.assertFalse(phases & set(FORMATION_CALLS), phases)
        self.assertIn("founding_diagnosis", phases)
        self.assertEqual([c for c in self.store.read_log("call") if c.get("phase") in FORMATION_CALLS], [])
        self.assertEqual(self.store.read_log("formation_no_motions"), [])

    def test_the_formation_record_keeps_the_shape_the_vote_keeps(self):
        rec = self.world.founding["formation"]
        self.assertLessEqual({"month", "proposals", "motions", "offices", "agenda_slots_used"}, set(rec))
        self.assertEqual(rec["month"], -1)
        self.assertEqual(rec["proposals"], {})
        self.assertEqual(rec["motions"], [])
        self.assertEqual(rec["agenda_slots_used"], 0)
        self.assertEqual(rec["offices"], OFFICE_LETTER)
        self.assertEqual(rec["assignment"], "by_letter")
        self.assertIn("by letter", rec["note"])

    def test_the_log_and_the_run_record_say_the_offices_were_assigned_by_letter(self):
        logged = self.store.read_log("government_formation")
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0]["assignment"], "by_letter")
        self.assertEqual(self.config_json["run"]["office_assignment"], "by_letter")
        self.assertEqual(self.manifest["office_assignment"],
                         {"option": "by_letter", "formation_vote": False, "letters": LETTER_OFFICE})

    def test_each_seat_is_told_the_office_its_letter_holds(self):
        for letter, office in LETTER_OFFICE.items():
            with self.subTest(letter=letter):
                prompt = self.month_prompt(letter, "session")
                self.assertIn(f"YOU ARE DELEGATE {letter}\nOffice: {OFFICE_TITLES[office]}", prompt)
                self.assertIn(SESSION_LINE, prompt)

    def test_each_seat_with_an_office_gets_orders_for_that_office(self):
        for letter, office in LETTER_OFFICE.items():
            if office == "head":
                continue
            with self.subTest(letter=letter):
                self.assertIn(f"Give orders for your offices ({office})", self.month_prompt(letter, "decision"))

    def test_the_prompts_do_not_describe_a_vote_that_was_not_held(self):
        self.assertIn("filled by assignment, without a vote", self.system)
        self.assertNotIn("propose and vote on procedural office appointments", self.system)
        self.assertIn("after the offices were filled without a vote", self.month_prompt("A", "session"))
        self.assertNotIn("government-formation vote", self.month_prompt("A", "session"))

    def test_the_scorecard_counts_each_letter_in_its_own_office(self):
        for letter, office in LETTER_OFFICE.items():
            with self.subTest(letter=letter):
                self.assertEqual(self.scorecard["members"][letter]["office_months"], {office: 2})

    def test_every_office_gets_the_same_loyalty_reset_the_vote_gives_it(self):
        self.assertLessEqual(set(OFFICES), set(self.reset_offices))

    def test_a_run_that_dies_at_the_formation_resumes_with_the_offices_assigned_once(self):
        tmp = tempfile.mkdtemp(prefix="karamaniya-s1-crash-")
        try:
            def die_at_formation(event):
                if event.get("type") == "government_formation":
                    raise Crash()

            with self.assertRaises(Crash):
                new_run(self.config, runs_dir=tmp, name="crashed", months=2, quiet=True, check=False,
                        observer=die_at_formation)
            path = Path(tmp) / "crashed"
            _, _, meta = RunStore(path).load_checkpoint()
            self.assertTrue(meta.get("government_formation_pending"))
            resumed = resume_run(path, quiet=True, check=False)
            after, _, _ = RunStore(resumed).load_checkpoint()
            self.assertEqual(len(after.history), 2)
            self.assertEqual(after.history[1]["offices"], OFFICE_LETTER)
            self.assertEqual(after.founding["formation"]["assignment"], "by_letter")
            self.assertEqual(len(RunStore(resumed).read_log("government_formation")), 1)
            calls = RunStore(resumed).read_log("call")
            self.assertEqual([c for c in calls if c.get("phase") in FORMATION_CALLS], [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_run_stopped_before_month_one_resumes_with_the_same_offices_and_no_formation_call(self):
        tmp = tempfile.mkdtemp(prefix="karamaniya-s1-resume-")
        try:
            stop = threading.Event()
            stop.set()
            path = new_run(self.config, runs_dir=tmp, name="stopped", months=2, quiet=True, check=False,
                           stop_event=stop)
            before, _, _ = RunStore(path).load_checkpoint()
            self.assertEqual(before.history, [])
            self.assertEqual(before.const.offices, OFFICE_LETTER)
            resumed = resume_run(path, quiet=True, check=False)
            after, _, _ = RunStore(resumed).load_checkpoint()
            self.assertEqual(len(after.history), 2)
            self.assertEqual(after.history[1]["offices"], OFFICE_LETTER)
            calls = RunStore(resumed).read_log("call")
            self.assertEqual([c for c in calls if c.get("phase") in FORMATION_CALLS], [])
            self.assertEqual(len(RunStore(resumed).read_log("government_formation")), 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class DefaultRunTests(unittest.TestCase):
    """The default run still holds the formation vote, and its run record says so."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-s1-default-")
        cls.config = os.path.join(cls.tmp, "formation.toml")
        write_config(cls.config)
        cls.path = new_run(cls.config, runs_dir=cls.tmp, name="formation", months=2, quiet=True, check=False)
        cls.store = RunStore(cls.path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_default_run_still_holds_the_formation_vote(self):
        calls = [c.get("phase") for c in self.store.read_log("call")]
        self.assertIn("formation_proposal", calls)
        self.assertIn("formation_vote", calls)

    def test_the_default_run_records_the_formation_option_in_its_config_and_manifest(self):
        self.assertEqual(self.store.read_json("config.json")["run"]["office_assignment"], "formation")
        self.assertEqual(self.store.read_json("manifest.json")["office_assignment"],
                         {"option": "formation", "formation_vote": True})

    def test_the_default_formation_record_has_no_by_letter_note(self):
        rec = self.store.read_log("government_formation")[0]
        self.assertNotIn("assignment", rec)
        self.assertGreater(len(rec["motions"]), 0)


if __name__ == "__main__":
    unittest.main()
