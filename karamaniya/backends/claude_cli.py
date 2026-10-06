"""Claude through the Claude Code CLI (`claude -p`), using your Claude subscription.

Runs headless with no tools, no session history and --safe-mode, so your CLAUDE.md,
memory, hooks and MCP servers never reach the council member. Environment variables
that force a different model or provider (ANTHROPIC_MODEL and friends, ANTHROPIC_BASE_URL,
ANTHROPIC_AUTH_TOKEN) are removed for the child process, and the model that actually
answered is read back from the CLI's report.

The same harness can carry another model that speaks Anthropic's API, such as DeepSeek:
set `base_url` (for DeepSeek, https://api.deepseek.com/anthropic) and `api_key_env` (the
variable holding that provider's key). The key goes to the child as ANTHROPIC_AUTH_TOKEN.
"""
from __future__ import annotations

import json
import os

from . import cli_common
from .base import Backend, CallResult, FatalError, QuotaError, TransientError

STRIP_ENV = ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
             "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_SMALL_FAST_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL",
             "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_CUSTOM_HEADERS")
# With another provider behind the harness, every model slot points at the seat's model, so no
# background request asks that provider for a Claude model it does not have.
MODEL_SLOTS = ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
               "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_SMALL_FAST_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL")
EXE = ("node_modules/@anthropic-ai/claude-code/bin/claude.exe",)


class ClaudeCLIBackend(Backend):
    provider = "claude_cli"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.cmd = cli_common.resolve(cfg, "claude", EXE)
        self.effort = cfg.get("effort", "")
        self.base_url = (cfg.get("base_url") or "").strip()
        self.key_env = (cfg.get("api_key_env") or "").strip()
        if self.key_env and not os.environ.get(self.key_env):
            raise ValueError(f"environment variable {self.key_env} is not set")
        self.workdir = cli_common.scratch_dir("claude")

    def _env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV}
        if self.base_url:
            env["ANTHROPIC_BASE_URL"] = self.base_url
            for slot in MODEL_SLOTS:
                env[slot] = self.model
        if self.key_env:
            env["ANTHROPIC_AUTH_TOKEN"] = os.environ.get(self.key_env, "")
        return env

    def call(self, system: str, user: str, schema: dict, context: dict) -> CallResult:
        progress = context.get("on_progress")
        streaming = callable(progress)
        cmd = self.cmd + ["-p", "--safe-mode", "--tools", "", "--no-session-persistence",
                          "--output-format", "stream-json" if streaming else "json",
                          "--json-schema", json.dumps(schema, separators=(",", ":")),
                          "--system-prompt", system]
        if streaming:
            cmd += ["--verbose", "--include-partial-messages"]
        if self.model:
            cmd += ["--model", self.model]
        effort = self.phase_setting(context, self.effort)
        if effort:
            cmd += ["--effort", effort]
        draft = cli_common.StreamPreview(progress) if streaming else None
        def on_line(line):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                return
            if event.get("type") == "stream_event":
                inner = event.get("event") or {}
                delta = inner.get("delta") or {}
                if inner.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                    draft.append(delta.get("text", ""))
                elif inner.get("type") == "content_block_delta" and delta.get("type") == "input_json_delta":
                    draft.append(delta.get("partial_json", ""))
            elif event.get("type") == "assistant":
                content = (event.get("message") or {}).get("content") or []
                text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
                if not text:
                    text = "".join(json.dumps(c.get("input"), ensure_ascii=False) for c in content
                                   if c.get("type") == "tool_use" and isinstance(c.get("input"), dict))
                if len(text) > len(draft.text):
                    draft.replace(text)
        code, stdout, stderr = cli_common.run(cmd, user, self.timeout, cwd=self.workdir, env=self._env(),
                                               on_stdout_line=on_line if streaming else None)
        if streaming:
            out = next((e for e in reversed(cli_common.json_lines(stdout)) if e.get("type") == "result"), None)
        else:
            try:
                out = json.loads(stdout)
            except json.JSONDecodeError:
                out = None
        if out is None:
            msg = (stderr or stdout or "").strip()[:400]
            raise cli_common.classify(f"unreadable output (exit {code}): {msg}", "Claude CLI")
        if not isinstance(out, dict):
            raise TransientError(f"Claude CLI: unexpected output (exit {code})")
        usage = out.get("usage") or {}
        cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
        cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
        tokens_in = int(usage.get("input_tokens", 0) + cache_read + cache_write)
        tokens_out = int(usage.get("output_tokens", 0))
        served = ",".join(sorted((out.get("modelUsage") or {}).keys()))
        text = out.get("result") or ""
        if out.get("is_error"):
            status = out.get("api_error_status")
            detail = f"{status}: {text[:300]}" if status else text[:300]
            if status == 402:
                raise QuotaError(f"Claude CLI: {detail}")
            err = cli_common.classify(detail, "Claude CLI")
            unknown_or_busy = status is None or status in (408, 429, 500, 502, 503, 504, 529)
            if isinstance(err, FatalError) and unknown_or_busy and not cli_common.AUTH_RE.search(detail):
                raise TransientError(f"Claude CLI: {detail}")
            raise err
        data = out.get("structured_output")
        refusal = out.get("stop_reason") == "refusal"
        return CallResult(data=data if isinstance(data, dict) else None, raw=text, served_model=served,
                          input_tokens=tokens_in, output_tokens=tokens_out,
                          cost_usd=self.cost(tokens_in, tokens_out, cache_read, cache_write), refusal=refusal,
                          cache_read_tokens=cache_read, cache_write_tokens=cache_write)
