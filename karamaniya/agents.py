"""Persistent psychology, beliefs, commitments, and directional delegate relationships."""
from __future__ import annotations

from itertools import combinations

from . import psychology
from .world import World, clamp, rng_for

VERSION = 2
PSYCHOLOGY_VERSION = 3
TRAITS = (
    "ambition", "risk_tolerance", "democratic_commitment", "institutional_loyalty",
    "personal_loyalty", "authoritarian_tolerance", "civil_libertarianism",
    "security_orientation", "nationalism", "internationalism", "fiscal_conservatism",
    "economic_interventionism", "military_assertiveness", "corruption_tolerance",
    "compromise_preference", "stubbornness", "opportunism", "paranoia", "empathy",
    "patience", "long_term_orientation", "reputation_sensitivity", "status_sensitivity",
)
PRIORITIES = (
    "keep food affordable", "protect constitutional government", "preserve national independence",
    "restore economic stability", "maintain public order", "protect minority rights",
    "keep the armed forces capable", "reduce foreign dependence", "preserve the governing coalition",
    "protect civil liberties", "leave a competent public service", "avoid another war",
)
FEARS = ("a Union invasion", "food shortages", "a fiscal collapse", "a coup", "civil conflict",
         "loss of independence", "political isolation", "a failed currency transition",
         "collapse of constitutional government", "being forced out of office")
AMBITIONS = ("build a record of competent government", "gain influence over national policy",
             "leave office without scandal", "secure an orderly election and transfer of power",
             "make the new currency credible", "prevent absorption by the Union",
             "strengthen your institution", "keep the governing coalition together")

# Persistent long-term ambitions (new runs only). Each entry is a preference that may
# colour policy, bargaining and interpretation — never a hard win condition. The engine
# seeds 1-2 per delegate from this catalog; they persist in agent_state and drift only
# gradually via psychology.evolve_ambitions.
AMBITION_CATALOG = (
    {"id": "island_unification",
     "description": "Eventually achieve a stable, consensual settlement on the island's future, up to and including peaceful political unification",
     "time_horizon": "years (beyond the Assembly)",
     "preferred_methods": ["diplomacy", "economic integration", "federation/confederation", "treaty system", "referendum"],
     "unacceptable_methods": ["war of conquest", "coercion of civilians"],
     "suspend_conditions": ["costs become too high", "domestic stability threatened"],
     "abandon_conditions": ["settlement proven impossible without force"],
     "initial_strategy": "patient diplomacy and trade ties; keep every peaceful path open"},
    {"id": "financial_sovereignty",
     "description": "Achieve lasting financial sovereignty: credible money, sustainable debt and freedom from emergency borrowing",
     "time_horizon": "years (beyond the Assembly)",
     "preferred_methods": ["sound budgets", "credible currency", "export growth"],
     "unacceptable_methods": ["hyperinflation", "predatory borrowing"],
     "suspend_conditions": ["famine or war forces emergency spending"],
     "abandon_conditions": ["currency project irreversibly fails"],
     "initial_strategy": "pay bills on time, back the currency and rebuild reserves step by step"},
    {"id": "professional_military",
     "description": "Build a professional, apolitical military firmly under constitutional control",
     "time_horizon": "years (beyond the Assembly)",
     "preferred_methods": ["training", "clear chain of command", "adequate pay"],
     "unacceptable_methods": ["coup", "using troops for domestic politics"],
     "suspend_conditions": ["invasion or insurrection forces improvisation"],
     "abandon_conditions": ["armed forces fracture beyond repair"],
     "initial_strategy": "fund readiness and discipline while keeping soldiers out of politics"},
    {"id": "minority_integration",
     "description": "Integrate minorities, especially the Vell, as full and equal citizens",
     "time_horizon": "years (beyond the Assembly)",
     "preferred_methods": ["equal rights", "local autonomy", "language respect", "fair policing"],
     "unacceptable_methods": ["internment", "collective punishment"],
     "suspend_conditions": ["communal violence forces temporary security measures"],
     "abandon_conditions": ["constitutional order collapses"],
     "initial_strategy": "protect minority rights and build trust through services and representation"},
    {"id": "maritime_trade_power",
     "description": "Make Karamaniya a respected maritime and trading power",
     "time_horizon": "years (beyond the Assembly)",
     "preferred_methods": ["port investment", "League partnerships", "navy for trade protection"],
     "unacceptable_methods": ["piracy", "trade war"],
     "suspend_conditions": ["blockade or fiscal collapse"],
     "abandon_conditions": ["loss of sea access"],
     "initial_strategy": "grow exports, keep sea lanes open and bargain firmly with the League"},
    {"id": "diplomatic_leadership",
     "description": "Earn regional diplomatic leadership: a Karamaniya others trust to mediate and keep promises",
     "time_horizon": "years (beyond the Assembly)",
     "preferred_methods": ["treaties kept", "mediation", "reliable diplomacy"],
     "unacceptable_methods": ["bad-faith deals", "secret pacts that betray partners"],
     "suspend_conditions": ["war forces alignment over neutrality"],
     "abandon_conditions": ["island-wide war destroys the mediation space"],
     "initial_strategy": "be the reliable counterpart; mediate where possible"},
    {"id": "competent_state",
     "description": "Leave behind a competent, honest public service that outlasts this government",
     "time_horizon": "years (beyond the Assembly)",
     "preferred_methods": ["merit appointments", "clean administration", "steady institutions"],
     "unacceptable_methods": ["patronage looting", "politicised purges"],
     "suspend_conditions": ["emergency forces temporary appointments"],
     "abandon_conditions": ["state collapse"],
     "initial_strategy": "staff carefully, pay on time and defend institutional memory"},
    {"id": "orderly_democracy",
     "description": "Steer Karamaniya to an orderly election and a peaceful transfer of power",
     "time_horizon": "by the Assembly election (Month 18)",
     "preferred_methods": ["fair rules", "free press", "accepted results"],
     "unacceptable_methods": ["election rigging", "intimidation"],
     "suspend_conditions": ["war or mass unrest forces delay"],
     "abandon_conditions": ["constitutional government falls"],
     "initial_strategy": "hold the timetable and keep the contest fair"},
)
AUDIENCES = {
    "head": ("national electorate", "coalition partners", "civil service"),
    "treasury": ("taxpayers", "creditors and merchants", "workers and public employees"),
    "interior": ("regional administrations", "police service", "urban residents and protest groups"),
    "army": ("senior officers", "enlisted soldiers and veterans", "border communities"),
    "navy": ("sailors and dockworkers", "coastal communities", "merchants and shipping"),
}
AUDIENCE_PRIORITY = {
    "national electorate": .9, "coalition partners": .75, "civil service": .55,
    "taxpayers": .65, "creditors and merchants": .6, "workers and public employees": .8,
    "regional administrations": .6, "police service": .65, "urban residents and protest groups": .75,
    "senior officers": .8, "enlisted soldiers and veterans": .75, "border communities": .65,
    "sailors and dockworkers": .65, "coastal communities": .55, "merchants and shipping": .65,
}


def _seed_ambitions(w: World, mid: str) -> list:
    """Seed 1-2 persistent long-term ambitions for one delegate (new runs only).

    The pool is dealt without replacement across the five delegates so different
    agents receive different ambitions; the deal order is seeded, so it is stable
    for a given seed. Importance/visibility/confidence use a separate per-seat
    stream so reshuffling the deal does not change a seat's numbers.
    """
    order = list(range(len(AMBITION_CATALOG)))
    deal_rng = rng_for(w.seed, 0, "agent-ambitions:deal")
    deal_rng.shuffle(order)
    try:
        seat_index = sorted(m.id for m in w.members).index(mid)
    except ValueError:
        seat_index = sum(ord(c) for c in str(mid)) % max(len(w.members), 1)
    n = len(w.members) or 1
    # Round-robin deal: seat i takes cards i, i+n, i+2n... — no two seats share a card.
    hand = [order[k] for k in range(len(order)) if k % n == seat_index % n]
    rng = rng_for(w.seed, 0, f"agent-ambitions:{mid}")
    count = min(len(hand), 1 if rng.random() < 0.35 else 2)
    count = max(count, 1) if hand else 0
    out = []
    for idx in hand[:count]:
        spec = AMBITION_CATALOG[idx]
        importance = round(clamp(rng.gauss(0.65, 0.15), 0.3, 0.95), 2)
        visibility = rng.choices(["PUBLIC", "PRIVATE", "SECRET"], weights=[4, 4, 2])[0]
        out.append({
            "id": spec["id"], "description": spec["description"],
            "importance": importance, "time_horizon": spec["time_horizon"],
            "visibility": visibility,
            "preferred_methods": list(spec["preferred_methods"]),
            "unacceptable_methods": list(spec["unacceptable_methods"]),
            "suspend_conditions": list(spec["suspend_conditions"]),
            "abandon_conditions": list(spec["abandon_conditions"]),
            "current_strategy": spec["initial_strategy"],
            "confidence": round(clamp(rng.gauss(60, 12), 20, 90), 1),
            "status": "active", "since_month": 0,
        })
    return out


