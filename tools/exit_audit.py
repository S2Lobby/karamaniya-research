#!/usr/bin/env python3
"""Exit-event trace audit for recorded runs (brief 9.S5 and 9.S6). Standard library only.

    python tools/exit_audit.py extract RUN_DIR [RUN_DIR ...] --out events.jsonl
    python tools/exit_audit.py sample events.jsonl --seed S --other N --out sample.csv
    python tools/exit_audit.py agreement sample_a.csv sample_b.csv [--col-a annotator_1 --col-b annotator_2]
                                         [--disagreements FILE]

`extract` reads run folders and writes one row per exit-like event. It also writes one row per executed motion
and one per refused motion: those are the pool that `sample` draws the non-exit events from. It never writes into
a run folder. The labels, and the rules for them, are in docs/EXIT_AUDIT_CODEBOOK.md.

The exit list is the engine's list. Member exits are the `remove_member` reasons in politics.py, plots.py and
council.py; government exits are the `outcome` types the engine writes; office exits are executed `vacate_office`
and displacing `assign_office` motions. tests/test_engine24_exit_audit.py reads the engine source to check it.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter

LABELS = ("substantively_supported", "ambiguous", "formatting_or_parser")

# politics.remove_member reasons (member leaves the government; checkpoint status "removed", removed_how = reason).
# "incapacitated" is the knockout arm (karamaniya/knockout.py): the office holder is removed at the start of the
# chosen month, with a public in-world event.
MEMBER_EXIT_HOWS = ("resigned", "expelled", "voted_out", "lost_seat", "coup", "failed_coup", "revolution",
                    "officers_coup", "incapacitated")
# world.outcome types that end the government or the country's government (each is an exit).
OUTCOME_EXIT_TYPES = ("voted_out", "no_government", "revolution", "revolution_union", "officers_coup", "conquered",
                      "joined_union", "federation", "reunified_by_vote", "reunified_by_referendum")
# survived: the run reached its horizon. kept_power_by_force: an election was lost and not handed over. It is not
# an exit, but it is recorded, because it is where an election defeat shows in the outcome.
NON_EXIT_OUTCOMES = ("survived", "kept_power_by_force")
# The phases in which a delegate speaks or votes. Its answers in these phases are what the audit reads.
PHASES = ("session", "revision", "motion_repair", "decision")
ELECTION_RESPONSES = ("concede", "legal_challenge", "request_recount", "negotiate_coalition", "resign", "refuse")
# Charter rule, as politics.charter_verdict applies it (a test checks these against the engine).
KEEP_SHARE = 0.40
LARGEST_SHARE = 0.30
# Month-record lists that name the member or the motion they concern. A flag is raised for each entry found.
# (rejected_motions is not here: a refused motion gets its own row, with its reason code.)
MONTH_LISTS = ("vote_intent_mismatches", "defiance", "unauthorized_orders", "superseded_orders",
               "memory_mismatches", "grounding", "stale_claims")
MOTION_CLASSES = ("motion_executed", "motion_refused")
CLASS_ORDER = {"member": 0, "office": 1, "election": 2, "government": 3, "terminal_non_exit": 4,
               "motion_executed": 5, "motion_refused": 6}
PLACEHOLDER_WORDS = ("", "n/a", "na", "tbd", "todo", "-", "--")
RESIGN_RE = re.compile(r'"resign"\s*:\s*("(?:[^"\\]|\\.)*"|true|false|null|[0-9.+-]+)')
ELECTION_RE = re.compile(r'"election_response"\s*:\s*"((?:[^"\\]|\\.)*)"')
COUP_RE = re.compile(r'"coup"\s*:\s*\{\s*"action"\s*:\s*"([^"]*)"')
FIELD_RE = re.compile(r'"(notes|statement|private_position)"\s*:\s*"((?:[^"\\]|\\.)*)"')
CSV_FIELDS = ["stratum", "event_id", "run", "month", "month_label", "event_type", "is_exit", "exit_class", "member",
              "seat", "model", "office", "motion_id", "motion_type", "raw_answers", "parsed", "state_change",
              "engine_flags", "parser_checks", "raw_reading", "annotator_1", "annotator_2", "adjudicated", "notes"]


class AuditError(Exception):
    """A problem with the inputs. The command stops and reports it; nothing is silently skipped."""


# ---- reading run folders ----------------------------------------------------------------------------------

def read_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except ValueError as exc:
                    raise AuditError(f"{path}:{number}: not JSON ({exc})") from exc
    return rows


def write_jsonl(rows, path):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _members_by_id(raw):
    if isinstance(raw, dict):
        return {str(k): dict(v, id=str(k)) for k, v in raw.items() if isinstance(v, dict)}
    out = {}
    for item in raw or []:
        if isinstance(item, dict) and item.get("id"):
            out[str(item["id"])] = item
    return out


def _offices(rec):
    return dict((rec.get("pre_resolution") or {}).get("offices") or {})


def _plain_text(raw):
    """The answer without a code fence around it. The engine accepts fenced JSON, so the audit does too."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


