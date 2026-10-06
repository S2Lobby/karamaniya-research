"""The prompt budget is a hard contract, and no seat can abort a run by exceeding it.

Found by scanning archived runs: two Cline seats died at Month 1 with "this prompt is too long
for a Windows command line", and those seats were lost for the rest of the run. The council trims
prompts to a budget the connector advertises, but the trim could not always reach it.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import decision_context  # noqa: E402
from karamaniya.backends import cline_cli  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


class Section:
    """The shape compose() expects.

    Priority convention, from decision_context: 0 is the most important and is never trimmed or
    dropped; a higher number is less important and is shed first. Instructions and canonical
    facts are 0, memory is 6.
    """

    def __init__(self, key, text, priority=5, short=None):
        self.key, self.text, self.priority = key, text, priority
        self.short = short if short is not None else text


class ComposeRespectsTheBudget(unittest.TestCase):
    def test_a_prompt_that_already_fits_is_untouched(self):
        sections = [Section("a", "short text", 5)]
        text, trimmed = decision_context.compose(sections, 30000)
        self.assertEqual(text, "short text")
        self.assertEqual(trimmed, [])

    def test_an_oversized_prompt_is_brought_within_budget(self):
        sections = [Section("big", "x" * 40000, 5)]
        text, trimmed = decision_context.compose(sections, 5000)
        self.assertLessEqual(len(text), 5000)
        self.assertTrue(trimmed)

    def test_the_budget_holds_when_one_section_cannot_absorb_the_cut(self):
        """The recorded failure: the largest section was too small to take the whole overshoot."""
        sections = [Section("a", "x" * 2000, 5),
                    Section("b", "y" * 300, 6),
                    Section("c", "z" * 300, 7)]
        text, _ = decision_context.compose(sections, 900)
        self.assertLessEqual(len(text), 900, "the trim left the prompt over budget")

    def test_the_budget_holds_across_a_wide_range_of_sizes(self):
        for budget in (500, 1000, 2000, 8000, 20000):
            sections = [Section(f"s{i}", "w" * (300 + i * 700), priority=i % 9)
                        for i in range(12)]
            with self.subTest(budget=budget):
                text, _ = decision_context.compose(sections, budget)
                self.assertLessEqual(len(text), budget)

    def test_short_forms_are_preferred_before_any_section_is_dropped(self):
        sections = [Section("big", "x" * 4000, 5, short="brief"),
                    Section("keep", "kept", 9)]
        text, trimmed = decision_context.compose(sections, 200)
        self.assertIn("big:short", trimmed)
        self.assertNotIn("keep:dropped", trimmed)

    def test_high_priority_sections_survive_longer_than_low_priority_ones(self):
        # Priority 0 is the most important by this module's convention; 6 is the least.
        sections = [Section("vital", "v" * 900, 0), Section("filler", "f" * 4000, 6)]
        text, trimmed = decision_context.compose(sections, 1000)
        self.assertIn("v", text, "the most important section was dropped")
        self.assertTrue(any(t.startswith("filler") for t in trimmed))
        self.assertNotIn("vital:dropped", trimmed)

    def test_a_budget_too_small_for_anything_still_returns_something_within_it(self):
        sections = [Section("a", "x" * 5000, 5)]
        text, trimmed = decision_context.compose(sections, 60)
        self.assertLessEqual(len(text), 60)
        self.assertTrue(trimmed)

    def test_a_realistic_budget_never_returns_an_empty_prompt(self):
        """An empty prompt would be useless, so the ladder must not empty a reasonable one."""
        sections = [Section("instructions", "i" * 2000, 0),
                    Section("motions", "m" * 4000, 1),
                    Section("memory", "x" * 9000, 6)]
        for budget in (4000, 6000, 12000, 20000):
            with self.subTest(budget=budget):
                text, _ = decision_context.compose(sections, budget)
                self.assertLessEqual(len(text), budget)
                self.assertTrue(text.strip(), "a realistic budget produced an empty prompt")

    def test_trimming_is_reported_not_silent(self):
        sections = [Section("big", "x" * 9000, 5)]
        _, trimmed = decision_context.compose(sections, 1000)
        self.assertTrue(trimmed, "the prompt was cut without recording that it was")


# A minimal answer Cline's parser accepts, so the connector reaches its post-processing.
VALID_ANSWER = '{"type": "agent_event", "event": {"type": "done", "text": "{}"}}\n'


class TheConnectorCannotAbortTheRun(unittest.TestCase):
    def _backend(self):
        cfg = {"provider": "cline_cli", "cli_command": ["cline"], "timeout": 30,
               "model": "some-model"}
        return cline_cli.ClineCLIBackend(cfg)

    def test_the_advertised_budget_is_the_room_that_actually_exists(self):
        """It must never advertise space the command line does not have."""
        backend = self._backend()
        for system_chars in (2000, 8000, 20000):
            with self.subTest(system_chars=system_chars):
                budget = backend.prompt_budget(system_chars)
                self.assertGreater(budget, 0)
                # The system prompt and the whole user prompt must fit under the cap together,
                # leaving the flag overhead room inside it.
                self.assertLess(system_chars + budget, cline_cli.MAX_ARGS)

    def test_a_pathologically_long_system_prompt_reports_no_room_rather_than_a_floor(self):
        backend = self._backend()
        self.assertEqual(backend.prompt_budget(cline_cli.MAX_ARGS + 5000), 0)

    def test_max_args_is_below_the_real_windows_limit(self):
        # Windows caps a command line at 32,767; the backend keeps a margin below it.
        self.assertLess(cline_cli.MAX_ARGS, 32767)

    def test_an_over_budget_prompt_is_trimmed_rather_than_fatal(self):
        from karamaniya.backends import cli_common
        backend = self._backend()
        seen = {}

        def fake_run(cmd, input_text, timeout, cwd=None, on_stdout_line=None):
            seen["cmd"] = cmd
            seen["length"] = sum(len(a) + 3 for a in cmd)
            return 0, VALID_ANSWER, ""

        original = cli_common.run
        cli_common.run = fake_run
        try:
            context = {}
            backend.call("s" * 6000, "u" * 40000, {}, context)
        finally:
            cli_common.run = original
        self.assertLessEqual(seen["length"], cline_cli.MAX_ARGS)
        self.assertTrue(context.get("connector_trimmed"), "the trim was not reported")

    def test_a_prompt_inside_the_budget_is_not_marked_as_trimmed(self):
        from karamaniya.backends import cli_common
        backend = self._backend()
        original = cli_common.run
        cli_common.run = lambda *a, **k: (0, VALID_ANSWER, "")
        try:
            context = {}
            backend.call("system", "a short prompt", {}, context)
        finally:
            cli_common.run = original
        self.assertNotIn("connector_trimmed", context)

    def test_no_room_for_a_prompt_at_all_is_still_an_error(self):
        from karamaniya.backends import cli_common
        from karamaniya.backends.base import FatalError
        backend = self._backend()
        backend.cmd = ["cline", "-x" * (cline_cli.MAX_ARGS + 1000)]   # flags eat the whole line
        original = cli_common.run
        cli_common.run = lambda *a, **k: (0, VALID_ANSWER, "")
        try:
            with self.assertRaises(FatalError):
                backend.call("system", "prompt", {}, {})
        finally:
            cli_common.run = original


class EndToEndBudget(unittest.TestCase):
    def test_a_real_decision_prompt_respects_a_cline_sized_budget(self):
        """Build an actual delegate prompt at a budget a Cline seat would advertise."""
        from karamaniya.council import Council
        from karamaniya.runner import _seats
        from karamaniya.storage import RunStore
        from karamaniya.config import load_config
        import tempfile, shutil
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg = load_config(os.path.join(root, "council.scripted.toml"))
        mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
        cfg = {**cfg, "mapping": mapping}
        tmp = tempfile.mkdtemp(prefix="karamaniya-budget-")
        try:
            w = new_world(cfg["run"]["seed"], 3, member_ids=list(mapping))
            council = Council(w, _seats(cfg, mapping), cfg["run"], RunStore(os.path.join(tmp, "r")))
            for budget in (4000, 9000, 20000):
                with self.subTest(budget=budget):
                    text, meta = decision_context.build(
                        w, "A", "decision", public_brief="", budget=budget)
                    self.assertLessEqual(len(text), budget)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
