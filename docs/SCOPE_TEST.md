# Scope test: SocioVerse2's decision step under our audit

Built in wave 3 (workstream E). The tool is [`tools/scope_test.py`](../tools/scope_test.py); this page gives the
exact command, the measured numbers, and what they do and do not say.

## What was run

The study is SocioVerse2 0.2.0's own reference from-scratch study, `studies/opinion_diffusion` (Path B, the
bounded-confidence opinion model with a step-2 media campaign). Its environment, population, decision model,
metric collector and `LongitudinalSimulator` are used unchanged. Two things were replaced, both named in the
output:

- **The LLM endpoint.** No local model server was running (`http://127.0.0.1:11434/api/tags` did not answer), and
  no key or network was used. The default `--llm stub` is a deterministic stand-in: it hashes the prompt and
  returns a fixed mix of well-formed JSON (60%), a bare number in prose (15%), unparseable prose (15%), an empty
  answer (5%) and a raised transport error (5%). The mix is chosen to exercise every path of the study's parser
  and fallback; the resulting rates are **not** a measurement of any model.
- **The trajectory store.** `duckdb` is not installed in the engine's environment (research `.venv`), so the script
  puts a stand-in `duckdb` module in `sys.modules` for package import and uses an in-memory store with the same
  four calls. Panel rows are built by SocioVerse2's own `build_panel_rows`, so their shape matches the DuckDB
  panel. The DuckDB store itself was not exercised.

The audit wraps the study's own `BoundedConfidenceDecision`: for every decision it records the prompt, the raw
reply, a transport error if the call raised, the rule's own value, the action's value and its `source`. The study's
fallback is in `studies/opinion_diffusion/model.py:345-358`: when `llm_kind="openai"` and the reply does not parse,
it logs a warning, sets `source="fallback"` and uses the bounded-confidence rule.

## The exact command

Run from the repository root, with the engine's Python:

```bash
C:/Users/litle/Karamaniya/research/.venv/Scripts/python.exe tools/scope_test.py --out docs/scope_test_run
```

The defaults are the study's own: 4 steps, seed 42, `prompt_lang="zh"` (the language of the shipped reference run),
12 agents, `--llm stub`. The run is deterministic. The committed output is
[`docs/scope_test_run/`](scope_test_run/): `summary.json`, `decisions.jsonl` (one line per decision, with the full
prompt and raw reply) and `report.md`.

A real endpoint uses SocioVerse2's own OpenAI-compatible client and reads the key from the environment; the key is
never printed or written:

```bash
SV_LLM_API_KEY=... python tools/scope_test.py --llm openai --model gpt-4o-mini --out scope_test_openai
# optional: --base-url http://127.0.0.1:8000/v1 for a local OpenAI-compatible server
```

## Measured numbers

12 agents x 4 steps = **48 decisions**; 44 of them had a non-empty model reply.

| decision class | count | share of decisions |
|---|---:|---:|
| `valid_json`: strict `"opinion"` JSON read | 37 | 77.1% |
| `bare_float`: strict regex failed, the parser's last-resort bare-number regex read it | 4 | 8.3% |
| `unparsed_reply`: a non-empty reply arrived and the rule replaced it | 3 | 6.2% |
| `empty_reply`: the call returned an empty string and the rule filled the metric | 3 | 6.2% |
| `call_error`: the call raised and the rule filled the metric | 1 | 2.1% |

- **Fallbacks of every kind: 7 of 48 decisions (14.6%).**
- **Quiet replacements of a model answer: 3 of 48 decisions (6.2%)**, which is 6.8% of the 44 non-empty model
  answers. "Quiet" means the model did answer, the parser could not read it, and the rule value took its place.
- The fallback value equals the study's own rule value in **7 of 7** cases (0 disagreements).
- The parser's bare-number last resort read **4 replies (8.3%)** beyond the strict JSON path.
- The study's own metrics still run: mean opinion 0.500 at step 0 to 0.569 at step 4; opinion std 0.288 to 0.219,
  with the step-2 campaign event recorded. The fallback does not break the study; it substitutes values.

## The finding that matters for our package

`BoundedConfidenceDecision` sets `source="fallback"` on the `Action`, but SocioVerse2's trajectory store does not
keep it. `build_panel_rows` records only `agent_id`, `step`, `state`, `action_kind` and `action_payload`; the
DuckDB panel DDL (`socioverse/io/duckdb_store.py`) has the same columns. The audit observed panel fields
`['action_kind', 'action_payload', 'agent_id', 'state', 'step']`, and `source` is absent from both the row and the
payload. A reader of the stored trajectory cannot tell a model answer from a rule replacement; the only trace is
the study's `_log.warning("unparsed reply from %s, using the rule: %r", ...)`, which is not in the trajectory. This
is why we audit the decision step rather than reading the store.

The same pattern in a Karamaniya-adjacent wrap would mean a model's answer could be replaced without the panel
showing it. Our engine records the raw answer and the engine's reading separately, so the exit audit can reconcile
them; the scope test is the check that a wrapped simulator does not quietly lose that distinction.

## What this does not say

- It does not measure any model. The stub mix is chosen; only `--llm openai` with a real endpoint measures a
  model's fallback rate. That run was not made here (no key, no local server, no network use).
- It exercises one decision implementation (`opinion_diffusion`). Other SocioVerse2 studies (`campus_dining_choice`,
  `hisim_roe`, `germany_auto_market`) have their own fallbacks; the tool would need their model module to audit
  those.
- The in-memory store is not DuckDB. The panel shape is SocioVerse2's own, but the store's own writes (parquet
  export, transactions) are not tested here.
- The three long lines of `unparsed reply ...` warnings on stderr are the study's own log; the audit keeps the same
  events in `decisions.jsonl`.

## Verification

- Command run on 2026-10-17 from `C:\Users\litle\Karamaniya\karamaniya-test\wave3-package` with Python 3.12.10.
- Exit code 0; the committed outputs in `docs/scope_test_run/` are the run's files.
- Tests: `python -m unittest tests.test_engine24_scope_test -v` -> 7 tests, OK (the integration tests run the
  reference study twice and compare the audits).
- The vendored checkout is `C:\Users\litle\Karamaniya\karamaniya-test\_vendor\SocioVerse2` (version 0.2.0); the
  scope test writes nothing into it.
