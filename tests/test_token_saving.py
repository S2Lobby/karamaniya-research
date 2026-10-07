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

from karamaniya import actions, intelligence, token_saving, tokens  # noqa: E402
from karamaniya.backends.base import Backend  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.council import Council  # noqa: E402
from karamaniya.runner import _seats, preflight, seats_to_check  # noqa: E402
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

    def test_messages_from_abroad_always_arrive_in_full(self):
        brief = self.BRIEF + "\n\nFOREIGN MESSAGES\n- Dorsania proposes restoring grain trade."
        shared, _ = token_saving.briefing_for(brief, [])
        self.assertIn("Dorsania proposes restoring grain trade.", shared)
        self.assertNotIn("foreign_messages", token_saving.requestable(brief))

    def test_answers_a_seat_could_send_without_a_schema_do_not_crash_the_month(self):
        """Connectors that do not enforce the schema can return any JSON; nothing in it may raise."""
        options = ["the_economy", "the_people"]
        for raw in ([{"section": "the_economy"}, ["x"], 3, None, "the_people"], "the_people", 7, {"a": 1}):
            with self.subTest(read_next_month=raw):
                self.assertEqual(token_saving.read_requests({"read_next_month": raw}, options),
                                 ["the_people"] if isinstance(raw, list) else [])
        tokens_on = {**token_saving.DEFAULTS, "wakeups": "on_events"}
        for wake in (1, True, "unemployment", {"metric": "unemployment"}, [1, None, ["x"]],
                     [{"metric": "unemployment", "operator": ">=", "value": "nan"}]):
            with self.subTest(wake_if=wake):
                plan = token_saving.read_stand_by({"stand_by": {"months": "2", "wake_if": wake}}, tokens_on)
                self.assertEqual(plan, {"months": 2, "wake_if": []})
        plan = token_saving.read_stand_by({"stand_by": {"months": "2", "wake_if": [
            {"metric": "unemployment", "operator": ">=", "value": 12}]}}, tokens_on)
        self.assertEqual(len(plan["wake_if"]), 1)


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

    def run_months(self, extra, n=6, foreign_cabinets=False):
        # Without foreign cabinets: the scripted Dorsania proposes trade every month, and a message
        # from abroad always brings the council together (test_a_message_from_abroad_...).
        council, w = scripted_council(self.tmp, {"wakeups": "on_events", "max_quiet_months": 2}, extra,
                                      foreign_cabinets=foreign_cabinets)
        records = [council.run_month() for _ in range(n)]
        return council, w, records

    def test_a_message_from_abroad_every_month_keeps_the_council_meeting(self):
        _, _, records = self.run_months(lambda ctx: {"stand_by": {"months": "2", "wake_if": []}}, n=5,
                                        foreign_cabinets=True)
        self.assertFalse([r for r in records if r.get("quiet_month")])

    def test_a_quiet_month_leaves_the_notebooks_and_their_dates_as_written(self):
        council, w = scripted_council(self.tmp, {"wakeups": "on_events", "max_quiet_months": 2},
                                      lambda ctx: {"stand_by": {"months": "2", "wake_if": []}},
                                      foreign_cabinets=False)
        for _ in range(8):
            before = {m.id: (m.notebook, (m.agent_state or {}).get("notes_month")) for m in w.active_members()}
            record = council.run_month()
            if record.get("quiet_month"):
                after = {m.id: (m.notebook, (m.agent_state or {}).get("notes_month")) for m in w.active_members()}
                self.assertEqual(after, before)
                self.assertTrue(any(n for n, _ in before.values()), "the delegates had written notes")
                self.assertEqual(record["memory_mismatches"], [], "old notes were checked again")
                return
        self.fail("no month was quiet")

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


