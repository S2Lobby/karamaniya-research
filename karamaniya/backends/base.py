"""Common plumbing for every AI connector: results, JSON extraction, retries, cost."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass

RETRY_NOTE = ("Your previous answer could not be read as the required JSON object. Reply again with only "
              "the JSON object, no other text.")


class TransientError(Exception):
    """Worth retrying: rate limits, timeouts, server errors, dropped connections."""


class FatalError(Exception):
    """Not worth retrying: bad key, unknown model, malformed request."""


class QuotaError(Exception):
    """The seat's plan or balance is used up for hours (a subscription usage limit, no credit).
    The run pauses instead of letting the member silently abstain; resume it when the limit resets."""


@dataclass
class CallResult:
    data: object = None
    raw: str = ""
    served_model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    refusal: bool = False
    error: str = ""
    attempts: int = 0
    format_retry: bool = False
    quota: bool = False
    temperature: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("data")
        return d


def extract_json(text):
    """Pull a JSON object out of a model's reply, tolerating code fences and trailing commas."""
    if not text:
        return None
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    if fence:
        t = fence.group(1)
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return None
    chunk = t[start:end + 1]
    for attempt in (chunk, re.sub(r",\s*([}\]])", r"\1", chunk)):
        try:
            obj = json.loads(attempt)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            continue
    return None


class Backend:
    provider = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.model = cfg.get("model", "")
        self.price_in = float(cfg.get("price_in", 0.0))
        self.price_out = float(cfg.get("price_out", 0.0))
        self.retries = int(cfg.get("retries", 4))
        self.timeout = float(cfg.get("timeout", 600))

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        return tokens_in / 1e6 * self.price_in + tokens_out / 1e6 * self.price_out

    supports_temperature = False

    def prompt_budget(self, system_chars: int) -> int:
        """How many characters of user prompt this seat can take (the council trims to fit)."""
        if self.cfg.get("max_prompt_chars"):
            return int(self.cfg["max_prompt_chars"])
        return 60000

    def call(self, system: str, user: str, schema: dict, context: dict) -> CallResult:
        """One attempt. Raise TransientError or FatalError on failure."""
        raise NotImplementedError

    def _attempt(self, system: str, user: str, schema: dict, context: dict) -> CallResult:
        delay = 5.0
        last = ""
        for i in range(self.retries + 1):
            try:
                res = self.call(system, user, schema, context)
                res.attempts = i + 1
                return res
            except FatalError as exc:
                return CallResult(error=f"fatal: {exc}", attempts=i + 1)
            except QuotaError as exc:
                return CallResult(error=f"usage limit: {exc}", attempts=i + 1, quota=True)
            except TransientError as exc:
                last = str(exc)
                if i < self.retries:
                    time.sleep(delay)
                    delay = min(delay * 2, 120.0)
            except Exception as exc:  # a broken seat must never crash the whole run
                return CallResult(error=f"fatal: {type(exc).__name__}: {exc}", attempts=i + 1)
        return CallResult(error=f"gave up after {self.retries + 1} attempts: {last}", attempts=self.retries + 1)

    def complete(self, system: str, user: str, schema: dict, context: dict | None = None) -> CallResult:
        context = context or {}
        t0 = time.time()
        res = self._attempt(system, user, schema, context)
        if res.data is None and not res.refusal and not res.error and not res.quota:
            again = self._attempt(system, user + "\n\n" + RETRY_NOTE, schema, context)
            again.input_tokens += res.input_tokens
            again.output_tokens += res.output_tokens
            again.cost_usd += res.cost_usd
            again.attempts += res.attempts
            again.format_retry = True
            if again.data is None and not again.raw:
                again.raw = res.raw
            res = again
        res.latency_s = round(time.time() - t0, 2)
        return res
