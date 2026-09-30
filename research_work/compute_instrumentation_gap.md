# Task H compute-instrumentation gap — read-only inspection (task_0007)

Status: PRELIMINARY OBSERVATIONS from code inspection only. No runs resumed, no code edited, no token counts invented.

Scope: `backends/base.py` CallResult + complete(), each backend's token/cost reporting, `council.py` `_call` / `_foreign_cabinets` / `_call_summary`, `prompts.jsonl` vs `log.jsonl` vs `system_prompt.txt`, `manifest.py` sampling + served_models, `council.*.toml` pricing.

## Where things are logged today

- Per-call row: `council.py:298-300` logs `type=call, month, phase, member, seat, provider, model, **res.to_dict(), prompt_chars`. `to_dict()` = `base.py:42-45` = all CallResult fields except `data`.
- Foreign row: `council.py:1608-1610`, same shape with `actor`.
- Prompt body: `council.py:301-302` + `:1611-1612` via `storage.py:69-70` to `prompts.jsonl`.
- System prompt: NOT in `prompts.jsonl`; saved once to `system_prompt.txt` at `runner.py:160` (resume `:211`).
- Month-record summary `_call_summary council.py:1582-1585`: served_model, refusal, error, ok, format_retry, cost_usd, latency_s — no tokens.
- Pricing: `base.py:80-81` (`price_in/out` from seat cfg) -> `base.py:85-86` cost(). No shipped TOML sets prices.

## Field classification 1/2

| Task-H field | Verdict | Evidence |
|---|---|---|
| input tokens | ALREADY_LOGGED (per call, caveats) | `base.py:31`; anthropic `anthropic_api.py:79-80`, openai-compat `openai_compat.py:160`, claude `claude_cli.py:103-104`, codex `codex_cli.py:147`, copilot `copilot_cli.py:54,59`, cline `cline_cli.py:113`, antigravity `antigravity_cli.py:68`, ollama `ollama.py:78`; persisted `council.py:298-300`. Caveats: scripted always 0 (`scripted.py:54`); cache accounting differs (Anthropic/Claude sum cache_read+creation; Copilot sums input+cache_read+cache_write). |
| output tokens | ALREADY_LOGGED (folded, see reasoning) | `base.py:32`; same paths (`anthropic_api.py:81`, `openai_compat.py:161`, `claude_cli.py:105`, `codex_cli.py:148`, `copilot_cli.py:52,57-58`, `cline_cli.py:114`, `antigravity_cli.py:69`, `ollama.py:79`). |
| total tokens | MISSING | Zero hits for `total_tokens` in repo. Derivable as in+out; never stored in `base.py:27-40`, `council.py:298-300,1582-1585`, or manifest. |
| model (requested) | ALREADY_LOGGED | `council.py:300` (`seat.cfg model`); `manifest.py:73-76`; cfgs `council.example.toml:28,36,43,49,58`, `live-free-local.toml:16,22,27,33,41`, `scripted.toml` (persona). |
| served_model | PARTIALLY_LOGGED | Per-call `base.py:30` at `council.py:298-300`; aggregated `manifest.py:80-98,135-136`. Observed: Claude `claude_cli.py:106` (modelUsage), Anthropic `:84,87` (resp.model), Copilot `:72-74,118`, Ollama `:77`, OpenAI-compat `:162` (out.model), Antigravity `:62,77`. Echoed: Codex `codex_cli.py:151` (`self.model or "codex default"`); Cline `cline_cli.py:117` (model/provider/default). Manifest fallback `:94` (`served_model or model`) masks gap. |
| provider | ALREADY_LOGGED | `council.py:299,1609`; `manifest.py:73`; list `backends/__init__.py:7-9`. Label != identity (DeepSeek behind claude_cli `council.example.toml:52-60`). |
| reasoning | MISSING | No reasoning-text field in `base.py:27-40`/rows. Splits folded: Codex `:148` (output+reasoning_output), Antigravity `:69` (output+thinking); openai-compat `:160-161` ignores reasoning/cached details. Knobs (effort/thinking/reasoning_effort) sent but outcome not logged per call.
<!--MORE-->
## Field classification 2/2

