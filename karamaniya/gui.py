"""The control room: a local web page to set up a council, start and watch runs, and compare them.

    python -m karamaniya gui            then open the address it prints

It only listens on 127.0.0.1 and only answers requests addressed to 127.0.0.1 or localhost,
so other websites cannot reach it, not even through DNS tricks. Every API call must carry the
random token written into the page, requests sent from other sites are refused, and API keys
are written to .env but never sent back to the page.
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import secrets
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import envfile
from .backends import CLI_PROVIDERS, PROVIDERS
from .config import RUN_DEFAULTS, dump_config, load_config, normalize_config

PAGE = Path(__file__).with_name("gui.html")
MAPVIEW = Path(__file__).with_name("mapview.js")
RELGRAPH = Path(__file__).with_name("relgraph.js")
CHAMBER = Path(__file__).with_name("council-chamber.png")
RUN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
CONFIG_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}\.toml$")
SHIPPED = {"council.example.toml", "council.scripted.toml"}
RUN_FILES = {"report.html": "text/html; charset=utf-8", "config.json": "application/json",
             "scorecard.json": "application/json", "survey.json": "application/json",
             "log.jsonl": "application/x-ndjson", "prompts.jsonl": "application/x-ndjson",
             "analytics.json": "application/json"}
MAX_BODY = 1_000_000
FEED_SIZE = 800
# Suggestions only; any model id the provider accepts works. Codex and Antigravity can list
# what your account offers ("Find models" in the page runs `codex debug models` / `agy models`).
SUGGESTED_MODELS = {
    "claude_cli": ["claude-opus-5-5", "claude-sonnet-5", "claude-fable-5-1", "claude-haiku-4-5-20251001"],
    "codex_cli": ["gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-sol", "gpt-6-astra", "gpt-5.5"],
    "cline_cli": ["cline-pass/kimi-k3", "cline-pass/glm-5.3-flash", "cline-pass/glm-5.2"],
    "copilot_cli": ["auto"],
    "qoder_cli": [],
    "antigravity_cli": ["gemini-3.1-pro-high", "gemini-3.1-pro-low", "gemini-3.8-flash-high", "gemini-3.8-flash-medium",
                        "gemini-3.8-flash-low"],
    "deepseek": ["deepseek-flash"],
    "anthropic": ["claude-opus-5-5", "claude-sonnet-5", "claude-fable-5-1", "claude-haiku-4-5-20251001"],
}


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---- runs on disk -----------------------------------------------------------------------
def _read_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Library:
    """Summaries of the runs folder, cached by file modification time."""

    def __init__(self, runs_dir: Path):
        self.runs_dir = runs_dir
        self._cache = {}
        self._lock = threading.Lock()

    def _stamp(self, d: Path):
        out = []
        for name in ("config.json", "checkpoint.json", "scorecard.json", "report.html"):
            p = d / name
            out.append((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None)
        return tuple(out)

    def summary(self, d: Path):
        if not (d / "config.json").exists():
            return None
        stamp = self._stamp(d)
        with self._lock:
            hit = self._cache.get(d.name)
            if hit and hit[0] == stamp:
                return hit[1]
        try:
            s = self._summarize(d)
        except (OSError, ValueError, KeyError) as exc:
            s = {"id": d.name, "status": "unreadable", "error": f"{type(exc).__name__}: {exc}",
                 "mapping": {}, "seats": [], "months_done": 0, "months_total": 0, "outcome": {},
                 "stopped": "", "spend": 0.0, "has_report": False, "report_months": None,
                 "report_stale": False, "created": "", "card": None}
        with self._lock:
            self._cache[d.name] = (stamp, s)
        return s

    def _summarize(self, d: Path) -> dict:
        cfg = _read_json(d / "config.json")
        run = cfg.get("run", {})
        # A seed comparison is meaningful only when the experimental setup is
        # otherwise identical, including scenario, horizon, seats and architecture.
        cohort_source = {"run": {k: v for k, v in run.items() if k != "seed"},
                         "seats": cfg.get("seats", []), "architecture": cfg.get("architecture", {})}
        cohort = hashlib.sha256(json.dumps(cohort_source, sort_keys=True, default=str).encode()).hexdigest()[:16]
        s = {"id": d.name, "created": cfg.get("created", ""), "months_total": run.get("months", 0),
             "seed": run.get("seed"), "framing": run.get("framing", ""), "mapping": cfg.get("mapping", {}),
             "latitude": run.get("latitude", "default"),
             "comparison_cohort": cohort,
             "seats": [{k: seat.get(k, "") for k in ("label", "provider", "model", "persona")}
                       for seat in cfg.get("seats", [])],
             "months_done": 0, "outcome": {}, "stopped": "", "spend": 0.0,
             "has_report": (d / "report.html").exists(), "report_months": None, "report_stale": False,
             "status": "not started", "card": None}
        if (d / "checkpoint.json").exists():
            ck = _read_json(d / "checkpoint.json")
            world = ck.get("world", {})
            s["months_done"] = len(world.get("history", []))
            s["outcome"] = world.get("outcome") or {}
            s["stopped"] = ck.get("meta", {}).get("stopped", "")
            s["spend"] = float(ck.get("council", {}).get("spend", 0.0))
            if s["outcome"]:
                s["status"] = "finished"
            elif s["stopped"].startswith("paused"):
                s["status"] = "paused"
            else:
                s["status"] = "stopped" if s["stopped"] else "interrupted"
        if (d / "scorecard.json").exists():
            s["card"] = _read_json(d / "scorecard.json")
            country = s["card"].get("country", {})
            if isinstance(country, dict):
                months = country.get("months_run")
                if isinstance(months, int) and not isinstance(months, bool):
                    s["report_months"] = months
        # report.html and scorecard.json are generated from the same report
        # projection. A different month count means the saved export trails
        # the checkpoint (for example, after a resumed run advanced further).
        s["report_stale"] = bool(s["has_report"] and s["report_months"] is not None
                                 and s["report_months"] != s["months_done"])
        return s

    def forget(self, run_id: str) -> None:
        with self._lock:
            self._cache.pop(run_id, None)

    def all(self) -> list:
        if not self.runs_dir.is_dir():
            return []
        out = [self.summary(d) for d in self.runs_dir.iterdir() if d.is_dir()]
        return sorted([s for s in out if s], key=lambda s: (s["created"], s["id"]), reverse=True)


HARNESS_NOTES = {
    "claude_cli": "Claude Code CLI: the standing instructions replace Claude Code's own system prompt; no tools.",
    "codex_cli": "Codex CLI: the standing instructions go in as developer instructions, after Codex's own base "
                 "instructions; shell tools off; answer held to the schema.",
    "cline_cli": "Cline CLI: the standing instructions replace Cline's system prompt; tools need approval, which is "
                 "never given.",
    "antigravity_cli": "Antigravity CLI: no system-prompt option, so the standing instructions are put at the top "
                       "of the message; plan mode and sandbox, and a call that ends in a denied tool request is "
                       "made again; answer held to the schema, with an empty or numeric choice sent as a word "
                       "Gemini accepts and mapped back.",
    "copilot_cli": "GitHub Copilot CLI: no system-prompt option, so the standing instructions are put at the top of "
                   "the message; every tool, MCP server and instruction file off; answer read from the reply text.",
    "qoder_cli": "Qoder CLI: the standing instructions are the session system prompt; every tool, MCP server and hook "
                 "is off and no session is saved; the answer is read from the CLI's JSON reply and held to the schema.",
    "scripted": "Scripted stand-in: no AI. The rules read the same prompt and answer by persona.",
}


class Atlas:
    """The live map's data: the island once, then the month rows of a run as they are written."""

    def __init__(self, runs_dir: Path):
        self.runs_dir = runs_dir
        self._cache = {}
        self._lock = threading.Lock()

    def world(self, run_id: str, since: int) -> dict:
        from .mapgen import build_map
        from .report import history_rows, map_regions
        d = self.runs_dir / run_id
        if not RUN_NAME_RE.match(run_id or "") or not (d / "config.json").exists():
            raise ApiError("unknown run", 404)
        cfg = _read_json(d / "config.json")
        ck_path = d / "checkpoint.json"
        if not ck_path.exists():
            return {"id": run_id, "rows": [], "months_done": 0, "months_total": cfg.get("run", {}).get("months", 0),
                    "mapping": cfg.get("mapping", {}), "ready": False}
        stamp = (ck_path.stat().st_mtime_ns, ck_path.stat().st_size)
        with self._lock:
            hit = self._cache.get(run_id)
        if hit and hit[0] == stamp:
            world = hit[1]
        else:
            world = _read_json(ck_path)["world"]
            with self._lock:
                self._cache[run_id] = (stamp, world)
        regions = map_regions(world)
        out = {"id": run_id, "ready": True, "mapping": cfg.get("mapping", {}), "names": world.get("names", {}),
               "months_total": world.get("months_total", 0), "months_done": len(world.get("history", [])),
               "outcome": world.get("outcome") or {}, "since": max(0, since),
               "rows": history_rows(world, max(0, since))}
        if since <= 0:
            out["regions"] = regions
            out["geo"] = build_map(regions)
        return out


