"""Replay a recorded run from its own answers, and compare the replay with the original (engine 24, brief S8).

    python tools/replay_run.py <run_dir> [--months N] [--keep]

The run's own config and seed are used again. Every seat and both foreign cabinets are answered from the run's
log.jsonl by karamaniya/backends/replay.py, so no model is called. The replay is written to a temporary folder, and
its month records and its final checkpoint are compared with the original's. The first divergence is printed, or
"identical". Exit status 0 when identical, 1 when not, 2 when the run cannot be read.

Not compared, because they are not the engine's decisions:
  - latency_s (timing), call_id (numbered in the order the threads finish), the run id and log offsets (the checkpoint
    meta, not compared at all), and engine_source_fingerprint (a hash of the code; the replay runs the current code);
  - a float is equal when it is within 1e-9 relative: the council adds each call's cost to its spend in the order the
    calls finish, so the last digits of the spend can differ between two runs of the same answers.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya.backends.replay import PLACEHOLDER, ReplayMissing  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.world import month_label  # noqa: E402

IGNORED = {"latency_s", "call_id", "log_mark", "run_id", "engine_source_fingerprint"}
ANSWER_TYPES = ("call", "foreign_call")


def _jsonl(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def replay_config(config: dict, log_path: str) -> dict:
    """The run's config with every seat and the foreign cabinets answered by replay, and no judges, report or baseline."""
    def as_replay(seat: dict) -> dict:
        return {**seat, "replay_of": seat.get("provider", ""), "provider": "replay", "replay_log": log_path}

    cfg = copy.deepcopy(config)
    cfg["seats"] = [as_replay(seat) for seat in cfg["seats"]]
    run = dict(cfg["run"])
    if run.get("foreign_cabinet_backend"):
        run["foreign_cabinet_backend"] = as_replay(run["foreign_cabinet_backend"])
    # Judges never change the world, and they would call real models. The report and the baseline are not needed.
    run.update(judge=False, report=False, baseline=False)
    cfg["run"] = run
    providers = {seat["provider"] for seat in cfg["seats"]}
    if run.get("foreign_cabinet_backend"):
        providers.add(run["foreign_cabinet_backend"]["provider"])
    if providers != {"replay"}:
        raise RuntimeError(f"a replay must call no model; these providers were not replaced: {sorted(providers)}")
    return cfg


class _StopAfter:
    """The stop_event of new_run: it is set once the replay has written `limit` month records."""

    def __init__(self, log_path: str, limit: int):
        self.log_path, self.limit = log_path, limit

    def is_set(self) -> bool:
        if not os.path.exists(self.log_path):
            return self.limit <= 0
        with open(self.log_path, encoding="utf-8") as f:
            # The month record is written as {"type": "month", ...}, so its line can be told from the others cheaply.
            return sum(1 for line in f if line.startswith('{"type": "month"')) >= self.limit


def _number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def first_difference(a, b, path: str = ""):
    """The first place two records differ, as (path, original, replay), or None. Ignored keys are skipped."""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            if key in IGNORED:
                continue
            where = f"{path}.{key}" if path else str(key)
            if key not in a or key not in b:
                return (where, a.get(key, "(absent)"), b.get(key, "(absent)"))
            found = first_difference(a[key], b[key], where)
            if found:
                return found
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return (f"{path} (number of items)", len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            found = first_difference(x, y, f"{path}[{i}]")
            if found:
                return found
        return None
    if _number(a) and _number(b):
        if math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12) or (a != a and b != b):
            return None
        return (path, a, b)
    return None if a == b else (path, a, b)


def _diverged(where: str, message: str, month=None, path: str = "", original=None, replayed=None) -> dict:
    return {"where": where, "month": month, "path": path, "original": original, "replay": replayed,
            "message": message}


