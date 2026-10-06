"""The opt-in token-saving features: each does what it says when on, and is checked when configured.

That a default run is unchanged by all of them is tests/test_prompt_freeze.py's job; this file is about
what they do once a run turns them on.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import actions, token_saving, tokens  # noqa: E402
from karamaniya.backends.base import Backend  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.council import Council  # noqa: E402
from karamaniya.runner import _seats  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

SCRIPTED = os.path.join(ROOT, "council.scripted.toml")


def raw_config(**run):
    return {"run": {"months": 6, **run}, "seat": [{"provider": "scripted", "label": f"s{i}"} for i in range(5)]}


class TheSettingsAreChecked(unittest.TestCase):
    def test_a_config_without_them_normalizes_as_before(self):
        cfg = normalize_config(raw_config())
        self.assertNotIn("tokens", cfg["run"])
        self.assertNotIn("foreign_cabinet_backend", cfg["run"])
        self.assertEqual(token_saving.settings(cfg["run"]), token_saving.DEFAULTS)

    def test_known_settings_are_kept_and_only_those(self):
        cfg = normalize_config(raw_config(tokens={"layout": "cache_friendly", "wakeups": "on_events"}))
        self.assertEqual(cfg["run"]["tokens"], {"layout": "cache_friendly", "wakeups": "on_events"})
        self.assertEqual(token_saving.settings(cfg["run"])["briefing"], "full")

    def test_mistakes_are_refused_by_name(self):
        for bad, needle in (({"layuot": "classic"}, "unknown"), ({"layout": "fancy"}, "layout"),
                            ({"max_quiet_months": 0}, "max_quiet_months"), ({"wakeups": True}, "wakeups")):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                normalize_config(raw_config(tokens=bad))
            self.assertIn(needle, str(caught.exception))

    def test_effort_by_phase_must_name_real_phases(self):
        raw = raw_config()
        raw["seat"][0]["effort_by_phase"] = {"decision": "high", "lunch": "low"}
        with self.assertRaises(ValueError) as caught:
            normalize_config(raw)
        self.assertIn("lunch", str(caught.exception))

    def test_a_foreign_backend_needs_a_provider(self):
        with self.assertRaises(ValueError):
            normalize_config(raw_config(foreign_cabinet_backend={"model": "x"}))
        cfg = normalize_config(raw_config(foreign_cabinet_backend={"provider": "scripted", "model": "env"}))
        self.assertEqual(cfg["run"]["foreign_cabinet_backend"]["label"], "env")

    def test_the_manifest_names_what_a_run_changed(self):
        cfg = normalize_config(raw_config(tokens={"layout": "cache_friendly"}))
        cfg["seats"][1]["effort_by_phase"] = {"decision": "high"}
        described = token_saving.describe(cfg)
        self.assertEqual(described["layout"], "cache_friendly")
        self.assertEqual(described["effort_by_phase"], {"s1": {"decision": "high"}})
        self.assertEqual(token_saving.describe(normalize_config(raw_config())), {})

    def test_two_runs_with_different_features_are_not_comparable(self):
        from karamaniya import manifest
        a = {"token_saving": {"layout": "cache_friendly"}}
        self.assertIn("token_saving", manifest.divergences(a, {}))
        self.assertNotIn("token_saving", manifest.divergences({}, {}))


class TheCompactSchemaHint(unittest.TestCase):
    def setUp(self):
        self.w = new_world(3, 6, member_ids=list("ABCDE"))
        self.schema = actions.decision_schema_v2(self.w, "A", ["M1", "M2"], False, 3)

    def test_every_field_and_allowed_value_survives(self):
        full, short = actions.example(self.schema), actions.compact_example(self.schema)
        import re
        names = set(re.findall(r'"([A-Za-z0-9_:]+)"', full))
        for name in names:
            with self.subTest(name=name):
                self.assertIn(name, short)

    def test_it_is_shorter(self):
        self.assertLess(len(actions.compact_example(self.schema)), 0.85 * len(actions.example(self.schema)))

    def test_auto_uses_it_only_where_the_connector_holds_the_answer_to_the_schema(self):
        class Enforcing(Backend):
            enforces_schema = True

        class Loose(Backend):
            pass
        council = Council.__new__(Council)
        council.tokens = {**token_saving.DEFAULTS, "schema_hint": "auto"}
        council.seats = {"A": type("S", (), {"backend": Enforcing({})})(), "B": type("S", (), {"backend": Loose({})})()}
        self.assertTrue(council._schema_text("A", self.schema).startswith(actions.COMPACT_KEY))
        self.assertEqual(council._schema_text("B", self.schema), actions.example(self.schema))
        council.tokens["schema_hint"] = "example"
        self.assertEqual(council._schema_text("A", self.schema), actions.example(self.schema))


class EffortByPhase(unittest.TestCase):
    def test_the_table_overrides_the_seat_effort_for_its_phases_only(self):
        backend = Backend({"effort_by_phase": {"decision": "high", "survey": "low"}})
        self.assertEqual(backend.phase_setting({"phase": "decision"}, "medium"), "high")
        self.assertEqual(backend.phase_setting({"phase": "session"}, "medium"), "medium")
        self.assertEqual(backend.phase_setting({}, "medium"), "medium")

    def test_an_openai_style_seat_sends_it_as_reasoning_effort(self):
        from karamaniya.backends.openai_compat import OpenAICompatBackend
        seat = OpenAICompatBackend({"provider": "llamacpp", "model": "m", "reasoning_effort": "medium",
                                    "effort_by_phase": {"decision": "high"}})
        decision = seat._body("s", "u", {"type": "object"}, None, seat._effort({"phase": "decision"}))
        session = seat._body("s", "u", {"type": "object"}, None, seat._effort({"phase": "session"}))
        self.assertEqual((decision["reasoning_effort"], session["reasoning_effort"]), ("high", "medium"))

    def test_ollama_reads_off_and_on(self):
        from karamaniya.backends.ollama import parse_think
        self.assertFalse(parse_think("off"))
        self.assertTrue(parse_think("high"))

    def test_the_call_record_says_which_effort_was_used(self):
        class Quick(Backend):
            def call(self, system, user, schema, context):
                from karamaniya.backends.base import CallResult
                return CallResult(data={"ok": True})
        res = Quick({"effort_by_phase": {"decision": "high"}}).complete("s", "u", {}, {"phase": "decision"})
        self.assertEqual(res.effort, "high")
        self.assertIn("effort", res.to_dict())


@unittest.skipUnless(importlib.util.find_spec("anthropic"), "the anthropic SDK is not installed")
class AnthropicCacheBreakpoints(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("KARAMANIYA_TEST_ANTHROPIC_KEY", "test-key")
        from karamaniya.backends.anthropic_api import AnthropicBackend
        self.backend = AnthropicBackend({"provider": "anthropic", "model": "claude-test",
                                         "api_key_env": "KARAMANIYA_TEST_ANTHROPIC_KEY"})

    def test_cache_points_become_breakpoints_and_the_text_is_unchanged(self):
        user = "shared part\n\nstanding part\n\nthe phase"
        points = [len("shared part\n\n"), len("shared part\n\nstanding part\n\n")]
        blocks = self.backend._user_content(user, {"prompt_meta": {"cache_points": points}})
        self.assertEqual("".join(b["text"] for b in blocks), user)
        self.assertEqual([("cache_control" in b) for b in blocks], [True, True, False])

    def test_a_classic_prompt_is_sent_as_one_string_as_before(self):
        self.assertEqual(self.backend._user_content("whole prompt", {"prompt_meta": {}}), "whole prompt")
        self.assertEqual(self.backend._user_content("whole prompt", {}), "whole prompt")


class CachedTokensArePricedOnlyWhenAsked(unittest.TestCase):
    def test_without_cache_prices_every_input_token_costs_price_in(self):
        b = Backend({"price_in": 3.0, "price_out": 15.0})
        self.assertAlmostEqual(b.cost(1_000_000, 0, cache_read=900_000), 3.0)

    def test_with_cache_prices_the_cached_part_is_cheaper(self):
        b = Backend({"price_in": 3.0, "price_out": 15.0, "price_cache_read": 0.3, "price_cache_write": 3.75})
        self.assertAlmostEqual(b.cost(1_000_000, 0, cache_read=900_000), 0.1 * 3.0 + 0.9 * 0.3)
        self.assertAlmostEqual(b.cost(1_000_000, 0, cache_write=1_000_000), 3.75)


class BriefingSections(unittest.TestCase):
    BRIEF = ("PUBLIC BRIEFING - Month 7\nDeclared principles: ...\n\n"
             "LAST MONTH'S COUNCIL DECISIONS\n- M1 passed\n\n"
             "THE ECONOMY (published estimates)\nInflation 4%\nUnemployment 9%\n\n"
             "THE PEOPLE\nApproval 41%")

    def test_the_sections_and_what_can_be_asked_for(self):
        ids = [sid for sid, _, _ in token_saving.briefing_sections(self.BRIEF)]
        self.assertEqual(ids, ["header", "last_months_council_decisions", "the_economy", "the_people"])
        self.assertEqual(token_saving.requestable(self.BRIEF), ["the_economy", "the_people"])

    def test_headlines_for_everyone_and_full_text_for_who_asked(self):
        shared, own = token_saving.briefing_for(self.BRIEF, ["the_economy"])
        self.assertIn("M1 passed", shared)                     # the council's own record, always in full
        self.assertIn("[the_economy] THE ECONOMY", shared)     # a headline for everything else
        self.assertNotIn("Unemployment 9%", shared)
        self.assertIn("Unemployment 9%", own)
        self.assertNotIn("Approval 41%", own)
        self.assertEqual(token_saving.briefing_for(self.BRIEF, [])[1], "")

    def test_a_request_for_something_that_does_not_exist_is_dropped(self):
        self.assertEqual(token_saving.read_requests({"read_next_month": ["the_people", "gossip", "the_people"]},
                                                    ["the_economy", "the_people"]), ["the_people"])


class Hooked(ScriptedBackend):
    """The scripted stand-in, plus whatever extra fields a test wants its decisions to carry."""

    def __init__(self, cfg, extra=None):
        super().__init__(cfg)
        self.extra = extra

    def call(self, system, user, schema, context):
        res = super().call(system, user, schema, context)
        if self.extra and context.get("phase") == "decision" and isinstance(res.data, dict):
            res.data.update(self.extra(context))
        return res


def scripted_council(tmp: str, tokens_table: dict, extra=None, months: int = 8, **run):
    cfg = load_config(SCRIPTED)
    cfg = {**cfg, "run": {**cfg["run"], "tokens": tokens_table, **run}}
    cfg = normalize_config({"run": cfg["run"], "seat": cfg["seats"]})
    mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
    cfg["mapping"] = mapping
    w = new_world(cfg["run"]["seed"], months, member_ids=list(mapping),
                  founding_scenario=cfg["run"].get("founding_scenario", "random"),
                  founding_severity=cfg["run"].get("founding_severity", "default"))
    seats = _seats(cfg, mapping)
    for seat in seats.values():
        seat.backend = Hooked(seat.cfg, extra)
    council = Council(w, seats, cfg["run"], RunStore(os.path.join(tmp, "r")))
    council.store.save_config(cfg)
    # As the runner does: the ledger reads the system prompt from the run folder.
    (council.store.path / "system_prompt.txt").write_text(council.system, encoding="utf-8")
    council.survey()
    council.diagnose_founding()
    council.form_government()
    return council, w


def calls_by_month(store_dir: str) -> dict:
    out = {}
    with open(os.path.join(store_dir, "log.jsonl"), encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("type") == "call":
                out.setdefault(rec["month"], []).append(rec["phase"])
    return out


class QuietMonths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-quiet-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_months(self, extra, n=6):
        council, w = scripted_council(self.tmp, {"wakeups": "on_events", "max_quiet_months": 2}, extra)
        records = [council.run_month() for _ in range(n)]
        return council, w, records

    def test_a_council_that_stands_by_skips_months_and_calls_no_delegate(self):
        council, w, records = self.run_months(lambda ctx: {"stand_by": {"months": "2", "wake_if": []}})
        quiet = [r["month"] for r in records if r.get("quiet_month")]
        self.assertTrue(quiet, "no month was quiet although every delegate stood by")
        by_month = calls_by_month(council.store.path)
        for month in quiet:
            self.assertNotIn(month, by_month, f"month {month} was quiet but models were called")
        self.assertGreater(w.month, records[0]["month"] + len(records) - 1, "the world did not advance")
        self.assertEqual(int(w.counters["quiet_months_total"]), len(quiet))

    def test_never_more_quiet_months_in_a_row_than_allowed(self):
        _, _, records = self.run_months(lambda ctx: {"stand_by": {"months": "2", "wake_if": []}}, n=7)
        run = longest = 0
        for r in records:
            run = run + 1 if r.get("quiet_month") else 0
            longest = max(longest, run)
        self.assertLessEqual(longest, 2)

    def test_a_wake_condition_that_holds_keeps_the_council_meeting(self):
        always = {"metric": "unemployment", "operator": ">=", "value": 0}
        _, _, records = self.run_months(lambda ctx: {"stand_by": {"months": "2", "wake_if": [always]}}, n=4)
        self.assertFalse([r for r in records if r.get("quiet_month")])

    def test_one_delegate_that_will_not_stand_by_is_enough(self):
        def extra(ctx):
            return {"stand_by": {"months": "0" if ctx.get("member") == "C" else "2", "wake_if": []}}
        _, _, records = self.run_months(extra, n=4)
        self.assertFalse([r for r in records if r.get("quiet_month")])

    def test_the_next_briefing_says_the_council_did_not_meet(self):
        council, _, records = self.run_months(lambda ctx: {"stand_by": {"months": "2", "wake_if": []}})
        quiet = [r["month"] for r in records if r.get("quiet_month")]
        self.assertTrue(quiet)
        with open(os.path.join(council.store.path, "prompts.jsonl"), encoding="utf-8") as f:
            after = [json.loads(line) for line in f]
        nxt = [p for p in after if p["month"] == quiet[0] + 1 and p["phase"] == "session"]
        if nxt:                         # the next month met (it may itself be quiet)
            self.assertIn("The council did not meet", nxt[0]["prompt"])


class BriefingOnDemand(unittest.TestCase):
    def test_only_the_delegate_that_asked_gets_the_full_section(self):
        tmp = tempfile.mkdtemp(prefix="karamaniya-brief-")
        self.addCleanup(shutil.rmtree, tmp, True)

        def extra(ctx):
            return {"read_next_month": ["the_economy"] if ctx.get("member") == "B" else []}
        council, _ = scripted_council(tmp, {"briefing": "on_demand"}, extra)
        for _ in range(3):              # the first month's briefing has no economy section to ask for
            council.run_month()
        with open(os.path.join(council.store.path, "prompts.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(line) for line in f]
        month = max(r["month"] for r in rows if r["phase"] == "session")
        sessions = {r["member"]: r["prompt"] for r in rows if r["phase"] == "session" and r["month"] == month}
        self.assertIn("THE BRIEFING SECTIONS YOU ASKED FOR", sessions["B"])
        self.assertIn("THE ECONOMY", sessions["B"].split("THE BRIEFING SECTIONS YOU ASKED FOR")[1])
        for other in "ACDE":
            if other in sessions:
                self.assertNotIn("THE BRIEFING SECTIONS YOU ASKED FOR", sessions[other])
                self.assertIn("[the_economy]", sessions[other])


class AFixedForeignCabinetModel(unittest.TestCase):
    def test_both_cabinets_use_it_and_no_council_seat(self):
        tmp = tempfile.mkdtemp(prefix="karamaniya-foreign-")
        self.addCleanup(shutil.rmtree, tmp, True)
        council, _ = scripted_council(tmp, {}, foreign_cabinets=True,
                                      foreign_cabinet_backend={"provider": "scripted", "label": "environment"})
        labels = {seat.label for seat in council.seats.values()}
        self.assertEqual({s.label for s in council.foreign_seats.values()}, {"environment"})
        self.assertFalse(labels & {"environment"})
        self.assertIsNot(council.foreign_seats["veleria"].backend, council.foreign_seats["dorsania"].backend)
        council.run_month()
        with open(os.path.join(council.store.path, "log.jsonl"), encoding="utf-8") as f:
            foreign = [json.loads(line) for line in f if '"foreign_call"' in line]
        self.assertTrue(foreign)
        self.assertEqual({r["seat"] for r in foreign}, {"environment"})


class TheCacheSimulator(unittest.TestCase):
    def call(self, user, model="m", month=0, phase="decision", system="S" * 5000):
        return {"provider": "p", "model": model, "seat": model, "who": model, "month": month, "phase": phase,
                "system_id": "council", "system": system, "user": user}

    def test_a_repeated_prefix_is_counted_once_it_is_long_enough(self):
        first = self.call("A" * 8000 + "x")
        second = self.call("A" * 8000 + "y")
        sim = tokens.simulate_cache([first, second], "month")
        self.assertEqual(sim["reused_chars"], 5000 + 8000)

    def test_different_models_share_nothing(self):
        sim = tokens.simulate_cache([self.call("A" * 8000), self.call("A" * 8000, model="other")], "month")
        self.assertEqual(sim["reused_chars"], 0)
        pooled = tokens.simulate_cache([self.call("A" * 8000), self.call("A" * 8000, model="other")], "month",
                                       same_model=True)
        self.assertGreater(pooled["reused_chars"], 0)

    def test_the_window_bounds_the_cache_lifetime(self):
        calls = [self.call("A" * 8000, month=0), self.call("A" * 8000, month=1)]
        self.assertEqual(tokens.simulate_cache(calls, "month")["reused_chars"], 0)
        self.assertGreater(tokens.simulate_cache(calls, "run")["reused_chars"], 0)

    def test_a_short_prefix_is_not_cached(self):
        calls = [self.call("A" * 100, system=""), self.call("A" * 100, system="")]
        self.assertEqual(tokens.simulate_cache(calls, "month")["reused_chars"], 0)

    def test_the_ledger_reads_a_real_run_and_pairs_every_call(self):
        tmp = tempfile.mkdtemp(prefix="karamaniya-ledger-")
        self.addCleanup(shutil.rmtree, tmp, True)
        council, _ = scripted_council(tmp, {})
        council.run_month()
        report = tokens.ledger(council.store.path)
        self.assertGreater(report["calls"], 0)
        self.assertTrue(all(c["user"] for c in tokens.load_calls(council.store.path)), "a call lost its prompt")
        self.assertIn("system", report["by_section"])
        self.assertIn("Token ledger", tokens.render(report))


if __name__ == "__main__":
    unittest.main()