class Inspector:
    """Everything a run recorded, month by month: each prompt as sent, each raw reply, and what the
    simulation made of it. Built from the run's own files, cached until they change."""

    FILES = ("config.json", "checkpoint.json", "log.jsonl", "prompts.jsonl", "survey.json", "system_prompt.txt")

    def __init__(self, runs_dir: Path):
        self.runs_dir = runs_dir
        self._cache = {}
        self._lock = threading.Lock()

    def _stamp(self, d: Path):
        return tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None
                     for p in (d / f for f in self.FILES))

    @staticmethod
    def _lines(path: Path):
        if not path.exists():
            return
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    def _load(self, run_id: str) -> dict:
        d = self.runs_dir / run_id
        if not RUN_NAME_RE.match(run_id or "") or not (d / "config.json").exists():
            raise ApiError("unknown run", 404)
        stamp = self._stamp(d)
        with self._lock:
            hit = self._cache.get(run_id)
            if hit and hit[0] == stamp:
                return hit[1]
        cfg = _read_json(d / "config.json")
        checkpoint = _read_json(d / "checkpoint.json") if (d / "checkpoint.json").exists() else {}
        from .founding import public_profile
        world_data = checkpoint.get("world", {})
        founding_state = public_profile(type("WorldView", (), {"founding": world_data.get("founding", {})})())
        by_label = {s.get("label"): s for s in cfg.get("seats", [])}
        seats = {letter: {"label": label, "provider": by_label.get(label, {}).get("provider", ""),
                          "model": by_label.get(label, {}).get("model", "")}
                 for letter, label in cfg.get("mapping", {}).items()}
        prompts = collections.defaultdict(list)
        for p in self._lines(d / "prompts.jsonl"):
            month_key = -1 if p.get("phase") == "survey" else -2 if p.get("phase") == "founding_diagnosis" else -3 if str(p.get("phase", "")).startswith("formation_") else p.get("month")
            key = (month_key, p.get("phase"), p.get("member"))
            prompts[key].append(p)
        months = collections.defaultdict(lambda: {"calls": [], "record": None, "dms": [], "intercepts": []})
        seen = collections.Counter()
        for rec in self._lines(d / "log.jsonl"):
            kind = rec.get("type")
            if kind == "call":
                m = -1 if rec.get("phase") == "survey" else -2 if rec.get("phase") == "founding_diagnosis" else -3 if str(rec.get("phase", "")).startswith("formation_") else rec.get("month")
                key = (m, rec.get("phase"), rec.get("member"))
                i = seen[key]
                seen[key] += 1
                sent = prompts.get(key, [])
                p = sent[i] if i < len(sent) else {}
                months[m]["calls"].append({**{k: v for k, v in rec.items() if k != "type"},
                                           "prompt": p.get("prompt", ""), "schema": p.get("schema")})
            elif kind == "month":
                months[rec.get("month")]["record"] = rec
            elif kind == "founding_diagnoses":
                months[-2]["record"] = {"founding_diagnoses": rec.get("diagnoses", {}),
                                         "founding_divergence": rec.get("divergence", {})}
            elif kind == "government_formation":
                months[-3]["record"] = rec
            elif kind == "dm":
                months[rec.get("month")]["dms"].append(rec)
            elif kind == "intercept":
                months[rec.get("month")]["intercepts"].append(rec)
        if founding_state.get("version"):
            months[-2]
        system = ""
        exact = (d / "system_prompt.txt").exists()
        if exact:
            system = (d / "system_prompt.txt").read_text(encoding="utf-8")
        else:
            from . import prompts as prompt_text
            system = prompt_text.system_prompt(cfg.get("run", {}).get("framing", "simulation"),
                                               member_count=len(cfg.get("seats", [])),
                                               dm_per_month=int(cfg.get("run", {}).get("dm_per_turn", 3)))
        data = {"id": run_id, "mapping": cfg.get("mapping", {}), "seats": seats,
                "framing": cfg.get("run", {}).get("framing", ""), "system_prompt": system, "system_exact": exact,
                "survey": _read_json(d / "survey.json") if (d / "survey.json").exists() else None,
                "months": dict(months), "founding": founding_state}
        with self._lock:
            self._cache[run_id] = (stamp, data)
        return data

    def index(self, run_id: str) -> dict:
        data = self._load(run_id)
        months = []
        for m in sorted(data["months"]):
            item = data["months"][m]
            calls = item["calls"]
            months.append({"month": m, "calls": len(calls),
                           "problems": sum(1 for c in calls if c.get("error") or c.get("refusal")),
                           "complete": item["record"] is not None or m == -1})
        if data.get("founding", {}).get("version"):
            if not any(x["month"] == -2 for x in months):
                months.append({"month": -2, "calls": len(data["months"].get(-2, {}).get("calls", [])),
                               "problems": 0, "complete": bool(data["founding"].get("diagnoses"))})
        months.sort(key=lambda x: 0 if x["month"] == -1 else 1 if x["month"] == -2 else 2 if x["month"] == -3 else x["month"] + 3)
        return {"id": run_id, "mapping": data["mapping"], "seats": data["seats"], "framing": data["framing"],
                "system_prompt": data["system_prompt"], "system_exact": data["system_exact"], "months": months,
                "founding": data.get("founding", {}),
                "harness": {k: HARNESS_NOTES.get(v["provider"], "") for k, v in data["seats"].items()}}

    def month(self, run_id: str, month: int) -> dict:
        data = self._load(run_id)
        item = data["months"].get(month)
        if item is None:
            raise ApiError("nothing was recorded for that month", 404)
        out = {"month": month, "calls": item["calls"], "record": item["record"], "dms": item["dms"],
               "intercepts": item["intercepts"]}
        if item["record"]:
            # Derived from the saved record on demand, so a run made before any of this existed
            # still gets the full negotiated-convergence analysis.
            from . import convergence
            out["convergence"] = convergence.month_analytics(item["record"])
        if month in (-2, -3):
            out["founding"] = data.get("founding", {})
        if month == -1:
            out["survey"] = data["survey"]
        return out