def _answer_fields(raw):
    """What the audit reads from one raw answer. A plain JSON object is read exactly; anything else is read by
    pattern, and is reported as not plain JSON, so the reader knows the reading is looser."""
    text = _plain_text(raw)
    obj = None
    if text:
        try:
            obj = json.loads(text)
        except ValueError:
            obj = None
    if isinstance(obj, dict):
        fields = {"plain": True, "resign": [], "election_response": [], "coup_action": [], "placeholder": []}
        if "resign" in obj:
            fields["resign"].append(json.dumps(obj["resign"], ensure_ascii=False))
        if "election_response" in obj:
            fields["election_response"].append(str(obj["election_response"]).strip())
        if isinstance(obj.get("coup"), dict) and "action" in obj["coup"]:
            fields["coup_action"].append(str(obj["coup"]["action"]).strip())
        for key in ("notes", "statement", "private_position"):
            if isinstance(obj.get(key), str) and is_placeholder(obj[key]):
                fields["placeholder"].append(key)
        if isinstance(obj.get("vote_reasons"), dict) and any(
                is_placeholder(v) for v in obj["vote_reasons"].values() if isinstance(v, str)):
            fields["placeholder"].append("vote_reasons")
        return fields
    fields = {"plain": False, "resign": [m.group(1) for m in RESIGN_RE.finditer(raw or "")],
              "election_response": [m.group(1).strip() for m in ELECTION_RE.finditer(raw or "")],
              "coup_action": [m.group(1).strip() for m in COUP_RE.finditer(raw or "")], "placeholder": []}
    for m in FIELD_RE.finditer(raw or ""):
        if is_placeholder(m.group(2)) and m.group(1) not in fields["placeholder"]:
            fields["placeholder"].append(m.group(1))
    return fields


def is_placeholder(text):
    """Empty, dots or dashes only, or a stock filler word: the kind of value a model writes when it has nothing to say."""
    s = str(text).strip()
    if s.lower() in PLACEHOLDER_WORDS:
        return True
    return all(ch in ".…-_ " for ch in s)


def _resign_sentences(raw):
    out = []
    for piece in re.split(r"(?<=[.!?])\s+|\n+", raw or ""):
        p = piece.strip()
        if p and re.search(r"resign", p, re.IGNORECASE) and p not in out:
            out.append(p)
    return out


def charter_verdict(shares):
    """What a vote with these shares means under the Charter, as politics.charter_verdict decides it."""
    if shares["Union Party"] > 0.5:
        return "union"
    council = shares["Council List"]
    largest = max(shares, key=shares.get)
    return "keep" if council >= KEEP_SHARE or (largest == "Council List" and council >= LARGEST_SHARE) else "lose"


