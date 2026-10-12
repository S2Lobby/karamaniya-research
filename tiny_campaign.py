"""The overnight campaign: many runs of the five-tiny-model council, unattended, on this PC's GPU.

Started by ../start-campaign.cmd (in the folder above this repo root). In order, it:
  1. checks the PC: Python, the charger, the GPU (it waits for the GPU after a boot), disk, the plan;
  2. starts its OWN Ollama on a private port with all five models kept in VRAM (your normal Ollama on
     11434 is left alone), makes sure the models are pulled, sends one tiny call per seat and checks that
     every model sits entirely on the GPU;
  3. runs the plan in campaign_plan.toml: a core grid of runs (cells x seat rotations, one world), then
     replicate runs in fresh worlds until the morning, several runs at the same time (they share the
     five loaded models); a run is a new run, or a resume if it was interrupted;
  4. watches Ollama (restarts it if it dies), keeps the PC awake, logs GPU temperature and power;
  5. writes everything down: a row per run in runs.csv, a summary, every console line, the Ollama log.

Everything it writes about itself goes to overnight_logs/<campaign name>/ beside this file; the runs go to
--runs-dir as <campaign name>-<cell>-r<rotation>-s<seed>. Starting it again continues where it stopped:
finished runs are skipped, interrupted ones are resumed from their last finished month.
"""
from __future__ import annotations

import argparse
import copy
import csv
import ctypes
import datetime as dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import traceback
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

NOWINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEWGROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

# Five models resident at once on an 8 GB card: one request at a time per model, a quantised KV cache (flash
# attention is what allows it) and no unloading. Measured on the RTX 4060 Laptop: ~7.0 GB in use with
# NUM_PARALLEL=1. With NUM_PARALLEL=2 the KV caches double and smollm2 is evicted (measured), so two runs at
# once share the models by queueing their requests, not by parallel slots.
OLLAMA_ENV = {"OLLAMA_MAX_LOADED_MODELS": "5", "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_KEEP_ALIVE": "-1",
              "OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0"}
SCENARIOS = ["fiscal-inheritance", "security-crisis", "regional-divide", "trade-dependency",
             "fragile-independence", "post-regime-transition"]
NOW = dt.datetime.now


# ---- logging ---------------------------------------------------------------------------------------
class Log:
    def __init__(self, path: Path):
        self.fh = open(path, "a", encoding="utf-8", buffering=1)
        self.lock = threading.Lock()

    def __call__(self, msg: str, console: bool = True) -> None:
        line = f"[{NOW():%Y-%m-%d %H:%M:%S}] {msg}"
        with self.lock:
            self.fh.write(line + "\n")
            if console:
                try:
                    print(line, flush=True)
                except Exception:
                    pass


# ---- Windows odds and ends ---------------------------------------------------------------------------
def disable_quick_edit() -> None:
    """A click inside a console window freezes whatever prints to it until a key is pressed. On a job left
    running overnight that is a real way to lose the night, so selection is switched off."""
    try:
        k = ctypes.windll.kernel32
        handle = k.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(handle, ctypes.byref(mode)):
            k.SetConsoleMode(handle, (mode.value | 0x0080) & ~0x0040)
    except Exception:
        pass


class KeepAwake(threading.Thread):
    """Stops Windows sleeping while the job runs (it does not stop a closed lid from sleeping a laptop)."""
    daemon = True

    def __init__(self):
        super().__init__()
        self.done = threading.Event()

    def run(self) -> None:
        try:
            k = ctypes.windll.kernel32
            k.SetThreadExecutionState.argtypes = [ctypes.c_uint32]
            k.SetThreadExecutionState.restype = ctypes.c_uint32
            k.SetThreadExecutionState(0x80000001)          # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            self.done.wait()
            k.SetThreadExecutionState(0x80000000)          # back to normal
        except Exception:
            pass


class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_uint32), ("BatteryFullLifeTime", ctypes.c_uint32)]


def on_battery():
    """True on battery, False on mains, None if Windows does not say."""
    try:
        status = _PowerStatus()
        ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status))
        return {0: True, 1: False}.get(status.ACLineStatus)
    except Exception:
        return None


def pid_alive(pid: int) -> bool:
    try:
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    except Exception:
        return False


def quiet(cmd, timeout=30) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=NOWINDOW,
                         encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout or f"exit code {out.returncode}").strip()[:300])
    return out.stdout


def powershell(script: str, timeout=30) -> str:
    return quiet(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout)


def gpu_sample() -> dict:
    fields = "name,memory.total,memory.used,temperature.gpu,power.draw,utilization.gpu,clocks.sm,driver_version"
    row = quiet(["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"]).strip().splitlines()[0]
    name, total, used, temp, power, util, clock, driver = [x.strip() for x in row.split(",")]

    def num(text):
        try:
            return float(text)
        except ValueError:
            return None
    return {"name": name, "vram_total_mib": num(total), "vram_used_mib": num(used), "temp_c": num(temp),
            "power_w": num(power), "util_pct": num(util), "clock_mhz": num(clock), "driver": driver}


def lid_closes_to_sleep():
    """True/False/None: does closing the lid put this PC to sleep on mains power? (read-only)"""
    try:
        text = quiet(["powercfg", "/query", "SCHEME_CURRENT", "SUB_BUTTONS", "LIDACTION"])
        hit = re.search(r"Current AC Power Setting Index:\s*0x([0-9a-fA-F]+)", text)
        return int(hit.group(1), 16) != 0 if hit else None
    except Exception:
        return None


