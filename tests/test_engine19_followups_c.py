"""World engine 19, the follow-up gaps left after the engine 18 audit fixes (docs/AUDIT_ENGINE18.md, the residual slice).

Each class pins one residual gap found on review of the fixes: it reproduces the gap, asserts the behaviour the fix makes
true, and fails on the code before that fix. No delegate is told what to decide by these tests.
"""
import contextlib
import copy
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import (agents, audits, briefing, causality, decision_context, dilemmas, director, engine,  # noqa: E402
                        foreign, forecasts)
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import annualize, new_world  # noqa: E402

SCRIPTED = os.path.join(ROOT, "council.scripted.toml")
TEMPLATE = os.path.join(ROOT, "karamaniya", "report_template.html")

# Runs the report template's baseline functions (renderBaseline and baselineHeadline) on the data it is given. The functions
# are cut out of the template's own script, so the test runs the code that ships; the DOM is a stub that records what they
# render. node is the only other program involved, and the test is skipped where node is not on the PATH.
BASELINE_HARNESS = r"""
const fs = require("fs");
const [template, dataPath] = process.argv.slice(2);
const src = fs.readFileSync(template, "utf8");
function cut(from, to) {
  const start = src.indexOf(from);
  const end = src.indexOf(to, start + from.length);
  if (start < 0 || end < 0) throw new Error("template marker not found: " + from);
  return src.slice(start, end);
}
const body = [cut("  // ---- helpers", "  // ---- outcome ----"), cut("  // ---- outcome ----", "  function renderHead()"),
  cut("  // ---- the same seed without the models", "  function renderConsensusLine()")].join("\n");
function Node(tag) {
  return { tag, children: [], attrs: {}, className: "", textContent: "", style: { cssText: "" },
    appendChild(child) { this.children.push(child); return child; },
    setAttribute(key, value) { this.attrs[key] = value; },
    replaceChildren(...nodes) { this.children = nodes; } };
}
const hosts = { "baseline-section": Node("section") };
const document = { createElement: Node, createElementNS: (ns, tag) => Node(tag),
  createTextNode: text => ({ tag: "#text", textContent: text, children: [] }), getElementById: id => hosts[id] || null };
function show(node) {
  if (node.tag === "#text") return node.textContent;
  const inner = node.children.length ? node.children.map(show).join("") : node.textContent;
  return `<${node.tag}${node.className ? ` class="${node.className}"` : ""}>${inner}</${node.tag}>`;
}
const data = JSON.parse(fs.readFileSync(dataPath, "utf8"));
const api = new Function("D", "document", body + "\nreturn { renderBaseline, baselineHeadline };")(data, document);
const headline = api.baselineHeadline();
api.renderBaseline();
process.stdout.write(JSON.stringify({ headline: headline ? show(headline) : null, section: show(hosts["baseline-section"]) }));
"""

THIS_RUN = {"approval_final": 0.41, "army_final": 38000, "inflation_mean": 0.031, "outcome": "survived"}


def finished_mode(approval: float = 0.35) -> dict:
    """A mode that reached its outcome, as baseline.compute records it."""
    return {"summary": {"months": 3, "approval_final": approval, "army_final": 40000, "inflation_mean": 0.027,
                        "outcome": "survived"}, "monthly": [], "personas": ["scripted"] * 5, "status": "ok"}


def failed_mode(reason: str, months: int) -> dict:
    """A mode that stopped or never reached its outcome, as baseline.compute records it (RU2)."""
    return {"status": "failed", "reason": reason, "months": months, "summary": {}, "monthly": [],
            "personas": ["hawk"] * 5}


def baseline_file(modes: dict, status: str = "failed") -> dict:
    return {"status": status, "world_engine": "19", "months": 3, "length": 3, "computed": "2026-10-11 10:00",
            "this_run": THIS_RUN, "modes": modes}