class Run:
    """One run folder: its month records, its raw answers and its canonical state at the checkpoint."""

    def __init__(self, path):
        if not os.path.isdir(path):
            raise AuditError(f"{path}: not a folder")
        self.path = path
        self.name = os.path.basename(os.path.normpath(path))
        for needed in ("log.jsonl", "checkpoint.json"):
            if not os.path.isfile(os.path.join(path, needed)):
                raise AuditError(f"{path}: no {needed}")
        self.records = read_jsonl(os.path.join(path, "log.jsonl"))
        self.checkpoint = _load_json(os.path.join(path, "checkpoint.json"))
        world = self.checkpoint.get("world") or {}
        self.members = _members_by_id(world.get("members"))
        const = world.get("const") or {}
        self.offices_final = dict(const.get("offices") or {})
        self.elections = list(const.get("elections") or [])
        self.checkpoint_outcome = dict(world.get("outcome") or {})
        self.months, self.calls, self.duplicate_months = {}, {}, []
        for rec in self.records:
            if rec.get("type") == "month":
                if rec.get("month") in self.months:
                    self.duplicate_months.append(rec.get("month"))
                self.months[rec.get("month")] = rec
            elif rec.get("type") == "call":
                self.calls.setdefault((rec.get("month"), rec.get("member"), rec.get("phase")), []).append(rec)
        self._emitted = set()

    # ---- raw answers -----------------------------------------------------------------------------------
    def answers(self, month, member, phases=PHASES):
        out = []
        for phase in phases:
            for rec in self.calls.get((month, member, phase), []):
                out.append({"member": member, "phase": phase, "call_id": rec.get("call_id", ""),
                            "seat": rec.get("seat", ""), "served_model": rec.get("served_model") or rec.get("model", ""),
                            "error": rec.get("error", ""), "refusal": bool(rec.get("refusal")),
                            "format_retry": bool(rec.get("format_retry")), "attempts": rec.get("attempts"),
                            "raw": rec["raw"] if isinstance(rec.get("raw"), str) else ""})
        return out

    def seat_and_model(self, month, member):
        for phase in PHASES:
            for rec in self.calls.get((month, member, phase), []):
                return rec.get("seat", ""), rec.get("served_model") or rec.get("model", "")
        return "", ""

    def decision_answers_of_all(self, month):
        members = sorted({k[1] for k in self.calls if k[0] == month and k[2] == "decision" and k[1]})
        return [a for m in members for a in self.answers(month, m, ("decision",))]

    def flags(self, month, member, motion_id=""):
        """What the engine itself recorded about this member's answers this month, and about the motion."""
        out = []
        rec = self.months.get(month) or {}
        for entry in rec.get("calls") or []:
            if entry.get("member") == member:
                for problem in entry.get("problems") or []:
                    out.append(f"problem:{problem}")
                for cut in entry.get("cuts") or []:
                    if isinstance(cut, dict):
                        # scorecard.py tallies the unstated ones as "unstated_limit": a cut to a length no prompt states.
                        tag = "cut" if cut.get("stated") else "cut_unstated_limit"
                        out.append(f"{tag}:{cut.get('field')}")
                    else:
                        out.append(f"cut:{cut}")
        for phase in PHASES:
            for c in self.calls.get((month, member, phase), []):
                if c.get("error"):
                    out.append(f"error:{c['error']}")
                if c.get("refusal"):
                    out.append("refusal")
                if c.get("format_retry"):
                    out.append("format_retry")
        for key in MONTH_LISTS:
            for entry in rec.get(key) or []:
                if not isinstance(entry, dict):
                    continue
                mentions_member = entry.get("member") == member
                mo = entry.get("motion") if isinstance(entry.get("motion"), dict) else {}
                mentions_motion = bool(motion_id) and (entry.get("motion_id") == motion_id or mo.get("id") == motion_id)
                if mentions_member or mentions_motion:
                    code = entry.get("reason_code") or entry.get("code")
                    out.append(f"{key}:{code}" if code else key)
        return out

    def unrecorded_resign_tokens(self):
        """Decision answers whose top-level resign token is true, where the month records no resignation. The
        parser can only miss one of these, so the count goes in the report."""
        recorded = {(m, mid) for m, rec in self.months.items() for mid in rec.get("resigned") or []}
        hits = []
        for (month, member, phase), recs in self.calls.items():
            if phase != "decision" or (month, member) in recorded:
                continue
            for rec in recs:
                if "true" in _answer_fields(rec.get("raw") or "")["resign"]:
                    hits.append(f"M{month}:{member}")
        return sorted(set(hits))

    # ---- rows ------------------------------------------------------------------------------------------
    def row(self, *, month, exit_class, event_type, is_exit, member="", office="", motion=None, answers=(),
            parsed=None, state_change=None, engine_flags=(), parser_checks=(), raw_reading=None, key=""):
        motion = motion or {}
        seat, model = self.seat_and_model(month, member) if member else ("", "")
        return {"event_id": "", "run": self.name, "month": month,
                "month_label": f"Month {month + 1}" if isinstance(month, int) and month >= 0 else "",
                "is_exit": bool(is_exit), "exit_class": exit_class, "event_type": event_type,
                "member": member or "", "seat": seat, "model": model, "office": office or "",
                "motion_id": motion.get("id", "") or "", "motion_type": motion.get("type", "") or "",
                "raw_answers": list(answers), "parsed": parsed or {}, "state_change": state_change or {},
                "engine_flags": list(engine_flags), "parser_checks": list(parser_checks),
                "raw_reading": raw_reading or {},
                "_key": key or (motion or {}).get("id", "") or member or office or event_type}

    def reading(self, answers, parsed, kind):
        """The audit's own reading of the raw answers, and the checks that compare it with the engine's reading.
        Resignation, election and coup tokens are read from the decision answers only, since that is where the
        engine reads them. Placeholder text and the sentences about resigning are read from every answer."""
        live = [a for a in answers if a["raw"].strip()]
        decided = [_answer_fields(a["raw"]) for a in live if a["phase"] == "decision"]
        every = [_answer_fields(a["raw"]) for a in live]
        tokens = {
            "plain_json": bool(live) and all(f["plain"] for f in every),
            "resign_tokens": [t for f in decided for t in f["resign"]],
            "election_response_tokens": [t for f in decided for t in f["election_response"]],
            "coup_action_tokens": [t for f in decided for t in f["coup_action"]],
            "placeholder_fields": sorted({p for f in every for p in f["placeholder"]}),
            "resign_sentences": [s for a in live for s in _resign_sentences(a["raw"])],
        }
        checks = []
        if not answers:
            checks.append("no_answer_in_log")
        for a in answers:
            if not a["raw"].strip():
                checks.append(f"raw_empty:{a['phase']}")
        if live and not tokens["plain_json"]:
            checks.append("raw_not_plain_json")
        if kind == "resigned" and parsed.get("source") == "decision":
            if not tokens["resign_tokens"]:
                checks.append("resign_token_missing_in_raw")
            checks += [f"resign_token_not_boolean:{t}" for t in tokens["resign_tokens"] if t != "true"]
        if kind in ("resigned", "voted_out"):
            unreadable = []
            for f in decided:
                for v in f["election_response"]:
                    if v.lower() not in ELECTION_RESPONSES and v not in unreadable:
                        unreadable.append(v)
            checks += [f"election_response_unreadable:{v}" for v in unreadable]
            if kind == "voted_out" and not tokens["election_response_tokens"]:
                checks.append("election_response_missing_in_raw")
        if kind in ("coup", "failed_coup"):
            engine_action = (parsed.get("coup") or {}).get("action") if isinstance(parsed.get("coup"), dict) else None
            for t in tokens["coup_action_tokens"]:
                if engine_action and t != engine_action:
                    checks.append(f"coup_action_mismatch:{t} (engine read {engine_action})")
            if not engine_action and any(t in ("remove", "take_over") for t in tokens["coup_action_tokens"]):
                checks.append("coup_action_not_read")
        checks += [f"placeholder:{p}" for p in tokens["placeholder_fields"]]
        return tokens, checks

    # ---- exits -----------------------------------------------------------------------------------------
    def member_exit(self, month, member, how, *, motion=None, parsed=None, extra_members=(), flags=()):
        rec = self.months.get(month) or {}
        checks_flags = list(flags)
        if not member:
            checks_flags.append("no_member_named")
        state = self.members.get(member) or {}
        if member and not state:
            checks_flags.append("member_not_in_checkpoint")
        if state:
            if state.get("status") == "active":
                checks_flags.append("still_active_in_checkpoint")
            if state.get("removed_how") not in (None, how):
                checks_flags.append(f"removal_how_mismatch:{state.get('removed_how')}")
            if state.get("removed_month") != month:
                checks_flags.append(f"removal_month_mismatch:{state.get('removed_month')}")
        if not isinstance(month, int) or month < 0:
            checks_flags.append("removal_month_unrecorded")
        held = sorted(o for o, h in _offices(rec).items() if h == member)
        vacated = sorted(o for o in held if self.offices_final.get(o) != member)
        answers = self.answers(month, member)
        for other in extra_members:
            answers += [dict(a, role="other") for a in self.answers(month, other, ("decision",))]
        parsed = dict(parsed or {"source": "removal"})
        tokens, checks = self.reading(answers, parsed, how)
        if not rec:
            checks_flags.append("no_month_record")
        return self.row(
            month=month, exit_class="member", event_type=how, is_exit=True, member=member, office=";".join(held),
            motion=motion, answers=answers, parsed=parsed,
            state_change={"status_before": "active", "status_after": state.get("status"),
                          "removed_how": state.get("removed_how"), "removed_month": state.get("removed_month"),
                          "offices_held_before": held, "offices_vacated": vacated},
            engine_flags=checks_flags + self.flags(month, member, (motion or {}).get("id", "")),
            parser_checks=checks, raw_reading=tokens)

    def resignation_reading(self, month, member):
        rec = self.months.get(month) or {}
        dec = (rec.get("decisions") or {}).get(member) or {}
        responses = (rec.get("election_responses") or {}).get(member)
        if dec.get("resign") is True:
            source = "decision"
        elif responses == "resign":
            source = "election_response"
        else:
            source = "unknown"
        election = responses if responses is not None else dec.get("election_response")
        return {"source": source, "resign": dec.get("resign"), "election_response": election}

    def coup_reading(self, month, member):
        rec = self.months.get(month) or {}
        dec = (rec.get("decisions") or {}).get(member) or {}
        record = next((c for c in rec.get("coups") or []
                       if member in (c.get("targets") or []) or member in (c.get("armed") or [])), None)
        return {"source": "coup", "coup": dec.get("coup"), "coup_stance": dec.get("coup_stance"),
                "coup_record": record}

    def motion_summary(self, mo):
        keys = ("id", "proposer", "type", "subject", "value", "previous_value", "status", "execution_status",
                "passed", "tally", "votes", "summary")
        return {k: mo.get(k) for k in keys if k in mo}

    def motion_row(self, month, mo):
        proposer = mo.get("proposer") or ""
        answers = self.answers(month, proposer)
        parsed = {"source": "motion", "motion": self.motion_summary(mo)}
        tokens, checks = self.reading(answers, parsed, "motion")
        office = mo.get("subject") if mo.get("type") in ("vacate_office", "assign_office") else ""
        flags = self.flags(month, proposer, mo.get("id", ""))
        return self.row(month=month, exit_class="motion_executed", event_type="motion_executed", is_exit=False,
                        member=proposer, office=office or "", motion=mo, answers=answers, parsed=parsed,
                        state_change={"status": mo.get("status"), "execution_status": mo.get("execution_status"),
                                      "passed": mo.get("passed")},
                        engine_flags=flags, parser_checks=checks, raw_reading=tokens)

    def refused_row(self, month, rej):
        mo = rej.get("motion") if isinstance(rej.get("motion"), dict) else {}
        member = rej.get("member") or mo.get("proposer") or ""
        answers = self.answers(month, member)
        parsed = {"source": "refusal", "reason_code": rej.get("reason_code"), "explanation": rej.get("explanation"),
                  "motion": self.motion_summary(mo)}
        tokens, checks = self.reading(answers, parsed, "motion")
        return self.row(month=month, exit_class="motion_refused", event_type="motion_refused", is_exit=False,
                        member=member, motion=mo, answers=answers, parsed=parsed,
                        state_change={"status": rej.get("status"), "related_state": rej.get("related_state")},
                        engine_flags=self.flags(month, member, mo.get("id", "")) + [f"rejected:{rej.get('reason_code')}"],
                        parser_checks=checks, raw_reading=tokens)

    def office_row(self, month, office, holder, replaced_by, event_type, mo):
        answers = self.answers(month, holder)
        parsed = {"source": "motion", "motion": self.motion_summary(mo), "replaced_by": replaced_by}
        tokens, checks = self.reading(answers, parsed, event_type)
        return self.row(month=month, exit_class="office", event_type=event_type, is_exit=True, member=holder,
                        office=office, motion=mo, answers=answers, parsed=parsed,
                        state_change={"office": office, "holder_before": holder,
                                      "holder_after": replaced_by if replaced_by else None},
                        engine_flags=self.flags(month, holder, mo.get("id", "")),
                        parser_checks=checks, raw_reading=tokens)

    def handover_reading(self, month, member):
        rec = self.months.get(month) or {}
        dec = (rec.get("decisions") or {}).get(member) or {}
        responses = (rec.get("election_responses") or {}).get(member)
        return {"source": "handover",
                "election_response": responses if responses is not None else dec.get("election_response")}

    def government_row(self, month, outcome, is_exit, flags):
        kind = str(outcome.get("type") or "")
        answers = self.decision_answers_of_all(month)
        tokens, checks = self.reading(answers, {"source": "outcome"}, "government")
        out_of_office = sorted(mid for mid, st in self.members.items() if st.get("status") != "active")
        return self.row(month=month, exit_class="government" if is_exit else "terminal_non_exit", event_type=kind,
                        is_exit=is_exit, answers=answers,
                        parsed={"source": "outcome", "outcome": {"type": kind, "month": outcome.get("month"),
                                                                  "text": outcome.get("text", "")}},
                        state_change={"members_out_of_office_at_checkpoint": out_of_office},
                        engine_flags=list(flags), parser_checks=checks, raw_reading=tokens)

    def election_row(self, index, entry):
        month = entry.get("month")
        routes = {k: entry[k] for k in ("challenged", "recount", "court", "coalition") if k in entry}
        return self.row(month=month, exit_class="election", event_type="election_defeat", is_exit=True,
                        parsed={"source": "election", "verdict": "lose", "shares": entry["shares"],
                                "rigged": bool(entry.get("rigged")), "exposed": bool(entry.get("exposed")),
                                "routes": routes},
                        state_change={"handover_due_month": month + 1 if isinstance(month, int) else None},
                        engine_flags=[] if isinstance(month, int) else ["election_month_missing"],
                        key=f"election{index}")

    def events(self):
        rows = []
        months = sorted(m for m in self.months if isinstance(m, int))
        for month in months:
            rec = self.months[month]
            for member in rec.get("resigned") or []:
                rows.append(self.member_exit(month, member, "resigned",
                                             parsed=self.resignation_reading(month, member)))
                self._emitted.add((member, month))
            for coup in rec.get("coups") or []:
                leader = coup.get("leader") or ""
                if coup.get("success"):
                    for target in coup.get("targets") or []:
                        rows.append(self.member_exit(month, target, "coup", parsed=self.coup_reading(month, target),
                                                     extra_members=[leader] if leader != target else []))
                        self._emitted.add((target, month))
                else:
                    for plotter in coup.get("armed") or []:
                        rows.append(self.member_exit(month, plotter, "failed_coup",
                                                     parsed=self.coup_reading(month, plotter),
                                                     extra_members=[leader] if leader != plotter else []))
                        self._emitted.add((plotter, month))
            offices = _offices(rec)
            for mo in rec.get("motions") or []:
                if mo.get("execution_status") != "EXECUTED":
                    continue
                rows.append(self.motion_row(month, mo))
                kind = mo.get("type")
                if kind == "expel":
                    member = str(mo.get("subject") or "").strip().upper()
                    rows.append(self.member_exit(month, member, "expelled", motion=mo,
                                                 parsed={"source": "motion", "motion": self.motion_summary(mo)}))
                    self._emitted.add((member, month))
                elif kind == "vacate_office":
                    office = str(mo.get("subject") or "")
                    holder = offices.get(office)
                    if holder:
                        rows.append(self.office_row(month, office, holder, None, "vacate_office", mo))
                    else:
                        rows[-1]["engine_flags"].append("vacated_empty_office")
                elif kind == "assign_office":
                    office = str(mo.get("subject") or "")
                    holder = offices.get(office)
                    new = str(mo.get("value") or "").strip().upper()
                    if holder and holder != new:
                        rows.append(self.office_row(month, office, holder, new, "office_displaced", mo))
            for rej in rec.get("rejected_motions") or []:
                rows.append(self.refused_row(month, rej))
        for month in months:
            outcome = self.months[month].get("outcome")
            if isinstance(outcome, dict) and outcome.get("type"):
                row = self._outcome(month, outcome)
                if row:
                    rows.append(row)
        seen_outcomes = {(r["event_type"], r["month"]) for r in rows if r["exit_class"] in ("government",
                                                                                              "terminal_non_exit")}
        cp = self.checkpoint_outcome
        if cp.get("type") and (cp.get("type"), cp.get("month")) not in seen_outcomes:
            row = self._outcome(cp.get("month", -1), cp, from_checkpoint=True)
            if row:
                rows.append(row)
        for index, entry in enumerate(self.elections):
            if isinstance(entry, dict) and isinstance(entry.get("shares"), dict):
                if charter_verdict(entry["shares"]) == "lose":
                    rows.append(self.election_row(index, entry))
        for member in sorted(self.members):
            state = self.members[member]
            if state.get("status") == "active":
                continue
            month = state.get("removed_month")
            if (member, month) in self._emitted:
                continue
            how = state.get("removed_how") or "unrecorded_reason"
            # A handover removes every member but no month record names them: the checkpoint is the only record.
            # That is the Charter's own mechanism, so it is not flagged as a gap.
            if how == "voted_out":
                rows.append(self.member_exit(month, member, how, parsed=self.handover_reading(month, member)))
            else:
                rows.append(self.member_exit(month, member, how, flags=["removal_only_in_checkpoint"]))
            self._emitted.add((member, month))
        if self.duplicate_months:
            for row in rows:
                row["engine_flags"].append("month_logged_twice")
        return rows

    def _outcome(self, month, outcome, from_checkpoint=False):
        kind = str(outcome.get("type") or "")
        if kind == "survived":
            return None
        flags = ["outcome_only_in_checkpoint"] if from_checkpoint else []
        if kind in OUTCOME_EXIT_TYPES:
            return self.government_row(month, outcome, True, flags)
        if kind in NON_EXIT_OUTCOMES:
            return self.government_row(month, outcome, False, flags)
        return self.government_row(month, outcome, True, flags + ["unrecognised_outcome_type"])


