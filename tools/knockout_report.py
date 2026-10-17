"""The knockout arm's measures, on a pair of runs: the run with the knockout and its same-seed twin.

    python tools/knockout_report.py KNOCKOUT_RUN TWIN_RUN --out DIR [--band 0.02] [--window 3]

The pair is a run with `run.knockout` set and the same seed, models and arms without it. The two are only
a pair if they are the same run up to the arm: every history row before the knockout month must be
identical, and the tool refuses a folder that does not match (`karamaniya.knockout.twin_differences`).

Measures:
  - months until the office is filled: the first end-of-month row at or after the knockout whose office is
    held again, counted from the knockout month (0 = filled in the knockout month's own session); a run
    that ends with the office still vacant reports it as not filled;
  - motions passed and executed per month, the `--window` months before against the `--window` after
    (the knockout month itself is listed but not counted in either), for both runs and their difference;
  - approval, unrest and food ratio against the twin month by month, with the difference (knockout minus
    twin) and its difference in differences from the last month before the knockout;
  - coups, defiance rows and decision-rule changes from the knockout month onward;
  - recovery time: the months until the approval difference is back within `--band` of the twin (the
    preregistered band, default 0.02), with whether it stayed within the band afterwards.

Writes into --out: `knockout_report.md` (the readable report), `knockout_report.json` (every number
above) and `knockout_months.csv` (one row per month). Standard library only. `month` is the engine's
0-based index throughout; the report labels it "Month N" (index + 1), as the plan does.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # the package imports from the repository root, as the other tools do

from karamaniya import knockout  # noqa: E402

METRICS = ("approval", "unrest", "food_ratio")
DEFAULT_BAND = 0.02
DEFAULT_WINDOW = 3


class ReportError(Exception):
    """A problem with the input runs. The command stops and says what; it never reports a false pair."""


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


def month_label(index):
    """The plan's label for a 0-based engine month: index 0 is Month 1."""
    return f"Month {int(index) + 1}"


class Run:
    """One run folder: the checkpoint's world history and members, the config, and the month records."""

    def __init__(self, path):
        self.path = Path(path)
        self.name = self.path.name
        checkpoint = self.path / "checkpoint.json"
        log = self.path / "log.jsonl"
        if not checkpoint.is_file():
            raise ReportError(f"{self.path}: no checkpoint.json")
        if not log.is_file():
            raise ReportError(f"{self.path}: no log.jsonl")
        loaded = _read_json(checkpoint)
        self.world = loaded.get("world") or {}
        self.history = sorted((row for row in self.world.get("history") or [] if isinstance(row, dict)),
                              key=lambda row: row.get("month", -1))
        self.members = {m.get("id"): m for m in self.world.get("members") or [] if isinstance(m, dict)}
        self.state = ((self.world.get("institutions") or {}).get(knockout.STATE_KEY)
                      if isinstance(self.world.get("institutions"), dict) else None)
        self.records = {}
        for record in _read_jsonl(log):
            if record.get("type") == "month" and isinstance(record.get("month"), int):
                self.records[record["month"]] = record
        config = self.path / "config.json"
        self.config = _read_json(config) if config.is_file() else {}
        run = self.config.get("run") if isinstance(self.config.get("run"), dict) else {}
        try:
            self.option = knockout.validate_option(run.get("knockout"))
        except ValueError as exc:
            raise ReportError(f"{self.path}: config.json: {exc}") from exc

    def row(self, month):
        for row in self.history:
            if row.get("month") == month:
                return row
        return None


def detect_knockout(run):
    """Where and when the arm fired in this run, or None. The checkpoint's state is the record of the
    removal; the month row's `incapacitated` event is the fallback for a run saved before the state
    key existed (there is none yet, but the report should not depend on the key's lifetime)."""
    state = run.state
    if isinstance(state, dict) and isinstance(state.get("engine_month"), int) and state.get("office"):
        option = state.get("option") if isinstance(state.get("option"), dict) else {}
        return {"office": state["office"], "engine_month": state["engine_month"],
                "month_label": month_label(state["engine_month"]),
                "option": option, "member": state.get("member"), "status": state.get("status") or "removed",
                "source": "checkpoint state"}
    for row in run.history:
        for event in row.get("events") or []:
            if isinstance(event, dict) and event.get("kind") == "incapacitated" and event.get("office"):
                index = row.get("month")
                return {"office": event["office"], "engine_month": index, "month_label": month_label(index),
                        "option": run.option or {}, "member": event.get("member"), "status": "removed",
                        "source": "history event"}
    if run.option:
        raise ReportError(
            f"{run.path}: the config sets knockout {run.option}, but the run records no removal "
            f"(no checkpoint state and no public event); it did not fire before the run ended")
    return None


