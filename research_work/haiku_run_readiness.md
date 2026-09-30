# Haiku 4.5 run readiness — 2026-09-30

## 1. Seat check (`python -m karamaniya check council.haiku.toml`)
PASS — all 5 seats, served model `claude-haiku-4-5-20251001`:

```
OK  haiku-A                claude_cli   asked claude-haiku-4-5-20251001 answered by claude-haiku-4-5-20251001    4.3s $0.0000
OK  haiku-B                claude_cli   asked claude-haiku-4-5-20251001 answered by claude-haiku-4-5-20251001    4.0s $0.0000
OK  haiku-C                claude_cli   asked claude-haiku-4-5-20251001 answered by claude-haiku-4-5-20251001    4.0s $0.0000
OK  haiku-D                claude_cli   asked claude-haiku-4-5-20251001 answered by claude-haiku-4-5-20251001    4.0s $0.0000
OK  haiku-E                claude_cli   asked claude-haiku-4-5-20251001 answered by claude-haiku-4-5-20251001    4.0s $0.0000
```

## 2. Engine-behavior cleanliness
`git diff --stat` (tracked modifications):
```
tests/test_outstanding_patch2.py | 35 +++++++++++++++++++++++++++++++++++
1 file changed, 35 insertions(+)
```
No engine-behavior files modified. Untracked additions only: `council.haiku.toml` (new pilot config), `research_work/`, `tools/` probes/diagnostics. No run started by research assistant.

## 3. Exact run command (user runs this)
```
python -m karamaniya run council.haiku.toml
```
Pilot config: `council.haiku.toml` — months=6, seed=11, framing=simulation, founding=random/default, survey=true, max_cost_usd=0.0, dm_per_turn=3.

## 4. Seat -> model mapping
| seat | provider | asked | served (verified by check) |
|------|----------|-------|----------------------------|
| haiku-A | claude_cli | claude-haiku-4-5-20251001 | claude-haiku-4-5-20251001 |
| haiku-B | claude_cli | claude-haiku-4-5-20251001 | claude-haiku-4-5-20251001 |
| haiku-C | claude_cli | claude-haiku-4-5-20251001 | claude-haiku-4-5-20251001 |
| haiku-D | claude_cli | claude-haiku-4-5-20251001 | claude-haiku-4-5-20251001 |
| haiku-E | claude_cli | claude-haiku-4-5-20251001 | claude-haiku-4-5-20251001 |

Homogeneous Condition A baseline: 5x same model, offices assigned by formation vote, normal asymmetric info. Model id previously served in `runs/20260928-204444-seed1/survey.json:220`.

## 5. Pilot seed plan (6 months each)
1. seed 11 (current `council.haiku.toml`) → `python -m karamaniya run council.haiku.toml`
2. seed 12 → edit `seed = 12`, rerun same command
3. seed 13 → edit `seed = 13`, rerun same command
Extend to 12 months if stable. Then proceed to heterogeneous/mixed conditions per compute plan.
