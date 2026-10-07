"""Opt-in ways of spending fewer tokens on the council, and the settings that switch them on.

Every one of them changes what a delegate is sent or when it is asked, so every one is OFF by default
and a run without a `[run.tokens]` table is engine 5 exactly: tests/test_prompt_freeze.py holds the
prompts of a default run to recorded fingerprints. A run that turns one on records it in config.json
and in the manifest (`token_saving`), and manifest.divergences() names it, so a run with a feature on
is never compared with one without as if they were alike.

    [run.tokens]
    layout = "cache_friendly"   # classic | cache_friendly
    schema_hint = "auto"        # example | compact | auto
    briefing = "on_demand"      # full | on_demand
    wakeups = "on_events"       # always | on_events
    max_quiet_months = 3        # with wakeups = "on_events": longest run of quiet months in a row

    [run]
    foreign_cabinet_backend = { provider = "ollama", model = "qwen3.5:9b" }   # one fixed model for both

    [[seat]]
    effort_by_phase = { decision = "high", session = "low", revision = "low" }

What each one does, and what it was measured to save, is in docs/TOKEN_EFFICIENCY.md.
"""
from __future__ import annotations

import math

DEFAULTS = {
    "layout": "classic",
    "schema_hint": "example",
    "briefing": "full",
    "wakeups": "always",
    "max_quiet_months": 3,
}
CHOICES = {
    "layout": ("classic", "cache_friendly"),
    "schema_hint": ("example", "compact", "auto"),
    "briefing": ("full", "on_demand"),
    "wakeups": ("always", "on_events"),
}
#: The phases a seat's effort_by_phase may name: the `phase` every model call is made with.
PHASES = ("session", "revision", "decision", "survey", "founding_diagnosis", "formation_proposal",
          "formation_vote", "motion_repair", "principles_repair", "foreign")


def validate(raw) -> dict:
    """A `[run.tokens]` table, checked. Keeps only what was set: the defaults stay implicit."""
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ValueError("[run.tokens] must be a table")
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"[run.tokens] has unknown settings: {sorted(unknown)}; known: {sorted(DEFAULTS)}")
    out = {}
    for key, value in raw.items():
        if key in CHOICES:
            if value not in CHOICES[key]:
                raise ValueError(f"tokens.{key} must be one of {CHOICES[key]}, not {value!r}")
            out[key] = value
        elif key == "max_quiet_months":
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 12:
                raise ValueError("tokens.max_quiet_months must be a whole number from 1 to 12")
            out[key] = value
    return out


def settings(run: dict | None) -> dict:
    """Every setting with its value for this run, defaults filled in."""
    return {**DEFAULTS, **validate((run or {}).get("tokens"))}


def validate_effort_by_phase(table, where: str = "seat") -> dict:
    if not isinstance(table, dict):
        raise ValueError(f"{where}: effort_by_phase must be a table of phase = effort")
    unknown = set(table) - set(PHASES)
    if unknown:
        raise ValueError(f"{where}: effort_by_phase names unknown phases {sorted(unknown)}; known: {list(PHASES)}")
    return {phase: str(value) for phase, value in table.items()}


def validate_foreign_backend(raw) -> dict:
    if not isinstance(raw, dict) or not raw.get("provider"):
        raise ValueError("foreign_cabinet_backend must be a table with at least a provider")
    out = dict(raw)
    out["label"] = str(out.get("label") or out.get("model") or out["provider"]).strip()
    return out


# ---- briefing on demand -----------------------------------------------------------------------------
#: Sections sent in full every month whatever a delegate asked for: what the council itself decided
#: is the record a delegate acts on, not background reading, and the foreign governments' messages
#: are addressed to the council and gone the month after (a request only brings next month's).
ALWAYS_FULL = ("last_months_council_decisions", "foreign_messages")


def _slug(heading: str) -> str:
    head = heading.split(":")[0].split("(")[0].replace("'", "").replace("’", "")
    words = "".join(ch.lower() if ch.isalnum() else " " for ch in head)
    return "_".join(words.split())[:48] or "section"