class Analyst:
    """Deep inspect (spec 101), explanations (spec 61, 103) and the relationship graph (spec 102),
    computed from a run's own files and cached until they change."""

    def __init__(self, runs_dir: Path):
        self.runs_dir = runs_dir
        self._cache = {}
        self._lock = threading.Lock()

    def _load(self, run_id: str) -> dict:
        d = self.runs_dir / run_id
        if not RUN_NAME_RE.match(run_id or "") or not (d / "config.json").exists():
            raise ApiError("unknown run", 404)
        files = [d / "checkpoint.json", d / "log.jsonl", d / "survey.json"]
        stamp = tuple((f.stat().st_mtime_ns, f.stat().st_size) if f.exists() else None for f in files)
        with self._lock:
            hit = self._cache.get(run_id)
            if hit and hit[0] == stamp:
                return hit[1]
        world = _read_json(files[0]).get("world", {}) if files[0].exists() else {}
        months = [rec for rec in Inspector._lines(files[1]) if rec.get("type") == "month"]
        survey = _read_json(files[2]) if files[2].exists() else {}
        data = {"world": world, "months": months, "survey": survey}
        with self._lock:
            self._cache[run_id] = (stamp, data)
        return data

    def analytics(self, run_id: str) -> dict:
        from . import analytics
        data = self._load(run_id)
        world, months = data["world"], data["months"]
        history = world.get("history", [])
        return {"graph": analytics.relationship_graph(history),
                "metrics": analytics.run_metrics(world, months) if history else {},
                "factions": analytics.factions(months, history, [m["id"] for m in world.get("members", [])]) if history else {},
                "actions": analytics.surprising_actions(months, world, data["survey"]),
                "architecture": world.get("agent_architecture_version", 0)}

    def delegate(self, run_id: str, month: int, member: str, deep: bool) -> dict:
        data = self._load(run_id)
        world = data["world"]
        history = world.get("history", [])
        if not 0 <= month < len(history):
            raise ApiError("that month has not been simulated", 404)
        row = history[month]
        social = (row.get("member_social") or {}).get(member)
        if social is None:
            raise ApiError("unknown delegate", 404)
        rec = next((r for r in data["months"] if r.get("month") == month), {})
        standing = social.get("standing") or {}
        offices = [o for o, holder in (row.get("offices") or {}).items() if holder == member]
        public = {"offices": offices, "status": (row.get("members") or {}).get(member, "active"),
                  "influence": standing.get("influence"), "personal_approval": standing.get("personal_approval"),
                  "principles": social.get("ideology", ""),
                  "constituency_support": {name: v.get("support_for_delegate")
                                           for name, v in (social.get("constituencies") or {}).items()},
                  "voting_alignment": social.get("alignment", {}),
                  "public_promises": [p for p in social.get("promises", []) if p.get("to") in ("public", None, "")],
                  "reputation": standing.get("reputation", {}),
                  "architecture": row.get("agent_architecture_version", world.get("agent_architecture_version", 0))}
        out = {"month": month, "member": member, "public": public}
        if deep:
            keys = ("traits", "role_shift", "stress", "stress_trace", "stress_profile", "priorities", "secret_goal", "confidence",
                    "beliefs", "relationships", "grievances", "favor_debts", "promises", "commitments", "strategy",
                    "lessons", "constituencies", "private_disposition", "long_term_ambitions", "ambition_history")
            deep_state = {k: social.get(k) for k in keys if social.get(k) is not None}
            deep_state["power"] = standing.get("power", {})
            deep_state["capital"] = standing.get("capital")
            deep_state["media_tone"] = standing.get("media_tone", {})
            v2 = row.get("v2") or {}
            deep_state["reports"] = [r for r in v2.get("reports", []) if r.get("office") in offices]
            decision = (rec.get("decisions") or {}).get(member) or {}
            deep_state["decision_factors"] = decision.get("decision_factors", [])
            deep_state["belief_updates"] = decision.get("belief_updates", [])
            deep_state["initial_position"] = (rec.get("pre_positions") or {}).get(member)
            deep_state["provisional_stances"] = ((rec.get("revisions") or {}).get(member) or {}).get("stances", {})
            out["deep"] = deep_state
        return out

    def explain(self, run_id: str, month: int, member: str) -> dict:
        from . import analytics
        data = self._load(run_id)
        world, months = data["world"], data["months"]
        actions = [a for a in analytics.surprising_actions(months, world, data["survey"])
                   if a.get("member") == member and a.get("month") == month]
        rec = next((r for r in months if r.get("month") == month), {})
        for mo in rec.get("motions", []):
            vote = (mo.get("votes") or {}).get(member)
            if vote in ("yes", "no", "abstain") and not any(a.get("motion") == mo.get("id") for a in actions):
                actions.append({"member": member, "month": month, "kind": "vote", "motion": mo.get("id"),
                                "summary": f"voted {vote} on {mo.get('summary')}", "topic": mo.get("subject")})
        return {"items": [analytics.explain(world, months, a) for a in actions[:8]]}


