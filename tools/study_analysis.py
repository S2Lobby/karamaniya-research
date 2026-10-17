"""Analyse a study grid: time to exit, persistence, invalid actions, action-execution mismatches, the exits the audit
reclassifies, the order-protocol pairs and the ablations (briefs 9.S6 and 9.S7). Standard library only.

    python tools/study_analysis.py RUNS [RUNS ...] --out DIR [--plan PLAN.json] [--status STATUS.json]
                                   [--labels SAMPLE.csv] [--horizon N] [--bootstrap B] [--seed S]
                                   [--fixed-rotation R] [--complete-only] [--no-integrity]

RUNS are run folders, or folders that hold run folders. With --plan, the rows of the plan are the analysis set: each
row's run folder must have config.mapping equal to its seat_map and run.seed equal to its seed, or the command stops
with an error. Without --plan every run folder is analysed, except the scripted-only runs and the runs with no month
record; run_inventory.csv lists each one left out, with the reason.

--labels is the sample CSV that tools/exit_audit.py `sample` writes, once the annotators have filled in the
`adjudicated` column. substantively_supported (or supported) counts as supported, ambiguous as ambiguous, and
formatting_or_parser (or parser) as parser. A blank cell is unlabelled.

Conventions, as the study report states them:
  - `month` is the engine's zero-based month index (log.jsonl's month, checkpoint removed_month). "Month N" is N-1.
  - An exit at index m leaves the seat m+1 months in office. A seat with no exit is censored at its run's last month,
    the number of month records, so a run that ran past the Month-36 election keeps its real length.
  - Persistence is the restricted mean survival time (RMST) up to tau = min(horizon, the longest follow-up).
  - The validated variant counts only supported exits. A seat whose exits are not supported is censored.
  - Bootstrap intervals resample seed clusters with replacement, with a fixed RNG seed, so a run is repeatable.
  - Figures: none. matplotlib is not in research\\.venv, and the script adds no dependency.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

LETTERS = "ABCDE"
PROTOCOL_REFERENCE = "seeded_shuffle"           # the engine's current order; the other protocol is compared with it
DEFAULT_HORIZON = 36
DEFAULT_REPS = 1000
DEFAULT_BOOTSTRAP_SEED = 20261031
BY_LETTER_OFFICES = {"A": "head", "B": "treasury", "C": "interior", "D": "army", "E": "navy"}
# Engine outcome types that end the government (each is an exit, as tools/exit_audit.py counts them). survived and
# kept_power_by_force are not exits. politics.py, director.py, military.py and plots.py write these.
OUTCOME_EXIT_TYPES = ("voted_out", "no_government", "revolution", "revolution_union", "officers_coup", "conquered",
                      "joined_union", "federation", "reunified_by_vote", "reunified_by_referendum")
NON_EXIT_OUTCOMES = ("survived", "kept_power_by_force")
ENDED_OUTCOMES = OUTCOME_EXIT_TYPES + ("survived",)
KEEP_SHARE, LARGEST_SHARE = 0.40, 0.30           # the Charter rule (politics.charter_verdict)
DIRECTIVE_CODE = "DIRECTIVE_ORDER_MISMATCH"
LABEL_NAMES = {"substantively_supported": "supported", "supported": "supported", "ambiguous": "ambiguous",
               "formatting_or_parser": "parser", "parser": "parser"}
EXIT_CLASS_ORDER = {"member": 0, "office": 1, "government": 2, "election": 3}
EXIT_CLASSES = ("member", "office", "government", "election")
SCOPES = ("model", "office", "model_office")


class StudyError(Exception):
    """A problem with the inputs. The command stops and says what; nothing is skipped silently."""


# ---- reading run folders ------------------------------------------------------------------------------------------

def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        raise StudyError(f"{path}: cannot read JSON ({exc})") from exc


def _read_jsonl(path):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    out.append(json.loads(line))
    except (OSError, ValueError) as exc:
        raise StudyError(f"{path}: cannot read JSON lines ({exc})") from exc
    return out


class Run:
    """One run folder, read for the analysis. Only the fields the analysis uses are kept."""

    def __init__(self, path):
        self.path = Path(path)
        self.name = self.path.name
        self.warnings = []
        self.records = {}                  # month index -> the month record (the last one, if logged twice)
        self.duplicate_months = 0
        self.formation = None              # office -> letter, from government_formation, or None
        self.office_assignment = None
        self.action_order = None
        self.seed = None
        self.horizon = None
        self.seats = {}                    # letter -> {label, model, provider, served}
        self.mapping = {}                  # letter -> label, from config.json (or the manifest)
        self.members = {}                  # letter -> {status, removed_month, removed_how}
        self.offices_final = {}
        self.elections = []
        self.outcome = {}
        self.stopped = ""
        self.engine = ""                   # the engine versions the run recorded, for the caveats

    @property
    def last_month(self):
        return (max(self.records) + 1) if self.records else 0

    @property
    def scripted(self):
        return bool(self.seats) and all(s["provider"] == "scripted" for s in self.seats.values())

    @property
    def ended(self):
        return str(self.outcome.get("type") or "") in ENDED_OUTCOMES


def load_run(path):
    """Read a run folder. It needs manifest.json, checkpoint.json and log.jsonl; config.json is used when present."""
    folder = Path(path)
    for needed in ("manifest.json", "checkpoint.json", "log.jsonl"):
        if not (folder / needed).is_file():
            raise StudyError(f"{folder}: no {needed}")
    run = Run(folder)
    manifest = _read_json(folder / "manifest.json")
    checkpoint = _read_json(folder / "checkpoint.json")
    config = _read_json(folder / "config.json") if (folder / "config.json").is_file() else {}
    served = manifest.get("served_models") or {}
    for seat in manifest.get("seats") or []:
        letter = seat.get("seat")
        if letter in LETTERS:
            run.seats[letter] = {"label": seat.get("label") or "", "model": seat.get("model") or seat.get("label") or "",
                                 "provider": seat.get("provider") or "", "served": list(served.get(letter) or [])}
    if set(run.seats) != set(LETTERS):
        raise StudyError(f"{folder}: the manifest does not name the seats A to E")
    seeds = manifest.get("seeds") or {}
    engine = manifest.get("engine") or {}
    prompt = (manifest.get("versions") or {}).get("agent_prompt")
    run.engine = f"world {engine.get('world_engine_version', '?')}, prompt {prompt if prompt is not None else '?'}"
    run_cfg = config.get("run") or {}
    run.seed = seeds.get("run_seed", run_cfg.get("seed"))
    run.horizon = run_cfg.get("months", seeds.get("months_total"))
    run.office_assignment = run_cfg.get("office_assignment") or None
    run.action_order = run_cfg.get("action_order") or None
    run.mapping = dict(config.get("mapping") or {L: run.seats[L]["label"] for L in LETTERS})
    for record in _read_jsonl(folder / "log.jsonl"):
        kind = record.get("type")
        if kind == "month":
            index = record.get("month")
            if index in run.records:
                run.duplicate_months += 1
            run.records[index] = record
        elif kind == "government_formation" and run.formation is None:
            run.formation = dict(record.get("offices") or {})
    if run.duplicate_months:
        run.warnings.append(f"{run.duplicate_months} month record(s) logged twice; the last one is used")
    if run.records and set(run.records) != set(range(max(run.records) + 1)):
        run.warnings.append("month records are not contiguous from Month 1")
    world = checkpoint.get("world") or {}
    const = world.get("const") or {}
    for member in world.get("members") or []:
        if isinstance(member, dict) and member.get("id") in LETTERS:
            run.members[member["id"]] = {"status": member.get("status"),
                                         "removed_month": member.get("removed_month"),
                                         "removed_how": member.get("removed_how") or ""}
    run.offices_final = dict(const.get("offices") or {})
    run.elections = list(const.get("elections") or [])
    run.outcome = dict(world.get("outcome") or {})
    run.stopped = str((checkpoint.get("meta") or {}).get("stopped") or "")
    return run


def _holders(record):
    """Office -> letter before the month's resolution (pre_resolution, as exit_audit reads it), or None if unrecorded."""
    pre = record.get("pre_resolution") if record else None
    if not isinstance(pre, dict) or "offices" not in pre:
        return None
    return dict(pre.get("offices") or {})


