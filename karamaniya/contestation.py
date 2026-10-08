"""Neutral measurements of council agreement and late vote changes.

This module never tells a delegate to dissent. It measures whether dissent occurred, how
strong the majority was, and whether a delegate's final vote differed from the provisional
stance recorded after deliberation. It is deliberately separate from policy logic so these
metrics cannot change the simulated world.
"""
from __future__ import annotations

from collections import Counter
from math import log2

STANCE_TO_VOTE = {
    "support": "yes",
    "oppose": "no",
    "undecided": "abstain",
}


def vote_metrics(motion: dict) -> dict:
    """Return auditable agreement metrics for one resolved motion."""
    raw = motion.get("votes") or {}
    votes = [v for v in raw.values() if v in ("yes", "no", "abstain")]
    n = len(votes)
    counts = Counter(votes)
    yes, no, abstain = (counts.get(x, 0) for x in ("yes", "no", "abstain"))
    binary_n = yes + no
    dominant_binary = max(yes, no) / binary_n if binary_n else None
    margin = (yes - no) / binary_n if binary_n else None
    p = [count / n for count in (yes, no, abstain) if count]
    entropy = (-sum(x * log2(x) for x in p) / log2(3)) if n and len(p) > 1 else 0.0
    return {
        "motion": motion.get("id"),
        "proposer": motion.get("proposer"),
        "voters": n,
        "yes": yes,
        "no": no,
        "abstain": abstain,
        "yes_rate": round(yes / n, 4) if n else None,
        "no_rate": round(no / n, 4) if n else None,
        "abstain_rate": round(abstain / n, 4) if n else None,
        "strict_unanimous": bool(n) and len(counts) == 1,
        "yes_unanimous": bool(n) and yes == n,
        "no_unanimous": bool(n) and no == n,
        "contested": yes > 0 and no > 0,
        "binary_dominant_share": round(dominant_binary, 4) if dominant_binary is not None else None,
        "binary_margin": round(margin, 4) if margin is not None else None,
        "vote_entropy": round(entropy, 4),
        "polarization": round(4 * (yes / n) * (no / n), 4) if n else 0.0,
    }


def motion_records(motions: list[dict]) -> list[dict]:
    """Measure substantive, resolved motions only."""
    out = []
    for motion in motions or []:
        if not isinstance(motion, dict):
            continue
        if motion.get("void") or motion.get("withdrawn"):
            continue
        if not any(v in ("yes", "no", "abstain") for v in (motion.get("votes") or {}).values()):
            continue
        out.append(vote_metrics(motion))
    return out


def month_summary(motions: list[dict], revisions: dict | None = None) -> dict:
    """Record vote agreement plus revision-to-final vote changes for a month."""
    measured = motion_records(motions)
    decided = len(measured)
    yes_unanimous = sum(x["yes_unanimous"] for x in measured)
    no_unanimous = sum(x["no_unanimous"] for x in measured)
    strict = sum(x["strict_unanimous"] for x in measured)
    contested = sum(x["contested"] for x in measured)
    dominant = [x["binary_dominant_share"] for x in measured if x["binary_dominant_share"] is not None]
    margins = [abs(x["binary_margin"]) for x in measured if x["binary_margin"] is not None]
    entropy = [x["vote_entropy"] for x in measured]
    polarization = [x["polarization"] for x in measured]
    changes = stance_changes(motions, revisions or {})
    return {
        "motions": measured,
        "decided_motions": decided,
        "strict_unanimous_count": strict,
        "yes_unanimous_count": yes_unanimous,
        "no_unanimous_count": no_unanimous,
        "contested_count": contested,
        "unanimous_rate": round(strict / decided, 4) if decided else None,
        "yes_unanimous_rate": round(yes_unanimous / decided, 4) if decided else None,
        "no_unanimous_rate": round(no_unanimous / decided, 4) if decided else None,
        "contested_rate": round(contested / decided, 4) if decided else None,
        "mean_binary_dominant_share": round(sum(dominant) / len(dominant), 4) if dominant else None,
        "mean_abs_binary_margin": round(sum(margins) / len(margins), 4) if margins else None,
        "mean_vote_entropy": round(sum(entropy) / len(entropy), 4) if entropy else None,
        "mean_polarization": round(sum(polarization) / len(polarization), 4) if polarization else None,
        "stance_changes": changes,
    }


