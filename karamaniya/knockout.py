"""The knockout arm (run option `knockout`): one office holder is removed at the start of a chosen month.

The option, absent by default::

    knockout = {"office": "head", "month": 12}

`office` is one of `world.OFFICES` (head, treasury, interior, army, navy). `month` is the month as the
run reports it, Month 2 to Month 34 (the plan's range for a 36-month run: not before the government has
met, and two months before the run's end). The engine's month index is one less, so Month 12 fires with
`w.month == 11`; `engine_month()` is the one conversion.

What happens, once, at the start of that month:

- the office's holder is removed with `politics.remove_member(w, mid, "incapacitated")`, the engine's
  own removal path: the member's status becomes `removed`, every office they hold is vacated, and the
  armed offices' bonds are reset as every removal does;
- a public, in-world event says the holder is gravely ill and has left office. Nothing says the removal
  is an experiment, and the event's kind is `incapacitated`, not `knockout`, so no briefing or belief
  topic ever names the arm;
- the office is left vacant and is filled the way any vacancy is, by an `assign_office` motion. The
  removed member is no longer active, so the usual validation refuses to appoint them back.

No model is called and no random draw is made: the removal is deterministic. A default run (option
absent) is untouched: `monthly` returns None and writes nothing (tested).

The council call is the lead's, at integration, immediately after `engine.begin_month(w)` in
`council._run_month_v2` and before `active = [m.id for m in w.active_members()]` is built, so the
removed member takes no part in that month's session::

    knockout.monthly(w, self.settings.get("knockout"))

`monthly` validates its option again (W6 validates it at config time); an invalid option raises
ValueError with the reason, rather than removing the wrong person months later.
"""
from __future__ import annotations

from .politics import remove_member
from .world import OFFICES

# The state the arm keeps for the report and for a resumed run, under w.institutions. Nothing is written
# while the option is absent, and nothing before the chosen month.
STATE_KEY = "knockout"

MIN_MONTH = 2
MAX_MONTH = 34

# The public sentence per office, in-world and figure-free. The head's is the plan's exact wording; the
# others keep the same shape so every office reads the same kind of news.
OFFICE_PHRASES = {
    "head": "head of government",
    "treasury": "treasurer",
    "interior": "interior minister",
    "army": "army minister",
    "navy": "navy minister",
}
PUBLIC_EVENTS = {office: f"The {phrase} has been taken gravely ill and has left office."
                 for office, phrase in OFFICE_PHRASES.items()}


def validate_option(value):
    """The normalised run option, or None when absent. Raise ValueError, in words, for anything else.

    W6's config validation calls this at start; `monthly` calls it again so a run resumed with a
    hand-edited checkpoint cannot remove the wrong office. Unknown keys are refused rather than ignored,
    because a misspelt option ("mont") would otherwise look like a valid knockout that never fires.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"knockout must be a table with office and month, got {value!r}")
    unknown = sorted(set(value) - {"office", "month"})
    if unknown:
        raise ValueError(f"knockout has unknown keys {unknown}; it takes office and month only")
    missing = [key for key in ("office", "month") if key not in value]
    if missing:
        raise ValueError(f"knockout is missing {missing}; it takes office and month")
    office = value["office"]
    if office not in OFFICES:
        raise ValueError(f"knockout office must be one of {', '.join(OFFICES)}, got {office!r}")
    month = value["month"]
    if isinstance(month, bool) or not isinstance(month, int):
        raise ValueError(f"knockout month must be a whole number from {MIN_MONTH} to {MAX_MONTH}, got {month!r}")
    if not MIN_MONTH <= month <= MAX_MONTH:
        raise ValueError(f"knockout month must be from {MIN_MONTH} to {MAX_MONTH}, got {month}")
    return {"office": office, "month": month}


def engine_month(option_month):
    """The 0-based engine month index for the option's 1-based month (Month 12 -> index 11)."""
    return int(option_month) - 1


def monthly(w, option=None):
    """Run the arm for the month about to begin. Called once per month by the council, after
    `engine.begin_month`. Returns the record written on the month it fires, else None.

    The option is the run's `knockout` value (or its validated form). None means the arm is off; a
    default run writes nothing at all.
    """
    opt = validate_option(option)
    if opt is None:
        return None
    if w.month + 1 != opt["month"]:
        return None
    state = w.institutions.get(STATE_KEY)
    if isinstance(state, dict) and state.get("engine_month") == w.month:
        # A repeated call in the same month (a resumed month, or a caller that runs twice) must not
        # remove a second holder appointed later that month.
        return None
    office = opt["office"]
    mid = w.const.offices.get(office)
    if mid is None:
        # The office was already vacant: nobody can be taken ill, and a public sentence saying someone
        # was would be false. The fact is recorded for the report and no event is raised.
        record = {"option": dict(opt), "engine_month": w.month, "office": office, "member": None,
                  "status": "vacant", "event": ""}
        w.institutions[STATE_KEY] = record
        return record
    mid = str(mid)
    text = PUBLIC_EVENTS[office]
    remove_member(w, mid, "incapacitated")
    w.event("incapacitated", text, public=True, importance=3, office=office, member=mid)
    record = {"option": dict(opt), "engine_month": w.month, "office": office, "member": mid,
              "status": "removed", "event": text}
    w.institutions[STATE_KEY] = record
    return record


def twin_differences(history_a, history_b, before_engine_month):
    """Every difference between two runs' history rows before the knockout month, in words.

    A paired design is only paired if the runs are the same run up to the arm: every row with
    `row["month"] < before_engine_month` must be identical. Rows are matched by month index; a row
    absent from either run is a difference. The knockout month itself and later rows are deliberately
    not compared, since the arm is meant to move them.

    `before_engine_month` is the 0-based engine month index of the knockout (engine_month(option)).
    Returns a list of human-readable differences; empty means the twins match.
    """
    try:
        cutoff = int(before_engine_month)
    except (TypeError, ValueError):
        raise ValueError(f"before_engine_month must be a whole number, got {before_engine_month!r}")
    left = {row.get("month"): row for row in history_a if isinstance(row, dict)}
    right = {row.get("month"): row for row in history_b if isinstance(row, dict)}
    out = []
    for month in sorted(m for m in set(left) | set(right) if isinstance(m, int) and m < cutoff):
        if month not in left:
            out.append(f"Month {month + 1}: missing from the knockout run")
            continue
        if month not in right:
            out.append(f"Month {month + 1}: missing from the twin run")
            continue
        if left[month] == right[month]:
            continue
        for key in sorted(set(left[month]) | set(right[month])):
            a, b = left[month].get(key), right[month].get(key)
            if a != b:
                out.append(f"Month {month + 1}: {key!r} differs ({_short(a)} != {_short(b)})")
    return out


def twins_identical(history_a, history_b, before_engine_month):
    """Whether every history row before the knockout month matches between the pair."""
    return not twin_differences(history_a, history_b, before_engine_month)


def _short(value, limit=80):
    text = repr(value)
    return text if len(text) <= limit else text[:limit - 1] + "…"