def _event_order(row):
    return (row["month"] if isinstance(row["month"], int) else -1, CLASS_ORDER.get(row["exit_class"], 9),
            row["event_type"], row["member"], row["office"], row["motion_id"], row["_key"])


def extract_runs(run_dirs, notes=None):
    """Every exit-like event and every executed or refused motion, across the given run folders. `notes`, when
    given, collects the diagnostics the command prints (resign tokens the records do not explain, repeated months)."""
    rows = []
    for path in run_dirs:
        run = Run(path)
        batch = run.events()
        batch.sort(key=_event_order)
        seen = Counter()
        for row in batch:
            base = f"{run.name}|m{row['month']}|{row['event_type']}|{row['_key']}"
            seen[base] += 1
            row["event_id"] = base if seen[base] == 1 else f"{base}#{seen[base]}"
            row.pop("_key", None)
        if notes is not None:
            hits = run.unrecorded_resign_tokens()
            if hits:
                notes.append(f"{run.name}: decision answers with resign true and no recorded resignation: "
                             + ", ".join(hits))
            if run.duplicate_months:
                notes.append(f"{run.name}: months logged twice: {sorted(set(run.duplicate_months))}")
        rows.extend(batch)
    return rows


# ---- sampling ----------------------------------------------------------------------------------------------

