"""Stand-ins for the AI command-line tools, printing what the real ones print (recorded from
codex-cli 0.154, Cline CLI 3.0, Antigravity CLI and Claude Code), so the connectors can be
tested without logins or cost.

    python fake_cli.py codex|cline|agy|claude [the real tool's arguments]

FAKE_CLI_RECORD=<file>        write the arguments, stdin and selected environment there
FAKE_CLI_LIMIT_AFTER=<n>      answer n calls, then report the plan's usage limit
FAKE_CLI_COUNTER=<file>       where the call count is kept between calls
"""
import json
import os
import sys
import time


def over_limit() -> bool:
    limit = os.environ.get("FAKE_CLI_LIMIT_AFTER")
    if limit is None:
        return False
    path = os.environ["FAKE_CLI_COUNTER"]
    n = 0
    if os.path.exists(path):
        with open(path) as f:
            n = int(f.read().strip() or 0)
    n += 1
    with open(path, "w") as f:
        f.write(str(n))
    return n > int(limit)


def answer(schema_text: str) -> dict:
    if '"ok"' in schema_text:
        return {"ok": True, "note": "ready"}
    if '"statement"' in schema_text:
        return {"statement": "We should protect open elections."}
    return {}


def arg_after(argv, flag, default=""):
    return argv[argv.index(flag) + 1] if flag in argv else default


