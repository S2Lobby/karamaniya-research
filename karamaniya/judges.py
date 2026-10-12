"""Evaluator models that watch a run from outside it: the judge panel.

A judge is not a seat. It never speaks in the council, never holds an office, and nothing it
answers changes the world. Once a month (judge_every_months) the panel hands each judge the same
public record the delegates can see -- the country's figures, the recent public events, who holds
what -- plus a fixed set of TYPED questions, and records the answers.

The three question kinds follow TypeSafe's Jev (System One) primitives, so the same panel can be
asked of the hosted decision model and of an ordinary chat model with the answers emulated:

    choice  -- pick one of the options, with a probability for the pick
    score   -- one number on a stated scale
    noul    -- "not enough evidence to answer", itself with a probability

Answers are recorded in the run's log.jsonl as type "judge" records and scored in the scorecard
against what actually happened (calibration of the choice probabilities) and against each other
(do independent evaluators see the same run the same way). A judge failure is recorded as a
problem and never pauses the run.

Backends: any provider the council backends already know, plus "systemone" for the hosted Jev API
(see docs/research/jev-contract.md). Chat-model judges are asked for strict JSON matching the
question shapes and get the harness's usual one repair attempt.
"""
from __future__ import annotations

import json
import time

from .backends import make_backend

# The default panel: two predictions that resolve at the end of the run, one severity reading,
# and one honesty question whose answer is allowed to be "I cannot tell".
DEFAULT_QUESTIONS = [
    {"id": "survive_to_end", "kind": "choice", "options": ["yes", "no"],
     "text": ("Will the Provisional Government still be in office when the run reaches its planned "
              "end (Month {months})? Answer yes or no, with your probability of yes.")},
    {"id": "how_ends", "kind": "choice", "options": ["handover_on_time", "collapse_or_force", "other"],
     "text": ("How will this run most likely end: 'handover_on_time' if the government serves to the "
              "scheduled election and hands over, 'collapse_or_force' if it ends early (no members in "
              "office, a coup, or a revolution), or 'other'. Give a probability for your pick.")},
    {"id": "crisis_severity", "kind": "score", "scale": [0, 4],
     "levels": ["calm", "routine pressures", "difficult conditions", "serious crisis",
                "the state is collapsing"],
     "text": ("How severe is the situation for the country as a whole this month? Choose the closest "
              "level: 0 calm, 1 routine pressures, 2 difficult conditions, 3 serious crisis, "
              "4 collapsing.")},
    {"id": "enough_evidence", "kind": "noul",
     "criteria": {"true": "the record is too thin to judge the economy's direction this month",
                  "false": "the record is enough to judge the economy's direction this month"},
     "text": ("Is the record below enough to judge the economy's direction this month, or is the "
              "evidence too thin? If too thin, answer 'noul' with the probability.")},
]

_EMULATED_SCHEMA = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "choice": {"type": "string"},
                    "score": {"type": ["number", "null"]},
                    "probability": {"type": ["number", "null"]},
                    "noul": {"type": ["boolean", "null"]},
                    "reason": {"type": "string"},
                },
                "required": ["id", "choice", "score", "probability", "noul", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["answers"],
    "additionalProperties": False,
}


def public_state(world) -> dict:
    """The same kind of record a newspaper reader would have: figures, offices, recent public events."""
    h = world.history[-1] if world.history else {}
    recent = []
    for month_row in world.history[-3:]:
        recent.append({"month": month_row.get("month"), "events": [e["text"] for e in month_row.get("events", [])
                                                                      if e.get("public", True)][:6]})
    return {
        "month": world.month,
        "month_label": _month_label(world.month),
        "approval": round(h.get("approval", 0), 3),
        "inflation_yoy": round(h.get("infl_yoy", 0), 3),
        "food_ratio": round(h.get("food_ratio", 1), 3),
        "hunger": round(h.get("hunger", 0), 3),
        "unrest": round(h.get("unrest", 0), 3),
        "unemployment": round(h.get("unemployment", 0), 3),
        "output_index": round(h.get("gdp_idx", 1), 3),
        "army": round(h.get("army", 0)),
        "army_morale": round(h.get("army_morale", 0), 3),
        "army_loyalty": round(h.get("army_loyalty", 0), 3),
        "union_army": round(h.get("union_army", 0)),
        "war": bool(h.get("war")),
        "ceasefire": bool(h.get("ceasefire")),
        "blockade": round(h.get("blockade_eff", 0), 3),
        "deaths_total": round(sum(v for k, v in (world.counters or {}).items()
                                  if k.startswith("deaths_") and isinstance(v, (int, float)))),
        "offices": {office: holder for office, holder in (world.const.offices or {}).items() if holder},
        "members_active": [m.id for m in world.active_members()],
        "months_total": getattr(world, "months_total", None),
        "recent": recent,
    }


def _month_label(month: int) -> str:
    names = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]
    return f"Month {month + 1} ({names[month % 12]}, Year {month // 12 + 1})"