def _rank(seed, event_id):
    return hashlib.sha256(f"{seed}|{event_id}".encode("utf-8")).hexdigest()


def _allocate(budget, sizes):
    """Equal allocation over the strata, with the unused share of a small stratum passed on to the others."""
    quota = {k: 0 for k in sizes}
    remaining = min(budget, sum(sizes.values()))
    active = sorted(k for k in sizes if sizes[k] > 0)
    while remaining > 0 and active:
        share, extra = divmod(remaining, len(active))
        progressed = False
        for i, key in enumerate(active):
            take = min(share + (1 if i < extra else 0), sizes[key] - quota[key])
            if take > 0:
                quota[key] += take
                remaining -= take
                progressed = True
        active = [k for k in active if quota[k] < sizes[k]]
        if not progressed:
            break
    return quota


def sample_rows(rows, seed, other):
    """Every exit, plus `other` motion events drawn at random, equally across the strata (exit class, motion type)."""
    exits = [r for r in rows if r["is_exit"]]
    pool = {}
    for r in rows:
        if not r["is_exit"] and r["exit_class"] in MOTION_CLASSES:
            pool.setdefault(f"{r['exit_class']}/{r['motion_type'] or '-'}", []).append(r)
    for key in pool:
        pool[key].sort(key=lambda r: _rank(seed, r["event_id"]))
    quota = _allocate(other, {k: len(v) for k, v in pool.items()})
    chosen = [("exit", r) for r in exits]
    for key in sorted(pool):
        chosen += [(key, r) for r in pool[key][:quota.get(key, 0)]]
    chosen.sort(key=lambda t: _rank(seed, t[1]["event_id"]))
    meta = {"seed": seed, "other_requested": other, "other_drawn": len(chosen) - len(exits), "exits": len(exits),
            "pool_size": sum(len(v) for v in pool.values()),
            "strata": {k: {"pool": len(pool[k]), "drawn": quota.get(k, 0)} for k in sorted(pool)}}
    return chosen, meta


