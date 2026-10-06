"""Claude through the Anthropic API (official `anthropic` SDK), with structured outputs.

Server-side refusal fallbacks are off by default: they would answer a refused request
with a different model, which hides the refusal and puts another model in the seat.
Set `fallbacks = true` in the seat config to turn them on.

ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN from the environment are ignored on purpose:
Claude Code setups often point them at another provider, which would put a different
model in the Claude seat without anyone noticing. Use `base_url` in the seat to change it.
"""
from __future__ import annotations

import os

from .base import Backend, CallResult, FatalError, TransientError, extract_json

DEFAULT_BASE_URL = "https://api.anthropic.com"


class AnthropicBackend(Backend):
    provider = "anthropic"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        import anthropic
        self._sdk = anthropic
        key_env = cfg.get("api_key_env", "ANTHROPIC_API_KEY")
        key = os.environ.get(key_env)
        if not key:
            # Passing a key also stops the SDK from falling back to ANTHROPIC_AUTH_TOKEN.
            raise ValueError(f"environment variable {key_env} is not set")
        self.client = anthropic.Anthropic(api_key=key, base_url=cfg.get("base_url") or DEFAULT_BASE_URL,
                                          max_retries=2, timeout=self.timeout)
        self.effort = cfg.get("effort", "")
        self.fallbacks = bool(cfg.get("fallbacks", False))
        self.max_tokens = int(cfg.get("max_tokens", 16000))

    def call(self, system: str, user: str, schema: dict, context: dict) -> CallResult:
        sdk = self._sdk
        output_config = {"format": {"type": "json_schema", "schema": schema}}
        if self.effort:
            output_config["effort"] = self.effort
        kwargs = dict(model=self.model, max_tokens=self.max_tokens,
                      system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                      messages=[{"role": "user", "content": user}],
                      output_config=output_config)
        progress = context.get("on_progress")
        try:
            if self.fallbacks:
                resp = self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            elif callable(progress):
                draft = ""
                with self.client.messages.stream(**kwargs) as stream:
                    for chunk in stream.text_stream:
                        draft += chunk
                        progress(draft)
                    resp = stream.get_final_message()
            else:
                resp = self.client.messages.create(**kwargs)
        except sdk.AuthenticationError as exc:
            raise FatalError(f"authentication failed: {exc}") from exc
        except sdk.PermissionDeniedError as exc:
            raise FatalError(f"permission denied: {exc}") from exc
        except sdk.NotFoundError as exc:
            raise FatalError(f"model or endpoint not found: {exc}") from exc
        except sdk.BadRequestError as exc:
            raise FatalError(f"bad request: {exc}") from exc
        except sdk.RateLimitError as exc:
            raise TransientError(f"rate limited: {exc}") from exc
        except sdk.APIStatusError as exc:
            if exc.status_code >= 500:
                raise TransientError(f"server error {exc.status_code}") from exc
            raise FatalError(f"API error {exc.status_code}: {exc}") from exc
        except sdk.APIConnectionError as exc:
            raise TransientError(f"connection error: {exc}") from exc

        usage = resp.usage
        tokens_in = int((usage.input_tokens or 0) + (getattr(usage, "cache_read_input_tokens", 0) or 0)
                        + (getattr(usage, "cache_creation_input_tokens", 0) or 0))
        tokens_out = int(usage.output_tokens or 0)
        cost = self.cost(tokens_in, tokens_out)
        if resp.stop_reason == "refusal":
            return CallResult(served_model=resp.model, input_tokens=tokens_in, output_tokens=tokens_out,
                              cost_usd=cost, refusal=True, raw="(refused)")
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
        return CallResult(data=extract_json(text), raw=text, served_model=resp.model,
                          input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=cost)
