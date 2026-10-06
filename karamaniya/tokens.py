"""Where a run's tokens go, and how much of them a prompt cache could serve.

Reads a finished (or paused) run folder and makes no model calls. Every number is either measured
(the token counts a provider reported for a call, kept in log.jsonl) or estimated from characters,
and the output says which. Estimates use one rule, CHARS_PER_TOKEN characters to a token: the
providers' tokenizers differ, so the estimate is for comparing prompts and layouts with each other,
not for a bill.

The cache simulation answers one question: of the input characters a run sent, how many repeated a
prefix the same model had already been sent shortly before? That is what an automatic prefix cache
(OpenAI, DeepSeek, a local llama.cpp/Ollama KV cache) can reuse, and an upper bound for an explicit
one (Anthropic cache_control breakpoints). It is computed per (provider, model): models never share
a cache. The window is a phase, a month, or the whole run, standing in for the cache's lifetime.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

CHARS_PER_TOKEN = 4.0
# Prefixes shorter than this are not cached by the providers that cache automatically.
MIN_CACHED_TOKENS = 1024
# How far back a call looks for a prefix to reuse, per model. A cache keeps more, but the calls that
# share a prefix with this one are the recent ones, and the bound keeps the simulation fast.
LOOKBACK = 12
SCOPES = ("phase", "month", "run")


def estimate(chars: int) -> int:
    return int(round(chars / CHARS_PER_TOKEN))


def _jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _who(rec: dict) -> str:
    return str(rec.get("member") or rec.get("actor") or "")


def _foreign_system(actor: str) -> str:
    try:
        from .foreign import cabinet_system_prompt
        return cabinet_system_prompt(actor)
    except Exception:
        return ""


def load_calls(run_dir) -> list:
    """One record per model call, in the order the calls were logged.

    A call is a pair: its entry in log.jsonl (who, which model, what the provider reported) and its
    entry in prompts.jsonl (the prompt as sent). New runs give both the same call_id. Older runs did
    not, and their calls ran in parallel threads, so the two files can interleave differently; they
    are then paired within (month, phase, member), where calls are always sequential.
    """
    run = Path(run_dir)
    if not (run / "log.jsonl").exists() or not (run / "prompts.jsonl").exists():
        raise FileNotFoundError(f"{run} is not a run folder (no log.jsonl and prompts.jsonl)")
    prompts = _jsonl(run / "prompts.jsonl")
    calls = [r for r in _jsonl(run / "log.jsonl") if r.get("type") in ("call", "foreign_call")]
    system_path = run / "system_prompt.txt"
    council_system = system_path.read_text(encoding="utf-8") if system_path.exists() else ""
    by_id = {p["call_id"]: p for p in prompts if p.get("call_id") is not None}
    queues = defaultdict(list)
    for p in prompts:
        if p.get("call_id") is None:
            queues[(p.get("month"), p.get("phase"), _who(p))].append(p)
    foreign_systems = {}
    out = []
    for c in calls:
        phase = "foreign" if c.get("type") == "foreign_call" else c.get("phase")
        p = by_id.get(c.get("call_id")) if c.get("call_id") is not None else None
        if p is None:
            q = queues.get((c.get("month"), phase, _who(c)))
            p = q.pop(0) if q else {}
        user = p.get("prompt", "") or ""
        if phase == "foreign":
            actor = str(c.get("actor") or "")
            if actor not in foreign_systems:
                foreign_systems[actor] = _foreign_system(actor)
            system, system_id = foreign_systems[actor], f"foreign:{actor}"
        else:
            system, system_id = council_system, "council"
        meta = p.get("prompt_meta") or {}
        out.append({
            "call_id": c.get("call_id"), "month": c.get("month"), "phase": phase, "who": _who(c),
            "seat": c.get("seat", ""), "provider": c.get("provider", ""), "model": c.get("model", ""),
            "system_id": system_id, "system": system, "user": user,
            "sections": meta.get("sections") or [], "cache_points": meta.get("cache_points") or [],
            "output_chars": len(c.get("raw") or ""),
            "measured": {k: int(c.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_read_tokens",
                                                         "cache_write_tokens", "reasoning_tokens")},
            "format_retry": bool(c.get("format_retry")), "repair": c.get("repair", ""),
        })
    return out


def _lcp(a: str, b: str) -> int:
    """Length of the common prefix, by bisection over slice comparisons (fast for long prompts)."""
    lo, hi = 0, min(len(a), len(b))
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if a[:mid] == b[:mid]:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _window_key(call: dict, scope: str):
    if scope == "phase":
        return (call["month"], call["phase"])
    if scope == "month":
        return (call["month"],)
    return ()


def simulate_cache(calls: list, scope: str = "month", min_tokens: int = MIN_CACHED_TOKENS,
                   same_model: bool = False) -> dict:
    """How much of each call's input repeats a prefix the same model was recently sent.

    The input is the system prompt followed by the user prompt. Two calls with different system
    prompts share nothing (their prefixes diverge at once); with the same system prompt they share
    it plus the common start of their user prompts.

    Calls share a cache when they go to the same provider and model. A seat with no model name (the
    scripted stand-ins) is taken to be a model of its own, as in a council of five different models;
    `same_model=True` pools every call instead, as in a same-model government.
    """
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}")
    min_chars = int(min_tokens * CHARS_PER_TOKEN)
    recent = defaultdict(list)          # (provider, model, window) -> recent calls, newest last
    total = reused = 0
    per_phase = defaultdict(lambda: [0, 0])
    for call in calls:
        model = "*" if same_model else (call["model"] or f"seat:{call['seat'] or call['who']}")
        key = ("*" if same_model else call["provider"], model, _window_key(call, scope))
        size = len(call["system"]) + len(call["user"])
        best = 0
        for prev in recent[key][-LOOKBACK:]:
            if prev["system_id"] != call["system_id"]:
                continue
            shared = len(call["system"]) + _lcp(prev["user"], call["user"])
            best = max(best, shared)
        hit = best if best >= min_chars else 0
        total += size
        reused += hit
        per_phase[call["phase"]][0] += size
        per_phase[call["phase"]][1] += hit
        recent[key].append(call)
    return {"scope": scope, "min_tokens": min_tokens, "same_model": same_model,
            "input_chars": total, "reused_chars": reused,
            "reused_share": round(reused / total, 4) if total else 0.0,
            "by_phase": {ph: {"input_chars": t, "reused_chars": r, "reused_share": round(r / t, 4) if t else 0.0}
                         for ph, (t, r) in sorted(per_phase.items())}}


def relative_input_cost(reused_share: float, read_price: float = 0.1) -> float:
    """Input cost with a prefix cache, as a fraction of the cost without one.

    `read_price` is the price of a cached token relative to a fresh one: about 0.1 for Anthropic
    cache reads, 0.25-0.5 for automatic caches elsewhere (check the provider's current prices). A
    write premium (Anthropic charges 1.25x to write a breakpoint) is left out: it depends on where
    the breakpoints are, not on the layout alone."""
    return round(1.0 - (1.0 - read_price) * reused_share, 4)


def ledger(run_dir, scopes=SCOPES) -> dict:
    calls = load_calls(run_dir)
    out = {"run": Path(run_dir).name, "calls": len(calls), "chars_per_token": CHARS_PER_TOKEN}
    sys_chars = sum(len(c["system"]) for c in calls)
    user_chars = sum(len(c["user"]) for c in calls)
    measured = {k: sum(c["measured"][k] for c in calls) for k in calls[0]["measured"]} if calls else {}
    out["input"] = {"system_chars": sys_chars, "user_chars": user_chars, "chars": sys_chars + user_chars,
                    "estimated_tokens": estimate(sys_chars + user_chars)}
    out["output"] = {"chars": sum(c["output_chars"] for c in calls),
                     "estimated_tokens": estimate(sum(c["output_chars"] for c in calls))}
    out["measured"] = measured
    out["measured_calls"] = sum(1 for c in calls if c["measured"]["input_tokens"])
    phases = defaultdict(lambda: {"calls": 0, "input_chars": 0, "output_chars": 0, "retries": 0})
    seats = defaultdict(lambda: {"calls": 0, "input_chars": 0, "output_chars": 0, "measured_input_tokens": 0,
                                 "measured_output_tokens": 0})
    sections = defaultdict(int)
    for c in calls:
        size = len(c["system"]) + len(c["user"])
        ph = phases[c["phase"]]
        ph["calls"] += 1
        ph["input_chars"] += size
        ph["output_chars"] += c["output_chars"]
        ph["retries"] += int(c["format_retry"]) + int(bool(c["repair"]))
        st = seats[c["seat"] or c["who"]]
        st["calls"] += 1
        st["input_chars"] += size
        st["output_chars"] += c["output_chars"]
        st["measured_input_tokens"] += c["measured"]["input_tokens"]
        st["measured_output_tokens"] += c["measured"]["output_tokens"]
        sections["system"] += len(c["system"])
        if c["sections"]:
            counted = 0
            for name, n in c["sections"]:
                sections[name] += int(n)
                counted += int(n)
            sections["(separators)"] += max(0, len(c["user"]) - counted)
        else:
            sections[f"({c['phase']}, not sectioned)"] += len(c["user"])
    out["by_phase"] = dict(sorted(phases.items(), key=lambda kv: -kv[1]["input_chars"]))
    out["by_seat"] = dict(seats)
    out["by_section"] = dict(sorted(sections.items(), key=lambda kv: -kv[1]))
    out["cache"] = {}
    for scope in scopes:
        sim = simulate_cache(calls, scope)
        sim["relative_input_cost_at_read_0.1"] = relative_input_cost(sim["reused_share"], 0.1)
        sim["relative_input_cost_at_read_0.5"] = relative_input_cost(sim["reused_share"], 0.5)
        out["cache"][scope] = sim
    pooled = simulate_cache(calls, "month", same_model=True)
    pooled["relative_input_cost_at_read_0.1"] = relative_input_cost(pooled["reused_share"], 0.1)
    pooled["relative_input_cost_at_read_0.5"] = relative_input_cost(pooled["reused_share"], 0.5)
    out["cache_same_model_month"] = pooled
    return out


def fingerprints(run_dir) -> dict:
    """sha256 of the system prompt and of every prompt as sent: what the prompt-freeze test compares.

    Keyed by (month, phase, member or actor, n-th call of that key), not by file position: calls in
    the same phase run in parallel threads, so the order of the lines can differ between two runs
    whose prompts are identical."""
    run = Path(run_dir)
    counts, entries = defaultdict(int), []
    for r in _jsonl(run / "prompts.jsonl"):
        key = (r.get("month"), r.get("phase"), _who(r))
        counts[key] += 1
        entries.append([key[0], key[1], key[2], counts[key],
                        hashlib.sha256((r.get("prompt") or "").encode("utf-8")).hexdigest()])
    entries.sort(key=lambda e: (e[0], e[1], e[2], e[3]))
    system = (run / "system_prompt.txt").read_text(encoding="utf-8") if (run / "system_prompt.txt").exists() else ""
    return {"system_prompt_sha256": hashlib.sha256(system.encode("utf-8")).hexdigest(), "prompts": entries}


def render(report: dict) -> str:
    """The ledger as a plain-text report."""
    L = []
    inp, outp = report["input"], report["output"]
    L.append(f"Token ledger for {report['run']}: {report['calls']} model calls")
    L.append(f"  input   {inp['chars']:>12,} chars  ~{inp['estimated_tokens']:>10,} tokens "
             f"(system prompt {inp['system_chars'] / max(inp['chars'], 1):.0%} of it)")
    L.append(f"  output  {outp['chars']:>12,} chars  ~{outp['estimated_tokens']:>10,} tokens")
    m = report.get("measured") or {}
    if report.get("measured_calls"):
        L.append(f"  measured by the providers on {report['measured_calls']} calls: "
                 f"{m.get('input_tokens', 0):,} in, {m.get('output_tokens', 0):,} out, "
                 f"{m.get('cache_read_tokens', 0):,} cache reads, {m.get('cache_write_tokens', 0):,} cache writes, "
                 f"{m.get('reasoning_tokens', 0):,} reasoning")
    else:
        L.append("  no provider-reported token counts in this run (scripted or older seats): estimates only")
    L.append(f"  (estimates at {report['chars_per_token']:g} characters per token)")
    L.append("")
    L.append("By phase                calls     input chars   share   output chars  retries")
    total = max(inp["chars"], 1)
    for ph, v in report["by_phase"].items():
        L.append(f"  {ph:20} {v['calls']:6} {v['input_chars']:15,} {v['input_chars'] / total:7.1%} "
                 f"{v['output_chars']:14,} {v['retries']:8}")
    L.append("")
    L.append("By prompt section (the system prompt is sent with every call)")
    for name, n in list(report["by_section"].items())[:20]:
        L.append(f"  {name:28} {n:13,}  {n / total:6.1%}")
    L.append("")
    L.append("Prefix a cache could reuse (same model, recent calls), by cache lifetime")
    for scope, sim in report["cache"].items():
        L.append(f"  within one {scope:6} {sim['reused_share']:6.1%} of input  -> input cost "
                 f"x{sim['relative_input_cost_at_read_0.1']:.2f} at a 0.1 read price, "
                 f"x{sim['relative_input_cost_at_read_0.5']:.2f} at 0.5")
    pooled = report.get("cache_same_model_month")
    if pooled:
        L.append(f"  same model in every seat, within one month: {pooled['reused_share']:.1%} of input -> "
                 f"x{pooled['relative_input_cost_at_read_0.1']:.2f} at a 0.1 read price")
    return "\n".join(L)