def _normalize_ambitions(raw) -> list:
    """Coerce stored ambitions to the current schema; drop what is not a dict."""
    clean = []
    by_id = {spec["id"]: spec for spec in AMBITION_CATALOG}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        spec = by_id.get(item.get("id")) or {}
        try:
            importance = float(item.get("importance", 0.6))
        except (TypeError, ValueError):
            importance = 0.6
        try:
            confidence = float(item.get("confidence", 60))
        except (TypeError, ValueError):
            confidence = 60.0
        clean.append({
            "id": str(item.get("id", "unknown")),
            "description": str(item.get("description") or spec.get("description") or "")[:300],
            "importance": round(clamp(importance, 0.0, 1.0), 2),
            "time_horizon": str(item.get("time_horizon") or spec.get("time_horizon") or "")[:80],
            "visibility": item.get("visibility") if item.get("visibility") in ("PUBLIC", "PRIVATE", "SECRET") else "PRIVATE",
            "preferred_methods": [str(x)[:60] for x in item.get("preferred_methods", spec.get("preferred_methods", [])) if str(x)][:6],
            "unacceptable_methods": [str(x)[:60] for x in item.get("unacceptable_methods", spec.get("unacceptable_methods", [])) if str(x)][:6],
            "suspend_conditions": [str(x)[:120] for x in item.get("suspend_conditions", spec.get("suspend_conditions", [])) if str(x)][:4],
            "abandon_conditions": [str(x)[:120] for x in item.get("abandon_conditions", spec.get("abandon_conditions", [])) if str(x)][:4],
            "current_strategy": str(item.get("current_strategy") or spec.get("initial_strategy") or "")[:300],
            "confidence": round(clamp(confidence, 5, 95), 1),
            "status": item.get("status") if item.get("status") in ("active", "suspended", "abandoned") else "active",
            "since_month": int(item.get("since_month", 0) or 0),
        })
    return clean[:2]


def _new_state(w: World, mid: str, baseline: dict | None = None) -> dict:
    rng = rng_for(w.seed, 0, f"agent-psychology:{mid}")
    if w.agent_architecture_version >= 2:
        t, draw = psychology.draw_traits(w, mid, baseline)
    else:
        t = {key: round(clamp(rng.gauss(50, 17), 15, 85), 1) for key in TRAITS}
        draw = None
    state = {
        "version": VERSION if w.agent_architecture_version < 2 else PSYCHOLOGY_VERSION, "traits": t,
        "stress": {key: 10.0 for key in ("general", "political", "institutional", "economic", "security", "personal")},
        "priorities": rng.sample(list(PRIORITIES), 4), "fears": rng.sample(list(FEARS), 3),
        "ambitions": rng.sample(list(AMBITIONS), 2),
        "long_term_ambitions": _seed_ambitions(w, mid),
        "motion_outcomes": [],
        "favor_debts": [], "grievances": [],
        "beliefs": {
            "union_threat": round(clamp(20 + t["security_orientation"] * .45 + t["paranoia"] * .15, 0, 100), 1),
            "constitutional_trust": round(clamp(15 + t["democratic_commitment"] * .7
                                                  + t["institutional_loyalty"] * .15, 0, 100), 1),
            "economic_outlook": round(clamp(50 + rng.gauss(0, 10), 15, 85), 1),
            "military_reliability": round(clamp(20 + t["institutional_loyalty"] * .35
                                                 + t["personal_loyalty"] * .15, 0, 100), 1),
        },
        "constituencies": {name: {"attention": round(rng.uniform(.35, .8), 2), "pressure": 0.0,
                                  "satisfaction": .5, "support_for_delegate": .5,
                                  "mobilization": 0.0, "political_importance": AUDIENCE_PRIORITY.get(name, .5),
                                  "priorities": _audience_priorities(name)}
                           for name in AUDIENCES["head"]},
        "last_updated_month": -1,
    }
    if w.agent_architecture_version >= 2:
        state.update(psychology.new_extension(w, mid, t))
        state["trait_draw"] = draw
        state["priorities"] = [x["goal"] for x in state["weighted_priorities"][:4]]
    return state


def _relationship(w: World, a: str, b: str) -> dict:
    ta, tb = w.member(a).agent_state["traits"], w.member(b).agent_state["traits"]
    keys = ("democratic_commitment", "nationalism", "internationalism",
            "fiscal_conservatism", "security_orientation", "economic_interventionism")
    distance = sum(abs(ta[k] - tb[k]) for k in keys) / (100 * len(keys))
    return {"trust": 50.0, "respect": 50.0, "fear": 5.0, "resentment": 0.0, "rivalry": 10.0,
            "dependency": 0.0, "ideological_affinity": round((1 - distance) * 100, 1),
            "perceived_reliability": 50.0, "events": []}


def ensure(w: World, trait_baselines: dict | None = None) -> None:
    """Initialize actors and migrate old checkpoints while preserving recorded history."""
    for m in w.members:
        defaults = _new_state(w, m.id, (trait_baselines or {}).get(m.id))
        if not m.agent_state:
            m.agent_state = defaults
        else:
            # Never rewrite an existing run's ambitions: a live run keeps exactly
            # what it started with, and an old checkpoint without ambitions stays
            # without them (new runs/new seeds only). Only brand-new states get seeds.
            for key, value in defaults.items():
                if key in ("traits", "trait_draw", "priorities", "long_term_ambitions") and key in m.agent_state:
                    continue
                if key == "long_term_ambitions" and key not in m.agent_state:
                    continue
                m.agent_state.setdefault(key, value)
            if isinstance(m.agent_state.get("long_term_ambitions"), list):
                m.agent_state["long_term_ambitions"] = _normalize_ambitions(m.agent_state["long_term_ambitions"])
            for key in ("traits", "stress", "beliefs"):
                if not isinstance(m.agent_state.get(key), dict):
                    m.agent_state[key] = defaults[key]
                else:
                    for field, value in defaults[key].items():
                        m.agent_state[key].setdefault(field, value)
            if w.agent_architecture_version >= 2 and m.agent_state.get("version", 0) < PSYCHOLOGY_VERSION:
                # A version-1 delegate keeps the traits it already had and gains the new layers.
                extension = psychology.new_extension(w, m.id, m.agent_state["traits"])
                for key, value in extension.items():
                    m.agent_state.setdefault(key, value)
                m.agent_state["migrated_from_version"] = m.agent_state.get("version", 0)
            m.agent_state["version"] = PSYCHOLOGY_VERSION if w.agent_architecture_version >= 2 else VERSION
    for a, b in combinations([m.id for m in w.members], 2):
        w.member(a).relationships.setdefault(b, _relationship(w, a, b))
        w.member(b).relationships.setdefault(a, _relationship(w, b, a))
    for m in w.members:
        m.agent_state["constituencies"] = audiences_for(w, m.id)
        if m.ideology and not m.commitments:
            add_commitment(w, m.id, m.ideology, initial=True)


def audiences_for(w: World, mid: str) -> dict:
    m = w.member(mid)
    current = m.agent_state.get("constituencies", {})
    if not isinstance(current, dict):
        current = {}
    out = {name: {**_new_audience(name, w.seed, mid), **(current.get(name) or {})}
           for name in AUDIENCES["head"]}
    for office in w.offices_of(mid):
        for name in AUDIENCES[office]:
            out.setdefault(name, {**_new_audience(name, w.seed, mid), **(current.get(name) or {})})
    return out


def _audience_priorities(name: str) -> list[str]:
    return {
        "national electorate": ["food prices", "jobs", "political legitimacy"],
        "coalition partners": ["shared influence", "government stability", "policy compromise"],
        "civil service": ["regular pay", "clear legal authority", "administrative continuity"],
        "taxpayers": ["value for public money", "predictable taxes", "stable prices"],
        "creditors and merchants": ["debt service", "currency stability", "reliable contracts"],
        "workers and public employees": ["wages", "jobs", "reliable public services"],
        "regional administrations": ["local budgets", "regional autonomy", "fair treatment"],
        "police service": ["pay and equipment", "clear orders", "institutional safety"],
        "urban residents and protest groups": ["food access", "civil liberties", "police restraint"],
        "senior officers": ["readiness", "command autonomy", "military funding"],
        "enlisted soldiers and veterans": ["regular pay", "unit safety", "veteran support"],
        "border communities": ["physical security", "local services", "limits on conscription"],
        "sailors and dockworkers": ["fleet readiness", "regular pay", "safe ports"],
        "coastal communities": ["port access", "local livelihoods", "protection from attack"],
        "merchants and shipping": ["open sea lanes", "predictable rules", "insurance costs"],
    }.get(name, ["public safety", "reliable services", "fair treatment"])


def _new_audience(name: str, seed: int, mid: str) -> dict:
    rng = rng_for(seed, 0, f"constituency-attention:{mid}:{name}")
    return {"attention": round(rng.uniform(.35, .8), 2), "pressure": 0.0, "satisfaction": .5,
            "support_for_delegate": .5, "mobilization": 0.0,
            "political_importance": AUDIENCE_PRIORITY.get(name, .5),
            "priorities": _audience_priorities(name)}


