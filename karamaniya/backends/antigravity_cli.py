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
from .base import Backend, CallResult, TransientError, extract_json

NUMERIC = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf")


def _needs_strings(enum) -> bool:
    return isinstance(enum, list) and any(v == "" or not isinstance(v, str) for v in enum)


def _sent_values(enum: list) -> dict:
    """What Gemini is sent for each enum value, mapped to the value itself: an empty string as a
    word the enum does not already use, a number or other non-string as its JSON text."""
    used = {v for v in enum if isinstance(v, str)}
    empty = next((w for w in ("none", "empty", "blank") if w not in used), "(empty)")
    return {(empty if v == "" else v if isinstance(v, str) else json.dumps(v)): v for v in enum}


def gemini_schema(schema):
    """The schema in the form Gemini's function declarations accept (--json-schema becomes one).
    Gemini takes enum values only as non-empty strings and one type per field: the empty string
    that leaves an office out of a formation slate, and the forecast horizons 3, 6 and 12 (which
    the CLI forwards as empty strings), were rejected with INVALID_ARGUMENT before the model saw
    the prompt. Such an enum is sent as strings, "" as "none", and a type list such as
    ["string", "null"] as a nullable string. `restore` maps the answer back."""
    if isinstance(schema, list):
        return [gemini_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: (v if k in ("properties", "enum", "required") else gemini_schema(v)) for k, v in schema.items()}
    if isinstance(schema.get("properties"), dict):
        out["properties"] = {name: gemini_schema(sub) for name, sub in schema["properties"].items()}
    kind = schema.get("type")
    if isinstance(kind, list) and len([k for k in kind if k != "null"]) == 1:
        out["type"] = next(k for k in kind if k != "null")
        if "null" in kind:
            out["nullable"] = True
    if _needs_strings(schema.get("enum")):
        sent = _sent_values(schema["enum"])
        out["enum"] = list(sent)
        out["type"] = "string"
        for k in NUMERIC:
            out.pop(k, None)
        empty = [word for word, value in sent.items() if value == ""]
        if empty:
            note = f'"{empty[0]}" stands for the empty string "".'
            out["description"] = f'{schema["description"]} {note}' if schema.get("description") else note
    return out


def restore(data, schema):
    """Undo gemini_schema on the answer, so the council reads the values every other seat sends."""
    if not isinstance(schema, dict):
        return data
    if isinstance(data, str) and _needs_strings(schema.get("enum")):
        return _sent_values(schema["enum"]).get(data, data)
    props = schema.get("properties")
    if isinstance(data, dict) and isinstance(props, dict):
        return {k: restore(v, props.get(k)) for k, v in data.items()}
    if isinstance(data, list) and isinstance(schema.get("items"), dict):
        return [restore(x, schema["items"]) for x in data]
    return data


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
                json.dump(gemini_schema(schema), f)
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
        if not isinstance(data, dict) and not text.strip() and result.get("denied_actions"):
            # The CLI has no switch for its own tools. Now and then the model reaches for one (its
            # terminal, to list the scratch folder) instead of answering; headless mode denies it
            # and the turn ends with no answer. That is the harness, not the delegate: the same
            # prompt is sent again, as after a dropped connection.
            denied = ", ".join(str(a.get("display_name") or a.get("action")) for a in result["denied_actions"]
                               if isinstance(a, dict))
            raise TransientError(f"Antigravity CLI: no answer; the model reached for a tool ({denied or 'unknown'}), "
                                 "which headless mode denies")
        if not isinstance(data, dict):
            data = extract_json(text)
        if isinstance(data, dict):
            data = restore(data, schema)
        return CallResult(data=data, raw=text, served_model=served or "antigravity default",
                          input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=self.cost(tokens_in, tokens_out))
