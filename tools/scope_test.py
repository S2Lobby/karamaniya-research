"""Run one of SocioVerse2's own reference studies with its decision step audited.

    python tools/scope_test.py [--socioverse-root PATH] [--out DIR] [--llm stub|openai]
                               [--model ID] [--base-url URL] [--steps N] [--seed S]
                               [--prompt-lang en|zh] [--quiet]

The study is `studies/opinion_diffusion`, SocioVerse2 0.2.0's reference from-scratch study (Path B). Its own
environment, population, decision model and metric collector are used unchanged; its own `LongitudinalSimulator`
runs the steps. Only two things are replaced, and the report says so:

  - the decision model's LLM endpoint: `--llm stub` (the default) is a deterministic stand-in that returns a fixed
    mix of well-formed, bare-number, unparseable, empty and failed replies, keyed by the prompt, so no model and no
    network is needed. `--llm openai` calls a real OpenAI-compatible endpoint through SocioVerse2's own client and
    needs `SV_LLM_API_KEY` (or `OPENAI_API_KEY`) in the environment; the key is never printed or written;
  - the trajectory store: DuckDB is not installed in the engine's environment, so an in-memory store with the same
    four calls is used. The panel rows are built by SocioVerse2's own `build_panel_rows`, so they have the same
    shape as the DuckDB panel.

The audit wraps `decide_batch` and `_ask` on the study's own `BoundedConfidenceDecision`. For every decision it
records the raw reply, a transport error if the call raised, the rule's opinion, the action's opinion and its
`source` (`llm` or `fallback`). `opinion_diffusion` applies the bounded-confidence rule as a guaranteed fallback
whenever a reply does not parse: `model.py` logs a warning and sets `source="fallback"`, but the trajectory panel
stores only the action payload, not `source`. The audit measures:

  - decisions, parsed replies (strict JSON vs the parser's bare-number last resort), and fallbacks;
  - fallback_unparsed: a non-empty model reply arrived and the rule quietly replaced it;
  - fallback_empty / call_error: there was no model answer to replace;
  - the share of decisions and of non-empty model answers that the fallback replaced;
  - whether the fallback value equals the study's own rule value (it should, always);
  - whether `source` survives into the panel row (it does not).

Outputs, in --out (default scope_test/): decisions.jsonl, summary.json, report.md. Nothing is written into the
vendored SocioVerse2 checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import threading
import types
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "scope_test"
STUDY_ID = "opinion_diffusion"
# The reference study's decision_args set llm_kind="openai" and prompt_lang="zh" (its shipped run used Chinese).
# The stub keeps the arguments and replaces the callable, so the prompt and the parsing path are the study's own.
STUB_MIX = (("valid_json", 60), ("bare_float", 15), ("unparsed_reply", 15), ("empty_reply", 5), ("call_error", 5))
CLASSES = ("valid_json", "bare_float", "unparsed_reply", "empty_reply", "call_error")
PANEL_FIELDS = ("agent_id", "step", "state", "action_kind", "action_payload")


class ScopeTestError(Exception):
    """The scope test cannot run here. The message says what is missing."""


class StubTransportError(RuntimeError):
    """A simulated provider failure: the audit must count it as a call error, not as an answer."""


# ---- the environment -------------------------------------------------------------------------------------------

def socioverse_root(explicit=None) -> Path:
    """The SocioVerse2 checkout to use: the flag, $SOCIOVERSE2_ROOT, the vendored checkout, or an installed package."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("SOCIOVERSE2_ROOT"):
        candidates.append(Path(os.environ["SOCIOVERSE2_ROOT"]))
    candidates += [ROOT.parent / "_vendor" / "SocioVerse2", ROOT / "_vendor" / "SocioVerse2"]
    for candidate in candidates:
        if (candidate / "socioverse" / "__init__.py").is_file() and (candidate / "studies" / STUDY_ID).is_dir():
            return candidate.resolve()
    raise ScopeTestError("no SocioVerse2 checkout found. Pass --socioverse-root, set SOCIOVERSE2_ROOT, or put the "
                         "0.2.0 source at <worktree>/../_vendor/SocioVerse2 (it needs studies/opinion_diffusion).")