class WhatAlwaysWakesTheCouncil(unittest.TestCase):
    """The quiet-month rule on its own: every delegate stands by, then one reason to meet at a time."""
    TOKENS = {**token_saving.DEFAULTS, "wakeups": "on_events"}

    def setUp(self):
        self.w = new_world(1, 12, member_ids=list("ABCDE"))
        c = self.w.const
        self.w.month = next(m for m in range(2, 12) if m not in (c.election_month, c.handover_month))
        self.w.last_events, self.w.dilemmas["active"] = [], []
        self.w.dip.inbox, self.w.dip.private_inbox = [], []
        intelligence.state(self.w)["deliveries"] = []
        for m in self.w.members:
            m.agent_state = {**(m.agent_state or {}), "stand_by": {"months_left": 2, "wake_if": []}}

    def due(self, carried=(), pending_dms=False, last_record=None):
        return token_saving.quiet_month_due(self.w, [m.id for m in self.w.members], list(carried), pending_dms,
                                            last_record or {"coups": []}, self.TOKENS)

    def test_with_nothing_happening_the_month_is_quiet(self):
        self.assertTrue(self.due())
        self.assertIsNone(token_saving.quiet_month_due(self.w, [m.id for m in self.w.members], [], False, None,
                                                       token_saving.DEFAULTS), "off unless a run turns it on")

    def test_a_new_issue_on_the_agenda(self):
        self.w.dilemmas["active"].append({"id": "I5-storm", "kind": "storm", "month": self.w.month})
        self.assertIsNone(self.due())

    def test_an_issue_the_council_already_met_over_does_not(self):
        self.w.dilemmas["active"].append({"id": "I4-storm", "kind": "storm", "month": self.w.month - 1})
        self.assertTrue(self.due())

    def test_a_major_public_event_last_month(self):
        self.w.last_events = [{"kind": "protest", "text": "People were killed.", "public": True, "importance": 3}]
        self.assertIsNone(self.due())

    def test_minor_or_unpublished_events_do_not(self):
        self.w.last_events = [{"kind": "issue_resolved", "public": True, "importance": 1},
                              {"kind": "plot", "public": False, "importance": 3}]
        self.assertTrue(self.due())

    def test_a_message_from_abroad_or_a_private_dispatch(self):
        self.w.dip.inbox = [{"month": self.w.month - 1, "from": "Dorsania", "text": "Dorsania proposes grain trade."}]
        self.assertIsNone(self.due())
        self.w.dip.inbox, self.w.dip.private_inbox = [], [{"to": "B", "text": "A private word."}]
        self.assertIsNone(self.due())

    def test_an_answer_to_an_information_request_due_this_month(self):
        intelligence.state(self.w)["deliveries"].append(
            {"to": "B", "deliver_month": self.w.month, "phase_ready": "session", "text": "The figures you asked for."})
        self.assertIsNone(self.due())
        intelligence.state(self.w)["deliveries"][0]["deliver_month"] = self.w.month + 1
        self.assertTrue(self.due(), "an answer due next month waits for next month")

    def test_deferred_motions_private_messages_coups_and_war(self):
        self.assertIsNone(self.due(carried=[{"id": "D1"}]))
        self.assertIsNone(self.due(pending_dms=True))
        self.assertIsNone(self.due(last_record={"coups": [{"by": "A"}]}))
        self.w.dip.war = True
        self.assertIsNone(self.due())

    def test_a_delegate_whose_stand_by_ran_out(self):
        self.w.members[2].agent_state["stand_by"]["months_left"] = 0
        self.assertIsNone(self.due())


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

    def test_the_seat_check_tests_it_too(self):
        """It is called every month: a broken one, unchecked, would leave both cabinets idle all run."""
        def cfg(backend):
            return normalize_config({"run": {"months": 2, "foreign_cabinet_backend": backend},
                                     "seat": [{"provider": "scripted", "label": f"s{i}"} for i in range(5)]})
        checked = seats_to_check(cfg({"provider": "scripted", "label": "environment"}))
        self.assertEqual([s["label"] for s in checked][-1], "environment (foreign cabinets)")
        broken = preflight(cfg({"provider": "ollama", "model": "missing", "base_url": "http://127.0.0.1:9",
                                "label": "environment", "timeout": 2}))
        self.assertEqual([b["label"] for b in broken], ["environment (foreign cabinets)"])
        off = normalize_config({"run": {"months": 2, "foreign_cabinets": False,
                                        "foreign_cabinet_backend": {"provider": "scripted"}},
                                "seat": [{"provider": "scripted", "label": f"s{i}"} for i in range(5)]})
        self.assertEqual(len(seats_to_check(off)), 5)


