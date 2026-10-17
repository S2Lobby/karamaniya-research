#!/usr/bin/env python3
"""Run the test suite in parallel on this machine (development only).

The authoritative gate is the CI command, `python -m unittest discover -s tests -t .`. This runner is
for local iteration and needs pytest and pytest-xdist:

    pip install -r requirements-dev.txt
    python tools/test_fast.py                      # the whole suite
    python tools/test_fast.py tests/test_engine27_media.py -v

`--dist loadfile` keeps each test module in one worker, so module-level state and temporary
directories stay in one process. On a 20-thread CPU (i7-13650HX) 12 workers are used; the wall time
was 87 s for 3,188 tests, against 369 s single-process.
"""
from __future__ import annotations

import os
import subprocess
import sys


def workers() -> int:
    """One worker per free logical CPU, capped so the desktop stays responsive."""
    cpus = os.cpu_count() or 4
    return max(2, min(12, cpus - 6))


def main(argv: list[str]) -> int:
    try:
        import pytest  # noqa: F401
        import xdist  # noqa: F401
    except ImportError:
        print("pytest and pytest-xdist are needed: python -m pip install -r requirements-dev.txt",
              file=sys.stderr)
        return 2
    cmd = [sys.executable, "-m", "pytest", "-q", "-n", str(workers()), "--dist", "loadfile"]
    cmd += argv or ["tests"]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