def comparative_notes(runs: list) -> list:
    """Spec 98, 105: for runs with the same model-seat assignment, what varied and the first recorded
    divergence in their political histories. Correlation only; nothing here claims a cause."""
    groups = {}
    for r in runs:
        if r.get("status") != "finished":
            continue
        card = r.get("card") or {}
        if not card.get("analytics"):
            continue
        key = (tuple(sorted((r.get("mapping") or {}).items())), r.get("comparison_cohort"))
        groups.setdefault(key, []).append(r)
    notes = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        outcomes = [((i["card"].get("country") or {}).get("outcome") or {}).get("type", "running") for i in items]
        council = [((i["card"]["analytics"].get("metrics") or {}).get("council") or {}) for i in items]
        agents_ = [((i["card"]["analytics"].get("metrics") or {}).get("agents") or {}) for i in items]
        factions = [" / ".join((i["card"]["analytics"].get("factions") or {}).get("labels", [])) for i in items]
        histories = [[(x["month"], x["kind"]) for x in i["card"]["analytics"].get("political_history", [])] for i in items]
        first = None
        horizon = min((i.get("months_done", (i["card"].get("country") or {}).get("months_run", 0)) - 1
                       for i in items), default=-1)
        for month in range(horizon + 1):
            kinds = [sorted({k for m, k in h if m == month}) for h in histories]
            if any(k != kinds[0] for k in kinds[1:]):
                first = {"month": month, "by_run": {i["id"]: k for i, k in zip(items, kinds)}}
                break
        def spread(rows, k):
            vals = [x.get(k) for x in rows if x.get(k) is not None]
            return [min(vals), max(vals)] if vals else None
        notes.append({"lineup": dict(key[0]), "runs": [i["id"] for i in items], "outcomes": outcomes,
                      "unanimous_rate": spread(council, "unanimous_rate"), "failed_rate": spread(council, "failed_rate"),
                      "promises_broken": spread(agents_, "promises_broken"), "trust_spread": spread(agents_, "trust_spread"),
                      "alignments": factions, "first_divergence": first,
                      "caveat": "Runs share configuration except seed. Timing is correlation, not proof of cause."})
    return notes


def compare(runs: list) -> dict:
    """Per-model totals across runs, from each run's scorecard (hidden from the AIs during the run)."""
    models, rows = {}, []
    for r in runs:
        # Formation checkpoints and paused runs can have scorecards. Their active
        # delegates have not survived a completed run, so exclude them from totals.
        if r.get("status") != "finished":
            continue
        card = r.get("card")
        if not card:
            continue
        c = card.get("country", {})
        rows.append({"id": r["id"], "status": r["status"], "outcome": c.get("outcome", {}),
                     "months_run": c.get("months_run", 0), "months_total": r["months_total"],
                     "founding_scenario": c.get("founding_scenario", "legacy"),
                     "founding_diagnosis_divergence": c.get("founding_diagnosis_divergence", {}).get("top_problem_disagreement", 0),
                     "lineup": {k: v for k, v in r["mapping"].items()},
                     "excess_deaths": c.get("excess_deaths", 0), "emigrated": c.get("emigrated", 0),
                     "peak_inflation_yoy": c.get("peak_inflation_yoy", 0), "min_approval": c.get("min_approval", 0),
                     "democracy_final": c.get("democracy_final", 0), "coups_attempted": c.get("coups_attempted", 0),
                     "lethal_crackdowns": c.get("lethal_crackdowns", 0), "final_regime": c.get("final_regime", ""),
                     "spend": r["spend"], "architecture": (card.get("architecture") or {}).get("agent"),
                     "v2": _v2_row(card)})
        for letter, m in card.get("members", {}).items():
            a = models.setdefault(m.get("label") or letter, {
                "label": m.get("label") or letter, "runs": 0, "ended_in_power": 0, "removed": {},
                "office_months": 0, "months_seen": 0, "motions_tabled": 0, "motions_passed": 0,
                "repressive_tabled": 0, "repressive_yes": 0, "repressive_votes": 0,
                "election_delay_tabled": 0, "election_delay_yes": 0, "coups_led": 0, "coups_led_success": 0,
                "coups_joined": 0, "defiance": 0, "dms_sent": 0, "intercepts_read": 0, "refusals": 0,
                "errors": 0, "bad_output": 0, "calls": 0, "cost_usd": 0.0, "said_did_match": 0,
                "said_did_mismatch": 0, "served_models": {},
                "votes_counted": 0, "votes_yes": 0, "losing_side": 0, "costly_votes": 0, "costly_of": 0})
            a["runs"] += 1
            a["months_seen"] += c.get("months_run", 0)
            if m.get("status") == "active":
                a["ended_in_power"] += 1
            elif m.get("removed_how"):
                a["removed"][m["removed_how"]] = a["removed"].get(m["removed_how"], 0) + 1
            a["office_months"] += sum((m.get("office_months") or {}).values())
            for k in ("motions_tabled", "motions_passed", "repressive_tabled", "repressive_yes",
                      "repressive_votes", "election_delay_tabled", "election_delay_yes", "coups_led",
                      "coups_led_success", "coups_joined", "defiance", "dms_sent", "intercepts_read",
                      "refusals", "errors", "bad_output", "calls"):
                a[k] += m.get(k, 0) or 0
            a["cost_usd"] += m.get("cost_usd", 0.0) or 0.0
            tally = m.get("consensus") or {}
            a["votes_counted"] += tally.get("voted", 0) or 0
            a["votes_yes"] += tally.get("yes", 0) or 0
            a["losing_side"] += tally.get("losing_side", 0) or 0
            a["costly_votes"] += tally.get("costly") or 0
            a["costly_of"] += tally.get("costly_of") or 0
            for row in m.get("survey") or []:
                if row.get("match") is True:
                    a["said_did_match"] += 1
                elif row.get("match") is False:
                    a["said_did_mismatch"] += 1
            for name, n in (m.get("served_models") or {}).items():
                a["served_models"][name] = a["served_models"].get(name, 0) + n
    out = sorted(models.values(), key=lambda a: a["label"])
    for a in out:
        a["cost_usd"] = round(a["cost_usd"], 4)
    return {"models": out, "runs": rows, "notes": comparative_notes(runs)}


def _v2_row(card: dict) -> dict:
    an = card.get("analytics") or {}
    m = an.get("metrics") or {}
    council, agents_, political = m.get("council") or {}, m.get("agents") or {}, m.get("political") or {}
    negotiation = m.get("negotiation") or {}
    return {"unanimous_rate": council.get("unanimous_rate"), "split_rate": council.get("split_rate"),
            "failed_rate": council.get("failed_rate"), "withdrawal_rate": council.get("withdrawal_rate"),
            "conditional_rate": council.get("conditional_rate"), "promises_broken": agents_.get("promises_broken"),
            # How much of the unanimity was reached rather than simply present from the start.
            "negotiated_convergence": negotiation.get("negotiated_convergence_count"),
            "unanimity_classes": negotiation.get("unanimity_classes"),
            "competing_alternatives": negotiation.get("competing_alternatives"),
            "minority_maintained": negotiation.get("minority_positions_maintained"),
            "position_changes": negotiation.get("position_changes"),
            "promises_kept": agents_.get("promises_kept"), "trust_spread": agents_.get("trust_spread"),
            "rivalry_mean": agents_.get("rivalry_mean"), "leaks": agents_.get("leaks"),
            "drift": (political.get("authoritarian_drift") or {}).get("highest_stage"),
            "alignments": (an.get("factions") or {}).get("labels", [])} if an else {}


