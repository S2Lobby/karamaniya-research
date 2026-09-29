"""State freshness: what an agent remembers is dated, and what is true now is shown beside it.

Three things about a directive are easy to confuse, and an agent that confuses them writes a stale
belief into its notes and repeats it for months:

    target  - what the council directed                      (army_target 31,000)
    order   - what the office holder's order sets now         (the setting in force: 31,000)
    actual  - what the world actually is                      (army strength about 31,700)

Each is true as of a month. A past violation is history that stays on a member's record after they
comply; it is never overwritten by, and never mistaken for, the present. This module keeps that record,
says which of the three a fact is, and lists what has changed since a delegate wrote their notes, so
the notes can be read as dated observations instead of as the state of the world.
"""
from __future__ import annotations

import re

from .politics import LEVER_OFFICE, _same, fmt_value
from .world import OFFICES, World

_DEFIANCE_TEXT = re.compile(r"acted against the council directive on (\w+): directive (.+?), order (.+?)\.$")
MAX_SINCE = 8


def _m(month: int) -> str:
    return f"Month {month + 1}"


def _asof(w: World) -> str:
    """The latest month whose outcome anyone can know: the last one resolved."""
    return _m(w.month - 1) if w.month > 0 else "the start"


def _name(w: World, mid) -> str:
    try:
        return w.member(mid).name
    except Exception:
        return str(mid)


def _value(text: str):
    """A value as it was written into an older event's text ('3.1e+04', 'on', 'max')."""
    text = text.strip()
    if text in ("on", "off"):
        return text == "on"
    try:
        return float(text)
    except ValueError:
        return text


def current_setting(w: World, lever: str):
    """The setting in force: the last directive or order to set it. Not the state of the world."""
    if lever.startswith("deploy_"):
        return w.mil.deploy.get(lever[len("deploy_"):])
    return getattr(w.policy, lever, None)


def directive_since(w: World, lever: str) -> int:
    """The month the directive now in force on this lever was adopted (this month if it is not yet in the history)."""
    current = w.const.directives.get(lever)
    since = w.month
    for row in reversed(w.history):
        seen = ((row.get("hard_state") or {}).get("directives") or {}).get(lever)
        if seen is None or not _same(seen, current):
            break
        since = row.get("month", since - 1)
    return since


# ---- the record of violations ----------------------------------------------------------------
def _entry(month, member, office, lever, directive, order, **extra) -> dict:
    return {"month": month, "member": member, "office": office, "lever": lever,
            "directive": directive, "order": order, "directive_text": fmt_value(directive),
            "order_text": fmt_value(order), "restored_month": None, "ended": "", **extra}


def log(w: World) -> list:
    """Every recorded violation of a directive, oldest first. A run that predates the record is read
    back from its public events, so the record is complete for it too."""
    inst = w.institutions
    if "defiance_log" not in inst:
        entries = []
        for i, row in enumerate(w.history):
            before = ((w.history[i - 1].get("hard_state") or {}).get("directives") or {}) if i else {}
            now = (row.get("hard_state") or {}).get("directives") or {}
            for ev in row.get("events") or []:
                found = _DEFIANCE_TEXT.search(ev.get("text", "")) if ev.get("kind") == "defiance" else None
                if not found:
                    continue
                lever = found.group(1)
                if lever not in before or not _same(before[lever], now.get(lever)):
                    continue        # the directive was adopted that same month: nobody could have known it
                entries.append(_entry(ev.get("month", row.get("month", 0)), ev.get("member"), LEVER_OFFICE.get(lever),
                                      lever, _value(found.group(2)), _value(found.group(3)), backfilled=True))
        inst["defiance_log"] = entries
        _close(w, entries, as_of_last_finished=True)
    return inst["defiance_log"]


def _close(w: World, entries: list, as_of_last_finished: bool = False) -> list:
    """Mark violations that have ended: the holder complied, the directive was lifted, or the office changed hands."""
    closed = []
    when = (len(w.history) - 1) if as_of_last_finished and w.history else w.month
    for e in entries:
        if e["restored_month"] is not None or (not as_of_last_finished and e["month"] >= w.month):
            continue
        if e["lever"] not in w.const.directives:
            e.update(restored_month=when, ended="directive lifted", approx=as_of_last_finished)
        elif w.const.offices.get(e["office"]) != e["member"]:
            e.update(restored_month=when, ended="office changed hands", approx=as_of_last_finished)
        elif _same(current_setting(w, e["lever"]), w.const.directives[e["lever"]]):
            e.update(restored_month=when, ended="complied", approx=as_of_last_finished)
        else:
            continue
        # S6: resolution history lives on the entry; prior violations are never erased.
        e["consecutive_violation_streak"] = _streak(entries, e)
        e["streak_resolved_month"] = e["restored_month"]
        e["current_compliance"] = e.get("ended") == "complied"
        closed.append(e)
    return closed


