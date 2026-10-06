# Token efficiency

A 36-month run makes roughly 375–555 model calls, and every one of them sends a long prompt. On
subscription seats that is what runs into usage limits; on API seats it is the bill; on local models it
is the time per month. This page is about measuring where those tokens go and about the opt-in features
that send fewer of them.

Everything here follows one rule: **a run that does not ask for a feature is engine 5 exactly.**
`tests/test_prompt_freeze.py` holds a default run to the sha256 of every prompt the published
engine-5 code sends in a four-month scripted run. A run that turns a feature on records it in
`config.json` and in the manifest (`token_saving`), and `manifest.divergences()` names it, so such a run
is never compared with a default one as if they were alike. Every feature changes what a delegate is
sent or when it is asked, so each is a condition to compare, not a free optimisation; validate one on a
few seeds with real models before using it in a study.

## Measure first

```bash
python -m karamaniya tokens runs/<name>            # one run
python -m karamaniya tokens runs/a runs/b --json ledger.json
```

The ledger reads a run folder and makes no model calls. It reports input and output by phase, by seat
and by prompt section; the token counts the providers reported, where they did (input, output, cache
reads, cache writes, reasoning); and a deterministic prefix-cache simulation: of the input a run sent,
how much repeated a prefix the same model had just been sent, within one phase, one month or the whole
run. That is what an automatic prefix cache (OpenAI, DeepSeek, a llama.cpp or Ollama KV cache) can
reuse, and an upper bound for an explicit one (Anthropic `cache_control` breakpoints). Estimates are at
four characters per token: the tokenizers differ, so they are for comparing prompts and layouts with
each other, not for a bill.

### Where the tokens go

A 12-month run of `council.scripted.toml` (seed 1, 194 calls, about 1.34M input tokens):

| Phase | Share of input |  | Section | Share of input |
|---|---:|---|---|---:|
| session (opening statements) | 37.1% | | **system prompt** (sent with every call) | **32.5%** |
| decision | 35.3% | | canonical state | 11.8% |
| revision (response round) | 16.6% | | public briefing | 9.3% |
| foreign cabinets | 4.6% | | instructions | 8.5% |
| founding diagnosis | 2.1% | | answer schema | 6.5% |
| formation proposal | 1.8% | | disposition | 4.8% |
| formation vote | 1.2% | | office reports, role, transcript, beliefs, standing, notes, memory, ... | each under 3% |
| survey | 1.2% | | | |

The single largest item is the 10,140-character system prompt, identical in every council call. The
canonical state and the briefing are the same for every delegate in a month. That is why caching, not
trimming, is where most of the saving is.

## The features

All of them are set in the council file:

```toml
[run.tokens]
layout = "cache_friendly"   # classic | cache_friendly
schema_hint = "auto"        # example | compact | auto
briefing = "on_demand"      # full | on_demand
wakeups = "on_events"       # always | on_events
max_quiet_months = 3

[run]
foreign_cabinet_backend = { provider = "ollama", model = "qwen3.5:9b", label = "environment" }

[[seat]]
effort_by_phase = { decision = "high", session = "low", revision = "low", survey = "low" }
```

### 1. Cache-friendly layout (`layout = "cache_friendly"`)

The same sections, nothing added or removed, sent in the order in which they stop being shared: the
month's canonical state and the public briefing (identical for every delegate in every phase of the
month), then the delegate's standing context (disposition, standing, forecasts, notes: the same in all
three of its calls that month), then what depends on the motions on the table, then the phase. The
instructions and the answer schema stay last. The two lines of the canonical state that depend on the
phase (the phase name, and the pending line listing this session's motions) move, word for word, into
the phase part. A test checks that every prompt has exactly the words of its classic counterpart.

The prompt builder records where the shared and the standing parts end (`cache_points` in
`prompt_meta`), and the Anthropic API connector turns them into `cache_control` breakpoints (the system
prompt already was one). OpenAI and DeepSeek cache a repeated prefix automatically, a local llama.cpp or
Ollama server reuses its KV cache for one, and Claude Code applies prompt caching itself (it reports the
cache reads, which the ledger records); the layout is what gives all of them a long prefix to reuse.

Measured (same 12-month world): the share of input a cache can reuse goes from **21% to 41% within a
month** and from **31% to 52% over the run**, for a council of five different models. In a same-model
government, 41% to 59% within a month.

### 2. Compact schema hint (`schema_hint = "compact"` or `"auto"`)

The answer's shape spelled out without quotes, indentation or line breaks: every field and every
allowed value is still there. `auto` uses it only for seats whose connector holds the answer to the
schema anyway (Ollama `format`, the Anthropic API's JSON-schema output, Claude Code `--json-schema`,
Codex `--output-schema`, OpenAI-style strict `json_schema`), so a model that misreads the compact form
cannot produce a malformed answer.

Measured: the schema text shrinks by 24%; total input by **2%**. The JSON skeleton was already terse.

### 3. Briefing on demand (`briefing = "on_demand"`)

Every delegate gets the briefing's header, the council's own decisions of last month in full, and one
headline line for each other section, the section's own first line (no model summarises anything). A
decision may name, in `read_next_month`, the sections it wants in full next month; those arrive in a
part of the prompt of its own. Which sections each model chooses to read is recorded: what a model
chooses to pay attention to is itself a measurement.

Measured: **4% less input** if nobody asks for anything (the briefing is 9% of input, and the essentials
stay). Under the cache-friendly layout the briefing is already in the cached prefix, so this saves less
again there. It is worth running as a research condition, less as an optimisation.

### 4. Quiet months (`wakeups = "on_events"`)

A decision may say `stand_by`: how many coming months the delegate is content for the council not to
meet, and up to three `wake_if` conditions (for example unemployment above 12% or reserves below 50M)
that would bring it back. The council skips a month only when **every** delegate stands by and none of
their conditions holds. It always meets in an election or handover month, in war, the month after a
coup or after anyone left the government, and whenever a diplomatic proposal, a deferred motion or an
unread private message is waiting, a new issue reaches the agenda, or last month brought a public event
of the engine's top importance (deaths at a protest, an uprising, a court annulling an election, a
region lost). Never more than `max_quiet_months` in a row. In a quiet month no council member is called:
policy and office orders stay as they are, the world moves on, the foreign cabinets still play their
month (with their own model if you give them one, see 5), and the next briefing says the council did
not meet.

