# Changelog

What changed in the simulator between published versions. Every run folder records the versions that
produced it (`manifest.json`, `karamaniya/versions.py`), and `docs/ENGINEERING_BACKLOG.md` keeps the
task-by-task record with the tests behind each item.

## Since engine-6

World engine 7 (`WORLD_ENGINE` 7). The prompts are engine 6's (`AGENT_PROMPT` 6; the prompt freeze is
unchanged), but the engine does two things differently with the same answers, so runs made before keep
their engine-6 stamp and a run resumed across the change is marked as mixed. Both came from Month 1 of
the first engine-6 run with real models (`docs/ENGINEERING_BACKLOG.md`, T34-T35):

- A setting written with its office run in front (`treasury_imports`, `Treasury imports`) is that
  office's setting, as `treasury:imports` already was. It was an unknown lever, and a motion setting
  imports to max was discarded.
- A conditional vote whose condition still does not match its stated reason after the repair takes the
  fallback the delegate set for an unmet condition (`if_unmet`, no before abstain). Engine 6 counted it
  as an abstention whatever the delegate had asked for, and called the safeguard "untestable" when the
  condition tested something the reason never named. In that run a delegate who had opposed the motion
  in public, with no as its fallback, was recorded as abstaining.

Connector fixes (details and tests: `docs/ENGINEERING_BACKLOG.md`, T32-T33)

- A Gemini seat (`antigravity_cli`) could not take part. Gemini accepts an enum value only as a non-empty
  string, and the CLI forwards numbers as empty strings, so the formation proposal (where "" leaves an
  office empty) and every monthly decision (forecast horizons 3, 6 and 12) were rejected with
  INVALID_ARGUMENT before the model saw the prompt, and the run paused. The connector now sends such a
  value as a word or as its digits and maps the answer back. Every seat's prompts are unchanged, and a
  schema Gemini already accepted (survey, founding diagnosis, formation vote, session, revision) is sent
  byte for byte as before.
- An Antigravity call could end with no answer when the model reached for one of the CLI's own tools,
  which headless mode denies (the CLI has no switch for them). It was asked once more with a note that
  the answer could not be read; it is now sent again unchanged, as after a dropped connection.

## engine-6 (2026-10-08)

`AGENT_PROMPT` 6 and `WORLD_ENGINE` 6. An audit of the prompts as a default run sends them, not as the code
writes them, found errors in what the delegates were told and a foreign rule that fired before the council
had met. A default run therefore no longer sends what the `engine-5` tag sends:
`tests/fixtures/prompt_freeze_engine6.json` holds the new prompts, and runs made before keep their engine-5
stamps, which `manifest.divergences()` names. Details and tests: `docs/ENGINEERING_BACKLOG.md`, T25-T31.

What the delegates were told

- The founding dossier gave the election as `"election_month": 17` (the engine counts months from 0)
  beside "Month 18" in every other prompt; it now reads "Month 18".
- Trade deals were shown ending a month early: the inherited Dorsania arrangement read "active through
  Month 5" and runs through Month 6.
- CURRENT SETTINGS left out six settings an office can order: ownership, import_cap, planning, amnesty,
  training_intensity and mobilization.
- The system prompt described two phases and left out the response round, called a delegate's notes its
  only memory, and said 3 private messages a month whatever `dm_per_turn` was.
- Deferral (`defer_motion`), emergency measures (`emergency_measure`), forecasts and the belief ids that
  `belief_updates` names were offered without being explained.
- One prompt printed the true output in the canonical block and a noisy estimate in the briefing; both
  now print the published figure.
- Minor: ".;" and ".." in the inherited strengths and commitments, "annualized over 1 months", and
  unrounded floats such as 0.7666000000000001 in the foreign cabinets' context.

What the engine did

- Veleria's red line on a bilateral split of the Union counted the grain arrangement the government
  inherited at independence, so it was crossed in the first month of every run and Veleria escalated
  before the council had met. Only a deal the government makes or extends counts now.
- A forecast's confidence written in percent ("75") was clamped to certainty and later scored as
  overconfidence, and its threshold was not read in the units conditions use. Both are read as a
  condition's are now.

Framing

- New: `framing = "unobserved"`, the immersive framing with nothing that tells the delegates their answers
  are studied or kept for comparison. The principles declaration is public without "later actions can be
  compared with it", the private opening position is private without "stored for later comparison", and
  casualty figures reach the government as reports and estimates without the research ledger. The survey
  keeps its questions.
- `framing = "immersive"` no longer says "simulation": its survey opened with "Before the simulation
  starts", and its rules and briefing said the month "is simulated" and the units "are not real-world
  dollars".

## Between engine-5 and engine 6

The world engine, the agent prompts and the psychology were unchanged (`WORLD_ENGINE` 5, `AGENT_PROMPT` 5,
`PSYCHOLOGY` 4): a run with default settings sent byte for byte the prompts the `engine-5` tag sends. What
was new is measurement, and features a run must turn on.

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
