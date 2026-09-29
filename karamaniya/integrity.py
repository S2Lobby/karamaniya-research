"""Auditing a finished or running run for motions that were executed as a different act (spec 111).

Runs recorded before the prose/action check existed can contain a motion whose text and whose
executable payload disagreed. This module finds those, works out whether the wrong act actually
reached canonical world state, and writes a correction record beside the run.

It never rewrites recorded history. The original statements, motions, votes and results stay exactly
as they were; the correction is a separate file that names what happened and how far it spread. A
run whose world state was changed by a wrong action is marked CORRECTED_BEHAVIORAL and carries the
parameters for a deterministic replay; one where the problem never left the logs is marked
CORRECTED_NON_BEHAVIORAL.
"""
from __future__ import annotations

import json

from . import motion_actions
from .storage import RunStore

#: What each diplomatic action touches in canonical state, for working out how far a wrong
#: execution spread. Keys are the state it can change; the values are how to read them.
ACTION_EFFECTS = {
    "trade_deal": ("league_trust", "counters.league_trade", "foreign.league.commercial_interest"),
    "alliance": ("league_alliance", "dip.nonaggression"),
    "loan_request": ("dip.league_loan_pending", "foreign.league.loan", "foreign.league.financial_exposure"),
    "military_aid": ("dip.league_aid",),
    "grain_deal": ("dip.grain_embargo", "foreign.actors.dorsania"),
    "non_aggression_pact": ("dip.nonaggression", "dip.union_weariness"),
    "trade_talks": ("counters.union_delay", "dip.grain_embargo"),
    "ceasefire": ("dip.ceasefire", "dip.war"),
    "federation": ("dip.federation", "outcome"),
    "join_union": ("outcome",),
    "diplomatic_protest": ("dip.union_weariness", "dip.propaganda"),
}


def _dig(state: dict, dotted: str):
    node = state
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list):
            return None
        else:
            return None
    return node


def audit(store: RunStore, world: dict | None = None) -> dict:
    """Every motion whose text and executable action disagreed, and what became of it."""
    if world is None:
        world = store.load_checkpoint()[0].to_dict()
    months = store.read_log("month")
    findings = []
    for rec in months:
        for mo in rec.get("motions", []):
            clash = motion_actions.conflict(_WorldView(world), mo)
            if not clash:
                continue
            action = clash["structured_action"]
            executed = bool(mo.get("passed")) and not mo.get("withdrawn") and not mo.get("void")
            findings.append({
                "month": rec.get("month"), "motion": mo.get("id"), "proposer": mo.get("proposer"),
                "prose": clash["prose"], "structured_action": action,
                "conflicts": clash["reasons"],
                "vote": {k: v for k, v in (mo.get("votes") or {}).items() if v in ("yes", "no")},
                "tally": mo.get("tally"), "passed": bool(mo.get("passed")),
                "executed": executed,
                "recorded_result": mo.get("result", ""),
                "touched_state": sorted(ACTION_EFFECTS.get(action.get("action_type"), ())) if executed else [],
            })
    behavioural = [f for f in findings if f["executed"]]
    return {
        "run": store.path.name,
        "months_audited": len(months),
        "findings": findings,
        "executed_wrongly": behavioural,
        "classification": ("CORRECTED_BEHAVIORAL" if behavioural else
                           "CORRECTED_NON_BEHAVIORAL" if findings else "CLEAN"),
        "explanation": _explain(findings, behavioural),
    }


def _explain(findings: list, behavioural: list) -> str:
    if not findings:
        return "No motion's text and executable action disagreed."
    if not behavioural:
        return (f"{len(findings)} motion(s) had text and action that disagreed, and none of them "
                "executed. The problem never left the record.")
    acts = ", ".join(sorted({f["structured_action"].get("action_type", "") for f in behavioural}))
    targets = ", ".join(sorted({str(f["structured_action"].get("target")) for f in behavioural}))
    return (f"{len(behavioural)} motion(s) whose text described one act were executed as another ({acts} "
            f"addressed to {targets}). This reached canonical world state through "
            f"{', '.join(sorted({s for f in behavioural for s in f['touched_state']}))}.")


def _WorldView(world: dict):
    """Just enough of a World for the action grammar: it reads `names` and nothing else."""
    class View:
        pass
    view = View()
    view.names = world.get("names", {})
    view.month = world.get("month", 0)
    return view


def mark(store: RunStore, world: dict | None = None, write: bool = False) -> dict:
    """The correction record for a run. With write=False it only reports.

    The recorded log is never touched: the correction stands beside it, and a reader can see both
    what the run did and what it should have done.
    """
    report = audit(store, world)
    if world is None:
        world = store.load_checkpoint()[0].to_dict()
    history = world.get("history", [])
    clean_month = _last_clean_month(report, history)
    record = {
        "kind": "behavioural_integrity",
        "run": report["run"],
        "classification": report["classification"],
        "explanation": report["explanation"],
        "recorded_history_preserved": True,
        "findings": report["findings"],
        "last_clean_month": clean_month,
        "replay": replay_plan(store, clean_month),
        "caveat": ("The run's own statements, motions, votes and results are unchanged. This file reports "
                   "what the engine did and what it should have done; it does not alter either."),
    }
    if write:
        (store.path / "correction.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return record


def _last_clean_month(report: dict, history: list) -> int:
    """The last month before the earliest wrongly-executed motion."""
    months = [f["month"] for f in report["executed_wrongly"] if f["month"] is not None]
    if not months:
        return (len(history) - 1) if history else 0
    return max(0, min(months) - 1)


def replay_plan(store: RunStore, up_to_month: int) -> dict:
    """How to rebuild the world state at the last clean month, deterministically.

    Replaying the recorded model answers through the engine reproduces the same world state without
    asking the models again. For stand-in seats the run is deterministic from its config alone.
    """
    try:
        cfg = store.read_json("config.json")
    except Exception:
        cfg = {}
    run = cfg.get("run", {})
    answers = [c for c in store.read_log("call") if c.get("month") is not None
               and c.get("month") <= up_to_month and c.get("raw")]
    seats = {s.get("label", ""): s.get("provider", "") for s in cfg.get("seats", [])}
    return {
        "from_month": 0,
        "to_month": up_to_month,
        "seed": run.get("seed"), "framing": run.get("framing"), "months_total": run.get("months"),
        "recorded_answers": len(answers),
        "live_seats": sorted({p for p in seats.values() if p not in ("scripted", "replay")}),
        "deterministic": not any(p not in ("scripted", "replay") for p in seats.values()),
        "how": ("Re-run the same config to month " + str(up_to_month + 1) +
                " with the recorded answers replayed in place of fresh model calls, then let the "
                "corrected engine continue. Stand-in runs reproduce exactly from the config alone; a "
                "run with live model seats is reproducible only from its recorded answers, since the "
                "models themselves are not deterministic."),
    }


def record_replay(store: RunStore, up_to_month: int | None = None, write: bool = True) -> dict:
    """Convenience: audit the run and write the correction record for the last clean month."""
    world = store.load_checkpoint()[0].to_dict()
    report = audit(store, world)
    if up_to_month is None:
        up_to_month = _last_clean_month(report, world.get("history", []))
    return mark(store, world, write=write)