def _csv_row(stratum, row):
    texts = [f"--- {a['member']} {a['phase']} {a['call_id']}\n{a['raw']}" for a in row["raw_answers"]]
    return {"stratum": stratum, "event_id": row["event_id"], "run": row["run"], "month": row["month"],
            "month_label": row["month_label"], "event_type": row["event_type"], "is_exit": str(row["is_exit"]),
            "exit_class": row["exit_class"], "member": row["member"], "seat": row["seat"], "model": row["model"],
            "office": row["office"], "motion_id": row["motion_id"], "motion_type": row["motion_type"],
            "raw_answers": "\n\n".join(texts), "parsed": json.dumps(row["parsed"], ensure_ascii=False, sort_keys=True),
            "state_change": json.dumps(row["state_change"], ensure_ascii=False, sort_keys=True),
            "engine_flags": "; ".join(row["engine_flags"]), "parser_checks": "; ".join(row["parser_checks"]),
            "raw_reading": json.dumps(row["raw_reading"], ensure_ascii=False, sort_keys=True),
            "annotator_1": "", "annotator_2": "", "adjudicated": "", "notes": ""}


# ---- agreement -----------------------------------------------------------------------------------------------

def _read_labels(path, column):
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        if "event_id" not in fields:
            raise AuditError(f"{path}: no event_id column")
        if column not in fields:
            raise AuditError(f"{path}: no column named {column!r}")
        rows = {}
        for row in reader:
            eid = (row.get("event_id") or "").strip()
            if not eid:
                raise AuditError(f"{path}: a row has no event_id")
            if eid in rows:
                raise AuditError(f"{path}: event_id {eid} appears twice")
            rows[eid] = row
    return rows


