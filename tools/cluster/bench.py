"""Measure a local vLLM server for the rehearsal: how fast it reads prompts and writes answers at one concurrency.

    python tools/cluster/bench.py --url http://127.0.0.1:8001/v1 --model rehearsal-qwen3-8b \
        --input-tokens 17000 --output-tokens 2000 --concurrency 4 --requests 8

It sends the same long prompt --requests times, --concurrency at a time, twice: once asking for one token (reading
the prompt only) and once asking for --output-tokens (reading the prompt and writing). The difference between the two
wall times is the time spent writing. It prints the numbers that `estimate.py --calibrate` takes, the exact command
to run, and the first answer's content and reasoning field, so that you can see whether thinking was split out of the
answer (README, step 4). Standard library only; it talks only to the URL you give it.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import time
import urllib.request

SENTENCE = ("The council met on the first day of the month to weigh the harvest, the treasury's reserves, and the "
            "neighbours' latest note on the border. ")
WORDS_PER_TOKEN = 0.75    # rough, only to size the prompt; the server's own usage counts are what is used


def build_prompt(input_tokens: int) -> str:
    """A prompt of about `input_tokens` tokens. The exact count comes back in the server's usage."""
    base = SENTENCE.split()
    words = max(1, int(input_tokens * WORDS_PER_TOKEN))
    return " ".join((base * (words // len(base) + 1))[:words])


def chat(url: str, model: str, prompt: str, max_tokens: int, timeout: float = 3600.0) -> dict:
    """One chat request. Returns the token counts, the wall time and the answer's text and reasoning."""
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
            "temperature": 0}
    req = urllib.request.Request(url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    began = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read().decode("utf-8", "replace"))
    elapsed = time.monotonic() - began
    usage = out.get("usage") or {}
    message = ((out.get("choices") or [{}])[0].get("message")) or {}
    reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
    content = message.get("content") or ""
    return {"prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "elapsed": elapsed, "content": content, "reasoning": reasoning}


def run_pass(url: str, model: str, prompt: str, max_tokens: int, concurrency: int, requests: int) -> dict:
    """`requests` identical calls, `concurrency` at a time. The wall time covers the whole pass."""
    began = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(lambda _: chat(url, model, prompt, max_tokens), range(requests)))
    return {"wall": time.monotonic() - began, "results": results}


def summarize(read_only: dict, read_and_write: dict, concurrency: int, input_tokens: int, output_tokens: int,
              gpu_key: str = "<gpu-key>", gpus: int = 1) -> dict:
    """The rates the calibration needs. Prefill from the one-token pass; decode from the difference of the two."""
    prompt_total = sum(r["prompt_tokens"] for r in read_only["results"])
    completion_total = sum(r["completion_tokens"] for r in read_and_write["results"])
    writing_wall = read_and_write["wall"] - read_only["wall"]
    if writing_wall <= 0:
        raise ValueError("the write pass was not longer than the read pass; raise --output-tokens")
    prefill_tps = prompt_total / read_only["wall"]
    decode_tps = completion_total / writing_wall
    ctx = input_tokens + output_tokens / 2
    command = (f"python tools/cluster/estimate.py --calibrate {gpu_key} --calibrate-gpus {gpus} "
               f"--calibrate-batch {concurrency} --calibrate-ctx {ctx:.0f} --measured-decode-tps {decode_tps:.1f} "
               f"--calibrate-input {input_tokens} --measured-prefill-tps {prefill_tps:.1f}")
    return {"concurrency": concurrency, "prompt_tokens_per_call": prompt_total // max(1, len(read_only["results"])),
            "completion_tokens_per_call": completion_total // max(1, len(read_and_write["results"])),
            "measured_prefill_tps": round(prefill_tps, 1), "measured_decode_tps": round(decode_tps, 1),
            "read_pass_wall_s": round(read_only["wall"], 2), "write_pass_wall_s": round(read_and_write["wall"], 2),
            "calibrate_command": command}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Measure a local vLLM server for the rehearsal (see the docstring).")
    ap.add_argument("--url", required=True, help="the server's OpenAI-compatible base URL, e.g. http://127.0.0.1:8001/v1")
    ap.add_argument("--model", required=True, help="the served model name")
    ap.add_argument("--input-tokens", type=int, default=17000)
    ap.add_argument("--output-tokens", type=int, default=2000)
    ap.add_argument("--concurrency", type=int, default=1,
                    help="sequences at once; use the batch the server can hold (1 on a 24 GB card)")
    ap.add_argument("--requests", type=int, default=8)
    ap.add_argument("--gpu", default="<gpu-key>", help="the estimate.py GPU key, to print a complete command")
    ap.add_argument("--gpus", type=int, default=1, help="GPUs in the server, for the printed command")
    args = ap.parse_args(argv)
    prompt = build_prompt(args.input_tokens)
    read_only = run_pass(args.url, args.model, prompt, 1, args.concurrency, args.requests)
    read_and_write = run_pass(args.url, args.model, prompt, args.output_tokens, args.concurrency, args.requests)
    summary = summarize(read_only, read_and_write, args.concurrency, args.input_tokens, args.output_tokens,
                        args.gpu, args.gpus)
    first = read_and_write["results"][0]
    summary["first_answer"] = {"content_head": first["content"][:300],
                               "reasoning_head": first["reasoning"][:200],
                               "think_tags_in_content": "<think>" in first["content"] or "</think>" in first["content"]}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