def main():
    kind, argv = sys.argv[1], sys.argv[2:]
    stdin = sys.stdin.buffer.read().decode("utf-8") if kind != "cline" else ""   # real CLIs read UTF-8
    if os.environ.get("FAKE_CLI_RECORD"):
        with open(os.environ["FAKE_CLI_RECORD"], "w", encoding="utf-8") as f:
            json.dump({"kind": kind, "argv": argv, "stdin": stdin, "cwd": os.getcwd(),
                       "env": {k: os.environ.get(k) for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN",
                                                              "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL")}}, f)
    limited = over_limit()
    out = sys.stdout

    if kind == "codex":
        schema = open(arg_after(argv, "--output-schema"), encoding="utf-8").read()
        print(json.dumps({"type": "thread.started", "thread_id": "01a0e79f"}), file=out)
        print(json.dumps({"type": "turn.started"}), file=out)
        if limited:
            msg = ("You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit "
                   "https://chatgpt.com/codex/settings/usage to purchase more credits or try again at 4:45 PM.")
            print(json.dumps({"type": "error", "message": msg}), file=out)
            print(json.dumps({"type": "turn.failed", "error": {"message": msg}}), file=out)
            return 1
        text = json.dumps(answer(schema))
        with open(arg_after(argv, "-o"), "w", encoding="utf-8") as f:
            f.write(text)
        print(json.dumps({"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": text}}), file=out)
        print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 6717, "cached_input_tokens": 0,
                                                             "output_tokens": 19}}), file=out)
        return 0

    if kind == "cline":
        prompt = argv[-1]
        if limited and os.environ.get("FAKE_CLI_LIMIT_STYLE") == "text":
            # Recorded from Cline CLI on 2026-09-29: the plan limit arrives as the answer text.
            text = "You have reached your monthly Clinepass limit. The limit resets in 1h 11m, please try again later."
            print(json.dumps({"type": "agent_event", "event": {"type": "done", "reason": "completed", "text": text,
                                                              "iterations": 1, "usage": {"inputTokens": 0, "outputTokens": 0}}}), file=out)
            return 0
        if limited:
            print(json.dumps({"type": "error", "message": "Cline Pass usage limit reached. Resets tomorrow."}), file=sys.stderr)
            return 1
        text = json.dumps(answer(prompt))
        print(json.dumps({"type": "agent_event", "event": {"type": "iteration_start", "iteration": 1}}), file=out)
        print(json.dumps({"type": "agent_event", "event": {"type": "content_end", "contentType": "text", "text": text}}), file=out)
        print(json.dumps({"type": "agent_event", "event": {"type": "iteration_end", "iteration": 1, "hadToolCalls": False,
                                                          "toolCallCount": 0}}), file=out)
        print(json.dumps({"type": "agent_event", "event": {"type": "done", "reason": "completed", "text": text,
                                                          "iterations": 1, "usage": {"inputTokens": 3937, "outputTokens": 31}}}), file=out)
        print(json.dumps({"type": "run_result", "finishReason": "completed", "iterations": 1,
                          "usage": {"inputTokens": 3937, "outputTokens": 31}}), file=out)
        return 0

    if kind == "copilot":
        # Recorded from GitHub Copilot CLI 1.0.89 (prompt on stdin, --output-format json); the
        # used-up-plan wording is not yet recorded.
        if os.environ.get("FAKE_CLI_NO_LOGIN"):
            print("Error: No authentication information found.", file=sys.stderr)
            return 1
        if limited:
            print("Error: You have exceeded your premium requests allowance for this month.", file=sys.stderr)
            return 1
        model = "mai-code-1.1-flash" if arg_after(argv, "--model", "auto") == "auto" else arg_after(argv, "--model")
        usage = arg_after(argv, "--usage-output-file")
        if usage:
            with open(usage, "w", encoding="utf-8") as f:
                json.dump({"totalPremiumRequestCost": 1, "tokenDetails": {"input": {"tokenCount": 10202},
                           "output": {"tokenCount": 139}}, "modelMetrics": {model: {"requests": {"count": 1, "cost": 1},
                           "usage": {"inputTokens": 10202, "outputTokens": 139}}}}, f)
        events = [{"type": "session.auto_mode_resolved", "data": {"chosenModel": model}},
                  {"type": "user.message", "data": {"content": stdin}},
                  {"type": "assistant.message", "data": {"model": model, "content": json.dumps(answer(stdin)),
                                                         "toolRequests": []}},
                  {"type": "result", "exitCode": 0, "usage": {"premiumRequests": 1}}]
        for event in events:
            print(json.dumps(event), file=out)
        return 0

    if kind == "agy":
        msg = json.loads(stdin.splitlines()[0])
        text = msg["message"]["content"][0]["text"]
        schema = open(arg_after(argv, "--json-schema"), encoding="utf-8").read()
        print(json.dumps({"event": "init", "init": {"model": arg_after(argv, "--model", "gemini-default"), "tools": []}}), file=out)
        if limited:
            print(json.dumps({"event": "result", "result": {"status": "ERROR", "response": "",
                                                            "error": "RESOURCE_EXHAUSTED: usage limit reached for today"}}), file=out)
            return 3
        data = answer(schema)
        print(json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": json.dumps(data) + "\n",
                                                        "structured_output": data, "num_turns": 2,
                                                        "usage": {"input_tokens": 27485, "output_tokens": 46,
                                                                  "thinking_tokens": 782}},
                          "echo": len(text)}), file=out)
        return 0

    if kind == "claude":
        schema = arg_after(argv, "--json-schema")
        if limited:
            print(json.dumps({"type": "result", "is_error": True, "result": "Claude AI usage limit reached|1790620000"}), file=out)
            return 1
        data = answer(schema)
        model = arg_after(argv, "--model", "claude-default")
        if arg_after(argv, "--output-format") == "stream-json" and os.environ.get("FAKE_CLI_STREAM"):
            for chunk in ('{"statement":"We should ', 'protect open elections."}'):
                print(json.dumps({"type": "stream_event", "event": {"type": "content_block_delta",
                                  "delta": {"type": "text_delta", "text": chunk}}}), file=out, flush=True)
                time.sleep(0.25)
        print(json.dumps({"type": "result", "is_error": False, "result": json.dumps(data), "structured_output": data,
                          "stop_reason": "end_turn", "usage": {"input_tokens": 120, "output_tokens": 12},
                          "modelUsage": {model: {}}, "total_cost_usd": 0.01}), file=out)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
