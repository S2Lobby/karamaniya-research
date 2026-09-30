# Primary endpoint + deliberation-vs-conformity (Tasks F + G)

## F. Primary endpoint: Trajectory Disagreement Index (TDI)

**TDI = P(initial material disagreement | final unanimous vote)**

- Numerator: unanimous votes (VOTED_STATES denominator, `convergence.py:52,567-568`)
  whose episode shows material initial disagreement: oppose stance, competing
  same-family motion, substantive amendment, or recorded demand before the vote.
- Denominator: all unanimous votes (yes/no counted only, `convergence.py:568`).
- Unit of analysis: one voted motion (one row of the blind/key CSVs).
- UNKNOWN: excluded from both (reported as rate alongside, not imputed).
- Conditional votes: CONDITIONAL_COMPROMISE counts as disagreement-present
  (support was bounded), but reported split: TDI_strict (exclude conditionals
  from numerator) + TDI_loose (include) — pre-register TDI_loose as primary
  since conditions are the compromise mechanism the paper studies.
- Why it answers the question: the paper claims final agreement hides divergent
  trajectories. TDI is exactly the fraction of 5-0s that hide one. Historical
  anchor (exploratory, NOT clean): 090535 run 11/14 non-initial classes imply
  TDI_loose ~= 0.79; 175850 run 22/29 imply ~= 0.76 — pilot must re-measure.
- Secondary/exploratory: per-class rates, position-change counts, conditional
  rate, minority-maintained, promise kept/broken, persuasion reasons, leak counts.

## G. Conformity vs deliberation: what logs can(not) say

Available motive evidence per revision (structured only):
- `analytics.persuasion[].likely_reasons`: concession / political_trade /
  new_evidence / relationship_trust / social_pressure / threat_change /
  unexplained (`analytics.py:88-108`). These map approximately:
  NEW_INFORMATION ~= new_evidence + threat_change; ARGUMENT_ACCEPTED ~= concession;
  CONDITIONAL_BARGAIN ~= political_trade + OWN_CONDITIONAL_VOTE; RECIPROCAL_CONCESSION
  ~= political_trade + favor_debts; MAJORITY_PRESSURE ~= social_pressure;
  PROCEDURAL_CONSOLIDATION ~= COMPETING_MOTION_WITHDRAWN; UNEXPLAINED_REVERSAL ~=
  unexplained; else UNKNOWN.
- Limits (explicit): reasons are heuristic tags, not stated motives; prose motive
  ("I accept because X") is stored only as STATED_RESPONSE text (<=300 chars,
  `convergence.py:449-450`) and vote_reasons (truncated `[cut]` in storage);
  no schema field asks WHY a delegate changed position. Do NOT infer motives
  beyond tags; report tag distribution + unexplained rate instead.
- Smallest logging change for clean runs: add optional `why_changed` free-text
  (<=200 chars) + `because_motion` id to the revision schema (`actions.py:718`
  normalize_revision empty-dict), surfaced in `positions().changes[].reasons`
  beside existing codes. No behavior change: informational field only.
- Verdict: current logs support a WEAK version (tag distribution over 7 buckets
  + unexplained share); the strong version (deliberative vs conformist mechanism)
  needs the `why_changed` field + human coding of the new blind column.
