"""What each token-saving feature saves, on one deterministic world.

    python tools/token_benchmark.py [--months 12] [--seed 1] [--json out.json]

Every variant is the same scripted council (council.scripted.toml) on the same seed: the stand-ins
answer from the world state, not from the prompt, so the world and the calls are the same in every
variant and only what the prompts say, and how they are ordered, differs. That makes the comparison
exact for input characters and for the prefix-cache simulation. It cannot measure what real models
would do differently (answer quality, output length, whether they choose to stand by or what they
ask to read); the quiet-month and briefing variants therefore show what the feature saves when the
delegates use it (every delegate standing by, every delegate reading nothing extra), an upper bound.
No model is called.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from karamaniya.tokens import ledger  # noqa: E402

VARIANTS = (
    ("engine 5 (classic)", {}, None),
    ("cache-friendly layout", {"layout": "cache_friendly"}, None),
    ("compact schema hint", {"schema_hint": "compact"}, None),
    ("briefing on demand, nothing requested", {"briefing": "on_demand"}, None),
    ("quiet months, everyone stands by", {"wakeups": "on_events", "max_quiet_months": 3}, "stand_by"),
    ("all of the above", {"layout": "cache_friendly", "schema_hint": "compact", "briefing": "on_demand",
                          "wakeups": "on_events", "max_quiet_months": 3}, "stand_by"),
)


def run_variant(tmp: str, tokens: dict, hook: str | None, months: int, seed: int) -> str:
    from test_token_saving import scripted_council   # the same in-process council the tests use
    extra = (lambda ctx: {"stand_by": {"months": "3", "wake_if": []}}) if hook == "stand_by" else None
    council, w = scripted_council(tmp, tokens, extra, months=months, seed=seed)
    while not w.ended() and w.month < months:
        council.run_month()
    return council.store.path


def main() -> int:
    ap = argparse.ArgumentParser(description="token savings of each feature on one deterministic world")
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()
    rows = []
    base = None
    for name, tokens, hook in VARIANTS:
        tmp = tempfile.mkdtemp(prefix="karamaniya-bench-")
        try:
            report = ledger(run_variant(tmp, tokens, hook, args.months, args.seed))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        row = {"variant": name, "tokens": tokens, "calls": report["calls"],
               "input_chars": report["input"]["chars"], "input_tokens_est": report["input"]["estimated_tokens"],
               "reuse_month": report["cache"]["month"]["reused_share"],
               "reuse_run": report["cache"]["run"]["reused_share"],
               "cost_month_0.1": report["cache"]["month"]["relative_input_cost_at_read_0.1"],
               "same_model_reuse_month": report["cache_same_model_month"]["reused_share"]}
        base = base or row
        row["input_vs_engine5"] = round(row["input_chars"] / base["input_chars"], 4)
        # Input cost relative to engine 5 with no cache at all: fewer characters, and of those,
        # the share a cache serves at a tenth of the price (within one month).
        row["billed_vs_engine5_uncached"] = round(row["input_vs_engine5"] * row["cost_month_0.1"], 4)
        rows.append(row)
    print(f"{args.months} months, seed {args.seed}, five scripted seats (each its own model for the cache)\n")
    print(f"{'variant':40} {'calls':>5} {'input chars':>12} {'vs e5':>6} {'cache/mo':>8} {'cache/run':>9} "
          f"{'billed*':>7}")
    for r in rows:
        print(f"{r['variant']:40} {r['calls']:5} {r['input_chars']:12,} {r['input_vs_engine5']:6.2f} "
              f"{r['reuse_month']:8.1%} {r['reuse_run']:9.1%} {r['billed_vs_engine5_uncached']:7.2f}")
    print("\n* input cost relative to engine 5 without any cache, with a cache that serves the reusable prefix "
          "within a month at a tenth of the price")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"months": args.months, "seed": args.seed, "rows": rows}, f, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
