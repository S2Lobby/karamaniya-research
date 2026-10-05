"""The map: the island is the same every time and has everything the live view draws on."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import engine, mapgen  # noqa: E402
from karamaniya.report import engine_source_groups, engine_source_unrecorded_months, history_rows  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.world import FRONT_CHAINS, new_world  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Island(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = new_world(1)
        cls.geo = mapgen.build_map(cls.world.regions)

    def test_same_island_every_time(self):
        mapgen._build.cache_clear()
        again = mapgen.build_map(new_world(7).regions)  # the seed changes the dice, not the geography
        self.assertEqual(json.dumps(self.geo, sort_keys=True), json.dumps(again, sort_keys=True))

    def test_every_region_is_drawn_inside_the_frame(self):
        regions = {r.id: r for r in self.world.regions}
        self.assertEqual(set(self.geo["regions"]), set(regions))
        for rid, g in self.geo["regions"].items():
            self.assertTrue(g["path"].startswith("M") and g["path"].endswith("Z"), rid)
            self.assertGreater(g["area"], 300, rid)
            self.assertTrue(0 < g["lx"] < self.geo["w"] and 0 < g["ly"] < self.geo["h"], rid)

    def test_borders_ports_and_fronts(self):
        nation = {r.id: r.nation for r in self.world.regions}
        pairs = set()
        for b in self.geo["borders"]:
            self.assertEqual(b["national"], nation[b["a"]] != nation[b["b"]], b["a"] + "/" + b["b"])
            pairs.add(frozenset((b["a"], b["b"])))
        # Each front starts in a region that really touches the enemy it faces.
        enemy = {"north": "veleria", "east": "dorsania"}
        for front, chain in FRONT_CHAINS.items():
            first = chain[0]
            self.assertTrue(any(first in p and any(nation[x] == enemy[front] for x in p if x != first) for p in pairs),
                            f"{first} does not border {enemy[front]}")
        coastal = {r.id for r in self.world.regions if r.coast}
        ports = {c["region"] for c in self.geo["cities"] if c["port"]}
        self.assertTrue(coastal <= ports, f"ports {ports} miss {coastal - ports}")
        self.assertEqual({lane["region"] for lane in self.geo["lanes"]}, coastal)
        self.assertGreaterEqual(len(self.geo["rivers"]), 3)
        self.assertTrue(self.geo["mountains"] and self.geo["forest"] and self.geo["fields"])
        self.assertLess(len(json.dumps(self.geo)) / 1024, 250)


class MonthDetail(unittest.TestCase):
    def test_stored_history_projects_effective_front_strength_and_legacy_defaults(self):
        world = {
            "regions": [{"id": "capital", "capital": True}],
            "history": [
                {"month": 0, "army": 1000, "army_mobilized": 200, "army_mobilized_effective": 100,
                 "engine_source_fingerprint": "engine-a",
                 "deploy": {"north": 0.4, "east": 0.35, "capital": 0.25},
                 "fronts": {"north": {"region": "capital", "ours": 400, "union": 500},
                            "east": {"region": "coast", "ours": 350, "union": 500}}},
                {"month": 1, "army": 800, "engine_source_fingerprint": "engine-b",
                 "fronts": {"north": {"region": "coast", "ours": 320, "union": 0}}},
                {"month": 2, "army": 700, "fronts": {"north": {"region": "coast", "ours": 280, "union": 0}}},
            ],
        }
        rows = history_rows(world)
        self.assertEqual(rows[0]["currency"], "crown")
        self.assertEqual(rows[0]["army_field_total"], 1100)
        self.assertEqual(rows[0]["fronts"]["north"]["ours_effective"], 465)
        self.assertEqual(rows[0]["fronts"]["east"]["ours_effective"], 385)
        self.assertEqual(rows[1]["army_field_total"], 800)
        self.assertNotIn("ours_effective", rows[1]["fronts"]["north"])
        self.assertEqual(rows[2]["army_field_total"], 700)
        self.assertEqual(engine_source_groups(rows), [
            {"fingerprint": "engine-a", "months": [0]},
            {"fingerprint": "engine-b", "months": [1]},
        ])
        self.assertEqual(engine_source_unrecorded_months(rows), [2])
        # Projection is safe for the shared Atlas cache: it does not rewrite checkpoint data.
        self.assertNotIn("ours_effective", world["history"][0]["fronts"]["north"])

    def test_snapshot_has_regions_and_fronts(self):
        w = new_world(1, 6)
        for _ in range(3):
            engine.begin_month(w)
            engine.step(w)
        row = w.history[-1]
        k_regions = {r.id for r in w.regions if r.nation == "karamaniya"}
        self.assertEqual(set(row["region_detail"]), k_regions)
        d = row["region_detail"]["aster"]
        for key in ("pop", "approval", "hunger", "unrest", "indep", "fear", "unemployment", "income", "ident", "cls"):
            self.assertIn(key, d)
        self.assertAlmostEqual(sum(d["ident"].values()), 1.0, places=3)
        self.assertEqual(set(row["fronts"]), {"north", "east"})
        self.assertEqual(row["fronts"]["north"]["region"], FRONT_CHAINS["north"][0])
        self.assertIsNone(row["fronts"]["north"]["combat"])  # no war yet, so no fighting this month

    def test_report_carries_the_map(self):
        tmp = tempfile.mkdtemp(prefix="karamaniya-map-test-")
        try:
            path = new_run(os.path.join(HERE, "council.scripted.toml"), runs_dir=tmp, name="m", months=2,
                           survey=False, quiet=True, check=False)
            with open(os.path.join(path, "report.html"), encoding="utf-8") as f:
                html = f.read()
            self.assertIn("window.KaramaniyaMap", html)
            self.assertIn('"geo":{', html)
            self.assertIn('"region_detail":', html)
            self.assertIn("Karamaniya effective field strength", html)
            self.assertIn('h.currency === "karam" ? "karam" : "crown"', html)
            self.assertIn("ours_effective", html)
            self.assertIn("This run recorded multiple engine source fingerprints", html)
            self.assertIn("Engine source not recorded for this history", html)
            self.assertNotIn("/*__MAPVIEW__*/", html)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
