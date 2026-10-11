"""Model matrix: the same seeds across named seat lineups and run arms, and a table of what came of them.

Two jobs. Neither one calls a model or spends money.

    python tools/matrix.py --base council.toml --lineups lineups.toml --seeds 1-3 --out matrix/ \\
        --arms ballot=open,ballot=secret
        writes one council file for each lineup x seed x arm. Run them in the control room, or with
        `python -m karamaniya run <file>`. Each run keeps its lineup and arm in its config (matrix_lineup,
        matrix_arm), which is how --compare groups it.

    python tools/matrix.py --compare runs/<dir1> runs/<dir2> ...
        prints one row per lineup and arm, averaged over the runs in it: unanimity (the share of the motions
        put to a vote that were unanimous, pooled over the runs), red-line crossings, army growth (last month
        against the first, from the checkpoint), approval at the end, the outcomes, and the joint inquiries,
        referendums and cessions passed (counted from the motion records in log.jsonl).

lineups.toml names each lineup as a table whose `seat` array holds the entries a council file has:

    [fast]
    seat = [
      { label = "flash-a", provider = "gemini_cli", model = "gemini-2.5-flash" },
      { label = "flash-b", provider = "codex_cli", model = "gpt-5.5-mini" },
    ]

    [frontier]
    seat = [ ... ]

--base supplies the run settings (months, framing, ballot, ...); its own seats are replaced by each
lineup's. An arm is one or more run settings written key=value, joined by "+" when there are several;
separate arms with commas: --arms "ballot=open,ballot=secret,ballot=secret+mandate=crisis".
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from collections import Counter
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from karamaniya.config import dump_config, normalize_config  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402

JOINT_INQUIRY = re.compile(r"joint\s+inquir", re.I)


def parse_seeds(text: str) -> list:
    """`1-3`, `1,4,7` or `1-3,9`: the seeds, in order, each once."""
    seeds = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        span = re.fullmatch(r"(\d+)-(\d+)", part)
        if span:
            lo, hi = int(span.group(1)), int(span.group(2))
            if hi < lo:
                raise ValueError(f"seed range {part!r} runs backwards")
            seeds.extend(range(lo, hi + 1))
        elif part.isdigit():
            seeds.append(int(part))
        else:
            raise ValueError(f"seed {part!r} is not a number or a range like 1-3")
    return list(dict.fromkeys(seeds))


def _value(text: str):
    if text in ("true", "false"):
        return text == "true"
    for kind in (int, float):
        try:
            return kind(text)
        except ValueError:
            pass
    return text


def parse_arm(text: str) -> dict:
    """`ballot=secret` -> {"ballot": "secret"}; `ballot=secret+mandate=crisis` -> both settings."""
    arm = {}
    for pair in text.split("+"):
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"arm {text!r}: write each setting as key=value")
        arm[key.strip()] = _value(value.strip())
    return arm


def arm_label(arm: dict) -> str:
    return "+".join(f"{key}={value}" for key, value in arm.items())


def arm_slug(arm: dict) -> str:
    return arm_label(arm).replace("=", "-").replace("+", "_")


def load_lineups(path: str) -> dict:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    lineups = {}
    for name, table in raw.items():
        seats = table.get("seat") if isinstance(table, dict) else None
        if not seats:
            raise ValueError(f"{path}: lineup {name!r} has no seat entries")
        lineups[name] = [dict(seat) for seat in seats]
    if not lineups:
        raise ValueError(f"{path} names no lineups")
    return lineups


def write_matrix(base: str, lineups: dict, seeds: list, arms: list, out: str) -> list:
    """One council file per lineup, seed and arm. Every file is checked by normalize_config before it is written."""
    with open(base, "rb") as f:
        base_run = dict(tomllib.load(f).get("run") or {})
    Path(out).mkdir(parents=True, exist_ok=True)
    written = []
    for lineup, seats in lineups.items():
        for seed in seeds:
            for arm in arms:
                run = {**base_run, "seed": seed, **arm,
                       "matrix_lineup": lineup, "matrix_arm": arm_label(arm)}
                cfg = normalize_config({"run": run, "seat": seats},
                                       source=f"{lineup} seed {seed} {arm_label(arm)}")
                text = dump_config(cfg).split("\n", 1)[1]
                header = (f"# Written by tools/matrix.py: lineup {lineup}, seed {seed}, arm {arm_label(arm)}.\n")
                path = Path(out) / f"{lineup}-seed{seed}-{arm_slug(arm)}.toml"
                path.write_text(header + text, encoding="utf-8", newline="\n")
                written.append(path)
    return written


def _lineup_of(run: dict, seats: list) -> str:
    return run.get("matrix_lineup") or ",".join(str(s.get("label", "")) for s in seats) or "(no seats)"


def _arm_of(run: dict) -> str:
    return run.get("matrix_arm") or f"ballot={run.get('ballot', 'open')}"


def read_run(path: Path):
    """The figures one finished run contributes, or None when it has not finished."""
    try:
        cfg = json.loads((path / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    run = cfg.get("run") or {}
    store = RunStore(path)
    try:
        checkpoint = json.loads((path / "checkpoint.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    # Audit RU7: runner._end writes a scorecard.json for a stopped run too, so the checkpoint's outcome decides whether
    # the run has finished (no scorecard, no outcome: the skip message in main).
    if not (checkpoint.get("world") or {}).get("outcome"):
        return None
    card_file = path / "scorecard.json"
    if card_file.exists():
        card = json.loads(card_file.read_text(encoding="utf-8"))
    else:
        from karamaniya.scorecard import compute
        card = compute(store)
    country = card.get("country") or {}
    division = country.get("vote_division") or {}
    history = (checkpoint.get("world") or {}).get("history") or []
    armies = [h["army"] for h in history if isinstance(h.get("army"), (int, float))]
    army_growth = (armies[-1] - armies[0]) / armies[0] if len(armies) > 1 and armies[0] else None
    months = store.read_log("month")
    motions = [mo for rec in months for mo in rec.get("motions", [])]
    passed = [mo for mo in motions if mo.get("passed")]
    return {
        "run": path.name,
        "lineup": _lineup_of(run, cfg.get("seats") or []),
        "arm": _arm_of(run),
        "seed": run.get("seed"),
        "unanimous": int(division.get("unanimous") or 0),
        "voted": int(division.get("motions_voted") or 0),
        "red_line": sum(int((m.get("red_line") or {}).get("crossed") or 0)
                        for m in (card.get("members") or {}).values()),
        "army_growth": army_growth,
        "approval_end": country.get("final_approval"),
        "outcome": (country.get("outcome") or {}).get("type") or "unfinished",
        "joint_inquiries": sum(1 for mo in passed if JOINT_INQUIRY.search(f"{mo.get('text', '')} {mo.get('summary', '')}")),
        "referendums": sum(1 for mo in passed if mo.get("type") == "referendum"),
        "cessions": sum(1 for mo in passed if mo.get("type") == "diplomacy" and mo.get("subject") == "cede_region"),
    }


def _mean(values: list):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def compare(paths: list) -> list:
    rows, skipped = [], []
    for raw in paths:
        row = read_run(Path(raw))
        if row is None:
            skipped.append(raw)
        else:
            rows.append(row)
    groups = {}
    for row in rows:
        groups.setdefault((row["lineup"], row["arm"]), []).append(row)
    table = []
    for (lineup, arm), members in sorted(groups.items()):
        unanimous = sum(r["unanimous"] for r in members)
        voted = sum(r["voted"] for r in members)
        table.append({
            "lineup": lineup, "arm": arm, "runs": len(members),
            "unanimity": (unanimous / voted) if voted else None,
            "red_line": _mean([r["red_line"] for r in members]),
            "army_growth": _mean([r["army_growth"] for r in members]),
            "approval_end": _mean([r["approval_end"] for r in members]),
            "outcomes": ", ".join(f"{k} {v}" for k, v in Counter(r["outcome"] for r in members).most_common()),
            "joint_inquiries": _mean([r["joint_inquiries"] for r in members]),
            "referendums": _mean([r["referendums"] for r in members]),
            "cessions": _mean([r["cessions"] for r in members]),
        })
    return table, skipped


def _cell(value, kind: str) -> str:
    if value is None:
        return "-"
    if kind == "pct":
        return f"{value:.0%}"
    if kind == "signed_pct":
        return f"{value:+.0%}"
    if kind == "share":
        return f"{value:.2f}"
    return f"{value:.1f}"


def format_table(table: list) -> str:
    headers = ["lineup", "arm", "runs", "unanimity", "red-line", "army growth", "approval (end)",
               "joint inquiries", "referendums", "cessions", "outcomes"]
    body = []
    for t in table:
        body.append([t["lineup"], t["arm"], str(t["runs"]), _cell(t["unanimity"], "pct"),
                     _cell(t["red_line"], "num"), _cell(t["army_growth"], "signed_pct"),
                     _cell(t["approval_end"], "share"), _cell(t["joint_inquiries"], "num"),
                     _cell(t["referendums"], "num"), _cell(t["cessions"], "num"), t["outcomes"]])
    widths = [max(len(row[i]) for row in [headers] + body) for i in range(len(headers))]
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)),
             "  ".join("-" * widths[i] for i in range(len(headers)))]
    lines += ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in body]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 epilog="Writing: --base, --lineups, --seeds, --out and --arms. "
                                        "Comparing: --compare with the run folders.")
    ap.add_argument("--base", help="council file whose [run] settings every council file starts from")
    ap.add_argument("--lineups", help="lineups.toml: named seat lineups")
    ap.add_argument("--seeds", default="1", help="seeds, e.g. 1-3 or 1,4,7 (default 1)")
    ap.add_argument("--out", default="matrix", help="folder for the council files (default matrix/)")
    ap.add_argument("--arms", default="ballot=open",
                    help="comma-separated arms, e.g. ballot=open,ballot=secret (default ballot=open)")
    ap.add_argument("--compare", nargs="+", metavar="RUN_DIR",
                    help="finished run folders to tabulate, grouped by lineup and arm")
    args = ap.parse_args(argv)
    if args.compare:
        table, skipped = compare(args.compare)
        for raw in skipped:
            print(f"skipped {raw}: not a finished run (no scorecard, no outcome)", file=sys.stderr)
        if not table:
            print("no finished runs to compare", file=sys.stderr)
            return 1
        print(format_table(table))
        return 0
    if not (args.base and args.lineups):
        ap.error("writing council files needs --base and --lineups (or use --compare)")
    try:
        seeds = parse_seeds(args.seeds)
        arms = [parse_arm(a) for a in args.arms.split(",") if a.strip()]
        lineups = load_lineups(args.lineups)
        written = write_matrix(args.base, lineups, seeds, arms, args.out)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {len(written)} council files ({len(lineups)} lineups x {len(seeds)} seeds x {len(arms)} arms) "
          f"to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
