"""Engine 19, slice "what the delegates read": the prompt text that is sent to the delegates.

Audit IDs in this file: TO2 (motion and amendment text cut silently), TO3 (the Treasury's tax printed to two
places), TO6 (small seats lose sections silently), TO8 (one output figure printed twice), TO9 (the English word
"union" translated), TO10 (an emergency measure's length) and AG7 (the short disposition keeps its key lines).
"""
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import briefing, decision_context, naming, prompts  # noqa: E402
from karamaniya.actions import MOTION_WORDS, words  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.politics import fmt_value  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402

SCRIPTED = os.path.join(ROOT, "council.scripted.toml")
SENTENCE = ("The government proposes a joint inquiry into the border shooting, with observers from both sides "
            "and a published report within two months. ")


def play(months: int = 2, seed: int = 1):
    """A scripted council (rule-following stand-ins, no model, no network): (world, prompts) of its run."""
    cfg = load_config(SCRIPTED)
    raw = {"run": {**cfg["run"], "survey": False, "baseline": False, "seed": seed}, "seat": cfg["seats"]}
    tmp = tempfile.mkdtemp(prefix="engine19-prompts-")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            path = new_run(normalize_config(raw, "test"), runs_dir=tmp, name="run", months=months,
                           quiet=True, check=False)
        w = RunStore(path).load_checkpoint()[0]
        with open(os.path.join(path, "prompts.jsonl"), encoding="utf-8") as f:
            return w, [json.loads(line) for line in f]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class TO2MotionTextIsShownAsStored(unittest.TestCase):
    """Audit TO2: wherever a motion's or an amendment's text is shown, colleagues read the stored text, which is
    word-limited and ends in its cut marker. The old character slices showed 160, 200 and 140 characters, with no
    marker and mid-sentence, while the engine executes the whole stored text."""

    @classmethod
    def setUpClass(cls):
        cls.w, _ = play(months=2)
        cls.stored = words((SENTENCE * 7).strip(), MOTION_WORDS)   # 120 words and " [cut]", as the engine keeps them
        cls.motion = {"id": "M1", "proposer": "A", "type": "diplomacy", "subject": "status_talks", "value": "",
                      "summary": "talks on status with the Union", "text": cls.stored, "cosponsors": []}

    def _with_amendment(self, read):
        saved = self.w.const.amendments
        self.w.const.amendments = [{"text": self.stored, "month": 0}]
        try:
            return read()
        finally:
            self.w.const.amendments = saved

    def test_the_stored_text_is_word_limited_and_marked(self):
        self.assertTrue(self.stored.endswith(" [cut]"))
        self.assertEqual(len(self.stored.split()), MOTION_WORDS + 1)

    def test_the_transcript_shows_the_whole_stored_text(self):
        statements = [{"member": "A", "statement": "A short statement.", "principles_changed": False,
                       "communications": [], "invalid": [], "shared": []}]
        self.assertIn(f' - "{self.stored}"', prompts.transcript_v2(self.w, statements, [self.motion]))

    def test_the_current_motions_show_the_whole_stored_text(self):
        self.assertIn(f' - "{self.stored}"', decision_context.motion_block(self.w, "B", [self.motion]))

    def test_the_charter_in_the_canonical_state_shows_the_whole_amendment(self):
        text = self._with_amendment(lambda: decision_context.canonical_hard_state_v2(self.w, "decision"))
        self.assertIn(f"Amendment 1 (Month 1): {self.stored}", text)

    def test_the_v1_canonical_state_shows_the_whole_recent_clause(self):
        text = self._with_amendment(lambda: decision_context.canonical_hard_state(self.w, "decision"))
        self.assertIn(f"Recent clauses: {self.stored}.", text)

    def test_the_public_briefing_shows_the_whole_recent_amendment(self):
        text = self._with_amendment(lambda: briefing.government_block(self.w))
        self.assertIn(self.stored, text)


