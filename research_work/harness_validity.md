# Harness validity: 16 failure classes
HEAD e4c27f7. Format: fix commit (full hash) + regression test + status + old-run impact.
1. Malformed formation slates: dd22cc4d729d4df704e68b6ef2270b766ba967c5 FIXED; tests/test_formation_slate.py:30-57; bijection slate.py:79-118; old runs: bad slate governed in 20260929-165029-seed1 per message.
2. Empty-response-as-abstention: 2e365f438ae62ef568dbc4347e8500caf4199be9 FIXED; test_formation_slate.py:260-301; answered flag council.py:117-122; old runs: empty replies filed as abstentions.
3. Prose/structured mismatch: dd22cc4 (formation prose) + e4c27f770aa2eb97354ccfd10957aa815fe56604 (motion conflict) FIXED; formation_slate.py:63-108 + motion_integrity.py:44-92; conflict() motion_actions.py:359; old runs: wrong acts reachable pre-fix, auditable via integrity.py:49.
4. Mutual withdrawal collision: 6c9685afe530d88427a5ab27d07eed5e8d221f37 FIXED; consolidation_memory_authority.py:39-90; resolve_mutual_withdrawals deliberation.py:307-365; old runs: agenda emptied (A+E farm case).
5. Stale future-self memory: 6c9685a + 4b2018db81818a00e53a7c7644718dd3328c5889 FIXED; consolidation tests 91-194; validate_notes memory.py:93-144 + outcome store council.py:63-74; old runs: false agreed-memory hardened.
6. Unauthorized office actions: 6c9685a FIXED; consolidation 210-243; LEVER_OFFICE/AUTHORITY politics.py:45-93; old runs: silent drops, now UNAUTHORIZED_OFFICE_ACTION.
7. Directive-bound ambiguity: 5880249521f4e02d94003d118e916aa403d9011f FIXED; directive_bounds.py:34-151; intersection politics.py:569-790; old runs: safe-by-accident exact reading.
8. Missing disaster vocabulary: 26f8e7f893bcf2faf9f1f2b000465e078263fd28 FIXED; disaster_relief.py:29-142; relief branch politics.py:527,870; old runs: 3 coastal-relief refusals in 20260930-090535-seed1.
9. Foreign-target ambiguity: e4c27f7 FIXED; outstanding_patch.py:32-76; FOREIGN_TARGET_MISMATCH motion_actions.py:359-374; old runs: protest misfiled as trade deal (motion_integrity.py:47).
10. Vote-intent mismatch: aeddd6d6ed944072afb03894b65bb40fe67d8467 FIXED (ask-back, no rewrite); vote_intent_memory_phase.py:24-62; council.py:43-57; old runs: 8/4659 bare reversals affected tallies.
11. Memory-phase mismatch: aeddd6d FIXED; vote_intent_memory_phase.py:63-87; memory.py:147-168; old runs: 2/5981 notes.
12. Unsupported facts: aeddd6d FIXED; vote_intent_memory_phase.py:88-115 + outstanding_patch2.py:101-109; memory.py:185-258; old runs: invented audits persisted as memory.
13. Directive/order mismatch: e4c27f7 (+6c9685a authority, 020fa3b quota context) FIXED; orders_vs_directives.py:26-56 + outstanding_patch2.py:110-139; politics.py:1292-1369; old runs: stale-order defiance misreads, now SUPERSEDED vs EXPLICIT_VIOLATION.
14. Repeated deals: e4c27f7 FIXED; outstanding_patch.py:98-99 + outstanding_patch2.py:32-49; deal_action_for politics.py:1078-1115; old runs: same agreement recreated, none in force.
15. Missing deferral: e4c27f7 FIXED; outstanding_patch2.py:50-68; defer branch politics.py:546-557 + apply 932-951; old runs: defer word read as illegal lever value.
16. Arrears gaps: 1a71343133b62cd9d74d680a488cbccf10725c13 + e8387878e917613f1b1013541935875f0451b430 + e4c27f7 (targeted settle) FIXED; fiscal_structure.py + review_regressions.py:46-191 + outstanding_patch2.py:69-100; economy.py:405-556; old runs: 12x months, dormant contractors; composition now reconciles.