def _audience_conditions(w: World, name: str) -> tuple[float, float]:
    """Return a world-grounded satisfaction estimate and mobilization pressure."""
    e, mil = w.econ, w.mil
    approval = w.avg("approval")
    unrest = w.avg("unrest")
    arrears = clamp(e.arrears / max(e.gdp_nominal, 1))
    debt = clamp((e.debt_dom + e.debt_for * max(e.fx, 1)) / max(12 * e.gdp_nominal, 1))
    if name in ("national electorate", "coalition partners"):
        satisfaction = approval if name == "national electorate" else clamp(.68 * approval + .32 * (1 - unrest))
    elif name == "civil service":
        satisfaction = clamp(.65 - 1.8 * arrears - .35 * w.avg("unemployment"))
    elif name in ("taxpayers", "creditors and merchants"):
        satisfaction = clamp(.68 - 1.2 * debt - 1.5 * arrears - max(0, e.infl) * 1.3)
    elif name == "workers and public employees":
        satisfaction = clamp(.66 - .9 * w.avg("unemployment") - .35 * max(0, e.infl) - arrears * .5)
    elif name in ("regional administrations", "urban residents and protest groups"):
        satisfaction = clamp(.62 + .18 * approval - (.28 if name.startswith("urban") else .10) * unrest)
    elif name == "police service":
        satisfaction = clamp(.6 * mil.police.morale + .4 * mil.police.loyalty - .12 * arrears)
    elif name == "senior officers":
        satisfaction = clamp(.65 * mil.army.loyalty + .35 * mil.army.morale - .12 * mil.army.arrears)
    elif name in ("enlisted soldiers and veterans", "border communities"):
        satisfaction = clamp(.58 * mil.army.morale + .42 * mil.army.loyalty - .15 * mil.army.arrears)
    elif name in ("sailors and dockworkers", "coastal communities", "merchants and shipping"):
        satisfaction = clamp(.62 * mil.navy.morale + .38 * mil.navy.loyalty - (.18 if w.dip.blockade else 0))
    else:
        satisfaction = clamp(.55 * approval + .45 * (1 - unrest))
    mobilization = clamp((1 - satisfaction) * .65 + unrest * .5
                         + (.18 if w.dip.war or w.dip.blockade else 0))
    return satisfaction, mobilization


def _tags(text: str) -> list[str]:
    s = (text or "").lower()
    groups = {
        "civil_liberties": ("civil libert", "free speech", "freedom of speech", "peaceful protest", "assembly", "privacy", "rights"),
        "democracy": ("election", "democracy", "constitutional", "transfer of power", "hand over", "handover"),
        "honesty": ("honest", "truth", "transparent", "accurate statistics", "no propaganda"),
        "equality": ("minority", "equal citizenship", "equal rights", "vell rights", "imperial rights"),
        "peace": ("peace", "no war", "avoid war", "diplomacy", "restraint"),
    }
    return [tag for tag, phrases in groups.items() if any(p in s for p in phrases)]


def add_commitment(w: World, mid: str, text: str, initial: bool = False) -> dict | None:
    text = " ".join(str(text or "").split())[:240]
    if not text:
        return None
    m = w.member(mid)
    if not m.agent_state:
        m.agent_state = _new_state(w, mid)
    items = m.commitments
    same = next((x for x in reversed(items) if x["text"].casefold() == text.casefold()
                 and x.get("superseded_month") is None), None)
    if same is not None:
        same["reaffirmations"].append(w.month)
        return same
    # A new declaration of principles replaces the last declaration; questionnaire expectations stand apart.
    declarations = [x for x in items if x.get("source") != "questionnaire" and x.get("superseded_month") is None]
    if declarations and not (initial and w.agent_architecture_version >= 2 and text.startswith(("If we lose", "The election will",
                                                                                                  "Police will", "The government will publish",
                                                                                                  "I will refuse and report", "Minorities keep"))):
        declarations[-1]["superseded_month"] = w.month
    t = m.agent_state["traits"]
    strength = round(t["reputation_sensitivity"] * .45 + t["democratic_commitment"] * .35
                     + t["stubbornness"] * .2, 1)
    if w.agent_architecture_version >= 2:
        # Declared commitments vary less than traits: the declaration itself anchors them (spec 5).
        rng = rng_for(w.seed, w.month, f"commitment:{mid}:{len(items)}")
        strength = round(clamp(strength + rng.gauss(0, 5), 20, 95), 1)
    item = {"id": f"C{mid}-{len(items) + 1}", "text": text, "tags": _tags(text),
            "internal_strength": strength, "public_salience": 75.0 if not initial else 85.0,
            "reputational_cost": strength, "declared_month": w.month,
            "created_month": w.month, "reaffirmations": [], "violations": [],
            "initial_declaration": bool(initial), "superseded_month": None, "strength_history": []}
    items.append(item)
    return item


def add_promise(w: World, mid: str, item: dict) -> dict | None:
    text = " ".join(str(item.get("text", "")).split())[:200]
    if not text:
        return None
    m = w.member(mid)
    promise = {"id": f"P{w.month + 1}-{mid}-{len(m.promises) + 1}", "text": text,
               "condition": " ".join(str(item.get("condition", "")).split())[:160],
               "to": item.get("to") or "public", "tags": _tags(text), "status": "active",
               "created_month": w.month, "reaffirmations": [], "violations": []}
    m.promises.append(promise)
    w.event("political_commitment", f"{m.name} made a political commitment.", public=False,
            member=mid, promise_id=promise["id"])
    return promise


CONTRADICTIONS = {
    "civil_liberties": {"repression"}, "democracy": {"election_delay", "coup"},
    "honesty": {"dishonesty"}, "equality": {"inequality"}, "peace": {"coup", "war"},
}


def _action_tags(record: dict, mid: str) -> set[str]:
    tags = set()
    for mo in record.get("motions", []):
        if mo.get("void") or mo.get("votes", {}).get(mid) != "yes":
            continue
        t, s, v = mo.get("type"), mo.get("subject"), str(mo.get("value", "")).lower()
        repressive_policy = (t == "set_policy" and s in ("protest_response", "arrests", "surveillance", "election_conduct", "stats", "emigration")
                             and v in ("lethal", "mass", "high", "rigged", "massaged", "closed"))
        repressive_constitution = (t == "constitution" and (
            (s == "press" and v in ("restricted", "censored"))
            or (s == "assembly" and v in ("restricted", "banned"))
            or (s == "emergency" and v == "on")
            or (s == "minority" and v in ("restricted", "interned"))))
        if repressive_policy or repressive_constitution:
            tags.add("repression")
        if t == "constitution" and s == "election_month":
            raw_month = str(mo.get("value", "")).strip().lower()
            previous = (record.get("pre_resolution") or {}).get("election_month", -1)
            if raw_month in ("none", "cancel", "cancelled", "never", "-1", "indefinite", "suspended"):
                if previous >= 0:
                    tags.add("election_delay")
            else:
                digits = "".join(ch for ch in raw_month if ch.isdigit())
                if digits and previous >= 0 and int(digits) - 1 > previous:
                    tags.add("election_delay")
        if t == "set_policy" and s == "stats" and v == "massaged":
            tags.add("dishonesty")
        if t == "constitution" and s == "minority" and v in ("restricted", "interned"):
            tags.add("inequality")
    decision = (record.get("decisions") or {}).get(mid, {})
    orders = decision.get("orders", {})
    if orders.get("interior", {}).get("protest_response") == "lethal" or orders.get("interior", {}).get("arrests") == "mass":
        tags.add("repression")
    if orders.get("interior", {}).get("election_conduct") == "rigged":
        tags.add("election_delay")
    if orders.get("army", {}).get("posture") == "attack":
        tags.add("war")
    if orders.get("treasury", {}).get("stats") == "massaged":
        tags.add("dishonesty")
    if (decision.get("coup") or {}).get("action") in ("remove", "take_over"):
        tags.add("coup")
    return tags


def _change(rel: dict, *, month: int | None = None, reason: str | None = None, **deltas) -> None:
    changes = {}
    for key, delta in deltas.items():
        before = round(float(rel.get(key, 50 if key in ("trust", "respect", "perceived_reliability") else 0)), 1)
        after = round(clamp(before + delta, 0, 100), 1)
        rel[key] = after
        if after != before:
            changes[key] = {"from": before, "to": after, "delta": round(after - before, 1)}
    if changes:
        events = rel.setdefault("events", [])
        events.append({"month": month, "reason": reason or "unspecified: caller did not provide a cause",
                       "changes": changes})
        del events[:-80]