class TO3SettingsAreShownAsTheyAreSet(unittest.TestCase):
    """Audit TO3: CURRENT SETTINGS prints each numeric setting with the formatter the directives use. A delegate who
    repeats the shown value in an order must set the value in force: the tax of 0.185 was shown as 0.18."""

    def test_the_tax_shown_is_the_tax_in_force(self):
        w, _ = play(months=2)
        w.policy.tax = 0.185
        block = briefing.settings_block(w)
        shown = re.search(r"Treasury: tax (\S+),", block).group(1)
        self.assertEqual(float(shown), w.policy.tax, block[:200])
        self.assertEqual(fmt_value(w.policy.tax), shown)

    def test_every_numeric_setting_is_printed_with_the_directive_formatter(self):
        w, _ = play(months=2)
        w.policy.rate = 0.065
        w.policy.military = 0.0345
        w.mil.deploy["north"] = 0.333
        block = briefing.settings_block(w)
        self.assertIn("rate 0.065, ", block)
        self.assertIn("military 0.0345, ", block)
        self.assertIn("deploy_north 0.333, ", block)
        for name in ("tax", "military", "police", "welfare", "health_edu", "farm_support", "printing", "rate"):
            self.assertIn(f"{name} {fmt_value(getattr(w.policy, name))}", block, name)


class AG7ShortDispositionKeepsItsKeyLines(unittest.TestCase):
    """Audit AG7: a small seat's short disposition keeps the header, the agenda, the past, the base, the priorities
    and the fears. The trait sentences are the lines it drops first."""

    KEY = ("PRIVATE INTERNAL DISPOSITION", "YOUR POLITICAL AGENDA", "YOUR PAST:", "YOUR BASE:",
           "Above all, you want", "You especially fear")

    def test_the_short_form_keeps_the_key_lines_of_a_real_delegate(self):
        from karamaniya import agents
        w, _ = play(months=6)
        mid = w.members[0].id
        captured = {}
        original = decision_context.compose

        def spy(sections, budget):
            captured["sections"] = list(sections)
            return original(sections, budget)
        decision_context.compose = spy
        try:
            decision_context.build(w, mid, "decision", public_brief="", budget=60000)
        finally:
            decision_context.compose = original
        disposition = next(s for s in captured["sections"] if s.key == "disposition")
        short_lines = disposition.short.splitlines()
        self.assertLessEqual(len(short_lines), 9)
        full = agents.disposition_v2(w, mid).splitlines()
        self.assertTrue(any(line.startswith("Above all, you want") for line in full), "no priorities to keep")
        for line in full:
            if line.startswith(self.KEY):
                self.assertIn(line, short_lines)

    def test_the_trait_sentences_fill_what_is_left_in_the_order_written(self):
        traits = [f"You trait {i}." for i in range(6)]
        text = "\n".join(["PRIVATE INTERNAL DISPOSITION (only you see this)", "YOUR PAST: x", "YOUR BASE: y"]
                          + traits + ["Above all, you want a.", "You especially fear b.", "Looking back, c."])
        short = decision_context.disposition_short(text).splitlines()
        # Five kept lines leave room for four trait sentences in nine lines, taken in the order they were written.
        self.assertEqual(short, ["PRIVATE INTERNAL DISPOSITION (only you see this)", "YOUR PAST: x", "YOUR BASE: y",
                                 "You trait 0.", "You trait 1.", "You trait 2.", "You trait 3.",
                                 "Above all, you want a.", "You especially fear b."])


class TO10EmergencyMeasureLength(unittest.TestCase):
    """Audit TO10: a measure passed in a month is in force for that month and the next three (four months), and the
    motion detail that the delegates read beside the motion says so."""

    def test_the_detail_states_the_length_the_engine_keeps_the_measure(self):
        from karamaniya import dilemmas
        w, _ = play(months=2)
        dilemmas.set_emergency_measure(w, "curfew", True, "A", "")
        entry = w.institutions["emergency_measures"]["curfew"]
        self.assertEqual(entry["until"] - entry["since"] + 1, 4)
        motion = {"id": "M1", "proposer": "A", "type": "emergency_measure", "subject": "curfew", "value": "on",
                  "summary": "curfew", "text": "", "cosponsors": []}
        detail = decision_context.motion_block(w, "B", [motion])
        self.assertIn("lasts four months: this month and the next three", detail)
        self.assertNotIn("three months", detail)


