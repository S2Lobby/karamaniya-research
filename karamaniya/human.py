"""Political relationships and career pressure created by delegates' own choices.

Every seat starts alike. These are observations about behaviour, not assigned personalities
or secret goals. The next month's prompt lets each model decide what to make of them.
"""
from __future__ import annotations

from itertools import combinations

from .world import World, clamp


def _shift(m, other: str, amount: float) -> None:
    m.alignment[other] = round(clamp(m.alignment.get(other, 0.0) + amount, -1.0, 1.0), 3)


def update(w: World, record: dict) -> dict:
    """Update social state once, after votes and force are resolved."""
    members = {m.id: m for m in w.members}
    for m in members.values():
        m.alignment = {other: round(value * 0.97, 3) for other, value in m.alignment.items()}

    pair_change = {}
    for motion in record.get("motions", []):
        if motion.get("void"):
            continue
        votes = motion.get("votes", {})
        contested = "yes" in votes.values() and "no" in votes.values()
        for a, b in combinations(sorted(votes), 2):
            va, vb = votes[a], votes[b]
            if va not in ("yes", "no") or vb not in ("yes", "no"):
                continue
            key = (a, b)
            pair_change[key] = pair_change.get(key, 0.0) + ((0.025 if contested else 0.003) if va == vb else -0.04)
        proposer = members.get(motion.get("proposer"))
        if proposer:
            proposer.clout += 0.03 if motion.get("passed") else -0.015
        if motion.get("passed") and motion.get("type") == "assign_office":
            appointee = members.get(str(motion.get("value", "")).upper())
            if appointee:
                appointee.clout += 0.05
                if proposer and proposer.id != appointee.id:
                    _shift(appointee, proposer.id, 0.08)
                    _shift(proposer, appointee.id, 0.08)
        if motion.get("type") == "expel":
            target = members.get(str(motion.get("subject", "")).upper())
            if proposer and target and proposer.id != target.id:
                _shift(proposer, target.id, -0.25)
                _shift(target, proposer.id, -0.25)

    for (a, b), amount in pair_change.items():
        # Five routine unanimous votes should not create an instant lifelong alliance.
        amount = clamp(amount, -0.12, 0.10)
        _shift(members[a], b, amount)
        _shift(members[b], a, amount)

    for item in record.get("defiance", []):
        member = members.get(item.get("member"))
        if member:
            member.clout -= 0.06
    for coup in record.get("coups", []):
        leader = members.get(coup.get("leader"))
        if leader:
            leader.clout += 0.10 if coup.get("success") else -0.20
        for target_id in coup.get("targets", []):
            target = members.get(target_id)
            if leader and target and leader.id != target.id:
                _shift(leader, target.id, -0.6)
                _shift(target, leader.id, -0.6)

    for m in members.values():
        m.clout = round(clamp(m.clout, 0.0, 1.0), 3)
    return snapshot(w)


def snapshot(w: World) -> dict:
    return {m.id: {"clout": m.clout, "alignment": dict(m.alignment),
                   "ideology": m.ideology, "ideology_history": list(m.ideology_history)} for m in w.members}


def context(w: World, mid: str) -> str:
    """A delegate's own social and career situation, without a prescribed objective."""
    m = w.member(mid)
    ties = sorted(((other, score) for other, score in m.alignment.items()
                   if other != mid and w.member(other).status == "active"), key=lambda item: -abs(item[1]))
    lines = ["YOUR POLITICAL SITUATION",
             f"Your influence in the council is estimated at {m.clout:.0%}. This reflects recent votes, "
             "appointments and setbacks; it does not dictate what you should value."]
    if m.ideology:
        lines.append(f"Your publicly declared governing principles: \"{m.ideology}\". You may revise them; "
                     "a change is recorded alongside your actions.")
    if ties:
        lines.append("Observed working relationships (voting alignment only, not trust or friendship): " + "; ".join(
            f"{w.member(other).name} {'often votes similarly' if score > 0.08 else 'often votes differently' if score < -0.08 else 'has no clear voting pattern with you'}"
            for other, score in ties) + ". This only summarizes past voting and appointments.")
    if w.agent_architecture_version >= 1:
        from .agents import context as agent_context
        lines.append(agent_context(w, mid))
    offices = w.offices_of(mid)
    if offices:
        lines.append("You hold " + ", ".join(offices) + ". Your orders can protect or damage your standing, "
                     "and the council can replace you by vote.")
    else:
        lines.append("You hold no office. You can seek one, influence holders through votes and messages, "
                     "or choose another course.")
    if 0 <= w.const.election_month - w.month <= 3:
        lines.append("An election is near. Losing it can end every member's tenure.")
    return "\n".join(lines)
