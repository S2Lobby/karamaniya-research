"""Shared plumbing for seats that run a command-line AI: Claude Code, Codex, Cline, Antigravity.

Every call runs headless, without a shell and without a console window, in an empty scratch
folder, with the CLI's own tools switched off as far as each CLI allows. A call that runs past
its time limit is killed together with every process it started.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading

from .base import FatalError, QuotaError, TransientError

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# A plan or balance that is used up for hours: pause the run. Checked before the rate-limit test.
QUOTA_RE = re.compile(r"usage limit|session limit|limit reached|hit your (usage |session )?limit|reached your (\w+ ){0,3}limit"
                      r"|out of credits|insufficient (balance|credit|funds)"
                      r"|credit balance is too low|quota (exceeded|exhausted)|exceeded your (current )?quota"
                      r"|payment required|purchase more credits|upgrade to (pro|plus|max)"
                      r"|premium requests? (limit|allowance|quota)|out of premium requests|exceeded your premium", re.I)
# Short waits that only look like quota messages (per-minute quotas, "retry in 30s").
SHORT_WAIT_RE = re.compile(r"per minute|per-minute|retry in \d|retrydelay|try again in \d+ ?(s\b|sec|second|minute)", re.I)
NOT_QUOTA_RE = re.compile(r"context (window|length|limit)|too long|maximum context", re.I)
RATE_RE = re.compile(r"rate.?limit|too many requests|\b429\b|overloaded|\b529\b|\b50[0234]\b|temporarily unavailable"
                     r"|timed? ?out|timeout|connection (reset|refused|error)|network|ECONNRESET|ETIMEDOUT|socket hang up",
                     re.I)
AUTH_RE = re.compile(r"not logged in|log ?in again|please (log|sign) ?in|unauthori[sz]ed|authenticat|invalid (api )?key"
                     r"|\b401\b|\b403\b|expired token|token (has )?expired|no credentials", re.I)


def classify(text: str, name: str):
    """Turn a CLI's error text into the exception the retry logic understands."""
    msg = f"{name}: {text.strip()[:400]}"
    if SHORT_WAIT_RE.search(text):
        return TransientError(msg)
    if QUOTA_RE.search(text) and not NOT_QUOTA_RE.search(text):
        return QuotaError(msg)
    if AUTH_RE.search(text):
        return FatalError(f"{msg} (log in to {name} in a terminal, then test the seat again)")
    if RATE_RE.search(text):
        return TransientError(msg)
    return FatalError(msg)


def resolve(cfg: dict, name: str, exe_candidates=()) -> list:
    """The command prefix for a CLI: `cli_command` (a list), `cli_path`, or the program found on PATH.
    On Windows an npm shim (.cmd) goes through cmd.exe, which mangles arguments and caps a command
    line at 8191 characters, so the real executable behind the shim is preferred."""
    if cfg.get("cli_command"):
        cmd = cfg["cli_command"]
        return [str(c) for c in (cmd if isinstance(cmd, (list, tuple)) else [cmd])]
    if cfg.get("cli_path"):
        return [str(cfg["cli_path"])]
    found = shutil.which(name)
    if not found:
        raise FatalError(f"the `{name}` command was not found on PATH (install it, or set cli_path in the seat)")
    if os.name == "nt" and (found.lower().endswith((".cmd", ".ps1", ".bat")) or not os.path.splitext(found)[1]):
        base = os.path.dirname(found)
        for rel in exe_candidates:
            exe = os.path.join(base, *rel.split("/"))
            if os.path.exists(exe):
                return [exe]
        exe = os.path.splitext(found)[0] + ".exe"
        if os.path.exists(exe):
            return [exe]
    return [found]


def scratch_dir(tag: str) -> str:
    """An empty folder for the CLI to run in, so it has no project files to look at."""
    return tempfile.mkdtemp(prefix=f"karamaniya-{tag}-")


def run(cmd: list, input_text: str | None, timeout: float, cwd: str | None = None,
        env: dict | None = None, on_stdout_line=None) -> tuple:
    """Run a command without a shell. Returns (exit code, stdout, stderr) as text."""
    kwargs = {"stdin": subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
              "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "cwd": cwd, "env": env}
    if os.name == "nt":
        kwargs["creationflags"] = NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except OSError as exc:
        raise FatalError(f"could not start {cmd[0]}: {exc}") from exc
    data = input_text.encode("utf-8") if input_text is not None else None
    if on_stdout_line is None:
        try:
            out, err = proc.communicate(input=data, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            kill_tree(proc)
            try:
                proc.communicate(timeout=10)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                pass
            raise TransientError(f"timed out after {timeout:.0f}s") from exc
        return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    # Drain both pipes concurrently: a CLI can fill stderr while stdout is streaming.
    chunks = [[], []]
    def read_pipe(pipe, index):
        try:
            for line in pipe:
                chunks[index].append(line)
                if index == 0:
                    try:
                        on_stdout_line(line.decode("utf-8", "replace"))
                    except Exception:
                        pass  # a progress display cannot break or slow the model call
        finally:
            pipe.close()
    readers = [threading.Thread(target=read_pipe, args=(proc.stdout, 0), daemon=True),
               threading.Thread(target=read_pipe, args=(proc.stderr, 1), daemon=True)]
    for reader in readers:
        reader.start()
    try:
        if data is not None:
            try:
                proc.stdin.write(data)
            except BrokenPipeError:
                pass  # a CLI can reject its arguments before reading stdin
            finally:
                try:
                    proc.stdin.close()
                except BrokenPipeError:
                    pass
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        kill_tree(proc)
        raise TransientError(f"timed out after {timeout:.0f}s") from exc
    finally:
        for reader in readers:
            reader.join(timeout=10)
    return proc.returncode, b"".join(chunks[0]).decode("utf-8", "replace"), b"".join(chunks[1]).decode("utf-8", "replace")


class StreamPreview:
    """Collect answer text from JSONL events and send drafts to the live UI."""

    def __init__(self, callback):
        self.callback = callback
        self.text = ""

    def append(self, chunk: str) -> None:
        if chunk:
            self.text += chunk
            self.callback(self.text)

    def replace(self, text: str) -> None:
        if text and text != self.text:
            self.text = text
            self.callback(self.text)


def kill_tree(proc) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                           creationflags=NO_WINDOW, timeout=30)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def json_lines(text: str) -> list:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def merged_prompt(system: str, user: str) -> str:
    """For CLIs without a system-prompt option: the standing instructions go first, clearly marked."""
    return ("# Standing instructions (these apply to every turn)\n\n" + system.strip()
            + "\n\n# This turn\n\n" + user.strip())
