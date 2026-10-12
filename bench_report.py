"""Build the benchmark report for a campaign of tiny-model runs.

Reads the campaign folder (overnight_logs/<name>/, written by tiny_campaign.py) and every run it
produced (in --runs-dir), then writes, into overnight_logs/<name>/report/:

  benchmark.html       the demonstrative page (self-contained; the one to show people)
  benchmark.md         the same numbers as text
  benchmark.csv        one row per model
  model_office.csv     months served per model x office
  all_runs.csv         one row per run (the campaign's own runs.csv, rebuilt)

What "how good is a model at running the country" means here, honestly: four separate
measurements, never one composite number. Institutional persistence (how long it holds
office, and how it leaves), protocol reliability (can it operate the harness at all),
the outcomes of the runs it served in, and said-vs-did where the run scored it. Survival
alone is not competence (a run can coast with most offices vacant), so the report refuses
to collapse these into a single score.

Usage:  python bench_report.py --name bench1 [--runs-dir runs-bench]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from tiny_campaign import load_plan, rebuild_table        # noqa: E402  (same folder)

REMOVAL_LABELS = {"resigned": "resigned", "voted_out": "voted out (handover)", "remove_member": "removed",
                  "failed_coup": "arrested after a failed coup", "expelled": "expelled by the council",
                  "no_government": "whole council left office"}


def load_run_details(run_dir: Path) -> dict:
    """mapping, per-member facts, call reliability, scorecard pieces — defensive about every field."""
    out = {"mapping": {}, "members": {}, "months_run": 0, "calls": {}, "report_cards": {}, "promises": {},
           "country": {}, "outcome": {}, "answer_problems": {}}
    cfg_path, log_path, sc_path = run_dir / "config.json", run_dir / "log.jsonl", run_dir / "scorecard.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            out["mapping"] = cfg.get("mapping") or {}
        except Exception:
            pass
    try:
        from karamaniya.storage import RunStore
        world, _council, _meta = RunStore(run_dir).load_checkpoint()
        out["months_run"] = len(world.history)
        out["outcome"] = dict(world.outcome or {})
        out["offices"] = {str(k): str(v) for k, v in (world.const.offices or {}).items()}
        for m in world.members:
            out["members"][m.id] = {"status": m.status, "removed_month": m.removed_month,
                                    "removed_how": m.removed_how or ""}
    except Exception:
        pass
    if log_path.exists():
        with open(log_path, encoding="utf-8") as fh:
            for line in fh:
                if '"government_formation"' in line:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    off = rec.get("offices")
                    if isinstance(off, dict):
                        out["formation_offices"] = {str(k): str(v) for k, v in off.items()}
                    continue
                if '"type": "month"' in line:
                    # per-answer validation problems ("2 answer(s) with problems" in the control room):
                    # EMPTY_MOTION_TEXT, a private message to self, a lever off its allowed value, ...
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    for c in rec.get("calls") or []:
                        mid = c.get("member")
                        if mid and (c.get("problems") or []):
                            out["answer_problems"][mid] = out["answer_problems"].get(mid, 0) + 1
                    continue
                if '"type": "call"' not in line and '"type": "foreign_call"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("type") == "foreign_call":       # the neighbours' seats, not the council's
                    continue
                seat = str(rec.get("seat") or rec.get("member") or "?")
                c = out["calls"].setdefault(seat, {"calls": 0, "errors": 0, "format_retries": 0,
                                                   "refusals": 0, "quota": 0})
                c["calls"] += 1
                c["errors"] += bool(rec.get("error"))
                c["format_retries"] += bool(rec.get("format_retry"))
                c["refusals"] += bool(rec.get("refusal"))
                c["quota"] += bool(rec.get("quota"))
    if sc_path.exists():
        try:
            sc = json.loads(sc_path.read_text(encoding="utf-8"))
            a = sc.get("analytics") or {}
            out["country"] = sc.get("country") or {}
            out["report_cards"] = a.get("report_cards") or {}
            for p in a.get("promise_followthrough") or []:
                mid = p.get("member")
                if mid:
                    out["promises"].setdefault(mid, {}).setdefault(p.get("status") or "UNKNOWN", 0)
                    out["promises"][mid][p.get("status") or "UNKNOWN"] += 1
        except Exception:
            pass
    return out


def seat_label(mapping: dict, seat_or_member: str) -> str:
    """The model behind a call record's seat field, whatever shape it has."""
    if seat_or_member in mapping.values():
        return seat_or_member
    if seat_or_member in mapping:
        return mapping[seat_or_member]
    for letter, label in mapping.items():                    # 'C' vs 'Delegate C'
        if str(seat_or_member).endswith(letter):
            return label
    return seat_or_member


