# Council contestation analysis

Karamaniya does not need an artificial dissent quota. A forced no vote would change the thing
being measured. The engine instead records three separate phenomena:

1. Unanimity — every eligible voter selected the same resolved outcome.
2. Strong consensus — the binary votes have a dominant side, even when one or more members abstain.
3. Late vote change — a delegate's Phase-1B provisional stance differs from the final counted vote.

These are descriptive measurements, not targets.

A high unanimity rate is not automatically a bug. It becomes a research concern when it is
persistent across difficult, cost-bearing decisions, especially when binary stance changes are
frequent and predominantly move toward the majority.

The research workflow should compare at least:
- baseline prompts versus a structured contestation-review prompt;
- homogeneous versus heterogeneous councils;
- low-conflict and high-conflict scenarios;
- multiple seeds with the same world initialisation.

The structured review should ask each delegate to identify the strongest cost or objection from
its own mandate without requiring a dissent. The key outcome is whether disagreement appears
under controlled conditions without being scripted into the answer.