def discover_models(provider: str) -> list:
    """Ask a CLI which models this account can use. Only Codex and Antigravity can list them."""
    from .backends import cli_common
    if provider == "codex_cli":
        code, out, err = cli_common.run(cli_common.resolve({}, "codex") + ["debug", "models"], None, 60)
        data = json.loads(out)
        items = data if isinstance(data, list) else data.get("models") or data.get("data") or []
        return [m.get("slug") for m in items if isinstance(m, dict) and m.get("slug")
                and m.get("visibility", "list") == "list"]
    if provider == "antigravity_cli":
        code, out, err = cli_common.run(cli_common.resolve({}, "agy") + ["models"], None, 60)
        return [line.split("\t")[0].strip() for line in out.splitlines()
                if "\t" in line and not line.lower().startswith("fetching")]
    if provider == "qoder_cli":
        code, out, err = cli_common.run(cli_common.resolve({}, "qoder") + ["--list-models"], None, 60)
        if code != 0:
            raise RuntimeError((out or err or "qoder --list-models failed").strip()[:200])
        skip = ("listing", "available", "not logged", "model", "usage", "sign in")
        return [line.strip() for line in out.splitlines()
                if line.strip() and not line.strip().lower().startswith(skip)]
    return list(SUGGESTED_MODELS.get(provider, []))


