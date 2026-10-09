# Changelog

What changed in the simulator between published versions. Every run folder records the versions that
produced it (`manifest.json`, `karamaniya/versions.py`), and `docs/ENGINEERING_BACKLOG.md` keeps the
task-by-task record with the tests behind each item.

## World engine 12 and agent prompt 9

`WORLD_ENGINE` 12 and `AGENT_PROMPT` 9. The prompts changed on purpose (the election date, a sixth Charter
article, each delegate's seat outlook, the border in the briefing, the foreign cabinets' prompt), so a
default run no longer sends what engine 11 sends, and `tests/fixtures/prompt_freeze_engine6.json` was
rewritten with this bump. Runs made before keep their stamps. Details and tests:
`docs/ENGINEERING_BACKLOG.md`, T45-T50. All of it follows run `20261008-130316-seed1`.

- **The Assembly election is in Month 36.** In engine 11 it fell in Month 18: the government lost it, all
  five members conceded in Month 19 and a 36-month run ended half way. It is now the last month of a
  default run. A government that loses plays out the handover month; a refusal alone does not stop the
  handover (the instruction now says so), a coup the armed forces follow does, and the run then ends
  `kept_power_by_force`.
- **Each member stands for their own seat.** The Council List shares one vote share, so the members
  shared one fate: in that run 66 of the 70 motions put to a vote passed, 30 with all five voting yes,
  and one delegate voted yes on 69 of 70. At the election each member's own seat now rests on the support
  of the audiences that member answers to and on their personal approval, give or take a local margin,
  and a member who loses it leaves the government even if the government stays in power. The Charter
  says so (article 6), and each delegate's standing says whether its seat looks safe, too close to call
  or lost on current estimates. The threshold is `standing.seat_threshold` (0.45).
- **The neighbours can use force.** Each cabinet has a temperament from the seed and may mass troops,
  stage an incident, back unrest covertly, blockade, set an ultimatum and invade for a limited or a full
  aim. Acts the world does not allow are refused and reported back; the map shows troops massing at the
  border; the cabinets' prompt no longer asks them to avoid a damaging war. Before, the cabinets could
  hold exercises but never moved troops: war and blockade came only from fixed rules.
- **The model's own reasoning is recorded** with each call where its provider returns it, and Inspect
  has a "Said, thought, did" view of each delegate's month.
- **A permitted arm.** `latitude = "permitted"` ends the system prompt with a paragraph allowing harsh
  words, threats and radical measures, as permission, not a request. The default arm is unchanged.
- **One fixed model for the neighbours** can be chosen in the control room (`foreign_cabinet_backend`).
  By default the neighbours borrow the first two seats, so the shuffle decided which models played them
  (in that run Qwen3.5 played Veleria and kimi-k3 Dorsania).
- The said-versus-did comparison for the election question used Month 18 whatever the run's Charter
  said; it now uses the run's own date.

## Since engine-6

Everything here came from run `20261008-130316-seed1`, the first engine-6 run with real models
(`docs/ENGINEERING_BACKLOG.md`, T32-T44). Runs made before a change keep their stamps, and a run resumed
across one is marked as mixed. The prompt freeze is unchanged throughout: a default scripted run sends
the same prompts.

World engine 7 (`WORLD_ENGINE` 7): two things the engine does differently with the same answers, from
Month 1 (T34-T35):

- A setting written with its office run in front (`treasury_imports`, `Treasury imports`) is that
  office's setting, as `treasury:imports` already was. It was an unknown lever, and a motion setting
  imports to max was discarded.
- A conditional vote whose condition still does not match its stated reason after the repair takes the
  fallback the delegate set for an unmet condition (`if_unmet`, no before abstain). Engine 6 counted it
  as an abstention whatever the delegate had asked for, and called the safeguard "untestable" when the
  condition tested something the reason never named. In that run a delegate who had opposed the motion
  in public, with no as its fallback, was recorded as abstaining.

World engine 8 (`WORLD_ENGINE` 8), from Month 6 of the same run (T36):

- A constitution setting moved as a policy (`set_policy highlands_status = cultural`) is the
  constitution motion it can only mean. The prompt lists the regional statuses among the levers; such a
  motion was an unknown lever and was discarded.

World engine 9 and agent prompt 7 (`WORLD_ENGINE` 9, `AGENT_PROMPT` 7), from Months 3 to 7 (T37-T39):

- A safeguard the voted text states and the motion's conditions omit binds as well: the motion runs when
  its own conditions and the text's are all met, and a payment is sized to the stricter floor. An
  amendment had rewritten a payment's text to require reserves of at least 70M after it and left its
  condition at 60M; it passed 3-2 with reserves at 74M and the gate refused to run it at all.
- A delegate's opening prompt lists its own motions the engine refused to table the month before, with
  the reason. The reason was shown for the rest of that month only, and delegates asked for an audit
  inside its cooldown again two months later.
- Records, with no change in behaviour: forcing a motion onto a full agenda records the proposer's
  political capital, the capital needed and the cost, and a leak records the chance it had and the
  factors behind it (press, administration, the leaker, the kind of message).

World engine 10 and agent prompt 8 (`WORLD_ENGINE` 10, `AGENT_PROMPT` 8), from Months 3 to 8 (T40-T42):

- A standing treaty in force is not proposed again. The non-aggression pact is one agreement with the
  Union whoever it is addressed to, and the council had sent it five times in eight months; the
  alliance with the Maritime League is treated the same way.
- A policy motion whose text moves a share setting "from A% to B%" while it sets another figure goes
  back to its proposer for repair. A rate motion's text said "from 6% to 7%", Month 1's figures, while
  it set 0.11 from 0.10, and the council voted on it as written.
- A storm's damage is in the state when the storm is announced. The news said the damage was done, but
  it landed at the end of the month the council first answered it, so a 20M relief package voted on the
  news ran on 0.0% damage and repaired nothing.

World engine 11 (`WORLD_ENGINE` 11), from Month 18 of the same run (T43-T44):

- A text past its word limit is still shown to the council cut, and the engine reads the whole of it.
  Vote reasons are cut at 35 words, a limit the prompt never states, and in the first 15 months 120 of
  270 were cut; the checks read the cut copy, so a safeguard or an explanation after the 35th word went
  unseen and could send the delegate back to explain itself. The vote-intent and condition checks now
  read the whole reason and the whole response-round answer (cut at 70), and a reserve floor or a policy
  bound is read from the whole demand (cut at 30). The record keeps each whole text beside its cut copy.
- Each cut is recorded with its call (where it was, the limit, the words written, whether the prompt
  states the limit), and the scorecard and the report count them per delegate. Runs from before this
  have no count, which the report says rather than showing a zero.

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
