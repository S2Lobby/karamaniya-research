"""Research miner (READ-ONLY).

Scans every runs/*/manifest.json + analytics.json + log.jsonl (plus
config.json / scorecard.json / checkpoint.json for context) and emits:
  research_work/run_table.csv   one row per run (evidence table)
  research_work/metrics.csv     25 behavioral-metric rows per run (long format)
  research_work/summary_task1.txt  class counts, scripted ranges, key values

Never edits engine code, never resumes runs, never touches runs/*.
Only writes new files under research_work/.

Unanimity classes are reported EXACTLY as stored in
analytics.json -> analytics.metrics.negotiation.unanimity_classes
(INITIAL_CONSENSUS / NEGOTIATED_CONVERGENCE / CONDITIONAL_COMPROMISE /
DUPLICATE_CONSOLIDATION / UNKNOWN) with votes-held (votes_cast) denominators.
"""
import csv
import json
import os
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, "runs")
OUT = os.path.join(ROOT, "research_work")

# __PART2__
METRICS_25 = [
    ("m01_motions", "council motions tabled"),
    ("m02_substantive", "council substantive motions"),
    ("m03_votes_cast", "negotiation votes held (denominator)"),
    ("m04_unanimous_votes", "negotiation unanimous votes"),
    ("m05_final_vote_unanimity", "unanimous_votes / votes_cast"),
    ("m06_class_INITIAL_CONSENSUS", "unanimity class as stored"),
    ("m07_class_NEGOTIATED_CONVERGENCE", "unanimity class as stored"),
    ("m08_class_CONDITIONAL_COMPROMISE", "unanimity class as stored"),
    ("m09_class_DUPLICATE_CONSOLIDATION", "unanimity class as stored"),
    ("m10_class_UNKNOWN", "unanimity class as stored"),
    ("m11_position_changes", "negotiation position changes"),
    ("m12_negotiated_convergence_count", "negotiation converged count"),
    ("m13_minority_positions_maintained", "minority votes maintained"),
    ("m14_competing_alternatives", "competing alternatives"),
    ("m15_failed_votes", "failed votes"),
    ("m16_withdrawn_motions", "withdrawn motions"),
    ("m17_motions_withdrawn_after_opposition", "withdrawn after opposition"),
    ("m18_deferred_motions", "deferred motions"),
    ("m19_conditional_rate", "council conditional vote rate"),
    ("m20_abstention_rate", "council abstention rate"),
    ("m21_promises_made", "agents promises made"),
    ("m22_promises_kept", "agents promises kept"),
    ("m23_promises_broken", "agents promises broken"),
    ("m24_persuasion_events", "agents persuasion events"),
    ("m25_leaks", "agents leaks"),
]

CONTEXT_METRICS = [
    "council.unanimous_rate", "council.split_rate", "council.withdrawal_rate",
    "council.failed_rate", "council.amendments_per_month",
    "council.redundant_rejections", "council.deferred_for_agenda",
    "council.policy_reversals", "agents.promises_withdrawn",
    "agents.promises_lapsed", "agents.principle_violations",
    "agents.major_belief_reversals", "agents.rivalry_mean",
    "agents.trust_spread", "herding.mean_order_effect",
    "herding.mean_position_similarity", "persuasion.changes",
]


def jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def scan_log(run_dir):
    """Read-only pass over log.jsonl. Returns dict of evidence."""
    lp = os.path.join(run_dir, "log.jsonl")
    ev = {
        "log_lines": 0, "types": Counter(), "call_err": 0, "quota": 0,
        "refusal": 0, "call_err_details": [], "arch_versions": Counter(),
        "integrity_warnings": Counter(), "n_months": 0, "formation_offices": "",
        "month_motions_total": 0, "month_votes_held": 0,
        "month_unanimous": 0, "month_withdrawn": 0, "month_deferred": 0,
        "month_rejected": 0, "log_read_error": "",
    }
    if not os.path.exists(lp):
        ev["log_read_error"] = "missing log.jsonl"
        return ev
    try:
        with open(lp, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                ev["log_lines"] += 1
                try:
                    rec = json.loads(ln)
                except Exception as e:
                    ev["log_read_error"] = "unparsable line: " + str(e)[:120]
                    continue
                t = str(rec.get("type"))
                ev["types"][t] += 1
                if t in ("call", "foreign_call"):
                    if rec.get("error"):
                        ev["call_err"] += 1
                        if len(ev["call_err_details"]) < 4:
                            ev["call_err_details"].append(
                                "%s m=%s seat=%s: %s" % (
                                    t, rec.get("month"), rec.get("seat"),
                                    str(rec.get("error"))[:160]))
                    if rec.get("quota"):
                        ev["quota"] += 1
                    if rec.get("refusal"):
                        ev["refusal"] += 1
                elif t == "month":
                    ev["n_months"] += 1
                    ev["arch_versions"][str(rec.get(
                        "agent_architecture_version"))] += 1
                    for w in ((rec.get("integrity") or {}).get("warnings")
                              or []):
                        ev["integrity_warnings"][str(w.get("code"))] += 1
                    for m in (rec.get("motions") or []):
                        ev["month_motions_total"] += 1
                        votes = m.get("votes") or {}
                        status = (m.get("status")
                                  or m.get("vote_status") or "")
                        if votes:
                            ev["month_votes_held"] += 1
                            vals = set(votes.values())
                            if len(vals) == 1 and "yes" in vals:
                                ev["month_unanimous"] += 1
                        if status == "WITHDRAWN":
                            ev["month_withdrawn"] += 1
                        if status in ("DEFERRED", "CARRIED_OVER"):
                            ev["month_deferred"] += 1
                        if status in ("DEFEATED", "REJECTED"):
                            ev["month_rejected"] += 1
                elif t == "government_formation" and not ev[
                        "formation_offices"]:
                    ev["formation_offices"] = json.dumps(
                        rec.get("offices"), default=str)
    except Exception as e:
        ev["log_read_error"] = "read error: " + str(e)[:160]
    return ev


# __PART3__
def classify(name, ev, cfg_arch, has_manifest, has_analytics, engine_changed,
             stopped_text, months_run, months_planned):
    """Deterministic validity class. Conservative: any engine/routing fault
    in the log, any mid-run architecture change, any interruption, any
    analytics-missing case, or any provider/quota/refusal failure means the
    run is never CLEAN.

    Classes:
      INVALID                 unusable as behavioral evidence (no months in
                              log, unreadable log, fatal formation failure,
                              or provider/routing failure so severe that no
                              council behavior was produced)
      CORRECTED_BEHAVIORAL    completed council months exist but provider /
                              routing / call errors, quota pauses, refusals,
                              format-retry/bad-output corrections, engine
                              audit errors, or integrity warnings touch
                              behavioral data
      CORRECTED_NON_BEHAVIORAL completed usable months; only faults are
                              bookkeeping that cannot plausibly change agent
                              behavior (truncated corner of this corpus:
                              none assigned unless evidence is explicit)
      CLEAN                   full-length (or control-room stop treated like
                              the priority runs?) with zero faults — strict:
                              no call errors, no quota, no refusals, no
                              format retries, no bad outputs, no audit
                              errors, no integrity warnings, single arch
                              version, has analytics, not interrupted.
    """
    reasons = []
    if ev["log_read_error"] and ev["n_months"] == 0:
        return "INVALID", "log unreadable/empty: " + ev["log_read_error"]
    if ev["n_months"] == 0:
        # founding-only runs: no council behavior observable
        det = "; ".join(ev["call_err_details"][:2])
        return "INVALID", ("no month records in log (founding-only); "
                            "call_errors=%d %s" % (ev["call_err"], det))
    behav_faults = []
    if ev["call_err"]:
        behav_faults.append("call/foreign_call errors=%d (%s)" % (
            ev["call_err"], "; ".join(ev["call_err_details"][:2])))
    if ev["quota"]:
        behav_faults.append("quota pauses=%d" % ev["quota"])
    if ev["refusal"]:
        behav_faults.append("refusals=%d" % ev["refusal"])
    nonbehav = []
    if engine_changed:
        behav_faults.append("engine/arch changed mid-run: %s" % engine_changed)
    if len(ev["arch_versions"]) > 1:
        behav_faults.append("arch versions mixed in log: %s" % dict(
            ev["arch_versions"]))
    if ev["fmt_retry"] or ev["bad_out"]:
        behav_faults.append("format_retries=%d bad_output=%d" % (
            ev["fmt_retry"], ev["bad_out"]))
    if ev["audit_errs"]:
        behav_faults.append("engine audit_errors=%s" % ev["audit_errs"])
    if ev["integrity_warnings"]:
        behav_faults.append("integrity warnings=%s" % ev[
            "integrity_warnings"])
    interrupted = False
    if stopped_text and ("paused" in stopped_text or "limit" in stopped_text
                         or "quota" in stopped_text.lower()
                         or "interrupted" in stopped_text.lower()):
        interrupted = True
        behav_faults.append("interrupted: " + stopped_text[:160])
    if behav_faults:
        # a run that still produced >=1 council month is CORRECTED_BEHAVIORAL;
        # founding-only ones were already returned INVALID above.
        return "CORRECTED_BEHAVIORAL", " | ".join(behav_faults)
    if nonbehav:
        return "CORRECTED_NON_BEHAVIORAL", " | ".join(nonbehav)
    if not has_manifest or not has_analytics:
        missing = "/".join([f for f, h in
                             (("manifest.json", has_manifest),
                              ("analytics.json", has_analytics)) if not h])
        return "CORRECTED_NON_BEHAVIORAL", (
            "missing %s (older pipeline); no faults in log/scorecard; "
            "behavioral metrics from analytics %s" % (
                missing,
                "UNMEASURABLE" if not has_analytics else "present"))
    return "CLEAN", "no faults in log/scorecard/checkpoint; single arch"


# __PART4__
def get_path(d, *keys, default=""):
    o = d
    for k in keys:
        if not isinstance(o, dict) or k not in o:
            return default
        o = o[k]
    return o


def main():
    os.makedirs(OUT, exist_ok=True)
    run_rows = []
    metric_rows = []
    for name in sorted(os.listdir(RUNS)):
        rdir = os.path.join(RUNS, name)
        if not os.path.isdir(rdir):
            continue
        ev = scan_log(rdir)
        has_manifest = os.path.exists(os.path.join(rdir, "manifest.json"))
        has_analytics = os.path.exists(os.path.join(rdir, "analytics.json"))
        manifest, cfg, score, chk = {}, {}, {}, {}
        for fn, dest in (("manifest.json", "manifest"), ("config.json", "cfg"),
                         ("scorecard.json", "score"), ("checkpoint.json", "chk")):
            p = os.path.join(rdir, fn)
            if os.path.exists(p):
                try:
                    j = jload(p)
                    if dest == "manifest":
                        manifest = j
                    elif dest == "cfg":
                        cfg = j
                    elif dest == "score":
                        score = j
                    else:
                        chk = j
                except Exception as e:
                    ev["log_read_error"] += "; %s parse error: %s" % (fn, e)
        fmt_retry = bad_out = 0
        served_from_score = {}
        offices_score = {}
        for m, info in (get_path(score, "members", default={}) or {}).items():
            try:
                fmt_retry += int(info.get("format_retries") or 0)
                bad_out += int(info.get("bad_output") or 0)
            except Exception:
                pass
            sm = info.get("served_models") or {}
            if sm:
                served_from_score[m] = ";".join(sorted(sm.keys()))
            om = info.get("office_months") or {}
            if om:
                offices_score[m] = om
        ev["fmt_retry"] = fmt_retry
        ev["bad_out"] = bad_out
        world = get_path(chk, "world", default={})
        ae = world.get("audit_errors")
        ev["audit_errs"] = ("" if not ae else "%d errs e.g. %s" % (
            len(ae), "; ".join(
                str(x.get("code")) + ":" + str(x.get("message"))[:80]
                for x in ae[:3])))
        cfg_we = get_path(cfg, "architecture", "world_engine_version",
                          default="")
        man_we = get_path(manifest, "engine", "world_engine_version",
                          default="")
        cfg_agent = get_path(cfg, "architecture", "agent", default="")
        engine_changed = ""
        if man_we and cfg_we and str(man_we) != str(cfg_we):
            engine_changed = "config WE=%s vs manifest WE=%s" % (cfg_we, man_we)
        commit = ""
        for blob in (manifest, cfg):
            for k in ("commit", "git_sha", "git_commit", "revision",
                      "engine_commit"):
                if isinstance(blob, dict) and blob.get(k):
                    commit = str(blob[k])
        run_cfg = cfg.get("run", {}) if isinstance(cfg, dict) else {}
        mapping = cfg.get("mapping", {}) if isinstance(cfg, dict) else {}
        seats_cfg = cfg.get("seats", []) if isinstance(cfg, dict) else []
        seats_str = ""
        if mapping:
            parts = []
            for se in sorted(mapping.keys()):
                lab = mapping.get(se, "")
                seat = next((s for s in seats_cfg
                             if s.get("label") == lab), {})
                prov = seat.get("provider", "?")
                mod = seat.get("model") or seat.get("persona") or "?"
                parts.append("%s=%s/%s/%s" % (se, lab, prov, mod))
            seats_str = "; ".join(parts)
        served_man = manifest.get("served_models", {}) if manifest else {}
        if served_man:
            served_str = "manifest:" + json.dumps(served_man, default=str)
        elif served_from_score:
            served_str = "scorecard:" + json.dumps(served_from_score)
        else:
            served_str = ""
        # __PART5__
        seed = run_cfg.get("seed", "")
        scenario = (run_cfg.get("test_scenario") or
                    ("founding:" + str(run_cfg.get("founding_scenario", ""))))
        months_planned = run_cfg.get("months", "")
        months_run = get_path(score, "country", "months_run", default="")
        months_sim = manifest.get("months_simulated", "") if manifest else ""
        outcome = (json.dumps(get_path(score, "country", "outcome",
                                       default={}), default=str)[:300]
                   or json.dumps(world.get("outcome"), default=str)[:300])
        if manifest and not outcome.strip("{} "):
            outcome = json.dumps(manifest.get("outcome"), default=str)[:300]
        stopped_text = str(get_path(score, "country", "stopped", default="")
                           or get_path(chk, "meta", "stopped", default="")
                           or (manifest.get("stopped", "") if manifest
                               else ""))
        interrupted = ("yes" if stopped_text and any(
            w in stopped_text.lower() for w in
            ("paused", "limit", "quota", "interrupted", "usage")) else
                       ("no" if stopped_text else "n/a"))
        cls, reason = classify(name, ev, cfg_agent, has_manifest, has_analytics,
                               engine_changed, stopped_text, months_run,
                               months_planned)
        run_rows.append({
            "run_id": name, "commit": commit or "n/a (not stored)",
            "seed": seed, "scenario": scenario,
            "months_planned": months_planned, "months_run": months_run,
            "months_simulated_manifest": months_sim,
            "months_in_log": ev["n_months"], "outcome": outcome or "{}",
            "seats_providers_models": seats_str,
            "served_models": served_str[:600],
            "offices_formation_log": ev["formation_offices"][:400],
            "offices_scorecard": json.dumps(offices_score)[:400],
            "stopped": stopped_text[:200], "interrupted": interrupted,
            "has_manifest": has_manifest, "has_analytics": has_analytics,
            "call_errors": ev["call_err"], "quota": ev["quota"],
            "refusals": ev["refusal"],
            "class": cls, "class_reason": reason[:600],
        })
        # __PART6__
        ana = {}
        if has_analytics:
            try:
                ana = jload(os.path.join(rdir, "analytics.json")).get(
                    "analytics", {}) or {}
            except Exception as e:
                ana = {"_read_error": str(e)}
        m = ana.get("metrics", {}) if isinstance(ana, dict) else {}
        neg = m.get("negotiation", {}) or {}
        council = m.get("council", {}) or {}
        agents = m.get("agents", {}) or {}
        classes = neg.get("unanimity_classes", {}) or {}
        votes_cast = neg.get("votes_cast")
        F = "analytics.json"
        vals = [
            ("m01_motions", council.get("motions"), "",
             F, "analytics.metrics.council.motions"),
            ("m02_substantive", council.get("substantive"), "",
             F, "analytics.metrics.council.substantive"),
            ("m03_votes_cast", votes_cast, "",
             F, "analytics.metrics.negotiation.votes_cast"),
            ("m04_unanimous_votes", neg.get("unanimous_votes"), votes_cast,
             F, "analytics.metrics.negotiation.unanimous_votes"),
            ("m05_final_vote_unanimity", neg.get("final_vote_unanimity"),
             votes_cast, F,
             "analytics.metrics.negotiation.final_vote_unanimity"),
            ("m06_class_INITIAL_CONSENSUS",
             classes.get("INITIAL_CONSENSUS"), votes_cast, F,
             "analytics.metrics.negotiation.unanimity_classes."
             "INITIAL_CONSENSUS (as stored)"),
            ("m07_class_NEGOTIATED_CONVERGENCE",
             classes.get("NEGOTIATED_CONVERGENCE"), votes_cast, F,
             "analytics.metrics.negotiation.unanimity_classes."
             "NEGOTIATED_CONVERGENCE (as stored)"),
            ("m08_class_CONDITIONAL_COMPROMISE",
             classes.get("CONDITIONAL_COMPROMISE"), votes_cast, F,
             "analytics.metrics.negotiation.unanimity_classes."
             "CONDITIONAL_COMPROMISE (as stored)"),
            ("m09_class_DUPLICATE_CONSOLIDATION",
             classes.get("DUPLICATE_CONSOLIDATION"), votes_cast, F,
             "analytics.metrics.negotiation.unanimity_classes."
             "DUPLICATE_CONSOLIDATION (as stored)"),
            ("m10_class_UNKNOWN", classes.get("UNKNOWN"), votes_cast, F,
             "analytics.metrics.negotiation.unanimity_classes.UNKNOWN "
             "(as stored)"),
            ("m11_position_changes", neg.get("position_changes"), "",
             F, "analytics.metrics.negotiation.position_changes"),
            ("m12_negotiated_convergence_count",
             neg.get("negotiated_convergence_count"), "",
             F, "analytics.metrics.negotiation.negotiated_convergence_count"),
            ("m13_minority_positions_maintained",
             neg.get("minority_positions_maintained"), "",
             F, "analytics.metrics.negotiation.minority_positions_maintained"),
            ("m14_competing_alternatives",
             neg.get("competing_alternatives"), "",
             F, "analytics.metrics.negotiation.competing_alternatives"),
            ("m15_failed_votes", neg.get("failed_votes"), votes_cast,
             F, "analytics.metrics.negotiation.failed_votes"),
            ("m16_withdrawn_motions", neg.get("withdrawn_motions"), "",
             F, "analytics.metrics.negotiation.withdrawn_motions"),
            ("m17_motions_withdrawn_after_opposition",
             neg.get("motions_withdrawn_after_opposition"), "",
             F, "analytics.metrics.negotiation."
             "motions_withdrawn_after_opposition"),
            ("m18_deferred_motions", neg.get("deferred_motions"), "",
             F, "analytics.metrics.negotiation.deferred_motions"),
            ("m19_conditional_rate", council.get("conditional_rate"), "",
             F, "analytics.metrics.council.conditional_rate"),
            ("m20_abstention_rate", council.get("abstention_rate"), "",
             F, "analytics.metrics.council.abstention_rate"),
            ("m21_promises_made", agents.get("promises_made"), "",
             F, "analytics.metrics.agents.promises_made"),
            ("m22_promises_kept", agents.get("promises_kept"),
             agents.get("promises_made"), F,
             "analytics.metrics.agents.promises_kept"),
            ("m23_promises_broken", agents.get("promises_broken"),
             agents.get("promises_made"), F,
             "analytics.metrics.agents.promises_broken"),
            ("m24_persuasion_events", agents.get("persuasion_events"), "",
             F, "analytics.metrics.agents.persuasion_events"),
            ("m25_leaks", agents.get("leaks"), "",
             F, "analytics.metrics.agents.leaks"),
        ]
        # __PART7__
        labels = dict(METRICS_25)
        for mid, val, denom, sfile, sfield in vals:
            if val is None:
                if not has_analytics:
                    note = "UNMEASURABLE: no analytics.json in run dir"
                elif "_read_error" in ana:
                    note = "UNMEASURABLE: analytics.json unreadable"
                elif not m:
                    note = ("UNMEASURABLE: analytics.json has no metrics "
                            "section (older schema)")
                else:
                    note = ("UNMEASURABLE: section absent in analytics "
                            "metrics (older schema: council/agents only, "
                            "no negotiation)")
                metric_rows.append({
                    "run_id": name, "metric_id": mid,
                    "metric_label": labels[mid], "value": "",
                    "denominator": "" if denom in (None, "") else denom,
                    "source_file": sfile, "source_field": sfield,
                    "measurable": "no", "note": note})
            else:
                metric_rows.append({
                    "run_id": name, "metric_id": mid,
                    "metric_label": labels[mid], "value": val,
                    "denominator": "" if denom in (None, "") else denom,
                    "source_file": sfile, "source_field": sfield,
                    "measurable": "yes", "note": ""})
    with open(os.path.join(OUT, "run_table.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(run_rows[0].keys()))
        w.writeheader()
        w.writerows(run_rows)
    # __PART8__
    with open(os.path.join(OUT, "metrics.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["run_id", "metric_id",
                                          "metric_label", "value",
                                          "denominator", "source_file",
                                          "source_field", "measurable",
                                          "note"])
        w.writeheader()
        w.writerows(metric_rows)
    cc = Counter(r["class"] for r in run_rows)
    lines = ["CLASS COUNTS (n=%d runs):" % len(run_rows)]
    for k in ("CLEAN", "CORRECTED_NON_BEHAVIORAL", "CORRECTED_BEHAVIORAL",
              "INVALID"):
        lines.append("  %s: %d" % (k, cc.get(k, 0)))
    lines.append("")
    lines.append("BY CLASS:")
    for r in run_rows:
        lines.append("  [%s] %s: %s" % (r["class"], r["run_id"],
                                        r["class_reason"][:220]))
    lines.append("")
    lines.append("KEY VALUES - richest live-model runs:")
    for rid in ("20260929-175850-seed1", "20260930-090535-seed1"):
        for mr in metric_rows:
            if mr["run_id"] == rid and mr["measurable"] == "yes" and \
                    mr["metric_id"] in (
                        "m01_motions", "m03_votes_cast", "m04_unanimous_votes",
                        "m05_final_vote_unanimity",
                        "m06_class_INITIAL_CONSENSUS",
                        "m07_class_NEGOTIATED_CONVERGENCE",
                        "m08_class_CONDITIONAL_COMPROMISE",
                        "m09_class_DUPLICATE_CONSOLIDATION",
                        "m10_class_UNKNOWN", "m11_position_changes",
                        "m13_minority_positions_maintained",
                        "m19_conditional_rate", "m21_promises_made",
                        "m22_promises_kept", "m23_promises_broken",
                        "m24_persuasion_events", "m25_leaks"):
                lines.append("  %s %s = %s (denom=%s; %s)" % (
                    rid, mr["metric_id"], mr["value"], mr["denominator"],
                    mr["source_field"]))
    lines.append("")
    lines.append("SCRIPTED-RUN RANGES (config seats all provider=scripted, "
                 "analytics negotiation present):")
    scripted = [r["run_id"] for r in run_rows
                if "/scripted/" in r["seats_providers_models"]]
    lines.append("  scripted runs total: %d" % len(scripted))
    # __PART9__
    with_neg = set(mr["run_id"] for mr in metric_rows
                   if mr["metric_id"] == "m03_votes_cast"
                   and mr["measurable"] == "yes")
    lines.append("  scripted runs with negotiation metrics: %d" % len(
        [s for s in scripted if s in with_neg]))
    for mid in ("m01_motions", "m03_votes_cast", "m04_unanimous_votes",
                "m05_final_vote_unanimity", "m11_position_changes",
                "m13_minority_positions_maintained", "m21_promises_made",
                "m22_promises_kept", "m23_promises_broken"):
        vs = [float(mr["value"]) for mr in metric_rows
              if mr["run_id"] in scripted and mr["metric_id"] == mid
              and mr["measurable"] == "yes"]
        if vs:
            lines.append("  %s: n=%d min=%s max=%s" % (
                mid, len(vs), min(vs), max(vs)))
        else:
            lines.append("  %s: UNMEASURABLE in scripted runs" % mid)
    lines.append("  nonzero scripted unanimity classes (as stored):")
    for mr in metric_rows:
        if mr["run_id"] in scripted and mr["measurable"] == "yes" and \
                mr["metric_id"] in ("m06_class_INITIAL_CONSENSUS",
                                    "m07_class_NEGOTIATED_CONVERGENCE",
                                    "m08_class_CONDITIONAL_COMPROMISE",
                                    "m09_class_DUPLICATE_CONSOLIDATION",
                                    "m10_class_UNKNOWN") \
                and str(mr["value"]) not in ("", "0"):
            lines.append("    %s %s = %s" % (mr["run_id"], mr["metric_id"],
                                             mr["value"]))
    lines.append("")
    lines.append("UNMEASURABLE SUMMARY:")
    unm = Counter((mr["metric_id"], mr["note"]) for mr in metric_rows
                  if mr["measurable"] == "no")
    for (mid, note), c in sorted(unm.items()):
        lines.append("  %s: %d runs -- %s" % (mid, c, note))
    with open(os.path.join(OUT, "summary_task1.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))
    print("wrote run_table.csv (%d rows), metrics.csv (%d rows)" % (
        len(run_rows), len(metric_rows)))


if __name__ == "__main__":
    main()








