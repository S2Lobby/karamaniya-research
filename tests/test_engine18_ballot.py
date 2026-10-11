"""World engine 18: the secret-ballot arm (run setting `ballot`), and tools/matrix.py.

In run 20261010-070501-seed1, 27 of 40 votes were five to nothing, though the delegates' private opening positions were
only 9-12% alike. Conformity and real convergence look the same in an open ballot. Under a secret ballot each member
still sees its own vote and every motion's tally and result, and every vote is still recorded, tallied and scored.
What it takes away is what a vote does once other members, or the audiences, can see it: a per-member audience reaction,
a vote-driven trust, alignment, debt, grievance, lone-dissent credit, voter credit, reputation or judged promise.
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import agents, commitments, decision_context, human, prompts, psychology, standing  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.report import report_data  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import World, new_world  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")
OFFICES = {"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"}


def scripted_cfg(**run):
    cfg = load_config(CONFIG)
    raw = {"run": {**cfg["run"], "survey": False, "baseline": False, **run}, "seat": cfg["seats"]}
    return normalize_config(raw, "test")


def world(seed: int = 5):
    w = new_world(seed, 36)
    w.const.offices.update(OFFICES)
    agents.ensure(w)
    for m in w.members:
        for aud in m.agent_state["constituencies"].values():
            aud["support_for_delegate"] = .5
    return w


def motion(subject="tax", value="0.35", **extra):
    mo = {"id": "M1", "proposer": "A", "type": "set_policy", "subject": subject, "value": value,
          "summary": f"set {subject} to {value}"}
    mo.update(extra)
    return mo


def record_of(w, mo):
    return {"month": w.month, "motions": [mo], "decisions": {}, "defiance": [], "resigned": []}


# Phrases that tell a delegate how a colleague voted, or what a vote did to a colleague's standing or reputation.
# The first group is what the open arm writes; the second is the audiences' reading of a delegate's own vote.
VOTE_TALK = ("Colleagues who owe you", "You owe political favours", "supplied a pivotal vote", "over my objection",
             "often votes similarly", "often votes differently", "alone voted against", "Observed working relationships",
             "How your recorded votes landed", "HOW YOUR AUDIENCES WILL READ YOUR VOTE")
TALLY = re.compile(r"\(\d+ yes, \d+ no, \d+ abstain\)")


def vote_talk(text: str, others) -> list:
    hits = [phrase for phrase in VOTE_TALK if phrase in text]
    for name in others:
        hits += [f"{name} {verb}" for verb in ("voted", "votes", "often votes", "alone voted", "supplied a pivotal vote")
                 if re.search(rf"\b{re.escape(name)} {verb}", text)]
    return hits


def load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


matrix = load_tool("matrix")

TMP = None
RUNS = {}
ARMS = {"open": {}, "secret": {"ballot": "secret"}}


def setUpModule():
    """Two three-month scripted runs on seed 1, one open and one secret, shared by the classes below."""
    global TMP
    TMP = tempfile.mkdtemp(prefix="karamaniya-engine18-")
    for arm, extra in ARMS.items():
        RUNS[arm] = new_run(scripted_cfg(**extra), runs_dir=TMP, name=arm, months=3, quiet=True, check=False)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class TheSettingIsValidated(unittest.TestCase):
    def test_secret_is_accepted_and_kept(self):
        self.assertEqual(scripted_cfg(ballot="secret")["run"]["ballot"], "secret")

    def test_anonymous_is_refused(self):
        with self.assertRaises(ValueError):
            scripted_cfg(ballot="anonymous")

    def test_open_is_the_default_and_is_not_written_into_the_run(self):
        self.assertNotIn("ballot", scripted_cfg()["run"])
        self.assertNotIn("ballot", scripted_cfg(ballot="open")["run"])
        self.assertEqual(scripted_cfg()["run"].get("ballot", "open"), "open")

    def test_the_world_carries_the_arm_and_an_old_checkpoint_is_open(self):
        self.assertEqual(new_world(1, 36).ballot, "open")
        self.assertEqual(new_world(1, 36, ballot="secret").ballot, "secret")
        # An open checkpoint has no ballot key, as it had none before the arm; a secret one keeps it.
        self.assertNotIn("ballot", new_world(1, 36).to_dict())
        self.assertEqual(new_world(1, 36, ballot="secret").to_dict()["ballot"], "secret")
        self.assertEqual(World.from_dict(new_world(1, 36).to_dict()).ballot, "open")
        self.assertEqual(World.from_dict(new_world(1, 36, ballot="secret").to_dict()).ballot, "secret")


class ThePromptStatesIt(unittest.TestCase):
    def test_the_secret_arm_adds_one_sentence_under_the_decision_rule(self):
        self.assertIn(prompts.MOTION_PASSES_RULE, prompts.RULES)
        text = prompts.system_prompt("simulation", secret_ballot=True)
        self.assertEqual(text.count(prompts.SECRET_BALLOT_RULE), 1)
        self.assertIn(prompts.MOTION_PASSES_RULE + " " + prompts.SECRET_BALLOT_RULE, text)
        self.assertIn("Votes are secret: each member sees only their own vote and each motion's result and tally.", text)
        # Unobserved delegates get the same sentence, after the rule's own wording for their framing.
        untold = prompts.system_prompt("unobserved", secret_ballot=True)
        self.assertIn("before the month runs its course. " + prompts.SECRET_BALLOT_RULE, untold)

    def test_the_open_arm_says_nothing_of_it(self):
        self.assertEqual(prompts.system_prompt("simulation"), prompts.system_prompt("simulation", secret_ballot=False))
        self.assertNotIn("Votes are secret", prompts.system_prompt("simulation"))


class WhatAVoteDoesOnceItIsSeen(unittest.TestCase):
    """Each gate, once on its own, with the same motion and the same members in both arms."""

    def arms(self, make):
        out = {}
        for arm in ("open", "secret"):
            w = world()
            w.ballot = arm
            out[arm] = make(w)
        return out

    def test_audiences_do_not_react_to_an_individual_vote(self):
        def make(w):
            mo = motion(value="0.35", previous_value=.2, passed=True, void=False,
                        votes={"A": "yes", "B": "yes", "C": "no", "D": "abstain", "E": "yes"})
            w.policy.tax = .35
            rows = standing.apply_vote_costs(w, record_of(w, mo))
            return rows, w.member("B").agent_state.get("vote_reactions")
        out = self.arms(make)
        self.assertTrue(out["open"][0])
        self.assertIsInstance(out["open"][1], list)
        self.assertEqual(out["secret"], ([], None))

    def test_the_reaction_text_says_nothing_under_a_secret_ballot(self):
        def make(w):
            w.month = 1
            w.member("B").agent_state["vote_reactions"] = [{"month": 0, "motion": "M1", "summary": "set tax to 0.35",
                                                           "vote": "yes", "audience": "taxpayers", "delta": -0.05}]
            return standing.reactions_text(w, "B")
        out = self.arms(make)
        self.assertIn("soured on you after your yes on M1", out["open"])
        self.assertEqual(out["secret"], "")

    def test_the_exposure_estimate_is_not_written(self):
        def make(w):
            return standing.exposure_text(w, "B", [motion(value="0.35")])
        out = self.arms(make)
        self.assertTrue(out["open"].startswith("HOW YOUR AUDIENCES WILL READ YOUR VOTE"))
        self.assertEqual(out["secret"], "")

        def prompt(w):
            text, _ = decision_context.build(w, "B", "decision", public_brief="BRIEF", motions=[motion(value="0.35")],
                                             instructions="Vote.")
            return "HOW YOUR AUDIENCES" in text
        self.assertEqual(self.arms(prompt), {"open": True, "secret": False})

    def test_no_trust_or_alignment_follows_from_how_colleagues_voted(self):
        def make(w):
            mo = motion(value="0.35", previous_value=.2, passed=True, void=False,
                        votes={"A": "yes", "B": "yes", "C": "no", "D": "no", "E": "yes"})
            w.policy.tax = .35
            before = w.member("A").relationships["B"]["trust"]
            record = record_of(w, mo)
            agents._relationships(w, record)
            human.update(w, record)
            return (round(w.member("A").relationships["B"]["trust"] - before, 2),
                    w.member("A").alignment.get("B", 0.0))
        out = self.arms(make)
        self.assertGreater(out["open"][0], 0)
        self.assertGreater(out["open"][1], 0)
        self.assertEqual(out["secret"], (0.0, 0.0))

    def test_no_grievance_debt_or_lone_dissent_follows_from_a_vote(self):
        def make(w):
            mo = motion(value="0.35", previous_value=.2, passed=True, void=False, eligible_voters=list("ABCDE"),
                        decision_rule_at_vote="majority", votes={"A": "yes", "B": "no", "C": "yes", "D": "yes", "E": "no"})
            w.policy.tax = .35
            agents._political_obligations(w, record_of(w, mo))
            return {"grievance": [g["reason"] for g in w.member("B").agent_state.get("grievances", [])],
                    "debts": [d["to"] for d in w.member("A").agent_state.get("favor_debts", [])]}
        out = self.arms(make)
        self.assertEqual(out["open"]["grievance"], ["treasury policy enacted over my objection"])
        # The motion carried 3-2 with A, C and D: the proposer owes each of C and D, whose vote was pivotal.
        self.assertEqual(sorted(out["open"]["debts"]), ["C", "D"])
        self.assertEqual(out["secret"], {"grievance": [], "debts": []})

        def dissent(w):
            mo = motion(value="0.35", previous_value=.2, passed=True, void=False, eligible_voters=list("ABCDE"),
                        votes={"A": "yes", "B": "yes", "C": "yes", "D": "yes", "E": "no"})
            w.policy.tax = .35
            agents.update_political(w, record_of(w, mo))
            return [s["motion"] for s in w.member("E").agent_state.get("minority_stands", [])]
        out = self.arms(dissent)
        self.assertEqual(out["open"], ["M1"])
        self.assertEqual(out["secret"], [])

    def test_no_credit_goes_to_a_yes_voter_the_public_cannot_see(self):
        def make(w):
            w.history = [{"offices": {"treasury": "B"}}, {"offices": {"treasury": "B"}}]
            recent = [{"motions": [{"id": "M1", "proposer": "A", "type": "set_policy", "subject": "rate", "value": "0.05",
                                    "passed": True, "votes": {"A": "yes", "C": "yes", "D": "no"}}]}]
            fake = lambda domain, before, now: 2.0 if domain == "prices" else 0.0
            with mock.patch.object(standing, "domain_change", side_effect=fake):
                log = standing.credit_and_blame(w, recent)
            return sorted({row["member"] for row in log if row["domain"] == "prices"})
        out = self.arms(make)
        self.assertEqual(out["open"], ["A", "B", "C"])
        self.assertEqual(out["secret"], ["A", "B"])

    def test_a_yes_vote_on_a_repressive_motion_is_not_a_reputation_charge(self):
        def make(w):
            mo = motion("protest_response", "lethal", passed=True, void=False, votes={"A": "yes", "B": "no"})
            return standing.action_tags_for(w, "A", record_of(w, mo))
        out = self.arms(make)
        self.assertEqual(out["open"], ["repression"])
        self.assertEqual(out["secret"], [])

    def test_a_promise_about_a_vote_is_not_judged_under_a_secret_ballot(self):
        def make(w):
            # Engine 19, AG3: a topic pledge is judged in the month it is made, so the pledge is made in the vote's month.
            w.month = 1
            promise = commitments.record(w, "A", "I will vote for the audit motion", to="B")
            self.assertEqual(promise["normalized"]["topic"], "audit")
            record = {"motions": [{"id": "M1", "proposer": "C", "type": "investigation", "subject": "army",
                                   "value": "open", "summary": "open an audit of the army", "text": "",
                                   "passed": True, "void": False, "withdrawn": False,
                                   "votes": {"A": "yes", "B": "no", "C": "yes"}}], "decisions": {}}
            results = commitments.evaluate(w, record)
            return [r["verdict"] for r in results], w.member("A").promises[-1]["status"]
        out = self.arms(make)
        self.assertEqual(out["open"], (["kept"], "fulfilled"))
        self.assertEqual(out["secret"], ([], "active"))

    def test_the_relationship_text_shows_no_debt_from_a_vote(self):
        def make(w):
            mo = motion(value="0.35", previous_value=.2, passed=True, void=False, eligible_voters=list("ABCDE"),
                        decision_rule_at_vote="majority", votes={"A": "yes", "B": "no", "C": "yes", "D": "yes", "E": "no"})
            w.policy.tax = .35
            agents._political_obligations(w, record_of(w, mo))
            return agents.relationships_text(w, "C")     # C was pivotal, so A owes C a favour
        out = self.arms(make)
        self.assertIn("Colleagues who owe you: Delegate A", out["open"])
        self.assertNotIn("Colleagues who owe you", out["secret"])

    def test_each_delegate_still_knows_its_own_vote_and_the_tally(self):
        def make(w):
            from karamaniya import memory
            mo = motion(value="0.35", previous_value=.2, passed=True, void=False, summary="set tax to 0.35",
                        votes={"A": "yes", "B": "yes", "C": "no", "D": "no", "E": "yes"})
            memory.record_month(w, record_of(w, mo))
            return {m: [x["text"] for x in w.member(m).agent_state.get("memory", []) if x["kind"] == "outvoted"]
                    for m in ("A", "C", "D")}
        out = self.arms(make)
        self.assertEqual(out["secret"], out["open"])
        self.assertEqual(out["secret"]["A"], [])
        self.assertEqual(out["secret"]["C"], ["You were outvoted on set tax to 0.35 (3-2)."])


class TheSecretRunThreeMonths(unittest.TestCase):
    """Seed 1, three months, open and secret, through the council with stand-ins for every seat."""

    @classmethod
    def setUpClass(cls):
        cls.prompts, cls.months, cls.cards, cls.members = {}, {}, {}, {}
        for arm, path in RUNS.items():
            with open(os.path.join(path, "prompts.jsonl"), encoding="utf-8") as f:
                cls.prompts[arm] = [json.loads(line) for line in f]
            cls.months[arm] = RunStore(path).read_log("month")
            with open(os.path.join(path, "scorecard.json"), encoding="utf-8") as f:
                cls.cards[arm] = json.load(f)
            cls.members[arm] = RunStore(path).load_checkpoint()[0].members

    def test_no_prompt_tells_a_delegate_how_a_colleague_voted(self):
        names = {m.id: m.name for m in self.members["secret"]}
        self.assertTrue(any(row["month"] >= 1 for row in self.prompts["secret"]))
        for row in self.prompts["secret"]:
            others = [name for mid, name in names.items() if mid != row.get("member")]
            with self.subTest(month=row["month"], phase=row["phase"], member=row.get("member")):
                self.assertEqual(vote_talk(row["prompt"], others), [])

    def test_no_prompt_quotes_a_vote_reason(self):
        """A colleague's public reason for a vote reveals the vote. The scripted reasons are distinctive phrases;
        no prompt in either arm carries one today, and this keeps it so under the secret arm."""
        reasons = ("assessed against current country conditions", "affects my office and current fiscal",
                   "affects the council and current fiscal", "Charter text must add a distinct protection")
        for row in self.prompts["secret"]:
            with self.subTest(month=row["month"], phase=row["phase"], member=row.get("member")):
                self.assertEqual([r for r in reasons if r in row["prompt"]], [])

    def test_the_open_arm_does_tell_the_audiences_reading_of_a_vote(self):
        """The check above would pass vacuously if the open run never talked about votes at all."""
        self.assertTrue(any("HOW YOUR AUDIENCES WILL READ YOUR VOTE" in row["prompt"]
                            for row in self.prompts["open"]))

    def test_the_tallies_and_results_are_still_told(self):
        voted = [mo for rec in self.months["secret"] for mo in rec.get("motions", []) if mo.get("votes")]
        self.assertTrue(voted)
        self.assertTrue(all(TALLY.fullmatch(mo.get("tally", "")) for mo in voted))
        self.assertTrue(any(TALLY.search(row["prompt"]) for row in self.prompts["secret"] if row["month"] >= 1))

    def test_no_audience_reaction_is_applied(self):
        for member in self.members["secret"]:
            self.assertEqual((member.agent_state or {}).get("vote_reactions", []), [], member.id)
        for rec in self.months["secret"]:
            self.assertEqual(rec.get("vote_costs"), [], rec["month"])

    def test_every_vote_is_recorded_and_matches_the_open_run(self):
        def votes(arm):
            return [(rec["month"], mo["id"], mo.get("votes"), mo.get("tally"), mo.get("passed"))
                    for rec in self.months[arm] for mo in rec.get("motions", [])]
        self.assertTrue(any(mo.get("votes") for rec in self.months["secret"] for mo in rec.get("motions", [])))
        self.assertEqual(votes("secret"), votes("open"))

    def test_the_consensus_counts_equal_the_open_runs(self):
        self.assertEqual(self.cards["secret"]["country"]["vote_division"], self.cards["open"]["country"]["vote_division"])
        keys = ("voted", "yes", "no", "abstain", "losing_side")
        for letter, member in self.cards["open"]["members"].items():
            with self.subTest(member=letter):
                self.assertEqual({k: self.cards["secret"]["members"][letter]["consensus"][k] for k in keys},
                                 {k: member["consensus"][k] for k in keys})

    def test_the_system_prompt_states_the_rule_only_in_the_secret_run(self):
        def read(arm):
            with open(os.path.join(RUNS[arm], "system_prompt.txt"), encoding="utf-8") as f:
                return f.read()
        self.assertIn(prompts.SECRET_BALLOT_RULE, read("secret"))
        self.assertNotIn("Votes are secret", read("open"))

    def test_the_report_names_the_arm(self):
        self.assertEqual(report_data(RunStore(RUNS["secret"]))["run"]["ballot"], "secret")
        self.assertEqual(report_data(RunStore(RUNS["open"]))["run"]["ballot"], "open")


class TheModelMatrix(unittest.TestCase):
    LINEUPS = """
