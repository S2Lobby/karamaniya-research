"""The referee audit: a seeded sample of rulings for two annotators, and their agreement (Wave A W6, plan 4.7).

    python tools/referee_audit.py sample RUN_DIR [RUN_DIR ...] --seed S --size N --out worksheet.csv
    python tools/referee_audit.py agreement SHEET_A [SHEET_B] [--col-a annotator_1] [--col-b annotator_2]
                                       [--out DIR]

No model is called. `sample` reads every referee call in the runs' log.jsonl (phase "referee", member "referee")
whose answer is a ruling, pairs each with the prompt record that holds the act and the true-state block, and draws
a seeded, stratified sample: `N` rulings spread equally over the ruling categories (unused quota passes to the
other strata, as tools/exit_audit.py allocates). The ranking is sha256("seed|ruling_id"), so the same seed and
pool draw the same worksheet. It writes the worksheet CSV and a `.meta.json` sidecar; it never writes in a run
folder.

The worksheet's `act` and `true_state` columns are excerpts of the prompt the referee was sent, and `ruling` is
the referee's own answer. Two annotators each score the plausibility of the ruling from 1 (implausible: it could
not be carried out, or its effects are badly wrong) to 5 (fully plausible), using docs/REFEREE_CODEBOOK.md.
`agreement` reads their scores back and computes observed agreement, Cohen's kappa (unweighted) and
Krippendorff's alpha with the interval metric. With one sheet, the scores are the `annotator_1` and `annotator_2`
columns of that file; with two, each file's `--col-a` / `--col-b` column.

The codebook defines the labels, the sample size and the agreement thresholds. The statistics are the ones
tools/exit_audit.py uses, extended to the interval metric the scores need: two coders, coincidence matrix built by
adding each pair in both orders, Do = sum o_ck (c-k)^2 / N and De = sum n_c n_k (c-k)^2 / (N(N-1)).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path

COLUMNS = ["ruling_id", "run", "month", "month_label", "category", "success", "feasible", "act", "ruling",
           "public_report", "true_state", "annotator_1", "annotator_2", "adjudicated", "notes"]
SCORES = (1, 2, 3, 4, 5)


class AuditError(Exception):
    """A problem with the inputs. The command stops and reports it; nothing is silently skipped."""


def read_jsonl(path) -> list:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for number, line in enumerate(f, 1):
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except ValueError as exc:
                        raise AuditError(f"{path}:{number}: not JSON ({exc})") from exc
    except OSError as exc:
        raise AuditError(f"{path}: cannot read ({exc})") from exc
    return out


def _section(text: str, heading: str, stop: str) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    start += len(heading)
    end = text.find(stop, start)
    return (text[start:end] if end >= 0 else text[start:]).strip()


def act_and_state(prompt: str) -> tuple:
    """(the act block, a true-state excerpt) from the referee's user prompt."""
    act = _section(prompt, "=== THE ACT ===", "\n\n=== TRUE STATE")
    state = _section(prompt, "=== TRUE STATE", "\n\n")
    if not state:
        state = _section(prompt, "=== TRUE STATE", "\n\n=== ")
    lines = [line for line in state.splitlines() if line.strip()][:3]
    excerpt = "\n".join(lines)
    return act[:1200], excerpt[:600]