def months_until_filled(run, office, start):
    """The first end-of-month row at or after `start` whose office is held again, counted from `start`."""
    for row in run.history:
        index = row.get("month")
        if not isinstance(index, int) or index < start:
            continue
        holder = (row.get("offices") or {}).get(office)
        if holder:
            return {"months": index - start, "engine_month": index, "month_label": month_label(index),
                    "member": str(holder)}
    return {"months": None, "engine_month": None, "month_label": None, "member": None}


def motion_counts(run, months):
    """Motions passed and executed in those months. Executed means passed and EXECUTED, as the engine
    records execution; withdrawn and void motions never count. A month with no record counts zero and is
    named in `missing`."""
    passed = executed = 0
    missing = []
    for index in months:
        record = run.records.get(index)
        if record is None:
            missing.append(index)
            continue
        for motion in record.get("motions") or []:
            if motion.get("withdrawn") or motion.get("void"):
                continue
            if motion.get("passed"):
                passed += 1
                if motion.get("execution_status") == "EXECUTED":
                    executed += 1
    return {"passed": passed, "executed": executed, "months": list(months), "missing": missing}


def _difference(ko, twin):
    return {"before_passed": ko["before"]["passed"] - twin["before"]["passed"],
            "after_passed": ko["after"]["passed"] - twin["after"]["passed"],
            "before_executed": ko["before"]["executed"] - twin["before"]["executed"],
            "after_executed": ko["after"]["executed"] - twin["after"]["executed"],
            # The arm's own change against the twin's: (after - before) with the knockout minus the same with
            # the twin. Zero means the decision rate moved exactly as the twin's did.
            "change_passed": ((ko["after"]["passed"] - ko["before"]["passed"])
                              - (twin["after"]["passed"] - twin["before"]["passed"])),
            "change_executed": ((ko["after"]["executed"] - ko["before"]["executed"])
                                - (twin["after"]["executed"] - twin["before"]["executed"]))}


def month_table(ko, twin, start, band):
    """Month by month: each metric for both runs, the difference (knockout minus twin), and its difference
    in differences from the last month before the knockout."""
    base_index = start - 1
    ko_rows = {row.get("month"): row for row in ko.history}
    twin_rows = {row.get("month"): row for row in twin.history}
    base = {}
    for metric in METRICS:
        a, b = ko_rows.get(base_index), twin_rows.get(base_index)
        base[metric] = ((a or {}).get(metric, 0.0) or 0.0) - ((b or {}).get(metric, 0.0) or 0.0)
    out = []
    for index in sorted(m for m in set(ko_rows) | set(twin_rows) if isinstance(m, int)):
        a, b = ko_rows.get(index), twin_rows.get(index)
        if a is None or b is None:
            continue
        entry = {"month": index, "month_label": month_label(index),
                 "phase": "before" if index < start else "knockout month" if index == start else "after"}
        for metric in METRICS:
            left = a.get(metric)
            right = b.get(metric)
            if left is None or right is None:
                entry[metric] = {"knockout": left, "twin": right, "diff": None, "did": None}
                continue
            diff = float(left) - float(right)
            entry[metric] = {"knockout": left, "twin": right, "diff": round(diff, 6),
                             "did": round(diff - base[metric], 6)}
        out.append(entry)
    return out, base


def _decision_rule_changes(run, start):
    changes = []
    previous = None
    for row in run.history:
        constitution = row.get("constitution")
        if not isinstance(constitution, dict):
            continue
        rule = constitution.get("decision_rule")
        if previous is not None and rule != previous and row.get("month", -1) >= start:
            changes.append({"month": row["month"], "month_label": month_label(row["month"]),
                            "from": previous, "to": rule})
        previous = rule
    return changes


def _after_knockout(run, start):
    coups = successful = defiance = 0
    for index in sorted(run.records):
        if index < start:
            continue
        record = run.records[index]
        for coup in record.get("coups") or []:
            coups += 1
            if coup.get("success"):
                successful += 1
        defiance += len(record.get("defiance") or [])
    return {"coups": coups, "coups_successful": successful, "defiance": defiance,
            "decision_rule_changes": _decision_rule_changes(run, start),
            "months": [index for index in sorted(run.records) if index >= start]}


