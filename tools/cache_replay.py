"""Replay a run's prompts through a local Ollama model and measure how much of them its cache reuses.

    ollama serve > ollama.log 2>&1          (with OLLAMA_NUM_PARALLEL=1: one cache slot)
    python tools/cache_replay.py runs/a runs/b --model llama3.2:1b --server-log ollama.log

Every call of the run (system prompt and user prompt, in the order the run logged them) is sent to one
model with num_predict = 1: the model reads the prompt and writes a single token, so what is measured
is the prompt work alone, and the answers cannot change what comes next. Comparing two runs that made
the same calls with different prompt layouts (council.scripted.toml with and without [run.tokens]
layout = "cache_friendly") shows what the layout saves on a real local server.

What is counted. The server keeps the prompt it last evaluated in its KV cache and, for a new prompt,
evaluates only what follows the prefix the two share. Ollama's API does not say how much that was: its
prompt_eval_count is the whole prompt even when most of it came from the cache (checked with Ollama
0.32.9). The server's log does, for every request ("prompt eval time = ... ms / N tokens"), so with
--server-log the tool reads the tokens actually evaluated from there. Without it, only times are
reported (prompt_eval_duration, the prefill), which vary from run to run on the same machine.

Not every model can reuse any part of a prompt: for hybrid and sliding-window models (Qwen3.5, Gemma 3)
llama.cpp can only go back to a context checkpoint it saved earlier, so they reuse less of the shared
prefix than a standard-attention model would. Run it with nothing else using the server: another
client's requests would take the cache.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya.tokens import load_calls  # noqa: E402

NEW_PROMPT = re.compile(r"\| task (\d+) \| new prompt, .*task\.n_tokens = (\d+)")
EVALUATED = re.compile(r"\| task (\d+) \| prompt eval time =\s*[\d.]+ ms /\s*(\d+) tokens")


def ask(base_url: str, model: str, system: str, user: str, num_ctx: int, timeout: float) -> dict:
    body = {"model": model, "stream": False, "keep_alive": "30m",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"num_ctx": num_ctx, "num_predict": 1, "temperature": 0, "seed": 1}}
    req = urllib.request.Request(base_url.rstrip("/") + "/api/chat", data=json.dumps(body).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read().decode("utf-8", "replace"))
    return {"prompt_tokens": int(out.get("prompt_eval_count") or 0),
            "prefill_s": (out.get("prompt_eval_duration") or 0) / 1e9, "wall_s": time.time() - t0}


def server_tasks(text: str) -> list:
    """(prompt tokens, tokens evaluated) for every request in a stretch of the server's log, in order."""
    size, evaluated, order = {}, {}, []
    for task, n in NEW_PROMPT.findall(text):
        if task not in size:
            order.append(task)
        size[task] = int(n)
    for task, n in EVALUATED.findall(text):
        evaluated[task] = int(n)
    return [(size[t], evaluated[t]) for t in order if t in evaluated]


def replay(run_dir: str, model: str, base_url: str, num_ctx: int, timeout: float, server_log: str | None) -> dict:
    calls = load_calls(run_dir)
    # Load the model first, so that loading it is not counted as the first call's prompt work.
    ask(base_url, model, "Ready?", "Say yes.", num_ctx, timeout)
    start = os.path.getsize(server_log) if server_log else 0
    rows = [ask(base_url, model, c["system"], c["user"], num_ctx, timeout) for c in calls]
    out = {"run": os.path.basename(os.path.normpath(run_dir)), "model": model, "calls": len(calls),
           "input_chars": sum(len(c["system"]) + len(c["user"]) for c in calls), "num_ctx": num_ctx,
           "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
           "prefill_s": round(sum(r["prefill_s"] for r in rows), 2),
           "wall_s": round(sum(r["wall_s"] for r in rows), 2)}
    longest = max((r["prompt_tokens"] for r in rows), default=0)
    if longest >= num_ctx:
        raise SystemExit(f"{out['run']}: a prompt of {longest} tokens does not fit num_ctx {num_ctx}; "
                         "the server would cut it. Raise --num-ctx.")
    out["chars_per_token"] = round(out["input_chars"] / out["prompt_tokens"], 2) if out["prompt_tokens"] else None
    if server_log:
        time.sleep(1.0)                     # the runner's last lines can follow the HTTP reply
        with open(server_log, "rb") as f:
            f.seek(start)
            tasks = server_tasks(f.read().decode("utf-8", "replace"))
        if len(tasks) != len(calls):
            raise SystemExit(f"{out['run']}: the server log shows {len(tasks)} requests for {len(calls)} calls; "
                             "was another client using the server, or is the log from another server?")
        out["evaluated_tokens"] = sum(e for _, e in tasks)
        out["reused_share"] = round(1 - out["evaluated_tokens"] / max(1, sum(n for n, _ in tasks)), 4)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--model", required=True, help="an Ollama model, e.g. llama3.2:1b")
    ap.add_argument("--base-url", default="http://127.0.0.1:11434")
    ap.add_argument("--num-ctx", type=int, default=16384, help="context per request; must hold the longest prompt")
    ap.add_argument("--server-log", help="the Ollama server's log file, to count the tokens it really evaluated")
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--json", dest="json_out", help="write the measurements to this file")
    args = ap.parse_args()
    results = []
    for run in args.run_dirs:
        r = replay(run, args.model, args.base_url, args.num_ctx, args.timeout, args.server_log)
        results.append(r)
        line = (f"{r['run']}: {r['calls']} calls, {r['prompt_tokens']:,} prompt tokens, "
                f"prefill {r['prefill_s']:.1f} s, wall {r['wall_s']:.1f} s")
        if "evaluated_tokens" in r:
            line += f"; evaluated {r['evaluated_tokens']:,}, reused from the cache {r['reused_share']:.1%}"
        print(line, flush=True)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