def hardware_info() -> dict:
    info = {"platform": platform.platform(), "python": sys.version.split()[0], "cpu": platform.processor(),
            "cpu_threads": os.cpu_count()}
    try:
        class _Mem(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                        ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                        ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                        ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                        ("sullAvailExtendedVirtual", ctypes.c_uint64)]
        mem = _Mem()
        mem.dwLength = ctypes.sizeof(_Mem)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
        info["ram_gb"] = round(mem.ullTotalPhys / 1e9, 1)
    except Exception:
        pass
    try:
        info["bios_and_machine"] = json.loads(powershell(
            "$b=Get-CimInstance Win32_BIOS; $s=Get-CimInstance Win32_ComputerSystem; "
            "[pscustomobject]@{bios_version=$b.SMBIOSBIOSVersion; bios_date=[string]$b.ReleaseDate; "
            "bios_vendor=$b.Manufacturer; maker=$s.Manufacturer; model=$s.Model} | ConvertTo-Json -Compress"))
    except Exception:
        pass
    try:
        info["gpu"] = gpu_sample()
    except Exception:
        pass
    return info


def http_json(url: str, timeout: float = 5):
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


# ---- our own Ollama ----------------------------------------------------------------------------------
def find_ollama():
    exe = shutil.which("ollama")
    if exe:
        return exe
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    return str(local) if local.exists() else None


class Ollama:
    def __init__(self, exe: str, port: int, logfile: Path, log: Log):
        self.exe, self.port, self.logfile, self.log = exe, port, logfile, log
        self.base = f"http://127.0.0.1:{port}"
        self.proc = None
        self.restarts = 0

    def env(self) -> dict:
        return {**os.environ, **OLLAMA_ENV, "OLLAMA_HOST": f"127.0.0.1:{self.port}"}

    def alive(self) -> bool:
        try:
            return "version" in http_json(self.base + "/api/version", timeout=6)
        except Exception:
            return False

    def kill_listener(self) -> None:
        """Whatever Ollama is still answering on OUR port is a leftover (a window closed mid-run): it is
        holding models in VRAM with unknown settings, so it is stopped rather than reused."""
        try:
            pids = powershell(f"(Get-NetTCPConnection -LocalPort {self.port} -State Listen "
                              "-ErrorAction SilentlyContinue).OwningProcess").split()
        except Exception:
            pids = []
        for pid in {p for p in pids if p.isdigit()}:
            self.log(f"stopping the leftover Ollama on port {self.port} (pid {pid})")
            subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True, creationflags=NOWINDOW)
        time.sleep(3)

    def start(self) -> None:
        if self.alive():
            self.kill_listener()
            if self.alive():
                raise RuntimeError(f"something still answers on port {self.port}; pass --port with a free port")
        logfh = open(self.logfile, "ab")
        self.proc = subprocess.Popen([self.exe, "serve"], env=self.env(), stdout=logfh, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, creationflags=NOWINDOW | NEWGROUP)
        for _ in range(90):
            if self.alive():
                self.log(f"Ollama up on port {self.port} (pid {self.proc.pid})")
                return
            if self.proc.poll() is not None:
                break
            time.sleep(1)
        raise RuntimeError(f"Ollama did not come up on port {self.port}; see {self.logfile}")

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True,
                           creationflags=NOWINDOW)
        self.proc = None

    def restart(self) -> None:
        self.restarts += 1
        self.log(f"restarting Ollama (restart #{self.restarts})")
        self.stop()
        time.sleep(3)
        self.start()

    def tags(self) -> list:
        return http_json(self.base + "/api/tags").get("models", [])

    def loaded(self) -> list:
        return http_json(self.base + "/api/ps").get("models", [])


class Watchdog(threading.Thread):
    """Every 15 s: is Ollama answering? (four misses in a row, or a dead process, restart it). Every minute:
    GPU temperature, power, memory and load to gpu.csv, with a warning when it runs hot. Every 5 minutes:
    which models are loaded and how much of each is on the GPU, to ollama_ps.jsonl."""
    daemon = True

    def __init__(self, server: Ollama, folder: Path, log: Log):
        super().__init__()
        self.server, self.folder, self.log = server, folder, log
        self.done = threading.Event()
        self.hot_warned = 0.0
        self.last_gpu = {}
        self.csv_path = folder / "gpu.csv"
        if not self.csv_path.exists():
            self.csv_path.write_text("time,temp_c,power_w,vram_used_mib,util_pct,clock_mhz\n", encoding="utf-8")

    def run(self) -> None:
        misses, t_gpu, t_ps = 0, 0.0, 0.0
        while not self.done.wait(15):
            try:
                dead = self.server.proc is not None and self.server.proc.poll() is not None
                misses = 0 if self.server.alive() else misses + 1
                if dead or misses >= 4:
                    misses = 0
                    self.server.restart()
                if time.time() - t_gpu >= 60:
                    t_gpu = time.time()
                    g = self.last_gpu = gpu_sample()
                    with open(self.csv_path, "a", encoding="utf-8") as fh:
                        fh.write(f"{NOW():%Y-%m-%d %H:%M:%S},{g['temp_c']},{g['power_w']},"
                                 f"{g['vram_used_mib']},{g['util_pct']},{g['clock_mhz']}\n")
                    if (g["temp_c"] or 0) >= 90 and time.time() - self.hot_warned > 600:
                        self.hot_warned = time.time()
                        self.log(f"WARNING: the GPU is at {g['temp_c']:.0f} C")
                if time.time() - t_ps >= 300:
                    t_ps = time.time()
                    rows = [{"name": m["name"], "size": m.get("size"), "size_vram": m.get("size_vram"),
                             "context": m.get("context_length"), "expires_at": m.get("expires_at")}
                            for m in self.server.loaded()]
                    with open(self.folder / "ollama_ps.jsonl", "a", encoding="utf-8") as fh:
                        fh.write(json.dumps({"time": f"{NOW():%Y-%m-%d %H:%M:%S}", "models": rows}) + "\n")
            except Exception as exc:          # the watchdog itself must never die
                self.log(f"watchdog: {type(exc).__name__}: {exc}", console=False)


