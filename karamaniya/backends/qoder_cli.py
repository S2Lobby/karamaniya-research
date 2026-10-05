"""Models through the Qoder CLI (`qoder`), on your Qoder login.

Runs headless in an empty scratch folder with every built-in tool disabled and no session written
to disk, so a Qoder seat can only answer the council: it cannot read your files, run commands, or
reach MCP servers/hooks. The council's standing instructions go in as the session's system prompt
and this turn's message arrives on stdin (a command-line argument would cap the prompt and mangle
non-ASCII); the reply is read from the CLI's JSON output and parsed as the object the schema asks
for. Log in once with `qoder login`. The model that actually answered is read back from the CLI's
usage report, so "which model served this seat" stays honest even when you ask for "auto".
"""
from __future__ import annotations

import json
import shutil

from . import cli_common
from .base import Backend, CallResult, FatalError, extract_json

NOT_LOGGED_IN = ("not logged in", "qodercli login", "qoder login", "please log in", "sign in to",
                 "run `qoder")


def _token_count(usage: dict, *keys: str) -> int:
    """Sum token counts from a CLI payload without trusting optional metadata types."""
    total = 0
    for key in keys:
        try:
            value = int(usage.get(key, 0) or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        total += max(0, value)
    return total


class QoderCLIBackend(Backend):
    provider = "qoder_cli"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        # Qoder's public Windows `qoder` command is a PowerShell dispatcher (.cmd).
        # Passing the 10 KB council system prompt through that wrapper hits cmd.exe's
        # shorter argument limit before the CLI starts. Call the native executable
        # directly when it is installed, while keeping explicit per-seat overrides.
        if cfg.get("cli_command") or cfg.get("cli_path"):
            self.cmd = cli_common.resolve(cfg, "qoder")
        else:
            native = shutil.which("qodercli")
            self.cmd = [native] if native else cli_common.resolve({}, "qoder")
        self.effort = cfg.get("effort", "")    # none | low | medium | high (reasoning effort)
        self.workdir = cli_common.scratch_dir("qoder")

    def _command(self, system: str) -> list:
        cmd = self.cmd + ["-p", "--output-format", "json", "--no-session-persistence",
                          "--tools", "", "--system-prompt", system]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["--reasoning-effort", self.effort]
        return cmd

    def call(self, system: str, user: str, schema: dict, context: dict) -> CallResult:
        code, stdout, stderr = cli_common.run(self._command(system), user, self.timeout, cwd=self.workdir)
        try:
            out = json.loads(stdout)
        except json.JSONDecodeError:
            out = None
        if not isinstance(out, dict):
            detail = (stderr or stdout or "").strip()[:400]
            if any(marker in detail.lower() for marker in NOT_LOGGED_IN):
                raise FatalError("Qoder CLI is not logged in: run `qoder login` once, then test the seat again")
            raise cli_common.classify(detail or f"unreadable output (exit {code})", "Qoder CLI")
        text = out.get("result")
        if not isinstance(text, str) or not text:
            text = out.get("text")
        if not isinstance(text, str):
            text = ""
        if out.get("is_error"):
            error = out.get("error")
            if isinstance(error, dict):
                error = error.get("message") or error.get("detail") or error.get("error")
            error_messages = []
            if isinstance(error, str) and error.strip():
                error_messages.append(error.strip())
            errors = out.get("errors")
            if isinstance(errors, list):
                for item in errors:
                    if isinstance(item, str) and item.strip():
                        error_messages.append(item.strip())
                    elif isinstance(item, dict):
                        message = item.get("message") or item.get("detail") or item.get("error")
                        if isinstance(message, str) and message.strip():
                            error_messages.append(message.strip())
            for key in ("message", "api_error_status", "error_code"):
                value = out.get(key)
                if isinstance(value, (str, int)) and str(value).strip():
                    error_messages.append(str(value).strip())
            detail = "; ".join(dict.fromkeys(error_messages)) or text[:300] or "Qoder request failed"
            if any(marker in detail.lower() for marker in NOT_LOGGED_IN):
                raise FatalError("Qoder CLI is not logged in: run `qoder login` once, then test the seat again")
            raise cli_common.classify(detail, "Qoder CLI")
        usage = out.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        tokens_in = _token_count(usage, "input_tokens", "cache_read_input_tokens",
                                 "cache_creation_input_tokens")
        tokens_out = _token_count(usage, "output_tokens")
        model_usage = out.get("modelUsage")
        served_models = sorted(k for k in model_usage if isinstance(k, str)) if isinstance(model_usage, dict) else []
        served = ",".join(served_models) or out.get("model") or self.model or "qoder"
        served = str(served)
        data = out.get("structured_output")
        if not isinstance(data, dict):
            data = extract_json(text)
        refusal = out.get("stop_reason") == "refusal"
        return CallResult(data=data if isinstance(data, dict) else None, raw=text, served_model=served,
                          input_tokens=tokens_in, output_tokens=tokens_out,
                          cost_usd=self.cost(tokens_in, tokens_out), refusal=refusal)
