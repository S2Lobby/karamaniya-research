"""World engine 30, Wave A W1: the effect bus (karamaniya/effects.py).

One registry of bounded channels through which every new consequence passes. The tests pin the measured caps
from A0-recon section 5, the refusals the bus owes a caller in words, the monthly step (where it applies, ages
and clips), the class target the society step now reads, the income and hunger modifiers, the month record, and
the rule that a world with nothing scheduled behaves exactly as it did before the bus existed.

    python -m unittest tests.test_engine30_effects
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import dilemmas, effects, engine, errors, public_mood  # noqa: E402
from karamaniya.world import CLASSES, IDENTITIES, OFFICES, World, new_world, rng_for  # noqa: E402

SOURCE = {"kind": "policy", "actor": "A", "motion": "M-1", "month": 0}

# A0-recon section 5 / the lead's decision 4: the measured per-entry cap, and the per-month sum cap, which is
# the same figure for every channel.
CAPS = {
    "approval": 0.03, "grievance": 0.03, "fear": 0.03, "indep": 0.03, "repression": 0.03,
    "income": 0.02, "hunger": 0.02,
    "damage": 0.02, "logistics": 0.05,
    "admin_capacity": 0.02, "confidence": 0.01,
    "corruption": 0.02,
    "relations": 0.03, "league_trust": 0.05,
    "morale": 0.02,
}


def one(channel, target, value, months=1, **extra):
    return {"channel": channel, "target": target, "value": value, "months": months, **extra}


def accepted(w, items, source=None):
    good, problems = effects.validate(w, items, source or SOURCE)
    if problems:
        raise AssertionError(problems)
    return good


def schedule_one(w, channel, target, value, months=1, source=None):
    good = accepted(w, [one(channel, target, value, months)], source)
    return effects.schedule(w, good, source or SOURCE)


def farmers(w):
    return [p for p in w.k_pops() if p.cls == "farmers"]


def of_ident(w, ident):
    return [p for p in w.k_pops() if p.ident == ident]


def of_class(w, cls):
    return [p for p in w.k_pops() if p.cls == cls]


class RegistryTests(unittest.TestCase):
    def test_caps_match_the_measured_table(self):
        self.assertEqual(set(effects.CHANNELS), set(CAPS))
        for channel, cap in CAPS.items():
            with self.subTest(channel=channel):
                spec = effects.CHANNELS[channel]
                self.assertAlmostEqual(spec["cap"], cap)
                self.assertAlmostEqual(spec["month_cap"], cap)

    def test_every_channel_documents_what_it_reaches_and_why_it_is_capped(self):
        for channel, spec in effects.CHANNELS.items():
            with self.subTest(channel=channel):
                for key in ("state", "targets", "unit", "cap", "month_cap", "max_months", "why"):
                    self.assertIn(key, spec)
                self.assertTrue(spec["why"].strip())
                self.assertEqual(spec["max_months"], effects.MAX_MONTHS)
                self.assertGreater(spec["max_months"], 0)

    def test_society_channels_are_the_five_public_reactions_and_the_two_money_channels(self):
        self.assertEqual(effects.SOCIETY_CHANNELS,
                         ("approval", "grievance", "fear", "indep", "repression"))
        self.assertEqual(effects.MONEY_CHANNELS, ("income", "hunger"))


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.w = new_world(1)

    def problems(self, items, source=None):
        good, problems = effects.validate(self.w, items, source or SOURCE)
        self.assertEqual(good, [])
        return problems

    def codes(self, items, source=None):
        return [p["code"] for p in self.problems(items, source)]

    def test_an_unknown_channel_is_refused(self):
        problems = self.problems([one("charisma", "*", 0.01)])
        self.assertEqual(problems[0]["code"], "EFFECT_UNKNOWN_CHANNEL")
        self.assertIn("charisma", problems[0]["problem"])

    def test_every_refusal_code_is_registered(self):
        cases = [
            [one("charisma", "*", 0.01)],
            [one("damage", "nowhere", 0.01)],
            [one("approval", "class:peasants", 0.01)],
            [one("approval", "ident:martian", 0.01)],
            [one("morale", "airforce", 0.01)],
            [one("corruption", "treasury", 0.03)],
            [one("relations", "veleria", 0.03), one("relations", "veleria", 0.03)],
            [one("damage", "aster", 0.01, 30)],
            [one("damage", "aster", 0.01, 0)],
            [one("damage", "aster", "a lot")],
            [one("damage", "aster", 0.01, 1, decay=2.0)],
        ]
        for items in cases:
            for problem in self.problems(items):
                with self.subTest(problem=problem):
                    self.assertTrue(errors.is_registered(problem["code"]))
                    self.assertNotIn(problem["code"], problem["problem"])

    def test_an_unknown_target_is_refused_for_each_kind_of_channel(self):
        cases = [
            ("approval", "class:peasants"), ("approval", "ident:martian"), ("approval", "atlantis"),
            ("damage", "*"), ("damage", "veleria_capital"), ("logistics", "class:farmers"),
            ("corruption", "chancellor"), ("admin_capacity", "chancellor"),
            ("morale", "airforce"), ("relations", "mars"), ("league_trust", "veleria"),
            ("confidence", "aster"), ("income", "ident:martian"), ("hunger", "class:peasants"),
        ]
        for channel, target in cases:
            with self.subTest(channel=channel, target=target):
                self.assertEqual(self.codes([one(channel, target, 0.01)]), ["EFFECT_UNKNOWN_TARGET"])

    def test_the_class_target_is_accepted_for_every_class_and_society_channel(self):
        for channel in effects.SOCIETY_CHANNELS + effects.MONEY_CHANNELS:
            for cls in CLASSES:
                with self.subTest(channel=channel, cls=cls):
                    goods, problems = effects.validate(self.w, [one(channel, f"class:{cls}", 0.01)], SOURCE)
                    self.assertEqual(problems, [])
                    self.assertEqual(goods[0]["target"], f"class:{cls}")

    def test_region_identity_and_everyone_targets_are_accepted(self):
        for target in ("*", "aster", "ident:vell"):
            with self.subTest(target=target):
                goods, problems = effects.validate(self.w, [one("approval", target, 0.01)], SOURCE)
                self.assertEqual(problems, [])
        for actor in ("veleria", "dorsania"):
            goods, problems = effects.validate(self.w, [one("relations", actor, 0.01)], SOURCE)
            self.assertEqual(problems, [])
        for office in OFFICES:
            goods, problems = effects.validate(self.w, [one("corruption", office, 0.01)], SOURCE)
            self.assertEqual(problems, [])
        for force in ("army", "navy", "police"):
            goods, problems = effects.validate(self.w, [one("morale", force, 0.01)], SOURCE)
            self.assertEqual(problems, [])

    def test_a_value_over_the_per_entry_cap_is_refused_in_words(self):
        problems = self.problems([one("approval", "*", 0.031)])
        self.assertEqual(problems[0]["code"], "EFFECT_OVER_CAP")
        self.assertIn("0.03", problems[0]["problem"])
        problems = self.problems([one("confidence", "*", -0.02)])
        self.assertEqual(problems[0]["code"], "EFFECT_OVER_CAP")
        self.assertIn("0.01", problems[0]["problem"])

    def test_values_at_the_cap_are_accepted(self):
        for channel, cap in CAPS.items():
            target = {"damage": "aster", "logistics": "aster", "corruption": "treasury",
                      "relations": "veleria", "league_trust": "*", "morale": "army",
                      "confidence": "*", "admin_capacity": "*"}.get(channel, "*")
            with self.subTest(channel=channel):
                goods, problems = effects.validate(self.w, [one(channel, target, cap)], SOURCE)
                self.assertEqual(problems, [])

    def test_a_list_that_sums_over_the_month_cap_on_one_target_is_refused(self):
        problems = self.problems([one("grievance", "aster", 0.02), one("grievance", "aster", 0.02)])
        self.assertEqual(problems[0]["code"], "EFFECT_MONTH_CAP")
        self.assertIn("0.03", problems[0]["problem"])
        # Different targets do not share a cap.
        goods, problems = effects.validate(
            self.w, [one("grievance", "aster", 0.02), one("grievance", "kessel", 0.02)], SOURCE)
        self.assertEqual(problems, [])

    def test_a_society_effect_that_would_stack_on_a_live_one_is_refused(self):
        schedule_one(self.w, "approval", "class:farmers", 0.02, months=3)
        # A second 0.02 in a month the first is still running would sum to 0.04, over the 0.03 cap.
        problems = self.problems([one("approval", "class:farmers", 0.02, months=1)])
        self.assertEqual(problems[0]["code"], "EFFECT_MONTH_CAP")
        # Once two months have passed the first has decayed out and the same effect is allowed.
        self.w.month = 2
        self.assertEqual(self.problems([one("approval", "class:farmers", 0.02, months=1)]), [])

    def test_too_many_months_is_refused(self):
        problems = self.problems([one("damage", "aster", 0.01, effects.MAX_MONTHS + 1)])
        self.assertEqual(problems[0]["code"], "EFFECT_TOO_MANY_MONTHS")
        self.assertIn(str(effects.MAX_MONTHS), problems[0]["problem"])

    def test_a_duration_that_is_not_a_whole_month_is_refused(self):
        for months in (0, -1, 1.5, "three"):
            with self.subTest(months=months):
                self.assertEqual(self.codes([one("damage", "aster", 0.01, months)]), ["EFFECT_BAD_MONTHS"])

    def test_a_value_that_is_not_a_usable_number_is_refused(self):
        for value in (0, 0.0, "much", None, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.assertEqual(self.codes([one("damage", "aster", value)]), ["EFFECT_BAD_VALUE"])

    def test_an_unknown_source_is_refused(self):
        problems = self.problems([one("damage", "aster", 0.01)],
                                 source={"kind": "whim", "actor": "A", "motion": None, "month": 0})
        self.assertEqual(problems[0]["code"], "EFFECT_UNKNOWN_SOURCE")

    def test_validate_does_not_change_the_world(self):
        before = repr(self.w.to_dict())
        effects.validate(self.w, [one("damage", "aster", 0.02, 3)], SOURCE)
        self.assertEqual(repr(self.w.to_dict()), before)

    def test_accepted_effects_are_normalized(self):
        goods, problems = effects.validate(
            self.w, [one("approval", "aster", "0.01", "2", reason="x" * 400)], SOURCE)
        self.assertEqual(problems, [])
        entry = goods[0]
        self.assertIsInstance(entry["value"], float)
        self.assertEqual(entry["months"], 2)
        self.assertEqual(entry["decay"], 1.0)
        self.assertEqual(len(entry["reason"]), 160)
        self.assertNotIn("source", entry)


class StepTests(unittest.TestCase):
    def setUp(self):
        self.w = new_world(1)

    def advance(self):
        self.w.month += 1
        effects.step(self.w)

    def test_a_region_stock_effect_applies_and_expires(self):
        schedule_one(self.w, "damage", "aster", 0.02, months=3)
        effects.step(self.w)
        self.assertAlmostEqual(self.w.region("aster").damage, 0.02)
        self.advance()
        self.assertAlmostEqual(self.w.region("aster").damage, 0.04)
        self.advance()
        self.assertAlmostEqual(self.w.region("aster").damage, 0.06)
        self.assertEqual(effects.state(self.w), [])
        self.advance()
        self.assertAlmostEqual(self.w.region("aster").damage, 0.06)
        self.assertEqual(effects.applied(self.w), [])

    def test_decay_shrinks_what_each_month_applies(self):
        schedule_one(self.w, "damage", "aster", 0.02, months=3, decay=0.5)
        effects.step(self.w)
        self.assertAlmostEqual(self.w.region("aster").damage, 0.02)
        self.advance()
        self.assertAlmostEqual(self.w.region("aster").damage, 0.03)
        self.advance()
        self.assertAlmostEqual(self.w.region("aster").damage, 0.035)
        self.advance()
        self.assertAlmostEqual(self.w.region("aster").damage, 0.035)

    def test_a_second_call_in_the_same_month_does_not_apply_twice(self):
        schedule_one(self.w, "damage", "aster", 0.02, months=2)
        effects.step(self.w)
        effects.step(self.w)
        self.assertAlmostEqual(self.w.region("aster").damage, 0.02)
        self.advance()
        self.assertAlmostEqual(self.w.region("aster").damage, 0.04)

    def test_entries_scheduled_separately_cannot_exceed_the_month_cap(self):
        schedule_one(self.w, "damage", "aster", 0.02, months=1)
        schedule_one(self.w, "damage", "aster", 0.02, months=1)
        effects.step(self.w)
        self.assertAlmostEqual(self.w.region("aster").damage, 0.02)
        total = sum(abs(x["value"]) for x in effects.applied(self.w)
                    if x["channel"] == "damage" and x["target"] == "aster")
        self.assertLessEqual(total, effects.CHANNELS["damage"]["month_cap"] + 1e-9)

    def test_each_stock_channel_reaches_its_state(self):
        schedule_one(self.w, "logistics", "aster", -0.05)
        schedule_one(self.w, "morale", "army", -0.02)
        schedule_one(self.w, "morale", "navy", 0.02)
        schedule_one(self.w, "morale", "police", 0.02)
        schedule_one(self.w, "corruption", "interior", 0.02)
        schedule_one(self.w, "admin_capacity", "*", -0.02)
        schedule_one(self.w, "confidence", "*", -0.01)
        schedule_one(self.w, "relations", "veleria", 0.03)
        schedule_one(self.w, "league_trust", "*", -0.05)
        effects.step(self.w)
        self.assertAlmostEqual(self.w.region("aster").logistics, 0.95)
        self.assertAlmostEqual(self.w.mil.army.morale, 0.53)
        self.assertAlmostEqual(self.w.mil.navy.morale, 0.62)
        self.assertAlmostEqual(self.w.mil.police.morale, 0.62)
        self.assertAlmostEqual(self.w.institutions["corruption"]["interior"], 0.02)
        self.assertAlmostEqual(self.w.econ.admin_capacity, 0.98)
        self.assertAlmostEqual(self.w.econ.confidence, 0.99)
        rel = self.w.foreign["actors"]["veleria"]["relations"]["karamaniya"]
        self.assertAlmostEqual(rel["trust"], 0.23)
        self.assertAlmostEqual(rel["hostility"], 0.69)
        self.assertAlmostEqual(self.w.dip.league_trust, 0.50)

    def test_an_office_capacity_effect_reaches_that_office(self):
        schedule_one(self.w, "admin_capacity", "treasury", 0.02)
        effects.step(self.w)
        self.assertAlmostEqual(self.w.institutions["capacity"]["treasury"], 1.0)
        # A bare world has no capacity table yet; the bus starts the named office at 1.0.
        schedule_one(self.w, "admin_capacity", "interior", -0.02)
        self.w.month += 1
        effects.step(self.w)
        self.assertAlmostEqual(self.w.institutions["capacity"]["interior"], 0.98)

    def test_the_month_record_names_channel_target_and_source(self):
        source = {"kind": "open_act", "actor": "B", "motion": "M-7", "month": self.w.month}
        schedule_one(self.w, "morale", "army", -0.02, source=source)
        effects.step(self.w)
        record = effects.applied(self.w)[0]
        self.assertEqual(record["channel"], "morale")
        self.assertEqual(record["target"], "army")
        self.assertAlmostEqual(record["value"], -0.02)
        self.assertEqual(record["source"], source)

    def test_the_source_is_kept_on_every_entry(self):
        source = {"kind": "cabinet_open_act", "actor": "veleria", "motion": "C-2", "month": self.w.month}
        entries = schedule_one(self.w, "relations", "dorsania", 0.03, source=source)
        self.assertEqual(entries[0]["source"], source)

    def test_an_effect_with_nothing_to_do_leaves_no_state(self):
        effects.step(self.w)
        self.assertNotIn("effects", self.w.institutions)
        self.assertNotIn("effects_step_month", self.w.institutions)
        self.assertNotIn("effects_applied", self.w.institutions)
        self.assertNotIn("effects_modifiers", self.w.institutions)

    def test_the_month_record_is_cleared_when_a_later_month_applies_nothing(self):
        schedule_one(self.w, "damage", "aster", 0.02)
        effects.step(self.w)
        self.assertEqual(len(effects.applied(self.w)), 1)
        self.advance()
        self.assertEqual(effects.applied(self.w), [])
        self.assertEqual(effects.modifiers(self.w, "income"), {})


class SocietyTests(unittest.TestCase):
    def test_public_mood_accepts_a_class_target_and_rejects_an_unknown_class(self):
        w = new_world(1)
        entry = public_mood.react(w, "approval", "class:farmers", 0.03, 2, "a farm package")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["where"], "class:farmers")
        self.assertIsNone(public_mood.react(w, "approval", "class:peasants", 0.01, 2, "x"))

    def test_a_class_reaction_moves_only_that_class(self):
        plain, treated = new_world(1), new_world(1)
        for w in (plain, treated):
            w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
        schedule_one(treated, "approval", "class:farmers", 0.03, months=1)
        engine.step(plain)
        engine.step(treated)
        moved = treated.avg("approval", farmers(treated)) - plain.avg("approval", farmers(plain))
        self.assertGreater(moved, 0.005)
        for cls in ("workers", "middle", "elite"):
            unchanged = treated.avg("approval", of_class(treated, cls)) - plain.avg("approval", of_class(plain, cls))
            self.assertAlmostEqual(unchanged, 0.0, places=6)

    def test_a_region_and_an_identity_reaction_still_reach_only_their_group(self):
        plain, treated = new_world(1), new_world(1)
        schedule_one(treated, "grievance", "ident:vell", 0.03, months=1)
        engine.step(plain)
        engine.step(treated)
        moved = treated.avg("grievance", of_ident(treated, "vell")) - plain.avg("grievance", of_ident(plain, "vell"))
        self.assertGreater(moved, 0.005)
        untouched = treated.avg("grievance", of_ident(treated, "karamanian")) - \
            plain.avg("grievance", of_ident(plain, "karamanian"))
        self.assertAlmostEqual(untouched, 0.0, places=6)

    def test_the_engine_records_a_society_effect_in_the_month_history(self):
        w = new_world(1)
        schedule_one(w, "fear", "class:workers", 0.02, months=1)
        engine.step(w)
        row = w.history[-1]
        self.assertIn("effects_applied", row)
        record = row["effects_applied"][0]
        self.assertEqual((record["channel"], record["target"]), ("fear", "class:workers"))
        self.assertEqual(record["source"]["kind"], "policy")

    def test_income_reaches_the_named_class(self):
        plain, treated = new_world(1), new_world(1)
        schedule_one(treated, "income", "class:farmers", 0.02, months=1)
        engine.step(plain)
        engine.step(treated)
        moved = treated.avg("income", farmers(treated)) - plain.avg("income", farmers(plain))
        self.assertGreater(moved, 0.005)
        other = treated.avg("income", of_class(treated, "workers")) - plain.avg("income", of_class(plain, "workers"))
        self.assertAlmostEqual(other, 0.0, places=9)

    def test_hunger_reaches_the_named_identity(self):
        plain, treated = new_world(1), new_world(1)
        schedule_one(treated, "hunger", "ident:vell", 0.02, months=1)
        engine.step(plain)
        engine.step(treated)
        moved = treated.avg("hunger", of_ident(treated, "vell")) - plain.avg("hunger", of_ident(plain, "vell"))
        self.assertAlmostEqual(moved, 0.02, places=9)
        other = treated.avg("hunger", of_ident(treated, "karamanian")) - \
            plain.avg("hunger", of_ident(plain, "karamanian"))
        self.assertAlmostEqual(other, 0.0, places=9)

    def test_an_income_modifier_is_read_from_the_effects_table(self):
        w = new_world(1)
        schedule_one(w, "income", "aster", 0.02)
        effects.step(w)
        self.assertEqual(effects.modifiers(w, "income"), {"aster": 0.02})
        self.assertEqual(effects.modifiers(w, "hunger"), {})


class EngineIntegrationTests(unittest.TestCase):
    def test_the_engine_step_applies_a_scheduled_effect(self):
        w = new_world(1)
        schedule_one(w, "damage", "kessel", 0.02)
        engine.step(w)
        self.assertGreaterEqual(w.region("kessel").damage, 0.02)

    def test_with_nothing_scheduled_a_scripted_month_is_identical_to_one_without_the_bus(self):
        plain, bus = new_world(4), new_world(4)
        with mock.patch.object(effects, "step", lambda w: None):
            engine.step(plain)
        engine.step(bus)
        self.assertEqual(plain.history[-1], bus.history[-1])
        self.assertNotIn("effects_applied", bus.history[-1])
        self.assertEqual(plain.institutions, bus.institutions)

    def test_an_old_checkpoint_without_an_effects_key_loads_as_empty(self):
        w = new_world(1)
        engine.step(w)
        data = w.to_dict()
        for key in ("effects", "effects_step_month", "effects_applied", "effects_modifiers"):
            data["institutions"].pop(key, None)
        loaded = World.from_dict(data)
        self.assertEqual(effects.state(loaded), [])
        effects.step(loaded)
        schedule_one(loaded, "damage", "aster", 0.02)
        loaded.month += 1
        effects.step(loaded)
        self.assertAlmostEqual(loaded.region("aster").damage, 0.02)


class PropertyTests(unittest.TestCase):
    """Seeded random effect lists never exceed the per-month cap on a channel and target."""

    CHANNEL_TARGETS = {
        "approval": ["*", "aster", "ident:vell", "class:farmers", "class:workers"],
        "grievance": ["*", "kessel", "ident:imperial", "class:middle"],
        "fear": ["*", "highlands", "class:elite"],
        "indep": ["*", "dorran", "ident:karamanian"],
        "repression": ["*", "lissen", "class:farmers"],
        "income": ["*", "aster", "class:farmers", "ident:vell"],
        "hunger": ["*", "kessel", "class:workers", "ident:imperial"],
        "damage": ["aster", "kessel", "highlands"],
        "logistics": ["aster", "kessel", "dorran"],
        "admin_capacity": ["*", "head", "treasury"],
        "confidence": ["*"],
        "corruption": ["head", "treasury", "interior", "army", "navy"],
        "relations": ["veleria", "dorsania"],
        "league_trust": ["*", "league"],
        "morale": ["army", "navy", "police"],
    }

    def test_random_effect_lists_never_exceed_the_month_cap(self):
        for seed in range(1, 26):
            with self.subTest(seed=seed):
                rng = rng_for(seed, 0, "effects-test")
                w = new_world(seed)
                for _ in range(8):
                    channel = rng.choice(sorted(self.CHANNEL_TARGETS))
                    target = rng.choice(self.CHANNEL_TARGETS[channel])
                    # Some values are deliberately over the cap; validate must refuse those.
                    value = rng.uniform(-0.06, 0.06)
                    months = rng.randint(1, effects.MAX_MONTHS)
                    goods, problems = effects.validate(w, [one(channel, target, value, months)], SOURCE)
                    if problems:
                        self.assertEqual({p["code"] for p in problems} & {
                            "EFFECT_OVER_CAP", "EFFECT_MONTH_CAP"}, {problems[0]["code"]})
                        continue
                    effects.schedule(w, goods, SOURCE)
                dilemmas.apply_ongoing(w)
                effects.step(w)
                totals = {}
                for record in effects.applied(w):
                    key = (record["channel"], record["target"])
                    totals[key] = totals.get(key, 0.0) + abs(record["value"])
                    self.assertLessEqual(abs(record["value"]), effects.CHANNELS[record["channel"]]["cap"] + 1e-9)
                for (channel, target), total in totals.items():
                    self.assertLessEqual(total, effects.CHANNELS[channel]["month_cap"] + 1e-9,
                                         f"{channel} at {target} summed to {total}")


if __name__ == "__main__":
    unittest.main()