# ---- the plan ------------------------------------------------------------------------------------------
def load_plan(path: Path) -> dict:
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    c = raw.get("campaign", {})
    cells = raw.get("cell") or [{"name": "base"}]
    return {"name": str(c.get("name", "tiny5")),
            "base_config": str((path.parent / c.get("base_config", "council.tiny-local.toml")).resolve()),
            "months": int(c.get("months", 36)), "workers": int(c.get("workers", 2)), "seed": int(c.get("seed", 1)),
            "founding_scenario": str(c.get("founding_scenario", "fiscal-inheritance")),
            "rotations": [int(x) for x in c.get("rotations", [0, 1, 2, 3, 4])], "fill": bool(c.get("fill", True)),
            "fill_until": str(c.get("fill_until", "07:30")), "max_hours": float(c.get("max_hours", 11)),
            "grace_minutes": float(c.get("grace_minutes", 45)), "extra_seed_start": int(c.get("extra_seed_start", 101)),
            "replicates": int(c.get("replicates", 1)), "distinct_seeds": bool(c.get("distinct_seeds", False)),
            "seed_start": int(c.get("seed_start", 1001)), "scenario_mode": str(c.get("scenario_mode", "fixed")),
            "cells": [dict(cell) for cell in cells]}


def make_job(plan: dict, kind: str, index: int, cell: dict, rotation: int, seed: int, scenario: str) -> dict:
    tag = f"x{index:03d}-" if kind == "extra" else ""
    return {"id": f"{plan['name']}-{tag}{cell['name']}-r{rotation}-s{seed}", "kind": kind, "index": index,
            "cell": cell["name"], "rotation": rotation, "seed": seed, "scenario": scenario,
            "overrides": {k: v for k, v in cell.items() if k != "name"}}


def core_jobs(plan: dict) -> list:
    """replicates x rotations x cells, one full round of rotations x cells at a time. With distinct_seeds every
    run has its own world seed; with scenario_mode "cycle" the founding scenario changes from run to run."""
    jobs, i = [], 0
    for _round in range(plan["replicates"]):
        for rot in plan["rotations"]:
            for cell in plan["cells"]:
                i += 1
                seed = plan["seed_start"] + i - 1 if plan["distinct_seeds"] else plan["seed"]
                scenario = SCENARIOS[(i - 1) % len(SCENARIOS)] if plan["scenario_mode"] == "cycle" else plan["founding_scenario"]
                jobs.append(make_job(plan, "core", i, cell, rot, seed, scenario))
    return jobs


def extra_job(plan: dict, n: int) -> dict:
    cell = plan["cells"][(n - 1) % len(plan["cells"])]
    rot = plan["rotations"][(n - 1) % len(plan["rotations"])]
    return make_job(plan, "extra", n, cell, rot, plan["extra_seed_start"] + n - 1, SCENARIOS[(n - 1) % len(SCENARIOS)])


def write_job_config(plan: dict, job: dict, base_cfg: dict, folder: Path) -> Path:
    """One council file per run: the five seats rotated, the world and the cell's conditions set."""
    from karamaniya.config import dump_config, load_config, normalize_config
    seats = copy.deepcopy(base_cfg["seats"])
    k = job["rotation"] % len(seats)
    run = {**base_cfg["run"], "months": plan["months"], "seed": job["seed"], "founding_scenario": job["scenario"],
           "shuffle_seats": False, **job["overrides"]}
    cfg = normalize_config({"run": run, "seat": seats[k:] + seats[:k]}, source=job["id"])
    path = folder / "configs" / f"{job['id']}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_config(cfg), encoding="utf-8")
    load_config(path)                                       # it must read back
    return path


# ---- one run ---------------------------------------------------------------------------------------------
def inspect_run(path: Path, months: int) -> dict:
    """new / partial / done, without touching the folder."""
    if not (path / "checkpoint.json").exists():
        return {"state": "new", "months_done": 0}
    try:
        from karamaniya.storage import RunStore
        world, _council, meta = RunStore(path).load_checkpoint()
    except Exception as exc:
        return {"state": "unreadable", "months_done": 0, "error": f"{type(exc).__name__}: {exc}"}
    finished = world.ended() or len(world.history) >= months
    return {"state": "done" if finished else "partial", "months_done": len(world.history),
            "outcome": (world.outcome or {}).get("type", ""), "outcome_text": (world.outcome or {}).get("text", ""),
            "stopped": (meta or {}).get("stopped", "")}


class Children:
    lock = threading.Lock()
    procs: set = set()

    @classmethod
    def kill_all(cls) -> None:
        with cls.lock:
            for proc in list(cls.procs):
                if proc.poll() is None:
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                                   creationflags=NOWINDOW)


def stream(cmd: list, logpath: Path, env: dict, on_line) -> int:
    with open(logpath, "a", encoding="utf-8", buffering=1) as fh:
        fh.write(f"\n===== {NOW():%Y-%m-%d %H:%M:%S}  {' '.join(cmd)}\n")
        proc = subprocess.Popen(cmd, cwd=str(HERE), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                bufsize=1, creationflags=NOWINDOW)
        with Children.lock:
            Children.procs.add(proc)
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                fh.write(f"[{NOW():%H:%M:%S}] {line}\n")
                on_line(line)
            return proc.wait()
        finally:
            with Children.lock:
                Children.procs.discard(proc)


MONTH_LINE = re.compile(r"^Month (\d+) \(.*?\) done \| members (\S+)")