def recovery(run, twin, start, band):
    """Months until the approval difference is back within `band` of the twin, from the knockout month on,
    and whether it stayed within the band afterwards."""
    ko_rows = {row.get("month"): row for row in run.history}
    twin_rows = {row.get("month"): row for row in twin.history}
    months = sorted(m for m in set(ko_rows) & set(twin_rows) if isinstance(m, int) and m >= start)
    first = None
    for index in months:
        left, right = ko_rows[index].get("approval"), twin_rows[index].get("approval")
        if left is None or right is None:
            continue
        if abs(float(left) - float(right)) <= band:
            first = index
            break
    stable = False
    if first is not None:
        stable = all(abs(float(ko_rows[m].get("approval", 0.0)) - float(twin_rows[m].get("approval", 0.0))) <= band
                     for m in months if m >= first)
    return {"band": band, "months": None if first is None else first - start,
            "engine_month": first, "month_label": None if first is None else month_label(first),
            "stable_after": stable, "censored": first is None, "months_observed": len(months)}


def analyse_pair(knockout_run, twin_run, band=DEFAULT_BAND, window=DEFAULT_WINDOW):
    """Every measure above, on a pair of run folders. Raises ReportError on anything that would make the
    numbers mean something else (a missing run, a configured arm that never fired, a non-twin)."""
    if band < 0:
        raise ReportError(f"the recovery band must be zero or more, got {band}")
    if window < 1:
        raise ReportError(f"the motion window must be one month or more, got {window}")
    ko = Run(knockout_run)
    twin = Run(twin_run)
    found = detect_knockout(ko)
    if found is None:
        raise ReportError(f"{ko.path}: no knockout in the run's config, checkpoint state or history")
    start = found["engine_month"]
    differences = knockout.twin_differences(ko.history, twin.history, start)
    if differences:
        shown = "; ".join(differences[:5])
        more = f" (and {len(differences) - 5} more)" if len(differences) > 5 else ""
        raise ReportError(
            f"{ko.name} and {twin.name} are not a twin pair: their history rows before {month_label(start)} "
            f"differ: {shown}{more}. Only the same run up to the knockout can be compared.")
    before_months = [m for m in range(max(0, start - window), start)]
    after_months = [m for m in range(start + 1, start + 1 + window)]
    ko_motions = {"before": motion_counts(ko, before_months), "after": motion_counts(ko, after_months)}
    twin_motions = {"before": motion_counts(twin, before_months), "after": motion_counts(twin, after_months)}
    months, base = month_table(ko, twin, start, band)
    return {
        "runs": {"knockout": ko.name, "twin": twin.name},
        "knockout": found,
        "twin": {"identical": True, "differences": [], "checked_before": month_label(start)},
        "fill": months_until_filled(ko, found["office"], start),
        "motions": {"window": window, "knockout": ko_motions, "twin": twin_motions,
                    "difference": _difference(ko_motions, twin_motions)},
        "months": months,
        "base_difference": {metric: round(value, 6) for metric, value in base.items()},
        "after": {"knockout": _after_knockout(ko, start), "twin": _after_knockout(twin, start)},
        "recovery": recovery(ko, twin, start, band),
    }


# ---- writing --------------------------------------------------------------------------------------------------------

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


