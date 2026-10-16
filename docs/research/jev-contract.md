# Jev / TypeSafe "System One" — API contract and open analogs
Compiled 2026-10-13 from live fetches (see §4). INFERRED = inferred, not directly confirmed.

## 1. Official HTTP API — POST https://api.typesafe.ai/v1/systemone
Auth: `Authorization: Bearer <API_KEY>`, `Content-Type: application/json`. Keys: console.typesafe.ai/keys.
Discovery: `GET https://api.typesafe.ai/v1/models` -> [{name, description, release_date}] (currently lists aliases).

### Request
{
  "state":     <string | object | array>,   // required; content to evaluate; text only
  "model":     "jev-latest",                // required
  "questions": { "<your-id>": <Question> }  // required; ids are yours, never sent to the model
}

Question common: `type`, `instructions` (string | object | array).
Choice : {"type":"choice", "instructions":..., "criteria": {"<option>": <string|object|null>, ...}}  // required; <=255 options
Score  : {"type":"score",  "instructions":..., "criteria": [<level0>, <level1>, ...]}                // required; 2..10 levels, low->high
Noul   : {"type":"noul",   "instructions":..., "criteria": {"true": <...>, "false": <...>}}          // criteria optional

- Options live ONLY in `criteria` (no `options` key): Choice keys are option names, values are descriptions (null = name suffices); Score is an ordered array of level descriptions; level number = 0-based array index.
- Any entry (instructions, criteria value/level, Noul true/false) may be string | object | array | null. Structured objects use free-form fields (observed keys: what, not_for, examples, summary, signals, question, focus, note, unit); none reserved; instruction objects may reference fields by name in backticks.
- The model never sees question ids or level numbers, only descriptions. Put the whole question in `instructions`.
- Batch semantics: all three types mix in one request; questions run in parallel and in isolation (a question never sees another's answer). "Adding questions barely changes the response time" (tokens still billed per question).

### Response 200
{
  "model":   "jev-1.13.0",                 // resolved versioned id, not the alias sent
  "answers": { "<your-id>": <Answer>, ... },
  "usage":   { "input_tokens": <int>, "output_tokens": <int> }
}

Answer keys by type (each answer repeats "type"):
Choice: "choice" (top-probability option, string), "probabilities" {"<option>": float, sum=1}, "confidence" 0..1
Score : "score" (float, probability-weighted mean of level indices, may fall between levels), "legend" {"<indexStr>": "<description>"}, "probabilities" {"<indexStr>": float, sum=1}, "confidence" 0..1
Noul  : "noul" (float 0..1, P(yes)); no confidence field (use |2p-1| to map to 0..1)
Confidence formulas: Choice (p_max - 1/n)/(1 - 1/n); Score max(0, 1 - sum(p_i*|i-m|)/MAD_unif), MAD_unif = (1/n)*sum(|i-(n-1)/2|), m = peak level index. 1 = concentrated on one outcome, 0 = uniform.

### Errors (JSON body describing the problem; no other codes documented)
401 Unauthorized (missing/invalid key) | 422 Unprocessable Entity (body validation; names offending field) |
429 Too Many Requests (rate limit; SDKs retry with backoff and honor `retry-after`) | 529 Overloaded (retry with backoff)

### Models, pricing, limits
- Current model: jev-1.13.0. Aliases: jev-latest -> jev-1.13.0 (default in SDKs/docs), jev-preview -> jev-1.13.0 ("no preview build available right now"). Pin the versioned id when confidence thresholds matter.
- Pricing: $42 per Btok == $0.042 per Mtok, input tokens only; output tokens free.
- Rate limits: 100K tokens/s and 80 req/s ("adjusting dynamically... can change without notice"); excess -> 429.
- Context: 64k tokens per request (state + ALL questions); tighter cap 32k for state + the single longest question. Text only; English performs best.
- No per-customer fine-tuning/LoRA; docs say one weight set, trained with RLCD for calibrated decisions.
- Official SDK env vars: TYPESAFE_API_KEY, TYPESAFE_BASE_URL (default https://api.typesafe.ai), TYPESAFE_DEFAULT_MODEL (default jev-latest), TYPESAFE_LOG_LEVEL; DEFAULT_TIMEOUT = 10.0 s per HTTP op.
- Alternate host (reported in jev-library archive snapshot; NOT directly verified): OpenRouter Decisions API `POST https://openrouter.ai/api/alpha/decisions`, models `typesafe/jev-1.13` and `~typesafe/jev-latest` (untilded alias reportedly absent; OpenRouter listed 32K context on 2026-10-01 — do not merge with TypeSafe's 64k/32k).

## 2. system-one-adapter-python — drop-in SystemOne emulator over LLM APIs
Repo: github.com/typesafe-ai/system-one-adapter-python. "Drop-in TypeSafeClient replacement backed by LLM APIs"; same system_one surface, answers produced by an LLM.
Install extras: `system-one-adapter[openai]` | `[anthropic]` | `[gemini]`.
Entry points: `SystemOneAdapterClient` / `AsyncSystemOneAdapterClient`; package root also exports `Choice`, `Score`, `Noul`.
Providers (`system_one_adapter.providers.*`): `OpenAIProvider`, `AnthropicProvider`, `GeminiProvider`, async `Async*` variants, `Message`.
Config:
- Constructor: `structured_outputs` (native structured-output mode vs prompt-JSON+validate), `llm_answer_mode` ("probabilities" | "discrete"), `normalize_probabilities` (rescale invalid distributions to sum 1), `n_retry_malformed_structure` (corrective retries on schema failure), `retry=typesafe_sdk.RetryPolicy` (transient provider failures), optional default `provider=` / `model=`.
- Call: `client.system_one(state=..., questions={"q": Noul(instructions=...)}, provider="openai", model="gpt-4o-mini")` (async: `await client.system_one(...)`). `provider` required unless `model=` is a provider INSTANCE.
- Env: `OPENAI_BASE_URL` (custom OpenAI-compatible endpoint); `GEMINI_API_KEY` or `GOOGLE_API_KEY` (or `api_key=`). No config files.
- Per-provider: OpenAI -> Responses API (`store=False`); custom endpoints (incl. OPENAI_BASE_URL) default to Chat Completions; override with `api="responses"|"chat_completions"`. Gemini -> Interactions API (`store=False`). Anthropic -> `max_tokens` default 4096 (provider-level); hitting it, refusals, and context overflow raise `typesafe_sdk.TypeSafeError` with NO corrective retries.
- Ollama: not named in README. INFERRED path (untested): pass `OpenAIProvider("<model>", base_url="http://localhost:11434/v1")` as `model=`; custom endpoints default to Chat Completions, which ollama's OpenAI-compatible API serves. VERIFY at runtime.
- Response: `typesafe_sdk.SystemOneResponse` subclass — same `answers` + typed views, plus `usage` {input_tokens_total, output_tokens_total, n_retries, n_retries_malformed_structure, latency} and `debug` {llm_attempts, retry_reasons, normalization diagnostics}; `llm_attempts[i]` = {messages, model_request_parameters{schema, structured}, llm_response, debug_info{model, provider, error, api, finish_reason}}. Pydantic `model_dump()` / `model_dump_json()`. Errors carry `error.debug["llm_attempts"]`. Missing token counts -> None.
- Lifecycle: context manager or `close()` / `aclose()`; adapter closes providers it created, caller-supplied providers stay caller-owned.

## 3. Open analogs (none ship TypeSafe weights; none reproduce RLCD calibration)
Wire-compatible server:
- github.com/GitHub30/OpenJev (MIT) — open-weight System One server; `POST /v1/systemone` + `GET /v1/models` match TypeSafe's OpenAPI, so the official typesafe-sdk works unmodified: `TYPESAFE_BASE_URL=http://localhost:8000`, `TYPESAFE_API_KEY=anything` (server can check Bearer via OPENJEV_API_KEY). Any HF instruct model (examples Qwen/Qwen2.5-1.5B-Instruct, SmolLM2-135M; "Qwen, Llama, Gemma"); CPU-ok. Primitives and request/response keys identical to §1.
  Drive: Python `SystemOneEngine(backend=load_backend("<hf-id>"))` -> `.system_one(state=..., questions={...})`; server `openjev serve --model <hf-id> --port 8000 [--calibration calibration.json] [--adapter <lora-ckpt>]`; CLI `openjev ask -m <hf-id> -s <state> --noul "id=question" --choice "id=q|opt1,opt2" --score "id=q|low,mid,high"`. Training/calibration: `openjev calibrate` (temperature scaling), `scripts/train_calibrated.py` (LoRA, --brier-weight); JSONL rows {state, questions, gold}.
Trained weights / adapters:
- github.com/ejhshen/OpenJev — OpenJev-4B decision model (Qwen3.5-4B backbone + "Option Set Interactor" + decision head); weights shenjunhao/OpenJev-4B (HF); SFT -> REINFORCE-Analysis on OpenJevData-140k. SOURCE: search summary only, repo not directly fetched.
- HF ZefanCai/Open-Jev-2B and ZefanCai/Open-Jev-27B-v1.1 — LoRA + scalar decision head for Qwen3.5; served via `python -m jev.server` on :8791; candidate NLL + Brier loss. SOURCE: search summary / index lists only.
Logit-reading emulations (no generation; read option logits in one forward pass):
- github.com/TheoLeeCJ/SemIf (MIT; formerly OpenJev) — frozen Qwen/Qwen3.5-4B, revision 851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a; GPU-only; CLI only, no HTTP API. `semif-score --mode direct|shared --model Qwen/Qwen3.5-4B --input decisions.jsonl --output results.jsonl`; backends torch / `--backend mlx --device mps` / `--backend llamacpp --gguf <path>`. Input JSONL: {id, state, question, options:[{id, description}]}. Reported: 0.845 modal agreement with Jev on a 102-row TypeSafe subset (Jev 0.883); 5.21x faster than autoregressive JSON for 21 binary decisions on a 3090. States it "does not reproduce Jev's undisclosed model or training".
- github.com/r-ms/mini-jev (MIT) — study on frozen Qwen/Qwen3-4B-Instruct-2507 (bf16): lettered options, read letter logits vs xgrammar-constrained JSON. Demo browser server at http://127.0.0.1:8765/ (`MINIJEV_DEVICE=cuda uv run python demo/server.py`); flat JSON schema in, only string-enum/boolean/string(maxLength)/integer/number; nested objects/arrays refused. Reported: 0.907 (letters) vs 0.909 (JSON), 6750 paired obs; ~4x faster at 32-token texts. Endpoint paths (a `POST /run` is claimed in index summaries) are NOT documented in the README — unverified.
From-scratch learners / libraries (not API-compatible):
- github.com/vinnylarouge/jevlike (MIT) — option scorer + small released checkpoints (scorer head only; encoder weights not redistributed). One query vector per option attends over context; shared dot product -> softmax over options; default encoder learns byte embeddings (context 192B, option 32B). Drive: CLI `jevlike-train` / `jevlike-eval` / `jevlike-predict`; JSONL {context, options, label (0-based index)}. Reported ~98% synthetic, 26-29% Wikispeedia. "Not a copy of Jev".
- github.com/ikermoel/open-alternative-jev (Apache-2.0; import name `so1`) — Python library, NO HTTP server by design ("replaces the library, not the endpoint"). Any ChatML model (Qwen family); options addressed by letters A-Z, each must be a single token; `Decider.from_pretrained(id, backend="hf"|"vllm")` -> `decider.decide(state=..., questions=[...])`; `TemperatureScaler` calibration; `mode="packed"|"separate"`, `permutations=k`. Stated caveats: not calibrated out of the box; 6-9% of answers change from packing neighbours/order.
Named only in index lists (yibie/awesome-jev, Zaious/jev-capability-atlas, valentynkit/awesome-jev-typesafe), NOT individually verified: simple-jev, an OpenJev vLLM-server variant, openJev-verdict-2.0 (151M non-autoregressive, WebGPU), jevlike-esp32, jevbetter, minojev, TinyJev.

## 4. Verification status
Directly fetched this session: docs.typesafe.ai (llms.txt index; introduction/quickstart; api.md; models.md; primitives/choice|score|noul|advanced; confidence; sdk/python/api/constants), github.com/typesafe-ai/typesafe-sdk-python (landing page), github.com/typesafe-ai/system-one-adapter-python (raw README), github.com/Awesome-llms-labs/awesome-jev, github.com/mit-bach/jev-library, github.com/GitHub30/OpenJev, github.com/TheoLeeCJ/SemIf, github.com/r-ms/mini-jev, github.com/vinnylarouge/jevlike, github.com/ikermoel/open-alternative-jev.
Search-summary only (repo not fetched; treat as unverified): ejhshen/OpenJev, ZefanCai HF checkpoints, OpenRouter Decisions endpoint, mini-jev's `POST /run`.
INFERRED, never executed: the ollama-via-OpenAIProvider path (§2). All "reported" benchmark numbers are README/docs claims, not reproduced here. No live API call was made; no key used.
