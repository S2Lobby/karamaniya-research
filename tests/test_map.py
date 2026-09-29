"""The map: the island is the same every time and has everything the live view draws on."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import engine, mapgen  # noqa: E402
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
            self.assertNotIn("/*__MAPVIEW__*/", html)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
