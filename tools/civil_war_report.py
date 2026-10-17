"""The civil-war arm's measures, on run folders: per run, per arm, and against a same-seed twin.

    python tools/civil_war_report.py RUN_OR_DIR [RUN_OR_DIR ...] --out DIR
    python tools/civil_war_report.py --pair WAR_RUN TWIN_RUN [--pair ...] --out DIR

A run folder holds ``config.json``, ``checkpoint.json`` and ``log.jsonl``, as the runner writes
them. The war's month records are the ``civil_war`` key the C5 hook puts on each history row
(engine.snapshot): C2's combat record (fronts, casualties, control changes, refugees, defections)
and C3's faction record (answer, orders, the government's reply), plus C4's offers, breaches,
ceasefire state, settlement and the war's outcome. A run recorded before that hook existed still
reports its start, duration and end from the checkpoint, with a note that its month records are
absent.

Per run: whether and when a war started; its duration in months; how it ended (government victory,
rebel victory, settlement, partition, collapse, still running); soldier losses by side, civilian
deaths, damage and refugees; settlement against victory; offers, acceptances and refusals; broken
ceasefires and breaches; which seats and offices are in rebellion and which of them appear at the
front (armed offices), defect (the monthly allegiance movement C2 records) or negotiate (the
members C3's faction records name).

Per arm: the counts above across its runs, including how often a war started.

Against a twin: the same seed with the war arm off. The two must be the same run up to the month
the war starts; the tool refuses a pair whose earlier history rows differ. For approval, unrest,
fear (the engine's unrest input alongside grievance, which is not in the history row) and the food
ratio it reports the difference month by month and its difference in differences against the last
month before the war, as tools/knockout_report.py does for the knockout arm.

Writes into --out: ``civil_war_report.md`` (the readable report) and
``civil_war_report.json`` (every number above). Standard library only, no model calls, read-only.
The JSON's ``month`` is the engine's 0-based index; the report labels it "Month N" (index + 1).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

METRICS = ("approval", "unrest", "fear", "food_ratio")
END_LABELS = {
    "settled": "settlement",
    "civil_war_won_by_government": "government victory",
    "civil_war_won_by_rebels": "rebel victory",
    "partitioned": "partition",
    "no_government": "collapse",
}


class ReportError(Exception):
    """A problem with the input runs. The command stops and says what; it never reports a false pair."""


def month_label(index):
    """The plan's label for a 0-based engine month: index 0 is Month 1."""
    return f"Month {int(index) + 1}"


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        raise ReportError(f"{path}: cannot read JSON ({exc})") from exc


def _read_jsonl(path):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    out.append(json.loads(line))
    except (OSError, ValueError) as exc:
        raise ReportError(f"{path}: cannot read JSON lines ({exc})") from exc
    return out