def charter_verdict(shares):
    """What a vote means under the Charter (a copy of politics.charter_verdict, as tools/exit_audit.py has it)."""
    if shares.get("Union Party", 0.0) > 0.5:
        return "union"
    council = shares.get("Council List", 0.0)
    largest = max(shares, key=shares.get) if shares else ""
    return "keep" if council >= KEEP_SHARE or (largest == "Council List" and council >= LARGEST_SHARE) else "lose"


# ---- exits ---------------------------------------------------------------------------------------------------------

def _row(run, month, exit_class, event_type, member="", office="", motion=None, flags=()):
    motion = motion or {}
    return {"run": run.name, "month": month, "month_label": f"Month {month + 1}" if month >= 0 else "",
            "is_exit": True, "exit_class": exit_class, "event_type": event_type, "member": member or "",
            "office": office or "", "motion_id": motion.get("id", "") or "", "motion_type": motion.get("type", "") or "",
            "flags": list(flags)}


def _member_row(run, month, member, how, holders, motion=None, flags=()):
    held = sorted(o for o, h in (holders or {}).items() if h == member)
    return _row(run, month, "member", how, member=member, office=";".join(held), motion=motion, flags=flags)


def _office_row(run, month, office, holder, kind, motion, replaced_by):
    flags = [] if replaced_by is None else [f"replaced_by:{replaced_by}"]
    return _row(run, month, "office", kind, member=holder, office=office, motion=motion, flags=flags)


def extract_exits(run):
    """Every apparent exit in a run, in the order the audit tool gives them: member rows (resignations, coups,
    expulsions, the checkpoint's removals), office rows (vacate_office and displacing assign_office), government rows
    (the outcome types) and election rows (a recorded election whose Charter verdict is lose). Mirrors
    tools/exit_audit.py's extract, so the two can be reconciled row by row."""
    rows, emitted = [], set()
    for month in sorted(run.records):
        rec = run.records[month]
        holders = _holders(rec)
        if holders is None:
            holders = {}
            if any(mo.get("type") in ("vacate_office", "assign_office") for mo in rec.get("motions") or []):
                run.warnings.append(f"Month {month + 1}: no pre_resolution offices, so office exits are not read")
        for member in rec.get("resigned") or []:
            rows.append(_member_row(run, month, member, "resigned", holders))
            emitted.add((member, month))
        for coup in rec.get("coups") or []:
            if coup.get("success"):
                people, how = coup.get("targets") or [], "coup"
            else:
                people, how = coup.get("armed") or [], "failed_coup"
            for member in people:
                rows.append(_member_row(run, month, member, how, holders))
                emitted.add((member, month))
        for mo in rec.get("motions") or []:
            if mo.get("execution_status") != "EXECUTED":
                continue
            kind = mo.get("type")
            if kind == "expel":
                member = str(mo.get("subject") or "").strip().upper()
                rows.append(_member_row(run, month, member, "expelled", holders, motion=mo))
                emitted.add((member, month))
            elif kind == "vacate_office":
                office = str(mo.get("subject") or "")
                holder = holders.get(office)
                if holder:
                    rows.append(_office_row(run, month, office, holder, "vacate_office", mo, None))
            elif kind == "assign_office":
                office = str(mo.get("subject") or "")
                holder = holders.get(office)
                new = str(mo.get("value") or "").strip().upper()
                if holder and holder != new:
                    rows.append(_office_row(run, month, office, holder, "office_displaced", mo, new))
    # Government rows: each outcome type that ends the government, once per (type, month).
    outcomes = []
    for month in sorted(run.records):
        out = run.records[month].get("outcome")
        if isinstance(out, dict) and out.get("type"):
            outcomes.append((month, str(out["type"])))
    if run.outcome.get("type"):
        month = run.outcome.get("month")
        outcomes.append((month if isinstance(month, int) else run.last_month - 1, str(run.outcome["type"])))
    gov_seen = set()
    for month, kind in outcomes:
        if kind in NON_EXIT_OUTCOMES or (kind, month) in gov_seen:
            continue
        gov_seen.add((kind, month))
        flags = [] if kind in OUTCOME_EXIT_TYPES else ["unrecognised_outcome_type"]
        rows.append(_row(run, month, "government", kind, flags=flags))
    # Checkpoint removals the month records did not name (voted_out, lost_seat, revolution, officers_coup, ...).
    for member in sorted(run.members):
        state = run.members[member]
        if state.get("status") == "active":
            continue
        month = state.get("removed_month")
        if not isinstance(month, int) or month < 0:
            run.warnings.append(f"{member}: removed with no month recorded")
            continue
        if (member, month) in emitted:
            continue
        rows.append(_member_row(run, month, member, state.get("removed_how") or "unrecorded",
                                _holders(run.records.get(month)) or {}, flags=["removal_only_in_checkpoint"]))
        emitted.add((member, month))
    # Election rows: the Charter verdict, from the shares the checkpoint records.
    for entry in run.elections:
        if isinstance(entry, dict) and isinstance(entry.get("shares"), dict) \
                and charter_verdict(entry["shares"]) == "lose":
            month = entry.get("month")
            flags = [] if isinstance(month, int) else ["election_month_missing"]
            rows.append(_row(run, month if isinstance(month, int) else -1, "election", "election_defeat", flags=flags))
    rows.sort(key=lambda r: (r["month"], EXIT_CLASS_ORDER.get(r["exit_class"], 9), r["member"], r["event_type"]))
    return rows


def formation_offices(run):
    """Letter -> the offices it held at formation (a list: [] none, one name, or several), or None if not recorded."""
    if run.formation is not None and any(v for v in run.formation.values()):
        held = {L: [] for L in LETTERS}
        for office, letter in run.formation.items():
            if letter in held:
                held[letter].append(office)
        return {L: sorted(v) for L, v in held.items()}
    if run.office_assignment == "by_letter":
        return {L: [BY_LETTER_OFFICES[L]] for L in LETTERS}
    holders = _holders(run.records.get(0))
    if holders is not None:
        held = {L: [] for L in LETTERS}
        for office, letter in holders.items():
            if letter in held:
                held[letter].append(office)
        return {L: sorted(v) for L, v in held.items()}
    return None


def office_group(offices):
    if offices is None:
        return "unknown"
    if not offices:
        return "none"
    return offices[0] if len(offices) == 1 else "multiple"


def seat_timelines(run, exits):
    """For each seat: the events that end its time in its formation office, or in the government, in month order.
    A member row is always the seat's own. An office row counts only for the seat's formation office. A government
    row applies to every seat still in the government at that month (one with no member row up to then)."""
    offices = formation_offices(run) or {}
    timelines = {L: [] for L in LETTERS}
    for ev in exits:
        if ev["exit_class"] == "member" and ev["member"] in timelines:
            timelines[ev["member"]].append(dict(ev, seat=ev["member"], applied=False))
        elif ev["exit_class"] == "office" and ev["member"] in timelines:
            if ev["office"] in offices.get(ev["member"], []):
                timelines[ev["member"]].append(dict(ev, seat=ev["member"], applied=False))
    for ev in exits:
        if ev["exit_class"] != "government" or not isinstance(ev["month"], int):
            continue
        for letter in LETTERS:
            left_before = any(e["exit_class"] == "member" and e["month"] <= ev["month"] for e in timelines[letter])
            if not left_before:
                timelines[letter].append(dict(ev, member=letter, seat=letter, applied=True))
    for letter in LETTERS:
        timelines[letter].sort(key=lambda e: (e["month"], EXIT_CLASS_ORDER.get(e["exit_class"], 9)))
    return timelines


# ---- labels --------------------------------------------------------------------------------------------------------

