"""Gemini (and the other models Antigravity offers) through the Antigravity CLI (`agy`).

Runs `agy` headless in print mode, in plan mode and in its terminal sandbox, in an empty scratch
folder, with the answer held to the JSON schema (--json-schema). The prompt goes in on stdin as a
stream-json message, so its length is not limited by the command line. Antigravity has no
system-prompt option, so the council's standing instructions are put at the top of the prompt.
List the models your account can use with `agy models`.
"""
from __future__ import annotations

import json
import os
import tempfile

from . import cli_common
from .base import Backend, CallResult, extract_json


class AntigravityCLIBackend(Backend):
    provider = "antigravity_cli"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.cmd = cli_common.resolve(cfg, "agy")
        self.effort = cfg.get("effort", "")  # low | medium | high | max
        self.workdir = cli_common.scratch_dir("agy")

    def call(self, system: str, user: str, schema: dict, context: dict) -> CallResult:
        message = {"event": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": cli_common.merged_prompt(system, user)}]}}
        with tempfile.TemporaryDirectory(prefix="karamaniya-agy-io-") as io:
            schema_path = os.path.join(io, "schema.json")
            with open(schema_path, "w", encoding="utf-8") as f:
                json.dump(schema, f)
            cmd = self.cmd + ["--input-format", "stream-json", "--output-format", "stream-json",
                              "--json-schema", schema_path, "--mode", "plan", "--sandbox",
                              "--print-timeout", f"{int(self.timeout)}s"]
            if self.model:
                cmd += ["--model", self.model]
            if self.effort:
                cmd += ["--effort", self.effort]
            cmd.append("-p=")
            progress = context.get("on_progress")
            draft = cli_common.StreamPreview(progress) if callable(progress) else None
            def on_line(line):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    return
                if event.get("event") in ("message", "assistant"):
                    content = (event.get("message") or {}).get("content") or []
                    text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
                    if text:
                        draft.replace(text)
            code, stdout, stderr = cli_common.run(cmd, json.dumps(message, ensure_ascii=False) + "\n",
                                                  self.timeout + 30, cwd=self.workdir,
                                                  on_stdout_line=on_line if draft else None)
        events = cli_common.json_lines(stdout)
        served, result = self.model, None
        for e in events:
            if e.get("event") == "init":
                served = (e.get("init") or {}).get("model") or served
            elif e.get("event") == "result":
                result = e.get("result") or {}
        if result is None:
            raise cli_common.classify(stderr.strip() or stdout.strip()[-400:] or f"exit code {code}", "Antigravity CLI")
        usage = result.get("usage") or {}
        tokens_in = int(usage.get("input_tokens", 0))
        tokens_out = int(usage.get("output_tokens", 0)) + int(usage.get("thinking_tokens", 0))
        data = result.get("structured_output")
        text = result.get("response") or ""
        if str(result.get("status", "")).upper() != "SUCCESS" and not isinstance(data, dict):
            raise cli_common.classify(result.get("error") or stderr.strip() or f"status {result.get('status')}",
                                      "Antigravity CLI")
        if not isinstance(data, dict):
            data = extract_json(text)
        return CallResult(data=data, raw=text, served_model=served or "antigravity default",
                          input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=self.cost(tokens_in, tokens_out))
