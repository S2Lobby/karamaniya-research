"""Check, or deliberately regenerate, the prompt-freeze fixture.

    python tools/prompt_freeze.py            # does a default run still send exactly the recorded prompts?
    python tools/prompt_freeze.py --write    # record the current prompts (after bumping AGENT_PROMPT)

The fixture (tests/fixtures/prompt_freeze_engine5.json) is what makes "off by default" checkable: a
default four-month scripted run must reproduce the sha256 of every prompt. Writing it is a statement
that the prompts changed on purpose, so it is never done by the test suite.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import versions  # noqa: E402
from karamaniya.batch import simulate  # noqa: E402
from karamaniya.tokens import fingerprints  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "prompt_freeze_engine5.json")


def current(months: int) -> dict:
    tmp = tempfile.mkdtemp(prefix="karamaniya-freeze-")
    try:
        simulate(os.path.join(ROOT, "council.scripted.toml"), runs=1, months=months, first_seed=1,
                 runs_dir=tmp, prefix="freeze", check=False)
        return fingerprints(os.path.join(tmp, "freeze-seed1"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="overwrite the fixture with the current prompts")
    args = ap.parse_args()
    with open(FIXTURE, encoding="utf-8") as f:
        recorded = json.load(f)
    now = current(recorded["months"])
    same = (now["system_prompt_sha256"] == recorded["system_prompt_sha256"]
            and now["prompts"] == recorded["prompts"])
    if not args.write:
        print("prompts unchanged" if same else "prompts CHANGED from the recorded fixture")
        return 0 if same else 1
    recorded.update(now, engine=f"agent prompt {versions.AGENT_PROMPT}, world engine {versions.WORLD_ENGINE}")
    with open(FIXTURE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(recorded, f, indent=1)
        f.write("\n")
    print(f"wrote {FIXTURE} ({len(now['prompts'])} prompts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