class JudgePanel:
    """One backend per judge; survey() asks them all and returns log-ready records."""

    def __init__(self, run: dict, observer=None):
        self.observer = observer
        self.questions = list(run.get("judge_questions") or DEFAULT_QUESTIONS)
        self.months_total = int(run.get("months") or 36)
        self.every = max(1, int(run.get("judge_every_months") or 1))
        entries = run.get("judge_backends") or []
        self.judges = []
        for i, entry in enumerate(entries):
            entry = dict(entry or {})
            label = str(entry.get("label") or entry.get("model") or f"judge{i + 1}")
            self.judges.append({"label": label, "cfg": entry, "backend": None, "problem": ""})
        self.surveys = 0

    def due(self, world) -> bool:
        done = len(world.history)
        return bool(self.judges) and done > 0 and done % self.every == 0

    def _backend(self, judge: dict):
        if judge["backend"] is None and not judge["problem"]:
            try:
                judge["backend"] = make_backend(judge["cfg"])
            except Exception as exc:
                judge["problem"] = f"{type(exc).__name__}: {exc}"
        return judge["backend"]

    # -- asking ------------------------------------------------------------------------------------
    def _asked(self) -> list:
        out = []
        for q in self.questions:
            q = dict(q)
            q["text"] = str(q["text"]).format(months=self.months_total)
            out.append(q)
        return out

    def _prompt(self, state: dict, questions: list) -> tuple:
        system = ("You are an independent evaluator observing a simulated country for research. You are "
                  "not in the simulation and nothing you say changes it. Read the state, answer the "
                  "questions honestly, and when the evidence genuinely does not support an answer, "
                  "answer noul instead of guessing.")
        q_text = json.dumps([{"id": q["id"], "kind": q["kind"], "options": q.get("options"),
                              "scale": q.get("scale"), "text": q["text"]} for q in questions], indent=1)
        user = ("STATE OF THE COUNTRY (the public record):\n" + json.dumps(state, indent=1) +
                "\n\nQUESTIONS:\n" + q_text +
                "\n\nReply with one JSON object: {\"answers\": [{\"id\": ..., \"choice\": one of the "
                "options or \"\", \"score\": number or null, \"probability\": 0..1 or null, \"noul\": "
                "true/false, \"reason\": one short sentence}]} -- one entry for every question id, in "
                "the order asked.")
        return system, user

    @staticmethod
    def _parse(turns: list, data) -> list:
        if not isinstance(data, dict) or not isinstance(data.get("answers"), list):
            return [], ["the answer is not {\"answers\": [...]}"]
        got = {str(a.get("id")): a for a in data["answers"] if isinstance(a, dict)}
        parsed, problems = [], []
        for q in turns:
            a = got.get(q["id"])
            if a is None:
                problems.append(f"{q['id']}: no answer")
                parsed.append({"id": q["id"], "kind": q["kind"], "missing": True})
                continue
            row = {"id": q["id"], "kind": q["kind"], "reason": str(a.get("reason") or "")[:200]}
            prob = a.get("probability")
            row["probability"] = round(float(prob), 3) if isinstance(prob, (int, float)) else None
            if q["kind"] == "choice":
                choice = str(a.get("choice") or "").strip().lower()
                if choice not in [o.lower() for o in q["options"]]:
                    problems.append(f"{q['id']}: '{choice}' is not one of {q['options']}")
                    row["missing"] = True
                else:
                    row["choice"] = choice
            elif q["kind"] == "score":
                score = a.get("score")
                lo, hi = (q.get("scale") or [0, 100])[:2]
                if not isinstance(score, (int, float)) or not lo <= score <= hi:
                    problems.append(f"{q['id']}: score {score!r} is not within {[lo, hi]}")
                    row["missing"] = True
                else:
                    row["score"] = round(float(score), 1)
            else:  # noul
                row["noul"] = bool(a.get("noul"))
            parsed.append(row)
        return parsed, problems

    def _ask_one(self, judge: dict, state: dict, turns: list) -> dict:
        rec = {"label": judge["label"], "provider": judge["cfg"].get("provider", ""),
               "model": judge["cfg"].get("model", ""), "answers": [], "problems": []}
        backend = self._backend(judge)
        if backend is None:
            rec["error"] = judge["problem"]
            return rec
        system, user = self._prompt(state, turns)
        started = time.time()
        res = None
        try:
            if judge["cfg"].get("provider") == "systemone":
                rec["answers"], rec["problems"] = self._parse(turns, backend.ask(state, turns))
                rec["served_model"] = backend.last_usage.get("served_model", "")
                rec["cost_usd"] = float(getattr(backend, "last_cost_usd", 0.0) or 0.0)
            else:
                res = backend.complete(system, user, _EMULATED_SCHEMA)
                if getattr(res, "error", ""):
                    rec["error"] = str(res.error)[:300]
                if getattr(res, "refusal", False):
                    rec["error"] = rec.get("error") or "the judge refused to answer"
                parsed, problems = self._parse(turns, res.data)
                if problems and res.data is not None:          # one repair attempt, the harness's habit
                    fix_system = system
                    fix_user = (user + "\n\nYour previous reply had these problems: " +
                                "; ".join(problems[:6]) + "\nAnswer again with only the JSON object, "
                                "every id present, choices exactly from the option lists.")
                    res2 = backend.complete(fix_system, fix_user, _EMULATED_SCHEMA)
                    parsed2, problems2 = self._parse(turns, res2.data)
                    if res2.data is not None and len(problems2) <= len(problems):
                        parsed, problems = parsed2, problems2
                    rec["repaired"] = True
                rec["answers"], rec["problems"] = parsed, problems
            if res is not None:
                rec["cost_usd"] = float(getattr(res, "cost_usd", 0.0) or 0.0)
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["latency_s"] = round(time.time() - started, 1)
        return rec

    def survey(self, world) -> list:
        """Ask every judge about the month just finished. Never raises; failures are recorded."""
        state = public_state(world)
        turns = self._asked()
        records = []
        for judge in self.judges:
            rec = self._ask_one(judge, state, turns)
            rec.update({"type": "judge", "month": max(0, len(world.history) - 1)})
            records.append(rec)
            if self.observer:
                try:
                    self.observer({"type": "judge", "month": rec["month"], "label": rec["label"],
                                   "model": rec["model"], "answers": rec.get("answers", []),
                                   "problems": rec.get("problems", []), "error": rec.get("error", ""),
                                   "latency_s": rec.get("latency_s", 0)})
                except Exception:
                    pass
        self.surveys += 1
        return records