def stance_changes(motions: list[dict], revisions: dict) -> dict:
    """Compare each delegate's recorded Phase-1B stance with its final counted vote.

    A changed case is only a binary reversal (support to no or oppose to yes), or a clear
    movement from undecided to a binary vote. Conditional stances are reported separately
    because resolving a condition is not equivalent to changing one's mind.
    """
    records = []
    aligned = 0
    changed = 0
    conditional_resolutions = 0
    unrecorded = 0

    for motion in motions or []:
        if not isinstance(motion, dict) or motion.get("void") or motion.get("withdrawn"):
            continue
        for member, final in (motion.get("votes") or {}).items():
            if final not in ("yes", "no", "abstain"):
                continue
            rev = revisions.get(member) or {}
            stance = (rev.get("stances") or {}).get(motion.get("id"))
            if stance in STANCE_TO_VOTE:
                expected = STANCE_TO_VOTE[stance]
                if expected == final:
                    aligned += 1
                    status = "aligned"
                else:
                    changed += 1
                    status = "changed"
                records.append({
                    "member": member,
                    "motion": motion.get("id"),
                    "stance": stance,
                    "final_vote": final,
                    "status": status,
                })
            elif stance == "conditional":
                conditional_resolutions += 1
                records.append({
                    "member": member,
                    "motion": motion.get("id"),
                    "stance": "conditional",
                    "final_vote": final,
                    "status": "conditional_resolution",
                })
            else:
                unrecorded += 1

    denominator = aligned + changed
    return {
        "records": records,
        "aligned": aligned,
        "changed": changed,
        "conditional_resolutions": conditional_resolutions,
        "unrecorded": unrecorded,
        "binary_stance_alignment_rate": round(aligned / denominator, 4) if denominator else None,
        "binary_change_rate": round(changed / denominator, 4) if denominator else None,
    }


def run_summary(months: list[dict]) -> dict:
    """Aggregate the month-level measurements for saved-run analysis."""
    monthly = [r.get("vote_dynamics") for r in (months or [])
               if isinstance(r, dict) and r.get("vote_dynamics")]
    if not monthly:
        monthly = [month_summary(r.get("motions", []), r.get("revisions", {}))
                   for r in (months or []) if isinstance(r, dict)]

    decided = sum(int(m.get("decided_motions") or 0) for m in monthly)
    unanimous = sum(int(m.get("strict_unanimous_count") or 0) for m in monthly)
    yes_unanimous = sum(int(m.get("yes_unanimous_count") or 0) for m in monthly)
    no_unanimous = sum(int(m.get("no_unanimous_count") or 0) for m in monthly)
    contested = sum(int(m.get("contested_count") or 0) for m in monthly)
    all_changes = [x for m in monthly for x in (m.get("stance_changes", {}).get("records") or [])]
    binary = [m.get("stance_changes", {}) for m in monthly]
    aligned = sum(int(x.get("aligned") or 0) for x in binary)
    changed = sum(int(x.get("changed") or 0) for x in binary)
    conditional = sum(int(x.get("conditional_resolutions") or 0) for x in binary)
    dominant = [m["mean_binary_dominant_share"] for m in monthly if m.get("mean_binary_dominant_share") is not None]
    entropy = [m["mean_vote_entropy"] for m in monthly if m.get("mean_vote_entropy") is not None]
    polarization = [m["mean_polarization"] for m in monthly if m.get("mean_polarization") is not None]
    return {
        "decided_motions": decided,
        "strict_unanimous_count": unanimous,
        "yes_unanimous_count": yes_unanimous,
        "no_unanimous_count": no_unanimous,
        "contested_count": contested,
        "unanimous_rate": round(unanimous / decided, 4) if decided else None,
        "yes_unanimous_rate": round(yes_unanimous / decided, 4) if decided else None,
        "no_unanimous_rate": round(no_unanimous / decided, 4) if decided else None,
        "contested_rate": round(contested / decided, 4) if decided else None,
        "mean_binary_dominant_share": round(sum(dominant) / len(dominant), 4) if dominant else None,
        "mean_vote_entropy": round(sum(entropy) / len(entropy), 4) if entropy else None,
        "mean_polarization": round(sum(polarization) / len(polarization), 4) if polarization else None,
        "binary_stance_alignment_rate": round(aligned / (aligned + changed), 4)
        if aligned + changed else None,
        "binary_change_rate": round(changed / (aligned + changed), 4)
        if aligned + changed else None,
        "conditional_resolution_count": conditional,
        "change_records": len(all_changes),
    }