def collect(run_dirs) -> list:
    """Every ruling the runs' referee calls returned, with its act and true-state excerpt."""
    rows = []
    for run_dir in run_dirs:
        path = Path(run_dir)
        log = path / "log.jsonl"
        if not log.is_file():
            raise AuditError(f"{path}: no log.jsonl")
        prompts_path = path / "prompts.jsonl"
        prompt_list, prompt_by_id = {}, {}
        if prompts_path.is_file():
            for prompt in read_jsonl(prompts_path):
                key = (prompt.get("month"), prompt.get("phase"), prompt.get("member") or prompt.get("actor"))
                prompt_list.setdefault(key, []).append(prompt)
                if prompt.get("call_id"):
                    prompt_by_id[key + (prompt["call_id"],)] = prompt
        seen = Counter()
        for call in read_jsonl(log):
            if call.get("type") != "call" or call.get("phase") != "referee" or call.get("member") != "referee":
                continue
            try:
                data = json.loads(call.get("raw") or "")
            except ValueError:
                continue
            if not isinstance(data, dict) or "feasible" not in data:
                continue
            key = (call.get("month"), call.get("phase"), call.get("member"))
            index = seen[key]
            seen[key] += 1
            prompt = prompt_by_id.get(key + (call.get("call_id"),)) if call.get("call_id") else None
            if prompt is None:
                held = prompt_list.get(key) or []
                prompt = held[index] if index < len(held) else None
            act, state = act_and_state(str((prompt or {}).get("prompt") or ""))
            month = call.get("month") if isinstance(call.get("month"), int) else -1
            rows.append({
                "ruling_id": f"{path.name}|m{month}|{call.get('call_id') or index}",
                "run": path.name, "month": month,
                "month_label": f"Month {month + 1}" if month >= 0 else "",
                "category": str(data.get("category") or "other"),
                "success": str(data.get("success") or ""),
                "feasible": bool(data.get("feasible")),
                "act": act,
                "ruling": json.dumps(data, ensure_ascii=False, sort_keys=True),
                "public_report": str(data.get("public_report") or ""),
                "true_state": state,
            })
    return rows


def _rank(seed, ruling_id: str) -> str:
    return hashlib.sha256(f"{seed}|{ruling_id}".encode("utf-8")).hexdigest()


def _allocate(budget: int, sizes: dict) -> dict:
    """Equal allocation over the strata, with a small stratum's unused share passed on (as exit_audit does)."""
    quota = {key: 0 for key in sizes}
    remaining = min(budget, sum(sizes.values()))
    active = sorted(key for key in sizes if sizes[key] > 0)
    while remaining > 0 and active:
        share, extra = divmod(remaining, len(active))
        progressed = False
        for i, key in enumerate(active):
            take = min(share + (1 if i < extra else 0), sizes[key] - quota[key])
            if take > 0:
                quota[key] += take
                remaining -= take
                progressed = True
        active = [key for key in active if quota[key] < sizes[key]]
        if not progressed:
            break
    return quota


def sample(run_dirs, seed: int, size: int) -> tuple:
    """(rows, meta): a seeded, category-stratified sample of rulings, in rank order."""
    if size < 1:
        raise AuditError(f"the sample size must be one or more, got {size}")
    pool = collect(run_dirs)
    if not pool:
        raise AuditError("no referee rulings were found in these runs")
    strata = {}
    for row in pool:
        strata.setdefault(row["category"], []).append(row)
    for key in strata:
        strata[key].sort(key=lambda row: _rank(seed, row["ruling_id"]))
    quota = _allocate(size, {key: len(rows) for key, rows in strata.items()})
    chosen = [("category", row) for key in sorted(strata) for row in strata[key][:quota.get(key, 0)]]
    chosen.sort(key=lambda pair: _rank(seed, pair[1]["ruling_id"]))
    meta = {"seed": seed, "size_requested": size, "size_drawn": len(chosen), "pool_size": len(pool),
            "runs": [str(Path(path).name) for path in run_dirs],
            "strata": {key: {"pool": len(rows), "drawn": quota.get(key, 0)} for key, rows in sorted(strata.items())},
            "label_columns": ["annotator_1", "annotator_2", "adjudicated", "notes"],
            "scores": list(SCORES)}
    return [row for _stratum, row in chosen], meta


def _csv_row(row: dict) -> dict:
    return {**{column: row.get(column, "") for column in COLUMNS if column not in
               ("annotator_1", "annotator_2", "adjudicated", "notes")},
            "annotator_1": "", "annotator_2": "", "adjudicated": "", "notes": ""}