- temperature: PARTIALLY_LOGGED — field `base.py:40`, set `council.py:293`, logged `:298-300`. Injected only arch>=2 `:273-276` via `_temperature :771-782`, gated on tuning + supports_temperature `:775`. Only openai-compat `:56`, ollama `:33` True (default False `:88`), so CLI seats log null. Manifest `sampling() :54,59` copies cfg temperature; shipped TOMLs set none.
- latency: ALREADY_LOGGED — `base.py:34,135` whole-complete incl. format-retry; logged `:298-300`, summaries `:1585,1619`. No per-attempt split.
- retries/attempts: PARTIALLY_LOGGED — `attempts :37` (`:106`, summed `:130`) + `format_retry :38,131` logged. NOT captured: per-attempt tokens/latency; transient backoff `_attempt :100-119` keeps final attempt only; openai length-retry `openai_compat.py:92-100` drops first cut-off tokens (unlike base summation); connector_trimmed `cline_cli.py:59` on ctx, never logged.
- cost_usd: PARTIALLY_LOGGED — `base.py:33` via cost() per backend (claude `:122`, codex `:152`, copilot `:120`, cline `:118`, antigravity `:78`, anthropic `:82`; ollama no-cost `ollama.py:77-79` -> 0; scripted `:54` -> 0); spend `council.py:295,1604`, state `:254,260`; logged `:298-300,1610`. Prices default 0 `:80-81`; no shipped TOML sets price_in/out (example `:54` comment only); Copilot premium_requests `copilot_cli.py:60` read then dropped; max_cost_usd (`config.py:17`, example `:21`) binds only priced seats.
- engine seed: ALREADY_LOGGED (run-level) — `manifest.py:125-131`, `config.py:14,93`, streams `:31-43`. Call rows carry month only (rng_for derivation, by design).
- sampling seed: MISSING — SAMPLING_KEYS `manifest.py:46` lists seed but `sampling() :54-56` copies run.seed = world seed, not model seed. No backend sends a seed param; no per-call value. Outputs explicitly non-deterministic `:9-13,141-146`.

## Prompt/token inputs available without new code

- prompts.jsonl: month/phase/member(prompt=user only)/schema/[prompt_meta] (`council.py:301-302,1611-1612`). No system, temp/seed/effort, counts, trimmed flag.
- log.jsonl adds prompt_chars=len(user) `:300,1610` — chars only, system excluded; merged prompt (cli_common:193-196) is what Copilot/Antigravity saw.
- Usable today: count type=call/foreign_call; sum in/out tokens; measure prompt_chars; join prompts on (month,phase,member). No invented $/tokenizer — instrument first.

## Smallest future proposal (no implementation)

1. base.py: add total_tokens (in+out), reasoning_tokens=0, sampling_seed=None, effort/thinking=None, premium_requests=None, attempt_details=[]; keep to_dict() inclusive so council rows pick up free.
2. Backends: split received values — codex reasoning_output, antigravity thinking, openai-compat +reasoning/cached details; copilot pass premium_requests; codex/cline prefer CLI-reported model or add served_observed flag; document ollama cost 0 = local.
3. council.py _call: log sampling_seed + effective effort/thinking/reasoning_effort/max_tokens, system_chars+system_hash beside prompt_chars, connector_trimmed into row + prompt_meta.
4. manifest.py sampling() :59: also copy per-seat seed/max_tokens/reasoning_effort; add prices snapshot; clarify run.seed != sampling seed.
5. README cost note: subscription seats cost_usd=0 by design; $ needs explicit price_in/out.

## Missing-fields short answer

MISSING: total_tokens; reasoning content + split; sampling seed; premium_requests in logs; per-attempt detail; length-retry first-attempt tokens; connector_trimmed. PARTIALLY: served_model (Codex/Cline echoed), temperature (null on CLI), attempts/cost (aggregated/zero caveats). ALREADY: in/out tokens, requested model, provider, latency, engine seed, user prompt+schema, system text.
