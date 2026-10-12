# Karamaniya

**Karamaniya** is a persistent multi-agent AI evaluation environment designed to study **long-horizon behavior under institutional constraints**.

Five language-model agents govern the same evolving fictional country while occupying different offices, receiving asymmetric information, communicating privately, negotiating, voting, issuing structured actions, and facing path-dependent consequences.

The project is intended as **measurement science for persistent multi-agent AI systems**, not as a predictor of real-world politics.

---

## Research motivation

Most LLM evaluations focus on isolated prompts, short tasks, or final outcomes.

Karamaniya instead studies what happens when agents must operate over long trajectories with:

- persistent memory,
- institutional roles,
- asymmetric information,
- public and private communication,
- negotiation and revision,
- structured actions,
- and path-dependent consequences.

The central question is:

> **Which apparent long-horizon behavioral differences are reproducible properties of the models, and which are caused by role assignment, information access, interaction structure, or artifacts of the evaluation harness?**

A secondary question is whether final outcomes such as unanimous votes can hide substantial disagreement earlier in the decision trajectory.

---

## System design

Karamaniya separates **model decisions** from **world consequences**.

### Agent layer

Five LLM agents occupy different institutional roles and can:

- form independent positions,
- send private messages,
- negotiate,
- table motions,
- vote,
- revise positions,
- issue role-specific directives,
- maintain persistent notes and commitments.

### Causal world engine

A separate simulation engine updates the canonical world state after agent decisions.

It tracks variables such as:

- approval,
- inflation,
- food supply,
- unemployment,
- public unrest,
- military readiness,
- diplomatic relations,
- political stability,
- elections,
- and institutional continuity.

This separation is designed to make it possible to distinguish:

```text
model action
        ↓
validated structured action
        ↓
causal world-engine consequence
        ↓
next observation
```

rather than allowing the language model itself to invent the consequences of its actions.

---

### Code

The simulator itself is in this repository: the [`karamaniya/`](karamaniya/) package, its tests in
[`tests/`](tests/) and run-analysis scripts in [`tools/`](tools/). [ENGINE.md](ENGINE.md) explains how to
run it, how to choose the five models, and what every run folder records.

```bash
python -m karamaniya gui                      # the control room, in your browser
python -m unittest discover -s tests -t .     # the test suite
```

It needs Python 3.12 or newer and otherwise only the standard library; `pip install -r requirements.txt`
adds the `anthropic` package, which only seats calling the Anthropic API directly use.


## License

The source code (`karamaniya/`, `tests/`, `tools/` and the example council files) is released under the
[Apache License 2.0](LICENSE). The paper, the figures and the written research materials are not covered
by that license.

---
