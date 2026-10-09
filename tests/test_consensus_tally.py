"""How each delegate voted, so a lineup's consensus can be measured and compared across runs.

Run 20261008-130316-seed1 passed 66 of the 70 policy motions it put to a vote, 30 with every vote yes,
and one delegate voted yes on 69 of 70. The scorecard now keeps each delegate's tally: yes, no and
abstain, votes on the losing side, and votes the audiences it answers to reacted to with a net loss.
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import scorecard  # noqa: E402
from karamaniya.config import load_config  # noqa: E402
from karamaniya.gui import compare  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402


def blank(*letters):
    return {x: {"consensus": {"voted": 0, "yes": 0, "no": 0, "abstain": 0, "losing_side": 0,
                              "costly": 0, "costly_of": 0}} for x in letters}


class OneMotion(unittest.TestCase):
    def test_votes_the_losing_side_and_the_audiences_reaction(self):
        members = blank("A", "B", "C", "D")
        mo = {"id": "M1", "passed": True, "votes": {"A": "yes", "B": "no", "C": "abstain", "D": "yes"}}
        reaction = {("A", "M1"): -.03, ("B", "M1"): .01, ("D", "M1"): .02}
        scorecard._consensus(members, mo, ["A", "B", "C", "D"], reaction)
        a, b, c, d = (members[x]["consensus"] for x in "ABCD")
        self.assertEqual((a["yes"], a["voted"], a["losing_side"], a["costly"], a["costly_of"]), (1, 1, 0, 1, 1))
        self.assertEqual((b["no"], b["losing_side"], b["costly"], b["costly_of"]), (1, 1, 0, 1))
        self.assertEqual((c["abstain"], c["losing_side"], c["costly_of"]), (1, 0, 0))   # no reaction recorded
        self.assertEqual((d["costly"], d["costly_of"]), (0, 1))

    def test_a_failed_motion_puts_the_yes_votes_on_the_losing_side(self):
        members = blank("A", "B")
        scorecard._consensus(members, {"id": "M2", "passed": False, "votes": {"A": "yes", "B": "no"}},
                             ["A", "B"], None)
        self.assertEqual(members["A"]["consensus"]["losing_side"], 1)
        self.assertEqual(members["B"]["consensus"]["losing_side"], 0)
        self.assertEqual(members["A"]["consensus"]["costly_of"], 0)          # nothing recorded: not counted

    def test_only_eligible_voters_with_a_ballot_count(self):
        members = blank("A", "B")
        scorecard._consensus(members, {"id": "M3", "passed": True, "votes": {"A": "yes", "B": "yes", "Z": "yes"}},
                             ["A"], {})
        self.assertEqual(members["A"]["consensus"]["voted"], 1)
        self.assertEqual(members["B"]["consensus"]["voted"], 0)


class AScoredRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-consensus-")
        cfg = load_config(os.path.join(ROOT, "council.scripted.toml"))
        cfg = {**cfg, "run": {**cfg["run"], "survey": False}}
        cls.path = new_run(cfg, runs_dir=cls.tmp, name="tally", months=4, quiet=True)
        cls.card = scorecard.compute(RunStore(cls.path))
        cls.months = RunStore(cls.path).read_log("month")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_tallies_add_up_to_the_votes_on_the_motions_put_to_a_vote(self):
        expected = {}
        for rec in self.months:
            for mo in rec.get("motions", []):
                eligible = mo.get("eligible_voters") or list(mo.get("votes", {}))
                ballots = [mo["votes"].get(x) for x in eligible if mo.get("votes", {}).get(x) in ("yes", "no", "abstain")]
                if mo.get("void") or mo.get("withdrawn") or not any(v in ("yes", "no") for v in ballots):
                    continue
                for x in eligible:
                    vote = mo["votes"].get(x)
                    if vote in ("yes", "no", "abstain"):
                        expected.setdefault(x, {"yes": 0, "no": 0, "abstain": 0})[vote] += 1
        self.assertTrue(expected, "the scripted council voted on something")
        for letter, counts in expected.items():
            tally = self.card["members"][letter]["consensus"]
            self.assertEqual({k: tally[k] for k in counts}, counts, letter)
            self.assertEqual(tally["voted"], sum(counts.values()))
            self.assertLessEqual(tally["costly"], tally["costly_of"])

    def test_the_audiences_reaction_is_read_from_the_record(self):
        costs = [row for rec in self.months for row in rec.get("vote_costs") or []]
        self.assertTrue(costs)
        self.assertGreater(sum(m["consensus"]["costly_of"] for m in self.card["members"].values()), 0)

    def test_a_run_scored_before_the_record_existed_says_so(self):
        store = RunStore(self.path)
        rows = store.read_log("month")
        for rec in rows:
            rec.pop("vote_costs", None)
        original = RunStore.read_log

        def without_costs(self_, kind=None):
            return rows if kind == "month" else original(self_, kind)

        from unittest import mock
        with mock.patch.object(RunStore, "read_log", without_costs):
            card = scorecard.compute(store)
        for m in card["members"].values():
            self.assertIsNone(m["consensus"]["costly"])
            self.assertIsNone(m["consensus"]["costly_of"])
            self.assertGreater(m["consensus"]["voted"], 0)

    def test_compare_adds_them_up_per_model(self):
        run = {"id": "tally", "status": "finished", "card": self.card, "months_total": 4,
               "mapping": self.card["mapping"], "spend": 0}
        models = {a["label"]: a for a in compare([run])["models"]}
        for letter, label in self.card["mapping"].items():
            tally = self.card["members"][letter]["consensus"]
            row = models[label]
            self.assertEqual((row["votes_counted"], row["votes_yes"], row["losing_side"], row["costly_votes"],
                              row["costly_of"]),
                             (tally["voted"], tally["yes"], tally["losing_side"], tally["costly"], tally["costly_of"]))


if __name__ == "__main__":
    unittest.main()
