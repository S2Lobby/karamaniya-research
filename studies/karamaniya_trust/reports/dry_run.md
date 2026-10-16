# Karamaniya trust study: dry run

Council: council.scripted.toml (scripted seats: no model, no key)
Seed 4201, 2 months, status: finished.

Seats: A scripted-technocrat, B scripted-hawk, C scripted-loyalist, D scripted-democrat, E scripted-opportunist

| step | approval | inflation (yoy) | unrest | food ratio | army | active | exits | motions voted | refused | invalid rate | mismatch rate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 0.466 | 0.000 | 0.120 | 1.000 | 28,000 | 5 | 0 | 0 | 0 | 0.000 | 0.000 |
| 1 | 0.465 | 0.000 | 0.125 | 0.995 | 38,000 | 5 | 0 | 1 | 0 | 0.000 | 0.000 |
| 2 | 0.464 | -0.022 | 0.130 | 0.996 | 37,996 | 5 | 0 | 0 | 0 | 0.000 | 0.000 |

Steps 3-6 are past the legacy end and run no month (month_ran 0 in metrics_history.json).

Parity with the legacy loop (new_run, same seed): every month equal: yes (2/2 months, legacy 2, wrapped 2); final world equal: yes.
Outcome: After 2 months, the Provisional Government of Karamaniya still governs an independent Karamaniya.