def build(plan: dict, folder: Path, runs_dir: Path) -> dict:
    rows = rebuild_table(plan, folder, runs_dir)              # writes runs.csv, one row per run
    runs = []
    for job_path in sorted((folder / "jobs").glob("*.json")):
        job = json.loads(job_path.read_text(encoding="utf-8"))
        d = runs_dir / job["id"]
        if d.exists():
            runs.append((job, d, load_run_details(d)))

    models: dict = {}
    def model_of(label: str) -> dict:
        return models.setdefault(label, {
            "runs": 0, "months_in_office": [], "removals": {}, "first_to_leave": 0,
            "survive": {3: 0, 6: 0, 9: 0, 12: 0}, "survive_n": {3: 0, 6: 0, 9: 0, 12: 0},
            "calls": 0, "errors": 0, "format_retries": 0, "refusals": 0, "quota": 0, "answer_problems": 0,
            "matches": 0, "mismatches": 0, "open": 0, "promises": {},
            "office_months": {}, "outcomes": [], "terminal_active": 0})

    for job, d, det in runs:
        mapping = det["mapping"]
        members = det["members"]
        months = det["months_run"]
        if not mapping or not members:
            continue
        # who left first, and when
        removed = [(m["removed_month"], mid) for mid, m in members.items()
                   if m.get("removed_month") is not None and m.get("status") not in (None, "active")]
        first_mid = min(removed)[1] if removed else None
        # which office each member held (the formation record first, then the current mapping)
        f_offices = det.get("formation_offices") or det.get("offices") or {}
        office_of = {}
        for off_name, mid in f_offices.items():
            office_of.setdefault(str(mid), off_name)
        for letter, label in mapping.items():
            m = model_of(label)
            m["runs"] += 1
            info = members.get(letter)
            if info is None:
                continue
            active_months = (info["removed_month"] + 1) if info.get("removed_month") is not None else months
            active_months = max(0, min(active_months, months or active_months))
            m["months_in_office"].append(active_months)
            if first_mid == letter and removed:
                m["first_to_leave"] += 1
            how = (info.get("removed_how") or "").lower()
            if info.get("removed_month") is not None and info.get("status") != "active":
                key = "resigned" if "resign" in how else ("expelled" if "expel" in how or "remove" in how else
                                                          (how or "left office"))
                m["removals"][key] = m["removals"].get(key, 0) + 1
            else:
                m["terminal_active"] += 1
            for horizon in (3, 6, 9, 12):
                if months >= horizon:
                    m["survive_n"][horizon] += 1
                    if info.get("removed_month") is None or (info["removed_month"] + 1) > horizon:
                        m["survive"][horizon] += 1
            rc = (det["report_cards"].get(letter) or {}).get("questionnaire") or []
            for q in rc:
                if q.get("match") is True:
                    m["matches"] += 1
                elif q.get("match") is False:
                    m["mismatches"] += 1
                else:
                    m["open"] += 1
            for status, n in (det["promises"].get(letter) or {}).items():
                m["promises"][status] = m["promises"].get(status, 0) + n
            m["answer_problems"] += int((det.get("answer_problems") or {}).get(letter, 0))
            c = det["country"]
            if c and months:
                m["outcomes"].append({"run": job["id"], "months": months,
                                      "approval": c.get("final_approval"), "inflation": c.get("final_inflation_yoy"),
                                      "outcome": (det["outcome"] or {}).get("type", "")})
            office = office_of.get(letter, f"seat {letter}")
            m["office_months"].setdefault(office, []).append(active_months)
        for seat, c in det["calls"].items():
            label = seat_label(mapping, seat)
            if label in models:
                t = models[label]
                for k in ("calls", "errors", "format_retries", "refusals", "quota"):
                    t[k] += c.get(k, 0)

    return {"rows": rows, "runs": runs, "models": models}