def _shim_missing_duckdb() -> bool:
    """SocioVerse2 imports duckdb at package import time, but the scope test uses an in-memory store. When duckdb
    is not installed, put a stand-in module in sys.modules so the package imports; no store code calls it. Returns
    True when a stand-in was installed."""
    try:
        found = importlib.util.find_spec("duckdb") is not None
    except (ImportError, ValueError):
        found = False
    if found or "duckdb" in sys.modules:
        return False
    module = types.ModuleType("duckdb")
    module.__doc__ = "scope_test stand-in: duckdb is not installed; an in-memory store is used"
    module.__scope_test_shim__ = True
    sys.modules["duckdb"] = module
    return True


class _ImportState:
    """What the scope test added to the process, so a later test gets the interpreter it started with.

    The review run may import several test modules in one process. The socioVerse checkout is only for this tool;
    leaving `socioverse`, `studies` or the duckdb stand-in in `sys.modules` makes the wrap tests think the framework
    is installed and then fail, instead of skipping. Anything that was already imported before the scope test is
    kept (a real install), and anything the scope test brought in is removed afterwards."""

    def __init__(self):
        self.before = set(sys.modules)
        self.root = None
        self.added_path = False

    def restore(self) -> None:
        for name in list(sys.modules):
            if name in self.before:
                continue
            if (name == "duckdb" or name == "socioverse" or name.startswith("socioverse.")
                    or name == "studies" or name.startswith("studies.")):
                sys.modules.pop(name, None)
        if self.added_path and self.root is not None and str(self.root) in sys.path:
            sys.path.remove(str(self.root))


def load_reference(explicit=None, state=None):
    """Import SocioVerse2 and its opinion_diffusion study, returning (socioverse_root, module, bundles)."""
    root = socioverse_root(explicit)
    if state is not None:
        state.root = root
        state.added_path = str(root) not in sys.path
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    _shim_missing_duckdb()
    try:
        import socioverse  # noqa: F401
        import studies.opinion_diffusion.model as od
        from socioverse.schemas import EnvironmentBundle, PopulationBundle, SimulationConfig
        from socioverse.validation import validate_handoff
    except ImportError as exc:
        raise ScopeTestError(f"SocioVerse2 cannot be imported from {root}: {exc}. It needs pydantic (the engine's "
                             "environment has it); duckdb is stood in for the in-memory store.") from exc
    study = root / "studies" / STUDY_ID
    bundles = (
        validate_handoff(study / "environment" / "environment.json", EnvironmentBundle),
        validate_handoff(study / "population" / "population.json", PopulationBundle),
        validate_handoff(study / "simulation" / "simulation.json", SimulationConfig),
    )
    return root, od, bundles


# ---- the stub model --------------------------------------------------------------------------------------------

def _own_opinion(prompt: str):
    match = re.search(r"(?:current stance|当前的立场)\s*[:：]\s*([0-9]*\.?[0-9]+)", prompt)
    try:
        return float(match.group(1)) if match else None
    except (TypeError, ValueError):
        return None


class StubLLM:
    """A deterministic stand-in for the study's LLM endpoint.

    The reply class is chosen by a SHA-256 of the seed and the prompt, so the same run gives the same replies in any
    process. The mix is the documented STUB_MIX: it exercises the parser's happy path, its bare-number last resort,
    and all three ways the study reaches its rule fallback (unparseable text, an empty answer, a failed call).
    These rates are chosen to exercise the audit; they are not a measurement of any model.
    """

    def __init__(self, seed: int = 42):
        self.seed = int(seed)
        self.mix = STUB_MIX

    def _class(self, prompt: str) -> str:
        roll = hashlib.sha256(f"{self.seed}\0{prompt}".encode("utf-8")).digest()[0] % 100
        upto = 0
        for name, weight in self.mix:
            upto += weight
            if roll < upto:
                return name
        return self.mix[-1][0]

    def __call__(self, prompt: str) -> str:
        kind = self._class(prompt)
        own = _own_opinion(prompt)
        digest = hashlib.sha256(f"{self.seed}\0{prompt}\0opinion".encode("utf-8")).digest()
        base = own if own is not None else (digest[0] % 100) / 100.0
        value = round(min(1.0, max(0.0, base + (digest[1] % 9 - 4) / 100.0)), 3)
        if kind == "valid_json":
            return json.dumps({"opinion": value, "reason": f"stub reply {digest[2] % 100}"})
        if kind == "bare_float":
            return f"I heard the neighbours and would put myself near {value:.3f}, though not firmly."
        if kind == "unparsed_reply":
            return "I remain undecided; the neighbours do not move me enough to give a figure."
        if kind == "empty_reply":
            return ""
        raise StubTransportError("simulated transport failure")