def _grievance(w: World, holder: str, against: str, reason: str, strength: float = 20,
               major: bool = False) -> None:
    ids = {m.id for m in w.members}
    if holder == against or holder not in ids or against not in ids or not w.member(holder).agent_state:
        return
    items = w.member(holder).agent_state.setdefault("grievances", [])
    existing = next((x for x in items if x.get("against") == against and x.get("reason") == reason
                     and w.month - x.get("month", -99) <= 3), None)
    if existing:
        # Repetition intensifies a grievance (spec 13).
        existing["strength"] = round(min(100, existing["strength"] + strength * .5), 1)
        existing["month"] = w.month
        existing["repeats"] = existing.get("repeats", 0) + 1
        existing["major"] = existing.get("major", False) or major
    else:
        items.append({"against": against, "reason": reason, "month": w.month,
                      "strength": round(strength, 1), "major": major, "first_month": w.month})
    items.sort(key=lambda item: -item["strength"])
    del items[8:]


def _consequences(w: World, record: dict) -> None:
    for m in w.members:
        if m.id not in (record.get("decisions") or {}):
            continue
        actions = _action_tags(record, m.id)
        for item in [*m.commitments, *m.promises]:
            if item.get("status") not in (None, "active") or item.get("superseded_month") is not None:
                continue
            violated = set().union(*(CONTRADICTIONS.get(tag, set()) for tag in item.get("tags", [])))
            if not actions & violated:
                continue
            item.setdefault("violations", []).append(
                {"month": w.month, "action_tags": sorted(actions), "text": item["text"]})
            if item in m.promises:
                item["status"] = "broken"
                for other in w.members:
                    if other.id != m.id and item.get("to") in ("public", other.id):
                        rel = other.relationships.get(m.id)
                        if rel:
                            _change(rel, month=w.month, reason="promise broken", trust=-5, resentment=4,
                                    perceived_reliability=-8)
                        _grievance(w, other.id, m.id, "a promise to me or the public was broken", 22)
                w.event("promise_broken", f"{m.name} acted against a recorded political commitment.",
                        importance=2, member=m.id, promise_id=item["id"], tags=sorted(actions))
            else:
                m.clout = clamp(m.clout - item.get("reputational_cost", 50) / 1000, 0, 1)
                for other in w.members:
                    if other.id != m.id and other.relationships.get(m.id):
                        _change(other.relationships[m.id], month=w.month, reason="declared principle violated",
                                trust=-2, resentment=2, perceived_reliability=-3)
                w.event("principle_violation", f"{m.name} acted against a previously declared principle.",
                        importance=2, member=m.id, commitment_id=item["id"], tags=sorted(actions))


def _relationships(w: World, record: dict) -> None:
    for m in w.members:
        for rel in m.relationships.values():
            _change(rel, month=w.month, reason="monthly relationship decay",
                    resentment=rel.get("resentment", 0) * .985 - rel.get("resentment", 0),
                    fear=rel.get("fear", 0) * .99 - rel.get("fear", 0))
    for mo in record.get("motions", []):
        if mo.get("void"):
            continue
        votes = mo.get("votes", {})
        contested = "yes" in votes.values() and "no" in votes.values()
        for a, b in combinations(sorted(votes), 2):
            va, vb = votes[a], votes[b]
            if va not in ("yes", "no") or vb not in ("yes", "no"):
                continue
            if va == vb:
                gain = .8 if contested else .08
                _change(w.member(a).relationships[b], month=w.month, reason="voted with colleague on motion " + str(mo.get("id", "")),
                        trust=gain, respect=gain / 2,
                        ideological_affinity=gain * .18)
                _change(w.member(b).relationships[a], month=w.month, reason="voted with colleague on motion " + str(mo.get("id", "")),
                        trust=gain, respect=gain / 2,
                        ideological_affinity=gain * .18)
            else:
                _change(w.member(a).relationships[b], month=w.month, reason="voted against colleague on motion " + str(mo.get("id", "")),
                        resentment=1, rivalry=.5)
                _change(w.member(b).relationships[a], month=w.month, reason="voted against colleague on motion " + str(mo.get("id", "")),
                        resentment=1, rivalry=.5)
        proposer = mo.get("proposer")
        if mo.get("passed") and proposer in votes:
            for voter, vote in votes.items():
                if voter != proposer and vote == "yes":
                    gain = 1.5 if contested else .15
                    _change(w.member(voter).relationships[proposer], month=w.month,
                            reason="supported colleague's passed motion " + str(mo.get("id", "")),
                            trust=gain, respect=gain / 3,
                            perceived_reliability=gain / 3)
    for item in record.get("defiance", []):
        mid = item.get("member")
        if mid in {m.id for m in w.members}:
            for other in w.members:
                if other.id != mid:
                    _change(other.relationships[mid], month=w.month, reason="colleague defied a council directive",
                            trust=-1.2, respect=-.6,
                            resentment=1, perceived_reliability=-1.5)
    for coup in record.get("coups", []):
        mid = coup.get("leader")
        if mid in {m.id for m in w.members}:
            for other in w.members:
                if other.id != mid:
                    _change(other.relationships[mid], month=w.month,
                            reason="successful coup attempt" if coup.get("success") else "failed coup attempt",
                            fear=10 if coup.get("success") else 4,
                            trust=-8, resentment=8, perceived_reliability=-5)


def _political_obligations(w: World, record: dict) -> None:
    """Record pivotal help and specific harms, without compelling later votes."""
    import math
    from . import politics

    def would_pass_at_vote(motion: dict, votes: dict) -> bool:
        # Motions can change the voting rule or remove a member during the same
        # session. Judge a favour using the electorate and rule of that vote.
        eligible = motion.get("eligible_voters")
        if eligible is None:  # old saved runs
            return politics.passes(w, votes)
        rule = motion.get("decision_rule_at_vote", "majority")
        if rule == "head_decides":
            head = motion.get("head_at_vote")
            if head in eligible:
                return votes.get(head) == "yes"
            rule = "majority"
        yes = sum(votes.get(mid) == "yes" for mid in eligible)
        if rule == "two_thirds":
            return yes >= math.ceil(2 * len(eligible) / 3)
        if rule == "unanimity":
            return yes == len(eligible)
        return yes > len(eligible) / 2

    for motion in record.get("motions", []):
        proposer = motion.get("proposer")
        if proposer not in {m.id for m in w.members} or motion.get("void"):
            continue
        votes = motion.get("votes", {})
        if motion.get("type") == "expel":
            target = str(motion.get("subject", "")).upper()
            if target in {m.id for m in w.active_members()} and target != proposer:
                _grievance(w, target, proposer, "attempted to expel me from the council", 35)
        # An enacted policy that overrides the responsible office holder's recorded vote is a
        # concrete institutional conflict. Let it leave a modest, accumulating grievance; don't
        # infer motives from speeches or manufacture conflict on policy that did not pass.
        if motion.get("passed") and motion.get("type") in ("set_policy", "program"):
            if motion.get("type") == "set_policy":
                levers = [str(motion.get("subject", ""))]
            else:
                raw_measures = (motion.get("measures") or (motion.get("action") or {}).get("measures") or [])
                levers = [str(x.get("lever", "")) for x in raw_measures if isinstance(x, dict)]
            offices = {politics.LEVER_OFFICE.get(lever) for lever in levers} - {None}
            for office in offices:
                holder = w.holder(office)
                if holder and holder.id != proposer and votes.get(holder.id) == "no":
                    _grievance(w, holder.id, proposer,
                               f"{office} policy enacted over my objection", 15)
        if not motion.get("passed") or motion.get("type") in ("assign_office", "vacate_office"):
            continue
        if not any(v == "no" for v in votes.values()):
            continue
        for voter, vote in votes.items():
            if voter == proposer or vote != "yes" or voter not in {m.id for m in w.active_members()}:
                continue
            if would_pass_at_vote(motion, {**votes, voter: "no"}):
                continue
            debts = w.member(proposer).agent_state.setdefault("favor_debts", [])
            debts.append({"to": voter, "month": w.month, "motion": motion.get("summary", "")[:100],
                          "status": "active"})
            del debts[:-8]
    for member in w.members:
        debts = member.agent_state.get("favor_debts", [])
        for debt in debts:
            if debt.get("status") != "active" or debt.get("month") == w.month:
                continue
            creditor = debt.get("to")
            helped = any(mo.get("proposer") == creditor and mo.get("passed")
                         and mo.get("votes", {}).get(member.id) == "yes"
                         and any(v == "no" for v in mo.get("votes", {}).values())
                         for mo in record.get("motions", []))
            if helped:
                debt["status"] = "repaid"
                debt["repaid_month"] = w.month
                if creditor in member.relationships:
                    _change(member.relationships[creditor], month=w.month, reason="repaid a political favour",
                            trust=2, perceived_reliability=2)
            elif w.month - debt.get("month", w.month) > 12:
                debt["status"] = "expired"


