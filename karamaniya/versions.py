"""Version stamps written into every run, so later comparisons know what produced a run."""
from __future__ import annotations

AGENT_ARCHITECTURE = 2      # 0 legacy, 1 psychology + canonical state, 2 full deliberation architecture
# 6 corrects what engine 5 told the delegates: the founding dossier gave the election as month 17
# (counted from 0) beside "Month 18" everywhere else; trade deals were shown ending a month early;
# six settings an office can order never showed their current value; the system prompt described
# two phases and left out the response round, called notes a delegate's only memory and fixed the
# message quota at 3 whatever the run set; deferral, emergency measures, forecasts and belief ids
# were offered without being explained; one prompt printed two different figures for output; and a
# forecast confidence written in percent was recorded as certainty. The "unobserved" framing is new,
# and "immersive" no longer says "simulation" in the survey, the rules or the briefing.
# 7: a delegate's opening prompt lists its own motions the engine refused to table the month before,
# with the reason. The reason was shown for the rest of that month only, and delegates moved the same
# unknown lever, or asked for an audit inside its cooldown, again the next month.
# 8: a policy motion whose text says "from A% to B%" while its value sets another figure is sent back
# for repair, with the two figures, like a foreign motion whose words and action disagree.
AGENT_PROMPT = 8
PSYCHOLOGY = 4
# 3 added the causal world model: output gap and potential output, Okun unemployment, hybrid
# inflation expectations, lagged exchange-rate pass-through, and the lagged fiscal impulse. A run
# paused under engine 2 and resumed under 3 would mix two different economies in one history, so
# the version is stamped on every run and older runs keep the version they were produced with.
# 4 was reached twice, on two lines of work, before they were joined. One line fixed fiscal conversion,
# credit exposure, expiry dates and capped development (it stamped AGENT_PROMPT 5, PSYCHOLOGY 4 and
# ERROR_TAXONOMY 2). The other changed what the engine does with the same recorded model answers, not the
# economy: a vote-intent ask-back adopts only the ballot it asked about (it used to overwrite the whole
# decision, orders included), a foreign motion naming an act its own target cannot receive is held at
# tabling rather than voted on, and a reserve floor on an arrears payment now reaches execution and limits
# the payment (min(requested, reserves - floor)): a co-sponsor's safeguard is kept when its motion is
# folded in, a floor written as "50" is 50 million, a floor the winning coalition asked for in the
# response round binds the motion it voted through, and a floor limits the payment instead of holding the
# whole motion (it stamped AGENT_PROMPT 4, PSYCHOLOGY 3 and ERROR_TAXONOMY 1). A run stamped 4 came from
# one of the two, and its other stamps say which. 5 is both together. A run resumed across a change of
# engine version is marked, by the config stamp and the manifest stamp disagreeing, rather than mixing the
# behaviours quietly.
# 6: Veleria's red line on a bilateral split of the Union counts only a grain deal the government made
# or extended. In engine 5 the transition arrangement it inherited crossed the line in the first month
# of every run, before the council had met, and Veleria escalated against something nobody had done.
# 7 changes what the engine does with two kinds of answer, found in Month 1 of the first engine-6 run
# with real models; the prompts are engine 6's. A setting written with its office run in front
# (`treasury_imports`) is that office's setting, as `treasury:imports` already was: it was an unknown
# lever, and the motion was discarded. A conditional vote whose condition still does not match its
# stated reason after the repair takes the fallback the delegate set (if_unmet, no before abstain),
# where engine 6 counted it as an abstention whatever the delegate had asked for.
# 8: a constitution setting moved as a policy (`set_policy highlands_status = cultural`) is the
# constitution motion it can only mean; it was an unknown lever, and the motion was discarded.
# 9: a safeguard the voted text states and the motion's conditions omit (an amendment rewrote the
# text and left the conditions) binds as well: the motion runs when its own conditions and the
# text's are all met. Engine 8 refused to run it at all, even with the text's safeguard met.
# 10: a standing treaty in force (the non-aggression pact, the League alliance) is not proposed again;
# a policy motion whose text moves a share setting "from A% to B%" while it sets another figure goes
# back to its proposer; a storm's damage is in the state when the storm is announced, where it used
# to land after the council's first answer to it, so relief voted on the news ran on no damage.
WORLD_ENGINE = 10
EVENT_GENERATOR = 2
ANALYTICS = 1
PROVENANCE = 1
# 2 added the refusal codes for actions, motions, audits and foreign deals. 3 adds VOTE_INTENT_MISMATCH and
# CONDITION_EXECUTION_MISMATCH, which the other line had already added without a bump.
ERROR_TAXONOMY = 3


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
