"""AI connectors. Each seat in the config names a provider; make_backend builds it."""
from __future__ import annotations

from .base import Backend, CallResult, FatalError, QuotaError, TransientError

# Command-line AIs first: they run on subscriptions you are already logged into.
PROVIDERS = ("claude_cli", "codex_cli", "cline_cli", "antigravity_cli", "copilot_cli", "deepseek", "anthropic", "openai",
             "openrouter", "openai_compat", "lmstudio", "llamacpp", "ollama", "scripted")
CLI_PROVIDERS = ("claude_cli", "codex_cli", "cline_cli", "antigravity_cli", "copilot_cli")


def make_backend(cfg: dict) -> Backend:
    provider = cfg.get("provider", "")
    if provider == "anthropic":
        from .anthropic_api import AnthropicBackend
        return AnthropicBackend(cfg)
    if provider == "claude_cli":
        from .claude_cli import ClaudeCLIBackend
        return ClaudeCLIBackend(cfg)
    if provider == "codex_cli":
        from .codex_cli import CodexCLIBackend
        return CodexCLIBackend(cfg)
    if provider == "cline_cli":
        from .cline_cli import ClineCLIBackend
        return ClineCLIBackend(cfg)
    if provider in ("copilot_cli", "copilot"):
        from .copilot_cli import CopilotCLIBackend
        return CopilotCLIBackend(cfg)
    if provider in ("antigravity_cli", "agy"):
        from .antigravity_cli import AntigravityCLIBackend
        return AntigravityCLIBackend(cfg)
    if provider in ("openai", "deepseek", "openrouter", "openai_compat", "lmstudio", "llamacpp"):
        from .openai_compat import OpenAICompatBackend
        return OpenAICompatBackend(cfg)
    if provider == "ollama":
        from .ollama import OllamaBackend
        return OllamaBackend(cfg)
    if provider == "scripted":
        from .scripted import ScriptedBackend
        return ScriptedBackend(cfg)
    raise ValueError(f"unknown provider '{provider}'. Known: {', '.join(PROVIDERS)}")


__all__ = ["Backend", "CallResult", "FatalError", "QuotaError", "TransientError", "make_backend", "PROVIDERS",
           "CLI_PROVIDERS"]
