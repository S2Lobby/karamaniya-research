# Architecture map — from code only (HEAD e4c27f770aa2eb97354ccfd10957aa815fe56604)
All claims cite karamaniya/<module>.py:line. No behaviour inferred from runs.

## 1. Agent loop (council.py)
- Month shape: `Council.run_month` dispatches v1/v2 (council.py:590-593); v2 full month is `_run_month_v2` (council.py:791).
- Loop order: formation gate (council.py:793-794), `engine.begin_month` clears events (engine.py:13-15; council.py:797), capacity/intel/brief (council.py:802-805), Phase 2-4 independent openings in seeded order (council.py:806-807,823-839), repair-back pass (council.py:936-938), agenda allocate (council.py:941), then resolution `_resolve_v2` (council.py:1360) → foreign cabinets (council.py:1160-1163) → `engine.step` (council.py:1164) → snapshot/social/integrity recorded (council.py:1165-1168) → month log (council.py:1172).
- Force-before-paper: coups resolved (council.py:1385-1389 via politics.py:1417 `resolve_coups`), then votes/conditionals (council.py:1390-1398 via deliberation.py:437), then motions, then office orders (council.py:1527-1532). Module doc states order (council.py:1-6).
- Transport rule: quota refusal raises `RunPaused` (council.py:303-304); no-answer-at-all (not refusal, not unreadable) raises `RunPaused` "could not be reached" (council.py:317-319) instead of abstaining. Every call logged with seat/provider/model/served_model (council.py:298-302).
- Formation: schema proposes slate+nominations+statement (council.py:427-436); `_formation_read` validates (council.py:80-128); one repair then out of vote (council.py:458-465); empty ballot → offices begin vacant (council.py:547-554); winner = most yes among passed slates, else per-office appointments (council.py:565-578).

## 2. World-state loop (engine.py / world.py)
- `engine.step` (engine.py:18-68): guards ended (engine.py:20); v2 pre-pass dilemmas/audits/operations/standing (engine.py:22-28); `director.act` (engine.py:29); `rivals.monthly` (engine.py:31); lag release `causality.apply_lags` (engine.py:37); `economy.produce` (engine.py:38), `trade_and_food` (engine.py:39), `fiscal` (engine.py:40), `money_and_prices` (engine.py:41); `forecasts.resolve_due` (engine.py:44); `military.update` (engine.py:45); `society.update` (engine.py:46); `politics.monthly_checks` (engine.py:47); `founding.advance` (engine.py:48); `snapshot` (engine.py:51); v2 post-pass (engine.py:55-60); survived-outcome (engine.py:62-66); `month += 1` (engine.py:68).
- State: dataclasses Region (world.py:72), Pop (world.py:96), Zone (world.py:117), Economy (world.py:130), Force (world.py:230), Military (world.py:241), Rival (world.py:261), Diplomacy (world.py:277), Member (world.py:311), Constitution (world.py:329), Policy (world.py:362), World (world.py:413); offices tuple (world.py:18); `new_world` constructor (world.py:591); `democracy_index` (world.py:673).
- Determinism: `rng_for(seed,month,tag)` sha256 stream (world.py:47-50). Snapshot builders: `v2_extras` (engine.py:75), `region_detail` (engine.py:107), `front_detail` (engine.py:131), `nation_detail` (engine.py:148), `snapshot` (engine.py:177).

## 3. Memory lifecycle (memory.py)
- Doctrine: summarized, salience-weighted, never transcript; canonical state block authoritative (memory.py:1-9). Salience table (memory.py:18-27); claim types PRIVATE_ESTIMATE/BELIEF vs PAST_EVENT (memory.py:30-31); protected kinds (memory.py:39-40).
- Write: `add` dedupes by (month,kind,first-80-chars), stamps observed_month, defaults phase to POST_EXECUTION (memory.py:47-68). `record_month` writes motion fates/votes/defiance from resolved record with POST_EXECUTION phase (memory.py:261-307,372).
- Checks (report, never rewrite): `validate_notes` → MEMORY_FINAL_STATE_MISMATCH on closed lever vocabulary (memory.py:93-144); `validate_note_phase` → MEMORY_PHASE_MISMATCH only for outcome-unknown language (memory.py:147-168); `unsupported_facts` → UNSUPPORTED_MEMORY_FACT vs audits actually held (memory.py:185-208); `fact_reference_errors` → FACT_REFERENCE_ERROR (memory.py:214-258). Wired in `_resolve_v2` + logged as memory_finding (council.py:1546-1553).
- Read: `context` returns ≤6 recent + relevance-retrieved older, with phase suffixes (memory.py:448-478). Decay `decay` (memory.py:435); private plans `set_strategy`/`strategy_text` (memory.py:481-517).

