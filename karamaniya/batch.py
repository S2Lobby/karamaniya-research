"""Repeat a fixed council assignment across seeds and measure political variation."""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from .config import load_config
from .runner import new_run, preflight
from .scorecard import compute
from .storage import RunStore


def _run_metrics(path: Path) -> dict:
    store = RunStore(path)
    card = compute(store)
    world, _, _ = store.load_checkpoint()
    months = store.read_log("month")
    motions = [mo for rec in months for mo in rec.get("motions", [])
               if mo.get("type") not in ("assign_office", "vacate_office")]
    previous, reversals = {}, 0
    for motion in motions:
        if not motion.get("passed") or motion.get("type") not in ("set_policy", "constitution"):
            continue
        key = (motion["type"], motion["subject"])
        if key in previous and previous[key] != motion["value"]:
            reversals += 1
        previous[key] = motion["value"]
    trusts = [rel.get("trust", 50) for member in world.members for rel in member.relationships.values()]
    division = card["country"]["vote_division"]
    analytics = card.get("analytics") or {}
    metrics = analytics.get("metrics") or {}
    return {"run": path.name, "seed": world.seed, "months": len(months),
            "mapping": RunStore(path).read_json("config.json").get("mapping", {}),
            "unanimous_rate": (metrics.get("council") or {}).get("unanimous_rate"),
            "split_rate": (metrics.get("council") or {}).get("split_rate"),
            "withdrawal_rate": (metrics.get("council") or {}).get("withdrawal_rate"),
            "promises_kept": (metrics.get("agents") or {}).get("promises_kept", 0),
            "leaks": (metrics.get("agents") or {}).get("leaks", 0),
            "resignations": (metrics.get("political") or {}).get("resignations", 0),
            "authoritarian_drift": ((metrics.get("political") or {}).get("authoritarian_drift") or {}).get("highest_stage"),
            "alignments": (analytics.get("factions") or {}).get("labels", []),
            "trust_matrix": {m.id: {o: round(r.get("trust", 50)) for o, r in m.relationships.items()} for m in world.members},
            "offices_filled": sum(bool(holder) for holder in world.const.offices.values()),
            "substantive_motions": division.get("substantive", 0),
            "unanimous_substantive": division.get("substantive_unanimous", 0),
            "contested_substantive": division.get("substantive_contested", 0),
            "failed_motions": division.get("substantive_failed", division.get("failed", 0)),
            "policy_reversals": reversals,
            "trust_spread": round(statistics.pstdev(trusts), 2) if len(trusts) > 1 else 0,
            "broken_promises": sum(m.get("broken_promises", 0) for m in card["members"].values()),
            "principle_violations": sum(m.get("commitment_violations", 0) for m in card["members"].values()),
            "election_delays_proposed": sum(m.get("election_delay_tabled", 0) for m in card["members"].values()),
            "election_delay_yes_votes": sum(m.get("election_delay_yes", 0) for m in card["members"].values()),
            "coups": card["country"].get("coups_attempted", 0),
            "war": bool(world.dip.war or any(h.get("war") for h in world.history)),
            "democratic_handover": world.outcome.get("type") == "voted_out",
            "outcome": world.outcome.get("type", ""),
            "final_inflation_yoy": card["country"].get("final_inflation_yoy", 0),
            "final_approval": card["country"].get("final_approval", 0)}