class Campaign:
    """Everything the workers share."""

    def __init__(self, plan, args, folder, session, log, env, base_cfg, server):
        self.plan, self.args, self.folder, self.session, self.log = plan, args, folder, session, log
        self.env, self.base_cfg, self.server = env, base_cfg, server
        self.runs_dir = Path(args.runs_dir)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.pending: list = []
        self.extra_next = 1
        self.running: dict = {}
        self.finished: list = []          # rows of runs finished in this session
        self.fill_deadline = None
        self.noted_fill_stop = False
        self.failures_in_a_row = 0

    # -- what to do next ------------------------------------------------------------------------------
    def build_queue(self) -> None:
        jobs = core_jobs(self.plan)
        if self.args.limit:
            jobs = jobs[:self.args.limit]
        (self.folder / "jobs").mkdir(parents=True, exist_ok=True)
        extras = sorted((self.folder / "jobs").glob(f"{self.plan['name']}-x*.json"))
        for p in extras:                                     # extras of an earlier session come first if unfinished
            job = json.loads(p.read_text(encoding="utf-8"))
            self.extra_next = max(self.extra_next, job["index"] + 1)
            jobs.append(job)
        todo = []
        for job in jobs:
            state = inspect_run(self.runs_dir / job["id"], self.plan["months"])
            if state["state"] in ("new", "partial"):
                todo.append((0 if state["state"] == "partial" else 1, len(todo), job))
        todo.sort(key=lambda t: (t[0], t[1]))                # interrupted runs first, then the plan's order
        self.pending = [t[2] for t in todo]
        self.log(f"queue: {len(self.pending)} runs to do ({sum(1 for t in todo if t[0] == 0)} to resume), "
                 f"{len(jobs) - len(self.pending)} already finished")

    def estimate_minutes(self) -> float:
        walls = [r["wall_min"] for r in self.finished if r.get("wall_min")]
        return (sum(walls) / len(walls)) if walls else 15.0

    def next_job(self):
        with self.lock:
            if self.stop.is_set():
                return None
            if self.pending:
                return self.pending.pop(0)
            if not self.plan["fill"] or self.args.no_fill or self.args.limit:
                return None
            if self.failures_in_a_row >= 4:
                if not self.noted_fill_stop:
                    self.noted_fill_stop = True
                    self.log("no new replicate runs: the last four runs did not finish. Look at the logs, then start "
                             "this again.")
                return None
            if self.fill_deadline is not None:
                need = dt.timedelta(minutes=self.estimate_minutes() * 1.25)
                if NOW() + need > self.fill_deadline:
                    if not self.noted_fill_stop:
                        self.noted_fill_stop = True
                        self.log(f"no new replicate run: one takes ~{self.estimate_minutes():.0f} min and "
                                 f"{self.fill_deadline:%H:%M} is too close")
                    return None
            job = extra_job(self.plan, self.extra_next)
            self.extra_next += 1
            return job

    def wait_for_ollama(self, worker: int) -> None:
        """A run started while Ollama is down would finish with every seat abstaining. Wait for the watchdog."""
        for i in range(120):
            if self.server.alive() or self.stop.is_set():
                return
            if i == 0:
                self.log(f"[w{worker}] Ollama is not answering; waiting for the watchdog to bring it back")
            time.sleep(5)

    # -- one job, start to finish ----------------------------------------------------------------------
    def run_job(self, job: dict, worker: int) -> dict:
        path = self.runs_dir / job["id"]
        job_file = self.folder / "jobs" / f"{job['id']}.json"
        if job_file.exists():                               # an earlier session already worked on it: keep its totals
            prior = json.loads(job_file.read_text(encoding="utf-8"))
            job = {**job, **{k: prior[k] for k in ("started_at", "wall_min", "tries", "sessions") if k in prior}}
        job.setdefault("started_at", f"{NOW():%Y-%m-%d %H:%M:%S}")
        job.setdefault("sessions", [])
        job_file.write_text(json.dumps(job, indent=1), encoding="utf-8")
        config_path = write_job_config(self.plan, job, self.base_cfg, self.folder)
        started, tries = time.time(), 0
        status = inspect_run(path, self.plan["months"])
        run_log = self.folder / "runs" / f"{job['id']}.log"
        run_log.parent.mkdir(parents=True, exist_ok=True)
        while status["state"] in ("new", "partial") and tries < self.args.attempts and not self.stop.is_set():
            tries += 1
            self.wait_for_ollama(worker)
            if status["state"] == "new":
                cmd = [sys.executable, "-u", "-m", "karamaniya", "run", str(config_path), "--months",
                       str(self.plan["months"]), "--seed", str(job["seed"]), "--name", job["id"], "--runs-dir",
                       str(self.runs_dir), "--no-check"]
                self.log(f"[w{worker}] starting {job['id']} (try {tries}/{self.args.attempts})")
            else:
                cmd = [sys.executable, "-u", "-m", "karamaniya", "resume", str(path), "--no-check"]
                self.log(f"[w{worker}] resuming {job['id']} after {status['months_done']} months "
                         f"(try {tries}/{self.args.attempts})")
            with self.lock:
                self.running[job["id"]] = {"month": status["months_done"], "members": "?", "since": time.time()}
            month_times, mark = [], [time.time()]

            def on_line(line: str) -> None:
                hit = MONTH_LINE.match(line)
                if hit:
                    now = time.time()
                    month_times.append(now - mark[0])
                    mark[0] = now
                    with self.lock:
                        self.running[job["id"]].update(month=int(hit.group(1)), members=hit.group(2))
                    if int(hit.group(1)) % 6 == 0 or len(hit.group(2)) <= 1:
                        self.log(f"[w{worker}] {job['id']}: month {hit.group(1)}/{self.plan['months']} done, "
                                 f"members {hit.group(2)}, {sum(month_times[-5:]) / len(month_times[-5:]):.0f} s/month",
                                 console=False)
                elif line.startswith(("Stopped:", "Outcome:", "Traceback")) or "Error" in line[:40]:
                    self.log(f"[w{worker}] {job['id']}: {line[:200]}")
            rc = stream(cmd, run_log, self.env, on_line)
            status = inspect_run(path, self.plan["months"])
            self.log(f"[w{worker}] {job['id']}: process exited with code {rc}; run is {status['state']} "
                     f"at {status['months_done']} months")
            if status["state"] == "partial" and tries < self.args.attempts and not self.stop.is_set():
                time.sleep(20)
        with self.lock:
            self.running.pop(job["id"], None)
        job["wall_min"] = round(job.get("wall_min", 0) + (time.time() - started) / 60, 1)
        job["tries"] = job.get("tries", 0) + tries
        job["ended_at"] = f"{NOW():%Y-%m-%d %H:%M:%S}"
        job["sessions"] = sorted(set(job["sessions"] + [self.session]))
        job_file.write_text(json.dumps(job, indent=1), encoding="utf-8")
        row = run_row(job, path, self.plan, self.folder)
        with self.lock:
            self.finished.append(row)
            self.failures_in_a_row = 0 if row["state"] == "done" else self.failures_in_a_row + 1
        self.log(f"[w{worker}] {job['id']}: {row['state']}, {row['months_done']}/{self.plan['months']} months, "
                 f"outcome {row.get('outcome') or '-'}, members left {row.get('members_left') or '-'}, "
                 f"{row['wall_min']} min")
        rebuild_table(self.plan, self.folder, self.runs_dir)
        return row

    def worker(self, n: int) -> None:
        while True:
            try:
                job = self.next_job()
            except Exception:
                self.log(f"[w{n}] could not pick the next run:\n{traceback.format_exc()}")
                return
            if job is None:
                return
            try:
                self.run_job(job, n)
            except Exception:
                self.log(f"[w{n}] {job['id']}: STOPPED by an error:\n{traceback.format_exc()}")
                with self.lock:
                    self.running.pop(job["id"], None)

    # -- status ---------------------------------------------------------------------------------------
    def status_text(self, started: dt.datetime, watchdog) -> str:
        with self.lock:
            running = dict(self.running)
            done = list(self.finished)
            left = len(self.pending)
        g = watchdog.last_gpu if watchdog else {}
        lines = [f"campaign {self.plan['name']}  started {started:%Y-%m-%d %H:%M}  now {NOW():%Y-%m-%d %H:%M:%S}  "
                 f"up {str(NOW() - started).split('.')[0]}",
                 f"runs finished this session: {len(done)}   waiting in the plan: {left}   Ollama restarts: {self.server.restarts}",
                 f"GPU: {g.get('temp_c', '?')} C, {g.get('power_w', '?')} W, {g.get('vram_used_mib', '?')} MiB, "
                 f"{g.get('util_pct', '?')} % busy", "running now:"]
        for job_id, info in running.items():
            lines.append(f"  {job_id}: month {info['month']}, members {info['members']}, "
                         f"{(time.time() - info['since']) / 60:.0f} min on this try")
        lines.append("finished this session:")
        for r in done[-15:]:
            lines.append(f"  {r['run']}: {r['state']}, {r['months_done']} months, outcome {r.get('outcome') or '-'}, "
                         f"left {r.get('members_left') or '-'}, {r['wall_min']} min")
        return "\n".join(lines)