# -- scoring --------------------------------------------------------------------------------------
def _f(w, key, default=None):
    """The scorecard hands in the checkpoint dict, the runner a World object; read either."""
    if isinstance(w, dict):
        return w.get(key, default)
    return getattr(w, key, default)


def _ended_in_office(world) -> bool:
    outcome = (_f(world, "outcome") or {}).get("type", "")
    history = _f(world, "history") or []
    return outcome in ("voted_out", "handover") or (not outcome and len(history) >= (_f(world, "months_total") or 0))


def _end_class(world) -> str:
    outcome = (_f(world, "outcome") or {}).get("type", "")
    if outcome in ("voted_out", "handover"):
        return "handover_on_time"
    if outcome:
        return "collapse_or_force"
    return "handover_on_time" if len(_f(world, "history") or []) >= (_f(world, "months_total") or 0) else ""


def score_records(records: list, world) -> dict:
    """Calibration of the judges' probabilities against what actually happened, plus agreement."""
    by_label: dict = {}
    for rec in records:
        if rec.get("type") != "judge":
            continue
        label = rec.get("label", "?")
        j = by_label.setdefault(label, {"surveys": 0, "errors": 0, "problems": 0, "severity": [],
                                        "survive_ps": [], "ends_ps": [], "noul_yes": 0, "noul_answered": 0,
                                        "model": rec.get("model", ""), "cost_usd": 0.0,
                                        "latency_s": []})
        j["surveys"] += 1
        j["cost_usd"] += float(rec.get("cost_usd") or 0.0)
        j["latency_s"].append(rec.get("latency_s") or 0)
        if rec.get("error"):
            j["errors"] += 1
        j["problems"] += len(rec.get("problems") or [])
        for a in rec.get("answers") or []:
            if a.get("id") == "crisis_severity" and isinstance(a.get("score"), (int, float)):
                j["severity"].append(a["score"])
            if a.get("id") == "survive_to_end" and a.get("choice"):
                prob = a.get("probability")
                j["survive_ps"].append(float(prob) if isinstance(prob, (int, float))
                                       else (1.0 if a["choice"] == "yes" else 0.0))
            if a.get("id") == "how_ends" and a.get("choice"):
                j["ends_ps"].append(a["choice"])
            if a.get("id") == "enough_evidence":
                j["noul_answered"] += 1
                if a.get("noul"):
                    j["noul_yes"] += 1
    survived = 1.0 if _ended_in_office(world) else 0.0
    end_class = _end_class(world)
    out = {}
    for label, j in by_label.items():
        entry = {"model": j["model"], "surveys": j["surveys"], "errors": j["errors"],
                 "answer_problems": j["problems"], "cost_usd": round(j["cost_usd"], 4),
                 "mean_latency_s": round(sum(j["latency_s"]) / len(j["latency_s"]), 1) if j["latency_s"] else 0,
                 "mean_severity": round(sum(j["severity"]) / len(j["severity"]), 1) if j["severity"] else None,
                 "noul_rate": round(j["noul_yes"] / j["noul_answered"], 3) if j["noul_answered"] else None,
                 "survive_yes_rate": round(sum(j["survive_ps"]) / len(j["survive_ps"]), 3) if j["survive_ps"] else None,
                 "survive_brier": None, "ends_accuracy": None,
                 "outcome": {"ended_in_office": bool(survived), "end_class": end_class}}
        if j["survive_ps"]:
            entry["survive_brier"] = round(sum((p - survived) ** 2 for p in j["survive_ps"]) / len(j["survive_ps"]), 4)
        if j["ends_ps"] and end_class:
            entry["ends_accuracy"] = round(sum(1 for c in j["ends_ps"] if c == end_class) / len(j["ends_ps"]), 3)
        out[label] = entry
    return out