def write_markdown(pair, path, band, window):
    ko = pair["knockout"]
    fill = pair["fill"]
    lines = [f"# Knockout report: {pair['runs']['knockout']} against {pair['runs']['twin']}", ""]
    lines += [f"- Office: {ko['office']}; the holder was {ko['member'] or 'nobody (already vacant)'}.",
              f"- Knockout month: {ko['month_label']} (engine index {ko['engine_month']}), "
              f"read from the {ko['source']}.",
              f"- Twin identity: every history row before {pair['twin']['checked_before']} matches.",
              "", "## Months until the office is filled", ""]
    if fill["months"] is None:
        lines.append("The office was still vacant when the run ended (not filled).")
    else:
        lines.append(f"The office was filled in {fill['month_label']} ({fill['member']}), "
                     f"{fill['months']} month(s) after the knockout.")
    lines += ["", f"## Motions passed and executed, {window} months before against {window} after", ""]
    rows = []
    for label, key in (("knockout", "knockout"), ("twin", "twin")):
        item = pair["motions"][key]
        rows.append([label,
                     f"{item['before']['passed']} passed / {item['before']['executed']} executed",
                     f"{item['after']['passed']} passed / {item['after']['executed']} executed"])
    diff = pair["motions"]["difference"]
    rows.append(["knockout minus twin",
                 f"{diff['before_passed']:+d} / {diff['before_executed']:+d}",
                 f"{diff['after_passed']:+d} / {diff['after_executed']:+d}"])
    lines += _md_table(["run", "before", "after"], rows)
    lines += ["", "The knockout month itself is listed in the month table but counts in neither window.",
              "", "## Month by month against the twin (difference in differences)", ""]
    rows = []
    for entry in pair["months"]:
        cells = [entry["month_label"], entry["phase"]]
        for metric in METRICS:
            cell = entry[metric]
            cells += [_fmt(cell["knockout"]), _fmt(cell["twin"]), _fmt(cell["diff"]), _fmt(cell["did"])]
        rows.append(cells)
    lines += _md_table(["month", "phase"] + [part for metric in METRICS for part in
                                             (f"{metric} KO", f"{metric} twin", f"{metric} diff",
                                              f"{metric} DiD")], rows)
    lines += ["", "Difference is knockout minus twin; DiD is that difference against the last month before the "
                  "knockout.", "", "## Coups, defiance and decision-rule changes from the knockout month on", ""]
    rows = []
    for label, key in (("knockout", "knockout"), ("twin", "twin")):
        item = pair["after"][key]
        changes = "; ".join(f"{c['month_label']}: {c['from']} -> {c['to']}"
                            for c in item["decision_rule_changes"]) or "none"
        rows.append([label, item["coups"], item["coups_successful"], item["defiance"], changes])
    lines += _md_table(["run", "coups", "successful", "defiance rows", "decision-rule changes"], rows)
    lines += ["", "## Recovery time", ""]
    rec = pair["recovery"]
    if rec["months"] is None:
        lines.append(f"Approval did not come back within {band} of the twin by the end of the run "
                     f"({rec['months_observed']} month(s) observed; censored).")
    else:
        lines.append(f"Approval came back within {band} of the twin in {rec['month_label']}, "
                     f"{rec['months']} month(s) after the knockout; "
                     + ("it stayed within the band afterwards." if rec["stable_after"]
                        else "it left the band again afterwards."))
    lines += ["", "## Notes", "",
              f"The preregistered recovery band is {band} absolute approval. `month` is the engine's 0-based "
              "index in the JSON and CSV; this report labels it Month N (index + 1).",
              "Motion counts: a motion counts as passed when it passed and was neither withdrawn nor void; "
              "executed when it also reached EXECUTED.", ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_csv(pair, path):
    fields = ["month", "month_label", "phase"]
    for metric in METRICS:
        fields += [f"{metric}_knockout", f"{metric}_twin", f"{metric}_diff", f"{metric}_did"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for entry in pair["months"]:
            row = {"month": entry["month"], "month_label": entry["month_label"], "phase": entry["phase"]}
            for metric in METRICS:
                cell = entry[metric]
                row[f"{metric}_knockout"] = cell["knockout"]
                row[f"{metric}_twin"] = cell["twin"]
                row[f"{metric}_diff"] = cell["diff"]
                row[f"{metric}_did"] = cell["did"]
            writer.writerow(row)


def write_report(pair, out, band, window):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "knockout_report.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(pair, f, indent=2, ensure_ascii=False)
        f.write("\n")
    write_csv(pair, out / "knockout_months.csv")
    write_markdown(pair, out / "knockout_report.md", band, window)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="The knockout arm's measures on a run and its twin.")
    parser.add_argument("knockout_run", help="the run folder with the knockout")
    parser.add_argument("twin_run", help="its same-seed twin without the knockout")
    parser.add_argument("--out", required=True, help="folder for the report, JSON and CSV")
    parser.add_argument("--band", type=float, default=DEFAULT_BAND,
                        help=f"the preregistered recovery band in absolute approval (default {DEFAULT_BAND})")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                        help=f"months before and after the knockout for the motion counts (default {DEFAULT_WINDOW})")
    args = parser.parse_args(argv)
    try:
        pair = analyse_pair(args.knockout_run, args.twin_run, band=args.band, window=args.window)
    except ReportError as exc:
        print(f"knockout_report: {exc}", file=sys.stderr)
        return 2
    out = write_report(pair, args.out, args.band, args.window)
    fill = pair["fill"]
    rec = pair["recovery"]
    print(f"knockout {pair['knockout']['month_label']} ({pair['knockout']['office']}): "
          f"filled {'never' if fill['months'] is None else str(fill['months']) + ' month(s)'}; "
          f"recovery {'censored' if rec['months'] is None else str(rec['months']) + ' month(s)'}; "
          f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