def _kappa_alpha(pairs):
    """Cohen's kappa and Krippendorff's alpha (nominal, two coders) for a list of (label_a, label_b) pairs."""
    n = len(pairs)
    cats = sorted({x for p in pairs for x in p})
    table = Counter(pairs)
    agree = sum(v for (x, y), v in table.items() if x == y)
    p_o = agree / n
    count_a, count_b = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    p_e = sum((count_a[c] / n) * (count_b[c] / n) for c in cats)
    if p_e < 1:
        kappa = (p_o - p_e) / (1 - p_e)
    else:
        kappa = 1.0 if p_o == 1 else None
    # Coincidence matrix: each unit gives its two values in both orders. N = 2n pairable values.
    coincidence = Counter()
    for x, y in pairs:
        coincidence[(x, y)] += 1
        coincidence[(y, x)] += 1
    total = 2 * n
    marginal = Counter()
    for (x, _), v in coincidence.items():
        marginal[x] += v
    observed = sum(v for (x, y), v in coincidence.items() if x != y) / total
    expected_sum = sum(marginal[c] * marginal[k] for c in cats for k in cats if c != k)
    expected = expected_sum / (total * (total - 1)) if total > 1 else 0.0
    if expected > 0:
        alpha = 1 - observed / expected
    else:
        alpha = 1.0 if observed == 0 else None
    return {"p_o": p_o, "p_e": p_e, "kappa": kappa, "alpha": alpha, "categories": cats,
            "table": {f"{x} / {y}": v for (x, y), v in sorted(table.items())}}


def agreement_report(path_a, path_b, col_a="annotator_1", col_b="annotator_2"):
    a = _read_labels(path_a, col_a)
    b = _read_labels(path_b, col_b)
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    if only_a or only_b:
        raise AuditError(f"event ids differ: only in A {only_a[:10]}, only in B {only_b[:10]}")
    labels = {}
    for eid in a:
        for side, rows, col in (("A", a, col_a), ("B", b, col_b)):
            value = (rows[eid].get(col) or "").strip()
            if value and value not in LABELS:
                labels.setdefault("invalid", []).append(f"{side}:{eid}={value!r}")
    if labels.get("invalid"):
        raise AuditError("invalid labels (allowed: " + ", ".join(LABELS) + "): " + "; ".join(labels["invalid"][:20]))
    pairable, unlabelled, disagreements = [], 0, []
    for eid in sorted(a):
        la = (a[eid].get(col_a) or "").strip()
        lb = (b[eid].get(col_b) or "").strip()
        if not la or not lb:
            unlabelled += 1
            continue
        pairable.append((la, lb))
        if la != lb:
            detail = {k: a[eid].get(k, "") for k in ("run", "month", "event_type", "member", "motion_id")}
            disagreements.append({"event_id": eid, "label_a": la, "label_b": lb, **detail})
    stats = _kappa_alpha(pairable) if pairable else {"p_o": None, "p_e": None, "kappa": None, "alpha": None,
                                                     "categories": [], "table": {}}
    stats.update({"n_a": len(a), "n_b": len(b), "n_matched": len(a), "n_pairable": len(pairable),
                  "unlabelled": unlabelled, "disagreements": disagreements})
    return stats