def write_worksheet(run_dirs, out_path, seed: int, size: int) -> list:
    """Write the two-annotator worksheet CSV and its meta sidecar. Returns the drawn rows."""
    rows, meta = sample(run_dirs, seed, size)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(_csv_row(row))
    meta["worksheet"] = str(out)
    with open(str(out) + ".meta.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    return rows


# ---- agreement -------------------------------------------------------------------------------------

def read_scores(pairs):
    """The (a, b) score pairs, as whole numbers 1 to 5. A pair with an empty side is left unlabelled and skipped."""
    clean, bad = [], []
    for left, right in pairs:
        a, b = str(left).strip(), str(right).strip()
        if not a or not b:
            continue
        values = []
        for text in (a, b):
            try:
                value = int(text)
            except ValueError:
                value = None
            if value not in SCORES:
                bad.append(text)
            values.append(value)
        if all(value in SCORES for value in values):
            clean.append((values[0], values[1]))
    if bad:
        raise ValueError("plausibility scores must be whole numbers from 1 to 5; got " + ", ".join(sorted(set(bad))[:10]))
    return clean


def agreement(pairs) -> dict:
    """Observed agreement, Cohen's kappa (unweighted) and Krippendorff's alpha (interval), two coders."""
    pairable = read_scores(pairs)
    n = len(pairable)
    if not n:
        return {"n_pairable": 0, "p_o": None, "p_e": None, "kappa": None, "alpha": None,
                "categories": [], "table": {}, "disagreements": 0}
    agree = sum(1 for a, b in pairable if a == b)
    p_o = agree / n
    count_a, count_b = Counter(a for a, _ in pairable), Counter(b for _, b in pairable)
    categories = sorted(set(count_a) | set(count_b))
    p_e = sum((count_a[c] / n) * (count_b[c] / n) for c in categories)
    if p_e < 1:
        kappa = (p_o - p_e) / (1 - p_e)
    else:
        kappa = 1.0 if p_o == 1 else None
    # Coincidence matrix: each unit contributes its two scores in both orders; N = 2n.
    coincidence = Counter()
    for a, b in pairable:
        coincidence[(a, b)] += 1
        coincidence[(b, a)] += 1
    total = 2 * n
    marginal = Counter()
    for (a, _b), count in coincidence.items():
        marginal[a] += count
    observed_sum = sum(count * (a - b) ** 2 for (a, b), count in coincidence.items())
    do = observed_sum / total
    expected_sum = sum(marginal[a] * marginal[b] * (a - b) ** 2 for a in categories for b in categories)
    de = expected_sum / (total * (total - 1)) if total > 1 else 0.0
    if de > 0:
        alpha = 1 - do / de
    else:
        alpha = 1.0 if do == 0 else None
    table = Counter(tuple(sorted((a, b))) for a, b in pairable)
    return {"n_pairable": n, "p_o": round(p_o, 6), "p_e": round(p_e, 6),
            "kappa": None if kappa is None else round(kappa, 6),
            "alpha": None if alpha is None else round(alpha, 6),
            "categories": categories, "table": {f"{a}/{b}": count for (a, b), count in sorted(table.items())},
            "disagreements": n - agree}


def _read_sheet(path) -> dict:
    try:
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames or []
            if "ruling_id" not in fields:
                raise AuditError(f"{path}: no ruling_id column")
            rows = {}
            for row in reader:
                ruling_id = (row.get("ruling_id") or "").strip()
                if not ruling_id:
                    raise AuditError(f"{path}: a row has no ruling_id")
                if ruling_id in rows:
                    raise AuditError(f"{path}: ruling_id {ruling_id} appears twice")
                rows[ruling_id] = row
            return rows
    except OSError as exc:
        raise AuditError(f"{path}: cannot read ({exc})") from exc


def agreement_from_sheet(sheet_a, sheet_b=None, col_a="annotator_1", col_b=None) -> dict:
    """Agreement between the two annotators' scores. One sheet holds both columns; two sheets are compared."""
    a_rows = _read_sheet(sheet_a)
    if sheet_b is None:
        b_rows, col_b = a_rows, (col_b or "annotator_2")
    else:
        b_rows, col_b = _read_sheet(sheet_b), (col_b or "annotator_1")
    only_a, only_b = sorted(set(a_rows) - set(b_rows)), sorted(set(b_rows) - set(a_rows))
    if only_a or only_b:
        raise AuditError(f"ruling ids differ: only in A {only_a[:10]}, only in B {only_b[:10]}")
    pairs, disagreements = [], []
    for ruling_id in sorted(a_rows):
        left = (a_rows[ruling_id].get(col_a) or "").strip()
        right = (b_rows[ruling_id].get(col_b) or "").strip()
        pairs.append((left, right))
        if left and right and left != right:
            disagreements.append({"ruling_id": ruling_id, "a": left, "b": right})
    stats = agreement(pairs)
    stats.update({"n_rows": len(a_rows), "disagreements_detail": disagreements,
                  "unlabelled": sum(1 for left, right in pairs if not str(left).strip() or not str(right).strip())})
    return stats


def format_agreement(stats, sheet_a, sheet_b=None, col_a="annotator_1", col_b=None) -> str:
    def fmt(value):
        return "undefined" if value is None else f"{value:.4f}"
    lines = [f"A: {sheet_a} (column {col_a})",
             f"B: {sheet_b or sheet_a} (column {col_b or ('annotator_2' if sheet_b is None else 'annotator_1')})",
             f"Rows: {stats['n_rows']}; pairable: {stats['n_pairable']}; unlabelled: {stats['unlabelled']}",
             f"Observed agreement p_o: {fmt(stats['p_o'])}",
             f"Chance agreement p_e: {fmt(stats['p_e'])}",
             f"Cohen's kappa (unweighted): {fmt(stats['kappa'])}",
             f"Krippendorff's alpha (interval): {fmt(stats['alpha'])}",
             f"Disagreements: {stats['disagreements']}"]
    for item in stats["disagreements_detail"][:50]:
        lines.append(f"  {item['ruling_id']}: A={item['a']} B={item['b']}")
    return "\n".join(lines)


# ---- command line ----------------------------------------------------------------------------------

def cmd_sample(args) -> int:
    try:
        rows = write_worksheet(args.run_dirs, args.out, args.seed, args.size)
    except (AuditError, ValueError, OSError) as exc:
        print(f"referee_audit: {exc}", file=sys.stderr)
        return 2
    meta = json.loads(Path(str(args.out) + ".meta.json").read_text(encoding="utf-8"))
    print(f"{len(rows)} ruling(s) drawn from {meta['pool_size']} in {len(args.run_dirs)} run(s) -> {args.out}")
    for stratum, item in meta["strata"].items():
        print(f"  {stratum}: {item['drawn']} of {item['pool']}")
    return 0


def cmd_agreement(args) -> int:
    try:
        stats = agreement_from_sheet(args.sheet_a, args.sheet_b, args.col_a, args.col_b)
    except (AuditError, ValueError, OSError) as exc:
        print(f"referee_audit: {exc}", file=sys.stderr)
        return 2
    text = format_agreement(stats, args.sheet_a, args.sheet_b, args.col_a, args.col_b)
    print(text)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "agreement.txt").write_text(text + "\n", encoding="utf-8", newline="\n")
        with open(out / "agreement.json", "w", encoding="utf-8", newline="\n") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"wrote {out}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="referee_audit", description="Sample referee rulings and measure "
                                                                       "two annotators' agreement.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_sample = sub.add_parser("sample", help="draw the seeded worksheet of rulings")
    p_sample.add_argument("run_dirs", nargs="+")
    p_sample.add_argument("--seed", type=int, required=True, help="fixed in the pre-registration")
    p_sample.add_argument("--size", type=int, required=True, help="rulings to draw")
    p_sample.add_argument("--out", required=True, help="the worksheet CSV")
    p_sample.set_defaults(func=cmd_sample)
    p_agree = sub.add_parser("agreement", help="two annotators' scores: p_o, kappa and alpha")
    p_agree.add_argument("sheet_a")
    p_agree.add_argument("sheet_b", nargs="?", help="a second sheet; omitted: both columns are in sheet_a")
    p_agree.add_argument("--col-a", default="annotator_1")
    p_agree.add_argument("--col-b", default=None)
    p_agree.add_argument("--out", default="", help="folder for agreement.txt and agreement.json")
    p_agree.set_defaults(func=cmd_agreement)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
