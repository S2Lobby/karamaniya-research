"""A local model through Ollama's native API, with the answer forced to the JSON schema."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .base import Backend, CallResult, FatalError, TransientError, extract_json


def parse_think(raw):
    """true/false from a config file, or "on"/"off" from the control room; empty = the model's default."""
    if raw is None or isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("", "default"):
        return None
    return text not in ("off", "false", "0", "no", "none")


class OllamaBackend(Backend):
    provider = "ollama"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.base_url = (cfg.get("base_url") or os.environ.get("OLLAMA_API_BASE")
                         or "http://127.0.0.1:11434").rstrip("/")
        self.num_ctx = int(cfg.get("num_ctx", 12288))
        self.think = parse_think(cfg.get("think"))   # None = model default
        self.options = dict(cfg.get("options", {}) or {})

    supports_temperature = True

    def prompt_budget(self, system_chars: int) -> int:
        """Keep system prompt, user prompt and room for the answer inside the context window."""
        if self.cfg.get("max_prompt_chars"):
            return int(self.cfg["max_prompt_chars"])
        return max(6000, int(self.num_ctx * 3.2) - system_chars - 9000)

    def call(self, system: str, user: str, schema: dict, context: dict) -> CallResult:
        progress = context.get("on_progress")
        streaming = callable(progress)
        options = {"num_ctx": self.num_ctx, **self.options}
        if context.get("temperature") is not None:
            options["temperature"] = context["temperature"]
        body = {"model": self.model, "stream": streaming, "format": schema,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": options}
        if self.think is not None:
            body["think"] = bool(self.think)
        req = urllib.request.Request(self.base_url + "/api/chat", data=json.dumps(body).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if streaming:
                    chunks, out = [], {}
                    for line in resp:
                        part = json.loads(line)
                        chunks.append((part.get("message") or {}).get("content") or "")
                        progress("".join(chunks))
                        out = part
                    text = "".join(chunks)
                else:
                    out = json.loads(resp.read().decode("utf-8", "replace"))
                    text = (out.get("message") or {}).get("content") or ""
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            if exc.code == 404:
                raise FatalError(f"model '{self.model}' not found in Ollama: {detail}") from exc
            if exc.code >= 500:
                raise TransientError(f"HTTP {exc.code}: {detail}") from exc
            raise FatalError(f"HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise TransientError(f"cannot reach Ollama at {self.base_url} (is `ollama serve` running?): "
                                 f"{exc}") from exc
        return CallResult(data=extract_json(text), raw=text, served_model=out.get("model", self.model),
                          input_tokens=int(out.get("prompt_eval_count", 0)),
                          output_tokens=int(out.get("eval_count", 0)))
