"""Build the submission zip from a frozen git commit, then smoke-test it in a fresh environment.

    python tools/package.py build [--ref REF] [--out ZIP] [--force]
    python tools/package.py smoke [--zip ZIP] [--ref REF] [--out ZIP] [--force] [--python EXE] [--keep]
    python tools/package.py all   [--ref REF] [--out ZIP] [--force] [--python EXE] [--keep]

`build` exports a whitelist of the frozen tree (never the working tree): the engine (`karamaniya/`), the study
folder (`studies/karamaniya_trust/`), the study tools, the study tests, the pre-registration, the docs and the
submission README. It reads the files with `git archive <ref>`, so the zip is pinned to that commit even if the
checkout has uncommitted changes. The zip root holds `README.md` (from `docs/SUBMISSION_README.md`),
`README-engine.md` (the repository README), `PACKAGE_MANIFEST.json` (commit, versions, every file's SHA-256), and
the selected tree.

The build refuses a `.env` file, a key-like secret, a private folder, a run folder, a trajectory store (`.duckdb`,
`.parquet`), a log or a certificate. A `forbidden` list in the manifest records what was left out; a secret stops
the build.

`smoke` extracts the zip into a temp folder, creates a fresh virtual environment with no packages (`--without-pip`),
reads the first `python -m karamaniya simulate ...` command from the zip's `README.md`, and runs it there. It passes
when the command exits 0 and a run checkpoint exists. The default command calls no model.

The zip is not committed: `dist/` is in .gitignore and `build` writes there.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = ROOT / "dist"
PACKAGE_NAME = "karamaniya-trust-submission"

# Files copied into the zip at a path other than their repository path.
RENAMES = {
    "docs/SUBMISSION_README.md": "README.md",   # the package's one README
    "README.md": "README-engine.md",            # the repository's own README, kept as a reference
}
INCLUDE_EXACT = {
    "CHANGELOG.md", "CITATION.cff", "ENGINE.md", "LICENSE", "README.md", "requirements.txt",
    "council.scripted.toml",
    "paper/socioverse/PREREGISTRATION.md",
    "docs/EXIT_AUDIT_CODEBOOK.md", "docs/PACKAGING.md", "docs/SCOPE_TEST.md", "docs/SUBMISSION_README.md",
    "docs/WAVE3_PLAN.md",
    "tools/exit_audit.py", "tools/package.py", "tools/prompt_freeze.py", "tools/replay_run.py",
    "tools/scope_test.py", "tools/study_analysis.py", "tools/study_grid.py", "tools/study_example.toml",
    "tests/__init__.py", "tests/test_engine24_package.py", "tests/test_engine24_scope_test.py",
    "tests/test_engine24_study_analysis.py", "tests/test_engine24_study_grid.py",
    "tests/test_study_karamaniya_trust.py",
}
INCLUDE_PREFIXES = ("karamaniya/", "studies/karamaniya_trust/")
# The engine's GUI artwork is 2.4 MB and the study never uses it; the zip keeps code and text only.
ENGINE_EXCLUDE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".pyc")
STUDY_EXCLUDE_PARTS = ("wrapped_run", "legacy_run", "__pycache__")
STUDY_EXCLUDE_NAMES = ("progress.jsonl", "panel_live.jsonl")
STUDY_EXCLUDE_SUFFIXES = (".duckdb", ".parquet", ".db", ".sqlite", ".log", ".pyc")
FORBIDDEN_SUFFIXES = (".duckdb", ".parquet", ".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12", ".pfx",
                      ".log", ".pyc")
FORBIDDEN_PARTS = ("private", "runs", ".git", "wrapped_run", "legacy_run", "__pycache__")
VERSION_KEYS = ("WORLD_ENGINE", "AGENT_PROMPT", "ERROR_TAXONOMY", "PSYCHOLOGY", "AGENT_ARCHITECTURE")
REQUIRED_FILES = ("README.md", "PACKAGE_MANIFEST.json", "karamaniya/runner.py", "council.scripted.toml",
                  "studies/karamaniya_trust/run.py", "studies/karamaniya_trust/study.yaml")
# A key-like assignment or a provider token. Placeholders (YOUR_, xxx, <...>, ${...}) are allowed.
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b(?:API_KEY|APIKEY|SECRET|TOKEN|PASSWORD)\s*=\s*['\"]?([A-Za-z0-9_\-/+]{20,})", re.I),
)
PLACEHOLDER_PARTS = ("your", "xxx", "example", "placeholder", "redacted", "changeme", "dummy", "fake", "<", "${")


class PackageError(Exception):
    """The package cannot be built or does not pass its own checks."""


# ---- selection ---------------------------------------------------------------------------------------------------

def _study_excluded(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if any(part in STUDY_EXCLUDE_PARTS for part in parts):
        return True
    name = PurePosixPath(path).name
    if name in STUDY_EXCLUDE_NAMES or name.startswith(".env"):
        return True
    return PurePosixPath(path).suffix.lower() in STUDY_EXCLUDE_SUFFIXES


def included(path: str) -> bool:
    """Whether a repository path belongs in the package."""
    if path in INCLUDE_EXACT:
        return True
    if path.startswith("karamaniya/"):
        return PurePosixPath(path).suffix.lower() not in ENGINE_EXCLUDE_SUFFIXES
    if path.startswith("studies/karamaniya_trust/"):
        return not _study_excluded(path)
    return False


def forbidden_path(path: str) -> str:
    """Why a zip path must never appear in the package, or "" when it may."""
    parts = PurePosixPath(path).parts
    name = parts[-1] if parts else ""
    if name == ".env" or name.startswith(".env."):
        return "an .env file"
    if any(part in FORBIDDEN_PARTS for part in parts):
        return "a private, run, git or trajectory folder"
    if PurePosixPath(path).suffix.lower() in FORBIDDEN_SUFFIXES:
        return "a binary store, log or certificate"
    return ""


def secret_findings(data: bytes) -> list:
    """Labels of key-like secrets in a text file. The value is never returned."""
    if b"\0" in data[:4096]:
        return []
    text = data.decode("utf-8", "ignore")
    found = []
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            value = (match.group(1) if match.groups() else match.group(0)).lower()
            if any(marker in value for marker in PLACEHOLDER_PARTS):
                continue
            found.append("key-like assignment")
    return sorted(set(found))


def zip_name(repo_path: str) -> str:
    return RENAMES.get(repo_path, repo_path)


# ---- git and the build -------------------------------------------------------------------------------------------

def _git(root: Path, *args, binary: bool = False):
    proc = subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise PackageError(f"git {' '.join(args)} failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout if binary else proc.stdout.decode("utf-8", "replace")


def resolve_commit(ref: str = "HEAD", root: Path = ROOT) -> str:
    return _git(root, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def _versions(source: str) -> dict:
    out = {}
    for key in VERSION_KEYS:
        match = re.search(rf"^{key}\s*=\s*(\d+)", source, re.M)
        if match:
            out[key.lower()] = int(match.group(1))
    return out


def _commit_date(root: Path, commit: str):
    stamp = int(_git(root, "log", "-1", "--format=%ct", commit).strip())
    return time.gmtime(max(stamp, 315532800))[:6]     # ZIP cannot store a date before 1980


def build_package(ref: str = "HEAD", *, out=None, force: bool = False, root: Path = ROOT) -> dict:
    """Write the submission zip for `ref` and return its manifest. Never reads the working tree's content."""
    commit = resolve_commit(ref, root)
    out = Path(out) if out else DEFAULT_OUT_DIR / f"{PACKAGE_NAME}-{commit[:8]}.zip"
    if out.exists() and not force:
        raise PackageError(f"{out} exists; pass --force to replace it")
    archive = _git(root, "archive", "--format=tar", commit, binary=True)
    date_time = _commit_date(root, commit)
    selected, skipped = [], []
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            if not included(member.name):
                continue
            data = tar.extractfile(member).read()
            target = zip_name(member.name)
            why = forbidden_path(target)
            if why:
                raise PackageError(f"{member.name} would land in the zip as {target}: {why}")
            secrets = secret_findings(data)
            if secrets:
                raise PackageError(f"{member.name} looks like it carries a secret ({', '.join(secrets)}); "
                                   "the build stopped and the value was not printed")
            selected.append({"source": member.name, "path": target, "data": data,
                             "sha256": hashlib.sha256(data).hexdigest()})
    for repo_path in list(INCLUDE_EXACT):
        if not any(item["source"] == repo_path for item in selected):
            skipped.append(repo_path)
    if not selected:
        raise PackageError(f"the archive of {commit} has no file this package needs")
    versions_source = next((item["data"].decode("utf-8", "replace") for item in selected
                            if item["source"] == "karamaniya/versions.py"), "")
    for item in selected:
        item["bytes"] = len(item["data"])
    branch = _git(root, "rev-parse", "--abbrev-ref", commit).strip()
    commit_epoch = int(_git(root, "log", "-1", "--format=%ct", commit).strip())
    manifest = {
        "package": PACKAGE_NAME,
        "ref": ref,
        "commit": commit,
        "commit_date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(commit_epoch)),
        "branch": "(detached)" if branch == "HEAD" else branch,
        "versions": _versions(versions_source),
        "files": [{"path": item["path"], "source": item["source"], "sha256": item["sha256"],
                   "bytes": item["bytes"]}
                  for item in sorted(selected, key=lambda item: item["path"])],
        "missing_optional": sorted(skipped),
        "excluded_by_design": [
            "karamaniya/council-chamber.png (2.4 MB GUI artwork; the study does not use it)",
            "runs/, private/, .env files, .duckdb/.parquet stores, logs and certificates (never selected)",
            "the repository's full test suite, benchmarks, figures and council files other than council.scripted.toml",
        ],
        "built_by": "tools/package.py",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for item in sorted(selected, key=lambda item: item["path"]):
            info = zipfile.ZipInfo(item["path"], date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, item["data"])
        info = zipfile.ZipInfo("PACKAGE_MANIFEST.json", date_time=date_time)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        z.writestr(info, json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    os.replace(tmp, out)
    verification = verify_zip(out)
    if verification["forbidden"] or verification["missing"] or verification["hash_mismatches"]:
        raise PackageError(f"the zip failed its own checks: {verification}")
    manifest["zip"] = str(out)
    manifest["zip_sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
    manifest["zip_bytes"] = out.stat().st_size
    return manifest


def verify_zip(path) -> dict:
    """A built zip's contents: the file list, forbidden paths, required files and hash mismatches."""
    path = Path(path)
    with zipfile.ZipFile(path) as z:
        names = [name for name in z.namelist() if not name.endswith("/")]
        manifest = json.loads(z.read("PACKAGE_MANIFEST.json").decode("utf-8")) if "PACKAGE_MANIFEST.json" in names \
            else {"files": []}
        forbidden = [name for name in names if forbidden_path(name)]
        missing = [name for name in REQUIRED_FILES if name not in names]
        mismatches = []
        for entry in manifest.get("files") or []:
            name = entry.get("path")
            if name not in names:
                mismatches.append(f"{name}: listed but absent")
                continue
            digest = hashlib.sha256(z.read(name)).hexdigest()
            if digest != entry.get("sha256"):
                mismatches.append(f"{name}: sha256 differs")
    return {"files": len(names), "names": names, "forbidden": forbidden, "missing": missing,
            "hash_mismatches": mismatches, "manifest": manifest}


# ---- the clean-machine smoke test --------------------------------------------------------------------------------

def readme_command(text: str) -> list:
    """The first `python -m karamaniya simulate ...` line in the package README."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("python -m karamaniya simulate"):
            return shlex.split(line)
    raise PackageError("the package README has no 'python -m karamaniya simulate ...' one command")


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def smoke(zip_path, *, python_exe=None, keep: bool = False, timeout: int = 600) -> dict:
    """Extract the zip, make a fresh venv with no packages, and run the README's one command in it."""
    zip_path = Path(zip_path)
    verification = verify_zip(zip_path)
    if verification["forbidden"]:
        raise PackageError(f"the zip holds forbidden paths: {verification['forbidden']}")
    if verification["missing"]:
        raise PackageError(f"the zip is missing {verification['missing']}")
    if verification["hash_mismatches"]:
        raise PackageError(f"the zip's hashes do not match its manifest: {verification['hash_mismatches']}")
    temp = Path(tempfile.mkdtemp(prefix="karamaniya-package-smoke-"))
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(temp)
    readme = (temp / "README.md").read_text(encoding="utf-8")
    command = readme_command(readme)
    venv = temp / ".venv-smoke"
    subprocess.run([python_exe or sys.executable, "-m", "venv", "--without-pip", str(venv)],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    venv_python = _venv_python(venv)
    if not venv_python.is_file():
        raise PackageError(f"the fresh venv has no interpreter at {venv_python}")
    run_command = [str(venv_python), *command[1:]]
    env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "PYTHONHOME")}
    env["PYTHONNOUSERSITE"] = "1"
    began = time.monotonic()
    try:
        proc = subprocess.run(run_command, cwd=temp, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise PackageError(f"the README command did not finish in {timeout}s: {' '.join(run_command)}") from exc
    checkpoints = sorted(str(p.relative_to(temp)) for p in (temp / "runs").glob("*/checkpoint.json"))
    result = {
        "zip": str(zip_path), "zip_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        "files": verification["files"], "command": " ".join(run_command), "returncode": proc.returncode,
        "seconds": round(time.monotonic() - began, 1), "checkpoints": checkpoints,
        "output_tail": proc.stdout[-1500:], "temp": str(temp), "kept": keep,
    }
    if not keep:
        shutil.rmtree(temp, ignore_errors=True)
    if proc.returncode != 0:
        raise PackageError(f"the README command failed with exit code {proc.returncode}:\n{proc.stdout[-3000:]}")
    if not checkpoints:
        raise PackageError(f"the README command wrote no run checkpoint under {temp / 'runs'}")
    return result


# ---- command line -----------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "smoke", "all"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--ref", default="HEAD", help="the frozen commit or tag (default HEAD)")
        cmd.add_argument("--out", help="the zip path (default dist/karamaniya-trust-submission-<sha8>.zip)")
        cmd.add_argument("--force", action="store_true", help="replace an existing zip")
        if name in ("smoke", "all"):
            cmd.add_argument("--zip", help="an existing zip; build one when omitted")
            cmd.add_argument("--python", help="the interpreter that creates the fresh venv (default this one)")
            cmd.add_argument("--keep", action="store_true", help="keep the extracted temp folder")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "build":
            manifest = build_package(args.ref, out=args.out, force=args.force)
            print(f"built {manifest['zip']} ({manifest['zip_bytes']} bytes, {len(manifest['files'])} files, "
                  f"commit {manifest['commit'][:12]}, versions {manifest['versions']})")
            return 0
        zip_path = getattr(args, "zip", None)
        if args.cmd == "all" or not zip_path:
            manifest = build_package(args.ref, out=args.out, force=args.force)
            zip_path = manifest["zip"]
            print(f"built {zip_path} ({manifest['zip_bytes']} bytes, {len(manifest['files'])} files)")
        result = smoke(zip_path, python_exe=getattr(args, "python", None), keep=getattr(args, "keep", False))
        print(f"clean-machine smoke: exit {result['returncode']}, {result['files']} files, "
              f"{result['seconds']}s, checkpoints {result['checkpoints']}")
        print(f"command: {result['command']}")
        if not result["kept"]:
            print("the temp folder was removed; pass --keep to inspect it")
        return 0
    except (PackageError, OSError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