class CallIds(unittest.TestCase):
    def test_a_resumed_council_goes_on_numbering_its_calls(self):
        tmp = tempfile.mkdtemp(prefix="karamaniya-ids-")
        self.addCleanup(shutil.rmtree, tmp, True)
        council, _ = scripted_council(tmp, {})
        state = json.loads(json.dumps(council.state()))        # as the checkpoint stores it
        self.assertGreater(state["call_seq"], 0, "the setup made calls")
        resumed, _ = scripted_council(tempfile.mkdtemp(dir=tmp), {})
        resumed.load_state(state)
        self.assertEqual(resumed._next_call_id(), f"{resumed.w.month}.{state['call_seq'] + 1}")

    def test_a_repeated_id_pairs_only_with_its_own_call(self):
        """Runs resumed before the counter was saved can repeat an id across the setup and month 0."""
        tmp = tempfile.mkdtemp(prefix="karamaniya-ids-")
        self.addCleanup(shutil.rmtree, tmp, True)
        run = write_run(os.path.join(tmp, "r"), [
            {"month": 0, "phase": "survey", "member": "A", "seat": "a", "chars": 100},
            {"month": 0, "phase": "session", "member": "B", "seat": "b", "chars": 900}])
        for name in ("log.jsonl", "prompts.jsonl"):            # give both calls the same id
            path = os.path.join(run, name)
            with open(path, encoding="utf-8") as f:
                rows = [json.loads(line) for line in f]
            for row in rows:
                row["call_id"] = "0.1"
            with open(path, "w", encoding="utf-8") as f:
                f.write("".join(json.dumps(row) + "\n" for row in rows))
        calls = {c["phase"]: c for c in tokens.load_calls(run)}
        self.assertEqual((len(calls["survey"]["user"]), len(calls["session"]["user"])), (100, 900))


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


