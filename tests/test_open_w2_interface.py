"""Wave A W2: the interface for `policy` motions and `open_act` motions, and the cabinets' open act.

The arm is an explicit `harness` argument, default "menu". Under "menu" every schema and prompt is engine 29
byte for byte; the hashes below were taken from commit 6fb526b before this module existed, so a default run's
schemas and prompts must still hash to them. Under "language" the policy motion is offered; under "open" the
open act is offered to delegates and cabinets too.

Tabling refusals are in words, each with a registered code. The duplicate keys follow
deliberation._program_measure_key (canonical items, order-independent), and the same functions are the payload
W3's execution_key will hash. No model is called here.

    python -m unittest tests.test_open_w2_interface
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, decision_context, deliberation, errors, foreign, prompts  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

# The default arm's sha256 of the schema (JSON, sort_keys) and of the prompt text, taken after Wave B's
# deliberate default changes (B9's stance field and sentence) and before Wave A's arm text. The W2 change
# must add nothing under "menu"; the engine-29 values are in the Wave B changelog entry.
BASE_HASHES = {
    "system_prompt": "abfbef593df546708d91d4d7e936639fe82a6d04e0cea0c883d8638dec63dc60",
    "motion_schema": "c0bc55d4675fc576a63c61c5d54845d49b08562b6808e4a56095dc473b33f54f",
    "session_schema_v2_A": "ed101655b9939a94931caa8e92c03fa6775b9587a361c82ff654e009a92e368d",
    "session_schema_v2_B": "a44d71801258b2ab1743770b83dc7a4ae0fd2f22b0b9d7f9286097b3de4b37fd",
    "decision_schema_v2_B": "37b6fbe3a38504f1497d733c38f891cb39a8d49bdfb054ab3c042efb27099132",
    "revision_schema_A": "67a793d9a7f0d1d841b26338819c2719dfc0a470bd62593410a7725117592119",
    "opening_instructions_A": "43b0bea94e3278d59d230e2399bd0219b2cdf8424be3d71375104dbdc4626049",
    "revision_instructions": "71ec4e711f3ec8ea7b5e067440fe1128bbfb827904a1417d8b941ac15adf54a5",
    "decision_instructions": "5491c0f770b2bd444bb3ccc6f159740d40a9d774772543d5f8acf519fb488972",
    "cabinet_schema_veleria": "89d88305a2b286a87b3ae79553afc997a4b6baeef3a407ae1c51b7f2421ebdd5",
    "cabinet_schema_all": "3ab00f2b2cf94ba2abaae189155db8029470372b859d8e05caca86b5e50fddf5",
    "cabinet_prompt_veleria": "4cc69735ec37d20cde53597d9738e09ec9b639d2fe03ede132b394df265c243c",
    "cabinet_prompt_dorsania_hawk": "e7a6dcbf762bd38b81881fe3d4926b94a72b3837b4758cc259819a3d7af3454a",
}


def world() -> object:
    """A five-member world with the five offices filled, as the default arm has them."""
    w = new_world(11)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def digest(value) -> str:
    if isinstance(value, str):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def default_hashes(w) -> dict:
    return {
        "system_prompt": digest(prompts.system_prompt(
            "simulation", True, 5, 3, w.const.charter_election_month, w.const.personal_mandates, "default",
            hostile_neighbours=True, power_rule=True, founding_story=True, stakes=True, word_limits=True,
            political_agendas=False, mandate="default", secret_ballot=(w.ballot == "secret"),
            offices_by_letter=False)),
        "motion_schema": digest(actions.motion_schema(w)),
        "session_schema_v2_A": digest(actions.session_schema_v2(w, "A", 3)),
        "session_schema_v2_B": digest(actions.session_schema_v2(w, "B", 3)),
        "decision_schema_v2_B": digest(actions.decision_schema_v2(w, "B", ["M1", "M2"], dm_left=3)),
        "revision_schema_A": digest(actions.revision_schema(
            w, "A", [{"id": "M1", "proposer": "A", "type": "program", "action": {"measures": []}}], 3)),
        "opening_instructions_A": digest(prompts.opening_instructions_v2(
            w, "A", 3, ["A", "B", "C", "D", "E"], 4)),
        "revision_instructions": digest(prompts.revision_instructions(w, "A", 3, [])),
        "decision_instructions": digest(prompts.decision_instructions_v2(w, "A", [], 3, False, False)),
        "cabinet_schema_veleria": digest(foreign.cabinet_schema("veleria")),
        "cabinet_schema_all": digest(foreign.cabinet_schema(None)),
        "cabinet_prompt_veleria": digest(foreign.cabinet_system_prompt("veleria", "")),
        "cabinet_prompt_dorsania_hawk": digest(foreign.cabinet_system_prompt("dorsania", "hawk")),
    }


def policy(items, text="A policy the council is deciding.") -> dict:
    return {"type": "policy", "subject": "", "value": "", "text": text,
            "action": {"items": items}, "proposer": "A"}


def item(**fields) -> dict:
    return {"months": 6, **fields}


def open_act(text="The treasury pays the grain suppliers and reopens the coastal road.", **action) -> dict:
    return {"type": "open_act", "subject": "", "value": "", "text": text,
            "action": {"office": "treasury", **action}, "proposer": "A"}


def refusal(w, motion, tabled=(), proposer="A", harness="language"):
    rejection, _warning = deliberation.check(w, motion, list(tabled), proposer, harness=harness)
    return rejection


class TheDefaultArmIsUnchangedByWaveA(unittest.TestCase):
    """Nothing a menu run reads or is held to moved when Wave A's arms are added (Wave B's defaults stand)."""

    def test_the_schemas_and_prompts_hash_to_the_base(self):
        self.assertEqual(default_hashes(world()), BASE_HASHES)

    def test_the_new_motion_types_are_not_offered(self):
        self.assertEqual(actions.offered_motion_types(), ())
        kinds = actions.motion_schema(world())["properties"]["type"]["enum"]
        self.assertNotIn("policy", kinds)
        self.assertNotIn("open_act", kinds)

    def test_an_explicit_menu_arm_is_the_same(self):
        w = world()
        self.assertEqual(digest(actions.motion_schema(w, harness="menu")),
                         digest(actions.motion_schema(w)))
        self.assertEqual(digest(foreign.cabinet_schema("veleria", harness="menu")),
                         digest(foreign.cabinet_schema("veleria")))
        self.assertEqual(prompts.system_prompt("simulation", harness="menu"),
                         prompts.system_prompt("simulation"))


class TheLanguageArmOffersPolicy(unittest.TestCase):
    def test_the_motion_type_and_shape(self):
        w = world()
        kinds = actions.motion_schema(w, harness="language")["properties"]["type"]["enum"]
        self.assertIn("policy", kinds)
        self.assertNotIn("open_act", kinds)
        action = actions.motion_schema(w, harness="language")["properties"]["action"]
        items = action["properties"]["items"]
        self.assertEqual((items["minItems"], items["maxItems"]), (1, actions.POLICY_MAX_ITEMS))
        fields = items["items"]["properties"]
        self.assertEqual(fields["instrument"]["enum"], list(actions.POLICY_INSTRUMENTS))
        self.assertEqual(fields["start_in"]["minimum"], 0)
        self.assertEqual(fields["start_in"]["maximum"], 6)
        self.assertEqual(fields["months"]["minimum"], 1)
        self.assertEqual(fields["months"]["maximum"], 24)
        self.assertEqual(fields["mandate"]["enum"], list(actions.POLICY_MANDATES))
        self.assertIn("condition", fields)
        self.assertTrue(any("cut:military" == value for value in fields["funding"]["enum"]))

    def test_a_model_answer_is_read_into_the_motion(self):
        w = world()
        # A model may write the item list at the top level rather than under action, as media fields were
        # sometimes written; it is read into the action once, without guessing any item's contents.
        raw = {"type": "policy", "text": "Ration food while supplies are short.",
               "items": [{"instrument": "set_lever", "lever": "rationing", "value": "on", "months": 4}]}
        motion = actions.normalize_motion_v2(w, raw)
        self.assertEqual(motion["action"]["items"][0]["instrument"], "set_lever")
        self.assertIsNone(refusal(w, motion, harness="language"))

    def test_the_summary_reads_in_world_words(self):
        w = world()
        motion = policy([item(instrument="set_lever", lever="rationing", value="on", months=6),
                         item(instrument="transfer", amount=12, target="class:farmers", funding="reserves",
                              months=3)])
        self.assertIsNone(refusal(w, motion, harness="language"))
        text = actions.motion_summary(w, motion)
        self.assertIn("set rationing to on", text)
        self.assertIn("transfer 12M a month to class:farmers", text)
        self.assertNotRegex(text, r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+")

    def test_the_prompt_states_every_limit(self):
        text = prompts.system_prompt("simulation", harness="language")
        for phrase in ("one to four items", "start_in is 0 to 6", "months is 1 to 24",
                       "reserves, borrowing, or cut:", "A spending instrument needs an amount and funding",
                       "food_ratio", "reserves_after_payment", "class:farmers", "anti_corruption"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        self.assertNotIn("open_act", text)

    def test_a_policy_is_tabled_and_canonicalised(self):
        w = world()
        motion = policy([
            {"instrument": "set_lever", "lever": "rationing", "value": "on", "months": 6,
             "condition": {"metric": "food_ratio", "operator": "<=", "value": 0.8}},
            {"instrument": "transfer", "amount": 12, "target": "class:farmers", "funding": "reserves",
             "start_in": 1, "months": 3},
            {"instrument": "public_works", "amount": 8, "target": "Kessel Valley", "funding": "borrowing",
             "months": 12},
            {"instrument": "commission", "mandate": "anti_corruption", "amount": 2, "funding": "cut:military",
             "months": 24},
        ])
        self.assertIsNone(refusal(w, motion, harness="language"))
        items = motion["items"]
        self.assertEqual([entry["instrument"] for entry in items],
                         ["set_lever", "transfer", "public_works", "commission"])
        self.assertEqual(items[0]["lever"], "rationing")
        self.assertIs(items[0]["value"], True)   # the canonical reading of "on", as a programme measure stores it
        self.assertEqual(items[0]["condition"], {"metric": "food_ratio", "operator": "<=", "value": 0.8})
        self.assertEqual(items[1]["target"], "class:farmers")
        self.assertEqual(items[2]["target"], "kessel")
        self.assertEqual(items[3]["mandate"], "anti_corruption")
        self.assertEqual(actions.policy_items_of(w, motion), items)


class TheOpenArmOffersOpenActs(unittest.TestCase):
    def test_the_motion_type_and_shape(self):
        w = world()
        kinds = actions.motion_schema(w, harness="open")["properties"]["type"]["enum"]
        self.assertIn("policy", kinds)
        self.assertIn("open_act", kinds)
        action = actions.motion_schema(w, harness="open")["properties"]["action"]
        self.assertEqual(action["properties"]["office"]["enum"], list(actions.OFFICES))
        self.assertIn("budget", action["properties"])
        self.assertIn("reserves", action["properties"]["funding"]["enum"])

    def test_the_prompt_states_every_limit(self):
        text = prompts.system_prompt("simulation", harness="open")
        for phrase in ("open_act", "at most one a delegate a month", "at most 60 words",
                       "head, treasury, interior, army or navy", "action.budget", "months is 1 to 24",
                       "reserves, borrowing or cut:"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_an_open_act_is_tabled_and_canonicalised(self):
        w = world()
        motion = open_act("The treasury pays the grain suppliers and reopens the coastal road.",
                          budget={"amount": 5, "months": 3}, funding="borrowing")
        self.assertIsNone(refusal(w, motion, harness="open"))
        act = motion["act"]
        self.assertEqual(act["office"], "treasury")
        self.assertEqual(act["budget"], {"amount": 5.0, "months": 3})
        self.assertEqual(act["funding"], "borrowing")
        self.assertEqual(act["text"], motion["text"])

    def test_a_model_answer_is_read_into_the_motion(self):
        w = world()
        raw = {"type": "open_act", "text": "The navy escorts merchant shipping through the northern approaches.",
               "office": "navy", "budget": {"amount": 2, "months": 2}, "funding": "reserves"}
        motion = actions.normalize_motion_v2(w, raw)
        self.assertEqual(motion["action"]["office"], "navy")
        self.assertIsNone(refusal(w, motion, harness="open"))
        self.assertEqual(motion["act"]["office"], "navy")
        self.assertEqual(motion["act"]["budget"], {"amount": 2.0, "months": 2})

    def test_an_amendment_refreshes_the_canonical_act(self):
        w = world()
        motion = open_act("The treasury pays the grain suppliers.")
        motion["id"], motion["proposer"] = "M1", "A"
        self.assertIsNone(refusal(w, motion, harness="open"))
        notes = deliberation.apply_revisions(
            w, "A", {"amend": [{"motion_id": "M1", "value": "", "text": "The navy escorts merchant shipping."}]},
            [motion], [motion], harness="open")
        self.assertEqual(notes["amended"], ["M1"])
        self.assertEqual(motion["act"]["text"], "The navy escorts merchant shipping.")
        self.assertEqual(actions.open_act_of(w, motion)["text"], "The navy escorts merchant shipping.")

    def test_one_open_act_a_delegate_a_month(self):
        w = world()
        first = open_act()
        first["id"] = "M1"
        self.assertIsNone(refusal(w, first, harness="open"))
        second = open_act("The navy escorts merchant shipping through the northern approaches.")
        rejection = refusal(w, second, tabled=[first], proposer="A", harness="open")
        self.assertEqual(rejection["reason_code"], "OPEN_ACT_LIMIT")
        # Another delegate may still table its own.
        self.assertIsNone(refusal(w, second, tabled=[first], proposer="B", harness="open"))


class RefusalsAreInWordsWithRegisteredCodes(unittest.TestCase):
    def check(self, motion, code, harness="language"):
        rejection = refusal(world(), motion, harness=harness)
        self.assertIsNotNone(rejection)
        self.assertEqual(rejection["reason_code"], code)
        self.assertTrue(errors.is_registered(code), code)
        self.assertTrue(rejection["explanation"].strip())
        # The code stays in the record; the words a delegate is shown carry none.
        self.assertNotRegex(rejection["explanation"], r": [A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+ - ")
        self.assertNotIn("schema", rejection["explanation"].lower())
        self.assertNotIn("engine", rejection["explanation"].lower())
        return rejection

    def test_policy_refusals(self):
        cases = {
            "POLICY_UNKNOWN_INSTRUMENT": policy([item(instrument="subsidy", months=3)]),
            "POLICY_BAD_TARGET": policy([item(instrument="transfer", amount=4, target="the moon",
                                              funding="reserves", months=3)]),
            "POLICY_BAD_CONDITION": policy([item(instrument="set_lever", lever="rationing", value="on",
                                                 condition={"metric": "moonlight", "operator": "<=",
                                                            "value": 1})]),
            "POLICY_BAD_SCHEDULE": policy([item(instrument="set_lever", lever="rationing", value="on",
                                                start_in=9, months=3)]),
            "POLICY_UNFUNDED": policy([item(instrument="transfer", amount=4, target="class:farmers",
                                            months=3)]),
            "POLICY_LIMIT": policy([]),
        }
        for code, motion in cases.items():
            with self.subTest(code=code):
                self.check(motion, code)

    def test_too_many_items_is_a_limit(self):
        items = [item(instrument="set_lever", lever="rationing", value="on", months=3) for _ in range(5)]
        rejection = self.check(policy(items), "POLICY_LIMIT")
        self.assertIn("1 to 4", rejection["explanation"])
        self.assertIn("5", rejection["explanation"])

    def test_an_unknown_lever_is_refused_with_the_levers_named(self):
        rejection = self.check(policy([item(instrument="set_lever", lever="moon_phase", value="full",
                                            months=3)]), "POLICY_BAD_TARGET")
        self.assertIn("moon_phase", rejection["explanation"])

    def test_public_works_needs_one_region(self):
        self.check(policy([item(instrument="public_works", amount=3, target="class:farmers",
                                funding="reserves", months=3)]), "POLICY_BAD_TARGET")

    def test_open_act_refusals(self):
        cases = {
            "OPEN_ACT_TOO_LONG": open_act(" ".join(["word"] * 61)),
            "OPEN_ACT_UNKNOWN_OFFICE": open_act("The government issues a statement.",
                                                office="king"),
            "OPEN_ACT_BAD_BUDGET": open_act("The government issues a statement.",
                                            budget={"amount": 1, "months": 30}),
            "OPEN_ACT_UNFUNDED": open_act("The government issues a statement.",
                                          budget={"amount": 1, "months": 3}),
        }
        for code, motion in cases.items():
            with self.subTest(code=code):
                self.check(motion, code, harness="open")

    def test_the_open_act_limits_are_stated_where_they_are_enforced(self):
        text = prompts.system_prompt("simulation", harness="open")
        self.assertIn("at most 60 words", text)
        self.assertIn("at most one a delegate a month", text)


class DuplicateKeysFollowTheProgrammeKey(unittest.TestCase):
    def test_reordered_policy_items_are_one_motion(self):
        w = world()
        a = policy([item(instrument="set_lever", lever="rationing", value="on", months=6),
                    item(instrument="transfer", amount=4, target="class:farmers", funding="reserves", months=3)])
        a["id"] = "M1"
        b = policy([item(instrument="transfer", amount=4, target="class:farmers", funding="reserves", months=3),
                    item(instrument="set_lever", lever="rationing", value="on", months=6)])
        b["proposer"] = "B"
        self.assertEqual(deliberation._policy_measure_key(w, a), deliberation._policy_measure_key(w, b))
        self.assertIsNone(refusal(w, a, harness="language"))
        # The same proposer re-tabling the same policy, in another order, is the same motion.
        again = {**b, "proposer": "A"}
        self.assertEqual(refusal(w, again, tabled=[a], harness="language")["reason_code"], "SAME_MOTION_TABLED")
        # Another delegate tabling it becomes a co-sponsor, exactly as for engine 29's own types.
        rejection, warning = deliberation.check(w, b, [a], "B", harness="language")
        self.assertIsNone(rejection)
        self.assertEqual(warning["code"], "COSPONSOR")

    def test_a_different_policy_is_a_different_motion(self):
        w = world()
        a = policy([item(instrument="set_lever", lever="rationing", value="on", months=6)])
        b = policy([item(instrument="set_lever", lever="rationing", value="off", months=6)])
        b["proposer"] = "B"
        self.assertNotEqual(deliberation._policy_measure_key(w, a), deliberation._policy_measure_key(w, b))
        rejection, _warning = deliberation.check(w, b, [a], "B", harness="language")
        self.assertIsNone(rejection)

    def test_the_open_act_key_is_its_words_office_and_money(self):
        w = world()
        a = open_act("Reopen the coastal road.", budget={"amount": 5, "months": 3}, funding="borrowing")
        b = open_act("Reopen the coastal road.", budget={"amount": 5, "months": 3}, funding="borrowing")
        c = open_act("Reopen the coastal road.", budget={"amount": 6, "months": 3}, funding="borrowing")
        self.assertEqual(deliberation._open_act_key(w, a), deliberation._open_act_key(w, b))
        self.assertNotEqual(deliberation._open_act_key(w, a), deliberation._open_act_key(w, c))
        a["id"] = "M1"
        self.assertIsNone(refusal(w, a, harness="open"))
        self.assertEqual(refusal(w, b, tabled=[a], harness="open")["reason_code"], "SAME_MOTION_TABLED")
        # A different act by the same delegate is the one-a-month limit; another delegate may table it.
        self.assertEqual(refusal(w, c, tabled=[a], proposer="A", harness="open")["reason_code"],
                         "OPEN_ACT_LIMIT")
        self.assertIsNone(refusal(w, c, tabled=[a], proposer="B", harness="open"))


class TheCabinetOpenActIsAnOpenArmShape(unittest.TestCase):
    def schema_targets(self, actor, harness="menu"):
        return foreign.cabinet_schema(actor, harness=harness)["properties"]["actions"]["items"] \
            ["properties"]["target"]["enum"]

    def test_the_default_cabinet_has_no_open_act(self):
        kinds = foreign.cabinet_schema("veleria")["properties"]["actions"]["items"]["properties"]["type"]["enum"]
        self.assertNotIn("open_act", kinds)
        self.assertNotIn("karamaniya", self.schema_targets("veleria"))
        self.assertNotIn("open act", foreign.cabinet_system_prompt("veleria").lower())

    def test_the_open_arm_offers_it_with_its_targets(self):
        for actor, own in (("veleria", "veleria"), ("dorsania", "dorsania")):
            with self.subTest(actor=actor):
                kinds = foreign.cabinet_schema(actor, harness="open")["properties"]["actions"]["items"] \
                    ["properties"]["type"]["enum"]
                self.assertIn("open_act", kinds)
                targets = self.schema_targets(actor, harness="open")
                self.assertIn("karamaniya", targets)
                self.assertIn("kessel", targets)
                self.assertIn(own, targets)
                other = "dorsania" if own == "veleria" else "veleria"
                self.assertNotIn(other, targets)
                self.assertIn("text", foreign.cabinet_schema(actor, harness="open")["properties"]["actions"]
                              ["items"]["properties"])

    def test_the_prompt_sentence_states_its_limits(self):
        text = foreign.cabinet_system_prompt("veleria", harness="open")
        self.assertIn(foreign.OPEN_ACT_SENTENCE, text)
        for phrase in ("at most 60 words", "Karamaniya", "one of its regions", "your own country"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, foreign.OPEN_ACT_SENTENCE)


class ThePromptBudgetKeepsTheNewParagraph(unittest.TestCase):
    """The paragraphs ride in the system prompt, which every call carries whole; the per-seat budget trims the
    other sections and its own notice names them, so the new text is never cut silently."""

    def test_the_paragraphs_are_in_the_system_prompt(self):
        text = prompts.system_prompt("simulation", harness="open")
        self.assertIn(prompts.POLICY_PARAGRAPH, text)
        self.assertIn(prompts.OPEN_ACT_PARAGRAPH, text)

    def test_a_small_budget_names_what_it_shortened(self):
        section = decision_context.Section
        sections = [section("canonical", 0, "x" * 400),
                    section("briefing", 3, "y" * 900),
                    section(decision_context.NOTICE_KEY, 0, ""),
                    section(decision_context.RESERVED_KEY, 0, prompts.OPEN_ACT_PARAGRAPH)]
        text, trimmed = decision_context.compose(sections, len(prompts.OPEN_ACT_PARAGRAPH) + 200)
        self.assertIn("open_act", text)
        self.assertTrue(any(item.startswith("briefing") for item in trimmed), trimmed)
        self.assertNotIn("prompt:over_budget", trimmed)


if __name__ == "__main__":
    unittest.main()