def _number(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number


def _round(value, digits=4):
    return round(value, digits) if isinstance(value, (int, float)) else value


class Run:
    """One run folder: its config, checkpoint, month records and the war state."""

    def __init__(self, path):
        self.path = Path(path)
        self.name = self.path.name
        checkpoint = self.path / "checkpoint.json"
        if not checkpoint.is_file():
            raise ReportError(f"{self.path}: no checkpoint.json")
        loaded = _read_json(checkpoint)
        self.world = loaded.get("world") or {}
        self.history = sorted((row for row in self.world.get("history") or [] if isinstance(row, dict)),
                              key=lambda row: row.get("month", -1))
        config = self.path / "config.json"
        self.config = _read_json(config) if config.is_file() else {}
        run = self.config.get("run") if isinstance(self.config.get("run"), dict) else {}
        self.seed = run.get("seed")
        self.option = str(run.get("civil_war", "off") or "off")
        self.source = str(self.config.get("source") or "")
        self.arm = self.source.split(":")[1] if self.source.startswith("cw-sweep:") else self.option
        self.twin = run.get("twin")
        manifest = self.path / "manifest.json"
        self.manifest = _read_json(manifest) if manifest.is_file() else {}
        self.state = self.world.get("civil_war") if isinstance(self.world.get("civil_war"), dict) else None
        self.outcome = self.world.get("outcome") if isinstance(self.world.get("outcome"), dict) else {}
        self.counters = self.world.get("counters") if isinstance(self.world.get("counters"), dict) else {}
        self.offices = {}
        if self.history:
            self.offices = self.history[-1].get("offices") or {}
        self.months = [row for row in self.history if isinstance(row.get("civil_war"), dict)]
        self.records = {}
        log = self.path / "log.jsonl"
        if log.is_file():
            for record in _read_jsonl(log):
                if record.get("type") == "month" and isinstance(record.get("month"), int):
                    self.records[record["month"]] = record

    @property
    def war_started(self):
        return self.state is not None or bool(self.months)

    @property
    def run_outcome(self):
        """The run's own outcome type: the checkpoint first, the manifest as the fallback for a
        checkpoint written before the outcome was final."""
        return ((self.outcome or {}).get("type")
                or (self.manifest.get("outcome") or {}).get("type", ""))

    @property
    def war_since(self):
        if isinstance(self.state, dict) and isinstance(self.state.get("since"), int):
            return self.state["since"]
        return self.months[0]["month"] if self.months else None

    @property
    def war_outcome(self):
        if isinstance(self.state, dict) and isinstance(self.state.get("outcome"), dict):
            return self.state["outcome"]
        # A checkpoint recorded before C4 kept the war's outcome only in the run's own outcome,
        # and only for the terminal cases. Read it back rather than call such a war "running".
        for source in (self.outcome, self.manifest.get("outcome")):
            if isinstance(source, dict) and source.get("type") in END_LABELS:
                return source
        return None

    @property
    def last_month(self):
        return self.history[-1]["month"] if self.history else None

    @property
    def war_duration(self):
        """Months from the start month through the end month, both counted; a running war through
        the last recorded month."""
        since = self.war_since
        if since is None:
            return None
        end = (self.war_outcome or {}).get("month")
        if end is None:
            end = self.last_month
        if end is None or end < since:
            return None
        return int(end) - int(since) + 1

    @property
    def war_end_label(self):
        outcome = self.war_outcome
        if outcome is not None:
            return END_LABELS.get(outcome.get("type"), str(outcome.get("type") or "outcome"))
        if self.war_started:
            return "still running"
        return "none"


def discover(paths) -> list:
    """Every run folder under the paths given, in a stable order."""
    found = []
    seen = set()
    for path in paths:
        path = Path(path)
        candidates = [path] if (path / "checkpoint.json").is_file() else sorted(path.rglob("checkpoint.json"))
        for candidate in candidates:
            folder = candidate if candidate.is_dir() else candidate.parent
            resolved = str(folder.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(Run(folder))
    if not found:
        raise ReportError("no run folders with a checkpoint.json were found")
    return found


def war_measure(run: Run) -> dict:
    """Every per-run measure above, read from the war state and its month records."""
    state = run.state or {}
    combat_rows = []
    soldiers = {"government": 0.0, "rebels": 0.0, "civilians": 0.0}
    equivalent = {"government": 0.0, "rebels": 0.0}
    damage = 0.0
    refugees = 0.0
    defections = {}
    control_changes = []
    breach_rows = 0
    for row in run.months:
        record = row.get("civil_war") or {}
        combat = record.get("combat")
        if not isinstance(combat, dict):
            continue
        combat_rows.append(row["month"])
        losses = combat.get("losses") or {}
        for side in ("government", "rebels", "civilians"):
            soldiers[side] += _number(losses.get(side))
        loss_eq = combat.get("losses_equivalent") or {}
        for side in ("government", "rebels"):
            equivalent[side] += _number(loss_eq.get(side))
        for front in (combat.get("fronts") or {}).values():
            damage += _number(front.get("damage"))
        refugees += _number(combat.get("refugees"))
        for change in combat.get("control_changes") or []:
            control_changes.append(dict(change))
        for office, block in (combat.get("defections") or {}).items():
            if not isinstance(block, dict):
                continue
            entry = defections.setdefault(office, {"government": 0.0, "rebels": 0.0, "neutral": 0.0,
                                                   "months": 0})
            before = block.get("before") or {}
            after = block.get("after") or {}
            for side in ("government", "rebels", "neutral"):
                entry[side] += _number(after.get(side)) - _number(before.get(side))
            entry["months"] += 1
        if record.get("ceasefire_breach"):
            breach_rows += 1
    for office in defections:
        for side in ("government", "rebels", "neutral"):
            defections[office][side] = round(defections[office][side], 6)
    offers = [dict(entry) for entry in state.get("offers") or [] if isinstance(entry, dict)]
    statuses = {}
    for offer in offers:
        statuses[offer.get("status", "?")] = statuses.get(offer.get("status", "?"), 0) + 1
    ceasefire = state.get("ceasefire") if isinstance(state.get("ceasefire"), dict) else {}
    ceasefire_offers = [dict(entry) for entry in ceasefire.get("offers") or [] if isinstance(entry, dict)]
    ceasefire_statuses = {}
    for offer in ceasefire_offers:
        ceasefire_statuses[offer.get("status", "?")] = ceasefire_statuses.get(offer.get("status", "?"), 0) + 1
    breaches = [dict(entry) for entry in state.get("breaches") or [] if isinstance(entry, dict)]
    factions = state.get("factions") if isinstance(state.get("factions"), dict) else {}
    rebels = ((factions.get("rebels") or {}).get("members") or []) if isinstance(factions, dict) else []
    government = ((factions.get("government") or {}).get("members") or []) if isinstance(factions, dict) else []
    # The war state's own faction block names the holder of each armed office while C1 wrote it;
    # C2 rewrites the top-level `forces` but leaves the faction blocks alone. The last history row's
    # offices are the fallback, and they are empty when a handover removed the old government.
    rebel_offices = {}
    rebel_forces = ((factions.get("rebels") or {}).get("forces") or {}) if isinstance(factions, dict) else {}
    for office, entry in rebel_forces.items():
        holder = entry.get("holder") if isinstance(entry, dict) else None
        if holder in rebels and _number(entry.get("share")) > 0.0:
            rebel_offices[office] = holder
    if not rebel_offices:
        rebel_offices = {office: holder for office, holder in run.offices.items() if holder in rebels}
    spoke = set()
    replies = {"offers_answered": 0, "accepted": 0, "refused": 0}
    for row in run.months:
        record = row.get("civil_war") or {}
        for member in record.get("spoke") or []:
            spoke.add(member)
        reply = record.get("government_reply")
        if isinstance(reply, dict):
            replies["offers_answered"] += 1
            if reply.get("accept") is True:
                replies["accepted"] += 1
            elif reply.get("accept") is False:
                replies["refused"] += 1
    counter_killed = {key: _number(value) for key, value in run.counters.items()
                      if key in ("civil_war_soldiers_killed", "civil_war_government_killed",
                                 "civil_war_rebel_killed", "civil_war_security_killed",
                                 "civil_war_sailors_killed", "civil_war_civilians_killed")}
    # The seats that command a fighting service on the rebel side, and the services whose allegiance
    # moved at all. "Which seats defect" is a question about people the war state names; the
    # defection model moves services, so the report names the service and its movement.
    fighting = sorted({holder for office, holder in rebel_offices.items()})
    defected_services = sorted(office for office, entry in defections.items()
                               if any(abs(entry.get(side, 0.0)) >= 1e-9
                                      for side in ("government", "rebels", "neutral")))
    return {
        "run": run.name, "path": str(run.path.resolve()), "arm": run.arm, "seed": run.seed,
        "option": run.option, "started": run.war_started, "since": run.war_since,
        "since_label": None if run.war_since is None else month_label(run.war_since),
        "duration": run.war_duration, "end": run.war_end_label,
        "cause": state.get("cause"),
        "war_outcome": run.war_outcome, "run_outcome": run.run_outcome,
        "manifest_outcome": (run.manifest.get("outcome") or {}).get("type", ""),
        "manifest_months": run.manifest.get("months_simulated"),
        "month_records": len(run.months), "combat_records": len(combat_rows),
        "month_records_note": ("" if combat_rows or not run.war_started else
                               "no combat data in the month records: the run predates the C5 record "
                               "hook, or the scripted rebels never attacked"),
        "soldiers_lost": {side: round(value, 1) for side, value in soldiers.items()},
        "soldiers_lost_equivalent": {side: round(value, 1) for side, value in equivalent.items()},
        "killed_counters": {key: round(value, 1) for key, value in counter_killed.items()},
        "damage": round(damage, 4), "refugees": round(refugees, 1),
        "control_changes": control_changes, "defections": defections,
        "offers": {"total": len(offers), "statuses": statuses, "records": offers},
        "ceasefire": {"active": bool(ceasefire.get("active")) and not bool(ceasefire.get("broken")),
                      "broken": bool(ceasefire.get("broken")),
                      "offers_total": len(ceasefire_offers), "statuses": ceasefire_statuses},
        "breaches": {"total": len(breaches), "rows": breaches, "breach_months": breach_rows},
        "settlement": state.get("settlement"),
        "factions": {"rebels": list(rebels), "government": list(government),
                     "rebel_leader": (factions.get("rebels") or {}).get("leader") if isinstance(factions, dict) else None,
                     "government_leader": (factions.get("government") or {}).get("leader") if isinstance(factions, dict) else None,
                     "rebel_offices": rebel_offices, "fighting": fighting,
                     "defected_services": defected_services,
                     "negotiated_by": sorted(spoke)},
        "government_replies": replies,
        "combat_months": combat_rows,
        "last_orders": (run.months[-1]["civil_war"].get("orders") if run.months else None),
    }


def arm_measure(runs: list) -> dict:
    """The counts above across one arm's on runs; its off twins are counted separately."""
    on = [run for run in runs if run["option"] == "on"]
    twins = [run for run in runs if run["option"] != "on"]
    started = [run for run in on if run["started"]]
    ends = {}
    durations = []
    for run in started:
        ends[run["end"]] = ends.get(run["end"], 0) + 1
        if run["duration"] is not None:
            durations.append(run["duration"])
    return {
        "runs": len(on), "twins": len(twins), "started": len(started),
        "started_share": round(len(started) / len(on), 4) if on else None,
        "seeds_started": sorted({run["seed"] for run in started if run["seed"] is not None}),
        "ends": ends,
        "duration_mean": round(sum(durations) / len(durations), 2) if durations else None,
        "soldiers_lost": {side: round(sum(run["soldiers_lost"][side] for run in started), 1)
                          for side in ("government", "rebels", "civilians")},
        "refugees": round(sum(run["refugees"] for run in started), 1),
        "settlements": sum(1 for run in started if run["end"] == "settlement"),
        "victories": {key: sum(1 for run in started if run["end"] == key)
                      for key in ("government victory", "rebel victory")},
        "breaches": sum(run["breaches"]["total"] for run in started),
        "offers": sum(run["offers"]["total"] for run in started),
        "offer_statuses": _merge_counts(run["offers"]["statuses"] for run in started),
        "ceasefire_statuses": _merge_counts(run["ceasefire"]["statuses"] for run in started),
        "war_outcomes": _merge_counts((run["war_outcome"] or {}).get("type") for run in started
                                      if run["war_outcome"]),
    }


def _merge_counts(counts) -> dict:
    out = {}
    for item in counts:
        if isinstance(item, dict):
            for key, value in item.items():
                out[key] = out.get(key, 0) + value
        elif isinstance(item, (int, str)) and item is not None:
            out[item] = out.get(item, 0) + 1
    return out


# ---- the twin ------------------------------------------------------------------------------

def _row_without_code_fingerprint(row):
    """A history row as compared between twins: the code fingerprint is the same file on both
    sides, and an on run's pre-war rows carry no civil_war key, so nothing else is dropped."""
    return row


def twin_differences(war: Run, twin: Run, start: int) -> list:
    """Differences in the history rows before the war's start month; empty means a twin pair."""
    left = {row.get("month"): row for row in war.history}
    right = {row.get("month"): row for row in twin.history}
    problems = []
    for month in sorted(m for m in set(left) | set(right) if isinstance(m, int) and m < start):
        if left.get(month) != right.get(month):
            problems.append(month_label(month))
            if len(problems) >= 5:
                break
    return problems


def did_table(war: Run, twin: Run, start: int) -> dict:
    """Approval, unrest, fear and food ratio month by month: war, twin, difference, DiD.

    The DiD base is the last month before the war (or the first month when the war starts in
    Month 1, which the design forbids but a hand-built checkpoint may do).
    """
    left = {row.get("month"): row for row in war.history}
    right = {row.get("month"): row for row in twin.history}
    base_month = start - 1 if start > 0 else 0
    base = {}
    for metric in METRICS:
        a = (left.get(base_month) or {}).get(metric)
        b = (right.get(base_month) or {}).get(metric)
        base[metric] = (None if a is None or b is None else _number(a) - _number(b))
    rows = []
    for month in sorted(m for m in set(left) & set(right) if isinstance(m, int)):
        entry = {"month": month, "month_label": month_label(month),
                 "phase": "before" if month < start else "war month" if month == start else "after"}
        for metric in METRICS:
            a = left[month].get(metric)
            b = right[month].get(metric)
            if a is None or b is None:
                entry[metric] = {"war": a, "twin": b, "diff": None, "did": None}
                continue
            diff = _number(a) - _number(b)
            base_value = base[metric]
            entry[metric] = {"war": a, "twin": b, "diff": round(diff, 6),
                             "did": None if base_value is None else round(diff - base_value, 6)}
        rows.append(entry)
    return {"base_month": base_month, "base_difference": {m: (None if base[m] is None else round(base[m], 6))
                                                          for m in METRICS},
            "months": rows}


def pair_measure(war_path, twin_path) -> dict:
    war, twin = Run(war_path), Run(twin_path)
    if not war.war_started:
        raise ReportError(f"{war.name}: the war run records no civil war; nothing to compare")
    start = war.war_since
    if start is None:
        raise ReportError(f"{war.name}: the war's start month is missing")
    differences = twin_differences(war, twin, start)
    if differences:
        shown = ", ".join(differences)
        raise ReportError(
            f"{war.name} and {twin.name} are not a twin pair: their history rows before the war "
            f"(before {month_label(start)}) differ in {shown}. Only the same run up to the war can "
            "be compared.")
    return {"war": war.name, "twin": twin.name, "war_arm": war.arm, "seed": war.seed,
            "start": start, "start_label": month_label(start),
            "twin_identical_before": True, "did": did_table(war, twin, start)}


# ---- writing -------------------------------------------------------------------------------

def _fmt(value, digits=4):
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        cells = [str(cell).replace("|", "/") for cell in row]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def write_markdown(report, path):
    lines = ["# Civil-war report", ""]
    lines += [f"Runs: {len(report['runs'])}; arms: {', '.join(report['arm_order'])}.", ""]
    lines += ["## Per arm", ""]
    rows = []
    for arm in report["arm_order"]:
        item = report["arms"][arm]
        share = "NA" if item["started_share"] is None else f"{item['started_share']:.0%}"
        rows.append([arm, item["runs"], item["twins"], item["started"], share,
                     ", ".join(str(s) for s in item["seeds_started"]) or "-",
                     _fmt(item["duration_mean"], 2),
                     item["settlements"], item["victories"]["government victory"],
                     item["victories"]["rebel victory"], item["breaches"]])
    lines += _md_table(["arm", "runs", "twins", "wars", "share", "seeds", "mean months", "settled",
                        "gov victory", "rebel victory", "breaches"], rows)
    lines += ["", "## Per run", ""]
    rows = []
    for run in report["runs"]:
        rows.append([run["run"], run["arm"], run["seed"], "yes" if run["started"] else "no",
                     run["since_label"] or "-", _fmt(run["duration"], 0), run["end"],
                     f"{run['soldiers_lost']['government']:,.0f} / {run['soldiers_lost']['rebels']:,.0f}",
                     f"{run['soldiers_lost']['civilians']:,.0f}",
                     f"{run['refugees']:,.0f}",
                     f"{run['offers']['total']} / {run['government_replies']['accepted']} / "
                     f"{run['government_replies']['refused']}",
                     run["breaches"]["total"]])
    lines += _md_table(["run", "arm", "seed", "war", "since", "months", "end",
                        "soldiers gov / rebels", "civilians", "refugees",
                        "offers / accepted / refused", "breaches"], rows)
    lines += ["", "## Wars in detail", ""]
    any_war = False
    for run in report["runs"]:
        if not run["started"]:
            continue
        any_war = True
        lines += [f"### {run['run']} ({run['arm']}, seed {run['seed']})", "",
                  f"- Started: {run['since_label']} (cause: {run['cause'] or 'not recorded'}); "
                  f"duration {run['duration']} month(s); end: {run['end']}.",
                  f"- Run outcome: {run['run_outcome'] or 'not ended'}.",
                  f"- Soldiers lost (wounded and dead): government {run['soldiers_lost']['government']:,.0f}, "
                  f"rebels {run['soldiers_lost']['rebels']:,.0f}; civilians {run['soldiers_lost']['civilians']:,.0f}.",
                  f"- Damage {run['damage']:.4f}; refugees {run['refugees']:,.0f}; control changes "
                  f"{len(run['control_changes'])}.",
                  f"- Settlement offers: {run['offers']['total']} ({_status_text(run['offers']['statuses'])}); "
                  f"government answers: {run['government_replies']['accepted']} accepted, "
                  f"{run['government_replies']['refused']} refused.",
                  f"- Ceasefire offers: {run['ceasefire']['offers_total']} "
                  f"({_status_text(run['ceasefire']['statuses'])}); in force at the end: "
                  f"{run['ceasefire']['active']}; breaches recorded: {run['breaches']['total']}.",
                  f"- Rebels: {', '.join(run['factions']['rebels']) or '-'} "
                  f"(leader {run['factions']['rebel_leader'] or '-'}); rebel-held offices: "
                  f"{', '.join(f'{o}={m}' for o, m in run['factions']['rebel_offices'].items()) or '-'}.",
                  f"- Fighting on the rebel side: {', '.join(run['factions']['fighting']) or '-'}; "
                  f"services whose allegiance moved: "
                  f"{', '.join(run['factions']['defected_services']) or 'none'}.",
                  f"- Negotiated by: {', '.join(run['factions']['negotiated_by']) or '-'}.",
                  f"- Defection movement (share of each service, summed over the war): "
                  f"{_defection_text(run['defections'])}."]
        if run["settlement"]:
            lines.append(f"- Settlement terms: {json.dumps(run['settlement'].get('terms'), ensure_ascii=False)}.")
        if run["month_records_note"]:
            lines.append(f"- Note: {run['month_records_note']}.")
        lines.append("")
    if not any_war:
        lines += ["No run in this report started a civil war.", ""]
    lines += ["## Against the twin (difference in differences)", ""]
    if not report["pairs"]:
        lines += ["No pairs were given or found.", ""]
    for pair in report["pairs"]:
        lines += [f"### {pair['war']} against {pair['twin']}", "",
                  f"War start: {pair['start_label']}; every history row before it matches the twin. "
                  f"The DiD base is the last month before the war (Month {pair['did']['base_month'] + 1}).", ""]
        headers = ["month", "phase"] + [part for metric in METRICS
                                        for part in (f"{metric} war", f"{metric} twin",
                                                     f"{metric} diff", f"{metric} DiD")]
        rows = []
        for entry in pair["did"]["months"]:
            cells = [entry["month_label"], entry["phase"]]
            for metric in METRICS:
                cell = entry[metric]
                cells += [_fmt(cell["war"]), _fmt(cell["twin"]), _fmt(cell["diff"]), _fmt(cell["did"])]
            rows.append(cells)
        lines += _md_table(headers, rows)
        lines += [""]
    lines += ["## Notes", "",
              "Month labels are the engine's 0-based index + 1 in this report and in the text; the JSON "
              "keeps the engine index. Soldier losses are C2's active losses (dead and wounded); the "
              "killed counters (30% of the losses, the engine's convention) are in the JSON. Damage is "
              "the sum of each fighting front's monthly damage. Fear is reported with unrest because "
              "the engine derives unrest from grievance and fear and only those two are in the history "
              "row; grievance itself is per region in region_detail and is not carried in the row.", ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _status_text(statuses: dict) -> str:
    if not statuses:
        return "none"
    return ", ".join(f"{key} {value}" for key, value in sorted(statuses.items()))


def _defection_text(defections: dict) -> str:
    if not defections:
        return "none"
    parts = []
    for office, entry in sorted(defections.items()):
        parts.append(f"{office}: government {entry.get('government', 0):+.4f}, "
                     f"rebels {entry.get('rebels', 0):+.4f}, neutral {entry.get('neutral', 0):+.4f}")
    return "; ".join(parts)


def analyse(run_paths, pair_paths):
    runs = discover(run_paths) if run_paths else []
    known = {str(run.path.resolve()) for run in runs}
    # A pair given without its folders in the run list still gets both runs into the per-run table,
    # so its numbers are never orphaned from the runs that produced them.
    for war, twin in pair_paths:
        for path in (war, twin):
            folder = Path(path)
            if not (folder / "checkpoint.json").is_file():
                folder = folder.parent
            if str(folder.resolve()) not in known:
                known.add(str(folder.resolve()))
                runs.append(Run(folder))
    measures = [war_measure(run) for run in runs]
    by_arm = {}
    for measure in measures:
        by_arm.setdefault(measure["arm"], []).append(measure)
    arms = {arm: arm_measure(items) for arm, items in by_arm.items()}
    pairs = [pair_measure(war, twin) for war, twin in pair_paths]
    report = {
        "format": 1,
        "arm_order": sorted(arms),
        "arms": arms,
        "runs": measures,
        "pairs": pairs,
    }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="The civil war's measures per run, per arm and against a twin.")
    parser.add_argument("runs", nargs="*", help="run folders, or folders holding them")
    parser.add_argument("--pair", nargs=2, action="append", default=[], metavar=("WAR_RUN", "TWIN_RUN"),
                        help="a war run and its same-seed twin without the war; repeatable")
    parser.add_argument("--out", required=True, help="folder for the report and its JSON sidecar")
    args = parser.parse_args(argv)
    if not args.runs and not args.pair:
        parser.error("give at least one run folder or one --pair")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        report = analyse(args.runs, [tuple(pair) for pair in args.pair])
    except ReportError as exc:
        print(f"civil_war_report: {exc}", file=sys.stderr)
        return 2
    with open(out / "civil_war_report.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    write_markdown(report, out / "civil_war_report.md")
    started = sum(1 for run in report["runs"] if run["started"])
    print(f"civil_war_report: {len(report['runs'])} run(s), {started} with a civil war, "
          f"{len(report['pairs'])} pair(s); wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