Measured: when every delegate stands by for the maximum, **39% fewer calls** (119 instead of 194 in 12
months) and 44% less input; the rest of the months something happened that the council had to meet
over. That is an upper bound: whether models choose to stand by, and for how long, is behaviour, and
measuring it is part of the point: a council that hands the country to standing policy for a quarter is
telling you something.

### 5. One fixed model for the foreign cabinets (`foreign_cabinet_backend`)

Veleria and Dorsania are the environment, not the subjects. By default they borrow the first two council
seats, so two of the models under study also write the foreign moves the council then answers, and pay
two extra calls a month for it (5% of input). A dedicated backend, for example a small local model,
takes both cabinets off the subject seats and keeps the environment the same across every council it
is compared with.

### 6. Effort by phase (`effort_by_phase`, per seat)

Reasoning is spent where the stakes are: high for the decision, low for the opening statement, the
survey or government formation. It maps to `--effort` (Claude Code), `output_config.effort` (Anthropic
API), `model_reasoning_effort` (Codex), `--thinking` (Cline), `--reasoning-effort` (Copilot),
`reasoning_effort` (OpenAI-style APIs) and `think` on or off (Ollama). Each call records the effort it
was made with. Output and reasoning tokens are the expensive ones, but what this saves depends on the
model: it can only be measured with real seats, where the ledger reports reasoning tokens by phase.

### 7. Memory written by the engine: already the case

The idea was to replace re-sent prose about past months with the engine's own record. Measured, engine 5
already does that: `memory` is a list of dated items taken from the council record and the delegate's
own commitments, selected by salience and topic, and it is 1.2% of input. The only free prose is the
delegate's notebook (1.3%), which is kept on purpose: it is what the memory-integrity checks compare
with the record. Tighter limits are available through the existing tuning
(`[run] tuning = { memory = { recent_months = ..., retrieved_items = ... } }`). Nothing new was built.

## All together

`python tools/token_benchmark.py --months 12` runs every variant on the same deterministic world (the
scripted stand-ins answer from the world, not the prompt, so the calls are identical across variants and
only the prompts differ):

| Variant | Calls | Input vs engine 5 | Cache reuse, month | Cache reuse, run | Billed vs engine 5 uncached* |
|---|---:|---:|---:|---:|---:|
| engine 5 (classic) | 194 | 1.00 | 21.0% | 31.4% | 0.81 |
| cache-friendly layout | 194 | 1.00 | 41.3% | 51.8% | 0.63 |
| compact schema hint | 194 | 0.98 | 21.3% | 31.9% | 0.80 |
| briefing on demand, nothing requested | 194 | 0.96 | 21.8% | 32.7% | 0.77 |
| quiet months, everyone stands by | 119 | 0.56 | 22.2% | 30.8% | 0.45 |
| all of the above | 119 | 0.53 | 39.8% | 48.9% | 0.34 |

\* Input cost relative to engine 5 with no cache, when a cache serves the reusable prefix within a month
at a tenth of the price (about what Anthropic charges for a cache read; check current prices).

The behaviour-dependent rows (briefing, quiet months) are upper bounds: real models decide what to read
and whether to stand by.

## Prices

A seat's cost is `price_in` and `price_out` per million tokens, as before. Give `price_cache_read` and
`price_cache_write` too, and cached input is billed at those prices; without them every input token is
billed at `price_in`, exactly as engine 5 did, so `max_cost_usd` behaves the same.

## Limits of these numbers

- Character counts are exact; token counts are estimates at four characters per token.
- The cache simulation counts the longest prefix a recent call to the same model shared (at least 1,024
  tokens). A real cache also needs the earlier call to have written that prefix and to still hold it:
  read the "month" column for a cache that lives minutes to an hour, "run" for one that lives longer.
- The scripted stand-ins do not read their prompts, so these runs show what the prompts cost, not how a
  model would behave with them. That is the next measurement: the same seeds, real seats, each feature
  on and off.
