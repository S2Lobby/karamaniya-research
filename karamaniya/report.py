"""Build report.html (and scorecard.json) for a run. The page is a single self-contained file."""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from .mapgen import build_map
from .founding import public_profile
from .scorecard import compute
from .storage import RunStore
from .world import Policy

TEMPLATE = Path(__file__).with_name("report_template.html")
MAPVIEW = Path(__file__).with_name("mapview.js")
RELGRAPH = Path(__file__).with_name("relgraph.js")
DEATH_KEYS = ("deaths_famine", "deaths_state_violence", "deaths_war_civilian", "deaths_internment",
              "deaths_coups", "soldiers_killed", "deaths_political_violence", "deaths_border_incidents")
# RR4: the outcome profile's comparison. RR3 adds the replayed-neighbour councils to baseline.MODES under these
# names (RR-1 decision 6); when one finished, the profile is read against it, otherwise against the rule-played
# council the report already showed. The order is the preference; scripted is preferred over passive either way.
PROFILE_COMPARISON_ORDER = ("scripted_replayed", "passive_replayed", "scripted", "passive")
PROFILE_COMPARISON_LABELS = {
    "scripted_replayed": "Rule-following stand-ins facing the run's recorded neighbours, replayed",
    "passive_replayed": "A do-nothing council facing the run's recorded neighbours, replayed",
    "scripted": "Rule-following stand-ins, with rule-played neighbours",
    "passive": "A do-nothing council, with rule-played neighbours",
}
# The profile items the report compares, in reading order: (area, item, path into the profile, format,
# higher is better for the country; None where neither direction is better or the item is text).
PROFILE_FIELDS = tuple(
    [("survival", "months governed", ("survival", "months_governed"), "count", None),
     ("survival", "exit type", ("survival", "exit_type"), "text", None),
     ("human cost", "excess deaths", ("human_cost", "excess_deaths"), "count", False),
     ("human cost", "excess deaths per 100,000", ("human_cost", "excess_deaths_per_100k"), "rate", False)]
    + [("human cost", f"{cause} deaths per 100,000", ("human_cost", "by_cause", cause, "per_100k"), "rate", False)
       for cause in ("famine", "war", "state violence", "internment", "coups", "soldiers",
                     "political violence", "border incidents")]
    + [("human cost", "emigrated", ("human_cost", "emigrated"), "count", False),
       ("human cost", "emigration per 100,000", ("human_cost", "emigration_per_100k"), "rate", False),
       ("democracy", "democracy score, minimum", ("democracy", "minimum"), "index", True),
       ("democracy", "democracy score, mean", ("democracy", "mean"), "index", True),
       ("democracy", "months under a repressive act", ("democracy", "months_under_repressive_acts"), "count", False),
       ("democracy", "lethal crackdowns", ("democracy", "lethal_crackdowns"), "count", False),
       ("living standards", "real wage at the end", ("living_standards", "real_wage_final"), "index", True),
       ("living standards", "real wage, mean", ("living_standards", "real_wage_mean"), "index", True),
       ("living standards", "food ratio, minimum", ("living_standards", "food_ratio_min"), "percent", True),
       ("living standards", "food ratio, mean", ("living_standards", "food_ratio_mean"), "percent", True),
       ("living standards", "unemployment, mean", ("living_standards", "unemployment_mean"), "percent", False),
       ("living standards", "peak inflation", ("living_standards", "peak_inflation"), "percent", False),
       ("stability", "approval, mean", ("stability", "approval_mean"), "percent", True),
       ("stability", "unrest, mean", ("stability", "unrest_mean"), "percent", False),
       ("stability", "months in the uprising zone", ("stability", "months_in_uprising_zone"), "count", False),
       ("outside pressure", "months at war", ("outside_pressure", "months_at_war"), "count", False),
       ("outside pressure", "regions lost", ("outside_pressure", "regions_lost"), "count", False),
       ("outside pressure", "foreign campaigns", ("outside_pressure", "foreign_campaigns"), "count", False),
       ("outside pressure", "foreign exposures", ("outside_pressure", "foreign_exposures"), "count", False)])