# ---- what to write down about a run ------------------------------------------------------------------------
TABLE_COLUMNS = ["run", "kind", "cell", "rotation", "world_seed", "scenario", "severity", "framing", "seats_A_to_E",
                 "months_planned", "months_done", "state", "outcome", "collapsed", "members_left", "members_final",
                 "resignations", "first_resign_month", "first_resigner", "coups_attempted", "coups_succeeded",
                 "substantive_motions_heard", "substantive_motions_passed", "tabling_rejections",
                 "engine_findings", "vote_intent_mismatches", "calls", "call_errors", "format_retries",
                 "call_error_rate", "final_approval", "final_inflation", "wall_min", "tries", "started_at", "ended_at",
                 "sessions"]


def run_row(job: dict, path: Path, plan: dict, folder: Path) -> dict:
    row = {"run": job["id"], "kind": job["kind"], "cell": job["cell"], "rotation": job["rotation"],
           "world_seed": job["seed"], "scenario": job["scenario"], "severity": job["overrides"].get("founding_severity", ""),
           "framing": job["overrides"].get("framing", ""), "months_planned": plan["months"],
           "wall_min": job.get("wall_min", ""), "tries": job.get("tries", ""), "started_at": job.get("started_at", ""),
           "ended_at": job.get("ended_at", ""), "sessions": " ".join(job.get("sessions", []))}
    status = inspect_run(path, plan["months"])
    row.update(state=status["state"], months_done=status.get("months_done", 0), outcome=status.get("outcome", ""),
               collapsed=status.get("outcome") == "no_government")
    if status["state"] == "new":
        return row
    try:
        from karamaniya import errors
        from karamaniya.storage import RunStore
        world, _council, _meta = RunStore(path).load_checkpoint()
        cfg = json.loads((path / "config.json").read_text(encoding="utf-8"))
        mapping = cfg.get("mapping", {})
        row["seats_A_to_E"] = "/".join(mapping.get(letter, "?") for letter in sorted(mapping))
        row["members_left"] = "".join(m.id for m in world.active_members())
        row["members_final"] = " ".join(f"{m.id}:{m.status}" + (f"@{m.removed_month + 1}({m.removed_how})" if m.removed_month is not None and m.status != "active" else "")
                                        for m in world.members)
        row["coups_attempted"] = int(world.counters.get("coups_attempted", 0))
        summary = errors.summary(world)
        row["engine_findings"] = json.dumps(summary.get("by_code", {}), sort_keys=True)
        last = world.history[-1] if world.history else {}
        row["final_approval"] = round(last.get("approval", 0), 3) if last else ""
        row["final_inflation"] = round(last.get("infl_yoy", 0), 3) if last else ""
        first = None
        resigned = heard = passed = rejected = vim = succeeded = 0
        log_path = path / "log.jsonl"
        calls = fails = retries = 0
        with open(log_path, encoding="utf-8") as fh:
            for line in fh:
                if '"type": "call"' in line or '"type": "foreign_call"' in line:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    calls += 1
                    fails += bool(rec.get("error"))
                    retries += bool(rec.get("format_retry"))
                elif '"decisions"' in line and '"motions"' in line:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(rec.get("motions"), list):
                        continue
                    for mid in rec.get("resigned") or []:
                        resigned += 1
                        if first is None:
                            first = (rec.get("month", 0) + 1, mapping.get(mid, mid))
                    subst = [m for m in rec["motions"] if m.get("type") not in ("assign_office", "vacate_office")]
                    heard += len(subst)
                    passed += sum(1 for m in subst if m.get("passed"))
                    rejected += len(rec.get("rejected_motions") or [])
                    vim += len(rec.get("vote_intent_mismatches") or [])
                    succeeded += sum(1 for c in rec.get("coups") or [] if c.get("success"))
        row.update(resignations=resigned, first_resign_month=first[0] if first else "", first_resigner=first[1] if first else "",
                   coups_succeeded=succeeded, substantive_motions_heard=heard, substantive_motions_passed=passed,
                   tabling_rejections=rejected, vote_intent_mismatches=vim, calls=calls, call_errors=fails,
                   format_retries=retries, call_error_rate=round(fails / calls, 3) if calls else "")
    except Exception as exc:
        row["engine_findings"] = f"(could not read the run: {type(exc).__name__}: {exc})"
    return row