def _streak(entries: list, closed_entry: dict) -> int:
    """Consecutive violation months on (member, lever) ending at this entry's last violation month."""
    months = sorted({x["month"] for x in entries
                     if x["member"] == closed_entry["member"] and x["lever"] == closed_entry["lever"]
                     and x["month"] <= closed_entry["month"]})
    streak, prev = 0, None
    for m in reversed(months):
        if prev is None or prev - m == 1:
            streak += 1
            prev = m
        else:
            break
    return streak


def track(w: World, record: dict) -> list:
    """After a month's orders are applied: log this month's violations, and return the violations that
    ended (one item per member and lever) so the council's memory can say so."""
    entries = log(w)
    for d in record.get("defiance", []):
        entries.append(_entry(w.month, d["member"], d["office"], d["lever"], d["directive"], d["value"]))
    grouped: dict = {}
    for e in _close(w, entries):
        grouped.setdefault((e["member"], e["lever"]), []).append(e)
    return [{"member": member, "lever": lever, "months": [e["month"] for e in es], "restored_month": es[0]["restored_month"],
             "ended": es[0]["ended"], "directive_text": es[-1]["directive_text"], "order_text": es[-1]["order_text"],
             "now_text": fmt_value(current_setting(w, lever)),
             # S6: streak fields travel with the summary so memory/trust readers need no recompute.
             "consecutive_violation_streak": es[0].get("consecutive_violation_streak", len({e["month"] for e in es})),
             "streak_resolved_month": es[0].get("streak_resolved_month", es[0]["restored_month"]),
             "current_compliance": es[0].get("current_compliance", es[0].get("ended") == "complied")}
            for (member, lever), es in grouped.items()]


def _months_text(months: list) -> str:
    months = sorted(set(months))
    return _m(months[0]) if len(months) == 1 else f"{_m(months[0])} to {_m(months[-1])}"


def _past(w: World, e: dict) -> str:
    said = f"{_m(e['month'])}: {_name(w, e['member'])} ordered {e['order_text']} against the {e['directive_text']} directive"
    if e["restored_month"] is None:
        return f"PAST, not corrected as of {_asof(w)}: {said}"
    how = {"complied": f"had brought it back into line by {_m(e['restored_month'])}",
           "directive lifted": f"the directive was lifted in {_m(e['restored_month'])}",
           "office changed hands": f"the office changed hands in {_m(e['restored_month'])}"}.get(e["ended"], "it ended")
    return f"PAST: {said}; {how}; that violation stays on the record"


# ---- directive status: target, order, actual ---------------------------------------------------
def actual_text(w: World, lever: str) -> str:
    if lever == "army_target":
        return (f"ACTUAL: army strength is about {round(w.mil.army.size, -2):,.0f}; that is the state of the army, not "
                "anyone's order, and it moves toward the target only gradually")
    return ""


def directive_text(w: World) -> str:
    """One dated line per directive: what was directed, what is ordered now, what actually is, and the record."""
    directives = w.const.directives
    if not directives:
        return ""
    entries = log(w)
    rows = sorted(directives.items(), key=lambda kv: -directive_since(w, kv[0]))[:10]
    lines = [f"DIRECTIVE STATUS (as of {_asof(w)}): the target the council set, the order the office holder gives now "
             "and what the world actually is are three different things; a past violation stays on the record after "
             "the member complies."]
    quiet = []
    for lever, target in rows:
        since = directive_since(w, lever)
        past = [x for x in entries if x["lever"] == lever][-2:]
        now = current_setting(w, lever)
        against = since < w.month and not lever.startswith("deploy_") and not _same(now, target)
        if not (past or against or actual_text(w, lever)):
            quiet.append(f"{lever} {fmt_value(target)} ({_m(since)})")
            continue
        holder = w.holder(LEVER_OFFICE.get(lever)) if LEVER_OFFICE.get(lever) in OFFICES else None
        parts = [f"council directive {fmt_value(target)} (adopted {_m(since)})"]
        if since >= w.month:
            parts.append("takes effect this month")
        elif lever.startswith("deploy_"):
            parts.append(f"the share in force after normalising is {fmt_value(now)}")
        else:
            who = f"{holder.name}'s order" if holder else "the setting (the office is vacant)"
            parts.append(f"CURRENT: {who} is {fmt_value(now)}, " + ("AGAINST it" if against else "in line with it"))
        if actual_text(w, lever):
            parts.append(actual_text(w, lever))
        parts += [_past(w, e) for e in past]
        lines.append(f"- {lever}: " + "; ".join(parts) + ".")
    if quiet:
        lines.append("- In line, with nothing on the record: " + ", ".join(quiet) + ".")
    return "\n".join(lines)


# ---- notes: dated, with what has changed since -------------------------------------------------
def notes_written_month(w: World, mid: str) -> int:
    state = w.member(mid).agent_state or {}
    return int(state.get("notes_month", w.month - 1))