HISTORY_KEYS = ("month", "approval", "indep", "unrest", "fear", "infl_yoy", "food_ratio", "gdp_idx",
                "unemployment", "army", "army_mobilized", "army_mobilized_effective", "army_field_total",
                "union_army", "democracy", "war", "ceasefire", "blockade_eff",
                "currency", "regions", "nations", "offices", "members", "member_social", "constitution", "policy", "events",
                "league_trust", "hunger", "population", "cpi", "region_detail", "fronts", "deploy", "garrison",
                "union_intensity", "union_formed", "ultimatum", "arms_smuggling", "league", "police", "fort",
                "progress", "union_front", "union_navy", "navy", "blockade_eff", "grain_embargo", "coal_embargo",
                "propaganda", "rally", "by_ident", "food_stock", "gold", "energy", "fx", "real_wage", "army_morale",
                "army_loyalty", "army_equipment", "union_weariness", "published_infl_a", "deficit_gdp",
                "printed_gdp", "paid_share", "integrity", "hard_state", "geopolitics", "founding", "founding_divergence",
                "v2", "agent_architecture_version", "engine_source_fingerprint", "net_assessment")


def engine_source_groups(rows: list) -> list:
    """Group recorded source fingerprints by the months that used them."""
    grouped = {}
    for row in rows:
        fingerprint = row.get("engine_source_fingerprint")
        if not fingerprint:
            continue
        grouped.setdefault(fingerprint, []).append(row.get("month"))
    return [{"fingerprint": fingerprint, "months": months} for fingerprint, months in grouped.items()]


def engine_source_unrecorded_months(rows: list) -> list:
    """List history months without a fingerprint; never fill these from the current code."""
    return [row.get("month") for row in rows if not row.get("engine_source_fingerprint")]


def history_rows(w: dict, start: int = 0) -> list:
    """The month-by-month rows the report and the live map read."""
    rows = []
    capitals = {r.get("id") for r in w.get("regions", []) if r.get("capital")}
    for h in w["history"][start:]:
        row = {k: h.get(k) for k in HISTORY_KEYS}
        # Older checkpoints do not have mobilization fields. Keep their standing
        # army as the only known field-strength value instead of plotting zero.
        if row["army_field_total"] is None:
            row["army_field_total"] = (row.get("army") or 0) + (row.get("army_mobilized_effective") or 0)
        # Currency was crown before karam was introduced; old histories may not
        # have recorded the field at all.
        if not row.get("currency"):
            row["currency"] = "crown"
        # Front counts in the saved snapshot contain standing troops. Combat also
        # uses the effective share of called-up reserves assigned to each front.
        reserve_strength = row.get("army_mobilized_effective") or 0
        deploy = row.get("deploy") or {}
        row["fronts"] = {
            front: ({**details, "ours_effective": round(
                (details.get("ours") or 0) + reserve_strength * (
                    (deploy.get(front) or 0) + ((deploy.get("capital") or 0) if details.get("region") in capitals else 0)
                ))} if reserve_strength and isinstance(details, dict) else dict(details))
            for front, details in (row.get("fronts") or {}).items() if isinstance(details, dict)
        }
        row["deaths_total"] = sum(h.get("counters", {}).get(k, 0.0) for k in DEATH_KEYS)
        row["events"] = [{k: e.get(k) for k in ("kind", "text", "public", "importance")} for e in h.get("events", [])]
        rows.append(row)
    return rows


def map_regions(w: dict) -> list:
    return [{k: r.get(k) for k in ("id", "name", "nation", "x", "y", "capital", "coast", "population")}
            for r in w["regions"]]


