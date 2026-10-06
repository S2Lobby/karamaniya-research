"""Run folders: config, a checkpoint after every month, and append-only logs."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .world import World


class RunStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _write_json(self, name: str, data) -> None:
        tmp = self.path / (name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, default=str)
        os.replace(tmp, self.path / name)

    def read_json(self, name: str):
        with open(self.path / name, encoding="utf-8") as f:
            return json.load(f)

    def exists(self, name: str) -> bool:
        return (self.path / name).exists()

    def save_config(self, cfg: dict) -> None:
        self._write_json("config.json", cfg)

    def save_checkpoint(self, world: World, council_state: dict, meta: dict) -> None:
        self._write_json("checkpoint.json", {"world": world.to_dict(), "council": council_state, "meta": meta})

    def load_checkpoint(self):
        d = self.read_json("checkpoint.json")
        return World.from_dict(d["world"]), d["council"], d["meta"]

    def _append(self, name: str, record: dict) -> None:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            with open(self.path / name, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def log(self, record: dict) -> None:
        self._append("log.jsonl", record)

    def mark(self) -> dict:
        """Where the append-only logs end now, so an abandoned month can be taken back out."""
        return {name: (self.path / name).stat().st_size if (self.path / name).exists() else 0
                for name in ("log.jsonl", "prompts.jsonl")}

    def rollback(self, mark: dict) -> None:
        with self._lock:
            for name, size in mark.items():
                p = self.path / name
                if p.exists() and p.stat().st_size > size:
                    with open(p, "r+b") as f:
                        f.truncate(size)

    def set_meta(self, meta: dict) -> None:
        """Update the checkpoint's notes without touching the saved world."""
        d = self.read_json("checkpoint.json")
        d["meta"] = {**d.get("meta", {}), **meta}
        self._write_json("checkpoint.json", d)

    def log_prompt(self, record: dict) -> None:
        self._append("prompts.jsonl", record)

    def read_log(self, kind: str | None = None) -> list:
        path = self.path / "log.jsonl"
        if not path.exists():
            return []
        out = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if kind is None or rec.get("type") == kind:
                    out.append(rec)
        return out