def briefing_sections(brief: str) -> list:
    """The public briefing as [(id, heading, text)]. The first block (the title, declared principles,
    who has left the government) is the header and has the id "header"."""
    out, seen = [], set()
    for i, block in enumerate(b for b in brief.split("\n\n") if b.strip()):
        heading = block.strip().splitlines()[0]
        sid = "header" if i == 0 else _slug(heading)
        while sid in seen:
            sid += "_2"
        seen.add(sid)
        out.append((sid, heading, block))
    return out


def requestable(brief: str) -> list:
    """The section ids a delegate can ask to read in full next month."""
    return [sid for sid, _, _ in briefing_sections(brief) if sid != "header" and sid not in ALWAYS_FULL]


def briefing_for(brief: str, requested) -> tuple[str, str]:
    """(shared part, this delegate's part) of an on-demand briefing.

    The shared part is the same for every delegate: the header, the sections always sent in full, and
    one headline line for each of the others. The delegate's own part is the full text of the sections
    it asked for last month. Nothing is summarised by a model: a headline is the section's own first
    line, cut short."""
    requested = set(requested or ())
    shared, own = [], []
    index = []
    for sid, heading, text in briefing_sections(brief):
        if sid == "header" or sid in ALWAYS_FULL:
            shared.append(text)
            continue
        lines = text.strip().splitlines()
        teaser = (" | " + lines[1].strip()) if len(lines) > 1 else ""
        index.append(f"- [{sid}] {heading[:90]}{teaser[:110]} ({len(lines)} lines)")
        if sid in requested:
            own.append(text)
    if index:
        shared.append("OTHER BRIEFING SECTIONS (headlines only: name any in read_next_month to receive them in full "
                      "next month)\n" + "\n".join(index))
    return "\n\n".join(shared), ("THE BRIEFING SECTIONS YOU ASKED FOR\n\n" + "\n\n".join(own)) if own else ""


def read_requests(data, options) -> list:
    """The section ids a decision asked for, kept only if they exist. A seat whose connector does not
    hold it to the schema can send anything here, so anything but a known id is dropped."""
    raw = (data or {}).get("read_next_month") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    known = set(options or ())
    return list(dict.fromkeys(x for x in raw if isinstance(x, str) and x in known))


# ---- quiet months -------------------------------------------------------------------------------------
#: What a delegate may name as a reason to be woken: the state readings conditions already test.
WAKE_METRICS = ("food_ratio", "reserves", "arrears", "unemployment", "army_morale", "inflation", "approval",
                "deficit")