# ---- the audit --------------------------------------------------------------------------------------------------

class MemoryStore:
    """The four calls LongitudinalSimulator makes on a TrajectoryStore. Panel rows are the study's own records."""

    def __init__(self):
        self.panel = []
        self.metrics = []
        self.events = []
        self.db_path = None                    # the loop's live-heartbeat writers skip a store without one

    def open(self) -> None:
        pass

    def record(self, records) -> None:
        self.panel.extend(records)

    def record_metrics(self, row) -> None:
        self.metrics.append(dict(row))

    def record_events(self, step, notes) -> None:
        if notes:
            self.events.append((step, list(notes)))

    def finalize(self) -> None:
        pass


class DecisionAudit:
    """The raw answer and the action it became, for every decision the study makes."""

    def __init__(self, decision, od):
        self.decision = decision
        self.od = od
        self.calls = []
        self.actions = []
        self._lock = threading.Lock()
        self._install()

    def _install(self) -> None:
        decision, od = self.decision, self.od

        def audited_ask(ob):
            # A faithful copy of BoundedConfidenceDecision._ask (model.py:320-327), with the raw reply and any
            # transport error recorded. The original catches the exception and returns ""; the audit must see why.
            if decision.llm is None:
                return ob, ""
            prompt = od.build_opinion_prompt(ob, decision.prompt_lang)
            rule_new, _target = decision._rule_opinion(ob)
            error = None
            try:
                raw = decision.llm(prompt)
            except Exception as exc:                       # noqa: BLE001 - the study counts any failure as no answer
                error = f"{type(exc).__name__}: {exc}"
                raw = ""
            with self._lock:
                self.calls.append({"agent_id": ob.agent_id, "step": ob.step, "prompt": prompt, "raw": raw,
                                   "error": error, "rule_opinion": rule_new})
            return ob, raw

        def audited_decide(obs, memories):
            actions = original_decide(obs, memories)
            with self._lock:
                self.actions.extend(actions)
            return actions

        original_decide = decision.decide_batch
        decision._ask = audited_ask
        decision.decide_batch = audited_decide


def classify(source: str, raw: str, error, strict: bool) -> str:
    """The audit's label for one decision. `strict` says the parser's JSON regex matched, not its bare-number resort."""
    if source == "fallback":
        if error:
            return "call_error"
        if not raw:
            return "empty_reply"
        return "unparsed_reply"
    if source == "llm":
        return "valid_json" if strict else "bare_float"
    return f"source:{source}"


def _strict_match(od, raw: str) -> bool:
    pattern = getattr(od, "_NUM_RE", None)
    if pattern is None:                                   # the study's regex, if a later version renames it
        pattern = re.compile(r'"opinion"\s*:\s*([0-9]*\.?[0-9]+)')
    return bool(pattern.search(raw)) if raw else False


def audit_rows(audit):
    """Pair each action with the call that produced it and label it."""
    calls = {(c["agent_id"], c["step"]): c for c in audit.calls}
    rows = []
    for action in audit.actions:
        call = calls.get((action.agent_id, action.step), {})
        raw, error = call.get("raw", ""), call.get("error")
        strict = _strict_match(audit.od, raw)
        label = classify(action.source, raw, error, strict)
        rows.append({
            "agent_id": action.agent_id, "step": action.step, "label": label, "source": action.source,
            "raw_reply": raw, "error": error or "", "strict_json": strict,
            "opinion": action.payload.get("opinion"), "rule_opinion": call.get("rule_opinion"),
            "reason": action.payload.get("reason", ""), "prompt": call.get("prompt", ""),
            "fallback_matches_rule": (None if action.source != "fallback"
                                      else action.payload.get("opinion") == call.get("rule_opinion")),
        })
    rows.sort(key=lambda r: (r["step"], r["agent_id"]))
    return rows