def format_agreement(stats, path_a, path_b, col_a, col_b):
    def fmt(v):
        return "undefined" if v is None else f"{v:.4f}"
    lines = [f"A: {path_a} (column {col_a}): {stats['n_a']} rows",
             f"B: {path_b} (column {col_b}): {stats['n_b']} rows",
             f"Pairable (labelled in both): {stats['n_pairable']}; left unlabelled: {stats['unlabelled']}",
             f"Categories: {', '.join(stats['categories']) or '-'}",
             f"Observed agreement p_o: {fmt(stats['p_o'])}",
             f"Chance agreement p_e: {fmt(stats['p_e'])}",
             f"Cohen's kappa: {fmt(stats['kappa'])}",
             f"Krippendorff's alpha (nominal): {fmt(stats['alpha'])}",
             f"Disagreements for adjudication: {len(stats['disagreements'])}"]
    for d in stats["disagreements"]:
        lines.append(f"  {d['event_id']}: A={d['label_a']} B={d['label_b']} "
                     f"({d.get('run', '')} month {d.get('month', '')}, {d.get('event_type', '')})")
    return "\n".join(lines)


# ---- command line --------------------------------------------------------------------------------------------

def cmd_extract(args):
    notes = []
    rows = extract_runs(args.run_dirs, notes)
    write_jsonl(rows, args.out)
    counts = Counter((r["exit_class"], r["event_type"], r["is_exit"]) for r in rows)
    print(f"{len(rows)} rows from {len(args.run_dirs)} run folder(s) -> {args.out}")
    for (cls, kind, is_exit), n in sorted(counts.items(), key=lambda kv: (CLASS_ORDER.get(kv[0][0], 9), kv[0][1])):
        print(f"  {cls:<18} {kind:<24} is_exit={str(is_exit):<5} {n}")
    for note in notes:
        print(f"  note: {note}")
    return 0


def cmd_sample(args):
    rows = read_jsonl(args.events)
    chosen, meta = sample_rows(rows, args.seed, args.other)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for stratum, row in chosen:
            writer.writerow(_csv_row(stratum, row))
    with open(args.events, "rb") as f:
        meta["events_sha256"] = hashlib.sha256(f.read()).hexdigest()
    meta["events_file"] = os.path.abspath(args.events)
    meta["label_columns"] = ["annotator_1", "annotator_2", "adjudicated", "notes"]
    with open(args.out + ".meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    print(f"{len(chosen)} rows ({meta['exits']} exits, {meta['other_drawn']} other) -> {args.out}")
    return 0


def cmd_agreement(args):
    stats = agreement_report(args.sample_a, args.sample_b, args.col_a, args.col_b)
    print(format_agreement(stats, args.sample_a, args.sample_b, args.col_a, args.col_b))
    if args.disagreements:
        fields = ["event_id", "label_a", "label_b", "run", "month", "event_type", "member", "motion_id"]
        with open(args.disagreements, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for d in stats["disagreements"]:
                writer.writerow(d)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="exit_audit", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_extract = sub.add_parser("extract", help="list every exit-like event in run folders")
    p_extract.add_argument("run_dirs", nargs="+")
    p_extract.add_argument("--out", required=True)
    p_extract.set_defaults(func=cmd_extract)
    p_sample = sub.add_parser("sample", help="draw the predefined sample: every exit plus stratified motions")
    p_sample.add_argument("events")
    p_sample.add_argument("--seed", type=int, required=True, help="fixed in the pre-registration")
    p_sample.add_argument("--other", type=int, required=True, help="number of non-exit events to draw")
    p_sample.add_argument("--out", required=True)
    p_sample.set_defaults(func=cmd_sample)
    p_agree = sub.add_parser("agreement", help="agreement between two annotators' sheets")
    p_agree.add_argument("sample_a")
    p_agree.add_argument("sample_b")
    p_agree.add_argument("--col-a", default="annotator_1")
    p_agree.add_argument("--col-b", default="annotator_2")
    p_agree.add_argument("--disagreements", default="", help="write the disagreement list to this CSV")
    p_agree.set_defaults(func=cmd_agreement)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except AuditError as exc:
        print(f"exit_audit: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