def read_stand_by(data, tokens: dict) -> dict:
    """A decision's stand_by answer, checked: {"months": n, "wake_if": [canonical conditions]}."""
    from .motion_actions import canonical_metric_value
    raw = (data or {}).get("stand_by") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {"months": 0, "wake_if": []}
    try:
        months = int(str(raw.get("months", "0")).strip())
    except ValueError:
        months = 0
    months = max(0, min(months, int(tokens.get("max_quiet_months", 3))))
    wake = []
    conditions = raw.get("wake_if")
    for cond in conditions if isinstance(conditions, list) else []:
        if not isinstance(cond, dict) or cond.get("metric") not in WAKE_METRICS or cond.get("operator") not in (">=", "<="):
            continue
        try:
            number = float(cond.get("value"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        value = canonical_metric_value(cond["metric"], number)
        wake.append({"metric": cond["metric"], "operator": cond["operator"], "value": value})
    return {"months": months, "wake_if": wake[:3]}


def extend_decision_schema(schema: dict, tokens: dict, read_options) -> dict:
    """The decision schema with the fields the switched-on features need, and nothing otherwise."""
    from .actions import _arr, _obj
    added = {}
    if tokens.get("wakeups") == "on_events":
        added["stand_by"] = _obj({
            "months": {"type": "string", "enum": [str(i) for i in range(int(tokens.get("max_quiet_months", 3)) + 1)]},
            "wake_if": _arr(_obj({"metric": {"type": "string", "enum": list(WAKE_METRICS)},
                                  "operator": {"type": "string", "enum": [">=", "<="]},
                                  "value": {"type": "number"}}), 3)})
    if tokens.get("briefing") == "on_demand" and read_options:
        added["read_next_month"] = _arr({"type": "string", "enum": list(read_options)}, len(read_options))
    if not added:
        return schema
    out = dict(schema)
    out["properties"] = {**(schema.get("properties") or {}), **added}
    if "required" in schema:
        out["required"] = list(schema["required"]) + [k for k in added if k not in schema["required"]]
    return out


def decision_addendum(tokens: dict) -> str:
    """What the decision instructions add for the switched-on features ("" when none is on)."""
    parts = []
    if tokens.get("wakeups") == "on_events":
        parts.append(
            "stand_by: how many coming months you are content for the council not to meet, if nothing in your "
            "wake_if list happens (\"0\" = meet next month as usual). The council skips a month only when every "
            "delegate stands by and no one's wake_if condition holds; it always meets for an election, a "
            "handover, war, a coup, a resignation, a message from abroad, a deferred motion, an unread "
            "private message or dispatch, an answer to an information request, a new issue or a major "
            "public event. In a month it does not meet, policy and office orders stay as they are.")
    if tokens.get("briefing") == "on_demand":
        parts.append(
            "read_next_month: the briefing sections you want in full next month. The others arrive as one-line "
            "headlines; your council's own decisions always arrive in full.")
    return ("\n" + "\n".join(parts)) if parts else ""


def quiet_month_due(w, active: list, carried: list, pending_dms: bool, last_record: dict | None,
                    tokens: dict) -> dict | None:
    """Whether the council may skip this month: every reason it must meet, checked. None means meet.

    Returns the record of who stood by and what was checked, for the month's log, when it may skip."""
    from .motion_actions import evaluate_conditions
    if tokens.get("wakeups") != "on_events" or w.month < 1 or not active:
        return None
    c = w.const
    if c.election_month == w.month or c.handover_month == w.month or w.dip.war or w.dip.proposals:
        return None
    if carried or pending_dms:
        return None
    # Anything addressed to the council that only this month's meeting would read: messages from the
    # foreign governments, private dispatches, and answers to information requests due this month.
    # Each is cleared or past its delivery month by the next one, so a quiet month would lose it unread.
    if w.dip.inbox or w.dip.private_inbox:
        return None
    from . import intelligence
    if any(intelligence.deliveries_for(w, mid) for mid in active):
        return None
    if last_record and last_record.get("coups"):
        return None
    if any(m.status != "active" and getattr(m, "removed_month", -99) == w.month - 1 for m in w.members):
        return None             # someone left the government last month
    if any(d.get("month") == w.month for d in (w.dilemmas or {}).get("active", [])):
        return None             # a new issue reaches the agenda this month
    if any(ev.get("public", True) and float(ev.get("importance") or 0) >= 3 for ev in w.last_events or []):
        return None             # last month made headlines: a public event of the engine's top importance
    if int(w.counters.get("quiet_months_in_a_row", 0)) >= int(tokens.get("max_quiet_months", 3)):
        return None
    standing_by = {}
    for mid in active:
        plan = (w.member(mid).agent_state or {}).get("stand_by") or {}
        if int(plan.get("months_left", 0)) < 1:
            return None
        wake = plan.get("wake_if") or []
        if wake and any(r.get("met") for r in evaluate_conditions(w, wake)):
            return None
        standing_by[mid] = {"months_left": int(plan["months_left"]), "wake_if": wake}
    return {"standing_by": standing_by, "in_a_row": int(w.counters.get("quiet_months_in_a_row", 0)) + 1}


def describe(cfg: dict) -> dict:
    """What a run changed from the default, for the manifest. Empty for a default run."""
    run = cfg.get("run") or {}
    out = dict(validate(run.get("tokens")))
    if run.get("foreign_cabinet_backend"):
        backend = run["foreign_cabinet_backend"]
        out["foreign_cabinet_backend"] = {k: backend.get(k) for k in ("provider", "model", "label") if backend.get(k)}
    efforts = {s.get("label"): s["effort_by_phase"] for s in (cfg.get("seats") or []) if s.get("effort_by_phase")}
    if efforts:
        out["effort_by_phase"] = efforts
    return out
