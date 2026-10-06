"""Inherited state generation and pre-council diagnosis are seeded and inspectable."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.config import normalize_config, RUN_DEFAULTS
from karamaniya.backends import CallResult
from karamaniya.backends.scripted import ScriptedBackend
from karamaniya.council import Council, Seat
from karamaniya.founding import (TEMPLATES, REQUIRED_DIAGNOSIS_FIELDS, diagnosis_prompt,
                                  diagnosis_schema, public_profile, validate_diagnosis)
from karamaniya.runner import new_run
from karamaniya.storage import RunStore
from karamaniya.world import World, new_world


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTED = os.path.join(ROOT, "council.scripted.toml")


class FoundingState(unittest.TestCase):
    def test_five_individual_votes_fill_offices_without_using_policy_slots(self):
        offices = ("head", "treasury", "interior", "army", "navy")
        class NominationBackend:
            def complete(self, system, user, schema, context):
                if context["phase"] == "formation_proposal":
                    return CallResult(data={"statement": "Consider each office separately.",
                        "nominations": [{"office": office, "member": mid}
                                        for office, mid in zip(offices, "ABCDE")],
                        "slate": {office: "" for office in offices}})
                return CallResult(data={"votes": {m["id"]: "yes" for m in context["formation_motions"]},
                    "reasons": {m["id"]: "Qualified for this office" for m in context["formation_motions"]}})

        with tempfile.TemporaryDirectory(prefix="karamaniya-appointments-") as temp:
            world = new_world(53, member_ids=list("ABCDE"), founding_scenario="random")
            seats = {mid: Seat(mid, mid, {"provider": "test"}, NominationBackend()) for mid in "ABCDE"}
            formation = Council(world, seats, {}, RunStore(os.path.join(temp, "r"))).form_government()
        self.assertEqual(formation["offices"], dict(zip(offices, "ABCDE")))
        self.assertEqual(len([m for m in formation["motions"] if m["selected"]]), 5)
        self.assertEqual(formation["agenda_slots_used"], 0)
        self.assertEqual(world.month, 0)

    def test_unanimous_full_slate_can_fill_every_office_without_advancing_month(self):
        class SlateBackend:
            def complete(self, system, user, schema, context):
                if context["phase"] == "formation_proposal":
                    return CallResult(data={"statement": "I support the complete cabinet slate.",
                        "nominations": [], "slate": dict(zip(("head", "treasury", "interior", "army", "navy"), "ABCDE"))})
                return CallResult(data={"votes": {m["id"]: "yes" for m in context["formation_motions"]}})

        temp = tempfile.mkdtemp(prefix="karamaniya-slate-")
        self.addCleanup(lambda: shutil.rmtree(temp, ignore_errors=True))
        world = new_world(52, member_ids=list("ABCDE"), founding_scenario="random")
        seats = {mid: Seat(mid, mid, {"provider": "test"}, SlateBackend()) for mid in "ABCDE"}
        formation = Council(world, seats, {}, RunStore(os.path.join(temp, "r"))).form_government()
        self.assertEqual(formation["offices"], dict(zip(("head", "treasury", "interior", "army", "navy"), "ABCDE")))
        self.assertEqual(formation["agenda_slots_used"], 0)
        self.assertTrue(any(m["type"] == "slate" and m["selected"] and m["yes"] == 5
                            for m in formation["motions"]))
        self.assertEqual(world.month, 0)
        self.assertEqual(world.history, [])

    def test_incomplete_diagnosis_gets_targeted_repair_and_terminal_failures_are_recorded(self):
        class PartialBackend:
            def __init__(self, fail=False):
                self.fail = fail
                self.repair_fields = []

            def complete(self, system, user, schema, context):
                if context.get("repair"):
                    self.repair_fields.append(tuple(schema["required"]))
                    if self.fail:
                        return CallResult(data={"information_needed": "check invoices"}, raw="{}")
                    return CallResult(data={k: "check invoices" if k == "information_needed"
                        else "Other delegates may overlook delivery costs." for k in schema["required"]}, raw="(repair)")
                data = ScriptedBackend({"persona": "democrat"})._founding_diagnosis(context["world"])
                data.pop("information_needed")
                data.pop("what_other_offices_may_be_underestimating")
                return CallResult(data=data, raw="(partial)")

        temp = tempfile.mkdtemp(prefix="karamaniya-diagnosis-repair-")
        self.addCleanup(lambda: shutil.rmtree(temp, ignore_errors=True))
        world = new_world(51, member_ids=list("ABCDE"), founding_scenario="random")
        backends = {mid: PartialBackend(fail=(mid == "E")) for mid in "ABCDE"}
        seats = {mid: Seat(mid, mid, {"provider": "test"}, backends[mid]) for mid in "ABCDE"}
        store = RunStore(os.path.join(temp, "r"))
        diagnoses = Council(world, seats, {}, store).diagnose_founding()
        self.assertTrue(all(backends[mid].repair_fields == [("information_needed", "what_other_offices_may_be_underestimating")]
                            for mid in "ABCDE"))
        self.assertTrue(all(diagnoses[mid]["status"] == "submitted" for mid in "ABCD"))
        self.assertEqual(diagnoses["E"]["status"], "invalid")
        self.assertNotIn("main_problem", diagnoses["E"])
        self.assertEqual(len(store.read_log("founding_diagnosis_failure")), 1)
        self.assertEqual(world.founding["diagnosis_divergence"]["diagnoses"], 4)

    def test_seeded_starts_are_repeatable_and_vary_across_seeds(self):
        a = new_world(121, member_ids=list("ABCDE"), founding_scenario="random")
        b = new_world(121, member_ids=list("ABCDE"), founding_scenario="random")
        c = new_world(122, member_ids=list("ABCDE"), founding_scenario="random")
        public = lambda w: [(p["id"], p["severity"], p["hidden_cause"]) for p in w.founding["problems"]]
        self.assertEqual(public(a), public(b))
        self.assertNotEqual(public(a), public(c))
        self.assertTrue(3 <= len(a.founding["problems"]) <= 7)
        self.assertGreaterEqual(len({p["category"].split(" /")[0] for p in a.founding["problems"]}), 2)
        self.assertTrue(2 <= len(a.founding["strengths"]) <= 3)
        restored = World.from_dict(a.to_dict())
        self.assertEqual(public(restored), public(a))

    def test_problem_effects_are_canonical_and_scenario_custom_is_bounded(self):
        w = new_world(9, human_factor=False, founding_scenario="custom", founding_severity="serious",
                      founding_problems=["food_dependence", "army_readiness", "rail_bottleneck", "regional_legitimacy"])
        ids = {p["id"] for p in w.founding["problems"]}
        self.assertEqual(ids, {"food_dependence", "army_readiness", "rail_bottleneck", "regional_legitimacy"})
        self.assertLess(w.econ.food_import_capacity, 1)
        self.assertLess(w.mil.army.equipment, .9)
        self.assertLess(w.region("kessel").logistics, 1)
        self.assertTrue(any(p.region == "kessel" and p.grievance > .15 for p in w.pops))
        with self.assertRaises(ValueError):
            new_world(9, founding_scenario="custom", founding_problems=list(TEMPLATES))

    def test_diagnostic_prompt_exposes_competing_hypotheses_not_hidden_truth(self):
        w = new_world(77, member_ids=list("ABCDE"), founding_scenario="random")
        first = diagnosis_prompt(w, "A")
        role_a, _ = __import__("karamaniya.founding", fromlist=["portfolio"]).portfolio(w, "A")
        other_roles = {__import__("karamaniya.founding", fromlist=["portfolio"]).portfolio(w, x)[0]
                       for x in "BCDE"}
        self.assertTrue(any(r != role_a for r in other_roles))
        self.assertIn("possible_causes", first)
        self.assertIn("independently", first)
        for p in w.founding["problems"]:
            self.assertNotIn(p["hidden_cause"], first)
        self.assertIn("Do not try to disagree", first)
        self.assertNotIn("YOUR PRIVATE HANDOVER PORTFOLIO", first)
        self.assertTrue(set(w.founding["dossiers"].values()).isdisjoint({"head", "treasury", "interior", "army", "navy"}))
        self.assertTrue(set(REQUIRED_DIAGNOSIS_FIELDS).issubset(diagnosis_schema(w)["required"]))

    def test_scripted_run_collects_distinct_diagnoses_before_month_one(self):
        temp = tempfile.mkdtemp(prefix="karamaniya-founding-")
        self.addCleanup(lambda: shutil.rmtree(temp, ignore_errors=True))
        cfg = normalize_config({"run": {**RUN_DEFAULTS, "months": 1, "seed": 33,
                "survey": False, "shuffle_seats": False, "founding_scenario": "custom",
                "founding_problems": ["regional_legitimacy", "fiscal_arrears", "army_readiness",
                    "constitutional_uncertainty", "monetary_dependence"]},
            "seat": [{"provider": "scripted", "persona": p, "label": "scripted-" + p}
                     for p in ("democrat", "technocrat", "hawk", "loyalist", "opportunist")]})
        path = new_run(cfg, runs_dir=temp, name="diagnostics", quiet=True)
        store = RunStore(path)
        calls = store.read_log("call")
        first_session = next(i for i, c in enumerate(calls) if c["phase"] == "session")
        self.assertTrue(all(c["phase"] in ("founding_diagnosis", "formation_proposal", "formation_vote")
                            for c in calls[:first_session]))
        self.assertEqual(sum(c["phase"] == "founding_diagnosis" for c in calls), 5)
        self.assertEqual(sum(c["phase"] == "formation_proposal" for c in calls), 5)
        self.assertEqual(sum(c["phase"] == "formation_vote" for c in calls), 5)
        ck = store.read_json("checkpoint.json")
        profile = public_profile(World.from_dict(ck["world"]))
        diagnoses = profile["diagnoses"]
        self.assertTrue(all(d["status"] == "submitted" and all(d.get(k) for k in REQUIRED_DIAGNOSIS_FIELDS)
                            for d in diagnoses.values()))
        self.assertEqual(len({v for v in profile["formation"]["offices"].values() if v}), 5)
        self.assertEqual(profile["formation"]["agenda_slots_used"], 0)
        self.assertGreaterEqual(len({d["main_problem"] for d in diagnoses.values()}), 4)
        self.assertGreater(profile["diagnoses"] and ck["world"]["founding"]["diagnosis_divergence"]["top_problem_disagreement"], 0)
        month = store.read_log("month")[0]
        self.assertEqual(month["founding_diagnoses"], diagnoses)
        self.assertLess(len(month["motions"]), 6)
        self.assertNotIn("hidden_cause", json.dumps(month["founding_state"]))
        self.assertTrue(ck["world"]["history"][0]["region_detail"]["kessel"]["founding_problems"])
        from karamaniya.gui import Inspector
        inspector = Inspector(store.path.parent)
        idx = inspector.index("diagnostics")
        self.assertEqual(sum(m["month"] == -2 for m in idx["months"]), 1)
        inspected = inspector.month("diagnostics", -2)
        self.assertEqual(len(inspected["founding"]["diagnoses"]), 5)
        self.assertNotIn("hidden_cause", json.dumps(inspected["founding"]))
        self.assertEqual(sum(m["month"] == -3 for m in idx["months"]), 1)
        self.assertEqual(inspector.month("diagnostics", -3)["record"]["agenda_slots_used"], 0)

    def test_three_seeded_random_starts_stay_playable_and_get_different_diagnoses(self):
        from karamaniya.config import load_config
        temp = tempfile.mkdtemp(prefix="karamaniya-random-starts-")
        self.addCleanup(lambda: shutil.rmtree(temp, ignore_errors=True))
        cfg = load_config(SCRIPTED)
        cfg["run"].update(months=1, survey=False, shuffle_seats=False, foreign_cabinets=False)
        states = []
        diagnosis_sets = []
        for seed in (201, 202, 203):
            path = new_run(cfg, runs_dir=temp, name="seed-" + str(seed), seed=seed, quiet=True)
            world = RunStore(path).load_checkpoint()[0]
            states.append(tuple(p["id"] for p in world.founding["problems"]))
            diagnosis_sets.append({d["main_problem"] for d in world.founding["diagnoses"].values()})
            self.assertTrue(3 <= len(world.founding["problems"]) <= 7)
            self.assertLessEqual(max(p["initial_severity"] for p in world.founding["problems"]), 70)
            self.assertGreater(len(diagnosis_sets[-1]), 1)
            self.assertGreater(world.history[0]["food_ratio"], .70)
        self.assertGreater(len(set(states)), 1)
        self.assertGreater(len(set(map(tuple, map(sorted, diagnosis_sets)))), 1)

    def test_run_configuration_accepts_named_and_rejects_invalid_foundation(self):
        raw = {"run": {**RUN_DEFAULTS, "founding_scenario": "regional-divide"},
               "seat": [{"provider": "scripted", "persona": "democrat"}]}
        self.assertEqual(normalize_config(raw)["run"]["founding_scenario"], "regional-divide")
        raw["run"]["founding_scenario"] = "invented"
        with self.assertRaises(ValueError):
            normalize_config(raw)


if __name__ == "__main__":
    unittest.main()