def _examples(rows):
    out = {}
    for row in rows:
        if row["label"] in out:
            continue
        text = row["raw_reply"]
        if row["error"]:
            text = f"[{row['error']}] {text}".strip()
        out[row["label"]] = text[:200]
    return out


def summarise(rows, store, history, *, root, shimmed, llm, model, steps, seed, prompt_lang, agents):
    counts = Counter(row["label"] for row in rows)
    decisions = len(rows)
    fallbacks = sum(counts[k] for k in ("unparsed_reply", "empty_reply", "call_error"))
    answers = counts["valid_json"] + counts["bare_float"] + counts["unparsed_reply"]   # non-empty model replies
    panel_fields = set()
    payload_fields = set()
    for record in store.panel:
        dumped = record.model_dump() if hasattr(record, "model_dump") else dict(record)
        panel_fields |= set(dumped)
        payload_fields |= set(dumped.get("action_payload") or {})
        if payload_fields:
            break
    fallback_disagreements = sum(1 for row in rows if row["fallback_matches_rule"] is False)
    summary = {
        "study": STUDY_ID,
        "socioverse_root": str(root),
        "socioverse_version": _socioverse_version(),
        "llm": llm,
        "model": model,
        "stub": llm == "stub",
        "stub_mix": dict(STUB_MIX) if llm == "stub" else None,
        "stub_duckdb": shimmed,
        "storage": "in-memory store; panel rows built by SocioVerse2's build_panel_rows",
        "steps": steps, "seed": seed, "agents": agents, "prompt_lang": prompt_lang,
        "decisions": decisions,
        "counts": {name: counts[name] for name in CLASSES},
        "other_sources": {k: v for k, v in counts.items() if k not in CLASSES},
        "fallbacks": fallbacks,
        "fallback_share": _share(fallbacks, decisions),
        "quiet_replacements": counts["unparsed_reply"],
        "quiet_replacement_share": _share(counts["unparsed_reply"], decisions),
        "quiet_share_of_model_answers": _share(counts["unparsed_reply"], answers),
        "model_answers": answers,
        "lenient_parses": counts["bare_float"],
        "lenient_parse_share": _share(counts["bare_float"], decisions),
        "fallback_matches_rule": fallbacks - fallback_disagreements,
        "fallback_rule_disagreements": fallback_disagreements,
        "panel_fields": sorted(panel_fields),
        "panel_payload_fields": sorted(payload_fields),
        "source_in_panel": bool({"source"} & panel_fields) or bool({"source"} & payload_fields),
        "panel_rows": len(store.panel),
        "metrics": [dict(row) for row in (history.rows if history is not None else [])],
        "examples": _examples(rows),
    }
    return summary


def _share(num, den):
    return round(num / den, 4) if den else None


def _socioverse_version() -> str:
    try:
        import socioverse
        return str(getattr(socioverse, "__version__", ""))
    except ImportError:
        return ""


# ---- the run ----------------------------------------------------------------------------------------------------

def run_scope_test(*, socioverse_root_path=None, out=DEFAULT_OUT, llm="stub", model=None, base_url=None,
                   steps=None, seed=None, prompt_lang=None) -> dict:
    """Run the reference study with the audited decision step. Returns the summary (also written to --out)."""
    state = _ImportState()
    try:
        return _run_scope_test(socioverse_root_path=socioverse_root_path, out=out, llm=llm, model=model,
                               base_url=base_url, steps=steps, seed=seed, prompt_lang=prompt_lang, state=state)
    finally:
        state.restore()