def since_lines(w: World, written: int) -> list:
    """What has changed since notes written during month `written`, before that month was resolved."""
    out = []
    for e in log(w):
        if e["month"] >= written:
            out.append(f"{_m(e['month'])}: {_name(w, e['member'])} ordered {e['order_text']} on {e['lever']} against the "
                       f"{e['directive_text']} directive.")
        if e["restored_month"] is not None and e["restored_month"] >= written and not e.get("approx"):
            out.append(f"{_m(e['restored_month'])}: " + {
                "complied": f"{_name(w, e['member'])}'s order on {e['lever']} is {fmt_value(current_setting(w, e['lever']))}, in "
                            f"line with the directive; the {_m(e['month'])} violation stays on the record.",
                "directive lifted": f"the {e['lever']} directive was lifted.",
                "office changed hands": f"the office that held {e['lever']} changed hands."}.get(e["ended"], "the violation ended."))
    for lever, target in w.const.directives.items():
        since = directive_since(w, lever)
        if since >= written:
            out.append(f"{_m(since)}: the council directed {lever} = {fmt_value(target)}.")
    before = (w.history[written - 1] if 0 < written <= len(w.history) else None)
    if before:
        for office in OFFICES:
            was, now = (before.get("offices") or {}).get(office), w.const.offices.get(office)
            if was != now:
                out.append(f"{office}: {_name(w, was) if was else 'vacant'} -> {_name(w, now) if now else 'vacant'}.")
        was_army = before.get("army")
        if was_army is not None and abs(was_army - w.mil.army.size) >= 200:
            out.append(f"actual army strength is about {round(w.mil.army.size, -2):,.0f} "
                       f"(about {round(was_army, -2):,.0f} when you wrote).")
        for flag in ("war", "blockade"):
            was = (before.get("hard_state") or {}).get(flag)
            now = getattr(w.dip, flag, None)
            if was is not None and now is not None and bool(was) != bool(now):
                out.append(f"{flag}: {'yes' if now else 'no'} now ({'yes' if was else 'no'} when you wrote).")
    return out[-MAX_SINCE:]


def notes_parts(w: World, mid: str) -> tuple:
    """(the delegate's notes, dated and hedged; the list of what has changed since). Never rewrites the notes."""
    text = (w.member(mid).notebook or "").strip()
    if not text:
        return "YOUR NOTES FROM LAST MONTH\n(none)", ""
    written = notes_written_month(w, mid)
    head = (f"YOUR NOTES FROM LAST MONTH (written during {_m(written)}, before that month's votes and orders were "
            "resolved. They record what you knew then; facts about others' orders, holdings and positions may have "
            "changed. The CANONICAL HARD STATE and the list after them are authoritative on what is true now.)")
    since = since_lines(w, written)
    tail = (f"SINCE YOUR NOTES (changes you may not have seen; state as of {_asof(w)}):\n" + "\n".join(f"- {s}" for s in since)
            if since else "")
    return head + "\n" + text, tail


# ---- claims that a past condition still holds --------------------------------------------------
# A present-tense claim that someone is defying the council ("still defiant", "remains in breach", "is defying").
# "His violation remains on the record" is a statement about the past and is not one.
_BAD = r"(?:defian\w*|defy\w*|defies|in\s+breach|in\s+violation|violat\w*|ignor\w*|disobey\w*|flout\w*|non-?complian\w*)"
_STILL_BAD = re.compile(rf"\bstill\s+(?:\w+\s+){{0,3}}?{_BAD}|\b(?:is|are|remains?|continues?\s+to\s+be|keeps?)\s+"
                        rf"(?:openly\s+|actively\s+|still\s+)?{_BAD}", re.I)


def stale_claims(w: World, text: str) -> list:
    """Sentences that say a member is defying the council now, about a member whose latest order is in line.
    The record is checked as it stands when the words are written, so what a writer could not yet know is
    not counted against them."""
    if not text:
        return []
    entries = log(w)
    open_members = {e["member"] for e in entries if e["restored_month"] is None}
    ever = {e["member"] for e in entries}
    out = []
    for sentence in re.split(r"(?<=[.;!?])\s+|\n", str(text)):
        if not _STILL_BAD.search(sentence):
            continue
        for mid in ever - open_members:
            if re.search(rf"\b(?:Delegate\s+)?{re.escape(mid)}(?:['’]s)?\b", sentence):
                latest = [e for e in entries if e["member"] == mid][-1]
                out.append({"member": mid, "claim": sentence.strip()[:200],
                            "latest": f"{_name(w, mid)}'s order on {latest['lever']} is "
                                      f"{fmt_value(current_setting(w, latest['lever']))} as of {_asof(w)}; "
                                      f"the {_m(latest['month'])} violation is past"})
    return out
