"""Evidence and counts for the detector precision audit (research only; worker 12).

    python tools/detector_audit.py extract    # writes docs/detector_labels/*_evidence*.csv from the recorded runs
    python tools/detector_audit.py score      # joins the hand labels to the evidence and prints counts and intervals
    python tools/detector_audit.py wilson K N # one 95% Wilson interval

The recorded runs are read-only input (research/runs). Nothing here calls a model. The labels are one annotator's
judgements, typed by hand into docs/detector_labels/*_labels*.csv. This script only joins them to the evidence and
counts them; it never decides a label.
"""
from __future__ import annotations

import csv
import glob
import json
import math
import os
import random
import re
import sys

RUNS = "C:/Users/litle/Karamaniya/research/runs"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "detector_labels")
#: The D1 sample: random.Random(SEED).sample(range(137), SAMPLE), over the flags in extract()'s order.
SEED = 20261017
SAMPLE = 40
Z = 1.959963984540054   # two-sided 95%


def wilson(k: int, n: int, z: float = Z) -> tuple:
    """Wilson score interval for k successes out of n trials."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def sample_indices(total: int, k: int, seed: int = SEED) -> list:
    return sorted(random.Random(seed).sample(range(total), k))


# ---- reading the recorded runs (read-only) -------------------------------------------------------------------------
def run_logs():
    for log in sorted(glob.glob(os.path.join(RUNS, "*", "log.jsonl"))):
        yield os.path.basename(os.path.dirname(log)), log


def month_records(log: str):
    with open(log, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("type") == "month":
                yield rec


def decision_prompts(run: str) -> dict:
    """(month index, member) -> the decision-phase prompt. A decision asked twice has two prompts; the first is kept."""
    out = {}
    path = os.path.join(RUNS, run, "prompts.jsonl")
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("phase") == "decision":
                out.setdefault((rec.get("month"), rec.get("member")), rec.get("prompt", ""))
    return out


# ---- D1: where the flagged figure sits in the text --------------------------------------------------------------
_FIGURE = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(%|percentage|percent|/\s*100\b|million|billion|thousand|bn\b|M\b|m\b|k\b)?", re.I)
_SCALE = {"%": 0.01, "percent": 0.01, "percentage": 0.01, "/100": 0.01, "million": 1e6, "m": 1e6,
          "bn": 1e9, "billion": 1e9, "thousand": 1e3, "k": 1e3, "": 1.0}
_BOUNDARY = re.compile(r"(?<!\d)\.(?!\d)|[!?;\n]")


#: A figure after a label word is an identifier or a date ("Month 6", "round 3"), not a statistic. The engine's
#: _is_label skips the same words (motion_actions._LABEL_WORD); without this, "Month 6" matched a claim of 6%.
_LABEL_BEFORE = re.compile(r"\b(?:month|year|week|day|round|motion|article|clause|section|item|step|phase)s?\s*#?\s*$",
                           re.I)


def locate(text: str, claimed, claim_text: str):
    """Where the engine's figure sits in the field's text: (start, end, how found). The engine's claim_text is
    normalised ("60M" is "60 m"), so the figure is matched by its value first, then by its bare number."""
    head = re.match(r"\s*(\d[\d,]*(?:\.\d+)?)", claim_text or "")
    bare = float(head.group(1).replace(",", "")) if head else None
    fallback = None
    for m in _FIGURE.finditer(text or ""):
        if _LABEL_BEFORE.search((text or "")[max(0, m.start() - 30):m.start()]):
            continue
        base = float(m.group(1).replace(",", ""))
        unit = re.sub(r"\s+", "", (m.group(2) or "").lower())
        value = base * _SCALE.get(unit, 1.0)
        if claimed is not None and abs(value - float(claimed)) <= max(1e-9, 1e-6 * abs(float(claimed))):
            return m.start(), m.end(), "value"
        if fallback is None and bare is not None and abs(base - bare) < 1e-9:
            fallback = (m.start(), m.end(), "bare_number")
    return fallback or (None, None, "not_found")


def sentence_around(text: str, start, end) -> str:
    text = text or ""
    if start is None:
        return text.strip()[:400]
    lo = 0
    for m in _BOUNDARY.finditer(text, 0, start):
        lo = m.end()
    stop = _BOUNDARY.search(text, end)
    return text[lo:(stop.start() if stop else len(text))].strip()


#: Words that name a metric in the decision prompt, where the delegate was told its canonical numbers.
METRIC_WORDS = {
    "reserves": ("reserve", "gold", "cash desk"), "arrears": ("arrear", "unpaid", "bills owed"),
    "army_size": ("army", "soldier", "troop", "forces"), "union_forces": ("union force", "union army", "union troops",
                                                                         "union strength", "union about"),
    "inflation": ("inflation", "prices"), "unemployment": ("unemploy",), "approval": ("approval",),
    "unrest": ("unrest",), "food_ratio": ("food", "grain"), "hunger": ("hunger",),
    "army_readiness": ("readiness", "morale", "loyalty"),
}


def briefing_excerpt(prompt: str, metric: str, limit: int = 600) -> str:
    """Lines of the decision prompt (what the delegate was told) that name the metric with a figure."""
    words = METRIC_WORDS.get(metric, (metric or "",))
    hits = []
    for line in (prompt or "").splitlines():
        if re.search(r"\d", line) and any(w in line.lower() for w in words):
            hits.append(line.strip()[:240])
    return " | ".join(hits)[:limit]


def d1_rows() -> list:
    rows = []
    for run, log in run_logs():
        prompts = decision_prompts(run)
        for rec in month_records(log):
            m = rec.get("month")
            statements = {}
            for s in rec.get("statements") or []:
                statements.setdefault(s.get("member"), str(s.get("statement", "")))
            decisions = rec.get("decisions") or {}
            for g in rec.get("grounding") or []:
                mid = g.get("member")
                if g.get("field") == "statement":
                    text = statements.get(mid, "")
                else:
                    text = str((decisions.get(mid) or {}).get("notes", ""))
                start, end, how = locate(text, g.get("claimed"), g.get("claim_text"))
                rows.append({
                    "run": run, "month_no": m + 1, "month_name": rec.get("label", ""), "member": mid,
                    "field": g.get("field"), "metric": g.get("metric"), "claim_text": g.get("claim_text"),
                    "claimed": g.get("claimed"), "observed": g.get("observed"), "located": how,
                    "sentence": sentence_around(text, start, end),
                    "briefing": briefing_excerpt(prompts.get((m, mid), ""), g.get("metric")),
                    "prompt_found": (m, mid) in prompts,
                })
    for i, row in enumerate(rows, 1):
        row["flag_id"] = f"D1-{i:03d}"
    return rows


# ---- D2: a final vote against the delegate's own stated position ----------------------------------------------------
def d2_rows() -> list:
    rows = []
    for run, log in run_logs():
        for rec in month_records(log):
            motions = {str(mo.get("id")): mo for mo in rec.get("motions") or []}
            decisions = rec.get("decisions") or {}
            for v in rec.get("vote_intent_mismatches") or []:
                mid, motion = v.get("member"), str(v.get("motion"))
                dec = decisions.get(mid) or {}
                mo = motions.get(motion) or {}
                full = (dec.get("vote_reasons_full") or {}).get(motion) or (dec.get("vote_reasons") or {}).get(motion)
                rows.append({
                    "run": run, "month_no": rec.get("month") + 1, "month_name": rec.get("label", ""),
                    "member": mid, "motion": motion, "motion_type": mo.get("type", ""),
                    "motion_subject": mo.get("subject", ""), "motion_text": str(mo.get("text", ""))[:300],
                    "passed": mo.get("passed", ""), "tally": str(mo.get("tally", ""))[:120],
                    "stance": v.get("stance"), "vote": v.get("vote"), "source": v.get("source"),
                    "statement": str(v.get("statement", ""))[:300],
                    "vote_condition": str((dec.get("vote_conditions") or {}).get(motion, ""))[:200],
                    "reason_full": str(full or v.get("reason", "")),
                })
    for i, row in enumerate(rows, 1):
        row["flag_id"] = f"D2-{i:03d}"
    return rows


# ---- D4: an office holder's order against a council directive -----------------------------------------------------
def decision_calls(log: str) -> dict:
    """(month index, member) -> the raw text of the last decision-phase answer."""
    out = {}
    with open(log, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("type") == "call" and rec.get("phase") == "decision":
                out[(rec.get("month"), rec.get("member"))] = str(rec.get("raw", ""))
    return out


def raw_order(raw: str, office: str, lever: str):
    """What the delegate wrote for the lever, read from its raw answer. A patronage order is one key, 'patronage'."""
    key = "patronage" if lever.startswith("patronage") else lever
    try:
        return json.loads(raw).get("orders", {}).get(office, {}).get(key, "(absent)")
    except (ValueError, AttributeError):
        return "(unparsed)"


def directive_in_force(prompt: str, lever: str) -> str:
    """The value the decision prompt gives for the lever under 'Current directives:' (the month's opening state).
    Values are cut at ';' only: a decimal point is part of the value (0.2), not the end of the list."""
    for line in (prompt or "").splitlines():
        if line.startswith("Current directives:"):
            m = re.search(r"(?<![\w])" + re.escape(lever) + r" = ([^;]+)", line)
            return m.group(1).strip().rstrip(".") if m else "(not listed)"
    return "(no directives line)"


def d4_rows() -> list:
    rows = []
    for run, log in run_logs():
        prompts = None
        calls = None
        for rec in month_records(log):
            if not rec.get("defiance"):
                continue
            if prompts is None:
                prompts, calls = decision_prompts(run), decision_calls(log)
            m = rec.get("month")
            for d in rec.get("defiance") or []:
                mid, lever, office = d.get("member"), d.get("lever"), d.get("office")
                comp = next((c for c in rec.get("compliance") or []
                             if c.get("member") == mid and c.get("lever") == lever), {})
                order = next((o for o in rec.get("office_orders") or []
                              if o.get("member") == mid and o.get("lever") == lever), {})
                family = "patronage" if lever.startswith("patronage") else lever
                touching = []
                for mo in rec.get("motions") or []:
                    if family in json.dumps(mo, ensure_ascii=False):
                        touching.append(f"{mo.get('id')} {mo.get('type')}/{mo.get('subject')} "
                                        f"{mo.get('execution_status')}: {str(mo.get('result'))[:70]}")
                rows.append({
                    "run": run, "month_no": m + 1, "month_name": rec.get("label", ""), "member": mid,
                    "office": office, "lever": lever, "directive": d.get("directive"), "order": d.get("value"),
                    "directive_open": directive_in_force(prompts.get((m, mid), ""), lever),
                    "order_raw": raw_order(calls.get((m, mid), "{}"), office, lever),
                    "compliance_status": comp.get("compliance_status", ""), "compliance_note": comp.get("note", ""),
                    "order_status": order.get("status", ""), "executed": order.get("actual_value", ""),
                    "motions_touching_lever": " | ".join(touching),
                })
    for i, row in enumerate(rows, 1):
        row["flag_id"] = f"D4-{i:03d}"
    return rows


# ---- writing and scoring ------------------------------------------------------------------------------------------
def write_csv(path: str, rows: list, fields: list) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        # The repository is LF (.gitattributes); csv would write CRLF by default.
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def read_csv(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def extract() -> int:
    os.makedirs(OUT, exist_ok=True)
    rows = d1_rows()
    chosen = set(sample_indices(len(rows), SAMPLE))
    for i, row in enumerate(rows):
        row["in_sample"] = "yes" if i in chosen else "no"
    fields = ["flag_id", "in_sample", "run", "month_no", "month_name", "member", "field", "metric", "claim_text",
              "claimed", "observed", "located", "sentence", "briefing", "prompt_found"]
    write_csv(os.path.join(OUT, "D1_evidence_all137.csv"), rows, fields)
    located = {}
    for row in rows:
        located[row["located"]] = located.get(row["located"], 0) + 1
    print(f"D1 flags: {len(rows)}; sample of {SAMPLE} with seed {SEED}: "
          f"{', '.join(rows[i]['flag_id'] for i in sorted(chosen))}")
    print(f"D1 located: {located}; decision prompt found: {sum(r['prompt_found'] for r in rows)}")
    d2 = d2_rows()
    write_csv(os.path.join(OUT, "D2_evidence_36.csv"), d2,
              ["flag_id", "run", "month_no", "month_name", "member", "motion", "motion_type", "motion_subject",
               "motion_text", "passed", "tally", "stance", "vote", "source", "statement", "vote_condition",
               "reason_full"])
    print(f"D2 flags: {len(d2)}")
    d4 = d4_rows()
    write_csv(os.path.join(OUT, "D4_evidence_all14.csv"), d4,
              ["flag_id", "run", "month_no", "month_name", "member", "office", "lever", "directive", "order",
               "directive_open", "order_raw", "compliance_status", "compliance_note", "order_status", "executed",
               "motions_touching_lever"])
    levers = {}
    for row in d4:
        levers[row["lever"]] = levers.get(row["lever"], 0) + 1
    print(f"D4 defiance records: {len(d4)}; by lever: {levers}")
    return 0


def tally(labels: list, true_label: str, false_label: str) -> dict:
    counts = {}
    for row in labels:
        counts[row["label"]] = counts.get(row["label"], 0) + 1
    tp, fp, unclear = counts.get(true_label, 0), counts.get(false_label, 0), counts.get("UNCLEAR", 0)
    decided = tp + fp
    out = {"labelled": len(labels), "counts": counts, "decided": decided}
    if decided:
        lo, hi = wilson(tp, decided)
        out.update(precision=tp / decided, wilson95=(lo, hi))
    if unclear:
        out["bounds_with_unclear"] = (tp / (decided + unclear), (tp + unclear) / (decided + unclear))
    return out


def join_labels(evidence_csv: str, labels_csv: str, out_csv: str, fields: list) -> list:
    evidence = {row["flag_id"]: row for row in read_csv(evidence_csv)}
    labels = read_csv(labels_csv)
    joined = []
    for lab in labels:
        ev = evidence.get(lab["flag_id"])
        if ev is None:
            raise SystemExit(f"no evidence for {lab['flag_id']} in {evidence_csv}")
        joined.append({**ev, "label": lab["label"], "reason": lab["reason"]})
    write_csv(out_csv, joined, fields)
    return labels


def score() -> int:
    labels = join_labels(os.path.join(OUT, "D1_evidence_all137.csv"), os.path.join(OUT, "D1_labels_sample40.csv"),
                         os.path.join(OUT, "D1_labelled_sample40.csv"),
                         ["flag_id", "run", "month_no", "member", "field", "metric", "claim_text", "claimed",
                          "observed", "sentence", "briefing", "label", "reason"])
    print("D1 (precision: TRUE_ERROR of decided):", tally(labels, "TRUE_ERROR", "FALSE_POSITIVE"))
    labels = join_labels(os.path.join(OUT, "D2_evidence_36.csv"), os.path.join(OUT, "D2_labels_36.csv"),
                         os.path.join(OUT, "D2_labelled_36.csv"),
                         ["flag_id", "run", "month_no", "member", "motion", "motion_type", "motion_subject",
                          "stance", "vote", "statement", "reason_full", "label", "reason"])
    print("D2 (precision: TRUE_MISMATCH of decided):", tally(labels, "TRUE_MISMATCH", "FALSE_POSITIVE"))
    labels = join_labels(os.path.join(OUT, "D4_evidence_all14.csv"), os.path.join(OUT, "D4_labels_14.csv"),
                         os.path.join(OUT, "D4_labelled_14.csv"),
                         ["flag_id", "run", "month_no", "member", "office", "lever", "directive", "order",
                          "directive_open", "order_raw", "compliance_status", "order_status", "executed",
                          "motions_touching_lever", "label", "reason"])
    counts = {}
    for row in labels:
        counts[row["label"]] = counts.get(row["label"], 0) + 1
    print("D4 (counts, not a precision):", {"labelled": len(labels), **counts})
    return 0


def main(argv: list) -> int:
    if not argv or argv[0] not in ("extract", "score", "wilson"):
        print(__doc__)
        return 2
    if argv[0] == "extract":
        return extract()
    if argv[0] == "score":
        return score()
    k, n = int(argv[1]), int(argv[2])
    lo, hi = wilson(k, n)
    print(f"{k}/{n} = {k / n:.4f}; Wilson 95%: [{lo:.4f}, {hi:.4f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