def _run_scope_test(*, socioverse_root_path, out, llm, model, base_url, steps, seed, prompt_lang,
                    state) -> dict:
    if llm not in ("stub", "openai"):
        raise ScopeTestError("--llm must be stub or openai")
    root, od, bundles = load_reference(socioverse_root_path, state)
    env_bundle, pop_bundle, sim_config = bundles
    from socioverse.engine import build_providers
    from socioverse.engine.loop import LongitudinalSimulator
    from socioverse.engine.registry import resolve

    n_steps = int(steps if steps is not None else sim_config.n_steps)
    run_seed = int(seed if seed is not None else sim_config.seed)
    if n_steps < 1:
        raise ScopeTestError("--steps must be at least 1")
    args = dict(sim_config.decision_args)
    args.pop("llm_kind", None)
    args.pop("model", None)
    if prompt_lang is not None:
        args["prompt_lang"] = prompt_lang
    lang = args.get("prompt_lang", "en")
    if lang not in getattr(od, "PROMPT_LANGS", ("en",)):
        raise ScopeTestError(f"prompt_lang must be one of {getattr(od, 'PROMPT_LANGS', ('en',))}")
    chosen_model = model or ("stub" if llm == "stub" else os.environ.get("SV_LLM_MODEL", "gpt-4o"))
    env, population = build_providers(env_bundle, pop_bundle)
    decision = resolve("decision", sim_config.decision_ref)(**dict(args, llm_kind="openai", model=chosen_model))
    if llm == "stub":
        decision.llm = StubLLM(run_seed)
    else:
        if base_url:
            os.environ["SV_LLM_BASE_URL"] = base_url
        if not (os.environ.get("SV_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")):
            raise ScopeTestError("--llm openai needs SV_LLM_API_KEY or OPENAI_API_KEY in the environment; the key is "
                                 "read there and never printed or written")
        if decision.llm is None:
            raise ScopeTestError("the reference decision model built no LLM client")
    collector = resolve("collector", sim_config.collector_ref)(**sim_config.collector_args)
    store = MemoryStore()
    sim = LongitudinalSimulator(
        env=env, population=population, decision=decision, store=store, collector=collector, n_steps=n_steps,
        seed=run_seed, interaction_rounds=sim_config.interaction_rounds,
        memory_window=int((sim_config.engine_args or {}).get("memory_window", 8)),
        metric_columns=["step", *getattr(od, "OD_METRICS", [])], study_id=sim_config.study_id)
    audit = DecisionAudit(decision, od)
    history = sim.run()
    rows = audit_rows(audit)
    summary = summarise(rows, store, history, root=root, shimmed=bool(sys.modules.get("duckdb")
                                                                     and getattr(sys.modules["duckdb"],
                                                                                 "__scope_test_shim__", False)),
                        llm=llm, model=chosen_model, steps=n_steps, seed=run_seed, prompt_lang=lang,
                        agents=len(population.build(run_seed)))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "summary.json", summary)
    with (out / "decisions.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out / "report.md").write_text(_report(summary), encoding="utf-8", newline="\n")
    return summary


def _write_json(path: Path, data) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False) + "\n")


def _pct(value):
    return "NA" if value is None else f"{value * 100:.1f}%"


