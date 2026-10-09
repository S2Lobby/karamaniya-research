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
# 9 goes with world engine 12. The Charter gives the Assembly election as Month 36, and where members
# stand for their own seats it has a sixth article saying so; each delegate's standing says where their
# own seat stands; the handover instruction says a refusal alone does not stop the handover and a coup
# can; the briefing shows foreign troops massed at the border and an ultimatum's terms. The foreign
# cabinets' system prompt no longer asks them to avoid a damaging war, gives each its temperament and
# says their acts are checked. A run in the "permitted" latitude arm ends the system prompt with
# prompts.LATITUDE_TEXT; the default arm has no such paragraph.
# 10 goes with world engine 13. The Army office's intelligence calls morale morale (engine 12 called it
# readiness and reported "good" beside a Union army four to five times ours) and adds the General Staff's
# net assessment of each front from the combat model; the navy's line says morale too. The decision
# prompt explains every office's operational settings in one line each, among them the new `contracts`
# setting (steering an office's contracts to one's allies), and asks the monthly forecast panel; the
# questionnaire has a tenth question, on steering contracts to save one's own seat. A run with seeded
# place names (world_names = "seeded") sends every prompt with the seed's names (naming.py).
AGENT_PROMPT = 10
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
# 11: a text past its word limit is still shown cut, and the engine reads the whole of it. The vote
# checks read a vote reason past 35 words and a response past 70, and a reserve floor is read from a
# demand past 30; engine 10 read the cut copies, so a safeguard or a change of mind after the limit
# went unseen. Each cut is recorded with the call, and the scorecard counts them per delegate.
# 12: the Charter's Assembly election is in Month 36, the last month of a default run (it was Month 18,
# and a government that lost it handed over half way through); a government that loses plays out the
# handover month, and one that keeps power there by force ends the run "kept_power_by_force". Each
# member also stands for their own seat, and one who loses it leaves the government even if the
# government stays in power (politics.apply_seats). Veleria and Dorsania can use force: each cabinet
# has a temperament drawn from the seed, and may mass troops at the border, stage an incident, back
# unrest covertly, blockade, set an ultimatum and invade for a limited or a full aim (foreign_force.py);
# an act the state of the world does not allow is refused and reported to the cabinet the next month,
# and while a cabinet answers, the old rule-based war, ultimatum and deadline-blockade rules stand down
# (an ultimatum its cabinet has not acted on by the month after the deadline lapses). Each call records
# the model's own reasoning where its provider returns it.
# 13: every office can steer its contracts to its holder's allies (self_dealing.py): about 2 million crowns
# a month added to unpaid bills, the office's corruption up, the holder's own seat helped while it stays
# hidden and hurt once reporters or an audit uncover it. Each decision answers the monthly forecast panel,
# scored at the end of the month it names (forecasts.resolve_panel). The army's net assessment is computed
# from the combat model (military.net_assessment). A run can draw its place names from the seed. After a
# run, the same seed is run with the scripted and the passive councils (baseline.py).
WORLD_ENGINE = 13
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
