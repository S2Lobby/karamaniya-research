# SocioVerse2 scope test: the opinion_diffusion decision step, audited

Study: `studies/opinion_diffusion` from SocioVerse2 0.2.0 at `C:\Users\litle\Karamaniya\karamaniya-test\_vendor\SocioVerse2`. Model endpoint: stub (stub); 12 agents x 4 steps = 48 decisions, seed 42, prompt language zh.

## What was replaced

- The LLM endpoint: a deterministic stub with the mix {"valid_json": 60, "bare_float": 15, "unparsed_reply": 15, "empty_reply": 5, "call_error": 5}.
- The trajectory store: in-memory store; panel rows built by SocioVerse2's build_panel_rows. DuckDB stand-in installed: True.
- Everything else is the reference study's own code: its environment, population, decision model, metric collector and `LongitudinalSimulator`.

## Measured

| decision class | count | share of decisions |
|---|---|---|
| valid_json | 37 | 77.1% |
| bare_float | 4 | 8.3% |
| unparsed_reply | 3 | 6.2% |
| empty_reply | 3 | 6.2% |
| call_error | 1 | 2.1% |

Definitions:

- `valid_json`: the model replied with a JSON object the study's strict `"opinion"` regex read.
- `bare_float`: the strict regex failed, but the parser's last-resort bare-number regex found a number and the study used it.
- `unparsed_reply`: a non-empty model reply arrived and the study's bounded-confidence rule replaced it (the quiet replacement).
- `empty_reply`: the call returned an empty string and the rule filled the metric.
- `call_error`: the call raised and the rule filled the metric (`_ask` catches the exception and returns "").

The quiet replacement rate:

- 3 of 48 decisions (6.2%) replaced a non-empty model answer with the rule.
- That is 6.8% of the 44 non-empty model answers.
- All fallbacks together: 7 (14.6% of decisions). Fallback value equals the study's rule value in 7 of 7 (disagreements: 0).
- The parser's bare-number last resort read 4 replies (8.3% of decisions).

## Is the replacement visible in the trajectory?

The panel row fields are ['action_kind', 'action_payload', 'agent_id', 'state', 'step']; the action payload fields are ['opinion']. `source` in the panel: **False**. The action carries `source='fallback'`, but `build_panel_rows` (and the DuckDB panel DDL) keep only kind and payload, so a reader of the trajectory cannot tell a model answer from a rule replacement; only the study's log warning does. That is what 'quietly' means here.

## Examples

- `valid_json`: "{\"opinion\": 0.165, \"reason\": \"stub reply 54\"}"
- `bare_float`: "I heard the neighbours and would put myself near 0.092, though not firmly."
- `unparsed_reply`: "I remain undecided; the neighbours do not move me enough to give a figure."
- `empty_reply`: ""
- `call_error`: "[StubTransportError: simulated transport failure]"

## Reading this number

This run used the stub, whose reply mix is chosen to exercise every parser path; the rates are not a measurement of any model. The point is that the audit sees and classifies every replacement. Re-run with `--llm openai` (a key in `SV_LLM_API_KEY`) to measure a specific model; the command and outputs are the same.
