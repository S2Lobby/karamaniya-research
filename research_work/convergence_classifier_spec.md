# Convergence Classifier Spec — Task B (HEAD-only)

Source: `karamaniya/convergence.py` at HEAD `e4c27f77`.
Scope: HEAD `karamaniya/convergence.py` ONLY. Every rule cites `convergence.py:line`.

## 0. Implementation type

Deterministic, rule-based, post-hoc audit classifier. Derives a unanimity explanation from the existing audit trail; never feeds back into the simulation.

- Purpose: distinguish 5-0s with different histories (`convergence.py:1-6`).
- Inputs: private openings, response-round stances/revisions, motions + status flags, demands, final votes (`convergence.py:8-11`).
- Legacy policy: missing field = `unknown`, never guessed (`convergence.py:10-11`).
- No-effect guarantee: never shown to delegates, never changes simulation (`convergence.py:13`).

## 1. Precedence (single-return chain)

Entry: `classify_unanimous(record, motion)` (`convergence.py:478-482`).

Total order `DUPLICATE_CONSOLIDATION > NEGOTIATED_CONVERGENCE > CONDITIONAL_COMPROMISE > INITIAL_CONSENSUS > UNKNOWN`:

1. `DUPLICATE_CONSOLIDATION` if `duplicates` non-empty (`convergence.py:507-510`).
2. Else `NEGOTIATED_CONVERGENCE` if `contested_withdrawn or amended or opposed or moved` (`convergence.py:511-522`).
3. Else `CONDITIONAL_COMPROMISE` if `conditions` non-empty (`convergence.py:523-526`).
4. Else `INITIAL_CONSENSUS` only if `not siblings` AND private-open test passes (`convergence.py:529-544`).
5. Else `UNKNOWN` (`convergence.py:545-546`).

Each branch `return`s one `{classification, confidence, evidence, because}` dict, so multi-category output is structurally impossible: one motion yields exactly one return.

## 2. Evidence per class

Common dict built before branching (`convergence.py:500-506`): `outcome` from `motion.get(passed)` (`convergence.py:500`); `family`, `family_size` (`convergence.py:501`); `withdrawn_siblings`, `duplicate_siblings`, `contested_withdrawn` (`convergence.py:502-504`); `opposed_in_response_round`, `position_changes_on_this_motion` (`convergence.py:505`); `amended`, `conditional_votes` (`convergence.py:506`). Only the initial-consensus path appends `opening_positions_read`, `opening_agreement` (`convergence.py:538-539`).

`because`: duplicate fixed string (`convergence.py:510`); negotiated joined bits for withdrawn-competitor / amended / N-opposed / M-moved (`convergence.py:512-522`); conditional `N delegate(s) supported it only under a stated condition` (`convergence.py:526`); initial `N delegate(s) privately supported/opposed it before discussion, no one took the other side, and no alternative was tabled` (`convergence.py:543-544`).

Confidence: `structured` for the four named classes (`convergence.py:508,521,524,541`); `low` for `UNKNOWN` (`convergence.py:545`).

## 3. VOTED_STATES denominator

- `VOTED_STATES = (PASSED, DEFEATED, EXECUTION_BLOCKED, PASSED_CONDITIONALLY, EXECUTION_PENDING)` (`convergence.py:52`).
- Rationale: execution-blocked / conditional / pending still reached a vote; politics happened even if the world did not change (`convergence.py:48-51`).
- Month scope: `voted` filtered by `VOTED_STATES` (`convergence.py:567`); `unanimous` where `set(_counted(m)) in ({"yes"},{"no"})` (`convergence.py:568`).
- `_counted` keeps only `yes`/`no` over `eligible_voters` else voters present (`convergence.py:146-150`).
- Rate `unanimous/voted` (`convergence.py:612`); run rollup `unanimous_votes/votes_cast` (`convergence.py:769-770`). Only `unanimous` motions reach `classify_unanimous` (`convergence.py:604,638-639`).

## 4. structured_change filter

- `c.get(from_basis) in (tabled_motion, response_round)` (`convergence.py:300-307`); private-position inference alone must not make negotiated convergence (`convergence.py:301-305`).
- Used as `moved = [c ... if structured_change(c)]` (`convergence.py:497-498`); consumed by negotiated branch (`convergence.py:511,519-520`).
- Changes built response-stage `initial != response` (`convergence.py:401-404`) and final-stage `anchor != vote` unless `response == conditional` (`convergence.py:406-411`); conditional resolving as expected is a condition met, not a mind-change (`convergence.py:406-407`).
- Reasons are structured-only, never prose-guessed (`convergence.py:423-424`): amendment codes (`convergence.py:429-433`), `DEMAND_BY_OTHER` (`convergence.py:434-437`), `COMPETING_MOTION_WITHDRAWN` (`convergence.py:438-444`), `OWN_CONDITIONAL_VOTE` (`convergence.py:445-447`), `STATED_RESPONSE` capped 300 chars (`convergence.py:449-450`).

