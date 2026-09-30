# Human labeling guide — convergence classes (Task C)

Independent of the engine. Label each episode from the evidence columns only
(opening positions, response statements/stances, demands/amendments, withdrawals,
votes, reasons, conditions). When in doubt, use UNKNOWN.

## Categories

INITIAL_CONSENSUS:
All materially relevant opening positions already support the same substantive
outcome before bargaining. Response round contains no material objection,
no competing alternative, no amendment that changes substance, and no condition
that limits support.

NEGOTIATED_CONVERGENCE:
At least one material initial disagreement exists (oppose stance, competing
motion on the same family, substantive amendment, or recorded demand), and later
interaction (withdrawal, amendment, stated response, position change) produces a
common final position. The final vote is unanimous.

CONDITIONAL_COMPROMISE:
The unanimous outcome depends on explicit conditions: conditional votes,
binding execution conditions, reciprocal concessions ("I vote yes if X"),
or bounded support stated in vote reasons. If the condition were removed, the
rater judges the vote would plausibly not be unanimous.

NON_UNANIMOUS (control):
The final vote tally includes at least one yes and one no among counted votes.
Use for controls only; not an engine class.

UNKNOWN:
Evidence is insufficient or ambiguous: missing openings for most voters,
truncated statements that hide substance, procedural tangle (void/lapsed),
or genuine borderline between two categories above.

## Operational rules

MATERIAL DIFFERENCE: a disagreement about the substantive outcome (level, target,
timing, mechanism with different effects). Wording variants, different
justifications for the same outcome, or different funding labels with identical
amounts are NOT material.

NUMERIC BARGAINING: two tabled values for the same lever (e.g. 0.04 vs 0.05 cap)
are material. A final value between them, or adoption of one after withdrawal of
the other, is NEGOTIATED_CONVERGENCE unless support was explicitly conditional.

PROCEDURAL vs SUBSTANTIVE: disagreements about agenda order, deferral, or
formation procedure are not substantive. A deferral/withdrawal that avoids a vote
is not convergence; label UNKNOWN unless a later vote on substance is unanimous.

ABSTENTIONS: abstain is not support and not opposition. Unanimity in the engine
counts only yes/no (`convergence.py:568`); a 4-yes + 1-abstain tally is unanimous
by the code. As a human, note the abstention in comments; if the abstention
reflects substantive reservation, prefer CONDITIONAL_COMPROMISE or UNKNOWN.

SAME POLICY / DIFFERENT IMPLEMENTATION: if two motions share type+subject+value
but differ in mechanism (e.g. reserves vs bonds), they are different outcomes
(the engine agrees: `convergence.py:464-465`). Do not call consolidation of such
motions duplicate; judge convergence on whether the mechanism dispute was resolved.

MUTUAL WITHDRAWAL / CONSOLIDATION: two rivals withdrawn with no vote is NOT a
unanimous vote. If the CSV shows no tally, use UNKNOWN (or NON_UNANIMOUS if a
split vote exists elsewhere). Only label DUPLICATE_CONSOLIDATION-equivalent when
one survivor passes unanimously after a substantive duplicate is withdrawn; note
that the engine's exact-triple rule is stricter than this human rule by design.

CONDITIONS vs REASONS: a vote reason explaining why ("good for food security")
is not a condition. A condition states a contingency ("only if funded from
existing revenue", "subject to published rules"). When truncation (`[cut]`)
removes the operative clause, use UNKNOWN.

## Output

Fill column `human_label` with exactly one of:
INITIAL_CONSENSUS, NEGOTIATED_CONVERGENCE, CONDITIONAL_COMPROMISE,
NON_UNANIMOUS, UNKNOWN.
Optional `human_comment` (<=200 chars) for the decisive evidence.
Optional second rater column `human_label_2` for inter-rater agreement.