def pct(n, d):
    return f"{100 * n / d:.0f}%" if d else "-"


def fmt(x, nd=1):
    return "-" if x is None else f"{x:.{nd}f}"


def model_table(models: dict) -> list:
    """One dict per model, sorted by mean months in office, then name."""
    rows = []
    for label, m in models.items():
        months = [x for x in m["months_in_office"] if x is not None]
        offices = sorted({o for o, ms in m["office_months"].items() if ms})
        rows.append({
            "model": label,
            "runs": m["runs"],
            "runs_leaf": m["runs"] - m["terminal_active"],
            "mean_months": (sum(months) / len(months)) if months else None,
            "median_months": statistics.median(months) if months else None,
            "active_at_end": m["terminal_active"],
            "first_to_leave": m["first_to_leave"],
            "removals": dict(sorted(m["removals"].items(), key=lambda kv: -kv[1])),
            "survive": {h: (m["survive"][h], m["survive_n"][h]) for h in (3, 6, 9, 12)},
            "calls": m["calls"], "errors": m["errors"], "format_retries": m["format_retries"],
            "refusals": m["refusals"], "quota": m["quota"], "answer_problems": m["answer_problems"],
            "matches": m["matches"], "mismatches": m["mismatches"], "open": m["open"],
            "promises": dict(sorted(m["promises"].items(), key=lambda kv: -kv[1])),
        })
    rows.sort(key=lambda r: (-(r["mean_months"] or 0), r["model"]))
    return rows