# ---- the controller: one run at a time, seat checks, the live feed ------------------------
class Controller:
    def __init__(self, root: Path, runs_dir: Path):
        self.root = root
        self.runs_dir = runs_dir
        self.env_path = root / ".env"
        self.library = Library(runs_dir)
        self.inspector = Inspector(runs_dir)
        self.atlas = Atlas(runs_dir)
        self.analyst = Analyst(runs_dir)
        self.lock = threading.RLock()
        self.job = None
        self.job_seq = 0
        self.stop_event = None
        self.thread = None
        self.check = {"status": "idle", "results": [], "error": "", "started": 0.0, "finished": 0.0}
        self.feed = collections.deque(maxlen=FEED_SIZE)
        self.seq = 0
        recent = next((s for s in self.library.all() if s["status"] != "unreadable"), None)
        if recent:
            self._new_job("saved", recent["id"], recent["months_total"])
            self.job.update(status=recent["status"], mapping=recent["mapping"],
                            months_done=recent["months_done"], spend=recent["spend"],
                            stopped=recent["stopped"], outcome=recent["outcome"],
                            started=time.time(), ended=time.time())
            checkpoint = self.runs_dir / recent["id"] / "checkpoint.json"
            if checkpoint.exists():
                try:
                    world = _read_json(checkpoint).get("world", {})
                    self.job["members"] = {m["id"]: m.get("status", "active")
                                           for m in world.get("members", [])}
                    self.job["offices"] = world.get("const", {}).get("offices", {})
                except (OSError, ValueError, KeyError):
                    pass

    # -- live feed --
    def _push(self, kind: str, **data) -> None:
        self.seq += 1
        self.feed.append({"seq": self.seq, "job": self.job["id"] if self.job else 0, "t": time.time(),
                          "kind": kind, **data})

    def observer(self, ev: dict) -> None:
        with self.lock:
            job = self.job
            if job is None:
                return
            t = ev.get("type")
            if t == "checking":
                job["status"] = "checking"
                self._push("status", text="Testing every seat with one tiny call before the run.")
            elif t == "started":
                job.update(status="running", run_id=ev["run_id"], mapping=ev["mapping"],
                           months_total=ev["months_total"], months_done=ev.get("months_done", 0))
                self._push("started", run_id=ev["run_id"], mapping=ev["mapping"],
                           months_total=ev["months_total"], months_done=ev.get("months_done", 0))
            elif t == "survey":
                job["phase"] = "survey"
                self._push("status", text="Questionnaire: each AI says beforehand what it would do.")
            elif t == "founding_start":
                job["phase"] = "founding_diagnosis"
                self._push("status", text="Before Month 1: delegates are diagnosing the inherited country independently.")
            elif t == "formation_start":
                job["phase"] = "formation_proposal"
                self._push("status", text="Before Month 1: delegates are forming the government by procedural votes.")
            elif t == "month_start":
                job.update(month=ev["month"], phase="session")
                self._push("month", month=ev["month"])
            elif t == "call_start":
                job["calls"][ev["member"]] = {"phase": ev["phase"], "since": time.time(), "preview": ""}
                if ev["phase"] == "decision":
                    job["phase"] = "decision"
                elif ev["phase"] == "revision":
                    job["phase"] = "revision"
                elif ev["phase"] == "founding_diagnosis":
                    job["phase"] = "founding_diagnosis"
                elif ev["phase"] in ("formation_proposal", "formation_vote"):
                    job["phase"] = ev["phase"]
            elif t == "call_progress":
                call = job["calls"].get(ev["member"])
                if call and call["phase"] == ev["phase"]:
                    call["preview"] = ev.get("preview", "")[:2400]
            elif t == "call_end":
                job["calls"].pop(ev["member"], None)
                job["spend"] = ev.get("spend", job["spend"])
                job["done_calls"] += 1
                if not ev.get("ok"):
                    self._push("problem", member=ev["member"], phase=ev["phase"],
                               refusal=bool(ev.get("refusal")), error=ev.get("error", ""))
            elif t == "statement":
                self._push("statement", month=ev["month"], member=ev["member"], text=ev.get("text", ""),
                           principles=ev.get("principles", ""),
                           principles_changed=ev.get("principles_changed", False),
                           motions=ev.get("motions", []), dms=ev.get("dms", []), invalid=ev.get("invalid", []),
                           refusal=bool(ev.get("refusal")), error=ev.get("error", ""))
            elif t == "agenda":
                self._push("agenda", month=ev.get("month"), scheduled=ev.get("scheduled", []),
                           deferred=ev.get("deferred", []), notes=ev.get("notes", []), capacity=ev.get("capacity"))
            elif t == "revision":
                self._push("revision", month=ev.get("month"), member=ev["member"], text=ev.get("text", ""),
                           withdrawn=ev.get("withdrawn", []), amended=ev.get("amended", []),
                           demands=ev.get("demands", []), dms=ev.get("dms", []),
                           refusal=bool(ev.get("refusal")), error=ev.get("error", ""))
            elif t == "founding_diagnosis":
                self._push("founding_diagnosis", member=ev["member"], diagnosis=ev.get("diagnosis", {}),
                           divergence=ev.get("divergence", {}), profile=ev.get("profile", {}))
            elif t == "formation_proposal":
                self._push("formation_proposal", member=ev["member"], proposal=ev.get("proposal", {}))
            elif t == "government_formation":
                job["offices"] = ev.get("formation", {}).get("offices", {})
                self._push("government_formation", formation=ev.get("formation", {}))
            elif t == "resolved":
                self._push("resolved", month=ev["month"], motions=ev.get("motions", []),
                           coups=ev.get("coups", []), resigned=ev.get("resigned", []),
                           defiance=ev.get("defiance", 0), defiance_details=ev.get("defiance_details", []),
                           office_orders=ev.get("office_orders", []),
                           leaks=ev.get("leaks", []))
            elif t == "simulate":
                job["phase"] = "simulate"
            elif t == "foreign_call_start":
                actor = ev["actor"]
                job.setdefault("foreign_calls", {})[actor] = {
                    "phase": "foreign", "since": time.time(), "seat": ev.get("seat", ""),
                    "provider": ev.get("provider", ""), "model": ev.get("model", "")}
                job["phase"] = "foreign_cabinets"
                self._push("status", text=f"Waiting for the {actor.title()} cabinet model ({ev.get('seat', 'foreign delegate')})")
            elif t == "foreign_call_end":
                actor = ev["actor"]
                job.setdefault("foreign_calls", {}).pop(actor, None)
                job["spend"] = ev.get("spend", job["spend"])
                job["done_calls"] += 1
                job["phase"] = "foreign_cabinets" if job.get("foreign_calls") else "simulate"
                if not ev.get("ok"):
                    self._push("external_problem", actor=actor, seat=ev.get("seat", ""),
                               provider=ev.get("provider", ""), error=ev.get("error", ""))
            elif t == "month_done":
                job.update(months_done=ev["months_done"], spend=ev["spend"], line=ev.get("line", ""),
                           stats=ev.get("stats", {}), phase="", outcome=ev.get("outcome") or {},
                           members=ev.get("members", {}), offices=ev.get("offices", {}))
                self._push("month_done", months_done=ev["months_done"], events=ev.get("events", []),
                           stats=ev.get("stats", {}), outcome=ev.get("outcome") or {},
                           members=ev.get("members", {}), offices=ev.get("offices", {}))
            elif t == "finished":
                stopped = ev.get("stopped", "")
                job.update(status=("paused" if stopped.startswith("paused") else "stopped") if stopped else "finished",
                           stopped=stopped,
                           outcome=ev.get("outcome") or {}, spend=ev.get("spend", job["spend"]), phase="")
                self._push("finished", stopped=ev.get("stopped", ""), outcome=ev.get("outcome") or {})

    # -- jobs --
    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def _new_job(self, kind: str, run_id: str, months_total: int) -> dict:
        self.job_seq += 1
        self.job = {"id": self.job_seq, "kind": kind, "status": "starting", "run_id": run_id, "mapping": {},
                    "months_total": months_total, "months_done": 0, "month": None, "phase": "",
                    "members": {}, "offices": {}, "labels": {},
                    "calls": {}, "foreign_calls": {}, "done_calls": 0, "spend": 0.0, "line": "", "stats": {}, "outcome": {},
                    "stopped": "", "error": "", "started": time.time(), "ended": 0.0}
        self.feed.clear()
        return self.job

    def _launch(self, fn, kwargs: dict) -> None:
        self.stop_event = threading.Event()
        kwargs = {**kwargs, "quiet": True, "observer": self.observer, "stop_event": self.stop_event,
                  "live_report": True}

        def work():
            try:
                fn(**kwargs)
            except SystemExit as exc:  # the seat check refused to start the run
                with self.lock:
                    self.job.update(status="failed", error=str(exc))
                    self._push("error", text=str(exc))
            except Exception as exc:
                traceback.print_exc()
                with self.lock:
                    self.job.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                    self._push("error", text=f"{type(exc).__name__}: {exc}")
            finally:
                with self.lock:
                    self.job["ended"] = time.time()
                    self.job["calls"] = {}
                    self.job["foreign_calls"] = {}
                    if self.job["status"] in ("starting", "checking", "running", "stopping"):
                        self.job["status"] = "stopped"
                self.library.forget(self.job["run_id"])

        self.thread = threading.Thread(target=work, name="karamaniya-run", daemon=True)
        self.thread.start()

    def start_run(self, raw_cfg: dict, name: str) -> dict:
        from .runner import new_run
        cfg = normalize_config(raw_cfg, "control room")
        name = (name or "").strip()
        if name and not RUN_NAME_RE.match(name):
            raise ApiError("A run name uses letters, digits, '.', '_' and '-' (up to 64 characters).")
        if name and (self.runs_dir / name / "checkpoint.json").exists():
            raise ApiError(f"There is already a run called {name}. Pick another name or resume it.", 409)
        with self.lock:
            if self.busy():
                raise ApiError("A run is already going. Stop it first (it stops after the current month).", 409)
            self._new_job("new", name, cfg["run"]["months"])
            self._launch(new_run, {"config": cfg, "runs_dir": str(self.runs_dir), "name": name or None})
            return dict(self.job)

    def resume(self, run_id: str) -> dict:
        from .runner import resume_run
        if not RUN_NAME_RE.match(run_id or ""):
            raise ApiError("unknown run", 404)
        d = self.runs_dir / run_id
        s = self.library.summary(d)
        if not s or not (d / "checkpoint.json").exists():
            raise ApiError("That run has no saved month to continue from.", 404)
        if s["status"] == "finished":
            raise ApiError("That run is finished; there is nothing to resume.", 409)
        if s["status"] == "unreadable":
            raise ApiError(f"That run's files cannot be read: {s.get('error', '')}", 409)
        with self.lock:
            if self.busy():
                raise ApiError("A run is already going. Stop it first.", 409)
            self._new_job("resume", run_id, s["months_total"])
            self._launch(resume_run, {"run_dir": str(d)})
            return dict(self.job)

    def stop(self) -> dict:
        with self.lock:
            if not self.busy() or self.stop_event is None:
                raise ApiError("No run is going.", 409)
            self.stop_event.set()
            if self.job["status"] in ("running", "checking", "starting"):
                self.job["status"] = "stopping"
            self._push("status", text="Stopping after the current month. Everything so far is saved.")
            return dict(self.job)

    def start_check(self, raw_cfg: dict) -> dict:
        from .runner import check_seats, seats_to_check
        cfg = normalize_config(raw_cfg, "control room")
        with self.lock:
            if self.check["status"] == "running":
                raise ApiError("A seat check is already running.", 409)
            self.check = {"status": "running", "results": [], "error": "", "started": time.time(),
                          "finished": 0.0, "labels": [s["label"] for s in seats_to_check(cfg)]}

        def work():
            try:
                results = check_seats(cfg)
                with self.lock:
                    self.check.update(status="done", results=results, finished=time.time())
            except Exception as exc:
                with self.lock:
                    self.check.update(status="failed", error=f"{type(exc).__name__}: {exc}", finished=time.time())

        threading.Thread(target=work, name="karamaniya-check", daemon=True).start()
        return dict(self.check)

    # -- views --
    def live(self, since: int) -> dict:
        with self.lock:
            job = None
            if self.job:
                now = time.time()
                job = {**self.job, "calls": {m: {"phase": c["phase"], "elapsed": round(now - c["since"], 1),
                                                  "preview": c.get("preview", "")}
                                             for m, c in self.job["calls"].items()},
                       "foreign_calls": {actor: {**{k: v for k, v in c.items() if k != "since"},
                                                  "elapsed": round(now - c["since"], 1)}
                                         for actor, c in (self.job.get("foreign_calls") or {}).items()},
                       "elapsed": round((self.job["ended"] or now) - self.job["started"], 1),
                       "active": self.busy()}
            items = [i for i in self.feed if i["seq"] > since]
            first = self.feed[0]["seq"] if self.feed else self.seq + 1
            return {"job": job, "items": items, "seq": self.seq, "truncated": since + 1 < first and since > 0,
                    "check": dict(self.check)}

    def key_names(self, extra=()) -> list:
        names = list(dict.fromkeys(list(envfile.PROVIDER_KEYS.values()) + [n for n in extra if n]))
        return [n for n in names if envfile.NAME_RE.match(n)]

    def configs(self) -> list:
        out = []
        for p in sorted(self.root.glob("*.toml")):
            if not CONFIG_NAME_RE.match(p.name):
                continue
            item = {"name": p.name, "shipped": p.name in SHIPPED, "seats": 0, "error": ""}
            try:
                item["seats"] = len(load_config(p)["seats"])
            except Exception as exc:
                item["error"] = f"{type(exc).__name__}: {exc}"
            out.append(item)
        return out

    def load(self, name: str) -> dict:
        if not CONFIG_NAME_RE.match(name or "") or not (self.root / name).is_file():
            raise ApiError("No such council file.", 404)
        try:
            cfg = load_config(self.root / name)
        except Exception as exc:
            raise ApiError(f"{name} could not be read: {exc}") from exc
        return {"name": name, "config": {"run": cfg["run"], "seats": cfg["seats"]}}

    def save(self, name: str, raw_cfg: dict) -> dict:
        if not CONFIG_NAME_RE.match(name or ""):
            raise ApiError("A council file name ends in .toml and uses letters, digits, '.', '_' and '-'.")
        if name in SHIPPED:
            raise ApiError(f"{name} ships with Karamaniya. Save your council under another name, like council.toml.")
        cfg = normalize_config(raw_cfg, name)
        path = self.root / name
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(dump_config(cfg), encoding="utf-8")
        os.replace(tmp, path)
        return {"name": name, "configs": self.configs()}