def simulate(config: str, *, runs: int, months: int, first_seed: int = 1,
             runs_dir: str = "runs", prefix: str = "batch", check: bool = True,
             same_seats: bool = True, rotate_seats: bool = False, scenario: str = "", quiet: bool = False) -> dict:
    if not 1 <= runs <= 100:
        raise ValueError("runs must be between 1 and 100")
    cfg = load_config(config) if not isinstance(config, dict) else config
    cfg["run"]["shuffle_seats"] = not same_seats and not rotate_seats
    if scenario:
        from .scenarios import resolve_name
        cfg["run"]["test_scenario"] = resolve_name(scenario)
    base_seats = list(cfg["seats"])
    if check:
        broken = preflight(cfg)
        if broken:
            raise RuntimeError("seat preflight failed: " + "; ".join(f"{b['label']}: {b['error']}" for b in broken))
    root = Path(runs_dir)
    output = root / f"{prefix}-summary.json"
    if output.exists():
        raise FileExistsError(f"batch would overwrite {output}")
    rows = []
    for seed in range(first_seed, first_seed + runs):
        name = f"{prefix}-seed{seed}"
        path = root / name
        if path.exists():
            raise FileExistsError(f"batch would overwrite {path}")
        if rotate_seats:
            # Spec 99: the same models move one seat along each seed, so each sits in different letters.
            k = (seed - first_seed) % len(base_seats)
            cfg["seats"] = base_seats[k:] + base_seats[:k]
        new_run(cfg, runs_dir=root, name=name, months=months, seed=seed, quiet=True, check=False)
        world, _, meta = RunStore(path).load_checkpoint()
        if len(world.history) < months and not world.ended():
            raise RuntimeError(f"{name} stopped before Month {months}: {meta.get('stopped', 'unknown reason')}")
        row = _run_metrics(path)
        rows.append(row)
        if not quiet:
            print(f"seed {seed}: {row['contested_substantive']}/{row['substantive_motions']} contested, "
                  f"{row['failed_motions']} failed, outcome {row['outcome']}", flush=True)
    total = sum(r["substantive_motions"] for r in rows)
    def spread(key):
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool)]
        return {"min": min(vals), "max": max(vals), "mean": round(sum(vals) / len(vals), 3),
                "sd": round(statistics.pstdev(vals), 3) if len(vals) > 1 else 0.0} if vals else None
    pair_trust = {}
    for r in rows:
        for a, views in r.get("trust_matrix", {}).items():
            for b, value in views.items():
                pair_trust.setdefault(f"{a}->{b}", []).append(value)
    relationship_variation = round(sum(statistics.pstdev(v) for v in pair_trust.values() if len(v) > 1)
                                   / max(1, sum(1 for v in pair_trust.values() if len(v) > 1)), 2)
    substantive_total = sum(r["substantive_motions"] for r in rows)
    unanimous_total = sum(r["unanimous_substantive"] for r in rows)
    diagnosis = ("too convergent: most substantive motions pass unanimously" if substantive_total and unanimous_total / substantive_total >= .8
                 else "mixed agreement and disagreement" if substantive_total else "no substantive motions")
    summary = {"config": str(Path(config).resolve()) if not isinstance(config, dict) else "(config dict)",
               "same_model_seat_assignment": same_seats and not rotate_seats, "rotated_seats": rotate_seats,
               "scenario": scenario or None,
               "distribution": {k: spread(k) for k in ("unanimous_rate", "split_rate", "failed_motions", "policy_reversals",
                                                       "trust_spread", "broken_promises", "principle_violations", "coups",
                                                       "resignations", "leaks", "final_inflation_yoy", "final_approval")},
               "relationship_variation_across_seeds": relationship_variation,
               "outcomes": {o: sum(1 for r in rows if r["outcome"] == o) for o in {r["outcome"] for r in rows}},
               "alignment_structures": sorted({" | ".join(r.get("alignments") or ["none"]) for r in rows}),
               "convergence_check": diagnosis,
               "runs": rows, "totals": {
                   "substantive_motions": total,
                   "unanimous_substantive": sum(r["unanimous_substantive"] for r in rows),
                   "contested_substantive": sum(r["contested_substantive"] for r in rows),
                   "failed_motions": sum(r["failed_motions"] for r in rows),
                   "policy_reversals": sum(r["policy_reversals"] for r in rows),
                   "democratic_handovers": sum(r["democratic_handover"] for r in rows),
               }}
    root.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
