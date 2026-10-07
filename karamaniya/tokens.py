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
    are then paired within (month, phase, member), where calls are always sequential. An id is only
    trusted when month, phase and member agree too: runs resumed before the call counter was saved
    can repeat an id.
    """
    run = Path(run_dir)
    if not (run / "log.jsonl").exists() or not (run / "prompts.jsonl").exists():
        raise FileNotFoundError(f"{run} is not a run folder (no log.jsonl and prompts.jsonl)")
    prompts = _jsonl(run / "prompts.jsonl")
    calls = [r for r in _jsonl(run / "log.jsonl") if r.get("type") in ("call", "foreign_call")]
    system_path = run / "system_prompt.txt"
    council_system = system_path.read_text(encoding="utf-8") if system_path.exists() else ""
    by_id, queues, used = defaultdict(list), defaultdict(list), set()
    for i, p in enumerate(prompts):
        if p.get("call_id") is not None:
            by_id[p["call_id"]].append(i)
        queues[(p.get("month"), p.get("phase"), _who(p))].append(i)

    def take(candidates, key):
        for i in candidates:
            if i not in used and (prompts[i].get("month"), prompts[i].get("phase"), _who(prompts[i])) == key:
                used.add(i)
                return prompts[i]
        return None

    foreign_systems = {}
    out = []
    for c in calls:
        phase = "foreign" if c.get("type") == "foreign_call" else c.get("phase")
        key = (c.get("month"), phase, _who(c))
        p = take(by_id.get(c.get("call_id"), ()), key) if c.get("call_id") is not None else None
        if p is None:
            p = take(queues.get(key, ()), key) or {}
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


#: Calls made once, before the first council month: the questionnaire and government formation.
SETUP_PHASES = ("survey", "founding_diagnosis", "formation_proposal", "formation_vote")


def _months_played(run_dir, calls: list) -> int:
    """How many months the run simulated: the manifest's count, else the months its calls name."""
    try:
        with open(Path(run_dir) / "manifest.json", encoding="utf-8") as f:
            n = json.load(f).get("months_simulated")
        if isinstance(n, int) and n >= 0:
            return n
    except (OSError, ValueError):
        pass
    return len({c["month"] for c in calls if c["phase"] not in SETUP_PHASES and c["month"] is not None})


def _cost_of(calls: list) -> dict:
    measured = [c for c in calls if c["measured"]["input_tokens"]]
    return {"calls": len(calls),
            "input_tokens_estimated": estimate(sum(len(c["system"]) + len(c["user"]) for c in calls)),
            "output_tokens_estimated": estimate(sum(c["output_chars"] for c in calls)),
            "measured_calls": len(measured),
            "measured_input_tokens": sum(c["measured"]["input_tokens"] for c in measured),
            "measured_output_tokens": sum(c["measured"]["output_tokens"] for c in measured),
            "retries": sum(int(c["format_retry"]) + int(bool(c["repair"])) for c in calls)}