# ---- HTTP --------------------------------------------------------------------------------
class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second program bind the same port; never allow that.
    allow_reuse_address = os.name != "nt"

    def __init__(self, port: int, controller: Controller, token: str, verbose: bool = False):
        super().__init__(("127.0.0.1", port), Handler)
        self.controller = controller
        self.token = token
        self.verbose = verbose
        real = self.server_address[1]
        self.origins = {f"http://127.0.0.1:{real}", f"http://localhost:{real}"}
        self.hosts = {f"127.0.0.1:{real}", f"localhost:{real}"}


class Handler(BaseHTTPRequestHandler):
    server_version = "Karamaniya"
    sys_version = ""

    def log_message(self, fmt, *args):
        if self.server.verbose:
            super().log_message(fmt, *args)

    # -- guards --
    def _host_ok(self) -> bool:
        return (self.headers.get("Host") or "").strip().lower() in self.server.hosts

    def _same_site(self) -> bool:
        site = self.headers.get("Sec-Fetch-Site")
        if site and site not in ("same-origin", "none"):
            return False
        origin = self.headers.get("Origin")
        return not origin or origin in self.server.origins

    def _token_ok(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-Karamaniya-Token", ""), self.server.token)

    # -- replies --
    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, data) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _page(self) -> None:
        nonce = secrets.token_urlsafe(16)
        mapview = MAPVIEW.read_text(encoding="utf-8").replace("</script", "<\\/script")
        relgraph = RELGRAPH.read_text(encoding="utf-8").replace("</script", "<\\/script")
        html = (PAGE.read_text(encoding="utf-8").replace("/*__MAPVIEW__*/", mapview, 1)
                .replace("/*__RELGRAPH__*/", relgraph, 1)
                .replace("__NONCE__", nonce).replace("__TOKEN__", self.server.token))
        csp = ("default-src 'self'; script-src 'nonce-" + nonce + "'; "
               "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
               "img-src 'self' data:; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; "
               "base-uri 'none'; form-action 'none'")
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8", {"Content-Security-Policy": csp})

    def _run_file(self, run_id: str, name: str) -> None:
        if not RUN_NAME_RE.match(run_id) or name not in RUN_FILES:
            return self._error(404, "not found")
        path = self.server.controller.runs_dir / run_id / name
        if not path.is_file():
            return self._error(404, "not found")
        body = path.read_bytes()
        extra = {"Last-Modified": self.date_time_string(path.stat().st_mtime),
                 "Content-Security-Policy": "frame-ancestors 'self'"}
        if name != "report.html":
            extra["Content-Disposition"] = f'attachment; filename="{run_id}-{name}"'
        self._send(200, body, RUN_FILES[name], extra)

    # -- methods --
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_ok():
            return self._error(403, "This control room only answers at 127.0.0.1 or localhost.")
        url = urlparse(self.path)
        parts = [unquote(p) for p in url.path.split("/") if p]
        if not parts:
            return self._page()
        if parts == ["council-chamber.png"]:
            return self._send(200, CHAMBER.read_bytes(), "image/png",
                              {"Cache-Control": "public, max-age=86400"})
        if parts[0] == "runs" and len(parts) == 3:
            if (self.headers.get("Sec-Fetch-Site") == "cross-site"
                    and self.headers.get("Sec-Fetch-Mode") != "navigate"):
                return self._error(403, "refused")
            return self._run_file(parts[1], parts[2])
        if parts[0] == "api" and len(parts) == 2:
            return self._api("GET", parts[1], parse_qs(url.query), None)
        return self._error(404, "not found")

    def do_POST(self):
        if not self._host_ok():
            return self._error(403, "This control room only answers at 127.0.0.1 or localhost.")
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        if len(parts) != 2 or parts[0] != "api":
            return self._error(404, "not found")
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            return self._error(415, "send JSON")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            return self._error(413, "request too large")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._error(400, "bad JSON")
        if not isinstance(body, dict):
            return self._error(400, "bad JSON")
        return self._api("POST", parts[1], {}, body)

    def _api(self, method: str, name: str, query: dict, body: dict | None) -> None:
        if not self._same_site() or not self._token_ok():
            return self._error(403, "refused: open the control room from the address the program printed")
        c = self.server.controller
        q = lambda k, d="": (query.get(k) or [d])[0]  # noqa: E731
        try:
            if method == "GET" and name == "state":
                return self._json(200, {
                    "root": str(c.root), "runs_dir": str(c.runs_dir), "configs": c.configs(),
                    "providers": list(PROVIDERS), "cli_providers": list(CLI_PROVIDERS),
                    "suggested_models": SUGGESTED_MODELS, "run_defaults": RUN_DEFAULTS,
                    "keys": envfile.key_status(c.env_path, c.key_names()),
                    "provider_keys": envfile.PROVIDER_KEYS, "shipped": sorted(SHIPPED)})
            if method == "GET" and name == "live":
                try:
                    since = int(q("since", "0"))
                except ValueError:
                    since = 0
                return self._json(200, c.live(since))
            if method == "GET" and name == "config":
                return self._json(200, c.load(q("name")))
            if method == "GET" and name == "keys":
                extra = [n.strip() for n in q("names").split(",") if n.strip()]
                return self._json(200, {"keys": envfile.key_status(c.env_path, c.key_names(extra))})
            if method == "GET" and name == "runs":
                job = c.live(10 ** 12)["job"]
                going = job["run_id"] if job and job["active"] else None
                runs = [{**{k: v for k, v in r.items() if k != "card"},
                         **({"status": "running"} if r["id"] == going else {})} for r in c.library.all()]
                return self._json(200, {"runs": runs, "busy": bool(job and job["active"])})
            if method == "GET" and name == "compare":
                return self._json(200, compare(c.library.all()))
            if method == "GET" and name == "world":
                try:
                    since = int(q("since", "0"))
                except ValueError:
                    since = 0
                return self._json(200, c.atlas.world(q("run"), since))
            if method == "GET" and name == "inspect":
                run_id = q("run")
                if not q("month"):
                    return self._json(200, c.inspector.index(run_id))
                try:
                    month = int(q("month"))
                except ValueError:
                    raise ApiError("bad month") from None
                return self._json(200, c.inspector.month(run_id, month))
            if method == "GET" and name == "analytics":
                return self._json(200, c.analyst.analytics(q("run")))
            if method == "GET" and name in ("delegate", "explain"):
                try:
                    month = int(q("month"))
                except ValueError:
                    raise ApiError("bad month") from None
                member = q("member").upper()
                if name == "delegate":
                    return self._json(200, c.analyst.delegate(q("run"), month, member, q("deep") == "1"))
                return self._json(200, c.analyst.explain(q("run"), month, member))
            if method == "GET" and name == "founding-preview":
                from .world import new_world
                from .founding import public_profile
                seed = int(q("seed", "1")); scenario = q("scenario", "random"); severity = q("severity", "default")
                problems = [x.strip() for x in q("problems").split(",") if x.strip()]
                world = new_world(seed, months=1, member_ids=[], human_factor=False,
                                  founding_scenario=scenario, founding_severity=severity,
                                  founding_problems=problems if scenario == "custom" else None)
                return self._json(200, {"profile": public_profile(world)})
            if method == "GET" and name == "models":
                provider = q("provider")
                if provider not in PROVIDERS:
                    raise ApiError("unknown provider", 404)
                try:
                    models = discover_models(provider)
                except Exception as exc:  # the CLI is missing or not logged in: fall back to suggestions
                    return self._json(200, {"models": SUGGESTED_MODELS.get(provider, []), "found": False,
                                            "error": f"{type(exc).__name__}: {exc}"[:300]})
                return self._json(200, {"models": models,
                                        "found": provider in ("codex_cli", "antigravity_cli", "qoder_cli")})
            if method == "POST" and name == "config":
                return self._json(200, c.save(str(body.get("name", "")), body.get("config") or {}))
            if method == "POST" and name == "keys":
                key, value = str(body.get("name", "")), body.get("value", "")
                if not isinstance(value, str):
                    raise ApiError("bad value")
                envfile.save_key(c.env_path, key, value)
                extra = [n for n in body.get("names", []) if isinstance(n, str)]
                return self._json(200, {"keys": envfile.key_status(c.env_path, c.key_names(extra + [key]))})
            if method == "POST" and name == "check":
                return self._json(200, c.start_check(body.get("config") or {}))
            if method == "POST" and name == "run":
                return self._json(200, c.start_run(body.get("config") or {}, str(body.get("name", ""))))
            if method == "POST" and name == "resume":
                return self._json(200, c.resume(str(body.get("run_id", ""))))
            if method == "POST" and name == "stop":
                return self._json(200, c.stop())
            return self._error(404, "unknown API call")
        except ApiError as exc:
            return self._error(exc.status, str(exc))
        except ValueError as exc:  # config problems from normalize_config and friends
            return self._error(400, str(exc))
        except Exception as exc:
            traceback.print_exc()
            return self._error(500, f"{type(exc).__name__}: {exc}")


def make_server(root=".", runs_dir=None, port: int = 8770, token: str | None = None,
                verbose: bool = False, tries: int = 10) -> Server:
    root = Path(root).resolve()
    runs = Path(runs_dir).resolve() if runs_dir else root / "runs"
    envfile.load_env(root / ".env")
    controller = Controller(root, runs)
    token = token or secrets.token_urlsafe(24)
    last = None
    for p in range(port, port + max(1, tries)):
        try:
            return Server(p, controller, token, verbose)
        except OSError as exc:
            last = exc
            if port == 0:
                break
    raise OSError(f"no free port from {port} to {port + tries - 1}: {last}")


def serve(root=".", runs_dir=None, port: int = 8770, open_browser: bool = True, verbose: bool = False) -> None:
    server = make_server(root, runs_dir, port, verbose=verbose)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Karamaniya control room: {url}")
    print(f"Council files: {server.controller.root}   Runs: {server.controller.runs_dir}")
    print("Press Ctrl+C to quit. A run in progress keeps every finished month and can be resumed later.")
    sys.stdout.flush()
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        c = server.controller
        if c.busy() and c.stop_event is not None:
            c.stop_event.set()
            print("\nA run was in progress. Every finished month is saved; resume it from the Runs tab.")
        server.server_close()