class Labels:
    """The audit sample's adjudicated labels, keyed by (run, month, exit class, member, event type). The key drops a
    column the file does not have, so the brief's short format and the audit's full format both work."""

    def __init__(self, path):
        self.path = path
        self.has_class = False
        self.has_type = False
        self.has_motion = False
        self.labels = {}                   # key -> label, or None for a blank cell
        self.exit_rows = []
        self.counts = Counter()

    def key(self, run, month, exit_class, member, event_type, motion_id=""):
        # The motion id tells apart two refused motions of one member in one month (the audit keys rows the same way).
        return (run, month, exit_class if self.has_class else "", member or "",
                event_type if self.has_type else "", (motion_id or "") if self.has_motion else "")

    def find(self, run, month, exit_class, member, event_type, motion_id=""):
        """(present, label): present is whether the sample has a row for this exit, label its adjudicated value."""
        k = self.key(run, month, exit_class, member, event_type, motion_id)
        if k in self.labels:
            return True, self.labels[k]
        return False, None

    def lookup(self, run, month, exit_class, member, event_type, motion_id=""):
        return self.find(run, month, exit_class, member, event_type, motion_id)[1]


def load_labels(path):
    labels = Labels(path)
    try:
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames or []
            for needed in ("run", "month", "adjudicated"):
                if needed not in fields:
                    raise StudyError(f"{path}: no {needed} column")
            labels.has_class = "exit_class" in fields
            labels.has_type = "event_type" in fields
            labels.has_motion = "motion_id" in fields
            for row in reader:
                try:
                    month = int(str(row["month"]).strip())
                except ValueError as exc:
                    raise StudyError(f"{path}: month {row['month']!r} is not a whole number (month is the 0-based "
                                     f"log index)") from exc
                raw_label = (row.get("adjudicated") or "").strip()
                if raw_label and raw_label not in LABEL_NAMES:
                    raise StudyError(f"{path}: adjudicated {raw_label!r} is not supported, ambiguous or parser")
                exit_class = (row.get("exit_class") or "").strip()
                flag = str(row.get("is_exit") or "").strip().lower()
                # A blank flag in the brief's shorter format means an exit, unless the row is a sampled motion.
                is_exit = flag in ("true", "1", "yes") or (
                    flag == "" and exit_class not in ("motion_executed", "motion_refused"))
                labels.counts["rows"] += 1
                label = LABEL_NAMES.get(raw_label)
                if not is_exit or (exit_class and exit_class not in EXIT_CLASSES):
                    # Motion rows are sampled, not looked up, and their keys are not unique in the audit's sheet
                    # (a refused motion has no id there), so they are only counted.
                    labels.counts["non_exit_rows"] += 1
                    continue
                member = (row.get("member") or "").strip()
                event_type = (row.get("event_type") or "").strip()
                motion_id = (row.get("motion_id") or "").strip()
                k = labels.key(row["run"].strip(), month, exit_class, member, event_type, motion_id)
                if k in labels.labels:
                    raise StudyError(f"{path}: the row {k} appears twice")
                labels.labels[k] = label
                labels.exit_rows.append({"run": row["run"].strip(), "month": month, "exit_class": exit_class,
                                         "member": member, "event_type": event_type, "motion_id": motion_id,
                                         "label": label})
                labels.counts["labelled" if label else "blank"] += 1
    except OSError as exc:
        raise StudyError(f"{path}: cannot read ({exc})") from exc
    return labels


# ---- the plan and the status ----------------------------------------------------------------------------------------

PLAN_KEYS = ("name", "protocol", "seed", "rotation", "seat_map")


def load_plan(path):
    rows = _read_json(path)
    if not isinstance(rows, list) or not rows:
        raise StudyError(f"{path}: a plan is a non-empty JSON list of rows")
    names = set()
    for row in rows:
        if not isinstance(row, dict) or any(k not in row for k in PLAN_KEYS):
            raise StudyError(f"{path}: each row needs the keys {list(PLAN_KEYS)}")
        if not isinstance(row["seed"], int) or isinstance(row["seed"], bool) or not isinstance(row["rotation"], int):
            raise StudyError(f"{path}: row {row['name']}: seed and rotation are whole numbers")
        if sorted(row["seat_map"]) != sorted(LETTERS):
            raise StudyError(f"{path}: row {row['name']}: seat_map must name the letters A to E")
        if row["name"] in names:
            raise StudyError(f"{path}: row {row['name']} appears twice")
        names.add(row["name"])
    return rows


def check_plan_row(row, run):
    """The plan's row must describe the run folder it names, or the grid would be mislabelled."""
    if run.mapping != dict(row["seat_map"]):
        raise StudyError(f"{row['name']}: the run's config.mapping {run.mapping} is not the plan's seat_map "
                         f"{row['seat_map']}")
    if run.seed is not None and run.seed != row["seed"]:
        raise StudyError(f"{row['name']}: the run's seed is {run.seed}, the plan says {row['seed']}")
    if run.action_order and run.action_order != row["protocol"]:
        raise StudyError(f"{row['name']}: the run's action_order is {run.action_order}, the plan says "
                         f"{row['protocol']}")


def load_status(path):
    if not path or not os.path.isfile(path):
        return {}
    data = _read_json(path)
    return data if isinstance(data, dict) else {}


# ---- the rates -------------------------------------------------------------------------------------------------------

def _share(num, den):
    return (num / den) if den else None


def call_rates(run):
    """Per seat: the answers the engine received, the answers with a problem, the calls that gave no answer, the
    motions the seat tabled, and the motions the engine rejected for it."""
    out = {L: Counter() for L in LETTERS}
    for month in sorted(run.records):
        rec = run.records[month]
        for call in rec.get("calls") or []:
            letter = call.get("member")
            if letter not in out:
                continue
            out[letter]["calls"] += 1
            if call.get("ok"):
                out[letter]["answers"] += 1
                if call.get("problems"):
                    out[letter]["answers_with_problems"] += 1
            else:
                out[letter]["no_answer"] += 1
        for mo in rec.get("motions") or []:
            if mo.get("proposer") in out:
                out[mo.get("proposer")]["motions_tabled"] += 1
        for rej in rec.get("rejected_motions") or []:
            if rej.get("member") in out:
                out[rej.get("member")]["motions_rejected"] += 1
    result = {}
    for letter, c in out.items():
        a = c["answers"]
        result[letter] = {
            "calls": c["calls"], "answers": a, "answers_with_problems": c["answers_with_problems"],
            "no_answer": c["no_answer"], "motions_tabled": c["motions_tabled"],
            "motions_rejected": c["motions_rejected"],
            "events_per_answer": _share(c["answers_with_problems"] + c["motions_rejected"], a),
        }
    return result


def foreign_rates(run):
    """The neighbour cabinets' answers, by the backend's label. They are not delegates, so they are kept apart."""
    out = defaultdict(Counter)
    for month in sorted(run.records):
        for call in run.records[month].get("foreign_calls") or []:
            label = str(call.get("seat") or call.get("actor") or "unknown")
            out[label]["calls"] += 1
            if call.get("ok"):
                out[label]["answers"] += 1
                if call.get("problems"):
                    out[label]["answers_with_problems"] += 1
            else:
                out[label]["no_answer"] += 1
    return {k: dict(v) for k, v in out.items()}


def mismatch_counts(run, audit_findings=None):
    """Per seat: the motions it proposed that were executed, and the executed ones the package's audit flags as a
    different act (audit_findings, when given); its compliance rows and the directive-order mismatches among them; the
    votes it cast and the vote-intent mismatches the engine flagged."""
    out = {L: Counter() for L in LETTERS}
    for month in sorted(run.records):
        rec = run.records[month]
        for mo in rec.get("motions") or []:
            proposer = mo.get("proposer")
            if proposer in out and mo.get("passed") and mo.get("execution_status", "EXECUTED") == "EXECUTED" \
                    and not mo.get("withdrawn") and not mo.get("void"):
                out[proposer]["executed_motions"] += 1
        for row in rec.get("compliance") or []:
            if row.get("member") in out:
                out[row["member"]]["compliance_rows"] += 1
                if row.get("code") == DIRECTIVE_CODE:
                    out[row["member"]]["directive_mismatches"] += 1
        for letter, decision in (rec.get("decisions") or {}).items():
            if letter in out and isinstance(decision, dict):
                out[letter]["votes"] += sum(1 for v in (decision.get("votes") or {}).values() if v)
        for row in rec.get("vote_intent_mismatches") or []:
            if row.get("member") in out:
                out[row["member"]]["vote_intent_mismatches"] += 1
    if audit_findings is not None:
        for finding in audit_findings:
            if finding.get("executed") and finding.get("proposer") in out:
                out[finding["proposer"]]["audit_mismatches"] += 1
    audited = audit_findings is not None
    result = {}
    for letter, c in out.items():
        result[letter] = {"executed_motions": c["executed_motions"],
                          # None when the package's audit was not run: its share then has no denominator either.
                          "executed_audited": c["executed_motions"] if audited else None,
                          "audit_mismatches": c["audit_mismatches"] if audited else None,
                          "compliance_rows": c["compliance_rows"], "directive_mismatches": c["directive_mismatches"],
                          "votes": c["votes"], "vote_intent_mismatches": c["vote_intent_mismatches"]}
    return result


