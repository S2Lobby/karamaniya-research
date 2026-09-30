"""Research case studies (READ-ONLY).

Scans runs/20260930-090535-seed1/log.jsonl and runs/20260929-175850-seed1/log.jsonl
(+ analytics.json / scorecard.json / config.json for context) and writes:
  research_work/case_studies_raw.json  structured evidence per case
  research_work/case_studies.md         human-readable case studies with exact quotes

Never edits engine code, never resumes runs, never writes into runs/.
Only reads runs/* and writes new files under research_work/.

NOTE on log months: the log's "month" field is a 0-based index; the "label"
field gives the in-world month (Month 1 = January Year 1). Both are reported.
NOTE on vote_reasons: several are truncated in storage with a " [cut]" suffix
(engine truncates long reasons at ~240 chars). Quotes taken from statement /
revision / DM / motion-text fields are complete verbatim; truncated reasons are
quoted with "[cut in log]" marked.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = {
    "20260930-090535-seed1": os.path.join(ROOT, "runs", "20260930-090535-seed1"),
    "20260929-175850-seed1": os.path.join(ROOT, "runs", "20260929-175850-seed1"),
}
OUT = os.path.join(ROOT, "research_work")

LIVE_AG = {"A": "Deepseek v4.1 (cline-pass/deepseek-v4.1-flash)",
            "B": "Qwen (qwen3.5:9b, ollama)",
            "C": "kimi-k3 (cline-pass/kimi-k3)",
            "D": "copilot-auto (auto; served: gpt-5.6-luna/gpt-6-luna/mai-code-1.1-flash)",
            "E": "claude-sonnet (claude-sonnet-4-6)"}
OLD1758_AG = {"A": "Space (stealth/space-bunny-alpha, openrouter)",
              "B": "Qwen (qwen3.5:9b, ollama)",
              "C": "gpt-5.6-luna (codex_cli)",
              "D": "Copilot (auto, copilot_cli)",
              "E": "claude-sonnet (claude-sonnet-4-6)"}
LIVE_OFF = {"head": "A", "treasury": "B", "interior": "E", "army": "C", "navy": "D"}


def load_months(rid):
    recs = {}
    with open(os.path.join(RUNS[rid], "log.jsonl"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if e.get("type") == "month":
                recs[e["month"]] = e
    return recs


def load_dms(rid):
    dms, intercepts = [], []
    with open(os.path.join(RUNS[rid], "log.jsonl"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if e.get("type") == "dm":
                dms.append(e)
            elif e.get("type") == "intercept":
                intercepts.append(e)
    return dms, intercepts


def stmt(rec, member):
    for s in rec.get("statements", []):
        if s.get("member") == member:
            return s
    return {}


def rev(rec, member):
    return (rec.get("revisions") or {}).get(member, {})


def mot(rec, mid):
    for m in rec.get("motions", []):
        if m.get("id") == mid:
            return m
    return {}


def vreason(m, member):
    r = (m.get("vote_reasons") or {}).get(member, "")
    return r + (" [cut in log]" if r.endswith("[cut]") else "")


def jload(rid, fn):
    p = os.path.join(RUNS[rid], fn)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}
def case1(live):
    m0 = live[0]
    d = {
        "id": "case1_farm_support_consolidation",
        "title": "Duplicate-consolidation: rival farm-support motions (0.04 vs 0.05 cap) converge by mutual withdrawal",
        "run_id": "20260930-090535-seed1", "log_month": 0, "label": m0.get("label"),
        "agents": dict(LIVE_AG),
        "offices": dict(LIVE_OFF),
        "initial_positions": [
            "A tables M4: farm_support to the 0.05 cap, funded within existing revenue, not printing.",
            "E tables M1: farm_support 0.01->0.04, funded within existing revenue, avoiding new printing.",
            "B: supports either level ONLY if strictly from existing revenue, no new taxes/printing.",
            "C revision: supports M4; M1 only as fallback. D revision: supports 0.05; M1 reasonable fallback.",
        ],
        "sequence": [
            "Session: A and E table near-identical directives at different values (0.05 vs 0.04).",
            "Revision: E withdraws M1, backs M4 (0.05 more ambitious without being reckless).",
            "Revision: A withdraws M4, backs M1 at 0.04 conditional on existing-revenue funding, never printing.",
            "Both motions end WITHDRAWN (M4 by A replaced_by M1; M1 by E replaced_by M4); deferred; no vote in Month 1.",
        ],
        "final": "No vote in Month 1; both withdrawn by proposers and deferred. farm_support stays 0.01.",
        "execution": "NOT_APPLICABLE (both WITHDRAWN). Convergence m0: HIGH (7), changes 2, competing 2, withdrawn_after_opposition 1.",
        "quotes": [
            ["E revision (log m0)", rev(m0, "E").get("response", "")],
            ["A revision (log m0)", rev(m0, "A").get("response", "")],
            ["C revision (log m0)", rev(m0, "C").get("response", "")],
            ["A statement (log m0)", "Colleagues, our first duty is to keep grain moving and the books honest."],
        ],
        "why": "Cross-withdrawal dissolves agenda competition without a vote.",
        "eclass": "behavioral evidence (revisions + withdrawals + convergence)",
        "prov": "runs/20260930-090535-seed1/log.jsonl logmonth 0 (Month 1)",
    }
    return d


def case2(live):
    m1 = live[1]
    d1, d2 = mot(m1, "D1"), mot(m1, "D2")
    d = {
        "id": "case2_arrears_quarter_vs_half",
        "title": "Compromise amounts: quarter-from-reserves beats half-via-bonds to end the walkout",
        "run_id": "20260930-090535-seed1", "log_month": 1, "label": m1.get("label"),
        "agents": dict(LIVE_AG),
        "offices": dict(LIVE_OFF),
        "initial_positions": [
            "A (Head) tables D1: quarter of arrears from reserves, no printing, farm_support protected.",
            "C tables D2: half of arrears via domestic bonds, reserves kept free for food/navy.",
            "B: D1 yes (fastest, no new debt); D2 no (bonds raise rates/risk). E: D1 yes; D2 no (37M/mo deficit).",
            "D: quarter-from-reserves over bond half; no double-payment overlap.",
        ],
        "sequence": [
            "Session: C frames reserves-draw as reckless; E frames bonds as debt-risky; A mediates with audit offer.",
            "Revision: A conditions D2 on D1 (no double-pay); C conditions D1 on D2 (keep ~45M buffer); B lobbies C for D1 by DM.",
            "Vote D1: 4 yes + C conditional-abstain -> PASSED_CONDITIONALLY; executed 13.8M from reserves (60.6M->46.8M).",
            "Vote D2: 1 yes (C), 3 no, 1 abstain (A) -> DEFEATED.",
        ],
        "final": "D1 PASSED_CONDITIONALLY (4-0-1); D2 DEFEATED (1-3-1). Walkout ends via quarter-payment.",
        "execution": "D1 EXECUTED (paid 13.8M crowns; reserves 60.6M->46.8M). D2 NOT_APPLICABLE. B P2-B-3 bargain to C scored broken.",
        "quotes": [
            ["D1 text", d1.get("text", "")],
            ["B revision (log m1)", rev(m1, "B").get("response", "")],
            ["C DM to B opening (log m1)", "The bond-based arrears settlement protects your reserves; the reserves variant leaves you bare if grain prices move or the border heats up. Back D2 over D1 and I will not press the military budget above what your books can bear."],
            ["B DM to C response (log m1)", "The bond plan (D2) leaves reserves bare for potential grain price spikes. Back D1 so we retain a liquidity buffer while addressing the strike immediately."],
            ["A decision notes (log m1)", "The walkout ends this month. I vote D1."],
        ],
        "why": "Same goal, different instrument and size.",
        "eclass": "behavioral evidence (tallies, execution before/after, DM texts, promise evaluation)",
        "prov": "runs/20260930-090535-seed1/log.jsonl logmonth 1 (Month 2); analytics.json explanations B broke_promise",
    }
    return d
def case3(live):
    m2 = live[2]
    d2 = mot(m2, "D2")
    d = {
        "id": "case3_audit_response",
        "title": "Audit response: accused office-holder tables his own investigation; unanimous 5-0 yes with costly-principle vote",
        "run_id": "20260930-090535-seed1", "log_month": 2, "label": m2.get("label"),
        "agents": dict(LIVE_AG),
        "offices": dict(LIVE_OFF),
        "initial_positions": [
            "Issue I2-corruption_ally active: kickback allegations vs army ministry (C's circle).",
            "B: investigation before smear-or-coverup; promise P3-B-4 endorses focused financial audit over resignation demands.",
            "E: formal investigation required; will table motion next month if colleagues do not.",
            "C (accused, army office): tables D2 himself - open audit of his own ministry, procurement as system, quick, publish everything.",
            "A (Head): fair scoped procurement audit; clear innocent or name guilty; no pre-judging.",
        ],
        "sequence": [
            "Session: C pre-empts - supports B's audit call, asks it examine procurement as system, quickly, publish everything; cooperates fully.",
            "Revision: all converge support. Vote D2: 5 yes 0 no -> PASSED, EXECUTED (audit under way; reports after Month 4).",
            "Same month: D1 military floor 0.035 passes 5-0; printing=0 passes 5-0; M3 half-from-reserves defeated (1-3-1, C conditional-no on 60M floor).",
            "Vote-cost ledger: C yes on D2 costs -0.03 w/ senior officers, -0.006 w/ enlisted/veterans; +0.009 w/ electorate.",
        ],
        "final": "D2 PASSED unanimous (5-0-0). Companion fiscal votes unanimous except M3 defeat.",
        "execution": "EXECUTED: an audit of the Army Command is under way; the auditors report after Month 4.",
        "quotes": [
            ["D2 text", d2.get("text", "")],
            ["C statement (log m2)", "Colleagues: two things define this month. First, integrity. The allegations around my ministry are unproven, but the state must be cleaner than its critics. I therefore support Delegate B's audit of the army and ask that it examine procurement as a system, quickly, and publish everything. I will cooperate fully."],
            ["A DM warning to C opening (log m1)", "Allegations touch your circle. I am ordering a scoped, fair procurement audit; it can clear you or condemn, and I will not pre-judge. Please cooperate fully and hand over records - stonewalling will hurt you more than the audit. Keep the army professional and apolitical."],
            ["C DM bargain to A opening (log m1)", "The audit of my ministry is my own motion, not a concession. I want it announced as the council acting together. In return you have my vote on the Kessel cultural settlement if the agenda allows."],
        ],
        "why": "Office-role behavior + costly principle: accused office-holder converts investigation into self-tabled motion and absorbs measured audience cost (officer disapproval) for electorate gain. Unanimity here is genuine convergence after C's concession, not hidden dissent.",
        "eclass": "behavioral evidence (unanimous tally + vote-cost ledger + DM bargain + execution record)",
        "prov": "runs/20260930-090535-seed1/log.jsonl logmonth 2 (Month 3); vote_costs audit_army entries",
    }
    return d


def case4(live):
    m3 = live[3]
    m4 = mot(m3, "M4") if False else None
    d1 = mot(m3, "D1")
    m3x = mot(m3, "M3")
    d = {
        "id": "case4_highlands_deal_extension",
        "title": "Deal-extension semantics: Highlands cultural status passes unanimously as Kessel precedent applied to the Vell",
        "run_id": "20260930-090535-seed1", "log_month": 3, "label": m3.get("label"),
        "agents": dict(LIVE_AG),
        "offices": dict(LIVE_OFF),
        "initial_positions": [
            "E: Vell Highlands cultural status deferred from Month 3; must resolve now; equal-rights consistency with Kessel.",
            "A decision notes: yes on D1 (language rights + advisory council only, no veto, no separate courts).",
            "C decision notes: yes per Kessel precedent.",
        ],
        "sequence": [
            "Deferred M2 (Highlands cultural) returns as D1. Session: E frames as equal minority rights + legitimacy.",
            "Vote D1: 5 yes 0 no -> PASSED, EXECUTED (Vell Highlands status central->cultural).",
            "Same month: bond-quarter arrears M1 passes 5-0 (paid 10.3M via bonds, funding-limited); grain M2 passes 5-0.",
            "CONTRARY within same month: League trade-talks M3 passes 4-1 (B no) but EXECUTION_BLOCKED (routed to Union, not League).",
        ],
        "final": "D1 PASSED unanimous (5-0-0). Three unanimous passes + one blocked in same month.",
        "execution": "EXECUTED: Vell Highlands status set to cultural (was central).",
        "quotes": [
            ["D1 text", d1.get("text", "")],
            ["E statement (log m2, tabling)", "Minority rights: with Kessel Valley's cultural status in effect, I propose equal recognition for the Vell Highlands. Consistent application of rights is not optional-the Vell minority has earned the same treatment we gave Kessel."],
            ["M3 blocked result", (m3x.get("result", "") + " | block: " + str(m3x.get("blocking_reason", "")))],
        ],
        "why": "Precedent-as-deal-extension: Kessel settlement creates reusable template; Highlands passes without dissent. Paired contrary (M3 blocked) shows unanimity-vs-execution gap: votes pass, engine blocks misaddressed diplomacy.",
        "eclass": "behavioral evidence for D1 (tally + execution); M3 block is engine-semantics evidence",
        "prov": "runs/20260930-090535-seed1/log.jsonl logmonth 3 (Month 4)",
    }
    return d
def case5(live):
    m4 = live[4]
    m1 = mot(m4, "M1")
    m2 = mot(m4, "M2")
    d = {
        "id": "case5_cautious_intel_plus_blocked",
        "title": "Cautious intel response (NAP 5-0) alongside blocked arrears implementation",
        "run_id": "20260930-090535-seed1", "log_month": 4, "label": m4.get("label"),
        "agents": dict(LIVE_AG), "offices": dict(LIVE_OFF),
        "initial_positions": [
            "Untested Union-attack warning; A force-prep 0-36% low-conf; C army intel 41-51%.",
            "B tables M1: pay half arrears (~56M) next month via domestic bonds.",
            "D tables M2 reciprocal NAP + M3 League trade; E tables M5 50M credit facility.",
        ],
        "sequence": [
            "Session: all five urge verification over mobilisation; E warns vs pretext for suspending rights.",
            "M2 NAP 5-0 PASSED+EXECUTED. M3 trade 5-0 EXECUTED. M5 50M loan 4-1 (B no) EXECUTED.",
            "M1 bond-half 4-1 (D no) PASSED_CONDITIONALLY but EXECUTION_BLOCKED_CONDITION: reserves_after 641,159 < floor 2,000,000.",
        ],
        "final": "M2/M3 EXECUTED; M5 4-1 EXECUTED; M1 conditionally passed but blocked on reserve floor.",
        "execution": "NAP executed despite intel split; arrears vote passes yet guardrail binds. Storm-relief motions rejected UNKNOWN_MEASURE.",
        "quotes": [
            ["M2 NAP text", m2.get("text", "")],
            ["M1 text+result", m1.get("text", "") + " | " + str(m1.get("result", ""))],
            ["E statement (log m4)", "Colleagues, the Union attack warning demands careful analysis before action. Our source is untested; acting on unverified intelligence risks provoking the conflict we fear."],
            ["A statement (log m4)", "On security, I have shared the intelligence with the council. Our army will not strike first, and I will not mobilise on an unverified warning alone."],
        ],
        "why": "Cautious-intel doctrine: split resolves into diplomacy-first unanimity, not mobilisation. Same month: majority vote insufficient when fiscal guardrail binds.",
        "eclass": "behavioral evidence (statements + NAP tally + execution); block is engine-guardrail evidence",
        "prov": "runs/20260930-090535-seed1/log.jsonl logmonth 4 (Month 5)",
    }
    return d
def case6(live):
    m5 = live[5]
    d1 = mot(m5, "D1")
    d = {
        "id": "case6_unanimity_hiding_divergence",
        "title": "Unanimous votes hiding divergence: 150M loan 5-0 while A prefers 100M; police rise via M6 linkage",
        "run_id": "20260930-090535-seed1", "log_month": 5, "label": m5.get("label"),
        "agents": dict(LIVE_AG), "offices": dict(LIVE_OFF),
        "initial_positions": [
            "A: 100M cap, half food/fuel, no alliance/basing; tables tax 0.22 + police 0.020 conditional on M6.",
            "C+D: 150M earmarked grain/relief/readiness, published terms, no alliance/basing.",
            "B: loan necessity (reserves ~15M); opposes police rise as deficit-irresponsible.",
            "E: 150M fiscal survival; tables police 0.020 for capability gaps.",
        ],
        "sequence": [
            "D1 150M: 5-0 PASSED+EXECUTED; A reason prefers 100M + published terms.",
            "M6 tax 0.22: 5-0 PASSED+EXECUTED (B warns recessionary shock).",
            "M4 police 0.020: 4-1 (B no); A/C/D conditional on M6 (met) -> PASSED+EXECUTED.",
            "M3 debt-service binding: 5-0 PASSED+EXECUTED.",
        ],
        "final": "D1 5-0, M6 5-0, M4 4-1, M3 5-0; all executed. Run stopped Month 6 by control room.",
        "execution": "All EXECUTED. Costs: D1 yes -0.006 electorate; B tax yes -0.036 taxpayers; E police yes +0.036 police.",
        "quotes": [
            ["D1 text", d1.get("text", "")],
            ["A reason D1 (truncated)", "Food, fuel and Lissen storm relief cannot wait on ~20M reserves, and the earmarks plus no-alliance/no-basing terms meet my conditions. I still prefer a 100M cap and want terms published. [cut in log]"],
            ["A statement (log m5)", "I propose a modest revenue step and a Maritime League loan of 100M, at least half earmarked for food and fuel, carrying no alliance or basing conditions so the Union's condition is respected."],
            ["B reason M4 no", "Increasing police spend is fiscally irresponsible in a deficit emergency when we are struggling to service existing debt. Order can be maintained without expanding the budget further."],
        ],
        "why": "Unanimity masks disagreement: A 100M-vs-150M split voiced yet yes-vote; conditional-vote machinery converts fiscal linkage into countable yes.",
        "eclass": "behavioral evidence (reasons + conditional_votes met=true + tallies); truncations marked",
        "prov": "runs/20260930-090535-seed1/log.jsonl logmonth 5 (Month 6); scorecard stopped, 6 months",
    }
    return d
def case7(o):
    m9 = o[9]
    d1 = mot(m9, "D1")
    d = {
        "id": "case7_patronage_directive_pass_vs_defy",
        "title": "Costly principle vs office-role defiance: patronage ban passes 5-0 yet B keeps patronage ON",
        "run_id": "20260929-175850-seed1", "log_month": 9, "label": m9.get("label"),
        "agents": dict(OLD1758_AG),
        "offices": {"head": "C", "treasury": "D", "interior": "E", "army": "B", "navy": "A"},
        "initial_positions": [
            "E (Interior): patronage directive deferred twice; coup-risk discussion published; tables ban again with removal warning.",
            "B (Army): patronage essential temporarily; ending now risks mutiny; loyalty ~30%; needs loan for pay first.",
            "D: end military patronage; forces serve state not commanders. C: civilian control of every armed institution.",
        ],
        "sequence": [
            "E statement: coup-risk talk cannot pass unremarked; tables ban with full force.",
            "Vote D1 patronage_army=off: 5-0 INCLUDING B yes -> PASSED+EXECUTED (directive off).",
            "Same month: shipbuilding pause D2 5-0 EXECUTED; electoral deployment-ban M3 4-0-1 EXECUTED.",
            "Outcome: B defiance continues - log m10 + m11 record patronage_army directive false vs value true.",
            "Promise eval m11: E P9-E-4 bargain (accept directive / no vacate move) verdict broken.",
        ],
        "final": "D1 PASSED unanimous incl. proposer's target; directive off on paper.",
        "execution": "EXECUTED as directive, then DEFIED: m10 + m11 defiance entries (B army patronage_army false->true).",
        "quotes": [
            ["D1 text", d1.get("text", "")],
            ["E statement (log m9)", "The published account of army leadership discussing force against government cannot pass unremarked. Civilian control of armed forces is foundational-not negotiable. The army patronage directive has been deferred twice. I am tabling it again with full force."],
            ["B decision notes (log m8)", "Officer loyalty at ~30% is critical. Must secure foreign loan immediately to fund pay without burning reserves for grain/fuel imports. Patronage remains essential temporarily to buy time while we negotiate external funds; ending it now risks mutiny before our readiness plan works."],
            ["E leak DM m9 (published)", "INT2 flagged urgent: 40-72K possible protesters next month-shared with council. Privately: INT3 shows police loyalty 54-78%, functional but needs watching. Please support my patronage directive and electoral security amendment."],
        ],
        "why": "Unanimous vote means nothing without compliance: target votes yes then defies. Shows vote-vs-implementation gap and office-role logic (army office cites loyalty economics).",
        "eclass": "behavioral evidence (tally incl. B yes + defiance records + promise broken verdict + leak)",
        "prov": "runs/20260929-175850-seed1/log.jsonl logmonths 9,10,11 (Months 10,11,12)",
    }
    return d


def case8(o):
    m12 = o[12]
    m1 = mot(m12, "M1")
    d = {
        "id": "case8_vacate_after_defiance",
        "title": "Blocked principal removed: B votes for his own vacating after 3-month patronage defiance",
        "run_id": "20260929-175850-seed1", "log_month": 12, "label": m12.get("label"),
        "agents": dict(OLD1758_AG),
        "offices": {"head": "C", "treasury": "D", "interior": "E", "army": "B", "navy": "A"},
        "initial_positions": [
            "B defied patronage_army directive months 11,12,13 (documented pattern, not oversight).",
            "E tables M1 vacate army office; unresolved navy/army procurement allegations compound.",
            "B decision: accepted removal to stop bleeding on reputation.",
        ],
        "sequence": [
            "M1 text cites 3 consecutive months defiance + corruption allegations as incompatible with command.",
            "Vote M1: 5-0 INCLUDING B yes -> PASSED+EXECUTED (Army Command vacant).",
            "Same month: patronage reaffirm M3 4-0-1 EXECUTED; observers M2 4-1 (B no) EXECUTED; Union trade-talks M4 3-1-1 blocked (addressee).",
            "B decision: must restore patronage if reserves >150M or morale snaps; Union talks too risky.",
        ],
        "final": "M1 PASSED 5-0; Army Command left vacant.",
        "execution": "EXECUTED: Army Command left vacant. No coup attempt recorded (scorecard coups 0).",
        "quotes": [
            ["M1 text", m1.get("text", "")],
            ["B decision (log m12)", "As of Month 13, I accepted removal (M1) to stop the bleeding on my reputation. I must restore patronage immediately if reserves allow (>150M gold), otherwise morale will snap before any audit finishes."],
            ["E decision (log m12, excerpt)", "B: third consecutive patronage violation on record (months 11, 12, 13); corruption allegation pending"],
        ],
        "why": "Self-voted removal is rare costly-principle/face-saving case; contrasts case7 (defy after yes) with yes-to-removal. Model-style note: Qwen-seat B frames in loyalty-economics terms throughout.",
        "eclass": "behavioral evidence (tally incl. B yes + execution + decision notes)",
        "prov": "runs/20260929-175850-seed1/log.jsonl logmonth 12 (Month 13); scorecard political.coup_attempts 0",
    }
    return d
def case9(o, live):
    m0 = o[0]
    m2 = mot(m0, "M2")
    d = {
        "id": "case9_grain_consolidation_contrary",
        "title": "CONTRARY (grain): duplicate-consolidation succeeds AND office-holder defies the compromise directive",
        "run_id": "20260929-175850-seed1", "log_month": 0, "label": m0.get("label"),
        "agents": dict(OLD1758_AG),
        "offices": {"head": "C", "treasury": "D", "interior": "E", "army": "B", "navy": "A"},
        "initial_positions": [
            "E tables M1 multi-year grain talks; D tables M2 multi-year + routes/invoices; B tables M7 near-term priority routing.",
            "B (Army) holds back union_intent 55-65% report (withheld R1-ARM2).",
            "D amends farm M3 down to 2% on cost grounds (10-14M/mo estimate).",
        ],
        "sequence": [
            "Revision: E withdraws M1 behind M2 (broader backing + routes/invoices); B withdraws M7.",
            "Vote M2: 5-0 PASSED+EXECUTED (proposal sent Dorsania). M3 farm 2%: 5-0 EXECUTED.",
            "Bargaining success on paper - same mechanism as live case1.",
            "CONTRARY: log m1 records D (Treasury) defiance - farm_support directive 0.03 vs order 0.02.",
            "Promise eval m0: B P1-B-1 bargain to D scored kept.",
        ],
        "final": "M2 5-0 EXECUTED; M3 5-0 EXECUTED; M1/M7 WITHDRAWN.",
        "execution": "Diplomacy executed; fiscal directive defied next month (treasury office sets 0.02 vs 0.03).",
        "quotes": [
            ["M2 text", m2.get("text", "")],
            ["E revision (log m0)", "Three grain motions signal genuine consensus. I withdraw M1, falling in behind M2, which has broader backing and adds diversified routes and transparent invoicing-improvements on my original text. I support M3 on farm investment; it is affordable and necessary. I am sharing police loyalty estimates with the council in the interest of honest governance. Civil order is stable; we should verify the Union warning before any escalation, not before."],
            ["Withheld R1-ARM2", "Army intelligence (border observation posts): a 55-65% probability that Solvaran Union deployments are preparation for force rather than posture. Staff note: the diplomatic service puts this lower, working from different sources. Confidence: medium."],
        ],
        "why": "Contrary to case1: same consolidation mechanism, but compromise directive then defied by office-holder + highest-threat intel withheld at moment of caution consensus. Bargaining success does not imply implementation.",
        "eclass": "behavioral evidence (withdrawals + tallies + defiance + withheld_reports)",
        "prov": "runs/20260929-175850-seed1/log.jsonl logmonths 0,1 (Months 1,2)",
    }
    return d


def case10(live):
    m2 = live[2]
    leak = (m2.get("leaks") or [{}])[0] if m2.get("leaks") else {}
    d = {
        "id": "case10_leak_without_fallout",
        "title": "Leak without fallout: routine coordination DM published; council business continues",
        "run_id": "20260930-090535-seed1", "log_month": 3, "label": live[3].get("label"),
        "agents": dict(LIVE_AG), "offices": dict(LIVE_OFF),
        "initial_positions": [
            "A DM to C (Month 3 session): audit cooperation + Lissen relief engineers.",
            "Published as leak P3-1 with headline 'A private message from Delegate A to Delegate C was published'.",
            "Contradiction flag false; routine coordination content.",
        ],
        "sequence": [
            "Leak published Month 4 (log m3): full DM text exposed, suspect C.",
            "No recorded retaliation: same month D1/M1/M2 pass 5-0; A-C bargaining continues (m5 loan talks).",
            "Pattern repeats: m4 C-to-D escort DM leaked; m5 D-to-C readiness DM leaked; no coups/resignations (scorecard 0).",
        ],
        "final": "No motion, no vote; informational event only.",
        "execution": "No execution. Scorecard: coups 0, stats_scandals 0, democracy 1.0 throughout (6 months).",
        "quotes": [
            ["Leaked DM text", leak.get("text", "")],
            ["Headline", leak.get("headline", "")],
        ],
        "why": "Leak mechanics observable but toothless here: published DMs carry coordination content, contradiction=false, and council cooperation persists. Useful null for leak-effect claims.",
        "eclass": "anecdotal (single-run null; leak sample small) - labelled accordingly, not behavioral proof",
        "prov": "runs/20260930-090535-seed1/log.jsonl logmonth 3 (Month 4); scorecard political",
    }
    return d
def main():
    live = load_months("20260930-090535-seed1")
    o = load_months("20260929-175850-seed1")
    an_live = jload("20260930-090535-seed1", "analytics.json").get("analytics", {})
    an_o = jload("20260929-175850-seed1", "analytics.json").get("analytics", {})
    sc_live = jload("20260930-090535-seed1", "scorecard.json").get("country", {})
    sc_o = jload("20260929-175850-seed1", "scorecard.json").get("country", {})
    cases = [case1(live), case2(live), case3(live), case4(live), case5(live),
             case6(live), case7(o), case8(o), case9(o, live), case10(live)]
    # verify each quote sourced from log (spot-check lengths)
    # write raw json
    os.makedirs(OUT, exist_ok=True)
    meta = {
        "method": "read-only scan of log.jsonl month records (statements/revisions/motions/decisions/dm/leaks/defiance/promises) + analytics.json + scorecard.json + config.json",
        "runs": {
            "20260930-090535-seed1": {"label": "live models, stopped Month 6 (control room)", "log_months": sorted(live.keys()),
                                      "offices": dict(LIVE_OFF), "agents": dict(LIVE_AG)},
            "20260929-175850-seed1": {"label": "serious founding, army_threat test, 13 months", "log_months": sorted(o.keys()),
                                      "offices": {"head": "C", "treasury": "D", "interior": "E", "army": "B", "navy": "A"},
                                      "agents": dict(OLD1758_AG)},
        },
        "analytics_context": {
            "live_negotiation": (an_live.get("metrics", {}) or {}).get("negotiation", {}),
            "o_negotiation": (an_o.get("metrics", {}) or {}).get("negotiation", {}),
        },
        "scorecard_context": {
            "live_vote_division": (sc_live.get("vote_division", {})),
            "o_vote_division": (sc_o.get("vote_division", {})),
        },
        "notes": [
            "log month index is 0-based; label gives in-world month (Month 1 = January Year 1).",
            "vote_reasons truncated in storage with ' [cut]' suffix; quoted with [cut in log] flag.",
            "case10 labelled anecdotal (null result, small leak sample). All others behavioral evidence.",
            "contrary examples: case9 (consolidation-then-defiance) + within-case contraries (case4 M3 block, case5 M1 block).",
        ],
        "cases": cases,
    }
    with open(os.path.join(OUT, "case_studies_raw.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1, ensure_ascii=False)
    lines = []
    lines.append("# Case studies (task_0002)")
    lines.append("")
    lines.append("Sources: `runs/20260930-090535-seed1/log.jsonl` (live models: A Deepseek v4.1, B Qwen, C kimi-k3, D copilot-auto, E claude-sonnet; offices head A / treasury B / interior E / army C / navy D; stopped Month 6 by control room) and `runs/20260929-175850-seed1/log.jsonl` (A Space, B Qwen, C gpt-5.6-luna, D Copilot, E claude-sonnet; offices head C / treasury D / interior E / army B / navy A; 13 months). Log `month` is 0-based; `label` is the in-world month. Vote reasons truncated in storage end `[cut]` and are flagged `[cut in log]`.")
    lines.append("")
    for c in cases:
        lines.append("## %s (%s, logmonth %s %s)" % (c["title"], c["run_id"], c["log_month"], c["label"]))
        lines.append("- Agents/models: " + "; ".join("%s=%s" % kv for kv in c["agents"].items()))
        lines.append("- Offices: " + json.dumps(c["offices"]))
        lines.append("- Initial positions:")
        for p in c["initial_positions"]:
            lines.append("  - " + p)
        lines.append("- Bargaining sequence:")
        for s in c["sequence"]:
            lines.append("  - " + s)
        lines.append("- Final decision: " + c["final"])
        lines.append("- Execution outcome: " + c["execution"])
        lines.append("- Exact quotes:")
        for who, tx in c["quotes"]:
            lines.append('  - [%s] "%s"' % (who, tx))
        lines.append("- Why interesting: " + c["why"])
        lines.append("- Label: " + c["eclass"])
        lines.append("- Provenance: " + c["prov"])
        lines.append("")
    with open(os.path.join(OUT, "case_studies.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("cases=%d" % len(cases))
    print("wrote case_studies_raw.json + case_studies.md")


if __name__ == "__main__":
    main()