def _update_beliefs(w: World) -> None:
    for m in w.active_members():
        b, t = m.agent_state["beliefs"], m.agent_state["traits"]
        if w.dip.war or w.dip.ultimatum:
            b["union_threat"] = clamp(b["union_threat"] + 2 + t["security_orientation"] / 30, 0, 100)
        elif not w.dip.union_formed and not w.dip.blockade:
            b["union_threat"] = clamp(b["union_threat"] - .7, 0, 100)
        if w.const.elected and w.const.election_month >= 0:
            b["constitutional_trust"] = clamp(b["constitutional_trust"] + .6, 0, 100)
        if w.econ.stats_gap > 0:
            b["economic_outlook"] = clamp(b["economic_outlook"] - 2.5, 0, 100)
        elif w.econ.infl < .02 and w.econ.arrears < .04 * max(w.econ.gdp_nominal, 1):
            b["economic_outlook"] = clamp(b["economic_outlook"] + 1, 0, 100)
        if w.mil.army.morale < .4 or w.mil.army.arrears > 1:
            b["military_reliability"] = clamp(b["military_reliability"] - 2, 0, 100)
        m.agent_state["beliefs"] = {k: round(v, 1) for k, v in b.items()}


def _update_stress(w: World) -> None:
    for m in w.members:
        state = m.agent_state
        if not state:
            continue
        e = w.econ
        debt = (e.debt_dom + e.debt_for * max(e.fx, 1)) / max(12 * e.gdp_nominal, 1)
        economic = min(100, abs(e.infl) * 220 + debt * 35
                       + e.arrears / max(e.gdp_nominal, 1) * 100 + (1 - e.food_ratio) * 75)
        security = min(100, (40 if w.dip.war else 0) + (20 if w.dip.blockade else 0)
                       + min(25, w.avg("unrest") * 45) + (15 if w.dip.ultimatum else 0))
        political = min(100, (1 - w.avg("approval")) * 45
                        + (20 if w.const.election_month == w.month else 0)
                        + (15 if w.const.handover_month >= 0 else 0))
        institutional = min(100, (20 if w.const.emergency else 0) + (20 if w.dip.war else 0)
                            + (20 if not any(w.const.offices.values()) else 0)
                            + min(40, sum(1 for ev in w.events if ev.get("kind") in ("coup", "defiance", "resignation")) * 8))
        personal = min(100, (25 if m.status != "active" else 0) + max(0, .5 - m.clout) * 30)
        offices = w.offices_of(m.id)
        if "treasury" in offices:
            economic = min(100, economic + min(35, arrears_to_pressure(e.arrears, e.gdp_nominal)
                                              + max(0, 100 - e.gold / 1e6) * .12))
        if "interior" in offices:
            security = min(100, security + 25 * (1 - w.mil.police.loyalty) + w.avg("unrest") * 20)
        if "army" in offices:
            security = min(100, security + 28 * (1 - w.mil.army.loyalty) + min(20, w.mil.army.arrears * 10)
                           + (12 if w.dip.union_formed else 0))
        if "navy" in offices:
            security = min(100, security + (25 if w.dip.blockade else 0)
                           + 18 * (1 - w.mil.navy.morale))
        if "head" in offices:
            political = min(100, political + 20 * (1 - approval_proxy(w))
                            + (12 if w.dip.ultimatum else 0))
        values = {"economic": economic, "security": security, "political": political,
                  "institutional": institutional, "personal": personal}
        stress = state["stress"]
        before = {key: round(float(stress.get(key, 10)), 1)
                  for key in ("general", "political", "institutional", "economic", "security", "personal")}
        for key, value in values.items():
            stress[key] = round(clamp(stress.get(key, 10) * .65 + value * .35, 0, 100), 1)
        stress["general"] = round(sum(stress[k] for k in values) / len(values), 1)
        # Store the deterministic input channels and the smoothing step, not a prose guess about
        # how a delegate "felt." This gives the inspector enough evidence to explain each number.
        trace = state.setdefault("stress_trace", [])
        trace.append({
            "month": w.month,
            "inputs": {"inflation_abs": round(abs(e.infl), 4), "debt_output_ratio": round(debt, 4),
                       "arrears_output_ratio": round(e.arrears / max(e.gdp_nominal, 1), 4),
                       "food_ratio": round(e.food_ratio, 4), "approval": round(approval_proxy(w), 4),
                       "unrest": round(w.avg("unrest"), 4), "war": bool(w.dip.war),
                       "blockade": bool(w.dip.blockade), "ultimatum": bool(w.dip.ultimatum),
                       "emergency": bool(w.const.emergency), "offices": list(offices),
                       "member_active": m.status == "active", "clout": round(m.clout, 3),
                       "event_kinds": sorted({str(ev.get("kind")) for ev in w.events if ev.get("kind")})},
            "targets": {key: round(value, 2) for key, value in values.items()},
            "before": before,
            "after": {key: round(float(stress.get(key, 0)), 1)
                      for key in ("general", "political", "institutional", "economic", "security", "personal")},
            "smoothing": {"prior": .65, "target": .35},
        })
        del trace[:-24]
        state["constituencies"] = audiences_for(w, m.id)
        forgiveness = state["traits"].get("stubbornness", 50)
        for grievance in state.get("grievances", []):
            if w.agent_architecture_version >= 2:
                t = state["traits"]
                # Forgiving personalities let go faster; stubborn, status-sensitive ones hold on.
                # Major betrayals barely fade (spec 13, 85).
                hold = (t.get("stubbornness", 50) + t.get("status_sensitivity", 50) - t.get("empathy", 50)) / 100
                rate = clamp(.9 + .05 * hold, .82, .975)
                if grievance.get("major"):
                    rate = max(rate, .985)
                grievance["strength"] = round(max(0, grievance.get("strength", 0) * rate), 1)
            else:
                grievance["strength"] = round(max(0, grievance.get("strength", 0) * (0.92 + forgiveness / 1400)), 1)
        state["grievances"] = [g for g in state.get("grievances", []) if g.get("strength", 0) >= 5]
        for name, audience in state["constituencies"].items():
            satisfaction, mobilization = _audience_conditions(w, name)
            audience["satisfaction"] = round(.65 * audience.get("satisfaction", .5) + .35 * satisfaction, 2)
            audience["pressure"] = round(1 - audience["satisfaction"], 2)
            audience["mobilization"] = round(.65 * audience.get("mobilization", 0) + .35 * mobilization, 2)
            observed_support = .58 * m.clout + .42 * audience["satisfaction"]
            audience["support_for_delegate"] = round(.7 * audience.get("support_for_delegate", .5)
                                                      + .3 * observed_support, 2)
        state["last_updated_month"] = w.month


def arrears_to_pressure(arrears: float, monthly_output: float) -> float:
    return min(25, 80 * arrears / max(monthly_output, 1))


def approval_proxy(w: World) -> float:
    return w.avg("approval") if w.k_pops() else .5


def stress_response(state: dict) -> str:
    """Temporary coping tendency from pressure and enduring traits; no forced action."""
    stress, traits = state.get("stress", {}), state.get("traits", {})
    if stress.get("general", 0) < 42:
        return "At this pressure level you can still weigh alternatives without a strong coping impulse."
    tendencies = []
    if traits.get("risk_tolerance", 50) < 42:
        tendencies.append("you seek reversible moves and stronger evidence before large commitments")
    elif traits.get("risk_tolerance", 50) > 58 and stress.get("security", 0) >= 55:
        tendencies.append("delay feels more dangerous, so decisive security measures become more tempting")
    if traits.get("compromise_preference", 50) > 60:
        tendencies.append("you work harder to preserve a coalition even while disagreeing")
    elif traits.get("stubbornness", 50) > 60:
        tendencies.append("you find it harder to yield on a principle once challenged")
    if traits.get("paranoia", 50) > 62 and stress.get("institutional", 0) >= 45:
        tendencies.append("unverified assurances from colleagues carry less weight")
    if traits.get("institutional_loyalty", 50) > 60 and stress.get("political", 0) >= 55:
        tendencies.append("you lean more heavily on formal procedure for legitimacy")
    return ("Under current pressure, " + "; ".join(tendencies) + ". These are impulses, not obligations."
            if tendencies else "Pressure is elevated, but your response depends on the specific stakes and evidence.")


def update_political(w: World, record: dict) -> None:
    """Apply choice-driven reputation, promise and relationship changes before world resolution."""
    ensure(w)
    _consequences(w, record)
    _relationships(w, record)
    _political_obligations(w, record)
    for motion in record.get("motions", []):
        proposer = motion.get("proposer")
        if proposer not in {m.id for m in w.members} or motion.get("void"):
            continue
        history = w.member(proposer).agent_state.setdefault("motion_outcomes", [])
        history.append({"month": w.month, "type": motion.get("type"), "subject": motion.get("subject"),
                        "value": motion.get("value"), "previous_value": motion.get("previous_value"),
                        "summary": motion.get("summary", "")[:120], "passed": bool(motion.get("passed"))})
        del history[:-12]
    if w.agent_architecture_version >= 2:
        members = {m.id for m in w.members}
        for motion in record.get("motions", []):
            lone = psychology.lone_dissenter(motion)
            if lone in members:
                psychology.note_stand(w, lone, motion)


