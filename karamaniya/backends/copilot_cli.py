"""Models through the GitHub Copilot CLI (`copilot`), on your Copilot subscription.

Copilot runs headless in an empty scratch folder with every tool, the built-in MCP servers and
custom-instruction files (AGENTS.md and the like) switched off, and without updating itself, so
the agent can only answer. The prompt goes in on stdin: a command-line argument would cap it at
32,767 characters and Copilot misreads non-ASCII characters there (a curly apostrophe or a dash
arrives as U+FFFD). The reply is read from the JSON event stream (--output-format json): the
plain-text mode wraps long lines, even inside JSON strings. Copilot has no system-prompt or
schema option, so the council's standing instructions are put at the top of the message and the
answer is read out of the reply text (and asked for once more if it cannot be read). A WinGet
install is found even when it is not on PATH. Each call spends Copilot premium requests at the
chosen model's rate; log in once with `copilot login`. With model "auto" Copilot picks the model,
and the one it picked is recorded as the served model.
"""
from __future__ import annotations

import glob
import json
import os
import tempfile

from . import cli_common
from .base import Backend, CallResult, FatalError, extract_json

WINGET = (r"Microsoft\WinGet\Links\copilot.exe", r"Microsoft\WinGet\Packages\GitHub.Copilot_*\copilot.exe")
NOT_LOGGED_IN = ("No authentication information found", "not logged in", "copilot login")


def find_copilot(cfg: dict) -> list:
    """`cli_command`, `cli_path`, `copilot` on PATH, or the WinGet install."""
    try:
        return cli_common.resolve(cfg, "copilot")
    except FatalError:
        base = os.environ.get("LOCALAPPDATA", "")
        for pattern in WINGET:
            hits = sorted(glob.glob(os.path.join(base, pattern))) if base else []
            if hits:
                return [hits[-1]]
        raise FatalError("the `copilot` command was not found on PATH or in the WinGet packages folder "
                         "(install GitHub Copilot CLI, or set cli_path in the seat)")


def _usage(path: str) -> dict:
    """Token counts from --usage-output-file (recorded from Copilot CLI 1.0.89)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    details = data.get("tokenDetails") or {}
    count = lambda key: (details.get(key) or {}).get("tokenCount")
    tokens_out = count("output")
    # A repeated prompt is mostly a cache hit, which the file counts apart from fresh input.
    tokens_in = None if count("input") is None else sum(int(count(k) or 0) for k in ("input", "cache_read", "cache_write"))
    if tokens_in is None or tokens_out is None:
        metrics = [m.get("usage") or {} for m in (data.get("modelMetrics") or {}).values() if isinstance(m, dict)]
        tokens_in = sum(int(u.get("inputTokens", 0)) for u in metrics)
        tokens_out = sum(int(u.get("outputTokens", 0)) for u in metrics)
    return {"in": int(tokens_in or 0), "out": int(tokens_out or 0),
            "premium_requests": data.get("totalPremiumRequestCost")}


def read_events(stdout: str) -> dict:
    """The answer, the model that gave it, and any error, from Copilot's JSON event stream."""
    text, model, errors, exit_code = "", "", [], None
    for event in cli_common.json_lines(stdout):
        kind = str(event.get("type", ""))
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if kind == "assistant.message":
            if data.get("content"):
                text = data["content"]          # the last message of the turn is the answer
            model = data.get("model") or model
        elif kind == "session.auto_mode_resolved":
            model = model or data.get("chosenModel", "")
        elif kind == "result":
            exit_code = event.get("exitCode")
        elif "error" in kind:
            errors.append(str(data.get("message") or data.get("error") or event.get("message") or kind))
    return {"text": text, "model": model, "errors": errors, "exit_code": exit_code}


class CopilotCLIBackend(Backend):
    provider = "copilot_cli"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.cmd = find_copilot(cfg)
        self.effort = cfg.get("effort", "")    # none | minimal | low | medium | high | xhigh | max
        self.workdir = cli_common.scratch_dir("copilot")

    def _command(self, usage_path: str) -> list:
        cmd = self.cmd + ["--output-format", "json", "--stream", "off", "--no-auto-update",
                          "--no-custom-instructions", "--disable-builtin-mcps", "--log-level", "none",
                          "-C", self.workdir, "--usage-output-file", usage_path]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["--reasoning-effort", self.effort]
        return cmd + ["--available-tools"]      # no tool at all is available to the model

    def call(self, system: str, user: str, schema: dict, context: dict) -> CallResult:
        with tempfile.TemporaryDirectory(prefix="karamaniya-copilot-io-") as io:
            usage_path = os.path.join(io, "usage.json")
            code, stdout, stderr = cli_common.run(self._command(usage_path), cli_common.merged_prompt(system, user),
                                                  self.timeout + 30, cwd=self.workdir)
            usage = _usage(usage_path)
        events = read_events(stdout)
        text = events["text"].strip()
        failed = code != 0 or (events["exit_code"] not in (None, 0))
        if failed or not text:
            detail = "; ".join(events["errors"]) or stderr.strip() or f"exit code {code}, no answer"
            if any(marker.lower() in (detail + " " + stderr).lower() for marker in NOT_LOGGED_IN):
                raise FatalError("Copilot CLI is not logged in: run `copilot login` once, then try again")
            raise cli_common.classify(detail, "Copilot CLI")
        data = extract_json(text)
        if data is None and len(text) < 600 and cli_common.QUOTA_RE.search(text):
            raise cli_common.classify(text, "Copilot CLI")   # a used-up plan reported as the answer
        return CallResult(data=data, raw=text, served_model=events["model"] or self.model or "copilot default",
                          input_tokens=usage.get("in", 0), output_tokens=usage.get("out", 0),
                          cost_usd=self.cost(usage.get("in", 0), usage.get("out", 0)))