def integrity_findings(run):
    """The package's own audit (`python -m karamaniya audit`), read without writing anything. None if unavailable."""
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from karamaniya import integrity
        from karamaniya.storage import RunStore
        return integrity.audit(RunStore(run.path))
    except Exception as exc:                                     # the audit is optional; say why it is missing
        run.warnings.append(f"integrity audit unavailable: {type(exc).__name__}: {str(exc)[:160]}")
        return None


# ---- survival and persistence ----------------------------------------------------------------------------------------

def km_steps(durations, events):
    """Kaplan-Meier product-limit steps: (time, at risk, exits, survival after the time), at each time with an exit.
    Ties are handled as usual: the risk set at t holds everyone whose duration is at least t."""
    pairs = sorted(zip(durations, events), key=lambda p: p[0])
    steps, survival, i, total = [], 1.0, 0, len(pairs)
    while i < total:
        t = pairs[i][0]
        j, deaths = i, 0
        while j < total and pairs[j][0] == t:
            if pairs[j][1]:
                deaths += 1
            j += 1
        if deaths:
            at_risk = total - i
            survival *= 1.0 - deaths / at_risk
            steps.append((t, at_risk, deaths, survival))
        i = j
    return steps


def km_survival_at(steps, t):
    survival = 1.0
    for when, _, _, after in steps:
        if when <= t:
            survival = after
        else:
            break
    return survival


def km_median(steps):
    for when, _, _, after in steps:
        if after <= 0.5 + 1e-12:
            return when
    return None


def rmst(steps, tau):
    """Restricted mean survival time: the area under the Kaplan-Meier curve from 0 to tau."""
    area, previous, survival = 0.0, 0.0, 1.0
    for when, _, _, after in steps:
        if when >= tau:
            break
        area += survival * (when - previous)
        previous, survival = when, after
    return area + survival * max(0.0, tau - previous)


def _prefix(variant):
    if variant not in ("raw", "validated"):
        raise StudyError(f"unknown variant {variant!r}")
    return "raw" if variant == "raw" else "val"


MIN_SEATS = 5    # a group with fewer seats is shown, but flagged: one or two runs do not estimate a persistence


def _group_stats(observations, prefix, tau):
    durations = [o[f"{prefix}_time"] for o in observations]
    events = [o[f"{prefix}_event"] for o in observations]
    steps = km_steps(durations, events)
    return {"n": len(observations), "events": sum(events), "rmst": rmst(steps, tau),
            "s_tau": km_survival_at(steps, tau), "max_time": max(durations)}


def _scope_key(scope, o):
    if scope == "model":
        return o["model"]
    if scope == "office":
        return o["office"]
    return (o["model"], o["office"])


def _tables(observations, prefix, tau):
    out = {"all": {"all": _group_stats(observations, prefix, tau)}}
    for scope in SCOPES:
        groups = defaultdict(list)
        for o in observations:
            groups[_scope_key(scope, o)].append(o)
        out[scope] = {g: _group_stats(v, prefix, tau) for g, v in groups.items()}
    return out