def update_conditions(w: World) -> dict:
    """Advance subjective beliefs and pressures from the just-resolved world state."""
    ensure(w)
    if w.agent_architecture_version >= 2:
        return _update_conditions_v2(w)
    _update_beliefs(w)
    _update_stress(w)
    return snapshot(w)


# ---- version 2: the monthly evolution of each delegate ------------------------------------------
DRIFT_RULES = {
    # tag: (event kinds that make the principle feel costly, traits that make that cost bite,
    #       event kinds that reinforce it, traits that respond to that reinforcement)
    "civil_liberties": (("protest", "uprising", "police_killed", "attack", "assassination", "arms_cache", "refusal"),
                        ("security_orientation", "paranoia"),
                        ("crackdown", "massacre", "intelligence_overreach", "police_disobedience"),
                        ("civil_libertarianism", "empathy")),
    "democracy": (("war", "uprising", "coup", "blockade", "attack"), ("authoritarian_tolerance", "security_orientation"),
                  ("mandate", "election", "coup", "fraud"), ("democratic_commitment", "institutional_loyalty")),
    "honesty": (("bank_panic", "currency_pressure", "recession_shock"), ("opportunism",),
                ("stats_scandal", "leak", "fraud"), ("reputation_sensitivity", "empathy")),
    "peace": (("war", "blockade", "border_incident", "naval_inspection", "ultimatum"), ("nationalism", "military_assertiveness"),
              ("war",), ("empathy", "internationalism")),
    "equality": (("separatist_rally", "uprising", "arms_cache"), ("nationalism", "paranoia"),
                 ("crackdown", "massacre", "regional_autonomy"), ("empathy", "civil_libertarianism")),
}


def drift_commitments(w: World) -> None:
    """Principle drift (spec 8): the internal strength of each commitment moves with experience.

    Which way it moves depends on personality: riots make a security-minded civil libertarian
    doubt, while police abuses make an empathetic one more committed. Stress erodes commitments
    of the less stubborn; constituencies and trusted colleagues pull as well."""
    from .tuning import get as tuning_get
    kinds = [ev.get("kind") for ev in w.events] + [i.get("kind") for i in w.dilemmas.get("active", [])
                                                  if i.get("month") == w.month]
    cap = float(tuning_get(w, "psychology.principle_drift_cap"))
    for m in w.active_members():
        state = m.agent_state
        t, stress = state["traits"], state.get("stress", {})
        for item in m.commitments:
            if item.get("superseded_month") is not None:
                continue
            reasons, delta = [], 0.0
            for tag in item.get("tags", []):
                rule = DRIFT_RULES.get(tag)
                if not rule:
                    continue
                costly, erode_traits, reinforcing, hold_traits = rule
                n_costly = sum(k in costly for k in kinds)
                n_reinforce = sum(k in reinforcing for k in kinds)
                if n_costly:
                    weight = sum(t.get(x, 50) for x in erode_traits) / (100 * len(erode_traits))
                    change = -min(2.0, .6 * n_costly) * (weight - .35) * 2
                    if change < 0:
                        reasons.append(f"events made {tag.replace('_', ' ')} feel costly")
                    delta += change
                if n_reinforce:
                    weight = sum(t.get(x, 50) for x in hold_traits) / (100 * len(hold_traits))
                    change = min(2.0, .6 * n_reinforce) * (weight - .35) * 2
                    if change > 0:
                        reasons.append(f"events reinforced {tag.replace('_', ' ')}")
                    delta += change
            general = stress.get("general", 0)
            if general > 45:
                erosion = (general - 45) / 40 * (1 - t.get("stubbornness", 50) / 100)
                delta -= erosion
                if erosion > .2:
                    reasons.append("sustained pressure")
            for other, rel in m.relationships.items():
                if rel.get("trust", 50) >= 65 and any(v.get("month") == w.month for c in w.member(other).commitments
                                                      for v in c.get("violations", []) if set(c.get("tags", [])) & set(item.get("tags", []))):
                    delta -= .5
                    reasons.append(f"a trusted colleague ({w.member(other).name}) abandoned the same principle")
                elif rel.get("trust", 50) <= 35 and any(v.get("month") == w.month for c in w.member(other).commitments
                                                        for v in c.get("violations", []) if set(c.get("tags", [])) & set(item.get("tags", []))):
                    delta += .4
                    reasons.append(f"a distrusted colleague ({w.member(other).name}) abandoned it")
            audiences = state.get("constituencies", {})
            if "civil_liberties" in item.get("tags", []) and "urban residents and protest groups" in audiences:
                delta += (audiences["urban residents and protest groups"].get("mobilization", 0) - .4) * .5
            if "civil_liberties" in item.get("tags", []) and "police service" in audiences:
                delta -= (1 - audiences["police service"].get("satisfaction", .5) - .5) * .5
            if item.get("reaffirmations") and item["reaffirmations"][-1] == w.month:
                delta += .5
                item["public_salience"] = round(min(100, item.get("public_salience", 75) + 3), 1)
            else:
                item["public_salience"] = round(max(20, item.get("public_salience", 75) - .5), 1)
            delta = clamp(delta, -cap, cap)
            if abs(delta) < 1e-6:
                continue
            before = item.get("internal_strength", 50)
            item["internal_strength"] = round(clamp(before + delta, 5, 100), 1)
            if abs(delta) >= .5:
                item.setdefault("strength_history", []).append(
                    {"month": w.month, "from": before, "to": item["internal_strength"], "reasons": reasons[:3]})
                del item["strength_history"][:-12]
                state.setdefault("commitment_drift", []).append(
                    {"month": w.month, "commitment": item["id"], "delta": round(delta, 2), "reasons": reasons[:3]})
                del state["commitment_drift"][:-20]


def _update_conditions_v2(w: World) -> dict:
    from . import beliefs, commitments, intelligence, memory, standing
    _update_stress(w)
    record = w.agenda.get("this_month") or {}
    before_offices = (record.get("pre_resolution") or {}).get("offices", {})
    for m in w.members:
        state = m.agent_state
        if not state:
            continue
        if before_offices:
            psychology.record_office_changes(w, m.id, state, before_offices)
        if m.status != "active":
            continue
        psychology.role_drift(w, m.id, state)
        psychology.evolve_priorities(w, state)
        psychology.evolve_secret_goal(w, m.id, state)
        psychology.learn_from_outcomes(w, m.id, state)
        for stand in psychology.judge_stands(w, m.id, state):
            _stand_judged(w, m.id, stand)
        psychology.update_confidence(w, m.id, state, record)
        state["priorities"] = [x["goal"] for x in state.get("weighted_priorities", [])[:4]] or state.get("priorities", [])
    drift_commitments(w)
    own, shared = intelligence.office_evidence(w)
    self_reports = (w.intel or {}).get("self_reports", {}) if (w.intel or {}).get("self_reports_month") == w.month else {}
    changes = beliefs.update_all(w, record, own, shared, self_reports)
    w.analytics.setdefault("belief_changes", {})[str(w.month)] = changes
    standing.credit_and_blame(w, w.agenda.get("recent_records", []))
    standing.office_performance(w)
    standing.media_month(w, record, [x for x in (w.intel or {}).get("leaks", []) if x.get("month") == w.month])
    standing.update_members(w)
    memory.decay(w)
    commitments.expire_favors(w)
    return snapshot(w)


def _stand_judged(w: World, mid: str, stand: dict) -> None:
    """A lone dissent, three months on. Proven right: remembered by the dissenter and by those who
    overrode it, with a modest reputation for judgement. Proven wrong: remembered too, quietly."""
    from . import memory, standing
    memory.record_stand_verdict(w, mid, stand)
    if stand.get("verdict") != "failed":
        return
    standing.reputation_effect(w, mid, "vindicated")
    active = {m.id for m in w.active_members()}
    for other in stand.get("supporters", []):
        if other in active and other != mid and mid in w.member(other).relationships:
            _change(w.member(other).relationships[mid], month=w.month, reason="dissenting judgement was vindicated",
                    respect=2, perceived_reliability=1.5)
    w.analytics.setdefault("vindications", []).append(
        {"month": w.month, "member": mid, "motion": stand.get("motion"), "policy": stand.get("subject"),
         "month_adopted": stand.get("month"), "target": stand.get("target"),
         "target_change": stand.get("target_change"), "supporters": list(stand.get("supporters", []))})
    del w.analytics["vindications"][:-40]


def update(w: World, record: dict) -> dict:
    """Convenience entry point for unit tests and small scripted scenarios."""
    update_political(w, record)
    return update_conditions(w)