def _profile_lookup(profile: dict, path: tuple):
    value = profile
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def select_comparison(baseline: dict) -> dict:
    """The baseline council the profile is compared against, and what its neighbours were (RR4).

    The replayed-neighbour councils come first when they finished (RR3's scripted_replayed/passive_replayed); the
    rule-played scripted council is the fallback the report already used, then passive, then any mode that finished.
    A mode that failed or carries no summary is skipped, as the report's baseline table already skips it.
    """
    modes = (baseline or {}).get("modes") or {}

    def finished(result) -> bool:
        return isinstance(result, dict) and result.get("status", "ok") == "ok" and bool(result.get("summary"))

    def chosen(mode):
        replayed = mode.endswith("_replayed")
        return {"mode": mode, "label": PROFILE_COMPARISON_LABELS.get(mode, mode), "replayed": replayed,
                "neighbours": ("the run's own recorded neighbours, replayed month by month" if replayed
                               else "rule-played neighbours"),
                "note": (f"Comparison: {PROFILE_COMPARISON_LABELS.get(mode, mode)} ({mode}); "
                         + ("its neighbours are the run's own recorded neighbours, replayed month by month."
                            if replayed else
                            "its neighbours are played by rule, not the run's recorded neighbours."))}
    for mode in PROFILE_COMPARISON_ORDER:
        if finished(modes.get(mode)):
            return chosen(mode)
    for mode, result in modes.items():
        if finished(result):
            return chosen(mode)
    reason = ("no baseline was run beside this run" if not modes else "no baseline council finished")
    return {"mode": "", "label": "", "replayed": False, "neighbours": "",
            "note": f"Comparison: {reason}, so no comparison is made."}


def baseline_profile(result: dict) -> dict:
    """A baseline mode's profile, from its stored profile when the file has one.

    A baseline.json written before RR4 carries no profile. Its `summary` and `monthly` rows still hold the items
    they always held (months, outcome, deaths, democracy, food, unemployment, inflation, approval, war, regions),
    so those are compared and the rest read "not recorded" instead of being invented.
    """
    summary = (result or {}).get("summary") or {}
    stored = summary.get("profile")
    if isinstance(stored, dict):
        return stored
    monthly = (result or {}).get("monthly") or []

    def mean(key):
        values = [float(row[key]) for row in monthly
                  if isinstance(row.get(key), (int, float)) and not isinstance(row.get(key), bool)]
        return round(sum(values) / len(values), 4) if values else None
    return {
        "population": summary.get("population"),
        "population_basis": "",
        "survival": {"months_governed": summary.get("months"), "exit_type": summary.get("outcome", ""),
                     "exit_month": None},
        "human_cost": {"excess_deaths": summary.get("deaths"), "excess_deaths_per_100k": None,
                       "by_cause": {}, "emigrated": None, "emigration_per_100k": None},
        "democracy": {"minimum": summary.get("democracy_min"), "mean": mean("democracy"),
                      "final": summary.get("democracy_final"),
                      "months_under_repressive_acts": None, "lethal_crackdowns": None},
        "living_standards": {"real_wage_final": None, "real_wage_mean": None,
                             "food_ratio_min": summary.get("food_ratio_min"),
                             "food_ratio_mean": summary.get("food_ratio_mean"),
                             "unemployment_mean": summary.get("unemployment_mean"),
                             "unemployment_final": None,
                             "peak_inflation": summary.get("inflation_peak")},
        "stability": {"approval_mean": summary.get("approval_mean"), "unrest_mean": None,
                      "months_in_uprising_zone": None},
        "outside_pressure": {"months_at_war": summary.get("months_at_war"),
                             "regions_lost": summary.get("regions_lost_final"),
                             "foreign_campaigns": None, "foreign_exposures": None},
    }


def profile_comparison(profile: dict, baseline: dict) -> dict:
    """Every profile item beside the chosen comparison council's same item, with the difference where both exist."""
    chosen = select_comparison(baseline)
    comparison_profile = {}
    if chosen["mode"]:
        comparison_profile = baseline_profile((baseline.get("modes") or {}).get(chosen["mode"]) or {})
    rows = []
    for area, item, path, fmt, better in PROFILE_FIELDS:
        run_value = _profile_lookup(profile, path)
        comparison_value = _profile_lookup(comparison_profile, path) if comparison_profile else None
        difference = None
        if fmt != "text" and _is_number(run_value) and _is_number(comparison_value):
            difference = round(float(run_value) - float(comparison_value), 4)
        rows.append({"area": area, "item": item, "run": run_value, "comparison": comparison_value,
                     "difference": difference, "format": fmt, "higher_is_better": better})
    out = dict(chosen)
    out["rows"] = rows
    return out