_table_lock = threading.Lock()


def rebuild_table(plan: dict, folder: Path, runs_dir: Path) -> list:
    """runs.csv: one row per run of this campaign, rebuilt from what is on disk (so it is right after a restart)."""
    rows = []
    with _table_lock:
        for p in sorted((folder / "jobs").glob("*.json")):
            job = json.loads(p.read_text(encoding="utf-8"))
            if (runs_dir / job["id"]).exists():
                rows.append(run_row(job, runs_dir / job["id"], plan, folder))
        with open(folder / "runs.csv", "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=TABLE_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    return rows


def summary_text(rows: list, plan: dict, server: Ollama, started: dt.datetime) -> str:
    def avg(values):
        values = [v for v in values if isinstance(v, (int, float))]
        return f"{sum(values) / len(values):.1f}" if values else "-"
    lines = [f"Campaign {plan['name']}: {len(rows)} runs on disk, {sum(r['state'] == 'done' for r in rows)} finished, "
             f"{sum(bool(r.get('collapsed')) for r in rows)} ended by the whole council leaving office "
             f"(no_government). Session {started:%Y-%m-%d %H:%M} to {NOW():%H:%M}; Ollama restarts {server.restarts}.", ""]
    lines.append(f"{'cell':<14}{'runs':<6}{'done':<6}{'collapsed':<11}{'mean months':<13}{'mean left':<11}{'mean resignations':<19}")
    for cell in sorted({r["cell"] for r in rows}):
        sel = [r for r in rows if r["cell"] == cell]
        left = [len(r.get("members_left") or "") for r in sel if r.get("members_left") is not None]
        lines.append(f"{cell:<14}{len(sel):<6}{sum(r['state'] == 'done' for r in sel):<6}"
                     f"{sum(bool(r.get('collapsed')) for r in sel):<11}{avg([r['months_done'] for r in sel]):<13}"
                     f"{avg(left):<11}{avg([r.get('resignations') for r in sel]):<19}")
    lines.append("")
    first = {}
    for r in rows:
        if r.get("first_resigner"):
            first[r["first_resigner"]] = first.get(r["first_resigner"], 0) + 1
    lines.append("model that resigned first (runs): " + (", ".join(f"{k} x{v}" for k, v in sorted(first.items(), key=lambda kv: -kv[1])) or "none"))
    lines.append(f"calls {sum(r.get('calls') or 0 for r in rows)}, call errors {sum(r.get('call_errors') or 0 for r in rows)}, "
                 f"format retries {sum(r.get('format_retries') or 0 for r in rows)}")
    lines.append("")
    lines.append(f"{'run':<44}{'state':<9}{'months':<8}{'left':<7}{'outcome':<14}{'min':<6}")
    for r in rows:
        lines.append(f"{r['run']:<44}{r['state']:<9}{r['months_done']:<8}{(r.get('members_left') or '-'):<7}{(r.get('outcome') or '-'):<14}{r.get('wall_min', ''):<6}")
    return "\n".join(lines)


# ---- main ------------------------------------------------------------------------------------------------
def kill_orphans(name: str, log: Log) -> None:
    """Runs left behind by a window that was closed mid-campaign would fight a new start for the same folders."""
    try:
        out = powershell("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ForEach-Object "
                         "{ \"$($_.ProcessId)`t$($_.CommandLine)\" }", timeout=40)
    except Exception:
        return
    for line in out.splitlines():
        pid, _, cmd = line.partition("\t")
        if pid.strip().isdigit() and int(pid) != os.getpid() and re.search(rf"-m karamaniya\s+(run|resume)\b.*{re.escape(name)}-", cmd):
            log(f"stopping an orphaned run process from an earlier start (pid {pid})")
            subprocess.run(["taskkill", "/PID", pid.strip(), "/T", "/F"], capture_output=True, creationflags=NOWINDOW)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", default=str(HERE / "bench" / "campaign_plan.toml"))
    ap.add_argument("--runs-dir", default=str(HERE / "runs-bench"))
    ap.add_argument("--prefix", default="", help="override the campaign name (folders and runs start with it)")
    ap.add_argument("--months", type=int, default=0, help="override months per run")
    ap.add_argument("--workers", type=int, default=0, help="override runs at the same time")
    ap.add_argument("--limit", type=int, default=0, help="only the first N runs of the core grid, no replicates (testing)")
    ap.add_argument("--no-fill", action="store_true", help="the core grid only, no replicate runs")
    ap.add_argument("--until", default="", help="HH:MM, overrides fill_until")
    ap.add_argument("--port", type=int, default=11435, help="private port for this script's own Ollama")
    ap.add_argument("--attempts", type=int, default=4, help="tries per run: the first, then resumes")
    ap.add_argument("--dry-run", action="store_true", help="check the PC and show the plan, then stop")
    ap.add_argument("--allow-battery", action="store_true")
    ap.add_argument("--allow-cpu", action="store_true", help="carry on even if a model is not on the GPU")
    args = ap.parse_args(argv)
    plan = load_plan(Path(args.plan))
    if args.prefix:
        plan["name"] = args.prefix
    if args.months:
        plan["months"] = args.months
    if args.workers:
        plan["workers"] = args.workers
    if args.until:
        plan["fill_until"] = args.until
    args.runs_dir = str(Path(args.runs_dir).resolve())

    folder = HERE / "overnight_logs" / plan["name"]
    session = NOW().strftime("%Y%m%d-%H%M%S")
    sfolder = folder / "sessions" / session
    sfolder.mkdir(parents=True, exist_ok=True)
    log = Log(sfolder / "driver.log")
    disable_quick_edit()
    started = NOW()
    log(f"campaign {plan['name']}: {plan['months']} months per run, {plan['workers']} at a time, "
        f"runs go to {args.runs_dir}")
    log(f"logs: {folder}  (this session: {sfolder.name})")

    # ---- the lock: two copies of this must never run at once ---------------------------------------------
    lock_path = folder / "campaign.lock"
    if lock_path.exists():
        try:
            other = json.loads(lock_path.read_text(encoding="utf-8"))
            if pid_alive(other["pid"]) and other["pid"] != os.getpid():
                log(f"PROBLEM: this campaign is already running (pid {other['pid']}, since {other['since']}). "
                    "Close that window first, or wait for it to finish.")
                return 1
        except Exception:
            pass
    lock_path.write_text(json.dumps({"pid": os.getpid(), "since": f"{started:%Y-%m-%d %H:%M:%S}"}), encoding="utf-8")

    # ---- 1. the PC ---------------------------------------------------------------------------------------
    problems = []
    if sys.version_info < (3, 11):
        problems.append(f"Python {sys.version.split()[0]} is too old (3.11+ needed)")
    base_cfg, models = None, []
    try:
        from karamaniya import versions
        from karamaniya.config import load_config
        base_cfg = load_config(plan["base_config"])
        models = [s["model"] for s in base_cfg["seats"]]
        log(f"engine: WORLD_ENGINE {versions.WORLD_ENGINE}, code in {HERE}")
        log("seats (rotation 0): " + ", ".join(f"{letter}={s['model']}" for letter, s in zip("ABCDE", base_cfg["seats"])))
        for job in core_jobs(plan) + [extra_job(plan, n) for n in (1, 2, 3)]:
            write_job_config(plan, job, base_cfg, folder)          # the plan must produce valid council files
    except Exception as exc:
        problems.append(f"the plan or council file is not valid: {type(exc).__name__}: {exc}")
    code = {"git": "", "dirty": False}
    try:
        code["git"] = quiet(["git", "-C", str(HERE), "rev-parse", "HEAD"], timeout=10).strip()
        code["dirty"] = bool(quiet(["git", "-C", str(HERE), "status", "--porcelain", "--untracked-files=no"], timeout=20).strip())
        log(f"code version: git {code['git'][:10]}{' (with uncommitted changes)' if code['dirty'] else ''}")
    except Exception:
        log("code version: git not available", console=False)
    if on_battery():
        log("the PC is on battery: a laptop GPU is slowed hard on battery and the battery will not last the night")
        if not args.allow_battery:
            problems.append("plug the charger in (or pass --allow-battery)")
    if lid_closes_to_sleep():
        log("WARNING: closing the lid puts this PC to sleep, and that stops everything. Keep the lid OPEN "
            "(the screen can be off), or set 'closing the lid: do nothing' in Power options.")
    gpu = None
    for attempt in range(36):                                      # after a boot or a BIOS update the driver may still be loading
        try:
            gpu = gpu_sample()
            break
        except Exception as exc:
            if attempt == 0:
                log(f"waiting for the GPU to answer ({exc})")
            time.sleep(5)
    if gpu is None:
        problems.append("nvidia-smi does not answer after 3 minutes. After a BIOS update check that the graphics mode "
                        "is hybrid/discrete and that Device Manager lists the NVIDIA GPU without a warning sign")
    else:
        log(f"GPU: {gpu['name']}, {gpu['vram_total_mib'] / 1024:.1f} GB, {gpu['vram_used_mib']:.0f} MiB used now, "
            f"{gpu['temp_c']} C, driver {gpu['driver']}")
        if gpu["vram_used_mib"] and gpu["vram_used_mib"] > 2500:
            log(f"WARNING: {gpu['vram_used_mib']:.0f} MiB of VRAM is already in use by other programs; the five "
                "models need about 7 GB, so some would run partly on the CPU. Close what is using the GPU.")
    free_gb = shutil.disk_usage(Path(args.runs_dir).anchor or ".").free / 1e9
    log(f"disk space free on the runs drive: {free_gb:.0f} GB")
    if free_gb < 5:
        problems.append("less than 5 GB free on the runs drive")
    exe = find_ollama()
    if not exe:
        problems.append("ollama.exe was not found (not on PATH and not in %LOCALAPPDATA%\\Programs\\Ollama)")
    fill_until = None
    if plan["fill"] and not args.no_fill and not args.limit:
        hh, mm = (int(x) for x in plan["fill_until"].split(":"))
        fill_until = started.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if fill_until <= started:
            fill_until += dt.timedelta(days=1)
        fill_until = min(fill_until, started + dt.timedelta(hours=plan["max_hours"]))
        log(f"after the core grid, replicate runs until {fill_until:%Y-%m-%d %H:%M} (hard stop "
            f"{fill_until + dt.timedelta(minutes=plan['grace_minutes']):%H:%M})")
    core = core_jobs(plan)
    worlds = (f"every run its own world seed ({core[0]['seed']}..{core[-1]['seed']})" if plan["distinct_seeds"]
              else f"world seed {plan['seed']}")
    log(f"core: {len(core)} runs = {len(plan['cells'])} cells x {len(plan['rotations'])} rotations x "
        f"{plan['replicates']} replicates, {worlds}, founding scenario "
        f"{'in turn from all six' if plan['scenario_mode'] == 'cycle' else plan['founding_scenario']}")
    if problems:
        for p in problems:
            log(f"PROBLEM: {p}")
        log("nothing was started.")
        lock_path.unlink(missing_ok=True)
        return 1
    if args.dry_run:
        states = [inspect_run(Path(args.runs_dir) / job["id"], plan["months"])["state"] for job in core]
        for job, state in list(zip(core, states))[:8]:
            log(f"  {job['id']:<44} {state}")
        log(f"  ... {len(core)} core runs in all: {states.count('new')} new, {states.count('partial')} partial, "
            f"{states.count('done')} done; {len({job['seed'] for job in core})} different world seeds")
        log("dry run: the PC checks passed. Ollama was not started and no run was made.")
        lock_path.unlink(missing_ok=True)
        return 0

    awake = KeepAwake()
    awake.start()
    server = Ollama(exe, args.port, sfolder / "ollama_server.log", log)
    watchdog, campaign, workers = None, None, []
    code_out = 0
    try:
        # ---- 2. Ollama, the models, the GPU ---------------------------------------------------------------
        kill_orphans(plan["name"], log)
        server.start()
        have = {m["name"] for m in server.tags()}
        for model in models:
            if model not in have:
                log(f"pulling {model} (not on this PC yet)")
                subprocess.run([exe, "pull", model], env=server.env(), creationflags=NOWINDOW, check=True)
        env = {**os.environ, "OLLAMA_API_BASE": server.base, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
        log("one tiny call to every seat (this loads all five models onto the GPU)")
        out = subprocess.run([sys.executable, "-m", "karamaniya", "check", plan["base_config"]], cwd=str(HERE), env=env,
                             capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWINDOW)
        for line in out.stdout.strip().splitlines():
            log("  " + line[:150])
        if out.returncode != 0:
            log("PROBLEM: a seat did not answer; nothing was started.")
            return 1
        partly = []
        loaded = server.loaded()
        for m in loaded:
            share = (m.get("size_vram", 0) / m["size"]) if m.get("size") else 0
            log(f"  {m['name']:<32} {m['size'] / 1e9:4.2f} GB, {share:4.0%} on the GPU")
            if share < 0.98:
                partly.append(m["name"])
        if len(loaded) < len(set(models)):
            partly.append("(not all five models are loaded at once)")
        g = gpu_sample()
        log(f"GPU memory in use with all models loaded: {g['vram_used_mib']:.0f} of {g['vram_total_mib']:.0f} MiB")
        if partly and not args.allow_cpu:
            log(f"PROBLEM: {', '.join(partly)}. That runs many times slower. Close the programs using the GPU and run "
                "this again (or pass --allow-cpu).")
            return 1
        (folder / "campaign.json").write_text(json.dumps({
            "started": f"{started:%Y-%m-%d %H:%M:%S}", "session": session, "plan": plan, "argv": sys.argv,
            "code": code, "engine_world_engine": versions.WORLD_ENGINE, "ollama_version": http_json(server.base + "/api/version"),
            "ollama_env": OLLAMA_ENV, "models": [m for m in server.tags() if m["name"] in models],
            "hardware": hardware_info(), "core_jobs": [j["id"] for j in core]}, indent=1, default=str), encoding="utf-8")
        try:
            (sfolder / "nvidia-smi-start.txt").write_text(quiet(["nvidia-smi", "-q"], timeout=60), encoding="utf-8")
            shutil.copy(args.plan, sfolder / "campaign_plan.toml")            # the exact inputs of this session
            shutil.copy(plan["base_config"], sfolder / "council.tiny-local.toml")
        except Exception:
            pass
        watchdog = Watchdog(server, sfolder, log)
        watchdog.start()

        # ---- 3. the campaign ------------------------------------------------------------------------------
        campaign = Campaign(plan, args, folder, session, log, env, base_cfg, server)
        campaign.fill_deadline = fill_until
        campaign.build_queue()
        hard_stop = (fill_until + dt.timedelta(minutes=plan["grace_minutes"])) if fill_until else started + dt.timedelta(hours=plan["max_hours"])
        hard_stop = min(hard_stop, started + dt.timedelta(hours=plan["max_hours"] + plan["grace_minutes"] / 60))
        workers = [threading.Thread(target=campaign.worker, args=(i + 1,), daemon=True) for i in range(max(1, plan["workers"]))]
        for w in workers:
            w.start()
        t_status = t_beat = 0.0
        while any(w.is_alive() for w in workers):
            time.sleep(3)
            if time.time() - t_status >= 60:
                t_status = time.time()
                (folder / "STATUS.txt").write_text(campaign.status_text(started, watchdog), encoding="utf-8")
            if time.time() - t_beat >= 300:
                t_beat = time.time()
                with campaign.lock:
                    running = ", ".join(f"{k.replace(plan['name'] + '-', '')} m{v['month']}({v['members']})" for k, v in campaign.running.items())
                    n_done = len(campaign.finished)
                try:
                    g = watchdog.last_gpu or gpu_sample()
                except Exception:
                    g = {}
                log(f"heartbeat: {n_done} finished this session, {len(campaign.pending)} waiting | running: {running or '-'} | "
                    f"GPU {g.get('temp_c', '?')} C {g.get('vram_used_mib', '?')} MiB | Ollama restarts {server.restarts}")
            if NOW() > hard_stop and not campaign.stop.is_set():
                log(f"hard stop time {hard_stop:%H:%M} reached: stopping the runs that are still going. They are "
                    "resumable: start this again to continue them.")
                campaign.stop.set()
                Children.kill_all()
        (folder / "STATUS.txt").write_text(campaign.status_text(started, watchdog), encoding="utf-8")
        rows = rebuild_table(plan, folder, Path(args.runs_dir))
        text = summary_text(rows, plan, server, started)
        (folder / "summary.txt").write_text(text, encoding="utf-8")
        log("finished. Summary:\n" + text)
        code_out = 0 if rows and all(r["state"] == "done" for r in rows) else 2
    except KeyboardInterrupt:
        log("stopped from the keyboard. Runs are resumable: start this again to continue.")
        if campaign is not None:
            campaign.stop.set()
        Children.kill_all()
        code_out = 130
    except Exception:
        log(f"STOPPED by an error:\n{traceback.format_exc()}")
        if campaign is not None:
            campaign.stop.set()
        Children.kill_all()
        code_out = 1
    finally:
        if watchdog is not None:
            watchdog.done.set()
        try:
            (sfolder / "nvidia-smi-end.txt").write_text(quiet(["nvidia-smi", "-q"], timeout=60), encoding="utf-8")
        except Exception:
            pass
        server.stop()
        awake.done.set()
        lock_path.unlink(missing_ok=True)
        log("Ollama stopped, the PC may sleep again.")
    return code_out


if __name__ == "__main__":
    sys.exit(main())