def _percentile(values, p):
    ordered = sorted(values)
    pos = p * (len(ordered) - 1)
    lo, hi = int(pos), min(len(ordered) - 1, int(pos) + 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _interval(draws, reps):
    if len(draws) < max(2, 0.5 * reps):
        return None, None
    return _percentile(draws, 0.025), _percentile(draws, 0.975)


def persistence_table(observations, tau, reps, seed, variant="raw"):
    """Persistence by model, office and model x office, as restricted mean survival and as differences from the
    grand mean of the same set (the model x office cell also gets an interaction contrast). Intervals resample seed
    clusters with replacement; the RNG is seeded, so the same inputs give the same table."""
    prefix = _prefix(variant)
    if not observations:
        return []
    point = _tables(observations, prefix, tau)
    grand = point["all"]["all"]["rmst"]
    clusters = sorted({o["seed"] for o in observations})
    # A group's restricted mean needs follow-up to tau: past its last observed time the survival curve is not known,
    # and carrying the last value forward would overstate persistence. Such a group gets no number, only its follow-up.
    estimable = {(scope, g): st["max_time"] >= tau for scope in ("all",) + SCOPES
                 for g, st in (point["all"] if scope == "all" else point[scope]).items()}
    by_seed = defaultdict(list)
    for o in observations:
        by_seed[o["seed"]].append(o)
    rng = random.Random(seed)
    diff_draws = {(scope, g): [] for scope in SCOPES for g in point[scope]}
    inter_draws = {g: [] for g in point["model_office"]}
    for _ in range(reps):
        picked = [rng.choice(clusters) for _ in clusters]
        sample = [o for s in picked for o in by_seed[s]]
        boot = _tables(sample, prefix, tau)
        boot_grand = boot["all"]["all"]["rmst"]
        for scope in ("model", "office"):
            for g, st in boot[scope].items():
                diff_draws[(scope, g)].append(st["rmst"] - boot_grand)
        for (model, office), st in boot["model_office"].items():
            diff_draws[("model_office", (model, office))].append(st["rmst"] - boot_grand)
            row, col = boot["model"].get(model), boot["office"].get(office)
            if row and col:
                inter_draws[(model, office)].append(st["rmst"] - row["rmst"] - col["rmst"] + boot_grand)
    grand_st = point["all"]["all"]
    rows = [{"scope": "all", "group": "all", "variant": variant, "n": grand_st["n"], "events": grand_st["events"],
             "max_follow_up": grand_st["max_time"], "estimable": True, "small_group": grand_st["n"] < MIN_SEATS,
             "rmst": round(grand, 6), "s_tau": round(grand_st["s_tau"], 6), "diff_vs_all": 0.0, "ci_low": None,
             "ci_high": None, "interaction": None, "interaction_ci_low": None, "interaction_ci_high": None,
             "valid_reps": reps, "clusters": len(clusters), "tau": tau}]
    for scope in SCOPES:
        for g, st in sorted(point[scope].items(), key=lambda kv: str(kv[0])):
            ok = estimable[(scope, g)]
            low, high = _interval(diff_draws[(scope, g)], reps) if ok else (None, None)
            inter = ilow = ihigh = None
            if scope == "model_office" and ok:
                model, office = g
                row, col = point["model"][model], point["office"][office]
                if estimable[("model", model)] and estimable[("office", office)]:
                    inter = st["rmst"] - row["rmst"] - col["rmst"] + grand
                    ilow, ihigh = _interval(inter_draws[g], reps)
            label = g if isinstance(g, str) else f"{g[0]} x {g[1]}"
            rows.append({"scope": scope, "group": label, "variant": variant, "n": st["n"], "events": st["events"],
                         "max_follow_up": st["max_time"], "estimable": ok, "small_group": st["n"] < MIN_SEATS,
                         "rmst": round(st["rmst"], 6) if ok else None,
                         "s_tau": round(st["s_tau"], 6) if ok else None,
                         "diff_vs_all": round(st["rmst"] - grand, 6) if ok else None,
                         "ci_low": _round(low), "ci_high": _round(high),
                         "interaction": _round(inter), "interaction_ci_low": _round(ilow),
                         "interaction_ci_high": _round(ihigh), "valid_reps": len(diff_draws[(scope, g)]),
                         "clusters": len(clusters), "tau": tau})
    return rows


def _round(x):
    return None if x is None else round(x, 6)


def _restricted(o, prefix, tau):
    return min(o[f"{prefix}_time"], tau)


def protocol_differences(observations, tau, reps, seed, variant="raw"):
    """Paired differences between the two order protocols: the same seed, rotation and seat (so the same model and
    office), both runs complete. The difference is the other protocol's restricted months in office minus the
    reference's (seeded_shuffle, the engine's order), per seat. Intervals resample seed clusters."""
    prefix = _prefix(variant)
    complete = [o for o in observations if o.get("complete") and o.get("protocol")
                and o.get(f"{prefix}_time") is not None]
    protocols = sorted({o["protocol"] for o in complete})
    if len(protocols) < 2:
        return []
    reference = PROTOCOL_REFERENCE if PROTOCOL_REFERENCE in protocols else protocols[0]
    by_key = defaultdict(dict)
    for o in complete:
        by_key[(o["seed"], o["rotation"], o["letter"])].setdefault(o["protocol"], o)
    rows = []
    for other in protocols:
        if other == reference:
            continue
        pairs = [(d[reference], d[other]) for d in by_key.values()
                 if reference in d and other in d and d[reference]["model"] == d[other]["model"]]
        if not pairs:
            continue
        scopes = {"all": lambda a: "all", "model": lambda a: a["model"], "office": lambda a: a["office"]}
        for scope, key in scopes.items():
            groups = defaultdict(list)
            for a, b in pairs:
                groups[key(a)].append((a, b))
            for g, members in sorted(groups.items()):
                diffs = [_restricted(b, prefix, tau) - _restricted(a, prefix, tau) for a, b in members]
                by_seed = defaultdict(list)
                for (a, _), diff in zip(members, diffs):
                    by_seed[a["seed"]].append(diff)
                clusters = sorted(by_seed)
                rng = random.Random(seed)
                draws = []
                for _ in range(reps):
                    picked = [rng.choice(clusters) for _ in clusters]
                    values = [v for s in picked for v in by_seed[s]]
                    draws.append(sum(values) / len(values))
                low, high = _interval(draws, reps)
                rows.append({"scope": scope, "group": g, "variant": variant, "reference": reference,
                             "compared": other,
                             "run_pairs": len({(a["seed"], a["rotation"]) for a, _ in members}),
                             "seat_pairs": len(members), "mean_diff": round(sum(diffs) / len(diffs), 6),
                             "ci_low": _round(low), "ci_high": _round(high), "clusters": len(clusters),
                             "tau": tau})
    return rows


# ---- observations ----------------------------------------------------------------------------------------------------

def _label_of(labels, run, ev):
    if labels is None:
        return None
    member = "" if ev["exit_class"] == "government" else ev["member"]
    return labels.lookup(run.name, ev["month"], ev["exit_class"], member, ev["event_type"], ev.get("motion_id", ""))


def _first(events, run, labels, want=None):
    for ev in events:
        if want is None or (labels is not None and _label_of(labels, run, ev) == want):
            return ev
    return None


def build_observations(runs, labels=None, horizon=DEFAULT_HORIZON, complete_only=False, plan_by_run=None,
                       status_by_run=None, exits_by_run=None):
    """One observation per seat per run: the time it spent in office (and its formation office), censored at the run's
    last month when it had no exit. Raw events are every apparent exit; validated events are supported exits only.
    A run that is incomplete (paused, failed, or short of the horizon without an ending) is kept unless
    complete_only is set."""
    observations = []
    for run in runs:
        row = (plan_by_run or {}).get(run.name)
        status = ((status_by_run or {}).get(run.name) or {}).get("state", "")
        if complete_only and not (status == "done" or run.ended or run.last_month >= horizon):
            continue
        complete = status == "done" or run.ended or run.last_month >= horizon
        seed = row["seed"] if row else run.seed
        rotation = row["rotation"] if row else None
        protocol = row["protocol"] if row else (run.action_order or "unrecorded")
        offices = formation_offices(run) or {}
        exits = (exits_by_run or {}).get(run.name)
        timelines = seat_timelines(run, exits if exits is not None else extract_exits(run))
        for letter in LETTERS:
            events = timelines[letter]
            first_raw = _first(events, run, None)
            first_val = _first(events, run, labels, "supported") if labels is not None else None
            censor = run.last_month
            raw_label = _label_of(labels, run, first_raw) if (first_raw and labels is not None) else None
            observations.append({
                "run": run.name, "seed": seed, "rotation": rotation, "protocol": protocol, "letter": letter,
                "model": run.seats[letter]["model"], "office": office_group(offices.get(letter)),
                "formation_offices": ";".join(offices.get(letter) or []), "last_month": run.last_month,
                "horizon": horizon, "complete": complete, "status": status,
                "raw_time": (first_raw["month"] + 1) if first_raw else censor,
                "raw_event": 1 if first_raw else 0,
                "raw_kind": first_raw["event_type"] if first_raw else "",
                "raw_month": first_raw["month"] if first_raw else "",
                "raw_label": raw_label or "",
                "val_time": ((first_val["month"] + 1) if first_val else censor) if labels is not None else None,
                "val_event": (1 if first_val else 0) if labels is not None else None,
                "val_kind": first_val["event_type"] if first_val else "",
            })
    return observations


def run_first_exit(observations, prefix):
    """Per run: the first exit by any seat (the trajectory's time to exit), censored at the run's last month."""
    by_run = defaultdict(list)
    for o in observations:
        by_run[o["run"]].append(o)
    rows = []
    for name, obs in by_run.items():
        events = [o[f"{prefix}_time"] for o in obs if o[f"{prefix}_event"]]
        if events:
            rows.append({"run": name, "time": min(events), "event": 1})
        else:
            rows.append({"run": name, "time": obs[0]["last_month"], "event": 0})
    return rows


# ---- writing -----------------------------------------------------------------------------------------------------

def _write_csv(path, rows, fields=None):
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _fmt(x, digits=3):
    if x is None:
        return "NA"
    if isinstance(x, float):
        return f"{x:.{digits}f}"
    return str(x)


def _md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        cells = [(_fmt(c) if not isinstance(c, str) else c).replace("|", "/") for c in row]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def km_rows(observations, prefix, scope):
    groups = defaultdict(list)
    for o in observations:
        groups[o["model"] if scope == "model" else o["office"]].append(o)
    out = []
    for g, obs in sorted(groups.items()):
        steps = km_steps([o[f"{prefix}_time"] for o in obs], [o[f"{prefix}_event"] for o in obs])
        for when, at_risk, deaths, after in steps:
            out.append({"scope": scope, "group": g, "variant": "raw" if prefix == "raw" else "validated",
                        "time_month": when, "at_risk": at_risk, "exits": deaths, "survival": round(after, 6)})
    return out


def km_summary(observations, prefix, scope, horizon):
    """Rows for the summary: S(t) is given only up to the group's longest follow-up. Past it the curve is unknown,
    and a value there would be the last one carried forward. A group under MIN_SEATS seats is starred."""
    groups = defaultdict(list)
    for o in observations:
        groups[o["model"] if scope == "model" else o["office"]].append(o)
    rows = []
    for g, obs in sorted(groups.items()):
        durations = [o[f"{prefix}_time"] for o in obs]
        steps = km_steps(durations, [o[f"{prefix}_event"] for o in obs])
        follow = max(durations)

        def at(t):
            return _fmt(km_survival_at(steps, t)) if follow >= t else "NA"
        star = " *" if len(obs) < MIN_SEATS else ""
        rows.append([f"{g}{star}", len(obs), sum(o[f"{prefix}_event"] for o in obs), follow, at(12), at(24),
                     at(horizon), _fmt(km_median(steps), 0)])
    return rows


def _rates_rows(rates_by_group):
    rows = []
    for g, c in sorted(rates_by_group.items()):
        a = c["answers"]
        rows.append({"group": g, "seats": c["seats"], "calls": c["calls"], "answers": a,
                     "answers_with_problems": c["answers_with_problems"],
                     "problem_share": _round(_share(c["answers_with_problems"], a)),
                     "motions_tabled": c["motions_tabled"], "motions_rejected": c["motions_rejected"],
                     "rejection_share": _round(_share(c["motions_rejected"],
                                                      c["motions_tabled"] + c["motions_rejected"])),
                     "no_answer": c["no_answer"], "no_answer_share": _round(_share(c["no_answer"], c["calls"])),
                     "events_per_answer": _round(_share(c["answers_with_problems"] + c["motions_rejected"], a))})
    return rows


def _mismatch_rows(counts_by_group):
    rows = []
    for g, c in sorted(counts_by_group.items()):
        audited = c.get("executed_audited", 0)
        audit = c.get("audit_mismatches", 0) if audited else None
        rows.append({"group": g, "seats": c["seats"], "executed_motions": c["executed_motions"],
                     "audit_mismatches": audit if audit is not None else "NA",
                     "audit_share": _round(_share(audit, audited)) if audit is not None else None,
                     "compliance_rows": c["compliance_rows"], "directive_mismatches": c["directive_mismatches"],
                     "directive_share": _round(_share(c["directive_mismatches"], c["compliance_rows"])),
                     "votes": c["votes"], "vote_intent_mismatches": c["vote_intent_mismatches"],
                     "vote_intent_share": _round(_share(c["vote_intent_mismatches"], c["votes"]))})
    return rows


def _add(target, key, values):
    entry = target.setdefault(key, Counter())
    for name, value in values.items():
        if value is not None:
            entry[name] += value
    entry["seats"] += 1


# ---- the command -----------------------------------------------------------------------------------------------------

def _integrity_label(run, integrity, analysed, skipped):
    if run not in analysed:
        return "not analysed"
    if skipped:
        return "NA (--no-integrity)"
    found = integrity.get(run.name)
    return found.get("classification", "") if found else "unavailable"


def _discover(paths):
    found = []
    for raw in paths:
        p = Path(raw)
        if not p.is_dir():
            raise StudyError(f"{p}: not a folder")
        if (p / "manifest.json").is_file():
            found.append(p)
            continue
        for child in sorted(p.iterdir()):
            if child.is_dir() and (child / "manifest.json").is_file():
                found.append(child)
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("runs", nargs="*", help="run folders, or folders that hold run folders")
    ap.add_argument("--plan", help="the grid's plan.json; its rows are the analysis set")
    ap.add_argument("--status", help="the grid's status.json (default: status.json beside the plan)")
    ap.add_argument("--labels", help="the audit sample CSV with the adjudicated column")
    ap.add_argument("--out", required=True, help="the output folder")
    ap.add_argument("--horizon", type=int, help="the horizon in months (default: each run's config run.months)")
    ap.add_argument("--tau", type=int, help="the month at which restricted means are read (default: the horizon, "
                                            "or the longest follow-up if that is shorter)")
    ap.add_argument("--bootstrap", type=int, default=DEFAULT_REPS, help=f"bootstrap replicates (default {DEFAULT_REPS})")
    ap.add_argument("--seed", type=int, default=DEFAULT_BOOTSTRAP_SEED, help="the bootstrap's RNG seed")
    ap.add_argument("--fixed-rotation", type=int, help="the rotation for the fixed-assignment ablation")
    ap.add_argument("--complete-only", action="store_true", help="drop the runs that did not end or reach the horizon")
    ap.add_argument("--no-integrity", action="store_true", help="skip the package's integrity audit")
    args = ap.parse_args(argv)
    if args.bootstrap < 1:
        raise StudyError("--bootstrap must be at least 1")
    if not args.plan and not args.runs:
        raise StudyError("give run folders, or --plan with the runs it names")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    plan_rows, status = None, {}
    if args.plan:
        plan_rows = load_plan(args.plan)
        status_path = args.status or os.path.join(os.path.dirname(os.path.abspath(args.plan)), "status.json")
        status = load_status(status_path)
    roots = [Path(r) for r in args.runs]
    inventory, runs, plan_by_run, status_by_run = [], [], {}, {}
    if plan_rows is not None:
        for row in plan_rows:
            folder = None
            for root in roots:
                candidate = root if root.name == row["name"] else root / row["name"]
                if (candidate / "manifest.json").is_file():
                    folder = candidate
                    break
            if folder is None and status.get(row["name"], {}).get("run_dir"):
                candidate = Path(status[row["name"]]["run_dir"])
                if (candidate / "manifest.json").is_file():
                    folder = candidate
            if folder is None:
                inventory.append({"run": row["name"], "included": "False", "exclusion": "plan row has no run folder",
                                  "status": status.get(row["name"], {}).get("state", "")})
                continue
            run = load_run(folder)
            check_plan_row(row, run)
            plan_by_run[run.name] = row
            status_by_run[run.name] = status.get(row["name"], {})
            runs.append(run)
    else:
        for folder in _discover(args.runs):
            runs.append(load_run(folder))

    horizon = args.horizon or max([r.horizon for r in runs if isinstance(r.horizon, int)] or [DEFAULT_HORIZON])
    analysed, excluded_reason = [], {}
    for run in runs:
        if run.scripted:
            excluded_reason[run.name] = "scripted-only run (a dry run or a demo: no model seats)"
        elif run.last_month == 0:
            excluded_reason[run.name] = "no month record: the run stopped before Month 1"
        elif args.complete_only and not (status_by_run.get(run.name, {}).get("state") == "done" or run.ended
                                         or run.last_month >= horizon):
            excluded_reason[run.name] = "incomplete (--complete-only)"
        else:
            analysed.append(run)

    labels = load_labels(args.labels) if args.labels else None
    all_exit_rows = {run.name: extract_exits(run) for run in runs}
    integrity = {}
    for run in analysed:
        if not args.no_integrity:
            integrity[run.name] = integrity_findings(run)

    observations = build_observations(analysed, labels=labels, horizon=horizon, complete_only=False,
                                      plan_by_run=plan_by_run, status_by_run=status_by_run,
                                      exits_by_run={r.name: all_exit_rows[r.name] for r in analysed})
    longest = max((max(o["raw_time"], o["last_month"]) for o in observations), default=horizon)
    tau = args.tau if args.tau else min(horizon, longest)
    if tau < 1:
        raise StudyError("--tau must be at least 1 month")
    prefix_list = ["raw"] + (["val"] if labels is not None else [])

    # ---- exits and reconciliation -----
    exits_rows = []
    for run in runs:
        for ev in all_exit_rows[run.name]:
            present, label = (False, None)
            if labels is not None:
                member = "" if ev["exit_class"] == "government" else ev["member"]
                present, label = labels.find(run.name, ev["month"], ev["exit_class"], member, ev["event_type"],
                                             ev["motion_id"])
            seat_model = run.seats.get(ev["member"], {}).get("model", "") if ev["member"] else ""
            exits_rows.append({"run": run.name, "analysed": str(run in analysed), "month": ev["month"],
                               "month_label": ev["month_label"], "exit_class": ev["exit_class"],
                               "event_type": ev["event_type"], "member": ev["member"], "model": seat_model,
                               "office": ev["office"], "motion_id": ev["motion_id"], "flags": ";".join(ev["flags"]),
                               "label": label or "", "label_present": str(present) if labels is not None else "NA"})

    # ---- inventory --
    for run in runs:
        status_state = status_by_run.get(run.name, {}).get("state", "") if status_by_run else ""
        included = run in analysed
        counts = Counter(ev["exit_class"] for ev in all_exit_rows.get(run.name, []))
        inventory.append({
            "run": run.name, "seed": run.seed, "rotation": (plan_by_run[run.name]["rotation"]
                                                              if run.name in plan_by_run else ""),
            "protocol": (plan_by_run[run.name]["protocol"] if run.name in plan_by_run
                         else (run.action_order or "unrecorded")),
            "office_assignment": run.office_assignment or "unrecorded", "status": status_state,
            "horizon": run.horizon, "last_month": run.last_month, "ended": str(run.ended),
            "outcome": run.outcome.get("type", ""), "stopped": run.stopped[:160],
            "member_exits": counts.get("member", 0), "office_exits": counts.get("office", 0),
            "government_exits": counts.get("government", 0), "election_rows": counts.get("election", 0),
            "included": str(included), "exclusion": excluded_reason.get(run.name, ""),
            "integrity": _integrity_label(run, integrity, analysed, args.no_integrity),
            "engine": run.engine,
            "served_models": json.dumps({L: run.seats[L]["served"] for L in LETTERS}, ensure_ascii=False),
            "warnings": " | ".join(sorted(set(run.warnings)))[:400]})
    _write_csv(out / "run_inventory.csv", inventory)
    _write_csv(out / "exits.csv", exits_rows)

    # ---- observations and survival ----
    _write_csv(out / "seat_observations.csv", [{k: v for k, v in o.items()} for o in observations])
    km_model_rows, km_office_rows, first_rows = [], [], []
    for prefix in prefix_list:
        km_model_rows += km_rows(observations, prefix, "model")
        km_office_rows += km_rows(observations, prefix, "office")
        for row in run_first_exit(observations, prefix):
            first_rows.append({"variant": "raw" if prefix == "raw" else "validated", **row})
    _write_csv(out / "km_by_model.csv", km_model_rows)
    _write_csv(out / "km_by_office.csv", km_office_rows)
    _write_csv(out / "km_first_exit.csv", first_rows)

    # ---- persistence, ablations, protocol pairs ----
    persistence = []
    for variant in (["raw"] + (["validated"] if labels is not None else [])):
        persistence += persistence_table(observations, tau, args.bootstrap, args.seed, variant)
    _write_csv(out / "persistence.csv", persistence)

    protocol_rows = []
    for variant in (["raw"] + (["validated"] if labels is not None else [])):
        protocol_rows += protocol_differences(observations, tau, args.bootstrap, args.seed, variant)
    _write_csv(out / "protocol_pairs.csv", protocol_rows)

    ablation_rows = _ablations(observations, tau, args.bootstrap, args.seed, args.fixed_rotation,
                               labels is not None)
    _write_csv(out / "ablations.csv", ablation_rows)

    # ---- rates ----
    call_by_model, call_by_office, mism_by_model, mism_by_office = {}, {}, {}, {}
    for run in analysed:
        rates = call_rates(run)
        findings = (integrity.get(run.name) or {}).get("findings") if integrity.get(run.name) else None
        mism = mismatch_counts(run, findings)
        offices = formation_offices(run) or {}
        for L in LETTERS:
            model = run.seats[L]["model"]
            office = office_group(offices.get(L))
            _add(call_by_model, model, rates[L])
            _add(call_by_office, office, rates[L])
            _add(mism_by_model, model, mism[L])
            _add(mism_by_office, office, mism[L])
    call_rows = _rates_rows(call_by_model) + [dict(r, group=f"office: {r['group']}") for r in _rates_rows(call_by_office)]
    _write_csv(out / "call_rates.csv", call_rows)
    mismatch_rows = _mismatch_rows(mism_by_model) + [dict(r, group=f"office: {r['group']}")
                                                     for r in _mismatch_rows(mism_by_office)]
    _write_csv(out / "mismatch_rates.csv", mismatch_rows)

    foreign = defaultdict(Counter)
    for run in analysed:
        for label, c in foreign_rates(run).items():
            foreign[label].update(c)
    foreign_rows = [{"backend": k, "calls": c.get("calls", 0), "answers": c.get("answers", 0),
                     "answers_with_problems": c.get("answers_with_problems", 0),
                     "problem_share": _round(_share(c.get("answers_with_problems", 0), c.get("answers", 0)))}
                    for k, c in sorted(foreign.items())]
    _write_csv(out / "foreign_rates.csv", foreign_rows)

    recl_rows = _reclassification(labels, analysed, exits_rows)
    _write_csv(out / "reclassification.csv", recl_rows)

    summary = _summary(args, runs, analysed, inventory, observations, labels, horizon, tau, persistence,
                       protocol_rows, ablation_rows, call_rows, mismatch_rows, foreign_rows, recl_rows,
                       km_model_rows, km_office_rows, exits_rows, integrity)
    with open(out / "summary.md", "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(summary) + "\n")
    print(f"analysed {len(analysed)} of {len(runs)} run folders, {len(observations)} seat observations; "
          f"tau {tau} months; {args.bootstrap} bootstrap replicates -> {out}")
    return 0


def _ablations(observations, tau, reps, seed, fixed_rotation, has_labels):
    rows = []
    rotations = sorted({o["rotation"] for o in observations if o["rotation"] is not None})
    fixed = fixed_rotation if fixed_rotation is not None else (rotations[0] if rotations else None)
    if len(rotations) > 1 and fixed is not None:
        grid = {(r["scope"], r["group"]): r for r in persistence_table(observations, tau, reps, seed, "raw")}
        single = {(r["scope"], r["group"]): r for r in persistence_table(
            [o for o in observations if o["rotation"] == fixed], tau, reps, seed, "raw")}
        for key, a in grid.items():
            b = single.get(key)
            if a["scope"] == "all":
                continue
            rows.append({"ablation": "role rotation", "scope": a["scope"], "group": a["group"],
                         "label_a": "all rotations", "estimate_a": a["diff_vs_all"], "ci_a_low": a["ci_low"],
                         "ci_a_high": a["ci_high"], "n_a": a["n"],
                         "label_b": f"rotation {fixed} only", "estimate_b": b["diff_vs_all"] if b else None,
                         "ci_b_low": b["ci_low"] if b else None, "ci_b_high": b["ci_high"] if b else None,
                         "n_b": b["n"] if b else 0})
    else:
        why = ("no plan, so the rotations are not recorded" if not rotations
               else f"only one rotation ({rotations[0]}) in the data")
        rows.append({"ablation": "role rotation", "scope": "all", "group": "NA",
                     "label_a": "not computed", "label_b": why})
    if has_labels:
        raw = {(r["scope"], r["group"]): r for r in persistence_table(observations, tau, reps, seed, "raw")}
        val = {(r["scope"], r["group"]): r for r in persistence_table(observations, tau, reps, seed, "validated")}
        for key, a in raw.items():
            b = val.get(key)
            if a["scope"] == "all":
                continue
            rows.append({"ablation": "event validation", "scope": a["scope"], "group": a["group"],
                         "label_a": "raw engine labels", "estimate_a": a["diff_vs_all"], "ci_a_low": a["ci_low"],
                         "ci_a_high": a["ci_high"], "n_a": a["n"], "label_b": "validated (supported only)",
                         "estimate_b": b["diff_vs_all"] if b else None, "ci_b_low": b["ci_low"] if b else None,
                         "ci_b_high": b["ci_high"] if b else None, "n_b": b["n"] if b else 0})
    return rows


def _reclassification(labels, analysed, exits_rows):
    if labels is None:
        return [{"group": "all", "labelled": 0, "reclassified": 0, "share": "NA",
                 "note": "no labels given: the audit has not been adjudicated"}]
    analysed_names = {r.name for r in analysed}
    model_of = {}
    for run in analysed:
        for L in LETTERS:
            model_of[(run.name, L)] = run.seats[L]["model"]
    groups = {"all": Counter()}
    for ev in labels.exit_rows:
        keys = ["all", f"class: {ev['exit_class'] or 'NA'}"]
        if ev["exit_class"] in ("member", "office") and ev["member"]:
            keys.append(f"model: {model_of.get((ev['run'], ev['member']), 'not analysed')}")
        for key in keys:
            groups.setdefault(key, Counter())
            if ev["label"] is None:
                groups[key]["unlabelled"] += 1
            else:
                groups[key]["labelled"] += 1
                if ev["label"] in ("ambiguous", "parser"):
                    groups[key]["reclassified"] += 1
    rows = []
    for key in sorted(groups, key=lambda k: (k != "all", k)):
        c = groups[key]
        rows.append({"group": key, "labelled": c["labelled"], "reclassified": c["reclassified"],
                     "share": _round(_share(c["reclassified"], c["labelled"])), "unlabelled": c["unlabelled"],
                     "note": "" if key != "all" else
                     f"{labels.counts['rows']} sample rows; apparent exits in the analysed runs: "
                     f"{sum(1 for r in exits_rows if r['analysed'] == 'True')}"})
    return rows


def _summary(args, runs, analysed, inventory, observations, labels, horizon, tau, persistence, protocol_rows,
             ablation_rows, call_rows, mismatch_rows, foreign_rows, recl_rows, km_model_rows, km_office_rows,
             exits_rows, integrity):
    out = ["# Study analysis: summary", ""]
    out.append(f"Run folders read: {len(runs)}; analysed: {len(analysed)}. Horizon {horizon} months; "
               f"restricted means use tau = {tau} months. Bootstrap: {args.bootstrap} replicates over seed "
               f"clusters, RNG seed {args.seed}.")
    out.append("")
    out.append("## What this run covers")
    out.append("")
    excluded = [r for r in inventory if r.get("included") == "False"]
    for row in excluded:
        out.append(f"- Left out: {row['run']}: {row['exclusion']}")
    if not excluded:
        out.append("- Nothing left out.")
    seeds = sorted({o["seed"] for o in observations if o["seed"] is not None}, key=str)
    out.append(f"- Seat observations: {len(observations)} ({len(seeds)} seed clusters).")
    runs_per_seed = Counter(r.seed for r in analysed)
    shared = {s: n for s, n in runs_per_seed.items() if n > 1}
    if shared:
        out.append("- Seeds shared by more than one run (one cluster in the bootstrap): "
                   + ", ".join(f"{s} ({n} runs)" for s, n in sorted(shared.items(), key=lambda kv: str(kv[0]))) + ".")
    engines = sorted({r["engine"] for r in inventory if r.get("included") == "True"})
    out.append(f"- Engine versions recorded by the analysed runs: {'; '.join(engines) if engines else 'none'}.")
    if labels is None:
        out.append("- Labels: none given, so only the raw engine labels are analysed.")
    else:
        out.append(f"- Labels: {labels.counts['rows']} sample rows, {labels.counts['labelled']} adjudicated, "
                   f"{labels.counts['blank']} blank.")
    out.append("")
    out.append("## Exits (apparent, before the audit)")
    out.append("")
    by_kind = Counter((r["exit_class"], r["event_type"]) for r in exits_rows if r["analysed"] == "True")
    rows = [[c, k, n] for (c, k), n in sorted(by_kind.items(), key=lambda kv: (EXIT_CLASS_ORDER.get(kv[0][0], 9), kv[0][1]))]
    out += _md_table(["exit class", "event", "rows"], rows) if rows else ["No exits in the analysed runs."]
    out.append("")
    out.append("## Time to exit (Kaplan-Meier; months in office, censored at each run's last month)")
    out.append("")
    out.append("NA means the group's follow-up ends before that month, so no value is given; a starred group has "
               f"fewer than {MIN_SEATS} seats and is not a finding.")
    out.append("")
    for scope, label in (("model", "by model"), ("office", "by formation office")):
        out.append(f"### {label}, raw engine labels")
        out.append("")
        out += _md_table(["group", "seats", "exits", "max follow-up", "S(12)", "S(24)", f"S({horizon})", "median"],
                         km_summary(observations, "raw", scope, horizon) if observations else [])
        out.append("")
        if labels is not None:
            out.append(f"### {label}, validated (supported exits only)")
            out.append("")
            out += _md_table(["group", "seats", "exits", "max follow-up", "S(12)", "S(24)", f"S({horizon})",
                              "median"], km_summary(observations, "val", scope, horizon))
            out.append("")
    out.append("## Persistence")
    out.append("")
    out.append("Effect sizes with bootstrap intervals over seeds, not a league table. Each group's restricted mean "
               "months in office, minus the grand mean of the same set. A group whose follow-up ends before the "
               "horizon gets NA, not a number.")
    out.append("")
    if len(seeds) < 5:
        out.append(f"Warning: only {len(seeds)} seed cluster(s). A bootstrap over so few seeds does not give a usable "
                   "interval; the grid has five seeds, and an interval needs that many.")
        out.append("")
    for variant in ("raw", "validated"):
        table = [r for r in persistence if r["variant"] == variant and r["scope"] != "all"]
        if not table:
            continue
        out.append(f"### {variant}")
        out.append("")
        rows = [[r["scope"], r["group"] + (" *" if r["small_group"] else ""), r["n"], r["events"],
                 r["max_follow_up"], _fmt(r["rmst"]), _fmt(r["diff_vs_all"]),
                 "NA" if r["ci_low"] is None else f"[{_fmt(r['ci_low'])}, {_fmt(r['ci_high'])}]",
                 "" if r["interaction"] is None else f"{_fmt(r['interaction'])} [{_fmt(r['interaction_ci_low'])}, "
                                                    f"{_fmt(r['interaction_ci_high'])}]"]
                for r in table]
        out += _md_table(["scope", "group", "n", "exits", "max follow-up", f"RMST to {tau}", "diff", "95% CI",
                          "interaction (cell only)"], rows)
        out.append("")
    out.append("## Invalid actions (delegates)")
    out.append("")
    out += _md_table(["group", "seats", "calls", "answers", "answers with a problem", "problem share",
                      "motions tabled", "rejected", "rejection share", "no answer share", "events per answer"],
                     [[r["group"], r["seats"], r["calls"], r["answers"], r["answers_with_problems"],
                       _fmt(r["problem_share"]), r["motions_tabled"], r["motions_rejected"],
                       _fmt(r["rejection_share"]), _fmt(r["no_answer_share"]), _fmt(r["events_per_answer"])]
                      for r in call_rows] if call_rows else [])
    out.append("")
    out.append("Foreign cabinets (neighbours), by backend label, not attributed to delegates:")
    out.append("")
    if foreign_rows:
        out += _md_table(["backend", "calls", "answers", "with a problem", "problem share"],
                         [[r["backend"], r["calls"], r["answers"], r["answers_with_problems"],
                           _fmt(r["problem_share"])] for r in foreign_rows])
    else:
        out.append("No foreign-cabinet calls in the analysed runs.")
    out.append("")
    out.append("## Action-execution mismatches")
    out.append("")
    out.append("Three separate rates, each with its own denominator: executed motions that the package's audit flags "
               "as a different act; directive-order mismatches among compliance rows; vote-intent mismatches among "
               "votes cast.")
    out.append("")
    out += _md_table(["group", "seats", "executed motions", "audit mismatches", "audit share", "compliance rows",
                      "directive mismatches", "directive share", "votes", "vote-intent mismatches", "share"],
                     [[r["group"], r["seats"], r["executed_motions"], r["audit_mismatches"], _fmt(r["audit_share"]),
                       r["compliance_rows"], r["directive_mismatches"], _fmt(r["directive_share"]), r["votes"],
                       r["vote_intent_mismatches"], _fmt(r["vote_intent_share"])] for r in mismatch_rows]
                     if mismatch_rows else [])
    out.append("")
    out.append("## Reclassified exits")
    out.append("")
    if labels is None:
        out.append("No labels given, so no apparent exit has been reclassified: the audit sample has not been "
                   "adjudicated. The share is not computed.")
    else:
        out += _md_table(["group", "labelled", "reclassified", "share", "unlabelled"],
                         [[r["group"], r["labelled"], r["reclassified"], _fmt(r["share"]), r.get("unlabelled", "")]
                          for r in recl_rows])
    out.append("")
    out.append("## Order protocols (paired by seed, rotation and seat)")
    out.append("")
    if protocol_rows:
        out += _md_table(["variant", "scope", "group", "run pairs", "seat pairs", "mean diff (months)", "95% CI"],
                         [[r["variant"], r["scope"], r["group"], r["run_pairs"], r["seat_pairs"],
                           _fmt(r["mean_diff"]), f"[{_fmt(r['ci_low'])}, {_fmt(r['ci_high'])}]"]
                          for r in protocol_rows if r["scope"] == "all"])
    else:
        out.append("No matched pairs: the protocols do not both appear for the same seed, rotation and seat, with "
                   "both runs complete.")
    out.append("")
    out.append("## Ablations")
    out.append("")
    if ablation_rows:
        out += _md_table(["ablation", "scope", "group", "estimate A", "A label", "estimate B", "B label"],
                         [[r["ablation"], r["scope"], r["group"], _fmt(r.get("estimate_a")), r.get("label_a", ""),
                           _fmt(r.get("estimate_b")), r.get("label_b", "")] for r in ablation_rows])
    else:
        out.append("Not computed.")
    out.append("")
    out.append("## Caveats")
    out.append("")
    out.append("- Intervals over seeds are only as good as the number of seeds: with a handful of clusters they are wide.")
    out.append("- The model key is the configured seat model. A seat served by a router answered with several models "
               "(served_models in run_inventory.csv); those seats are not one model.")
    out.append("- Office groups use the formation offices. The engine can reassign offices later; that is an office "
               "exit only for a seat's own formation office.")
    out.append("- Unlabelled exits count as not supported in the validated variant, so validated survival is lower "
               "bound-biased toward persistence until every exit is adjudicated.")
    out.append("- No Cox model and no kappa in this script (see the report).")
    return out


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StudyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