def write_run(path: str, calls: list, months: int | None = None, system: str = "S" * 400) -> str:
    """A minimal run folder: a log and a prompt file that pair by call_id, and optionally a manifest."""
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "log.jsonl"), "w", encoding="utf-8") as log, \
            open(os.path.join(path, "prompts.jsonl"), "w", encoding="utf-8") as prompts:
        for i, c in enumerate(calls):
            call_id = f"{c['month']}.{i}"
            log.write(json.dumps({"type": "call", "call_id": call_id, "month": c["month"], "phase": c["phase"],
                                  "member": c["member"], "seat": c["seat"], "provider": c.get("provider", "ollama"),
                                  "model": c.get("model", "m"), "raw": "x" * c.get("out", 40),
                                  "input_tokens": c.get("tokens_in", 0), "output_tokens": c.get("tokens_out", 0)}) + "\n")
            prompts.write(json.dumps({"call_id": call_id, "month": c["month"], "phase": c["phase"],
                                      "member": c["member"], "prompt": "u" * c["chars"]}) + "\n")
    with open(os.path.join(path, "system_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(system)
    if months is not None:
        with open(os.path.join(path, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"months_simulated": months}, f)
    return path


class TheLedgerPerSeatAndPerMonth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-ledger-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        calls = [{"month": 0, "phase": "survey", "member": m, "seat": s, "chars": 1600}
                 for m, s in (("A", "a"), ("B", "b"))]
        for month in (0, 1):
            for m, s in (("A", "a"), ("B", "b")):
                for phase in ("session", "decision"):
                    calls.append({"month": month, "phase": phase, "member": m, "seat": s, "chars": 3600,
                                  # seat a reports its tokens (one per five characters), seat b does not
                                  "tokens_in": 800 if s == "a" else 0, "tokens_out": 10 if s == "a" else 0})
        self.run_dir = write_run(os.path.join(self.tmp, "r1"), calls, months=2)

    def test_a_month_costs_what_its_calls_cost_and_the_setup_is_counted_apart(self):
        report = tokens.ledger(self.run_dir)
        self.assertEqual((report["months"], report["setup"]["calls"], report["monthly"]["calls"]), (2, 2, 8))
        self.assertEqual(report["monthly"]["input_tokens_estimated"], tokens.estimate(8 * (400 + 3600)))
        self.assertIn("Per simulated month (2 months; the 2 setup calls are counted apart)", tokens.render(report))

    def test_each_seat_compares_the_estimate_with_what_the_provider_counted(self):
        seats = tokens.ledger(self.run_dir)["by_seat"]
        a, b = seats["a"], seats["b"]
        self.assertEqual((a["measured_calls"], a["measured_input_tokens"]), (4, 3200))
        self.assertEqual(a["measured_input_chars"] / a["measured_input_tokens"], 5.0)
        self.assertEqual((b["measured_calls"], b["measured_input_tokens"]), (0, 0))
        self.assertIn("5.00", tokens.render(tokens.ledger(self.run_dir)))

    def test_without_a_manifest_the_months_are_the_months_the_calls_name(self):
        os.remove(os.path.join(self.run_dir, "manifest.json"))
        self.assertEqual(tokens.ledger(self.run_dir)["months"], 2)

    def test_several_runs_combine_into_a_rate_and_a_projection(self):
        other = write_run(os.path.join(self.tmp, "r2"), [
            {"month": m, "phase": "decision", "member": "A", "seat": "a", "chars": 3600} for m in range(4)], months=4)
        summary = tokens.combine([tokens.ledger(self.run_dir), tokens.ledger(other)])
        self.assertEqual((summary["runs"], summary["months"]), (2, 6))
        self.assertEqual(summary["per_month"]["calls"], round((8 + 4) / 6, 2))
        self.assertEqual(summary["setup_per_run"]["calls"], 2)            # only the run that had a setup
        text = tokens.render_combined(summary, months=10)
        self.assertIn("a 10-month run at this rate: ~22 calls", text)


class TheReplayReadsTheServerLog(unittest.TestCase):
    """tools/cache_replay.py counts what the server evaluated from its log, not from the API's count."""
    LOG = "\n".join([
        "slot   operator(): id  0 | task 0 | new prompt, n_ctx_slot = 16384, n_keep = 4, task.n_tokens = 7397",
        "slot   operator(): id  0 | task 0 | cached n_tokens = 0, memory_seq_rm [0, end)",
        "slot print_timing: id  0 | task 0 | prompt eval time =    1144.65 ms /  7397 tokens (    0.15 ms per token)",
        "[GIN] 2026/10/07 - 21:18:29 | 200 |    6.9048551s |       127.0.0.1 | POST     \"/api/chat\"",
        "slot   operator(): id  0 | task 10 | new prompt, n_ctx_slot = 16384, n_keep = 4, task.n_tokens = 7397",
        "slot   operator(): id  0 | task 10 | cached n_tokens = 7393, memory_seq_rm [7393, end)",
        "slot print_timing: id  0 | task 10 | prompt eval time =      41.39 ms /     4 tokens (   10.35 ms per token)",
        "slot print_timing: id  0 | task 10 |        eval time =       0.00 ms /     1 tokens"])

    def test_prompt_size_and_tokens_evaluated_per_request(self):
        spec = importlib.util.spec_from_file_location("cache_replay", os.path.join(ROOT, "tools", "cache_replay.py"))
        replay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(replay)
        self.assertEqual(replay.server_tasks(self.LOG), [(7397, 7397), (7397, 4)])


if __name__ == "__main__":
    unittest.main()