## 5. _opening sources

- Strong source: same-family tabled motion = opening offer, `stance=yes, basis=tabled_motion` (`convergence.py:385-391`); stated as strongest evidence (`convergence.py:348-349`).
- Weak fallback: `_opening` reads `pre_positions[mid]` via `analytics.initial_stance`, labelled `basis=private_position`, `raw=support/oppose/unknown` (`convergence.py:345-360`).
- Detail prefers `preferred_policy`/`would_support`, truncated 300 chars (`convergence.py:357,360`).
- Normalisation via `STANCE_TO_VOTE` plus `yes/no/abstain/conditional` (`convergence.py:73,336-342`).

## 6. Family / duplicate rules

- Family key (`convergence.py:218-233`): `settle_arrears -> (settle_arrears,)` ignoring funding mechanism (`convergence.py:226-228`); `set_policy/diplomacy/emergency_measure/amend -> (kind, subject.casefold())` (`convergence.py:229-233`). Only genuine alternatives share a family (`convergence.py:221-223`).
- Procedural motions excluded (`convergence.py:264`).
- Amend clustering: `len(shared)>=6, Jaccard>=0.20, anchors>=2` (`convergence.py:244-255`), best-match link (`convergence.py:256-258`), union-find transitive closure (`convergence.py:271-297`).
- `family_groups` drops singletons: family of one is not a contest (`convergence.py:310-320`).
- Classifier siblings: same family, different id, only if `key` exists (`convergence.py:484-486`); statuses via `motion_status` (`convergence.py:488`); `withdrawn = status in (WITHDRAWN, SUPERSEDED)` (`convergence.py:489`).
- `_is_duplicate` (`convergence.py:461-475`): exact `(type, subject, value)` with non-empty subject/value (`convergence.py:467-471`); `amend+amend` by `SequenceMatcher>0.7` (`convergence.py:472-474`). Same value but different mechanism is not a duplicate (`convergence.py:464-465`).
- Split `duplicates = withdrawn if _is_duplicate`, `contested_withdrawn = withdrawn - duplicates` (`convergence.py:490-491`).

## 7. UNKNOWN cases

- No-siblings + insufficient opens: `if not siblings` gate (`convergence.py:529`); `agree=support if passed else oppose` (`convergence.py:532`); `opens` over voters minus proposer (`convergence.py:534-535`); `sure` vs `against` split (`convergence.py:536-537`); need `sure and not against` else `UNKNOWN` (`convergence.py:540-545`). No data is not consensus (`convergence.py:527-528`).
- Sibling families never `INITIAL_CONSENSUS`: the `if not siblings` guard skips the branch for any `family_size>1` (`convergence.py:529`).
- Conditional masked by earlier classes: `conditions = motion.get(conditional_votes)` (`convergence.py:499`) is reachable only after duplicate and negotiated tests fail (`convergence.py:507-523`).

## 8. Failure modes (code paths)

- Proposer auto-support masking dissent: tabled sibling forces `initial=yes` (`convergence.py:388-391`); proposer excluded from `opens` (`convergence.py:534-535`).
- Structured-only blindness to prose motives: `private_position` basis rejected by `structured_change` (`convergence.py:307`); `_reasons` never guessed from prose (`convergence.py:424`); only prose carrier is `STATED_RESPONSE` at response stage (`convergence.py:449-450`).
- Conditional masking: `conditions` checked third (`convergence.py:523`); `conditional -> vote` transition suppresses a `changes` entry (`convergence.py:408`).
- Unanimous-but-unclassified legacy gaps: missing fields yield `UNKNOWN/low` (`convergence.py:10-11,545-546`); `EXECUTION_BLOCKED_CONDITION` folded to `EXECUTION_BLOCKED` for legacy readers (`convergence.py:60-61,116-119`).
- `DUPLICATE_CONSOLIDATION` never emitted (reported over 112 runs): needs withdrawn same-family motion passing whole-triple or amend-similarity test (`convergence.py:489-490,461-475`); near-duplicates route to negotiated (`convergence.py:464-465,491,511-514`).

## 9. Strongest ambiguity

Precedence-induced masking of `CONDITIONAL_COMPROMISE` by `NEGOTIATED_CONVERGENCE`, compounded by proposer auto-support. A motion with both a stated condition and any prior opposition/amendment/contested withdrawal can only emit negotiated (`convergence.py:511-526`); the condition survives only in `evidence.conditional_votes` (`convergence.py:506`) while the `because` string loses it. Proposer exclusion (`convergence.py:534-535`) makes the initial-consensus denominator `voters-1`, so dissent detection hinges on weak `private_position` reads.