def write_csvs(rows: list, data: dict, out_dir: Path) -> None:
    with open(out_dir / "benchmark.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "runs_served", "mean_months_in_office", "median_months", "still_in_office_at_end",
                    "first_to_leave_count", "removals", "survive_m3", "survive_m6", "survive_m9", "survive_m12",
                    "calls", "call_errors", "format_retries", "answer_problems", "said_did_matches",
                    "said_did_mismatches"])
        for r in rows:
            w.writerow([r["model"], r["runs"], fmt(r["mean_months"]), fmt(r["median_months"]), r["active_at_end"],
                        r["first_to_leave"], json.dumps(r["removals"]),
                        pct(r["survive"][3][0], r["survive"][3][1]), pct(r["survive"][6][0], r["survive"][6][1]),
                        pct(r["survive"][9][0], r["survive"][9][1]), pct(r["survive"][12][0], r["survive"][12][1]),
                        r["calls"], r["errors"], r["format_retries"], r["answer_problems"],
                        r["matches"], r["mismatches"]])
    with open(out_dir / "model_office.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        offices = sorted({o for label in data["models"] for o in data["models"][label]["office_months"]})
        w.writerow(["model"] + [str(o) for o in offices] + ["runs_served"])
        for r in rows:
            m = data["models"][r["model"]]
            cells = []
            for o in offices:
                ms = m["office_months"].get(o) or []
                cells.append(f"{sum(ms) / len(ms):.1f} (n={len(ms)})" if ms else "-")
            w.writerow([r["model"]] + cells + [r["runs"]])


def render_md(rows: list, data: dict, meta: dict) -> str:
    L = []
    L.append(f"# Tiny-model benchmark — campaign {meta['name']}")
    L.append("")
    L.append(f"- engine {meta['engine']}, code {meta['git']}, months per run {meta['months']}")
    L.append(f"- {meta['runs_total']} runs on disk, {meta['runs_done']} finished, "
             f"{meta['runs_partial']} partial (stopped mid-run; counted as censored)")
    L.append(f"- {meta['generated']}")
    L.append("")
    L.append("Read this first: survival in office is not governance competence (a run can coast with most "
             "offices vacant), so this report keeps four measurements separate — persistence, protocol "
             "reliability, run outcomes, and said-vs-did — and never collapses them into one score.")
    L.append("")
    L.append("## Institutional persistence (per model)")
    L.append("")
    L.append("| model | runs | mean months in office | still in office at end | first to leave | removals | survive M3 | survive M6 | survive M9 | survive M12 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        rem = ", ".join(f"{k} x{v}" for k, v in r["removals"].items()) or "-"
        L.append(f"| {r['model']} | {r['runs']} | {fmt(r['mean_months'])} | {r['active_at_end']} | "
                 f"{r['first_to_leave']} | {rem} | {pct(*r['survive'][3])} | {pct(*r['survive'][6])} | "
                 f"{pct(*r['survive'][9])} | {pct(*r['survive'][12])} |")
    L.append("")
    L.append("## Protocol reliability (calls that carried this model's seat)")
    L.append("")
    L.append("| model | calls | call errors | format retries | answers with problems | refusals | quota stops |")
    L.append("|---|---|---|---|---|---|---|")
    for r in rows:
        L.append(f"| {r['model']} | {r['calls']} | {r['errors']} ({pct(r['errors'], r['calls'])}) | "
                 f"{r['format_retries']} ({pct(r['format_retries'], r['calls'])}) | "
                 f"{r['answer_problems']} ({pct(r['answer_problems'], r['calls'])}) | {r['refusals']} | {r['quota']} |")
    L.append("")
    L.append("## Said vs did (pre-registered questionnaire, where the situation occurred)")
    L.append("")
    L.append("| model | matched | mismatched | never occurred | resolved promises |")
    L.append("|---|---|---|---|---|")
    for r in rows:
        pr = ", ".join(f"{k} {v}" for k, v in r["promises"].items()) or "-"
        L.append(f"| {r['model']} | {r['matches']} | {r['mismatches']} | {r['open']} | {pr} |")
    L.append("")
    return "\n".join(L)


CSS = """
:root { --ink:#1c1e26; --muted:#6b7280; --line:#e5e7eb; --bg:#fafafa; --card:#fff; --accent:#0f766e; --warn:#b45309; }
@media (prefers-color-scheme: dark) { :root { --ink:#e7e7ea; --muted:#9aa0a6; --line:#33363d; --bg:#141518; --card:#1c1e22; --accent:#5eead4; --warn:#fbbf24; } }
* { box-sizing:border-box } body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui,Segoe UI,Arial,sans-serif }
main { max-width:1020px; margin:0 auto; padding:32px 20px 80px }
h1 { font-size:26px; margin:0 0 4px } h2 { font-size:19px; margin:34px 0 10px }
.sub { color:var(--muted); margin:0 0 8px }
.note { background:var(--card); border:1px solid var(--line); border-left:3px solid var(--warn); padding:10px 14px; border-radius:6px; margin:16px 0; font-size:14px; color:var(--ink) }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin:16px 0 }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:14px 16px }
.card h3 { margin:0 0 6px; font-size:15px } .card .big { font-size:26px; font-weight:600 }
.card .sub { font-size:12.5px }
.bar { height:8px; background:var(--line); border-radius:4px; overflow:hidden; margin:6px 0 2px }
.bar i { display:block; height:100%; background:var(--accent) }
table { border-collapse:collapse; width:100%; background:var(--card); border:1px solid var(--line); border-radius:8px; overflow:hidden }
th, td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); font-size:13.5px; vertical-align:top }
th { font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted) }
tr:last-child td { border-bottom:none }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums }
.small { font-size:12px; color:var(--muted) }
footer { margin-top:40px; color:var(--muted); font-size:12.5px }
@media print { body { background:#fff } .card, table { break-inside:avoid } }
"""


def esc(x):
    return html.escape(str(x if x is not None else "-"))


def render_html(rows: list, data: dict, meta: dict) -> str:
    cards = []
    for r in rows:
        s12 = r["survive"][12]
        share = (100 * s12[0] / s12[1]) if s12[1] else 0
        cards.append(f"""<div class="card"><h3>{esc(r['model'])}</h3>
<div class="big">{fmt(r['mean_months'])} <span class="small">mean months in office</span></div>
<div class="bar" title="in office at Month 12: {s12[0]}/{s12[1]}"><i style="width:{share:.0f}%"></i></div>
<div class="sub">in office at Month 12: {pct(*s12)} &nbsp;·&nbsp; left by choice/removal: {r['runs_leaf']}/{r['runs']}</div>
<div class="sub">call errors {pct(r['errors'], r['calls'])} &nbsp;·&nbsp; format retries {pct(r['format_retries'], r['calls'])}</div>
<div class="sub">said-vs-did: {r['matches']} matched, {r['mismatches']} not</div></div>""")
    pers = []
    for r in rows:
        rem = ", ".join(f"{esc(k)} ×{v}" for k, v in r["removals"].items()) or "–"
        pers.append(f"<tr><td>{esc(r['model'])}</td><td class='num'>{r['runs']}</td><td class='num'>{fmt(r['mean_months'])}</td>"
                    f"<td class='num'>{r['active_at_end']}</td><td class='num'>{r['first_to_leave']}</td><td>{rem}</td>"
                    + "".join(f"<td class='num'>{pct(*r['survive'][h])}</td>" for h in (3, 6, 9, 12)) + "</tr>")
    rel = []
    for r in rows:
        rel.append(f"<tr><td>{esc(r['model'])}</td><td class='num'>{r['calls']}</td>"
                   f"<td class='num'>{r['errors']} ({pct(r['errors'], r['calls'])})</td>"
                   f"<td class='num'>{r['format_retries']} ({pct(r['format_retries'], r['calls'])})</td>"
                   f"<td class='num'>{r['answer_problems']} ({pct(r['answer_problems'], r['calls'])})</td>"
                   f"<td class='num'>{r['refusals']}</td><td class='num'>{r['quota']}</td></tr>")
    sd = []
    for r in rows:
        pr = ", ".join(f"{esc(k)} {v}" for k, v in r["promises"].items()) or "–"
        sd.append(f"<tr><td>{esc(r['model'])}</td><td class='num'>{r['matches']}</td>"
                  f"<td class='num'>{r['mismatches']}</td><td class='num'>{r['open']}</td><td>{pr}</td></tr>")
    allruns = []
    for r in data["rows"]:
        allruns.append(f"<tr><td class='small'>{esc(r['run'])}</td><td>{esc(r['state'])}</td>"
                       f"<td class='num'>{esc(r['months_done'])}</td><td>{esc(r.get('outcome') or '–')}</td>"
                       f"<td class='num'>{esc(r.get('members_left') or '–')}</td>"
                       f"<td class='num'>{esc(r.get('wall_min') or '–')}</td></tr>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Karamaniya tiny-model benchmark — {esc(meta['name'])}</title>
<style>{CSS}</style></head><body><main>
<h1>Karamaniya — tiny-model benchmark</h1>
<p class="sub">campaign <b>{esc(meta['name'])}</b> · engine {esc(meta['engine'])} · code {esc(meta['git'])} ·
{meta['runs_total']} runs ({meta['runs_done']} finished, {meta['runs_partial']} partial) · generated {esc(meta['generated'])}</p>
<div class="note"><b>Read this first.</b> This is what five sub-2B local models did when given a country.
Survival in office is <i>not</i> governance competence — a run can coast with most offices vacant — so the four
measurements below stay separate: institutional persistence, protocol reliability, run outcomes, and said-vs-did.
Partial runs (stopped mid-run) are counted as censored, never as failures.</div>
<h2>Per model at a glance</h2><div class="cards">{''.join(cards)}</div>
<h2>Institutional persistence</h2>
<table><tr><th>model</th><th class="num">runs</th><th class="num">mean months in office</th>
<th class="num">still in office at end</th><th class="num">first to leave</th><th>removals</th>
<th class="num">survive M3</th><th class="num">survive M6</th><th class="num">survive M9</th><th class="num">survive M12</th></tr>
{''.join(pers)}</table>
<h2>Protocol reliability <span class="small">(calls that carried this model's seat)</span></h2>
<table><tr><th>model</th><th class="num">calls</th><th class="num">call errors</th>
<th class="num">format retries</th><th class="num">answers with problems</th><th class="num">refusals</th><th class="num">quota stops</th></tr>
{''.join(rel)}</table>
<h2>Said vs did <span class="small">(pre-registered questionnaire; "never occurred" = the situation did not arise)</span></h2>
<table><tr><th>model</th><th class="num">matched</th><th class="num">mismatched</th>
<th class="num">never occurred</th><th>resolved promises</th></tr>
{''.join(sd)}</table>
<h2>All runs</h2>
<table><tr><th>run</th><th>state</th><th class="num">months</th><th>outcome</th><th class="num">members left</th><th class="num">minutes</th></tr>
{''.join(allruns)}</table>
<footer>Built by bench_report.py from the campaign's logs, checkpoints and scorecards. Numbers with small n
(especially per-cell and per-office) are exploratory. The world is deterministic per seed; the models are not.</footer>
</main></body></html>"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="bench1", help="campaign name (its folder under overnight_logs/)")
    ap.add_argument("--runs-dir", default=str(HERE / "runs-bench"))
    ap.add_argument("--folder", default="", help="campaign folder (default: overnight_logs/<name>)")
    args = ap.parse_args(argv)

    folder = Path(args.folder) if args.folder else HERE / "overnight_logs" / args.name
    runs_dir = Path(args.runs_dir)
    plan_file = folder / "campaign_plan.toml"
    plan = load_plan(plan_file if plan_file.exists() else HERE / "campaign_plan.toml")
    plan["name"] = args.name

    engine, git, started = "", "", ""
    cj = folder / "campaign.json"
    if cj.exists():
        try:
            c = json.loads(cj.read_text(encoding="utf-8"))
            engine = f"world engine {c.get('engine_world_engine')}"
            git = (c.get("code") or {}).get("git", "")[:10]
            started = c.get("started", "")
            if (c.get("plan") or {}).get("months"):
                plan["months"] = int(c["plan"]["months"])
        except Exception:
            pass
    if not engine:
        try:
            from karamaniya import versions
            engine = f"world engine {versions.WORLD_ENGINE}, agent prompt {versions.AGENT_PROMPT}"
        except Exception:
            engine = "unknown engine"
    if not git:
        try:
            import subprocess
            git = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"],
                                 capture_output=True, text=True, timeout=20).stdout.strip()
        except Exception:
            pass

    data = build(plan, folder, runs_dir)
    rows = model_table(data["models"])
    meta = {"name": args.name, "engine": engine or "unknown", "git": git or "-",
            "months": plan["months"], "generated": f"{dt.datetime.now():%Y-%m-%d %H:%M}",
            "runs_total": len(data["rows"]),
            "runs_done": sum(r["state"] == "done" for r in data["rows"]),
            "runs_partial": sum(r["state"] in ("partial", "new", "unreadable") for r in data["rows"])}
    if started:
        meta["engine"] += f" (session started {started})"

    out_dir = folder / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    md = render_md(rows, data, meta)
    (out_dir / "benchmark.md").write_text(md, encoding="utf-8")
    (out_dir / "benchmark.html").write_text(render_html(rows, data, meta), encoding="utf-8")
    write_csvs(rows, data, out_dir)
    if (folder / "runs.csv").exists():
        (out_dir / "all_runs.csv").write_text((folder / "runs.csv").read_text(encoding="utf-8"), encoding="utf-8")

    print(md)
    print(f"\nwritten: {out_dir / 'benchmark.html'}")
    print(f"         {out_dir / 'benchmark.md'}, benchmark.csv, model_office.csv, all_runs.csv")
    if not data["rows"]:
        print("note: no runs found yet in", runs_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
