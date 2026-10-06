"""Models through the Cline CLI (`cline`), for example Kimi K3 or GLM on a Cline Pass subscription.

Cline runs headless with --json output, tool auto-approval off, in an empty scratch folder, and
with the council's standing instructions as its system prompt in place of Cline's coding-agent
prompt. Cline has no schema option, so the answer is read out of the reply text (and asked for
once more if it cannot be read). On Windows Cline only takes the prompt as a command-line
argument; the council's prompts stay well under the 32,767-character limit.
"""
from __future__ import annotations

from threading import Lock

from . import cli_common
from .base import Backend, CallResult, FatalError, extract_json

EXE = ("node_modules/cline/node_modules/@cline/cli-windows-x64/bin/cline.exe",)
MAX_ARGS = 30000
_CLI_SESSION_LOCK = Lock()  # Cline CLI shares a local hub and session store across processes.


class ClineCLIBackend(Backend):
    provider = "cline_cli"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.cmd = cli_common.resolve(cfg, "cline", EXE)
        self.cline_provider = cfg.get("cline_provider", "")  # e.g. "cline-pass"; empty = Cline's default
        self.effort = cfg.get("effort", "")                  # none | low | medium | high | xhigh
        self.workdir = cli_common.scratch_dir("cline")

    def prompt_budget(self, system_chars: int) -> int:
        """Windows caps a command line near 32,767 characters, and Cline takes the prompt and
        the standing instructions as arguments; leave room for the flags and the model id."""
        fixed = sum(len(a) + 3 for a in self.cmd) + len(self.workdir) + len(self.model) + 260
        own = int(self.cfg.get("max_prompt_chars") or 10**9)
        # Report the room that actually exists. A floor here would advertise space the command
        # line does not have, and the council would trim to a budget the connector then refuses.
        return max(0, min(own, MAX_ARGS - system_chars - fixed))

    def call(self, system: str, user: str, schema: dict, context: dict) -> CallResult:
        cmd = self.cmd + ["--json", "--auto-approve", "false", "-c", self.workdir, "-s", system,
                          "-t", str(int(self.timeout))]
        if self.cline_provider:
            cmd += ["-P", self.cline_provider]
        if self.model:
            cmd += ["-m", self.model]
        effort = self.phase_setting(context, self.effort)
        if effort:
            cmd += ["--thinking", effort]
        # The council trims prompts to the budget this backend advertises, which is derived from
        # the same limit. A prompt can still arrive over it, and failing here used to abort the
        # whole run: one recorded run lost two seats at Month 1 and never recovered. Sending a cut
        # prompt costs this seat part of its context for one month; refusing costs the run.
        marker = "\n[...trimmed by the connector to fit the command line]"
        room = MAX_ARGS - sum(len(a) + 3 for a in cmd) - len(marker) - 3
        if room < 500:
            raise FatalError("Cline CLI: no command-line room left for a prompt after its flags")
        if len(user) > room:
            user = user[:room] + marker
            context["connector_trimmed"] = True
        cmd.append(user)
        progress = context.get("on_progress")
        draft = cli_common.StreamPreview(progress) if callable(progress) else None
        def on_line(line):
            try:
                event = cli_common.json_lines(line)[0]
            except IndexError:
                return
            if event.get("type") != "agent_event":
                return
            inner = event.get("event") or {}
            kind = inner.get("type", "")
            if kind in ("content_delta", "content_chunk") and inner.get("contentType") == "text":
                draft.append(inner.get("text") or inner.get("delta") or inner.get("content") or "")
            elif kind in ("content_end", "done") and inner.get("text"):
                draft.replace(inner["text"])
        with _CLI_SESSION_LOCK:
            code, stdout, stderr = cli_common.run(cmd, None, self.timeout + 30, cwd=self.workdir,
                                                   on_stdout_line=on_line if draft else None)
        events = cli_common.json_lines(stdout)
        errors, text, usage, finish, tool_calls = [], "", {}, "", 0
        for e in events:
            kind = e.get("type")
            if kind == "error":
                errors.append(e.get("message") or "error")
            elif kind == "agent_event":
                ev = e.get("event") or {}
                if ev.get("type") == "done":
                    text = ev.get("text") or text
                    usage = ev.get("usage") or usage
                    finish = ev.get("reason", finish)
                elif ev.get("type") == "content_end" and ev.get("contentType") == "text" and ev.get("text"):
                    text = text or ev["text"]
                elif ev.get("type") == "iteration_end":
                    tool_calls += int(ev.get("toolCallCount") or 0)
                elif ev.get("type") == "error":
                    errors.append(ev.get("message") or ev.get("error") or "error")
            elif kind == "run_result":
                usage = e.get("usage") or usage
                finish = e.get("finishReason", finish)
                if e.get("error"):
                    errors.append(str(e["error"]))
        for line in stderr.splitlines():
            if '"type":"error"' in line.replace(" ", ""):
                errors += [x.get("message", "") for x in cli_common.json_lines(line)]
        if not text:
            detail = errors[-1] if errors else (stderr.strip() or f"exit code {code}, finish {finish or '-'}")
            raise cli_common.classify(detail, "Cline CLI")
        data = extract_json(text)
        if data is None and len(text) < 600 and cli_common.QUOTA_RE.search(text):
            # A used-up plan can come back as the answer itself ("You have reached your monthly
            # Clinepass limit. The limit resets in 1h 11m..."), not as an error event.
            raise cli_common.classify(text, "Cline CLI")
        tokens_in = int(usage.get("inputTokens", 0))
        tokens_out = int(usage.get("outputTokens", 0))
        problems = f" (used {tool_calls} tool calls)" if tool_calls else ""
        return CallResult(data=data, raw=text + problems,
                          served_model=self.model or self.cline_provider or "cline default",
                          input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=self.cost(tokens_in, tokens_out))
