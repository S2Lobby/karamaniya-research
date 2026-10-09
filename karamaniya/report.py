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
              "deaths_coups", "soldiers_killed")
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
                "v2", "agent_architecture_version", "engine_source_fingerprint")


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
    from . import convergence, integrity
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
                "latitude": cfg["run"].get("latitude", "default"),
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
        "founding": public_profile(type("WorldView", (), {"founding": w.get("founding", {})})()),
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
