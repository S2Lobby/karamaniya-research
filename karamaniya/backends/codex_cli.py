"""GPT models through the Codex CLI (`codex exec`), using your ChatGPT subscription.

Runs headless and saves no session. Your ~/.codex config, rules, skills, plugins and apps are
not loaded, the shell tools are switched off, the sandbox is read-only, and it runs in an empty
scratch folder. The council's standing instructions go in as developer instructions, and the
answer is held to the JSON schema with --output-schema.

A ChatGPT plan has a usage limit. When Codex reports it, the run pauses (see QuotaError) and
can be resumed after the limit resets.
"""
from __future__ import annotations

import json
import os
import tempfile

from . import cli_common
from .base import Backend, CallResult, extract_json

DISABLE = ("shell_tool", "unified_exec", "plugins", "apps", "skill_search", "tool_suggest", "browser_use",
           "computer_use", "image_generation", "multi_agent", "goals", "hooks", "in_app_browser", "view_image",
           "sleep_tool", "personality")
# Keep Codex's own context blocks (skills list, sandbox notes, folder and shell) out of the prompt.
SETTINGS = ('web_search="disabled"', "skills.include_instructions=false", "include_permissions_instructions=false",
            "include_environment_context=false", "include_apps_instructions=false",
            "include_collaboration_mode_instructions=false")
PRIMITIVES = ("string", "number", "integer", "boolean")


def strict_schema(schema):
    """The schema in the form OpenAI's strict structured outputs accept (--output-schema is strict):
    every object lists all its properties as required, and a property that was optional becomes
    nullable. Without this Codex rejects any schema with an optional field (invalid_json_schema)."""
    if isinstance(schema, list):
        return [strict_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    # Codex's strict structured-output validator does not accept JSON Schema's
    # uniqueItems keyword. Keep the runtime's normalization/validation responsible
    # for uniqueness instead of making the whole response schema invalid.
    out = {k: (v if k in ("properties", "enum", "required") else strict_schema(v))
           for k, v in schema.items() if k != "uniqueItems"}
    props = schema.get("properties")
    if isinstance(props, dict):
        required = set(schema.get("required") or [])
        out["properties"] = {name: (strict_schema(sub) if name in required else _nullable(strict_schema(sub)))
                             for name, sub in props.items()}
        out["required"] = list(props)
        out.setdefault("additionalProperties", False)
    return out


def _nullable(s: dict) -> dict:
    if not isinstance(s, dict):
        return s
    if "anyOf" in s:
        return s if any(x.get("type") == "null" for x in s["anyOf"] if isinstance(x, dict)) \
            else {**s, "anyOf": s["anyOf"] + [{"type": "null"}]}
    kind = s.get("type")
    kinds = [kind] if isinstance(kind, str) else list(kind) if isinstance(kind, list) else []
    if kinds and all(k in PRIMITIVES + ("null",) for k in kinds):
        out = {**s, "type": kinds + ([] if "null" in kinds else ["null"])}
        if "enum" in s and None not in s["enum"]:
            out["enum"] = list(s["enum"]) + [None]
        return out
    return {"anyOf": [s, {"type": "null"}]}


def drop_optional_nulls(data, schema):
    """Undo strict_schema on the answer: an optional field the model set to null is left out, so
    the council reads the same shape it gets from every other seat."""
    if not isinstance(schema, dict):
        return data
    props = schema.get("properties")
    if isinstance(data, dict) and isinstance(props, dict):
        required = set(schema.get("required") or [])
        return {k: drop_optional_nulls(v, props.get(k)) for k, v in data.items()
                if not (v is None and k not in required)}
    if isinstance(data, list) and isinstance(schema.get("items"), dict):
        return [drop_optional_nulls(x, schema["items"]) for x in data]
    return data


def toml_string(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # a JSON string is a valid TOML basic string


class CodexCLIBackend(Backend):
    provider = "codex_cli"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.cmd = cli_common.resolve(cfg, "codex")
        self.effort = cfg.get("effort", "")
        self.workdir = cli_common.scratch_dir("codex")

    def call(self, system: str, user: str, schema: dict, context: dict) -> CallResult:
        with tempfile.TemporaryDirectory(prefix="karamaniya-codex-io-") as io:
            schema_path = os.path.join(io, "schema.json")
            answer_path = os.path.join(io, "answer.txt")
            with open(schema_path, "w", encoding="utf-8") as f:
                json.dump(strict_schema(schema), f)
            cmd = self.cmd + ["exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config",
                              "--ignore-rules", "--sandbox", "read-only", "--color", "never", "-C", self.workdir,
                              "--output-schema", schema_path, "-o", answer_path]
            for feature in DISABLE:
                cmd += ["--disable", feature]
            for setting in SETTINGS:
                cmd += ["-c", setting]
            cmd += ["-c", "developer_instructions=" + toml_string(system)]
            if self.model:
                cmd += ["-m", self.model]
            if self.effort:
                cmd += ["-c", "model_reasoning_effort=" + toml_string(self.effort)]
            cmd.append("-")  # the prompt comes on stdin, so its length is not limited by the command line
            progress = context.get("on_progress")
            draft = cli_common.StreamPreview(progress) if callable(progress) else None
            def on_line(line):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    return
                if event.get("type") in ("item.updated", "item.completed"):
                    item = event.get("item") or {}
                    if item.get("type") in ("agent_message", "assistant_message") and item.get("text"):
                        draft.replace(item["text"])
            code, stdout, stderr = cli_common.run(cmd, user, self.timeout, cwd=self.workdir,
                                                   on_stdout_line=on_line if draft else None)
            answer = ""
            if os.path.exists(answer_path):
                with open(answer_path, encoding="utf-8", errors="replace") as f:
                    answer = f.read().strip()
        events = cli_common.json_lines(stdout)
        errors, usage, text = [], {}, ""
        for e in events:
            kind = e.get("type")
            if kind == "error" and e.get("message"):
                errors.append(e["message"])
            elif kind == "turn.failed":
                errors.append((e.get("error") or {}).get("message") or "turn failed")
            elif kind == "turn.completed":
                usage = e.get("usage") or usage
            elif kind == "item.completed":
                item = e.get("item") or {}
                if item.get("type") in ("agent_message", "assistant_message") and item.get("text"):
                    text = item["text"]
        text = answer or text
        if not text:
            detail = errors[-1] if errors else (stderr.strip() or stdout.strip() or f"exit code {code}")
            raise cli_common.classify(detail, "Codex CLI")
        tokens_in = int(usage.get("input_tokens", 0))
        tokens_out = int(usage.get("output_tokens", 0)) + int(usage.get("reasoning_output_tokens", 0))
        data = extract_json(text)
        return CallResult(data=drop_optional_nulls(data, schema) if data is not None else None, raw=text,
                          served_model=self.model or "codex default",
                          input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=self.cost(tokens_in, tokens_out))