def rendered_baseline(baseline: dict) -> dict:
    """What the report's baseline headline and section render for this baseline file: {"headline", "section"} as HTML-like text."""
    tmp = tempfile.mkdtemp(prefix="engine19-followups-report-")
    try:
        harness, data = os.path.join(tmp, "harness.js"), os.path.join(tmp, "data.json")
        with open(harness, "w", encoding="utf-8") as f:
            f.write(BASELINE_HARNESS)
        with open(data, "w", encoding="utf-8") as f:
            json.dump({"baseline": baseline}, f)
        done = subprocess.run(["node", harness, TEMPLATE, data], capture_output=True, text=True, encoding="utf-8",
                              check=True)
        return json.loads(done.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def world(month: int = 3, seed: int = 5):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    w.month = month
    w.events = []
    return w


def veleria_threat(w) -> float:
    return w.foreign["actors"]["veleria"]["threat_perception"]["karamaniya"]


def live_issue(kind: str, truth: dict | None = None) -> dict:
    """An issue as dilemmas.generate raises it, in its first month, with its hidden details set."""
    return {"id": f"I3-{kind}", "kind": kind, "month": 3, "region": None, "target": None, "truth": truth or {},
            "applied": {}, "started": False, "status": "active"}


def scripted_world(months: int = 6, seed: int = 1):
    """A world with `months` months of history from the scripted council (rule-following stand-ins, no model, no network)."""
    cfg = load_config(SCRIPTED)
    raw = {"run": {**cfg["run"], "survey": False, "baseline": False, "seed": seed}, "seat": cfg["seats"]}
    tmp = tempfile.mkdtemp(prefix="engine19-followups-")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            path = new_run(normalize_config(raw, "test"), runs_dir=tmp, name="run", months=months, quiet=True,
                           check=False)
        return RunStore(path).load_checkpoint()[0]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class IssueThreatSurvivesPositions(unittest.TestCase):
    """Audit MI9-f: a leaked plan and a border shooting by our own troops wrote Veleria's threat of Karamaniya directly
    (+.02 and +.03). foreign.positions rebuilds that threat from Veleria's beliefs each month, so the write was lost at the
    next call. The effect now moves the offensive-intent belief the threat reads, so the lift is still there after
    positions(), sized to the same .02 or .03 of threat."""

    def lift_after_positions(self, kind: str, truth: dict | None = None) -> float:
        plain = world()
        foreign.positions(plain)
        hit = world()
        foreign.positions(hit)
        dilemmas._effect(hit, live_issue(kind, truth), True, lambda *a: None)
        foreign.positions(hit)
        return veleria_threat(hit) - veleria_threat(plain)

    def test_a_leaked_plan_still_lifts_veleria_threat_by_two_points_after_positions(self):
        self.assertAlmostEqual(self.lift_after_positions("leaked_plan"), .02, delta=.002)

    def test_a_border_shooting_by_our_own_troops_still_lifts_veleria_threat_by_three_points(self):
        self.assertAlmostEqual(self.lift_after_positions("border_incident", {"perpetrator": "our own troops"}), .03,
                               delta=.002)

    def test_a_border_shooting_by_others_does_not_move_veleria_threat(self):
        self.assertEqual(self.lift_after_positions("border_incident", {"perpetrator": "smugglers"}), 0)


class SnapshotRoundsRelationshipFigures(unittest.TestCase):
    """Audit AG1-f: AG1 keeps relationship values at full precision, and snapshot copied them raw into every month's record,
    so each float carried about 17 digits in the run's files. The copy now rounds its figures to 2 decimals; the stored
    relationship keeps its full precision and is not changed by taking a snapshot."""

    def member_world(self):
        w = new_world(5, 36)
        agents.ensure(w)
        a, b = w.members[0], w.members[1]
        a.relationships[b.id] = agents._relationship(w, a.id, b.id)
        agents._change(a.relationships[b.id], month=4, reason="test", trust=-0.3712, respect=0.0437, fear=1.0123456789)
        agents._change(a.relationships[b.id], month=5, reason="test", trust=-0.1, resentment=2.345678)
        return w, a, b

    def test_a_snapshot_relationship_float_has_at_most_two_decimals(self):
        w, a, b = self.member_world()
        record = agents.snapshot(w)[a.id]["relationships"][b.id]
        floats = {key: value for key, value in record.items() if isinstance(value, float)}
        self.assertTrue(floats)
        for key, value in floats.items():
            self.assertEqual(value, round(value, 2), key)
        for event in record["events"]:
            for change in event["changes"].values():
                for figure in change.values():
                    self.assertEqual(figure, round(figure, 2))

    def test_the_stored_relationship_keeps_full_precision_and_a_snapshot_does_not_change_it(self):
        w, a, b = self.member_world()
        stored = a.relationships[b.id]
        before = copy.deepcopy(stored)
        record = agents.snapshot(w)[a.id]["relationships"][b.id]
        self.assertEqual(stored, before)
        self.assertEqual(stored["trust"], 49.5288)
        self.assertEqual(stored["fear"], 6.0123456789)
        record["events"][0]["changes"]["trust"]["to"] = 0
        self.assertNotEqual(stored["events"][0]["changes"]["trust"]["to"], 0)


def stepped_world(months: int, seed: int = 7):
    """A world run for `months` months with no council or cabinet action, so the economy's own dynamics show."""
    w = new_world(seed, 36)
    with mock.patch.object(director, "act", lambda world, *_a, **_k: setattr(world.dip, "inbox", [])):
        for _ in range(months):
            engine.begin_month(w)
            engine.step(w)
    return w


def audit_world(human_factor: bool, seed: int = 5):
    """The armed world of the infra tests (army and navy held), with an audit of the army ordered by B."""
    w = new_world(seed, 36, human_factor=human_factor)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    audits.open_audit(w, "army", "B", "Investigate the army procurement office.", {"B": "yes"})
    return w


def twelve_months(w) -> list:
    """Twelve months of engine steps with no council action; returns the kinds of the events they raised."""
    kinds = []
    for _ in range(12):
        engine.begin_month(w)
        engine.step(w)
        kinds += [e["kind"] for e in w.events]
    return kinds


class NoPsychologyFromAnAuditWithoutTheHumanFactor(unittest.TestCase):
    """Audit MI5-f: an audit's consequences wrote the delegates' standing (standing.reputation_effect creates it), and ordering
    an audit charged the proposer's capital (standing.spend_capital creates it). A run without the human factor has no
    delegate psychology (RU5), so these are guarded on the human factor. The audit's finding and the public event still
    happen without it."""

    def test_a_twelve_month_run_with_an_audit_writes_no_standing_grievances_or_relationships(self):
        w = audit_world(human_factor=False)
        twelve_months(w)
        for m in w.members:
            with self.subTest(member=m.id):
                self.assertNotIn("standing", m.agent_state)
                self.assertFalse(m.agent_state.get("grievances"))
                self.assertEqual(m.relationships, {})

    def test_an_audit_that_reaches_a_verdict_neither_crashes_the_run_nor_is_lost_without_the_human_factor(self):
        """Seed 6's audit reaches a verdict whose consequences used to write standing into a member with no traits, and
        the run died in relationship code (KeyError 'traits')."""
        w = audit_world(human_factor=False, seed=6)
        kinds = twelve_months(w)
        self.assertIn("audit_report", kinds)
        self.assertEqual(len(audits.state(w)["done"]), 1)
        self.assertNotEqual(audits.state(w)["done"][-1]["verdict"], "inconclusive")

    def test_the_same_audit_with_the_human_factor_writes_the_proposers_standing(self):
        w = audit_world(human_factor=True)
        twelve_months(w)
        self.assertIn("standing", w.member("B").agent_state)


class DeflationIsNotHighInflation(unittest.TestCase):
    """Audit EC10-f (checked; no code change was needed): a Month-1 fall of 3% in prices is about -31% annualised, and
    causality.regime labels it DEFLATION, not HIGH_INFLATION. The engine sets econ.infl from the CPI change
    (economy.money_and_prices) and then calls causality.regime(w), which is the path this test takes."""

    def test_a_three_percent_fall_in_month_one_is_deflation_not_high_inflation(self):
        w = new_world(4, 36)
        w.foreign = foreign.initial_state(w.seed)
        w.month = 1
        w.history.append({"month": 0, "cpi": .97, "gdp_idx": 1.0})
        w.econ.cpi = .97
        w.econ.infl = .97 / 1.0 - 1
        self.assertLess(annualize(w.econ.infl), causality.DEFLATION_ANNUAL)
        label = causality.regime(w)
        self.assertEqual(label, causality.DEFLATION)
        self.assertNotEqual(label, causality.HIGH_INFLATION)


class PanelInflationNamesItsWindow(unittest.TestCase):
    """Audit TO1-f: the forecast panel asked about "reported annual inflation" without the window its figure covers. The
    TO1 fix made the prompts and the briefing name that window (briefing._yoy_window); the panel question now uses the
    same words. In Month 3 the window is the change so far, annualised over two months, so the question does not claim a
    year."""

    def test_in_month_three_the_inflation_question_names_the_window_and_does_not_claim_a_year(self):
        w = stepped_world(2)
        label = forecasts.panel_questions(w, "A")["inflation_up"][0]
        self.assertIn(briefing._yoy_window(w), label)
        self.assertIn("annualised over 2 months", label)
        self.assertNotIn("annual inflation", label)
        self.assertNotIn("year", label)


class TaxChangeComplianceCutReachesRevenue(unittest.TestCase):
    """Audit IN-L1-f: standing.implementation_effects wrote a tax change's compliance cut straight to econ.compliance, and
    economy.fiscal recomputes compliance from its formula each month, so the cut never reached revenue. It now goes through
    economy.cut_compliance, as the other shocks do (IN-L1), and the cut shows in that month's fiscal compliance."""

    @staticmethod
    def compliance_after_a_month(tax_change: bool) -> float:
        w = new_world(4, 36)
        w.foreign = foreign.initial_state(w.seed)
        w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
        w.month = 6
        w.institutions["capacity"] = {"treasury": .3}   # a weak treasury: the tax change's cut is .02 * (.7 - .3)
        if tax_change:
            w.institutions["changed_levers"] = {"tax": .2}
        engine.begin_month(w)
        engine.step(w)
        return w.econ.compliance

    def test_a_tax_change_into_a_weak_treasury_lowers_the_compliance_that_taxes_use(self):
        cut = self.compliance_after_a_month(False) - self.compliance_after_a_month(True)
        self.assertAlmostEqual(cut, .008, delta=.0005,
                               msg="the tax change's compliance cut did not reach fiscal compliance")


@unittest.skipUnless(shutil.which("node"), "node runs the report template's baseline code in this test")
class FailedBaselineModesStillShowTheirFigures(unittest.TestCase):
    """Audit RU2-f: a baseline file in which a mode stopped has status "failed". The report then printed "There are no
    months to compare yet.", hid the figures of the modes that finished and gave the wrong reason. Now the finished modes
    are shown as before, each failed mode is stated with the reason baseline.py recorded, and the no-months line is printed
    only when no mode has months."""

    def test_one_finished_and_one_failed_mode_shows_the_finished_figures_and_names_the_failure(self):
        out = rendered_baseline(baseline_file({"scripted": finished_mode(0.35),
                                               "hawk": failed_mode("stopped from the control room", 2)}))
        section = out["section"]
        self.assertIn("<table", section)
        self.assertIn("Rule-following stand-ins", section)
        self.assertIn("35%", section)
        self.assertIn("All-hawk rule council failed after 2 months: stopped from the control room.", section)
        self.assertNotIn("<th>All-hawk rule council</th>", section)
        self.assertNotIn("There are no months to compare yet.", section)
        self.assertIn("approval 41% (scripted 35%)", out["headline"])

    def test_a_failed_file_with_no_months_in_any_mode_says_so_and_states_each_failure(self):
        out = rendered_baseline(baseline_file({"hawk": failed_mode("did not reach its outcome", 0),
                                               "dove": failed_mode("stopped from the control room", 0)}))
        section = out["section"]
        self.assertIn("There are no months to compare yet.", section)
        self.assertIn("All-hawk rule council failed: did not reach its outcome.", section)
        self.assertIn("All-dove rule council failed: stopped from the control room.", section)
        self.assertNotIn("<table", section)

    def test_a_failed_mode_with_months_is_not_reported_as_no_months(self):
        out = rendered_baseline(baseline_file({"hawk": failed_mode("stopped from the control room", 2)}))
        self.assertNotIn("There are no months to compare yet.", out["section"])
        self.assertIn("All-hawk rule council failed after 2 months: stopped from the control room.", out["section"])

    def test_a_file_whose_modes_all_finished_renders_every_mode_as_before(self):
        out = rendered_baseline(baseline_file({"scripted": finished_mode(0.35), "hawk": finished_mode(0.30)}, status="ok"))
        section = out["section"]
        self.assertIn("Rule-following stand-ins", section)
        self.assertIn("All-hawk rule council", section)
        self.assertNotIn("failed:", section)
        self.assertNotIn("There are no months to compare yet.", section)

    def test_the_other_statuses_keep_their_messages(self):
        cases = {"no_months": ("There are no months to compare yet.", {}),
                 "engine_mismatch": ("This run was made by world engine 18.", {"run_world_engine": "18"})}
        for status, (text, extra) in cases.items():
            with self.subTest(status=status):
                out = rendered_baseline({**baseline_file({}, status=status), **extra})
                self.assertIn(text, out["section"])
                self.assertNotIn("failed", out["section"])


class V1PublicBriefingPrintsThePublishedOutput(unittest.TestCase):
    """Audit TO8-f: the v1 public briefing drew its own noisy output figure, while the canonical block prints
    briefing.published_index. Its Output line now prints the published figure, as public_v2 does, and keeps the draw the
    line took (Noise.skip), so the unemployment figure drawn after it keeps its value."""

    @classmethod
    def setUpClass(cls):
        cls.w = scripted_world(months=6)

    def test_the_v1_public_briefing_prints_the_canonical_output_in_several_months(self):
        for month in range(6, 12):
            self.w.month = month
            shown = re.search(r"Output: (\d+) \(start = 100\)", briefing.public(self.w))
            canon = re.search(r"output (\d+) \(start = 100\)",
                              decision_context.canonical_hard_state_v2(self.w, "decision"))
            with self.subTest(month=month):
                self.assertEqual(shown.group(1), canon.group(1))

    def test_the_output_line_prints_published_index_and_the_unemployment_after_it_does_not_move(self):
        self.w.month = 8
        plain = briefing.public(self.w)
        with mock.patch.object(briefing, "published_index", return_value=1.23):
            patched = briefing.public(self.w)
        self.assertIn("Output: 123 (start = 100)", patched)
        unemployment = r"Unemployment: (\S+)\."
        self.assertEqual(re.search(unemployment, patched).group(1), re.search(unemployment, plain).group(1))


if __name__ == "__main__":
    unittest.main()
