"""The harness arm's measures, by arm, over recorded run folders (Wave A W6, plan 4.7).

    python tools/harness_report.py RUN_DIR [RUN_DIR ...] [--out DIR]

Read-only: it never writes into a run folder, and it calls no model. The report is plain text; with --out it is
also written as harness_report.txt beside harness_report.json. The arms come from each run's config.json:
`harness` ("menu", "language", "open", the engine-29 default when absent) and `referee_effects` ("applied" or
"zeroed"). A run with `referee_effects = "zeroed"` is reported under `<harness>+zeroed`.

The measures are the plan's M1 to M7:
  M1  refusals: how many, by code, and the share that are unknown acts (UNKNOWN_*) or text/action mismatches
      (MOTION_ACTION_MISMATCH*), read from the month records.
  M2  the variety of acts: the distinct motion types, the distinct open-act categories, and each run's entropy over
      them (0 = one kind only; log2(distinct) when evenly spread).
  M3  outcomes: runs that survived, mean final approval, food ratio and unrest from the checkpoint's last history row.
  M4  the referee's plausibility inputs: referee calls, valid rulings, failed rulings (REFEREE_INVALID in the
      checkpoint's audit errors), the invalid rate, categories, success levels, rulings per month and effects by
      channel. The plausibility audit itself is tools/referee_audit.py.
  M5  the open arm against the open arm with effects zeroed, matched by seed, months and seat labels.
  M6  cost: calls and input/output tokens from log.jsonl, by phase.
  M7  awareness: the existing measures of tools/awareness_scan.py, where the run has them (it leaves out the
      referee, which is machinery).

What a month record must carry, and which entry shapes are read:
  - `rejected_motions`: [{reason_code, member, ...}] (engine 29's shape);
  - `motions`: [{type, ...}];
  - `open_acts` and `cabinet_open_acts`: each entry an act with a `ruling` table ({feasible, category, success,
    effects}) or a top-level ruling, plus an optional `referee_invalid` flag. A ruling in the entry is preferred;
    when a run records the acts only in the referee's call log (raw JSON), that is read instead, so a run recorded
    before W5's records existed still yields M4.

Standard library only. `month` is the engine's 0-based index; the text labels it Month N (index + 1).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))                       # the package imports from the repository root
sys.path.insert(0, str(Path(__file__).resolve().parent))
import awareness_scan  # noqa: E402

UNKNOWN_PREFIX = "UNKNOWN_"
MISMATCH_PREFIX = "MOTION_ACTION_MISMATCH"
REFEREE_INVALID = "REFEREE_INVALID"
OPEN_RECORD_KEYS = ("open_acts", "cabinet_open_acts")


class ReportError(Exception):
    """A problem with the input runs. The command stops and says what; nothing is silently skipped."""


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReportError(f"{path}: cannot read JSON ({exc})") from exc


def _read_jsonl(path: Path) -> list:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for number, line in enumerate(f, 1):
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except ValueError as exc:
                        raise ReportError(f"{path}:{number}: not JSON ({exc})") from exc
    except OSError as exc:
        raise ReportError(f"{path}: cannot read ({exc})") from exc
    return out


def month_label(index) -> str:
    return f"Month {int(index) + 1}"


def entropy(counter: Counter) -> float:
    """Shannon entropy in bits over a count table; 0 for one kind or none."""
    total = sum(counter.values())
    if total <= 1:
        return 0.0
    return round(-sum((n / total) * math.log2(n / total) for n in counter.values() if n), 6)


def _number(value, default=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


class Run:
    """One run folder: its arm, month records, calls, history and outcome."""

    def __init__(self, path):
        self.path = Path(path)
        self.name = self.path.name
        if not self.path.is_dir():
            raise ReportError(f"{self.path}: not a folder")
        for needed in ("config.json", "checkpoint.json", "log.jsonl"):
            if not (self.path / needed).is_file():
                raise ReportError(f"{self.path}: no {needed}")
        config = _read_json(self.path / "config.json")
        self.run = config.get("run") if isinstance(config.get("run"), dict) else {}
        self.harness = str(self.run.get("harness") or "menu")
        self.referee_effects = str(self.run.get("referee_effects") or "applied")
        self.arm = self.harness + ("" if self.referee_effects == "applied" else "+zeroed")
        self.seed = self.run.get("seed")
        self.months = int(self.run.get("months") or 0)
        seats = config.get("seats") if isinstance(config.get("seats"), list) else []
        self.seat_labels = tuple(sorted(str(s.get("label") or "") for s in seats if isinstance(s, dict)))
        checkpoint = _read_json(self.path / "checkpoint.json")
        world = checkpoint.get("world") if isinstance(checkpoint.get("world"), dict) else {}
        self.history = sorted((row for row in world.get("history") or [] if isinstance(row, dict)),
                              key=lambda row: row.get("month", -1))
        self.outcome = dict(world.get("outcome") or {})
        self.audit_errors = [e for e in world.get("audit_errors") or [] if isinstance(e, dict)]
        records = _read_jsonl(self.path / "log.jsonl")
        self.records = {r["month"]: r for r in records
                        if r.get("type") == "month" and isinstance(r.get("month"), int)}
        self.calls = [r for r in records if r.get("type") == "call"]

    # ---- M1 -----------------------------------------------------------------------------------------
    def refusals(self) -> dict:
        codes = Counter()
        for index in sorted(self.records):
            for entry in self.records[index].get("rejected_motions") or []:
                if isinstance(entry, dict):
                    codes[str(entry.get("reason_code") or "UNSPECIFIED")] += 1
        total = sum(codes.values())
        opening = sum(n for code, n in codes.items()
                      if code.startswith(UNKNOWN_PREFIX) or code.startswith(MISMATCH_PREFIX))
        return {"refusals": total, "unknown_or_mismatch": opening,
                "share_unknown_or_mismatch": round(opening / total, 6) if total else None,
                "by_code": dict(sorted(codes.items()))}

    # ---- M2 -----------------------------------------------------------------------------------------
    def act_variety(self) -> dict:
        motion_types, categories = Counter(), Counter()
        for index in sorted(self.records):
            for motion in self.records[index].get("motions") or []:
                if isinstance(motion, dict) and motion.get("type"):
                    motion_types[str(motion["type"])] += 1
            for entry in self.open_act_entries():
                category = self.ruling_of(entry).get("category")
                if category:
                    categories[str(category)] += 1
        return {"motion_types": sorted(motion_types), "motion_type_counts": dict(sorted(motion_types.items())),
                "motion_type_entropy": entropy(motion_types),
                "open_act_categories": sorted(categories),
                "open_act_category_counts": dict(sorted(categories.items())),
                "open_act_category_entropy": entropy(categories)}

    # ---- open-act entries and M4 --------------------------------------------------------------------
    def open_act_entries(self) -> list:
        """Every open-act record the month records hold, in month and list order."""
        out = []
        for index in sorted(self.records):
            for key in OPEN_RECORD_KEYS:
                for entry in self.records[index].get(key) or []:
                    if isinstance(entry, dict):
                        out.append({**entry, "_cabinet": key == "cabinet_open_acts", "_month": index})
        return out

    @staticmethod
    def ruling_of(entry: dict) -> dict:
        """The ruling table of an entry, whichever way a run recorded it."""
        ruling = entry.get("ruling")
        return ruling if isinstance(ruling, dict) else entry

    def referee_metrics(self) -> dict:
        referee_calls = [c for c in self.calls if c.get("phase") == "referee"]
        calls_by_month = Counter(int(c.get("month", -1)) for c in referee_calls if isinstance(c.get("month"), int))
        categories, successes, effects = Counter(), Counter(), {}
        rulings = 0
        entries = self.open_act_entries()
        for entry in entries:
            ruling = self.ruling_of(entry)
            if not isinstance(ruling, dict) or "feasible" not in ruling:
                continue
            rulings += 1
            if ruling.get("category"):
                categories[str(ruling["category"])] += 1
            if ruling.get("success"):
                successes[str(ruling["success"])] += 1
            for effect in ruling.get("effects") or []:
                if not isinstance(effect, dict) or not effect.get("channel"):
                    continue
                channel = effects.setdefault(str(effect["channel"]),
                                             {"effects": 0, "value_sum": 0.0, "month_value_sum": 0.0})
                value = _number(effect.get("value"))
                months = _number(effect.get("months"), 1.0)
                channel["effects"] += 1
                channel["value_sum"] = round(channel["value_sum"] + value, 6)
                channel["month_value_sum"] = round(channel["month_value_sum"] + value * months, 6)
        source = "month records"
        if not rulings:
            # A run recorded before the month records carried the acts: read the referee's own logged answers.
            source = "referee call log"
            for call in referee_calls:
                try:
                    data = json.loads(call.get("raw") or "")
                except ValueError:
                    continue
                if not isinstance(data, dict) or "feasible" not in data:
                    continue
                rulings += 1
                if data.get("category"):
                    categories[str(data["category"])] += 1
                if data.get("success"):
                    successes[str(data["success"])] += 1
                for effect in data.get("effects") or []:
                    if isinstance(effect, dict) and effect.get("channel"):
                        channel = effects.setdefault(str(effect["channel"]),
                                                     {"effects": 0, "value_sum": 0.0, "month_value_sum": 0.0})
                        value = _number(effect.get("value"))
                        months = _number(effect.get("months"), 1.0)
                        channel["effects"] += 1
                        channel["value_sum"] = round(channel["value_sum"] + value, 6)
                        channel["month_value_sum"] = round(channel["month_value_sum"] + value * months, 6)
        invalid = [e for e in self.audit_errors if e.get("code") == REFEREE_INVALID]
        invalid_by_month = Counter(int(e["month"]) + 1 for e in invalid if isinstance(e.get("month"), int))
        months_recorded = len(self.records)
        return {"referee_calls": len(referee_calls), "referee_calls_by_month": dict(sorted(calls_by_month.items())),
                "rulings": rulings, "rulings_source": source,
                "rulings_per_month": round(rulings / months_recorded, 6) if months_recorded else None,
                "invalid_rulings": len(invalid), "invalid_by_month": dict(sorted(invalid_by_month.items())),
                "invalid_rate": round(len(invalid) / (rulings + len(invalid)), 6)
                if (rulings + len(invalid)) else None,
                "categories": dict(sorted(categories.items())),
                "success_levels": dict(sorted(successes.items())),
                "effects_by_channel": dict(sorted(effects.items()))}

    # ---- M3 -----------------------------------------------------------------------------------------
    def outcome_metrics(self) -> dict:
        last = self.history[-1] if self.history else {}
        return {"outcome": self.outcome.get("type") or "",
                "survived": (self.outcome.get("type") or "") == "survived",
                "final_approval": last.get("approval"), "final_food_ratio": last.get("food_ratio"),
                "final_unrest": last.get("unrest"), "months_recorded": len(self.history)}

    # ---- M6 -----------------------------------------------------------------------------------------
    def cost_metrics(self) -> dict:
        by_phase = Counter(str(c.get("phase") or "?") for c in self.calls)
        return {"calls": len(self.calls), "calls_by_phase": dict(sorted(by_phase.items())),
                "input_tokens": sum(int(_number(c.get("input_tokens"))) for c in self.calls),
                "output_tokens": sum(int(_number(c.get("output_tokens"))) for c in self.calls),
                "cost_usd": round(sum(_number(c.get("cost_usd")) for c in self.calls), 6)}

    # ---- M7 -----------------------------------------------------------------------------------------
    def awareness_metrics(self) -> dict:
        result = awareness_scan.scan_run(str(self.path))
        out = {"reasoning_calls": 0, "reasoning_aware": 0, "answer_calls": 0, "answer_aware": 0,
               "debrief": {}}
        for (framing, kind), row in result["mentions"].items():
            if kind == "reasoning":
                out["reasoning_calls"] += row["calls"]
                out["reasoning_aware"] += row["AWARE"]
            elif kind == "answer":
                out["answer_calls"] += row["calls"]
                out["answer_aware"] += row["AWARE"]
        out["debrief"] = {framing: dict(counts) for framing, counts in result["debrief"].items()}
        return out


# ---- aggregation -----------------------------------------------------------------------------------

def _mean(values):
    values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return round(sum(values) / len(values), 6) if values else None


def _sum_by_channel(rows: list) -> dict:
    out = {}
    for row in rows:
        for channel, item in row.items():
            target = out.setdefault(channel, {"effects": 0, "value_sum": 0.0, "month_value_sum": 0.0})
            target["effects"] += item["effects"]
            target["value_sum"] = round(target["value_sum"] + item["value_sum"], 6)
            target["month_value_sum"] = round(target["month_value_sum"] + item["month_value_sum"], 6)
    return dict(sorted(out.items()))


def _aggregate(runs: list) -> dict:
    refusals = [r.refusals() for r in runs]
    variety = [r.act_variety() for r in runs]
    outcomes = [r.outcome_metrics() for r in runs]
    referees = [r.referee_metrics() for r in runs]
    costs = [r.cost_metrics() for r in runs]
    awareness = [r.awareness_metrics() for r in runs]
    total_refusals = sum(item["refusals"] for item in refusals)
    opening = sum(item["unknown_or_mismatch"] for item in refusals)
    codes = Counter()
    for item in refusals:
        codes.update(item["by_code"])
    categories, successes = Counter(), Counter()
    referee_months, call_phases = Counter(), Counter()
    for item in referees:
        categories.update(item["categories"])
        successes.update(item["success_levels"])
        referee_months.update(item["referee_calls_by_month"])
    for item in costs:
        call_phases.update(item["calls_by_phase"])
    rulings = sum(item["rulings"] for item in referees)
    invalid = sum(item["invalid_rulings"] for item in referees)
    debrief = {}
    for item in awareness:
        for framing, counts in item["debrief"].items():
            debrief.setdefault(framing, Counter()).update(counts)
    reasoning_calls = sum(item["reasoning_calls"] for item in awareness)
    reasoning_aware = sum(item["reasoning_aware"] for item in awareness)
    return {
        "runs": len(runs),
        "m1": {"refusals": total_refusals, "unknown_or_mismatch": opening,
               "share_unknown_or_mismatch": round(opening / total_refusals, 6) if total_refusals else None,
               "by_code": dict(sorted(codes.items())),
               "per_run": {r.name: item for r, item in zip(runs, refusals)}},
        "m2": {"motion_types": sorted({t for item in variety for t in item["motion_types"]}),
               "open_act_categories": sorted({c for item in variety for c in item["open_act_categories"]}),
               "mean_motion_types_per_run": _mean([len(item["motion_types"]) for item in variety]),
               "mean_open_act_categories_per_run": _mean([len(item["open_act_categories"]) for item in variety]),
               "mean_motion_type_entropy": _mean([item["motion_type_entropy"] for item in variety]),
               "mean_open_act_category_entropy": _mean([item["open_act_category_entropy"] for item in variety])},
        "m3": {"runs": len(runs),
               "runs_survived": sum(1 for item in outcomes if item["survived"]),
               "survival_share": round(sum(1 for item in outcomes if item["survived"]) / len(runs), 6)
               if runs else None,
               "outcomes": dict(sorted(Counter(item["outcome"] or "none" for item in outcomes).items())),
               "mean_final_approval": _mean([item["final_approval"] for item in outcomes]),
               "mean_final_food_ratio": _mean([item["final_food_ratio"] for item in outcomes]),
               "mean_final_unrest": _mean([item["final_unrest"] for item in outcomes])},
        "m4": {"referee_calls": sum(item["referee_calls"] for item in referees),
               "referee_calls_by_month": dict(sorted(referee_months.items())),
               "rulings": rulings, "invalid_rulings": invalid,
               "invalid_rate": round(invalid / (rulings + invalid), 6) if (rulings + invalid) else None,
               "categories": dict(sorted(categories.items())),
               "success_levels": dict(sorted(successes.items())),
               "effects_by_channel": _sum_by_channel([item["effects_by_channel"] for item in referees]),
               "per_run": {r.name: item for r, item in zip(runs, referees)}},
        "m6": {"calls": sum(item["calls"] for item in costs),
               "calls_by_phase": dict(sorted(call_phases.items())),
               "input_tokens": sum(item["input_tokens"] for item in costs),
               "output_tokens": sum(item["output_tokens"] for item in costs),
               "cost_usd": round(sum(item["cost_usd"] for item in costs), 6),
               "per_run": {r.name: item for r, item in zip(runs, costs)}},
        "m7": {"reasoning_calls": reasoning_calls,
               "reasoning_aware": reasoning_aware,
               "answer_calls": sum(item["answer_calls"] for item in awareness),
               "answer_aware": sum(item["answer_aware"] for item in awareness),
               "awareness_share": round(reasoning_aware / reasoning_calls, 6) if reasoning_calls else None,
               "debrief": {framing: dict(sorted(counts.items())) for framing, counts in sorted(debrief.items())}},
    }


def _pair_key(run: Run) -> tuple:
    """What makes two runs a matched open/zeroed pair: seed, months and the seat lineup."""
    return (run.seed, run.months, run.seat_labels)


def zeroed_comparison(runs: list) -> dict:
    """M5: each open+applied run against an open+zeroed run of the same cell."""
    applied = [r for r in runs if r.harness == "open" and r.referee_effects == "applied"]
    zeroed = [r for r in runs if r.harness == "open" and r.referee_effects == "zeroed"]
    if not applied or not zeroed:
        missing = "no open+applied run" if not applied else "no open+zeroed run"
        return {"available": False, "reason": f"{missing}: the ablation needs both arms", "pairs": [],
                "summary": {}}
    unused = list(applied)
    pairs = []
    for run in sorted(zeroed, key=lambda r: r.name):
        match = next((c for c in unused if _pair_key(c) == _pair_key(run)), None)
        if match is None:
            continue
        unused.remove(match)
        left, right = match.outcome_metrics(), run.outcome_metrics()
        m1_left, m1_right = match.refusals(), run.refusals()
        cost_left, cost_right = match.cost_metrics(), run.cost_metrics()
        pairs.append({
            "applied": match.name, "zeroed": run.name, "seed": run.seed, "seat_labels": list(run.seat_labels),
            "outcome": {"applied": left["outcome"], "zeroed": right["outcome"]},
            "approval_diff": _diff(left["final_approval"], right["final_approval"]),
            "food_ratio_diff": _diff(left["final_food_ratio"], right["final_food_ratio"]),
            "unrest_diff": _diff(left["final_unrest"], right["final_unrest"]),
            "refusal_share_diff": _diff(m1_left["share_unknown_or_mismatch"], m1_right["share_unknown_or_mismatch"]),
            "open_acts_applied": match.referee_metrics()["rulings"],
            "open_acts_zeroed": run.referee_metrics()["rulings"],
            "calls_diff": cost_left["calls"] - cost_right["calls"],
            "cost_usd_diff": round(cost_left["cost_usd"] - cost_right["cost_usd"], 6),
        })
    if not pairs:
        return {"available": False,
                "reason": "open+applied and open+zeroed runs exist but no two share a seed, months and seat lineup",
                "pairs": [], "summary": {}}
    return {"available": True,
            "pairs": pairs,
            "summary": {"pairs": len(pairs),
                        "mean_approval_diff": _mean([p["approval_diff"] for p in pairs]),
                        "mean_food_ratio_diff": _mean([p["food_ratio_diff"] for p in pairs]),
                        "mean_unrest_diff": _mean([p["unrest_diff"] for p in pairs]),
                        "mean_refusal_share_diff": _mean([p["refusal_share_diff"] for p in pairs]),
                        "mean_calls_diff": _mean([p["calls_diff"] for p in pairs]),
                        "mean_cost_usd_diff": _mean([p["cost_usd_diff"] for p in pairs])}}


def _diff(left, right):
    if left is None or right is None:
        return None
    return round(_number(left) - _number(right), 6)


def build(run_dirs) -> dict:
    """Every measure, per run and per arm. Reads only; raises ReportError on an input it cannot read."""
    runs = [Run(path) for path in run_dirs]
    if not runs:
        raise ReportError("no run folders were given")
    names = Counter(r.name for r in runs)
    duplicates = sorted(name for name, n in names.items() if n > 1)
    if duplicates:
        raise ReportError(f"two run folders have the same name, so the report could not tell them apart: {duplicates}")
    arms = {}
    for arm in sorted({r.arm for r in runs}):
        members = [r for r in runs if r.arm == arm]
        arms[arm] = {"runs_list": [r.name for r in members], **_aggregate(members)}
    return {"runs": [{"name": r.name, "path": str(r.path), "arm": r.arm, "harness": r.harness,
                      "referee_effects": r.referee_effects, "seed": r.seed, "months": r.months} for r in runs],
            "arms": arms, "m5": zeroed_comparison(runs)}


# ---- text ------------------------------------------------------------------------------------------

def _fmt(value, digits=4):
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _share(part, whole):
    return f"{part} ({part / whole:.0%})" if whole else "0 (NA)"


def render(result: dict) -> str:
    lines = ["Harness report", ""]
    for arm, data in result["arms"].items():
        lines += [f"=== arm {arm} ({data['runs']} run(s)) ===", ""]
        m1 = data["m1"]
        lines.append(f"M1 refusals: {m1['refusals']} in all; unknown acts or text/action mismatches "
                     f"{_share(m1['unknown_or_mismatch'], m1['refusals'])}"
                     + (f" (share {_fmt(m1['share_unknown_or_mismatch'])})." if m1["refusals"] else "."))
        if m1["by_code"]:
            lines.append("   " + ", ".join(f"{code} {n}" for code, n in m1["by_code"].items()))
        m2 = data["m2"]
        lines.append(f"M2 variety: motion types {len(m2['motion_types'])} "
                     f"({', '.join(m2['motion_types']) or '-'}); open-act categories "
                     f"{len(m2['open_act_categories'])} ({', '.join(m2['open_act_categories']) or '-'}).")
        lines.append(f"   Mean per run: {_fmt(m2['mean_motion_types_per_run'])} motion types, "
                     f"{_fmt(m2['mean_open_act_categories_per_run'])} categories; entropy "
                     f"{_fmt(m2['mean_motion_type_entropy'])} / {_fmt(m2['mean_open_act_category_entropy'])} bits.")
        m3 = data["m3"]
        lines.append(f"M3 outcomes: survived {m3['runs_survived']}/{m3['runs']} "
                     f"({_fmt(m3['survival_share'])}); final approval {_fmt(m3['mean_final_approval'])}, "
                     f"food ratio {_fmt(m3['mean_final_food_ratio'])}, unrest {_fmt(m3['mean_final_unrest'])}.")
        if m3["outcomes"]:
            lines.append("   " + ", ".join(f"{kind} {n}" for kind, n in m3["outcomes"].items()))
        m4 = data["m4"]
        lines.append(f"M4 referee: {m4['referee_calls']} call(s); {m4['rulings']} valid ruling(s); "
                     f"{m4['invalid_rulings']} failed; invalid rate {_fmt(m4['invalid_rate'])}.")
        if m4["categories"]:
            lines.append("   Categories: " + ", ".join(f"{k} {n}" for k, n in m4["categories"].items()))
        if m4["success_levels"]:
            lines.append("   Success: " + ", ".join(f"{k} {n}" for k, n in m4["success_levels"].items()))
        if m4["effects_by_channel"]:
            lines.append("   Effects by channel: " + ", ".join(
                f"{channel} {item['effects']} ({item['value_sum']:+g}, {item['month_value_sum']:+g} channel-months)"
                for channel, item in m4["effects_by_channel"].items()))
        m6 = data["m6"]
        lines.append(f"M6 cost: {m6['calls']} call(s), {m6['input_tokens']} input and {m6['output_tokens']} output "
                     f"tokens, ${m6['cost_usd']:.4f}.")
        if m6["calls_by_phase"]:
            lines.append("   " + ", ".join(f"{phase} {n}" for phase, n in m6["calls_by_phase"].items()))
        m7 = data["m7"]
        lines.append(f"M7 awareness: reasoning calls {m7['reasoning_calls']}, aware "
                     f"{_share(m7['reasoning_aware'], m7['reasoning_calls'])}; answer calls "
                     f"{m7['answer_calls']}, aware {_share(m7['answer_aware'], m7['answer_calls'])}.")
        lines.append("")
    m5 = result["m5"]
    if m5["available"]:
        summary = m5["summary"]
        lines += ["=== M5 open against open with effects zeroed ===",
                  f"{summary['pairs']} matched pair(s). Mean difference (applied minus zeroed): approval "
                  f"{_fmt(summary['mean_approval_diff'])}, food ratio {_fmt(summary['mean_food_ratio_diff'])}, "
                  f"unrest {_fmt(summary['mean_unrest_diff'])}, refusal share "
                  f"{_fmt(summary['mean_refusal_share_diff'])}, calls {_fmt(summary['mean_calls_diff'])}.",
                  ""]
        for pair in m5["pairs"]:
            lines.append(f"  {pair['applied']} against {pair['zeroed']} (seed {pair['seed']}): outcome "
                         f"{pair['outcome']['applied'] or '-'} / {pair['outcome']['zeroed'] or '-'}; approval diff "
                         f"{_fmt(pair['approval_diff'])}; open acts {pair['open_acts_applied']} / "
                         f"{pair['open_acts_zeroed']}.")
        lines.append("")
    else:
        lines += [f"=== M5 open against open with effects zeroed === unavailable: {m5['reason']}", ""]
    return "\n".join(lines)


def write(result: dict, out_dir) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "harness_report.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")
    (out / "harness_report.txt").write_text(render(result), encoding="utf-8", newline="\n")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="The harness arm's measures over recorded run folders.")
    parser.add_argument("run_dirs", nargs="+", help="run folders (each: config.json, checkpoint.json, log.jsonl)")
    parser.add_argument("--out", help="folder for harness_report.txt and harness_report.json (default: print only)")
    args = parser.parse_args(argv)
    try:
        result = build(args.run_dirs)
    except ReportError as exc:
        print(f"harness_report: {exc}", file=sys.stderr)
        return 2
    print(render(result))
    if args.out:
        write(result, args.out)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
