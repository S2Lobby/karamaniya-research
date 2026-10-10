"""How the public takes what the government does, for some months after it does it (engine 17).

A reaction is a monthly modifier on the people (the kinds society reads: approval, grievance, indep,
fear, repression), aimed at everyone ("*"), at one region ("kessel"), or at one identity
("ident:karamanian"), and it lasts a number of months. The society step folds the modifiers in through
dilemmas.apply_ongoing, as it does for live issues and regional status, so a run in which nothing
reacts is unchanged.

In run 20261010-070501-seed1 the council invited the Union into a joint inquiry over a border shooting
and twice asked the country whether it wanted to stay independent, and nobody reacted: those acts had no
effect on anyone. The mechanisms that make them land (fine_print.py, the referendum) put their public
side here.
"""
from __future__ import annotations

from .world import World

KINDS = ("approval", "grievance", "indep", "fear", "repression")
IDENTITIES = ("karamanian", "imperial", "vell")
LIMIT = .03            # no single reaction moves a monthly modifier further than this (society multiplies by 4)


def state(w: World) -> list:
    return w.institutions.setdefault("public_reactions", [])


def react(w: World, kind: str, where: str, value: float, months: int, reason: str, decay: float = 1.0) -> dict | None:
    """Record a public reaction. `value` is the monthly modifier (society multiplies it by four for the
    target the group moves toward), `months` how many monthly steps it lasts, and `decay` what is left of
    it after each one. Returns the entry, or None when it would do nothing."""
    if kind not in KINDS or months <= 0 or abs(value) < 1e-9:
        return None
    if where.startswith("ident:") and where[6:] not in IDENTITIES:
        return None
    if where != "*" and not where.startswith("ident:") and not any(r.id == where for r in w.regions):
        return None
    entry = {"kind": kind, "where": where, "value": round(max(-LIMIT, min(LIMIT, value)), 5),
             "months_left": int(months), "decay": float(decay), "reason": str(reason)[:160], "month": w.month}
    state(w).append(entry)
    return entry


def effects(w: World, add) -> None:
    """This month's modifiers from live reactions, for dilemmas.apply_ongoing to fold in. Each reaction is
    applied once a month and then aged."""
    live = []
    for entry in state(w):
        if entry["months_left"] <= 0:
            continue
        add(entry["kind"], entry["where"], entry["value"])
        entry["months_left"] -= 1
        entry["value"] = round(entry["value"] * entry.get("decay", 1.0), 5)
        if entry["months_left"] > 0 and abs(entry["value"]) >= 1e-6:
            live.append(entry)
    w.institutions["public_reactions"] = live


def active(w: World, reason_prefix: str = "") -> list:
    """Reactions still running, optionally only those whose reason starts with `reason_prefix`."""
    return [x for x in state(w) if x["months_left"] > 0 and str(x.get("reason", "")).startswith(reason_prefix)]