def _report(summary: dict) -> str:
    lines = [
        "# SocioVerse2 scope test: the opinion_diffusion decision step, audited", "",
        "Study: `studies/opinion_diffusion` from SocioVerse2 "
        f"{summary['socioverse_version'] or '(version unknown)'} at `{summary['socioverse_root']}`. "
        f"Model endpoint: {summary['llm']} ({summary['model']}); "
        f"{summary['agents']} agents x {summary['steps']} steps = {summary['decisions']} decisions, "
        f"seed {summary['seed']}, prompt language {summary['prompt_lang']}.", "",
        "## What was replaced", "",
        f"- The LLM endpoint: {('a deterministic stub with the mix ' + json.dumps(summary['stub_mix'])) if summary['stub'] else 'a real OpenAI-compatible endpoint through SocioVerse2 own client'}.",
        f"- The trajectory store: {summary['storage']}. DuckDB stand-in installed: {summary['stub_duckdb']}.",
        "- Everything else is the reference study's own code: its environment, population, decision model, metric "
        "collector and `LongitudinalSimulator`.", "",
        "## Measured", "",
        "| decision class | count | share of decisions |", "|---|---|---|",
    ]
    for name in CLASSES:
        count = summary["counts"][name]
        lines.append(f"| {name} | {count} | {_pct(_share(count, summary['decisions']))} |")
    lines += [
        "", "Definitions:", "",
        "- `valid_json`: the model replied with a JSON object the study's strict `\"opinion\"` regex read.",
        "- `bare_float`: the strict regex failed, but the parser's last-resort bare-number regex found a number and "
        "the study used it.",
        "- `unparsed_reply`: a non-empty model reply arrived and the study's bounded-confidence rule replaced it "
        "(the quiet replacement).",
        "- `empty_reply`: the call returned an empty string and the rule filled the metric.",
        "- `call_error`: the call raised and the rule filled the metric (`_ask` catches the exception and returns "
        "\"\").",
        "", "The quiet replacement rate:", "",
        f"- {summary['quiet_replacements']} of {summary['decisions']} decisions "
        f"({_pct(summary['quiet_replacement_share'])}) replaced a non-empty model answer with the rule.",
        f"- That is {_pct(summary['quiet_share_of_model_answers'])} of the {summary['model_answers']} non-empty "
        "model answers.",
        f"- All fallbacks together: {summary['fallbacks']} ({_pct(summary['fallback_share'])} of decisions). "
        f"Fallback value equals the study's rule value in {summary['fallback_matches_rule']} of "
        f"{summary['fallbacks']} (disagreements: {summary['fallback_rule_disagreements']}).",
        f"- The parser's bare-number last resort read {summary['lenient_parses']} replies "
        f"({_pct(summary['lenient_parse_share'])} of decisions).", "",
        "## Is the replacement visible in the trajectory?", "",
        f"The panel row fields are {summary['panel_fields']}; the action payload fields are "
        f"{summary['panel_payload_fields']}. `source` in the panel: **{summary['source_in_panel']}**. The action "
        "carries `source='fallback'`, but `build_panel_rows` (and the DuckDB panel DDL) keep only kind and payload, so "
        "a reader of the trajectory cannot tell a model answer from a rule replacement; only the study's log warning "
        "does. That is what 'quietly' means here.", "",
        "## Examples", "",
    ]
    for name in CLASSES:
        example = summary["examples"].get(name)
        if example is not None:
            lines.append(f"- `{name}`: {json.dumps(example, ensure_ascii=False)}")
    lines += [
        "", "## Reading this number", "",
        f"This run used {'the stub, whose reply mix is chosen to exercise every parser path; the rates are not a measurement of any model' if summary['stub'] else 'a real model endpoint'}. "
        "The point is that the audit sees and classifies every replacement. Re-run with `--llm openai` (a key in "
        "`SV_LLM_API_KEY`) to measure a specific model; the command and outputs are the same.", "",
    ]
    return "\n".join(lines)


# ---- command line -----------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--socioverse-root", help="the SocioVerse2 checkout (default: the vendored one)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help=f"output folder (default {DEFAULT_OUT})")
    ap.add_argument("--llm", choices=("stub", "openai"), default="stub",
                    help="stub (no model, no network) or openai (a real endpoint; needs SV_LLM_API_KEY)")
    ap.add_argument("--model", help="the model id for --llm openai (default $SV_LLM_MODEL or gpt-4o)")
    ap.add_argument("--base-url", help="an OpenAI-compatible base URL (sets SV_LLM_BASE_URL for this process)")
    ap.add_argument("--steps", type=int, help="steps to run (default: the study's n_steps)")
    ap.add_argument("--seed", type=int, help="run seed (default: the study's seed)")
    ap.add_argument("--prompt-lang", choices=("en", "zh"), help="the prompt language (default: the study's)")
    ap.add_argument("--quiet", action="store_true", help="do not print the summary")
    args = ap.parse_args(argv)
    try:
        summary = run_scope_test(socioverse_root_path=args.socioverse_root, out=args.out, llm=args.llm,
                                 model=args.model, base_url=args.base_url, steps=args.steps, seed=args.seed,
                                 prompt_lang=args.prompt_lang)
    except (ScopeTestError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not args.quiet:
        print(f"{summary['study']}: {summary['decisions']} decisions, {summary['fallbacks']} fallbacks "
              f"({_pct(summary['fallback_share'])}); {summary['quiet_replacements']} non-empty model answers "
              f"replaced by the rule ({_pct(summary['quiet_replacement_share'])} of decisions). source in panel: "
              f"{summary['source_in_panel']}. Output in {Path(args.out).resolve()}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