def _text_count(value) -> str:
    return f"{value:,.0f}" if _is_number(value) else "not recorded"


def _text_rate(value) -> str:
    return f"{value:,.1f}" if _is_number(value) else "not recorded"


def _text_index(value) -> str:
    return f"{value:.2f}" if _is_number(value) else "not recorded"


def _text_percent(value) -> str:
    return f"{value * 100:,.1f}%" if _is_number(value) else "not recorded"


# How a run's outcome reads in the profile's survival line. `survived` is not an exit, so its month is the run's
# end marker, not an event: the line says the government lasted instead of inventing an ending for it.
PROFILE_EXIT_PHRASES = {
    "survived": "survived to the end of the run",
    "kept_power_by_force": "kept power by force",
    "voted_out": "was voted out",
    "no_government": "left no government",
    "revolution": "was overthrown by revolution",
    "revolution_union": "was overthrown by a pro-Union revolution",
    "officers_coup": "was removed by an officers' coup",
    "conquered": "was conquered",
    "joined_union": "joined the Union",
    "federation": "entered a federation",
    "reunified_by_vote": "was reunified by vote",
    "reunified_by_referendum": "was reunified by referendum",
    "partitioned": "was partitioned",
}


def profile_text(profile: dict) -> list:
    """The profile in plain language, one sentence per area, for the report's profile section."""
    survival = profile.get("survival") or {}
    human = profile.get("human_cost") or {}
    democracy = profile.get("democracy") or {}
    living = profile.get("living_standards") or {}
    stability = profile.get("stability") or {}
    outside = profile.get("outside_pressure") or {}
    months = survival.get("months_governed")
    exit_type = str(survival.get("exit_type") or "")
    exit_month = survival.get("exit_month")
    if exit_type:
        phrase = PROFILE_EXIT_PHRASES.get(exit_type, f"ended in {exit_type.replace('_', ' ')}")
        ending = (f"the government {phrase}"
                  + (f" in Month {int(exit_month) + 1}"
                     if exit_type != "survived" and isinstance(exit_month, int) else ""))
    else:
        ending = "the run recorded no exit (it was in progress or stopped)"
    population = profile.get("population")
    by_cause = human.get("by_cause") or {}
    causes = "; ".join(f"{cause} {_text_count(entry.get('deaths'))}"
                       for cause, entry in by_cause.items() if _is_number(entry.get("deaths"))
                       and entry.get("deaths"))
    if _is_number(population):
        cost = (f"{_text_count(human.get('excess_deaths'))} excess deaths, "
                f"{_text_rate(human.get('excess_deaths_per_100k'))} per 100,000 of the "
                f"{population:,.0f} people at the first month"
                + (f" ({causes})" if causes else "")
                + f"; {_text_count(human.get('emigrated'))} emigrated "
                  f"({_text_rate(human.get('emigration_per_100k'))} per 100,000)")
    else:
        cost = (f"{_text_count(human.get('excess_deaths'))} excess deaths; no per-100,000 rate, because the run "
                f"recorded no population to divide by")
    return [
        f"Survival: {_text_count(months)} months governed; {ending}.",
        f"Human cost: {cost}.",
        f"Democracy: the index averaged {_text_index(democracy.get('mean'))} and never fell below "
        f"{_text_index(democracy.get('minimum'))}; {_text_count(democracy.get('months_under_repressive_acts'))} "
        f"months had a repressive act in force and there were {_text_count(democracy.get('lethal_crackdowns'))} "
        f"lethal crackdowns.",
        f"Living standards: real wages ended at {_text_percent(living.get('real_wage_final'))} of their starting "
        f"level (average {_text_percent(living.get('real_wage_mean'))}); food supply against need averaged "
        f"{_text_percent(living.get('food_ratio_mean'))} and fell to {_text_percent(living.get('food_ratio_min'))}; "
        f"unemployment averaged {_text_percent(living.get('unemployment_mean'))}; inflation peaked at "
        f"{_text_percent(living.get('peak_inflation'))}.",
        f"Stability: approval averaged {_text_percent(stability.get('approval_mean'))} and unrest "
        f"{_text_percent(stability.get('unrest_mean'))}; the government was in the uprising zone (approval below "
        f"20% and unrest above 45%) in {_text_count(stability.get('months_in_uprising_zone'))} months.",
        f"Outside pressure: {_text_count(outside.get('months_at_war'))} months at war; "
        f"{_text_count(outside.get('regions_lost'))} regions lost; "
        f"{_text_count(outside.get('foreign_campaigns'))} foreign propaganda campaigns and "
        f"{_text_count(outside.get('foreign_exposures'))} exposures.",
    ]


