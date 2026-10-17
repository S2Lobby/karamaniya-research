"""Replay: a seat that answers from a recorded run instead of a model (engine 24, brief S8).

The engine is deterministic given its answers. A seat that hands each call the raw text its run logged for that call
reproduces the run: the same month records and the same checkpoint (tools/replay_run.py checks this). Nothing here
calls a model.

A call is found by (month, phase, member); a foreign cabinet by (month, "foreign", actor). One key can hold more
than one answer. A repair is a second call in the same phase for the same member, so the k-th time the engine asks
for a key, the replay gives the k-th answer the run logged for it. A format retry is one call in the log
(base.complete keeps one record for it), so it is one answer here too, and the retry logic is not run again.

Two things the log does not hold are derived the way the connector derived them:
  - the answer is the JSON in raw (extract_json), for every connector except the three below;
  - codex_cli also drops the optional nulls that its strict schema adds (drop_optional_nulls).
Known gap: claude_cli, qoder_cli and antigravity_cli take the answer from the CLI's structured_output field, which the
log does not keep. A replay matches them only when raw is that same JSON.

The traits that shape the prompts (enforces_schema, supports_temperature, prompt_budget) are copied from the connector
the seat was recorded with, so the replay's prompts are the run's prompts. prompt_budget is copied for ollama only;
cline_cli's budget depends on its command line and is not copied.
"""
from __future__ import annotations

import dataclasses
import json
import os
import threading

from ..world import month_label
from .base import Backend, CallResult, extract_json
from .codex_cli import drop_optional_nulls
from .ollama import OllamaBackend
from .openai_compat import DEFAULTS as OPENAI_DEFAULTS

OPENAI_FAMILY = ("openai", "deepseek", "openrouter", "openai_compat", "lmstudio", "llamacpp")
SCHEMA_PROVIDERS = ("anthropic", "claude_cli", "codex_cli", "ollama")     # enforces_schema = True (class attribute)
TEMPERATURE_PROVIDERS = ("ollama",) + OPENAI_FAMILY                       # supports_temperature = True
# What a stand-in logged before engine 24: a placeholder with no answer in it.
PLACEHOLDER = "(scripted)"
_CALL_FIELDS = tuple(f.name for f in dataclasses.fields(CallResult) if f.name not in ("data", "raw"))
_INDEXES: dict = {}


class ReplayMissing(Exception):
    """The replay asked for an answer the run did not record: the replay has diverged from the run here."""

    def __init__(self, month, phase, member, attempt, why: str = ""):
        self.month, self.phase, self.member, self.attempt = month, phase, member, attempt
        text = f"no recorded answer for {month_label(int(month))}, phase {phase}, member {member}, call {attempt}"
        super().__init__(text + (f" ({why})" if why else ""))


def load_index(path: str) -> dict:
    """The run's recorded calls, keyed by (month, phase, who), each list in the order the run logged them.

    Parallel phases log in the order their threads finish, so file position is not the order of the calls; the order
    of the calls of one key is kept, because one member's calls run one after another in one thread."""
    st = os.stat(path)
    cache_key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    if cache_key not in _INDEXES:
        index: dict = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("type") == "call":
                    key = (rec.get("month"), rec.get("phase"), rec.get("member"))
                elif rec.get("type") == "foreign_call":
                    key = (rec.get("month"), "foreign", rec.get("actor"))
                else:
                    continue
                index.setdefault(key, []).append(rec)
        _INDEXES.clear()                 # one run at a time; a replaced log must not keep its old index alive
        _INDEXES[cache_key] = index
    return _INDEXES[cache_key]


class ReplayBackend(Backend):
    """A seat that answers each call with the raw text its recorded run logged for that call."""

    provider = "replay"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.replay_of = str(cfg.get("replay_of") or "")         # the provider the run was recorded with
        self.log_path = str(cfg.get("replay_log") or "")         # that run's log.jsonl
        self.num_ctx = int(cfg.get("num_ctx", 12288))            # ollama.py's default, read by prompt_budget
        family = OPENAI_DEFAULTS.get(self.replay_of, OPENAI_DEFAULTS["openai_compat"])
        self.json_mode = cfg.get("json_mode", family["json_mode"])   # openai_compat.py's json_mode for this seat
        self.supports_temperature = self.replay_of in TEMPERATURE_PROVIDERS
        self._index = None
        self._asked: dict = {}
        self._lock = threading.Lock()            # two cabinets may borrow one seat and call it at once

    @property
    def enforces_schema(self) -> bool:
        if self.replay_of in OPENAI_FAMILY:
            return self.json_mode == "json_schema"
        return self.replay_of in SCHEMA_PROVIDERS

    def prompt_budget(self, system_chars: int) -> int:
        if self.replay_of == "ollama":
            return OllamaBackend.prompt_budget(self, system_chars)   # reads only self.cfg and self.num_ctx
        return super().prompt_budget(system_chars)

    def call(self, system: str, user: str, schema: dict, context: dict) -> CallResult:
        context = context or {}
        month = int(context["world"].month)
        phase = context.get("phase")
        who = context.get("member") or context.get("actor")
        with self._lock:
            if self._index is None:
                self._index = load_index(self.log_path)
            attempt = self._asked.get((month, phase, who), 0) + 1
            self._asked[(month, phase, who)] = attempt
        recorded = self._index.get((month, phase, who), [])
        if attempt > len(recorded):
            raise ReplayMissing(month, phase, who, attempt)
        rec = recorded[attempt - 1]
        raw = rec.get("raw") or ""
        if raw == PLACEHOLDER:
            raise ReplayMissing(month, phase, who, attempt, why="the run logged its stand-in answer as '(scripted)'")
        data = extract_json(raw) if raw else None
        if data is not None and self.replay_of == "codex_cli":
            data = drop_optional_nulls(data, schema)
        return CallResult(data=data, raw=raw, **{k: rec[k] for k in _CALL_FIELDS if k in rec})

    def complete(self, system: str, user: str, schema: dict, context: dict | None = None) -> CallResult:
        # The recorded answer is final: no format retry, because the retry's answer is the one that was logged.
        return self.call(system, user, schema, context)