def ledger(run_dir, scopes=SCOPES) -> dict:
    calls = load_calls(run_dir)
    out = {"run": Path(run_dir).name, "calls": len(calls), "chars_per_token": CHARS_PER_TOKEN}
    # What one simulated month costs, with the one-off setup calls apart: a longer run costs
    # setup + months x per_month, which is what a study is sized from.
    out["months"] = _months_played(run_dir, calls)
    out["setup"] = _cost_of([c for c in calls if c["phase"] in SETUP_PHASES])
    out["monthly"] = _cost_of([c for c in calls if c["phase"] not in SETUP_PHASES])
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
    seats = defaultdict(lambda: {"provider": "", "model": "", "calls": 0, "input_chars": 0, "output_chars": 0,
                                 "measured_calls": 0, "measured_input_chars": 0, "measured_input_tokens": 0,
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
        st["provider"], st["model"] = c["provider"] or st["provider"], c["model"] or st["model"]
        st["calls"] += 1
        st["input_chars"] += size
        st["output_chars"] += c["output_chars"]
        if c["measured"]["input_tokens"]:
            # Characters per token as the provider counted them, over the calls it counted: how far
            # the four-characters estimate is from this model's tokenizer (and, for the command-line
            # seats, from whatever the tool adds to the prompt).
            st["measured_calls"] += 1
            st["measured_input_chars"] += size
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
    months, monthly, setup = report.get("months") or 0, report.get("monthly"), report.get("setup")
    if months and monthly:
        L.append("")
        L.append(f"Per simulated month ({months} months; the {setup['calls']} setup calls are counted apart)")
        L.append(f"  {monthly['calls'] / months:.1f} calls, ~{monthly['input_tokens_estimated'] / months:,.0f} input "
                 f"and ~{monthly['output_tokens_estimated'] / months:,.0f} output tokens, "
                 f"{monthly['retries'] / months:.2f} retries")
        if setup["calls"]:
            L.append(f"  setup, once: {setup['calls']} calls, ~{setup['input_tokens_estimated']:,} input "
                     f"and ~{setup['output_tokens_estimated']:,} output tokens")
    L.append("")
    L.append("By phase                calls     input chars   share   output chars  retries")
    total = max(inp["chars"], 1)
    for ph, v in report["by_phase"].items():
        L.append(f"  {ph:20} {v['calls']:6} {v['input_chars']:15,} {v['input_chars'] / total:7.1%} "
                 f"{v['output_chars']:14,} {v['retries']:8}")
    L.append("")
    seats = report.get("by_seat") or {}
    if seats:
        L.append("By seat (reported = the provider's own count, on the calls it counted)")
        name_w = max([22] + [len(str(s)) for s in seats])
        model_w = max([22] + [len(f"{v['provider']}:{v['model']}".strip(":")) for v in seats.values()])
        L.append(f"  {'seat':{name_w}} {'model':{model_w}} {'calls':>6} {'input chars':>13} "
                 f"{'reported in':>12} {'reported out':>13} {'chars/token':>12}")
        for name, v in sorted(seats.items(), key=lambda kv: -kv[1]["input_chars"]):
            ratio = (f"{v['measured_input_chars'] / v['measured_input_tokens']:.2f}"
                     if v.get("measured_input_tokens") else "-")
            model = f"{v['provider']}:{v['model']}".strip(":")
            L.append(f"  {str(name):{name_w}} {model:{model_w}} {v['calls']:6} {v['input_chars']:13,} "
                     f"{v['measured_input_tokens']:12,} {v['measured_output_tokens']:13,} {ratio:>12}")
        L.append("")
    L.append("By prompt section (the system prompt is sent with every call)")
    shown = list(report["by_section"].items())[:20]
    width = max([28] + [len(name) for name, _ in shown])
    for name, n in shown:
        L.append(f"  {name:{width}} {n:13,}  {n / total:6.1%}")
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


def combine(reports: list) -> dict:
    """Several runs' ledgers as one: what a month and a setup cost on average over all of them."""
    months = sum(r.get("months") or 0 for r in reports)
    with_setup = [r for r in reports if r["setup"]["calls"]]
    keys = ("calls", "input_tokens_estimated", "output_tokens_estimated", "retries")
    return {"runs": len(reports), "months": months,
            "run_lengths": {r["run"]: r.get("months") for r in reports},
            "per_month": {k: round(sum(r["monthly"][k] for r in reports) / months, 2) if months else 0.0
                          for k in keys},
            "setup_per_run": {k: round(sum(r["setup"][k] for r in with_setup) / len(with_setup), 2)
                              if with_setup else 0.0 for k in keys}}


def render_combined(summary: dict, months: int = 36) -> str:
    """The cross-run summary, and what a run of `months` months would cost at that rate."""
    pm, su = summary["per_month"], summary["setup_per_run"]
    lengths = sorted(n for n in summary["run_lengths"].values() if n is not None)
    L = [f"Across {summary['runs']} runs ({summary['months']} simulated months; run lengths "
         f"{', '.join(str(n) for n in lengths) or 'unknown'})",
         f"  per month: {pm['calls']:.1f} calls, ~{pm['input_tokens_estimated']:,.0f} input and "
         f"~{pm['output_tokens_estimated']:,.0f} output tokens, {pm['retries']:.2f} retries",
         f"  setup per run: {su['calls']:.0f} calls, ~{su['input_tokens_estimated']:,.0f} input tokens",
         f"  a {months}-month run at this rate: ~{su['calls'] + months * pm['calls']:,.0f} calls, "
         f"~{su['input_tokens_estimated'] + months * pm['input_tokens_estimated']:,.0f} input and "
         f"~{su['output_tokens_estimated'] + months * pm['output_tokens_estimated']:,.0f} output tokens "
         f"(estimates at {CHARS_PER_TOKEN:g} characters per token; a council that ends early costs less)"]
    return "\n".join(L)
