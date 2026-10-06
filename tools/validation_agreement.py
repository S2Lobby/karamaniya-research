"""Agreement between engine labels and human labels (Task D).

Read-only. Expects research_work/classifier_validation_key.csv plus a
human-filled copy with column `human_label` (and optional `human_label_2`).
Engine column: `engine_label` (NON_UNANIMOUS_CONTROL rows excluded from
engine-vs-human scores; UNANIMOUS_UNCLASSIFIED reported separately).

Usage:
  python tools/validation_agreement.py --human classifier_validation_human.csv
"""
import argparse, csv, math
from collections import Counter

CATS = ["INITIAL_CONSENSUS", "NEGOTIATED_CONVERGENCE", "CONDITIONAL_COMPROMISE", "UNKNOWN"]

def load(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def cohen_kappa(pairs):
    cats = sorted(set(a for a, _ in pairs) | set(b for _, b in pairs))
    n = len(pairs)
    if n == 0:
        return float("nan")
    po = sum(1 for a, b in pairs if a == b) / n
    ra = Counter(a for a, _ in pairs)
    rb = Counter(b for _, b in pairs)
    pe = sum(ra[c] * rb[c] for c in cats) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")

def report(engine_human):
    n = len(engine_human)
    agree = sum(1 for e, h in engine_human if e == h)
    print(f"episodes_scored={n} agreement={agree}/{n}={agree/n:.3f}" if n else "no scored episodes")
    for c in CATS:
        tp = sum(1 for e, h in engine_human if e == c and h == c)
        fp = sum(1 for e, h in engine_human if e == c and h != c)
        fn = sum(1 for e, h in engine_human if e != c and h == c)
        prec = tp / (tp + fp) if tp + fp else float("nan")
        rec = tp / (tp + fn) if tp + fn else float("nan")
        print(f"{c}: precision={prec:.3f} recall={rec:.3f} (tp={tp} fp={fp} fn={fn})")
    cats = CATS
    print("confusion (rows=engine, cols=human):")
    print(" eng \\ hum " + " ".join(f"{c[:7]:>7}" for c in cats))
    for e in cats:
        row = [(h, sum(1 for x, y in engine_human if x == e and y == h)) for h in cats]
        print(f" {e[:9]:>9} " + " ".join(f"{v:>7}" for _, v in row))
    print(f"cohen_kappa(engine,human)={cohen_kappa(engine_human):.3f}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--human", required=True)
    ap.add_argument("--engine-col", default="engine_label")
    ap.add_argument("--human-col", default="human_label")
    ap.add_argument("--human2-col", default="human_label_2")
    args = ap.parse_args()
    rows = load(args.human)
    scored = [(r[args.engine_col], r[args.human_col]) for r in rows
              if r.get(args.engine_col) in CATS and r.get(args.human_col) in CATS]
    skipped = len(rows) - len(scored)
    print(f"rows={len(rows)} scored={len(scored)} skipped_controls_unclassified={skipped}")
    report(scored)
    r2 = [(r[args.human_col], r[args.human2_col]) for r in rows
          if r.get(args.human_col) in CATS + ["NON_UNANIMOUS"] and r.get(args.human2_col) in CATS + ["NON_UNANIMOUS"]]
    if r2:
        a = sum(1 for x, y in r2 if x == y)
        print(f"inter_rater: {a}/{len(r2)}={a/len(r2):.3f} kappa={cohen_kappa(r2):.3f}")

if __name__ == "__main__":
    main()
