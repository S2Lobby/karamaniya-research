"""Any OpenAI-style chat API: OpenAI, DeepSeek, OpenRouter, LM Studio, llama.cpp server.

Plain HTTP (no SDK), so one connector covers every provider that speaks this format.
It asks for strict JSON-schema output where the provider supports it and falls back to
plain JSON mode, then to no format hint, if the provider rejects the request format.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .base import Backend, CallResult, FatalError, TransientError, extract_json

DEFAULTS = {
    "openai": {"base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY",
               "json_mode": "json_schema", "token_param": "max_completion_tokens"},
    "deepseek": {"base_url": "https://api.deepseek.com", "api_key_env": "DEEPSEEK_API_KEY",
                 "json_mode": "json_object", "token_param": "max_tokens"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY",
                   "json_mode": "json_schema", "token_param": "max_tokens", "max_tokens": 16000,
                   "max_tokens_cap": 65536},
    "lmstudio": {"base_url": "http://localhost:1234/v1", "api_key_env": "",
                 "json_mode": "json_schema", "token_param": "max_tokens"},
    "llamacpp": {"base_url": "http://localhost:8080/v1", "api_key_env": "",
                 "json_mode": "json_schema", "token_param": "max_tokens"},
    "openai_compat": {"base_url": "", "api_key_env": "", "json_mode": "json_object",
                      "token_param": "max_tokens"},
}
DOWNGRADE = {"json_schema": "json_object", "json_object": "none"}


class OpenAICompatBackend(Backend):
    provider = "openai_compat"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        d = DEFAULTS.get(cfg.get("provider", "openai_compat"), DEFAULTS["openai_compat"])
        self.base_url = (cfg.get("base_url") or d["base_url"]).rstrip("/")
        if not self.base_url:
            raise ValueError("openai_compat seats need base_url")
        key_env = cfg.get("api_key_env", d["api_key_env"])
        self.api_key = os.environ.get(key_env, "") if key_env else ""
        if key_env and not self.api_key:
            raise ValueError(f"environment variable {key_env} is not set")
        self.json_mode = cfg.get("json_mode", d["json_mode"])
        self.token_param = cfg.get("token_param", d["token_param"])
        # A reasoning model spends part of this on thinking the reply never shows: one such seat
        # used 5,700-7,700 of an 8,000 budget on ordinary turns and ran out on harder ones, leaving the
        # answer empty. A cut-off answer is retried with a larger budget until it fits or reaches the cap.
        self.max_tokens = int(cfg.get("max_tokens", d.get("max_tokens", 8000)))
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        self.max_tokens_cap = max(self.max_tokens, int(cfg.get("max_tokens_cap", d.get("max_tokens_cap", 32000))))
        self.reasoning_effort = cfg.get("reasoning_effort", "")
        self.extra = cfg.get("extra_body", {}) or {}

    supports_temperature = True

    def _body(self, system: str, user: str, schema: dict, temperature: float | None = None) -> dict:
        body = {"model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                self.token_param: self.max_tokens}
        if temperature is not None and not self.reasoning_effort:
            body["temperature"] = temperature
        if self.json_mode == "json_schema":
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "answer", "schema": schema, "strict": True}}
        elif self.json_mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        body.update(self.extra)
        return body

    def _post(self, body: dict) -> dict:
        req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(body).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            if exc.code in (408, 409, 429) or exc.code >= 500:
                raise TransientError(f"HTTP {exc.code}: {detail}") from exc
            raise _Http4xx(exc.code, detail) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise TransientError(f"connection error: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise TransientError("unreadable response") from exc

    def call(self, system: str, user: str, schema: dict, context: dict) -> CallResult:
        result, cut_off = self._call_once(system, user, schema, context)
        while result.data is None and cut_off and self.max_tokens < self.max_tokens_cap:
            # Keep retry progress explicit even if this logic is changed to use a non-doubling
            # budget later. A zero budget otherwise remains zero and can loop forever on cutoffs.
            self.max_tokens = min(self.max_tokens_cap, max(self.max_tokens + 1, self.max_tokens * 2))
            result, cut_off = self._call_once(system, user, schema, context)
        if result.data is None and cut_off:
            raise FatalError(f"the answer was cut off at {self.max_tokens} tokens (finish_reason=length): the "
                             f"model's thinking used the budget; raise max_tokens for this seat")
        return result

    def _call_once(self, system: str, user: str, schema: dict, context: dict) -> tuple:
        """One request. Returns (result, whether the token limit cut the answer off)."""
        for _ in range(4):
            try:
                # No `break` here: control has to fall through to the in-body error check below,
                # which is where a provider that reports its failure inside a 200 reply is handled.
                out = self._post(self._body(system, user, schema, context.get("temperature")))
            except _Http4xx as exc:
                text = exc.detail.lower()
                if "response_format" in text or "json_schema" in text or "json_object" in text:
                    if self.json_mode in DOWNGRADE:
                        self.json_mode = DOWNGRADE[self.json_mode]
                        continue
                if "max_completion_tokens" in text and self.token_param == "max_tokens":
                    self.token_param = "max_completion_tokens"
                    continue
                if "max_tokens" in text and self.token_param == "max_completion_tokens":
                    self.token_param = "max_tokens"
                    continue
                if "reasoning_effort" in text and self.reasoning_effort:
                    self.reasoning_effort = ""
                    continue
                raise FatalError(f"HTTP {exc.code}: {exc.detail}") from exc
            except TransientError as exc:
                # A provider can reject the structured-output request by failing INSIDE the stream
                # rather than answering with a 4xx. OpenRouter replies to a JSON schema its upstream
                # model cannot honour with "JSON error injected into SSE stream (code 502)" — a 5xx,
                # so it is retried, and retrying an identical request the provider structurally
                # cannot serve just fails five times and gives up. Treat it as a format rejection
                # and step the mode down, which is what a 4xx would have done immediately.
                text = str(exc).lower()
                if self.json_mode in DOWNGRADE and any(
                        token in text for token in ("json", "schema", "response_format", "sse")):
                    self.json_mode = DOWNGRADE[self.json_mode]
                    continue
                raise
            if isinstance(out.get("error"), dict):
                # OpenRouter reports an upstream failure inside a 200 reply rather than as an HTTP
                # status. It is worth naming, and trying again: the provider behind a model can fail
                # for a moment and then recover. But when the failure names the response format, it
                # is not momentary — the provider cannot serve the schema at all, and the retry that
                # follows would fail identically. Step the mode down here instead.
                code = out["error"].get("code")
                note = f"{out['error'].get('message', 'error')} (code {code})"
                message = str(out["error"].get("message", "")).lower()
                if self.json_mode in DOWNGRADE and any(
                        token in message for token in ("json", "schema", "response_format", "sse")):
                    self.json_mode = DOWNGRADE[self.json_mode]
                    continue
                if isinstance(code, int) and 400 <= code < 500 and code not in (408, 409, 429):
                    raise FatalError(f"provider error: {note}")
                raise TransientError(f"provider error: {note}")
            break
        else:
            raise FatalError("request format rejected after downgrades")
        choice = (out.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        usage = out.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens", 0))
        tokens_out = int(usage.get("completion_tokens", 0))
        served = out.get("model", self.model)
        cost = self.cost(tokens_in, tokens_out)
        finish = str(choice.get("finish_reason") or "")
        if msg.get("refusal"):
            return (CallResult(served_model=served, raw=str(msg["refusal"]), refusal=True,
                               input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=cost), False)
        text = msg.get("content") or ""
        if isinstance(text, list):
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        if not text.strip() and not tokens_out and finish != "length":
            # Nothing was generated at all (a reply in about a second, zero tokens): the provider
            # failed, the model did not answer. Not a formatting problem, so it is retried with
            # backoff rather than re-asked at once.
            raise TransientError(f"empty completion: 0 tokens, finish_reason={finish or 'none'}, "
                                 f"provider={out.get('provider') or served}")
        return (CallResult(data=extract_json(text), raw=text, served_model=served,
                           input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=cost),
                finish == "length")     # "length": the token limit ended the answer before it was finished


class _Http4xx(Exception):
    def __init__(self, code: int, detail: str):
        super().__init__(f"HTTP {code}")
        self.code = code
        self.detail = detail