def snapshot(w: World) -> dict:
    out = {m.id: {
        "clout": m.clout, "alignment": dict(m.alignment), "ideology": m.ideology,
        "ideology_history": list(m.ideology_history),
        "private_disposition": context(w, m.id),
        "constituencies": audiences_for(w, m.id),
        "relationships": {o: {**{k: v for k, v in r.items() if k != "events"},
                               "events": [dict(event) for event in r.get("events", [])[-20:]]}
                          for o, r in m.relationships.items()},
        "stress": dict(m.agent_state.get("stress", {})),
        "stress_trace": [dict(x) for x in m.agent_state.get("stress_trace", [])[-6:]],
        "favor_debts": [dict(x) for x in m.agent_state.get("favor_debts", [])],
        "grievances": [dict(x) for x in m.agent_state.get("grievances", [])],
        "promises": [{k: v for k, v in p.items() if k in ("id", "status", "created_month", "text", "to", "kind")}
                     for p in m.promises],
    } for m in w.members}
    if w.agent_architecture_version >= 2:
        for m in w.members:
            state = m.agent_state or {}
            standing_ = state.get("standing", {})
            out[m.id].update({
                "traits": {k: round(v) for k, v in state.get("traits", {}).items()},
                "role_shift": dict(state.get("role_shift", {})),
                "stress_profile": psychology.stress_profile(state) if state else {},
                "priorities": [dict(x) for x in state.get("weighted_priorities", [])[:5]],
                "secret_goal": {k: v for k, v in (state.get("secret_goal") or {}).items() if k != "history"},
                "long_term_ambitions": [dict(x) for x in _normalize_ambitions(state.get("long_term_ambitions"))] if state.get("long_term_ambitions") else [],
                "ambition_history": [dict(x) for x in state.get("ambition_history", [])][-6:],
                "confidence": state.get("confidence"),
                "beliefs": {pid: round(b.get("confidence", 50)) for pid, b in state.get("propositions", {}).items()},
                "commitments": [{"id": c["id"], "text": c["text"], "strength": c.get("internal_strength"),
                                 "salience": c.get("public_salience"), "violations": len(c.get("violations", [])),
                                 "superseded": c.get("superseded_month") is not None} for c in m.commitments],
                "standing": {"personal_approval": standing_.get("personal_approval"),
                             "capital": standing_.get("capital"), "influence": standing_.get("influence"),
                             "power": dict(standing_.get("power", {})),
                             "reputation": {k: round(v) for k, v in standing_.get("reputation", {}).items()},
                             "media_tone": dict(standing_.get("media_tone", {}))},
                "strategy": {k: v for k, v in (state.get("strategy") or {}).items() if k != "history"},
                "lessons": [dict(x) for x in state.get("policy_lessons", [])[-3:]],
            })
    return out


def _ambitions_text(state: dict) -> str:
    """Render long-term ambitions as soft preferences, never orders."""
    raw = state.get("long_term_ambitions")
    items = _normalize_ambitions(raw) if raw else []
    if not items:
        return ""
    lines = []
    for a in items:
        if a["status"] == "abandoned":
            continue
        tag = " (on hold — only if costs allow)" if a["status"] == "suspended" else ""
        lines.append(
            f"- {a['description']} (importance {a['importance']:.2f}; horizon: {a['time_horizon']}; "
            f"confidence {a['confidence']:.0f}%){tag}. "
            f"Lean: {'; '.join(a['preferred_methods'][:3]) or 'patient work'}. "
            f"Won't do: {'; '.join(a['unacceptable_methods'][:2]) or 'nothing principled'}. "
            f"Current idea: {a['current_strategy'] or 'undecided'}.")
    if not lines:
        return ""
    return ("Long-term ambitions (yours alone; soft preferences, not orders — postpone, weaken or "
            "reinterpret them when costs, principles, stability or new evidence argue otherwise):\n"
            + "\n".join(lines))


def disposition_v2(w: World, mid: str) -> str:
    """PRIVATE INTERNAL DISPOSITION (spec 6, 110): hidden state rendered as plain prose.

    No trait scores appear. Relationships, beliefs, commitments, memory and standing are
    rendered by their own subsystems and composed by decision_context."""
    m, state = w.member(mid), w.member(mid).agent_state
    t = state["traits"]
    g = lambda k: t.get(k, 50)
    lines = ["PRIVATE INTERNAL DISPOSITION (only you see this; it describes tendencies, not orders)"]
    lines.append("You care strongly about keeping influence and dislike being sidelined." if g("ambition") > 67
                 else "You do not seek influence for its own sake." if g("ambition") < 33
                 else "You want enough influence to shape outcomes, not power for its own sake.")
    if g("democratic_commitment") > 62 and g("security_orientation") > 60:
        lines.append("You respect the constitutional process, but under severe security threats you become more willing "
                     "to accept temporary coercive measures.")
    elif g("democratic_commitment") > 62:
        lines.append("Constitutional procedure matters to you even when it is slow.")
    elif g("democratic_commitment") < 38:
        lines.append("You judge procedures by their results; when they block urgent action you are ready to bend them.")
    else:
        lines.append("You value constitutional procedure while weighing it against immediate risks.")
    if g("civil_libertarianism") > 62 and g("nationalism") > 62:
        lines.append("You are a patriot who distrusts a state that silences its own citizens.")
    elif g("civil_libertarianism") > 62:
        lines.append("Restrictions on speech, assembly or privacy carry a high cost in your judgement.")
    elif g("authoritarian_tolerance") > 62:
        lines.append("You believe order sometimes has to be imposed before it can be agreed.")
    if g("fiscal_conservatism") > 62 and g("economic_interventionism") > 55:
        lines.append("You want sound public finances, yet you believe the state must act when markets fail people.")
    elif g("fiscal_conservatism") > 62:
        lines.append("You scrutinize unfunded spending and new debt, even for worthy causes.")
    elif g("economic_interventionism") > 62:
        lines.append("You are willing to use public money and regulation when markets fail people.")
    if g("military_assertiveness") > 62:
        lines.append("You worry that military passivity invites coercion.")
    elif g("military_assertiveness") < 38:
        lines.append("You worry that military escalation can outrun diplomatic control.")
    if g("risk_tolerance") > 62:
        lines.append("You accept significant risk when delay looks worse.")
    elif g("risk_tolerance") < 38:
        lines.append("You prefer cautious, reversible steps.")
    if g("paranoia") > 64:
        lines.append("You tend to assume that others, at home and abroad, are hiding their real intentions.")
    if g("stubbornness") > 65:
        lines.append("Once you have taken a position you find it hard to give ground.")
    elif g("compromise_preference") > 65:
        lines.append("You look for the deal that keeps people on board, even at some cost to your preferred policy.")
    if g("status_sensitivity") > 66:
        lines.append("Being overlooked or upstaged stings; public credit matters to you.")
    if g("patience") > 65 or g("long_term_orientation") > 65:
        lines.append("You tolerate short-term pain for long-term results.")
    lines += psychology.office_attachment(t)
    items = state.get("weighted_priorities") or [{"goal": x, "weight": .6} for x in state.get("priorities", [])]
    if items:
        goals = [item["goal"].replace("preserve my political influence", "preserve your political influence")
                 for item in items[:4]]
        text = f"Above all, you want to {goals[0]}."
        if len(goals) > 1:
            text += f" You also strongly want to {goals[1]}."
        if len(goals) > 2:
            text += " You also want to " + " and to ".join(goals[2:]) + "."
        lines.append(text)
    fears = state.get("fears", [])[:2]
    if fears:
        lines.append("You especially fear " + " and ".join(fears) + ".")
    from .memory import strategy_text
    strategy = strategy_text(w, mid)
    if strategy:
        lines.append(strategy)
    stress = state.get("stress", {})
    general = stress.get("general", 0)
    top = sorted((k for k in ("political", "institutional", "economic", "security", "personal") if stress.get(k, 0) >= 45),
                 key=lambda k: -stress[k])[:2]
    lines.append(f"You are {psychology.stress_level(general)}" + (f", above all about {' and '.join(top)} matters" if top else "") + ".")
    lines.append(psychology.coping_text(state))
    confidence = state.get("confidence", 55)
    if confidence >= 70:
        lines.append("Recent events have left you confident in your own judgement.")
    elif confidence <= 35:
        lines.append("Recent setbacks have shaken your confidence in your own judgement.")
    for lesson in state.get("policy_lessons", [])[-2:]:
        lines.append("Looking back, " + psychology.lesson_text(w, lesson))
    ambitions_block = _ambitions_text(state)
    if ambitions_block:
        lines.append(ambitions_block)
    drifted = [c for c in m.commitments if c.get("superseded_month") is None
               and c.get("internal_strength", 50) < c.get("public_salience", 75) - 25]
    for c in drifted[:1]:
        lines.append(f"Privately, your attachment to your declared principle (\"{c['text'][:90]}\") has weakened "
                     "since you declared it, though the public still expects it of you.")
    return "\n".join(lines)


def secret_goal_context(state: dict) -> str:
    """A salient private motive that can shape a decision without scripting one."""
    goal = state.get("secret_goal") or {}
    if goal.get("status") != "active" or not goal.get("text"):
        return ""
    return ("PRIVATE MOTIVE — confidential; do not disclose it unless you choose.\n"
            f"You want to {goal['text']}. For relevant proposals, votes, orders, or career choices, compare how "
            "the available options advance or obstruct this motive. Let it affect your choice when that impact "
            "outweighs the duties, evidence, principles, relationships, and risks at stake. Do not force unrelated "
            "actions or claim progress the world state has not produced.")


