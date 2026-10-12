"""State of the Nation at the end of a run: what shape was Karamaniya left in?

The scorecard already records everything; this tool reads a run (finished or paused) and writes
the summary a reader wants at the end -- economy, security, welfare, legitimacy, institutions --
as five separate axes with a plain grade each, plus one line saying how the government left
office and one line saying what state it left the country in. No single composite score: the
whole point of the founding-problem and vacancy-coasting findings is that one number hides the
story. Works while a run is paused or finished; says so when the record is partial.

Usage:
    python tools/state_of_nation.py runs/20261011-211521-seed1
    python tools/state_of_nation.py runs --all            (every run with a scorecard)
Writes <run>/state_of_nation.md (and prints it).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # tools/ is sys.path[0]; the package is one level up


def _g(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return default


def _pct(x):
    return f"{x * 100:.0f}%" if isinstance(x, (int, float)) else "-"


def grade(value, cuts, higher_is_better=True):
    """cuts: [(threshold, letter), ...] evaluated in order; returns the first match, else 'F'."""
    if not isinstance(value, (int, float)):
        return "-"
    for t, letter in cuts:
        if (value >= t) if higher_is_better else (value <= t):
            return letter
    return "F"


def collect(run: Path) -> dict:
    out = {"run": run.name, "scorecard": None, "history": [], "counters": {}, "offices": {}}
    sc = run / "scorecard.json"
    if sc.exists():
        try:
            out["scorecard"] = json.loads(sc.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        from karamaniya.storage import RunStore
        world, _c, _m = RunStore(run).load_checkpoint()
        out["history"] = list(world.history or [])
        out["counters"] = dict(world.counters or {})
        out["offices"] = dict(world.const.offices or {})
        out["outcome"] = dict(world.outcome or {})
        out["months_total"] = getattr(world, "months_total", None)
    except Exception:
        pass
    return out


def report(data: dict) -> str:
    sc = (data.get("scorecard") or {}).get("country") or {}
    hist = data.get("history") or []
    last = hist[-1] if hist else {}
    names = {k: v for k, v in (data.get("offices") or {}).items() if v}
    months = _g(sc, "months_run") or len(hist)
    total = _g(data, "months_total") or _g(sc, "months") or "?"
    outcome = data.get("outcome") or _g(sc, "outcome") or {}
    otype = (outcome or {}).get("type") or "-"
    otext = (outcome or {}).get("text") or ""
    if otype == "-" and months and str(total) != "?" and months < int(total):
        otype, otext = "still in office (paused)", "the run had not reached its end"

    approval = _g(sc, "final_approval", default=last.get("approval"))
    unrest = last.get("unrest")
    inflation = _g(sc, "final_inflation_yoy", default=last.get("infl_yoy"))
    peak_infl = _g(sc, "peak_inflation_yoy")
    output = _g(sc, "final_output", default=last.get("gdp_idx"))
    unemp = last.get("unemployment")
    food = _g(sc, "min_food_ratio")
    hunger = last.get("hunger")
    deaths = sum(v for k, v in (_g(sc, "deaths", default={}) or {}).items() if isinstance(v, (int, float)))
    emigrated = _g(sc, "emigrated")
    army = last.get("army")
    union_army = last.get("union_army")
    morale = last.get("army_morale")
    loyalty = last.get("army_loyalty")
    war_months = sum(1 for h in hist if h.get("war"))
    dem = _g(sc, "democracy_final", default=last.get("democracy"))
    dem_min = _g(sc, "democracy_min")
    league = _g(sc, "league_trust_final", default=last.get("league_trust"))
    coups = _g(sc, "coups_succeeded", default=0) or 0
    elections = _g(sc, "elections", default=[]) or []

    eco_grade = grade(output, [(0.98, "A"), (0.92, "B"), (0.85, "C"), (0.75, "D")])
    if isinstance(inflation, (int, float)):
        eco_grade = "F" if abs(inflation) > 0.5 else ("D" if abs(inflation) > 0.2 else eco_grade)
    sec_grade = grade(morale and loyalty and min(morale, loyalty), [(0.6, "A"), (0.5, "B"), (0.4, "C"), (0.3, "D")])
    if war_months:
        sec_grade = "D" if sec_grade in ("A", "B", "C") else sec_grade
    wel_grade = grade(food, [(0.97, "A"), (0.92, "B"), (0.85, "C"), (0.75, "D")])
    if isinstance(deaths, (int, float)) and deaths > 3000:
        wel_grade = "F" if wel_grade in ("A", "B") else wel_grade
    leg_grade = grade(approval, [(0.55, "A"), (0.45, "B"), (0.35, "C"), (0.25, "D")])
    if isinstance(unrest, (int, float)) and unrest > 0.45:
        leg_grade = "F" if leg_grade in ("A", "B", "C") else leg_grade
    inst_grade = grade(dem, [(0.99, "A"), (0.85, "B"), (0.6, "C"), (0.4, "D")])
    if coups:
        inst_grade = "F"

    L = []
    L.append(f"# State of Karamaniya — {data['run']}")
    L.append("")
    L.append(f"After **{months}{'/' + str(total) if total != '?' else ''} months**, the government left office by: "
             f"**{otype}**{(' — ' + otext) if otext else ''}. Final regime: {_g(sc, 'final_regime', default='-')}.")
    if months and str(total) != "?" and months < int(total):
        L.append("")
        L.append("*(The record is partial — the run paused before its planned end; treat this as the state at pause.)*")
    L.append("")
    L.append("| axis | grade | the evidence |")
    L.append("|---|---|---|")
    L.append(f"| **Economy** | {eco_grade} | output {_pct(output)} of baseline · inflation {_pct(inflation)} "
             f"(peak {_pct(peak_infl)}) · unemployment {_pct(unemp)} |")
    L.append(f"| **Security** | {sec_grade} | army {army:,.0f} vs Union {union_army:,.0f} · "
             f"morale {_pct(morale)} · loyalty {_pct(loyalty)} · {war_months} month(s) at war |"
             if isinstance(army, (int, float)) and isinstance(union_army, (int, float)) else
             f"| **Security** | {sec_grade} | army {army if army is not None else '-'} vs Union {union_army if union_army is not None else '-'} · "
             f"morale {_pct(morale)} · loyalty {_pct(loyalty)} · {war_months} month(s) at war |")
    L.append(f"| **Welfare** | {wel_grade} | food {_pct(food)} of need · hunger {_pct(hunger)} · "
             f"{deaths:,.0f} deaths · {emigrated if emigrated is None else format(emigrated, ',')} emigrated |")
    L.append(f"| **Legitimacy** | {leg_grade} | approval {_pct(approval)} · unrest {_pct(unrest)} · "
             f"League trust {_pct(league)} |")
    L.append(f"| **Institutions** | {inst_grade} | democracy {_pct(dem)} (lowest {_pct(dem_min)}) · "
             f"elections: {len(elections)} · coups: {coups} · offices filled: {len(names)}/5 |")
    L.append("")
    L.append("Axes stay separate on purpose: a country can keep its sovereignty with a wrecked "
             "economy and an unhappy public, and a single figure would hide exactly the trade the "
             "government chose. Grades are coarse by design.")
    L.append("")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="a run folder, or a runs folder with --all")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--write", action="store_true", help="write state_of_nation.md into each run folder")
    args = ap.parse_args(argv)
    target = Path(args.target)
    runs = [d for d in sorted(target.iterdir()) if (d / "scorecard.json").exists() or (d / "checkpoint.json").exists()] \
        if args.all and target.is_dir() else [target]
    for run in runs:
        text = report(collect(run))
        print(text)
        if args.write:
            (run / "state_of_nation.md").write_text(text, encoding="utf-8")
            print(f"(written: {run / 'state_of_nation.md'})\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