## 4. Council / bargaining lifecycle (deliberation.py + council.py)
- Doctrine: few substantive slots; procedural free; Head ranks; capital forcing; co-sponsorship; deferral not loss; conditional votes (deliberation.py:1-13). Procedural set (deliberation.py:23).
- Gate: clashing text/action held back + MOTION_ACTION_MISMATCH, one targeted repair via `_repair_motions` (council.py:857-868; council.py:1175-1233; mismatch codes AFTER_REPAIR/UNREPAIRED at council.py:1215,1231).
- Agenda: `allocate` carried → Head topics → forced → capital (deliberation.py:181-218); `carried_over` refreshes conditions, named defer-until measured from that month (deliberation.py:221-253); `coalesce_carried` renewals (deliberation.py:256); deferral applied at agenda write-up, changes WHEN not WHAT (council.py:944-948; politics.py:932-951).
- Collision: `resolve_mutual_withdrawals` restores convergence target, logs MUTUAL_WITHDRAWAL_COLLISION (deliberation.py:307-365).
- Votes: `resolve_conditionals` metric + motion-dependent, dependency order, unresolvable → abstain (deliberation.py:437-484); pre-vote metric snapshot `opening_values` (council.py:817).
## 5. Vote-directive-order-execution (politics.py)
- Franchise `passes` majority/two_thirds/unanimity/head_decides: politics.py:199-213.
- Gate `validate_motion_detail`: politics.py:417; disaster_relief branch 527; defer branch 546-557.
- Bounds: intersection rule politics.py:569; patterns 577-590; pre-bounds read-exact 695-698; allows 705-710; mismatch keeps voted value 723+.
- Execution: `set_lever` 1232; relief authorised-vs-carried-apart 870; deferral procedural only 932-951.
- Orders: all levers COUNCIL_DIRECTIVE_WITH_OFFICE_EXECUTION 59-71; `order_authority` 79-93; `apply_orders` fresh-superseded 1292-1319; bound-checked defiance 1364-1369; status codes 1273-1277; log wiring council.py:1538-1540.
- Coups/elections/shares/checks: 1417; 1547; 1591; 1639; 1655; 1690; 1521.
- Deals/arrears/constitution: DEAL_ACTIONS 1053-1054; `deal_action_for` 1078-1096; deal guard 1099-1115; arrears scope/funding 1127-1196; `settle_arrears_cost` 1035; `_constitution` 1199.

## 6. Economy/causal model (economy.py, causality.py, docs)
- Knobs: ALPHA/THETA/PRICE_SPEED/CREDIT/ADMIN economy.py:17-22; FOOD economy.py:24-25; loss 311-312; cap+cats 405-451; aliases 475-489.
- Flow: produce 94; trade_and_food 169; deliver 333-367; fiscal 571 (bills/accrue/settle/months/premium 418-556); money_and_prices 714; stats/trend/capacity/fx-launch 690-864.
- Causal: params 37-107; lags 118-154; impulse 161-198; regimes 225-242; credit/demand/money 290-327; fx/import/pressure 353-391; expectations 391-441; multiplier/Okun/FX/pass 441-539; trace 559-594.
- Doc: three rule kinds + monthly units + flow: CAUSAL_WORLD_MODEL.md:13-44; gap identity 55+.

## 7. Foreign actors (foreign.py/director.py/rivals.py)
- Constituencies foreign.py:26; coercive set 47; red lines 93-132; leadership 138-192; actors 192-310.
- Director prepare 38-47; act 50-57; cabinets 64-72; forces/league/weather 55-57,120-342.
- Cognition 329-597; positions 626; resolve_union 698; incidents/embargoes 775-817.
- Idempotency action_id 828-834; ledger 825-858; apply-once 861-866+; codes errors.py:52-54.
- Rivals budget/output/monthly/visible/observation rivals.py:26-144.

- Layers RAW..CANONICAL provenance.py:30-37; intent/hedge 54-66; raw-once 82-126; allegations 126-283.
- TAXONOMY errors.py:25-61; cap 500 at 63; record() 81-103; summary/since 106-123.
- Audit integrity.py:49-83; mark beside-run 107-133; replay_plan 144-171.

- Build manifest.py:101-147; streams 31-43; divergences/comparable 150-180; pre-first-call runner.py:157-158.
- Stamps ARCH 2/PROMPT 4/PSYCH 3/ENGINE 3 versions.py:4-11.
- RunStore storage.py:12-45; mark/rollback 50-62; monthly checkpoint runner.py:290-305; pre-Month-1 167-197; resume 203.

- A-E world-only post-formation scenarios.py:1-13,48-52; NAMES 19-20; setups 54-129.
- Seeds rng_for world.py:47-50; manifest streams manifest.py:125-131; map _build 216 + build_map 619; helpers 85-195.
## 10. Scenarios/seeds (scenarios.py/mapgen.py)
## 9. Reproducibility (manifest.py/versions.py/storage.py)
## 8. Provenance/integrity (provenance.py/integrity.py/errors.py)
