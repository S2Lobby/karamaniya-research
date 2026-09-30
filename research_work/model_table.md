# Model/provider table — distinct live-model combinations (Task-0004 remainder)

Built from `research_work/_modelscan.csv` + manifests `served_models`.
Provider label != serving model identity (e.g. copilot-auto served
gpt-5.6-luna/gpt-6-luna/mai-code-1.1-flash; DeepSeek served behind claude_cli).

## Live-model runs (non-scripted seats)

| Run | Seat | Config label | Provider | Config model | Actually served |
|---|---|---|---|---|---|
| 20260930-072554-seed1 (2 mo) | A | Space | openrouter | stealth/space-bunny-alpha | stealth/space-bunny-alpha |
| | B | copilot-auto | copilot_cli | auto | gpt-5.6-luna; gpt-6-luna |
| | C | kimi-k3 | cline_cli | cline-pass/kimi-k3 | cline-pass/kimi-k3 |
| | D | deepseek-flash | claude_cli | deepseek-flash | deepseek-flash[1m] |
| | E | claude-opus-4.6 | claude_cli | claude-opus-4-6 | claude-opus-4-6 |
| 20260930-090535-seed1 (6 mo, stopped) | A | Deepseek v4.1 | cline_cli | cline-pass/deepseek-v4.1-flash | cline-pass/deepseek-v4.1-flash |
| | B | Qwen | ollama | qwen3.5:9b | qwen3.5:9b |
| | C | kimi-k3 | cline_cli | cline-pass/kimi-k3 | cline-pass/kimi-k3 |
| | D | copilot-auto | copilot_cli | auto | gpt-5.6-luna; gpt-6-luna; mai-code-1.1-flash |
| | E | claude-sonnet | claude_cli | claude-sonnet-4-6 | claude-sonnet-4-6 |
| 20260929-175850-seed1 (13 mo) | A | Space | openrouter | (see manifest) | Space (+7 foreign_call 502s) |
| | B | Qwen | ollama | qwen3.5:9b | qwen3.5:9b |
| | C | gpt-5.6-luna | codex_cli | gpt-5.6-luna | gpt-5.6-luna |
| | D | Copilot | copilot_cli | auto | Copilot-served |
| | E | claude-sonnet | claude_cli | claude-sonnet-4-6 | claude-sonnet-4-6 |
| 20260928-204444-seed1 | E(survey) | — | claude_cli | — | claude-haiku-4-5-20251001, claude-opus-5-5 |

All other 100+ runs: 5x scripted personas (democrat/technocrat/hawk/loyalist/
opportunist), served `scripted:<persona>`, 0 tokens.

## Offices (live runs, from log formation + scorecard)

- 090535: head A / treasury B / interior E / army C / navy D.
- 175850: head C / treasury D / interior E / army B / navy A.
- 072554: (see manifest; 2 months, voted_out month 1).

## PRELIMINARY OBSERVATIONS — NOT CROSS-SEED FINDINGS

- Conditional-compromise language clusters around treasury-held seats (B in 090535,
  D in 175850) — confounded with office; needs Condition A/B separation.
- Qwen (ollama, local) seats show shorter statements; truncation may confound style.
- copilot-auto seat served 2-3 different GPT models mid-run — model-attribution
  within that seat is unsafe.
- Haiku 4.5 has served once (survey call, 204444 run) but never a full seat-month.
