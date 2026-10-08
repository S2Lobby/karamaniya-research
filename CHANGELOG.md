# Changelog

What changed in the simulator between published versions. Every run folder records the versions that
produced it (`manifest.json`, `karamaniya/versions.py`), and `docs/ENGINEERING_BACKLOG.md` keeps the
task-by-task record with the tests behind each item.

## Since engine-5 (on `main`)

The world engine, the agent prompts and the psychology are unchanged (`WORLD_ENGINE` 5, `AGENT_PROMPT` 5,
`PSYCHOLOGY` 4): a run with default settings sends byte for byte the prompts the `engine-5` tag sends,
which `tests/test_prompt_freeze.py` checks. What is new is measurement, and features a run must turn on.

Measurement

- `python -m karamaniya tokens`: where a run's tokens went, by phase, seat and prompt section; the counts
  the providers reported (input, output, cache reads and writes, reasoning); the cost of one simulated
  month with the setup apart; each seat's characters per provider-counted token; a combined rate and
  projection over several runs; and a simulation of how much of the input a prompt cache could reuse.
- `tools/cache_replay.py`: replays a run's prompts through a local Ollama server and counts, from the
  server's log, the prompt tokens it really evaluated.
- Every model call has a `call_id`, written to both `log.jsonl` and `prompts.jsonl`, and records the
  cache, reasoning and effort fields where the provider reports them (zero or empty otherwise).

Opt-in features (off by default; recorded in `config.json` and the manifest's `token_saving` when on,
and named by `manifest.divergences()`)

- `[run.tokens]`: `layout = "cache_friendly"`, `schema_hint = "compact" | "auto"`,
  `briefing = "on_demand"`, `wakeups = "on_events"` with `max_quiet_months`.
- `[run] foreign_cabinet_backend`: one fixed model for the two foreign cabinets.
- `[[seat]] effort_by_phase`, and `price_cache_read` / `price_cache_write` for cached input.

Fixes

- Codex CLI seats counted their reasoning tokens twice in `output_tokens` (Codex's own count already
  includes them). In engine-5 runs a Codex seat's output, and its cost when it had a `price_out`, is
  overstated by its reasoning tokens; input counts were right.
- The run report's header printed "null" when a run had no outcome yet.
- Government formation in a council of other than five seats. The slate check demanded exactly one
  office per delegate, and there are always five offices, so with six to twelve delegates (or fewer
  than five) no complete slate could pass: every proposer was sent to a repair it could not satisfy,
  and a council whose delegates all sent the same valid slate formed no government. A complete slate
  now means five different holders in a larger council and every delegate seated in a smaller one;
  the formation and repair prompts state the rule for the council's size; and the formation prose
  reader recognises seat letters past E, while a bare "I" stays the speaker. A five-seat council sends
  exactly the prompts it sent before.
- From an independent review of the token features (details in the backlog, T19-T24): a quiet month
  no longer drops foreign messages, private dispatches or answers addressed to the council, nor re-dates
  the delegates' notebooks; malformed `read_next_month` / `wake_if` answers are dropped instead of
  ending the run; the foreign-cabinet model is included in the seat check; call ids stay unique across a
  resume; and foreign messages always arrive in full under briefing on demand.

Measured results and their limits are in [docs/TOKEN_EFFICIENCY.md](docs/TOKEN_EFFICIENCY.md).

## engine-5 (2026-10-06)

The first public release: the simulator, engine version 5, with its development history, under the
Apache License 2.0.
