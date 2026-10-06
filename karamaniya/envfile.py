"""API keys kept in a local .env file (NAME=value lines), so the control room can save them.

Variables in .env win over the same variables in your shell, for this program only. That
matters when your shell points ANTHROPIC_* variables at another provider for Claude Code.
Nothing in this module ever hands a key's value back to the control room page.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
PROVIDER_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
                 "deepseek": "DEEPSEEK_API_KEY", "openrouter": "OPENROUTER_API_KEY"}

_shell = {}  # values the shell had before .env overrode them, restored if a key is removed


def _parse(line: str):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None, None
    name, _, value = line.partition("=")
    name = name.strip()
    if name.startswith("export "):
        name = name[len("export "):].strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return (name, value) if NAME_RE.match(name) else (None, None)


def read_env(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        name, value = _parse(line)
        if name:
            out[name] = value
    return out


def load_env(path) -> list:
    """Put the file's variables into this process's environment. Returns their names."""
    values = read_env(path)
    for name, value in values.items():
        if name in os.environ and name not in _shell and os.environ[name] != value:
            _shell[name] = os.environ[name]
        os.environ[name] = value
    return sorted(values)


def save_key(path, name: str, value: str) -> None:
    """Set (or with an empty value, remove) one variable in .env and in this process."""
    if not NAME_RE.match(name or ""):
        raise ValueError("a variable name uses capital letters, digits and _ (like OPENAI_API_KEY)")
    value = (value or "").strip()
    if any(ch in value for ch in "\r\n\0") or len(value) > 2000:
        raise ValueError("that value cannot be stored (line breaks, or too long)")
    p = Path(path)
    was_in_file = name in read_env(p)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    kept = [ln for ln in lines if _parse(ln)[0] != name]
    if value:
        kept.append(f"{name}={value}")
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    if value:
        if not was_in_file and name in os.environ and name not in _shell:
            _shell[name] = os.environ[name]  # the shell's value, put back if the key is removed later
        os.environ[name] = value
    elif name in _shell:
        os.environ[name] = _shell.pop(name)
    else:
        os.environ.pop(name, None)


def key_status(path, names) -> list:
    """Which variables are set and where they come from. Never the values."""
    in_file = read_env(path)
    out = []
    for name in names:
        if name in in_file and in_file[name]:
            source = ".env"
        elif os.environ.get(name):
            source = "environment"
        else:
            source = ""
        out.append({"name": name, "set": bool(source), "source": source,
                    "shadows_shell": name in _shell})
    return out
