"""Brief 9.S3: the action-order switch, the run option `action_order`.

Each month the council draws its speaking order from the month's seeded stream. That order is the publication order
of the openings, the order of the response round, what the month's prompts say, and what the month records.
`seeded_shuffle`, the default, is that draw exactly as it has always been. `fixed_precedence` gives every month the
office holders first, in world.OFFICES order (head of government, treasury, interior, army, navy), then the other
active members in letter order.

The study compares the two protocols on the same seeds, so only the order may differ between them. Under
fixed_precedence the shuffle is still drawn, on a copy that is then thrown away, so the stream advances exactly as it
does today, and every other draw of the month (the interception draws in Council._deliver above all) comes out the
same. The integration tests run scripted seats, which read the world and not the prompt, under both protocols on the
same seeds, for both the current month (_run_month_v2) and the legacy one (_run_month_v1). They check that the state
before the council acts in Month 1 is identical, that the state before Month 2 differs only in the order of list
entries (the intelligence share records, which the publication order writes, are the case that differs), that the
stream is in the same state after each month, and that the models are told the order that is used.
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

from karamaniya import council as council_module, manifest  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import OFFICES, new_world, rng_for  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")
PROTOCOLS = ("seeded_shuffle", "fixed_precedence")
SEEDS = (1, 2)
ARCHITECTURES = (2, 1)      # 2: _run_month_v2 (the current month); 1: _run_month_v1 (the legacy month)
MONTHS = 2                  # Month 1 and Month 2, month indices 0 and 1

_real_save_checkpoint = RunStore.save_checkpoint
_real_rng_for = council_module.rng_for


def scripted_cfg(**run):
    cfg = load_config(CONFIG)
    raw = {"run": {**cfg["run"], "survey": False, "baseline": False, **run}, "seat": cfg["seats"]}
    return normalize_config(raw, "test")


def precedence(offices: dict, active: list) -> list:
    """The fixed order, written out again here so the test does not share the code it checks: the holders by
    OFFICES order (a member who holds two offices counts once, at the first), then the rest in letter order."""
    held = []
    for office in OFFICES:
        holder = offices.get(office)
        if holder in active and holder not in held:
            held.append(holder)
    return held + sorted(mid for mid in active if mid not in held)


def canonical(x):
    """A state with every list sorted, so states that differ only in the order of their list entries compare equal."""
    if isinstance(x, dict):
        return {k: canonical(v) for k, v in x.items()}
    if isinstance(x, list):
        return sorted((canonical(v) for v in x), key=lambda v: json.dumps(v, sort_keys=True, default=str))
    return x


def recorded_run(tmp: str, seed: int, architecture: int, protocol: str) -> dict:
    """A two-month scripted run. Each checkpoint is kept as it is saved, and each council draw is kept as it is made."""
    snaps, streams = [], []

    def save(store, world, council_state, meta):
        snaps.append({"history": len(world.history), "world": world.to_dict(),
                      "council": copy.deepcopy(council_state)})
        return _real_save_checkpoint(store, world, council_state, meta)

    def rng(seed_, month, tag):
        stream = _real_rng_for(seed_, month, tag)
        if tag == "council":
            streams.append((month, stream))
        return stream

    cfg = scripted_cfg(seed=seed, agent_architecture_version=architecture, action_order=protocol)
    with mock.patch.object(RunStore, "save_checkpoint", save), mock.patch.object(council_module, "rng_for", rng):
        run_dir = new_run(cfg, runs_dir=tmp, name=f"seed{seed}-arch{architecture}-{protocol}", months=MONTHS,
                          quiet=True, check=False)
    return {"snaps": snaps, "streams": [(month, stream.getstate()) for month, stream in streams],
            "run_dir": run_dir}


TMP = None
RUNS = {}


def setUpModule():
    global TMP
    TMP = tempfile.mkdtemp(prefix="karamaniya-engine24-order-")
    for seed in SEEDS:
        for architecture in ARCHITECTURES:
            for protocol in PROTOCOLS:
                RUNS[(seed, architecture, protocol)] = recorded_run(TMP, seed, architecture, protocol)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def before_month(run: dict, month: int) -> dict:
    """The checkpoint the council sees when it acts in `month` (0-based): the last one saved with that many months done."""
    return [s for s in run["snaps"] if s["history"] == month][-1]


def month_records(run_dir) -> dict:
    return {row["month"]: row for row in RunStore(run_dir).read_log("month")}


def prompts_sent(run_dir) -> list:
    with open(os.path.join(run_dir, "prompts.jsonl"), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class TheOptionIsValidated(unittest.TestCase):
    def test_the_default_is_the_seeded_shuffle_and_a_config_without_the_key_reads_as_it(self):
        self.assertEqual(scripted_cfg()["run"]["action_order"], "seeded_shuffle")
        seats = load_config(CONFIG)["seats"]
        self.assertEqual(normalize_config({"run": {}, "seat": seats})["run"]["action_order"], "seeded_shuffle")

    def test_fixed_precedence_is_accepted_and_kept(self):
        self.assertEqual(scripted_cfg(action_order="fixed_precedence")["run"]["action_order"], "fixed_precedence")

    def test_any_other_order_is_refused(self):
        for bad in ("reversed", "rotating", "Fixed_Precedence", "", None):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                scripted_cfg(action_order=bad)


class TheSpeakingOrder(unittest.TestCase):
    """The helper that draws the speaking order (council.speaking_order), on its own."""

    @staticmethod
    def world(offices: dict, removed=()):
        w = new_world(1, 36)
        w.const.offices.update(offices)
        for mid in removed:
            w.member(mid).status = "removed"
        return w

    def test_seeded_shuffle_is_the_draw_the_council_has_always_made(self):
        active = ["A", "B", "C", "D", "E"]
        for seed in range(1, 25):
            with self.subTest(seed=seed):
                drawn, reference = rng_for(seed, 3, "council"), rng_for(seed, 3, "council")
                got = council_module.speaking_order(self.world({}), active, drawn, "seeded_shuffle")
                expected = active[:]
                reference.shuffle(expected)          # the council's own two lines: order = active[:]; rng.shuffle(order)
                self.assertEqual(got, expected)
                self.assertEqual(drawn.getstate(), reference.getstate())

    def test_fixed_precedence_follows_the_offices_then_the_letters(self):
        active = ["A", "B", "C", "D", "E"]
        cases = {
            "every office held": ({"head": "C", "treasury": "A", "interior": "B", "army": "E", "navy": "D"}, (),
                                  ["C", "A", "B", "E", "D"]),
            "some offices vacant": ({"head": "D", "army": "B"}, (), ["D", "B", "A", "C", "E"]),
            "one member holds two offices": ({"head": "A", "treasury": "A", "army": "C"}, (),
                                             ["A", "C", "B", "D", "E"]),
            "a holder who has left is skipped": ({"head": "A", "treasury": "B"}, ("A",), ["B", "C", "D", "E"]),
        }
        for name, (offices, removed, expected) in cases.items():
            with self.subTest(case=name):
                here = [mid for mid in active if mid not in removed]
                got = council_module.speaking_order(self.world(offices, removed), here, rng_for(4, 0, "council"),
                                                    "fixed_precedence")
                self.assertEqual(got, expected)

    def test_fixed_precedence_does_not_depend_on_the_draw(self):
        active = ["A", "B", "C", "D", "E"]
        w = self.world({"head": "C", "treasury": "A"})
        orders = {tuple(council_module.speaking_order(w, active, rng_for(seed, 0, "council"), "fixed_precedence"))
                  for seed in range(1, 25)}
        self.assertEqual(orders, {("C", "A", "B", "D", "E")})

    def test_fixed_precedence_advances_the_stream_exactly_as_the_shuffle_does(self):
        active = ["A", "B", "C", "D", "E"]
        offices = {"head": "C", "treasury": "A"}
        for seed in range(1, 25):
            with self.subTest(seed=seed):
                shuffled, fixed = rng_for(seed, 0, "council"), rng_for(seed, 0, "council")
                council_module.speaking_order(self.world(offices), active, shuffled, "seeded_shuffle")
                council_module.speaking_order(self.world(offices), active, fixed, "fixed_precedence")
                self.assertEqual(fixed.getstate(), shuffled.getstate())
                self.assertEqual(fixed.random(), shuffled.random())

    def test_an_unknown_protocol_is_an_error_not_a_silent_default(self):
        with self.assertRaises(ValueError):
            council_module.speaking_order(self.world({}), ["A", "B"], rng_for(1, 0, "council"), "reversed")


class TheProtocolsDifferOnlyInTheOrder(unittest.TestCase):
    """Two scripted runs on the same seed, one per protocol: the same world, the same draws, and the order alone."""

    def test_before_Month_1_the_state_is_identical(self):
        for seed in SEEDS:
            for architecture in ARCHITECTURES:
                with self.subTest(seed=seed, architecture=architecture):
                    seeded = before_month(RUNS[(seed, architecture, "seeded_shuffle")], 0)
                    fixed = before_month(RUNS[(seed, architecture, "fixed_precedence")], 0)
                    self.assertEqual(seeded["world"], fixed["world"])
                    self.assertEqual(seeded["council"], fixed["council"])

    def test_before_Month_2_the_state_differs_only_in_the_order_of_records(self):
        for seed in SEEDS:
            for architecture in ARCHITECTURES:
                with self.subTest(seed=seed, architecture=architecture):
                    seeded = before_month(RUNS[(seed, architecture, "seeded_shuffle")], 1)
                    fixed = before_month(RUNS[(seed, architecture, "fixed_precedence")], 1)
                    self.assertEqual(canonical(seeded["world"]), canonical(fixed["world"]))
                    self.assertEqual(seeded["council"], fixed["council"])

    def test_every_other_draw_of_each_month_leaves_the_stream_in_the_same_state(self):
        for seed in SEEDS:
            for architecture in ARCHITECTURES:
                with self.subTest(seed=seed, architecture=architecture):
                    seeded = RUNS[(seed, architecture, "seeded_shuffle")]["streams"]
                    fixed = RUNS[(seed, architecture, "fixed_precedence")]["streams"]
                    self.assertEqual([month for month, _ in seeded], list(range(MONTHS)))
                    self.assertEqual(seeded, fixed)

    def test_under_fixed_precedence_each_month_speaks_in_office_order(self):
        for seed in SEEDS:
            for architecture in ARCHITECTURES:
                with self.subTest(seed=seed, architecture=architecture):
                    records = month_records(RUNS[(seed, architecture, "fixed_precedence")]["run_dir"])
                    self.assertEqual(sorted(records), list(range(MONTHS)))
                    for month, row in records.items():
                        self.assertEqual(row["order"], precedence(row["pre_resolution"]["offices"], row["order"]),
                                         f"month {month}")

    def test_under_seeded_shuffle_each_month_speaks_in_the_draw_the_council_has_always_made(self):
        for seed in SEEDS:
            for architecture in ARCHITECTURES:
                with self.subTest(seed=seed, architecture=architecture):
                    run = RUNS[(seed, architecture, "seeded_shuffle")]
                    for month, row in month_records(run["run_dir"]).items():
                        active = [m["id"] for m in before_month(run, month)["world"]["members"]
                                  if m["status"] == "active"]
                        expected = active[:]
                        rng_for(seed, month, "council").shuffle(expected)
                        self.assertEqual(row["order"], expected, f"month {month}")

    def test_the_models_are_told_the_order_that_is_used(self):
        for seed in SEEDS:
            for architecture in ARCHITECTURES:
                for protocol in PROTOCOLS:
                    with self.subTest(seed=seed, architecture=architecture, protocol=protocol):
                        run = RUNS[(seed, architecture, protocol)]
                        names = {m["id"]: m["name"] for m in before_month(run, 0)["world"]["members"]}
                        order = month_records(run["run_dir"])[0]["order"]
                        lead = ("Publication order this month: " if architecture >= 2
                                else "Speaking order for publication: ")
                        line = lead + ", ".join(names[mid] for mid in order)
                        told = [p["prompt"] for p in prompts_sent(run["run_dir"])
                                if p.get("month") == 0 and p.get("phase") == "session"]
                        self.assertTrue(told)
                        self.assertTrue(any(line in prompt for prompt in told), line)


class TheProtocolIsRecordedInTheRun(unittest.TestCase):
    def test_config_json_and_the_manifest_record_the_protocol(self):
        for protocol in PROTOCOLS:
            with self.subTest(protocol=protocol):
                run_dir = new_run(scripted_cfg(action_order=protocol), runs_dir=TMP, name=f"recorded-{protocol}",
                                  months=1, quiet=True, check=False)
                store = RunStore(run_dir)
                self.assertEqual(store.read_json("config.json")["run"]["action_order"], protocol)
                self.assertEqual(store.read_json("manifest.json")["action_order"], protocol)

    def test_a_manifest_from_before_the_option_reads_as_the_default(self):
        built = manifest.build(new_world(1, 36), {"run": {}, "seats": [], "mapping": {}})
        self.assertEqual(built["action_order"], "seeded_shuffle")

    def test_runs_on_different_protocols_are_named_as_not_like_for_like(self):
        seeded, fixed = {"action_order": "seeded_shuffle"}, {"action_order": "fixed_precedence"}
        self.assertIn("action_order", manifest.divergences(seeded, fixed))
        self.assertNotIn("action_order", manifest.divergences(seeded, {"action_order": "seeded_shuffle"}))
        self.assertNotIn("action_order", manifest.divergences({}, seeded))


if __name__ == "__main__":
    unittest.main()
