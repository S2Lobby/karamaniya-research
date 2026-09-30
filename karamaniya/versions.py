"""Version stamps written into every run, so later comparisons know what produced a run."""
from __future__ import annotations

AGENT_ARCHITECTURE = 2      # 0 legacy, 1 psychology + canonical state, 2 full deliberation architecture
AGENT_PROMPT = 4
PSYCHOLOGY = 3
# 3 adds the causal world model: output gap and potential output, Okun unemployment, hybrid
# inflation expectations, lagged exchange-rate pass-through, and the lagged fiscal impulse. A run
# paused under engine 2 and resumed under 3 would mix two different economies in one history, so
# the version is stamped on every run and older runs keep the version they were produced with.
# 4 changes what the engine does with the same recorded model answers, not the economy: a vote-intent
# ask-back adopts only the ballot it asked about (it used to overwrite the whole decision, orders
# included), a foreign motion naming an act its own target cannot receive is held at tabling rather
# than voted on, and a reserve floor on an arrears payment now reaches execution and limits the payment
# (min(requested, reserves - floor)): a co-sponsor's safeguard is kept when its motion is folded in, a
# floor written as "50" is 50 million, a floor the winning coalition asked for in the response round
# binds the motion it voted through, and a floor limits the payment instead of holding the whole
# motion. A run resumed across the change is marked, by the config stamp and the manifest stamp
# disagreeing, rather than mixing the two behaviours quietly.
WORLD_ENGINE = 4
EVENT_GENERATOR = 2
ANALYTICS = 1
PROVENANCE = 1
ERROR_TAXONOMY = 1


def stamp(agent_architecture: int = AGENT_ARCHITECTURE) -> dict:
    """The architecture block stored in config.json and shown in reports."""
    legacy = agent_architecture < 2
    return {"agent": agent_architecture,
            "agent_prompt_version": 3 if legacy else AGENT_PROMPT,
            "psychology_version": 2 if legacy else PSYCHOLOGY,
            "world_engine_version": 1 if legacy else WORLD_ENGINE,
            "event_generator_version": 1 if legacy else EVENT_GENERATOR,
            "analytics_version": ANALYTICS,
            "label": ("legacy agent architecture" if agent_architecture == 0 else
                      "agent architecture v1" if agent_architecture == 1 else "agent architecture v2")}
