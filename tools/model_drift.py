"""Which model actually answered each seat? Flags seats whose served model drifted mid-run.

A seat is configured with one label and one model, but some providers answer with something
else: the openrouter/free auto-router picks a different free model per request, and CLI
wrappers (copilot auto, claude cli) can be moved to another model by the provider. The run
records the served model on every call, so the drift is visible after the fact -- but a seat
that quietly became eight different models is not one agent, and any per-model reading of its
behaviour is unsafe. This tool makes that visible in one line per seat.

Usage:
    python tools/model_drift.py runs/20261011-211521-seed1        (one run)
    python tools/model_drift.py runs --all                        (every run under a folder)

Exit code: 0 if no seat drifted, 1 if any did.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def scan_run(run: Path) -> dict:
    cfg_path = run / "config.json"
    log_path = run / "log.jsonl"
    configured = {}
    labels = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            for s in cfg.get("seats", []):
                labels[s.get("label")] = s.get("model")
            for letter, label in (cfg.get("mapping") or {}).items():
                configured[letter] = f"{label} ({labels.get(label, '?')})"
        except Exception:
            pass
    served: dict = {}
    if log_path.exists():
        with open(log_path, encoding="utf-8") as fh:
            for line in fh:
                if '"served_model"' not in line and '"seat"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("type") not in ("call", "foreign_call"):
                    continue
                seat = str(rec.get("seat") or rec.get("member") or "?")
                served.setdefault(seat, Counter())[str(rec.get("served_model") or rec.get("model") or "?")] += 1
    return {"configured": configured, "served": served}


def report(run: Path) -> bool:
    data = scan_run(run)
    drifted = False
    rows = []
    for seat, counts in sorted(data["served"].items()):
        models = counts.most_common()
        flag = len(models) > 1
        drifted = drifted or flag
        rows.append((seat, data["configured"].get(seat, ""), models, flag))
    print(f"== {run.name}")
    if not rows:
        print("   (no call records)")
        return drifted
    for seat, conf, models, flag in rows:
        mark = "DRIFT" if flag else "ok   "
        first = models[0]
        print(f"   [{mark}] seat {seat:<4} {conf:<44} served {len(models)} model(s): "
              f"{first[1]:>4}x {first[0]}" + ("" if not flag else "  <-- sits more than one model"))
        if flag:
            for name, n in models[1:]:
                print(f"            {n:>4}x {name}")
    return drifted


def main(argv) -> int:
    args = [a for a in argv if not a.startswith("--")]
    all_mode = "--all" in argv
    if not args:
        print(__doc__)
        return 2
    target = Path(args[0])
    runs = [d for d in sorted(target.iterdir()) if (d / "log.jsonl").exists()] if all_mode and target.is_dir() else [target]
    results = [report(r) for r in runs]          # no short-circuit: every run gets printed
    any_drift = any(results)
    print("\nmodel-identity drift found" if any_drift else "\nno seat drifted")
    return 1 if any_drift else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