class TO9EnglishUnionStaysEnglish(unittest.TestCase):
    """Audit TO9: with seeded names, the English word "union" stays a word of prose. The bloc is still translated
    where it is a name (Union, join_union, union_attack_soon) and every translation comes back to the canonical name."""

    @classmethod
    def setUpClass(cls):
        cls.names = naming.Names(naming.draw(1))
        cls.bloc = cls.names.names["Union"]

    def test_the_word_union_in_prose_is_not_translated(self):
        for text in ("the administrators' union", "your union, and its dues", "a labour union"):
            with self.subTest(text=text):
                self.assertEqual(self.names.out(text), text)

    def test_the_word_union_beside_a_region_is_not_translated_but_the_region_is(self):
        text = "the Kessel coal and steel union"
        self.assertEqual(self.names.out(text), f"the {self.names.names['Kessel']} coal and steel union")

    def test_the_bloc_and_its_identifiers_are_translated_and_come_back(self):
        for text, expected in (("the Union", f"the {self.bloc}"),
                               ("join_union", f"join_{self.bloc.lower()}"),
                               ("union_attack_soon", f"{self.bloc.lower()}_attack_soon")):
            with self.subTest(text=text):
                self.assertEqual(self.names.out(text), expected)
                self.assertEqual(self.names.back(expected), text)

    def test_a_quoted_union_is_a_json_identifier_and_is_translated(self):
        """The prompts and schemas name the bloc as a whole quoted key or value, as in "target": "public" | "union"."""
        text = '"target": "public" | "union", "union": {'
        out = self.names.out(text)
        self.assertEqual(out, f'"target": "public" | "{self.bloc.lower()}", "{self.bloc.lower()}": {{')
        self.assertEqual(self.names.back(out), text)
        # A schema is translated string by string, so an enum value or a key can arrive as the whole string.
        self.assertEqual(self.names.out("union"), self.bloc.lower())
        self.assertEqual(self.names.back(self.bloc.lower()), "union")

    def test_prose_round_trips(self):
        for text in ("the administrators' union", "the Union sent a note", "join_union"):
            with self.subTest(text=text):
                self.assertEqual(self.names.back(self.names.out(text)), text)


class TO8OneOutputFigurePerMonth(unittest.TestCase):
    """Audit TO8: the canonical block and the public briefing of one prompt print the same output for the same month.
    Both take it from briefing.published_output (one draw a month), not from the true figure and a noisy one."""

    def test_the_canonical_block_and_the_public_briefing_print_the_same_output(self):
        w, _ = play(months=6)
        for month in range(6, 18):
            w.month = month
            canon = decision_context.canonical_hard_state_v2(w, "decision")
            public = briefing.public_v2(w)
            with self.subTest(month=month):
                self.assertEqual(re.search(r"output (\d+) \(start = 100\)", canon).group(1),
                                 re.search(r"Output (\d+) \(start = 100\)", public).group(1))

    def test_before_the_first_month_the_output_is_the_founding_level(self):
        """Nothing has been measured yet, so the first prompt says 100, as it did before this fix."""
        from karamaniya.world import new_world
        w = new_world(1, 18, member_ids=("A", "B", "C", "D", "E"))
        self.assertEqual(briefing.published_index(w), 1.0)
        self.assertIn("output 100 (start = 100)", decision_context.canonical_hard_state_v2(w, "decision"))