def replay(run_dir: str, months: int | None = None, keep: bool = False) -> dict:
    """Replay a run folder and compare it with the original. Returns the verdict; see the module docstring."""
    run_dir = os.path.abspath(run_dir)
    config = _json(os.path.join(run_dir, "config.json"))
    checkpoint = _json(os.path.join(run_dir, "checkpoint.json"))
    log_path = os.path.join(run_dir, "log.jsonl")
    original_log = _jsonl(log_path)
    original_months = [r for r in original_log if r.get("type") == "month"]
    completed = len(checkpoint["world"]["history"])
    if months is None:
        limit = completed
    elif 1 <= months <= completed:
        limit = months
    else:
        raise ValueError(f"--months must be between 1 and {completed}: the run has {completed} completed months")

    base = {"identical": False, "recorded_months": len(original_months), "replay_limit": limit,
            "replayed_months": 0, "checkpoint_compared": False, "temp_dir": None}

    placeholders = [r for r in original_log if r.get("type") in ANSWER_TYPES and r.get("raw") == PLACEHOLDER]
    if placeholders:
        divergence = _diverged("recording", f"not replayable: {len(placeholders)} recorded answers are "
                                            f"'{PLACEHOLDER}' placeholders. The run was recorded before engine 24 "
                                            "logged the stand-ins' answers, so there is nothing to feed back.")
        return {**base, "divergence": divergence, "message": "first divergence: " + divergence["message"]}

    tmp = tempfile.mkdtemp(prefix="karamaniya-replay-")
    try:
        cfg = replay_config(config, log_path)
        error = None
        try:
            new_run(cfg, runs_dir=tmp, name="replay", quiet=True, check=False,
                    stop_event=_StopAfter(os.path.join(tmp, "replay", "log.jsonl"), limit))
        except ReplayMissing as exc:
            error = exc
        except Exception as exc:  # the engine itself failed on the replayed answers
            error = exc
        replay_dir = os.path.join(tmp, "replay")
        replayed_log = _jsonl(os.path.join(replay_dir, "log.jsonl")) if os.path.exists(replay_dir) else []
        replayed_months = [r for r in replayed_log if r.get("type") == "month"]
        base.update(replayed_months=len(replayed_months))
        verdict = _verdict(original_months, replayed_months, limit, error, run_dir, replay_dir, checkpoint, completed)
        result = {**base, **verdict}
        if keep:
            result["temp_dir"] = tmp
        return result
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


def _verdict(original_months, replayed_months, limit, error, run_dir, replay_dir, checkpoint, completed) -> dict:
    # 1. Month records, in order: the first month whose record differs is the divergence.
    for rec, orig in zip(replayed_months, original_months):
        found = first_difference(orig, rec)
        if found:
            label = month_label(int(rec["month"]))
            path, a, b = found
            message = (f"first divergence in {label} (its month record): {path}: the run has {_show(a)}, "
                       f"the replay has {_show(b)}.")
            return {"identical": False, "divergence": _diverged("month", message, rec["month"], path, a, b),
                    "message": message}
    # 2. The replay stopped on an answer the run does not hold, or on an error.
    if isinstance(error, ReplayMissing):
        label = month_label(int(error.month))
        message = f"first divergence in {label}: the replay asked for an answer the run does not hold ({error})."
        return {"identical": False, "divergence": _diverged("replay", message, error.month), "message": message}
    if error is not None:
        at = len(replayed_months)
        label = month_label(at)
        message = (f"first divergence in {label}: the replay raised {type(error).__name__}: {str(error)[:300]}")
        return {"identical": False, "divergence": _diverged("replay", message, at), "message": message}
    # 3. The replay ran a different number of months from the run.
    if len(replayed_months) != limit:
        at = min(len(replayed_months), limit)
        label = month_label(at)
        message = (f"first divergence in {label}: the replay has {len(replayed_months)} month records, the run "
                   f"has {limit} to compare.")
        return {"identical": False, "divergence": _diverged("replay", message, at), "message": message}
    # 4. The final checkpoint, when the replay covers the whole run.
    checkpoint_compared = limit == completed == len(original_months)
    if checkpoint_compared:
        replay_checkpoint = _json(os.path.join(replay_dir, "checkpoint.json"))
        for part in ("world", "council"):
            found = first_difference(checkpoint[part], replay_checkpoint[part], part)
            if found:
                path, a, b = found
                message = f"first divergence in the final checkpoint: {path}: the run has {_show(a)}, the replay has {_show(b)}."
                return {"identical": False, "checkpoint_compared": True,
                        "divergence": _diverged("checkpoint", message, None, path, a, b), "message": message}
    note = ("" if checkpoint_compared else
            f" The final checkpoint is not compared: the replay stopped at Month {limit} of the run's {completed}.")
    if checkpoint_compared:
        message = (f"identical: the {limit} month records and the final checkpoint match the original "
                   f"(the code fingerprint and timings are not compared).")
    else:
        message = f"identical: the {limit} month records match the original.{note}"
    return {"identical": True, "checkpoint_compared": checkpoint_compared, "divergence": None, "message": message}


def _show(value) -> str:
    text = repr(value)
    return text if len(text) <= 160 else text[:157] + "..."


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Replay a recorded run from its own answers and compare it with the "
                                                 "original.")
    parser.add_argument("run_dir", help="a run folder: config.json, log.jsonl and checkpoint.json")
    parser.add_argument("--months", type=int, default=None,
                        help="replay only the first N months (default: every completed month)")
    parser.add_argument("--keep", action="store_true", help="keep the temporary replay folder and print its path")
    args = parser.parse_args(argv)
    try:
        result = replay(args.run_dir, months=args.months, keep=args.keep)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"replay_run: {exc}", file=sys.stderr)
        return 2
    print(result["message"])
    if result.get("temp_dir"):
        print(f"replay folder: {result['temp_dir']}")
    return 0 if result["identical"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    raise SystemExit(main())