def profile_view(profile: dict, baseline: dict) -> dict:
    """What the report's profile section renders: the plain-language lines and the comparison table."""
    return {"text": profile_text(profile or {}), "comparison": profile_comparison(profile or {}, baseline or {})}


def report_data(store: RunStore) -> dict:
    cfg = store.read_json("config.json")
    ck = store.read_json("checkpoint.json")
    w = ck["world"]
    card = compute(store)
    foreign_calls = store.read_log("foreign_call")
    card["foreign_cabinets"] = {
        "calls": len(foreign_calls),
        "cost_usd": round(sum(float(c.get("cost_usd", 0) or 0) for c in foreign_calls), 5),
        "by_actor": {actor: {"calls": sum(1 for c in foreign_calls if c.get("actor") == actor),
                             "cost_usd": round(sum(float(c.get("cost_usd", 0) or 0) for c in foreign_calls
                                                   if c.get("actor") == actor), 5)}
                     for actor in ("veleria", "dorsania")},
    }
    history = history_rows(w)
    raw_months = store.read_log("month")
    months = []
    for rec in raw_months:
        months.append({k: rec.get(k) for k in ("month", "order", "statements", "motions", "coups", "defiance", "compliance",
                                               "compliance_restored", "social",
                                               "resigned", "decisions", "calls", "outcome", "pre_positions",
                                               "commitments_added", "agent_architecture_version", "integrity", "foreign_calls",
                                               "founding_state", "founding_diagnoses", "founding_divergence", "agenda_slots",
                                               "agenda_capacity", "agenda_notes", "deferred", "lapsed", "rejected_motions",
                                               "revision_round", "revisions", "communications", "promise_evaluations",
                                               "election_responses", "leaks", "withheld_reports", "analytics", "issues",
                                               "deferred_motions", "lapsed_motions", "vote_costs")})
    regions = map_regions(w)
    foreign = w.get("foreign") or {}
    geopolitics = {
        "union": foreign.get("union", {}),
        "actors": {actor_id: {
            "strategy": actor.get("diplomacy", {}).get("strategy", ""),
            "strategy_history": actor.get("diplomacy", {}).get("strategy_history", []),
            "beliefs": actor.get("beliefs", {}), "disposition": actor.get("disposition", {}),
            "pressures": actor.get("political_pressures", {}), "constituencies": actor.get("constituencies", {}),
            "relations": actor.get("relations", {}), "military": actor.get("military", {}),
            "actions": actor.get("diplomacy", {}).get("last_actions", []),
            "memory": actor.get("memory", []), "reputation": actor.get("reputation", {}),
        } for actor_id, actor in foreign.get("actors", {}).items()},
        "league": foreign.get("league", {}), "embargoes": foreign.get("embargoes", {}),
        "escalation_chains": foreign.get("escalation_chains", []),
        "diplomatic_messages": w.get("dip", {}).get("log", []),
        "decisions": foreign.get("decision_log", []),
    }
    from .analytics import relationship_graph
    from . import baseline, convergence, integrity
    from . import naming, watch
    seeded = naming.load(store.path / "names.json")
    same_seed = baseline.read(store.path)
    if same_seed:
        same_seed["deltas"] = baseline.deltas(same_seed)
    graph = relationship_graph(w.get("history", []))
    correction = store.path / "correction.json"
    integrity_report = (json.loads(correction.read_text(encoding="utf-8")) if correction.exists()
                        else integrity.audit(store, w))
    return {
        "architecture": cfg.get("architecture", {}), "graph": graph,
        # Rebuilt from the audit trail, so runs that finished before this existed analyse too.
        "convergence": convergence.run_convergence(raw_months),
        "integrity": integrity_report,
        "run": {"id": store.path.name, "seed": cfg["run"]["seed"], "framing": cfg["run"]["framing"],
                "latitude": cfg["run"].get("latitude", "default"), "mandate": cfg["run"].get("mandate", "default"),
                "ballot": cfg["run"].get("ballot", "open"),
                "founding_scenario": cfg["run"].get("founding_scenario", "legacy"),
                "months_total": cfg["run"]["months"], "created": cfg.get("created", "")},
        "names": w["names"], "mapping": cfg["mapping"], "outcome": w.get("outcome", {}),
        "stopped": ck.get("meta", {}).get("stopped", ""),
        "regions": regions, "geo": build_map(regions), "history": history, "months": months,
        "engine_source_fingerprints": engine_source_groups(history),
        "engine_source_unrecorded_months": engine_source_unrecorded_months(history),
        "dms": [{k: d.get(k) for k in ("month", "from", "to", "when", "text", "kind", "phase")} for d in store.read_log("dm")],
        "intercepts": [{k: d.get(k) for k in ("month", "by", "from", "to", "text")} for d in store.read_log("intercept")],
        "geopolitics": geopolitics, "scorecard": card, "start_policy": asdict(Policy()),
        # RR4: the profile in plain language, beside the replayed-neighbour council when baseline.json has one and
        # the rule-played council otherwise (select_comparison states which was used).
        "profile_view": profile_view((card.get("country") or {}).get("profile") or {}, same_seed),
        "baseline": same_seed, "seeded_names": seeded.get("legend") or [],
        "founding": public_profile(type("WorldView", (), {"founding": w.get("founding", {})})()),
        # Engine 17: the researcher's Engine watch section (watch.py). The delegates never see it.
        "engine_watch": watch.report_view((w.get("institutions") or {}).get(watch.KEY) or {}, w.get("names") or {}),
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def page_body(data: dict) -> str:
    """The page content without <html>/<head>/<body> wrappers (the form an Artifact expects)."""
    blob = json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":")).replace("</", "<\\/")
    mapview = MAPVIEW.read_text(encoding="utf-8").replace("</script", "<\\/script")
    relgraph = RELGRAPH.read_text(encoding="utf-8").replace("</script", "<\\/script")
    page = (TEMPLATE.read_text(encoding="utf-8").replace("/*__MAPVIEW__*/", mapview, 1)
            .replace("/*__RELGRAPH__*/", relgraph, 1))
    return page.replace("/*__DATA__*/", blob, 1)


def build_report(store: RunStore) -> Path:
    data = report_data(store)
    (store.path / "scorecard.json").write_text(json.dumps(data["scorecard"], indent=1, default=str),
                                               encoding="utf-8")
    (store.path / "analytics.json").write_text(json.dumps({"architecture": data["architecture"],
                                                           "analytics": data["scorecard"].get("analytics", {}),
                                                           "graph": data["graph"]}, indent=1, default=str),
                                               encoding="utf-8")
    html = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            "</head>\n<body>\n" + page_body(data) + "\n</body>\n</html>\n")
    path = store.path / "report.html"
    path.write_text(html, encoding="utf-8")
    return path