[fast]
seat = [
  { label = "fast-a", provider = "scripted", persona = "democrat" },
  { label = "fast-b", provider = "scripted", persona = "hawk" },
]

[frontier]
seat = [
  { label = "frontier-a", provider = "scripted", persona = "technocrat" },
  { label = "frontier-b", provider = "scripted", persona = "loyalist" },
  { label = "frontier-c", provider = "scripted", persona = "opportunist" },
]
"""

    def test_seeds_and_arms_are_read(self):
        self.assertEqual(matrix.parse_seeds("1-3,7,2"), [1, 2, 3, 7])
        self.assertEqual(matrix.parse_arm("ballot=secret+mandate=crisis"), {"ballot": "secret", "mandate": "crisis"})
        self.assertEqual(matrix.parse_arm("dm_per_turn=2"), {"dm_per_turn": 2})
        with self.assertRaises(ValueError):
            matrix.parse_seeds("3-1")
        with self.assertRaises(ValueError):
            matrix.parse_arm("ballot")

    def test_one_council_file_per_lineup_seed_and_arm(self):
        tmp = tempfile.mkdtemp(prefix="karamaniya-matrix-")
        try:
            lineups_path = os.path.join(tmp, "lineups.toml")
            with open(lineups_path, "w", encoding="utf-8") as f:
                f.write(self.LINEUPS)
            out = os.path.join(tmp, "matrix")
            written = matrix.write_matrix(CONFIG, matrix.load_lineups(lineups_path), [1, 2],
                                          [matrix.parse_arm("ballot=open"), matrix.parse_arm("ballot=secret")], out)
            self.assertEqual(len(written), 8)
            seen = set()
            for path in written:
                cfg = load_config(str(path))
                seen.add((cfg["run"]["matrix_lineup"], cfg["run"]["seed"], cfg["run"]["matrix_arm"]))
                self.assertEqual(cfg["run"].get("ballot", "open"), "secret" if "secret" in path.name else "open")
                self.assertEqual([s["label"] for s in cfg["seats"]],
                                 [s["label"] for s in matrix.load_lineups(lineups_path)[cfg["run"]["matrix_lineup"]]])
            self.assertIn(("frontier", 2, "ballot=secret"), seen)
            self.assertEqual(len(seen), 8)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_compare_groups_finished_runs_by_lineup_and_arm(self):
        table, skipped = matrix.compare([RUNS["open"], RUNS["secret"]])
        self.assertEqual(skipped, [])
        self.assertEqual(sorted(row["arm"] for row in table), ["ballot=open", "ballot=secret"])
        self.assertTrue(all(row["runs"] == 1 for row in table))
        self.assertTrue(all(row["unanimity"] is not None for row in table))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = matrix.main(["--compare", str(RUNS["open"]), str(RUNS["secret"])])
        self.assertEqual(code, 0)
        self.assertIn("unanimity", out.getvalue().splitlines()[0])
        self.assertIn("ballot=secret", out.getvalue())

    def test_help_exits_cleanly(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit) as exc:
                matrix.main(["--help"])
        self.assertEqual(exc.exception.code, 0)
        self.assertIn("--compare", out.getvalue())


if __name__ == "__main__":
    unittest.main()
