"""Models through the Cline CLI (`cline`), for example Kimi K3 or GLM on a Cline Pass subscription.

Cline runs headless with --json output, tool auto-approval off, in an empty scratch folder, and
with the council's standing instructions as its system prompt in place of Cline's coding-agent
prompt. Cline has no schema option, so the answer is read out of the reply text (and asked for
once more if it cannot be read).

Cline takes the standing instructions and the prompt as command-line arguments, and Windows caps a
command line near 32,767 characters. A prompt longer than the room left used to be cut to fit:
in one recorded run the Kimi seat's prompts were cut to about 19,000 characters every month
while the other seats were sent up to 52,000. A prompt that does not fit now goes in two parts: its
opening as the argument and the rest on stdin, which Cline appends after a blank line
(`${prompt}\n\n${stdin}`, Cline CLI 3.0), so the opening ends at a blank line and the model reads
the prompt as it was written. If Cline is seen to answer from the opening alone (its count of input
tokens far below the prompt's length), the seat goes back to cutting prompts to fit, as before.
"""
from __future__ import annotations

from threading import Lock

from . import cli_common
from .base import Backend, CallResult, FatalError, extract_json, reasoning

EXE = ("node_modules/cline/node_modules/@cline/cli-windows-x64/bin/cline.exe",)
MAX_ARGS = 30000
MIN_ROOM = 500             # the least of a prompt worth sending on the command line
# Characters per input token below which a split prompt must have been read whole: tokenizers take
# about 2.5 to 4.5 characters of English per token, and an answer from the opening alone counts only it.
CHARS_PER_TOKEN_CEILING = 5.0
_CLI_SESSION_LOCK = Lock()  # Cline CLI shares a local hub and session store across processes.


def split_prompt(text: str, room: int) -> tuple:
    """The prompt's opening for the command line (at most `room` characters) and the rest for stdin.
    Cline joins the two with a blank line, so the cut is made at the first blank line when it is close
    enough to the start, and the model reads exactly the prompt that was written."""
    cut = text.find("\n\n")
    if 0 < cut <= room and text[cut + 2:].strip():
        return text[:cut], text[cut + 2:]
    cut = text.rfind("\n", 0, room)      # the next best place: a line break, which the join makes a blank line
    if cut > 0:
        return text[:cut], text[cut + 1:]
    return text[:room], text[room:]


class ClineCLIBackend(Backend):
    provider = "cline_cli"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.cmd = cli_common.resolve(cfg, "cline", EXE)
        self.cline_provider = cfg.get("cline_provider", "")  # e.g. "cline-pass"; empty = Cline's default
        self.effort = cfg.get("effort", "")                  # none | low | medium | high | xhigh
        self.workdir = cli_common.scratch_dir("cline")
        # A prompt too long for the command line goes partly on stdin, until Cline is seen to ignore it.
        self.stdin_ok = True

    def prompt_budget(self, system_chars: int) -> int:
        """The standing instructions always go on the command line, so they and the flags must fit.
        Then a prompt's length is limited only as any other seat's is (max_prompt_chars, or the
        default), since what does not fit on the command line goes on stdin; unless Cline has been seen
        to ignore stdin, when the prompt has to fit in the room left on the command line."""
        fixed = sum(len(a) + 3 for a in self.cmd) + len(self.workdir) + len(self.model) + 260
        room = MAX_ARGS - system_chars - fixed
        if room < MIN_ROOM:
            # Report the room that actually exists. A floor here would advertise space the command
            # line does not have, and the council would trim to a budget the connector then refuses.
            return max(0, room)
        if self.stdin_ok:
            return super().prompt_budget(system_chars)
        own = int(self.cfg.get("max_prompt_chars") or 10**9)
        return max(0, min(own, room))

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
        marker = "\n[...trimmed by the connector to fit the command line]"
        room = MAX_ARGS - sum(len(a) + 3 for a in cmd) - len(marker) - 3
        if room < MIN_ROOM:
            raise FatalError("Cline CLI: no command-line room left for a prompt after its flags")
        rest = None
        if len(user) > room and self.stdin_ok:
            head, rest = split_prompt(user, room)
            cmd.append(head)
        else:
            # A prompt can still arrive over the room (when stdin cannot be used), and failing here
            # used to abort the whole run: one recorded run lost two seats at Month 1 and never
            # recovered. Sending a cut prompt costs this seat part of its context for one month;
            # refusing costs the run.
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
            code, stdout, stderr = cli_common.run(cmd, rest, self.timeout + 30, cwd=self.workdir,
                                                   on_stdout_line=on_line if draft else None)
        events = cli_common.json_lines(stdout)
        errors, text, usage, finish, tool_calls, thoughts = [], "", {}, "", 0, []
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
                elif (ev.get("type") == "content_end" and ev.get("contentType") in ("reasoning", "thinking")
                      and ev.get("text")):
                    thoughts.append(ev["text"])
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
        # Cached input, should a provider count it apart, was still read: it counts for the check below.
        seen = tokens_in + int(usage.get("cacheReadTokens", 0) or 0) + int(usage.get("cacheWriteTokens", 0) or 0)
        if rest is not None and 0 < seen * CHARS_PER_TOKEN_CEILING < len(system) + len(user):
            # Far fewer input tokens than the prompt holds: this Cline answered from the opening alone
            # and never read stdin. Ask again with the prompt cut to fit, as this connector used to, and
            # keep doing so for this seat; the first answer's tokens are still counted.
            self.stdin_ok = False
            again = self.call(system, user, schema, context)
            again.input_tokens += tokens_in
            again.output_tokens += tokens_out
            again.cost_usd += self.cost(tokens_in, tokens_out)
            return again
        problems = f" (used {tool_calls} tool calls)" if tool_calls else ""
        return CallResult(data=data, raw=text + problems,
                          served_model=self.model or self.cline_provider or "cline default",
                          input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=self.cost(tokens_in, tokens_out),
                          reasoning_text=reasoning(*thoughts))