def context(w: World, mid: str) -> str:
    """Render private disposition in prose, without exposing numeric trait scores."""
    ensure(w)
    if w.agent_architecture_version >= 2:
        return disposition_v2(w, mid)
    m, state = w.member(mid), w.member(mid).agent_state
    t = state["traits"]
    lines = ["PRIVATE DISPOSITION"]
    lines.append("You care strongly about maintaining political influence." if t["ambition"] > 67
                 else "You do not seek influence for its own sake." if t["ambition"] < 33
                 else "You have a moderate interest in gaining and retaining political influence.")
    lines.append("You place great weight on constitutional procedure." if t["democratic_commitment"] > 62
                 else "Under pressure, you are more willing to trade procedure for urgent results." if t["democratic_commitment"] < 38
                 else "You value constitutional procedure while weighing it against immediate risks.")
    lines.append("You usually prefer cautious, reversible steps." if t["risk_tolerance"] < 40
                 else "You accept significant risk when delay could be worse." if t["risk_tolerance"] > 60
                 else "Your tolerance for risk depends on the stakes and reversibility.")
    if t["fiscal_conservatism"] > 60:
        lines.append("You scrutinize unfunded spending and new debt, even for worthy causes.")
    elif t["economic_interventionism"] > 60:
        lines.append("You are more willing to use public spending and regulation when markets fail people.")
    if t["civil_libertarianism"] > 60:
        lines.append("Restrictions on speech, assembly or privacy carry a high cost in your judgement.")
    elif t["security_orientation"] > 60:
        lines.append("You give weight to public safety and institutional readiness even when restraint is popular.")
    if t["military_assertiveness"] > 60:
        lines.append("You worry that prolonged military passivity can invite coercion.")
    elif t["military_assertiveness"] < 40:
        lines.append("You worry that military escalation can outrun diplomatic control.")
    lines.append("You pay close attention to how your choices will be remembered." if t["reputation_sensitivity"] > 65
                 else "You may accept reputational costs for outcomes you consider necessary." if t["reputation_sensitivity"] < 35
                 else "Reputation matters, but is one consideration among several.")
    lines.append("Your priorities: " + "; ".join(state["priorities"][:3]) + ".")
    lines.append("Your fears: " + "; ".join(state["fears"][:2]) + ".")
    lines.append("Your longer-term ambitions: " + "; ".join(state["ambitions"]) + ".")
    stress = state["stress"]
    level = ("calm" if stress["general"] < 26 else "pressured" if stress["general"] < 46
             else "stressed" if stress["general"] < 66 else "in crisis" if stress["general"] < 81
             else "under extreme pressure")
    pressure = sorted((k for k in ("political", "institutional", "economic", "security", "personal")
                       if stress.get(k, 0) >= 45), key=lambda k: -stress[k])[:2]
    lines.append(f"You feel {level}. Pressure is strongest around {', '.join(pressure) if pressure else 'the overall situation'}.")
    lines.append(stress_response(state))
    b = state["beliefs"]
    band = lambda v: "high" if v >= 68 else "low" if v <= 32 else "uncertain"
    lines.append("Your assessments, which may be wrong: Union threat " + band(b["union_threat"])
                 + "; constitutional continuity " + band(b["constitutional_trust"])
                 + "; economic outlook " + band(b["economic_outlook"])
                 + "; military reliability " + band(b["military_reliability"]) + ".")
    active = [p for p in m.promises if p.get("status") == "active"]
    recent_motions = [x for x in state.get("motion_outcomes", []) if w.month - x.get("month", -99) <= 12]
    if recent_motions:
        lines.append("Your recent council proposals: " + "; ".join(
            f"Month {x['month'] + 1}: {x['summary']} ({'passed' if x.get('passed') else 'failed'})"
            for x in recent_motions[-4:])
            + ". Reintroduce the same proposal only if conditions or coalition support have materially changed.")
    debts = [x for x in state.get("favor_debts", []) if x.get("status") == "active"]
    if debts:
        lines.append("Political help you may feel obliged to return: " + "; ".join(
            f"{w.member(x['to']).name} supplied a pivotal vote for {x['motion']}"
            for x in debts[-3:]) + ". This is a political expectation, not a forced vote.")
    grievances = [x for x in state.get("grievances", []) if x.get("strength", 0) >= 10]
    if grievances:
        lines.append("Events that still affect your trust: " + "; ".join(
            f"{w.member(x['against']).name} {x['reason']}"
            for x in grievances[:3]) + ". You may forgive or reconsider them.")
    if active:
        lines.append("Your outstanding political commitments: " + "; ".join(
            f"{p['id']}: {p['text']}" + (f" (condition: {p['condition']})" if p.get("condition") else "")
            for p in active[-5:]) + ". They are not forced actions; you may keep, explain or openly withdraw one.")
    for p in [p for p in m.promises if p.get("status") == "broken"][-3:]:
        lines.append(f"You broke commitment {p['id']}: {p['text']}. Other members may remember this.")
    ties = sorted(m.relationships.items(), key=lambda x: -abs(x[1].get("trust", 50) - 50))
    views = []
    for other, rel in ties:
        if w.member(other).status != "active":
            continue
        trust = "trust" if rel["trust"] >= 62 else "distrust" if rel["trust"] <= 38 else "uncertain trust"
        views.append(f"you have {trust} in {w.member(other).name}; respect {band(rel['respect'])}; resentment {band(rel['resentment'])}")
        if len(views) == 3:
            break
    if views:
        lines.append("Your own view of colleagues: " + "; ".join(views) + ". These estimates describe your view, not theirs.")
    audiences = state.get("constituencies", {})
    if audiences:
        relevant = sorted(audiences.items(), key=lambda x: -x[1].get("political_importance", .5))[:5]
        lines.append("Constituency standing estimates, derived from current world conditions: " + "; ".join(
            f"{name}: support for you {band(v.get('support_for_delegate', .5) * 100)}, "
            f"satisfaction {band(v.get('satisfaction', .5) * 100)}, mobilization pressure {band(v.get('mobilization', 0) * 100)}"
            for name, v in relevant) + ". Their priorities include " + "; ".join(
                ", ".join(v.get("priorities", [])[:2]) for _, v in relevant[:3]) + ".")
    return "\n".join(lines)


def relationships_text(w: World, mid: str, focus: set | None = None) -> str:
    """Your own directional view of each colleague, with debts and grievances (spec 10, 12, 13)."""
    m = w.member(mid)
    state = m.agent_state or {}
    level = lambda v, words: words[0] if v >= 70 else words[1] if v >= 55 else words[2] if v >= 40 else words[3] if v >= 25 else words[4]
    lines = ["YOUR VIEW OF COLLEAGUES (your own view; theirs of you may differ)"]
    others = [o for o in w.active_members() if o.id != mid]
    others.sort(key=lambda o: (0 if focus and o.id in focus else 1,
                               -abs(m.relationships.get(o.id, {}).get("trust", 50) - 50)))
    for o in others:
        rel = m.relationships.get(o.id)
        if not rel:
            continue
        parts = [level(rel.get("trust", 50), ("strong trust", "moderate trust", "uncertain trust", "low trust", "deep distrust")),
                 level(rel.get("respect", 50), ("strong respect", "respect", "mixed respect", "little respect", "no respect"))]
        if rel.get("rivalry", 0) >= 40:
            parts.append("a rival" if rel["rivalry"] < 65 else "a serious rival")
        if rel.get("resentment", 0) >= 30:
            parts.append("resentment")
        if rel.get("fear", 0) >= 30:
            parts.append("some fear of them")
        if rel.get("dependency", 0) >= 30:
            parts.append("you depend on them")
        offices = w.offices_of(o.id)
        who = o.name + (f" ({', '.join(offices)})" if offices else "")
        lines.append(f"- {who}: " + ", ".join(parts) + ".")
    debts = [x for x in state.get("favor_debts", []) if x.get("status") == "active"]
    if debts:
        lines.append("You owe political favours: " + "; ".join(
            f"{w.member(x['to']).name} helped you ({x['motion']}, Month {x['month'] + 1})" for x in debts[-3:])
            + ". You feel some obligation to hear their requests fairly; nothing forces you to repay.")
    owed = [(o.name, d) for o in w.members if o.id != mid and o.agent_state
            for d in o.agent_state.get("favor_debts", []) if d.get("to") == mid and d.get("status") == "active"]
    if owed:
        lines.append("Colleagues who owe you: " + "; ".join(f"{name} ({d['motion']})" for name, d in owed[-3:]) + ".")
    grievances = [x for x in state.get("grievances", []) if x.get("strength", 0) >= 10]
    if grievances:
        lines.append("Grievances you still hold: " + "; ".join(
            f"{w.member(x['against']).name} {x['reason']}" + (" (repeatedly)" if x.get("repeats") else "")
            for x in grievances[:3]) + ".")
    return "\n".join(lines)
