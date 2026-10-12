"""The System One (Jev) evaluator backend: typed questions in, typed answers out.

TypeSafe's Jev answers typed questions about a piece of state -- Choice (one of the options, with
probabilities), Score (one position on an ordered set of levels), Noul (P(not enough evidence)) --
and nothing else: it does not chat. This backend speaks its HTTP contract directly
(POST {base_url}/v1/systemone, Bearer TYPESAFE_API_KEY), so the same class drives:

  * the hosted API               (default base_url https://api.typesafe.ai)
  * a wire-compatible open server (point base_url at it; GitHub30/OpenJev runs the official SDK
                                   unmodified against theirs)

Chat models answer the same questions through the panel's emulated path in judges.py, which is also
what the official system-one-adapter does; no extra dependency is needed for that route.

This is an evaluator, not a seat: complete() refuses. Config: provider "systemone", model
(default "jev-latest"), base_url, api_key_env (default TYPESAFE_API_KEY), timeout, retries.
Contract notes and sources: docs/research/jev-contract.md.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

DESC_NONE = None


class SystemOneBackend:
    provider = "systemone"
    #: input-only pricing, $ per million tokens (output is free)
    price_in_per_mtok = 0.042

    def __init__(self, cfg: dict):
        self.base_url = (cfg.get("base_url") or os.environ.get("TYPESAFE_BASE_URL")
                         or "https://api.typesafe.ai").rstrip("/")
        key_env = cfg.get("api_key_env", "TYPESAFE_API_KEY")
        self.api_key = os.environ.get(key_env, "") if key_env else ""
        if key_env and not self.api_key:
            raise ValueError(f"environment variable {key_env} is not set")
        self.model = str(cfg.get("model") or os.environ.get("TYPESAFE_DEFAULT_MODEL") or "jev-latest")
        self.timeout = int(cfg.get("timeout", 30))
        self.retries = int(cfg.get("retries", 2))
        self.last_usage = {}
        self.last_cost_usd = 0.0

    def complete(self, *a, **k):                       # a seat would call this; judges never do
        raise ValueError("systemone is an evaluator model, not a seat; enroll it in judge_backends")

    # -- question translation ------------------------------------------------------------------
    @staticmethod
    def _question(q: dict) -> dict:
        """Our internal question (text/options/levels) in the contract's shape."""
        out = {"type": q["kind"], "instructions": q["text"]}
        if q["kind"] == "choice":
            crit = q.get("criteria") or {}
            out["criteria"] = {opt: crit.get(opt, DESC_NONE) for opt in q["options"]}
        elif q["kind"] == "score":
            levels = q.get("levels") or [str(v) for v in range(int(q["scale"][0]), int(q["scale"][1]) + 1)]
            if not 2 <= len(levels) <= 10:
                raise ValueError(f"a score question needs 2 to 10 levels, got {len(levels)}")
            out["criteria"] = list(levels)
        elif q["kind"] == "noul":
            crit = q.get("criteria")
            if crit:
                out["criteria"] = {"true": crit.get("true", None), "false": crit.get("false", None)}
        else:
            raise ValueError(f"unknown question kind {q['kind']!r}")
        return out

    # -- the call -------------------------------------------------------------------------------
    def _post(self, body: dict) -> dict:
        req = urllib.request.Request(self.base_url + "/v1/systemone", data=json.dumps(body).encode(),
                                     method="POST", headers={
                                         "Content-Type": "application/json",
                                         "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    def ask(self, state, questions: list) -> dict:
        """Ask the typed questions about the state. Returns our answers dict {"answers": [...]}."""
        body = {"state": state, "model": self.model,
                "questions": {q["id"]: self._question(q) for q in questions}}
        out = None
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                out = self._post(body)
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                if exc.code in (429, 529, 500, 502, 503):           # rate limit / overloaded: back off
                    last_error = f"HTTP {exc.code}: {detail}"
                    time.sleep(min(8.0, 1.5 * (attempt + 1)))
                    continue
                raise ValueError(f"systemone refused the request (HTTP {exc.code}): {detail}") from None
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                time.sleep(min(8.0, 1.5 * (attempt + 1)))
        if out is None:
            raise RuntimeError(f"systemone unreachable: {last_error}")
        usage = out.get("usage") or {}
        self.last_usage = {"input_tokens": int(usage.get("input_tokens", 0)),
                           "output_tokens": int(usage.get("output_tokens", 0)),
                           "served_model": str(out.get("model", ""))}
        self.last_cost_usd = self.last_usage["input_tokens"] / 1e6 * self.price_in_per_mtok
        return {"answers": [self._row(q, (out.get("answers") or {}).get(q["id"]) or {})
                            for q in questions]}

    @staticmethod
    def _row(q: dict, a: dict) -> dict:
        """One System One answer in our record shape (the same shape the emulated path parses)."""
        row = {"id": q["id"], "kind": q["kind"], "reason": f"confidence {a.get('confidence')}"[:80]
               if a.get("confidence") is not None else ""}
        if q["kind"] == "choice":
            choice = str(a.get("choice", "")).strip().lower()
            probs = a.get("probabilities") or {}
            row["choice"] = choice
            row["probability"] = round(float(probs.get(a.get("choice", ""), probs.get(choice, 0)) or 0), 3)
            row["probabilities"] = {k: round(float(v), 3) for k, v in probs.items()} if probs else None
        elif q["kind"] == "score":
            levels = q.get("levels") or []
            value = a.get("score")
            lo, hi = (q.get("scale") or [0, len(levels) - 1])[:2]
            if isinstance(value, (int, float)) and len(levels) > 1:
                # the contract returns a probability-weighted mean of 0-based level indices
                row["score"] = round(lo + float(value) / (len(levels) - 1) * (hi - lo), 2)
            else:
                row["score"] = value
            row["probabilities"] = a.get("probabilities")
        else:  # noul -- the contract returns P(not enough evidence) as a float
            p = a.get("noul")
            row["probability"] = round(float(p), 3) if isinstance(p, (int, float)) else None
            row["noul"] = bool(isinstance(p, (int, float)) and p >= 0.5)
        return row