class TO6SmallSeatsKeepTheirAnswerFormat(unittest.TestCase):
    """Audit TO6: a seat with a small budget keeps its instructions and answer format, cuts the canonical block
    last, and is told in one line which sections were shortened, cut or left out for length."""

    @classmethod
    def setUpClass(cls):
        cls.w, _ = play(months=6)
        cls.mid = cls.w.members[0].id

    def _decision_prompt(self, budget: int):
        """The Month 7 decision prompt of a delegate with two motions, as the scripted run would send it."""
        statements = [{"member": m.id, "statement": f"Delegate {m.id} proposes a measured response this month.",
                       "principles": "", "communications": [], "invalid": [], "shared": []}
                      for m in self.w.members]
        transcript = prompts.transcript_v2(self.w, statements, [])
        text_ = ("The council directs the Treasury to set the tax at twenty per cent of output for the next six "
                 "months, with a review in Month 9 and a report to the council on arrears and reserves each month.")
        motions = [{"id": f"M{i + 1}", "proposer": "A", "type": "set_policy", "subject": "tax", "value": "0.2",
                    "summary": "set tax to 0.2 for the budget", "text": text_, "cosponsors": []} for i in range(2)]
        return decision_context.build(self.w, self.mid, "decision", public_brief=briefing.public_v2(self.w),
                                      motions=motions, messages="", transcript=transcript,
                                      instructions="PHASE 2: FINAL VOTES AND ORDERS. Vote on every motion.",
                                      schema_text='{"votes": []}', budget=budget)

    def test_the_answer_format_survives_the_eight_thousand_token_seat(self):
        text, _ = self._decision_prompt(6000)      # Ollama at num_ctx 8192 (council.validation-tiny.toml)
        self.assertLessEqual(len(text), 6000)
        self.assertTrue(text.endswith("Vote on every motion.\nReply with this JSON:\n{\"votes\": []}"), text[-200:])

    def test_the_seat_is_told_in_one_line_what_was_left_out(self):
        text, meta = self._decision_prompt(6000)
        self.assertTrue(meta["trimmed"])
        notices = [line for line in text.split("\n") if line.startswith("Length limit on this prompt")]
        self.assertEqual(len(notices), 1, "a trimmed prompt must say what was trimmed, once")
        self.assertIn("left out: ", notices[0])
        self.assertIn("your political memory", notices[0])     # the least important section goes first

    def test_a_section_shortened_to_fit_is_named(self):
        sections = [decision_context.Section("memory", 6, "m" * 3000, short="m" * 50),
                    decision_context.Section("briefing", 3, "b" * 3000, short="B" * 300),
                    decision_context.Section("canonical", 0, "c" * 3000),
                    decision_context.Section("instructions", 0, "i" * 100)]
        text, _ = decision_context.compose(sections, 4000)
        notices = [line for line in text.split("\n") if line.startswith("Length limit on this prompt")]
        self.assertEqual(len(notices), 1)
        self.assertIn("shortened: your political memory, public briefing", notices[0])
        self.assertLessEqual(len(text), 4000)
        self.assertTrue(text.endswith("i" * 100))
        self.assertIn("c" * 3000, text, "the canonical block was cut before the sections that could go")

    def test_the_instructions_are_never_cut_even_when_the_canonical_block_must_be(self):
        sections = [decision_context.Section("canonical", 0, "c" * 3000),
                    decision_context.Section("instructions", 0, "i" * 300 + "\nReply with this JSON:\n{}")]
        text, trimmed = decision_context.compose(sections, 2000)
        self.assertLessEqual(len(text), 2000)
        self.assertTrue(text.endswith("i" * 300 + "\nReply with this JSON:\n{}"))
        self.assertIn("canonical:truncated", trimmed)
        self.assertNotIn("prompt:hard_cut", trimmed)

    def test_the_canonical_block_is_the_last_section_cut(self):
        sections = [decision_context.Section("canonical", 0, "C" * 2000),
                    decision_context.Section("briefing", 3, "b" * 3000),
                    decision_context.Section("instructions", 0, "i" * 100)]
        text, trimmed = decision_context.compose(sections, 3000)
        self.assertIn("C" * 2000, text)
        self.assertTrue(any(t.startswith("briefing") for t in trimmed))
        self.assertFalse(any(t.startswith("canonical") for t in trimmed))

    def test_a_prompt_that_fits_is_sent_as_joined_with_no_notice(self):
        sections = [decision_context.Section("a", 0, "first"), decision_context.Section("b", 5, "second"),
                    decision_context.Section("instructions", 0, "do it")]
        text, trimmed = decision_context.compose(sections, 1000)
        self.assertEqual(text, "first\n\nsecond\n\ndo it")
        self.assertEqual(trimmed, [])


if __name__ == "__main__":
    unittest.main()
