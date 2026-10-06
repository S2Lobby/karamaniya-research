"""Task A (task_0005): export blind + key validation episode CSVs."""
import csv
import json
import os
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = ["20260929-175850-seed1", "20260930-090535-seed1", "20260929-165029-seed1"]
OUT_BLIND = os.path.join(BASE, "research_work", "classifier_validation_blind.csv")
OUT_KEY = os.path.join(BASE, "research_work", "classifier_validation_key.csv")
CONTROL_LABEL = "NON_UNANIMOUS_CONTROL"
UNCLASSIFIED_LABEL = "UNANIMOUS_UNCLASSIFIED"


def counted_unanimous(mo):
    """Engine unanimity rule (convergence._counted + month_analytics): only
    yes/no votes among eligible voters count; abstentions ignored; unanimous
    iff the counted set is exactly {yes} or exactly {no}."""
    votes = mo.get("votes") or {}
    elig = mo.get("eligible_voters")
    names = elig if elig is not None else list(votes)
    counted = [votes.get(x) for x in names if votes.get(x) in ("yes", "no")]
    return bool(counted) and set(counted) in ({"yes"}, {"no"})


def cut(s, n):
    if s is None:
        return ""
    s = " ".join(str(s).replace("\r", " ").replace("\n", " ").split())
    if len(s) > n:
        return s[:n].rstrip() + " [cut]"
    return s


def load_engine_labels(run_id):
    path = os.path.join(BASE, "runs", run_id, "analytics.json")
    with open(path, encoding="utf-8") as f:
        a = json.load(f)
    labels = {}
    months = a.get("analytics", {}).get("convergence", {}).get("months", [])
    for m in months:
        mm = m.get("month")
        for mid, cls in (m.get("unanimity_classification") or {}).items():
            labels[(mm, mid)] = cls
    return labels


def fmt_opening(pre):
    parts = []
    for member in sorted((pre or {}).keys()):
        p = pre[member] or {}
        parts.append("[%s] problem=%s // support=%s // oppose=%s" % (
            member, cut(p.get("main_problem", ""), 280),
            cut(p.get("would_support", ""), 280),
            cut(p.get("would_oppose", ""), 280)))
    return " || ".join(parts)


def fmt_responses(revs, mid):
    parts = []
    for member in sorted((revs or {}).keys()):
        r = revs[member] or {}
        stance = (r.get("stances") or {}).get(mid, "")
        parts.append("[%s stance=%s] %s" % (
            member, stance, cut(r.get("response", ""), 700)))
    return " || ".join(parts)


def fmt_demands(mo, revs, mid):
    bits = []
    for d in mo.get("demands") or []:
        bits.append("(tabled-demand by %s: %s)" % (
            d.get("member", "?"), cut(d.get("demand", ""), 350)))
    for member in sorted((revs or {}).keys()):
        r = revs[member] or {}
        for d in r.get("demands") or []:
            if d.get("motion_id") == mid:
                bits.append("(revision-demand by %s: %s)" % (
                    member, cut(d.get("demand", ""), 350)))
        if mid in (r.get("amended") or []):
            bits.append("(amended by %s)" % member)
    for rev in mo.get("revisions") or []:
        bits.append("(motion-revision text: %s)" % cut(rev.get("text", ""), 350))
    return " | ".join(bits)


def fmt_withdrawals(mo, revs):
    bits = []
    if mo.get("withdrawn_by"):
        bits.append("withdrawn_by=%s reason=%s replaced_by=%s" % (
            mo.get("withdrawn_by"), cut(mo.get("withdrawal_reason", ""), 400),
            mo.get("replaced_by", "") or "-"))
    for member in sorted((revs or {}).keys()):
        for w in (revs[member] or {}).get("withdrawn") or []:
            bits.append("(revision: %s withdrew %s)" % (member, w))
    return " | ".join(bits)


def fmt_votes(mo):
    return " ".join("%s=%s" % kv for kv in sorted((mo.get("votes") or {}).items()))


def fmt_reasons(mo):
    return " || ".join("[%s] %s" % (m, cut(r, 500))
                       for m, r in sorted((mo.get("vote_reasons") or {}).items()))


def build_episodes():
    episodes = []
    for run_id in RUNS:
        lpath = os.path.join(BASE, "runs", run_id, "log.jsonl")
        labels = load_engine_labels(run_id)
        with open(lpath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                e = json.loads(line)
                if e.get("type") != "month":
                    continue
                mm = e.get("month")
                for mo in e.get("motions") or []:
                    if not mo.get("votes"):
                        continue
                    mid = mo.get("id")
                    episodes.append({
                        "episode_id": "%s-m%s-%s" % (run_id, mm, mid),
                        "run_id": run_id,
                        "log_month": mm,
                        "month_label": e.get("label", ""),
                        "motion_id": mid,
                        "proposer": mo.get("proposer", ""),
                        "motion_type": mo.get("type", ""),
                        "motion_subject": mo.get("subject", ""),
                        "motion_text": cut(mo.get("text", ""), 1000),
                        "final_text": cut(mo.get("final_text", "") or "", 1000),
                        "amended": str(bool(mo.get("amended"))),
                        "opening_positions": fmt_opening(e.get("pre_positions")),
                        "response_statements_stances": fmt_responses(
                            e.get("revisions"), mid),
                        "demands_amendments": fmt_demands(
                            mo, e.get("revisions"), mid),
                        "withdrawals_consolidation": fmt_withdrawals(
                            mo, e.get("revisions")),
                        "votes": fmt_votes(mo),
                        "vote_reasons": fmt_reasons(mo),
                        "conditional_votes": cut(json.dumps(
                            mo.get("conditional_votes") or {},
                            ensure_ascii=False), 1200),
                        "vote_tally": mo.get("tally", ""),
                        "motion_status": mo.get("status", ""),
                        "execution_status": mo.get("execution_status", ""),
                        "engine_label": (
                            labels.get((mm, mid))
                            if labels.get((mm, mid)) is not None
                            else (UNCLASSIFIED_LABEL if counted_unanimous(mo)
                                  else CONTROL_LABEL)),
                    })
    episodes.sort(key=lambda r: (RUNS.index(r["run_id"]), r["log_month"],
                                 r["motion_id"]))
    return episodes


BLIND_COLS = ["episode_id", "run_id", "log_month", "month_label", "motion_id",
              "proposer", "motion_type", "motion_subject", "motion_text",
              "final_text", "amended", "opening_positions",
              "response_statements_stances", "demands_amendments",
              "withdrawals_consolidation", "votes", "vote_reasons",
              "conditional_votes", "vote_tally", "motion_status",
              "execution_status"]
KEY_COLS = BLIND_COLS + ["engine_label"]


def write_csv(path, cols, episodes):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore",
                           quoting=csv.QUOTE_MINIMAL, doublequote=True)
        w.writeheader()
        for e in episodes:
            w.writerow({c: e[c] for c in cols})


def main():
    episodes = build_episodes()
    assert 50 <= len(episodes) <= 100, "count %d outside 50-100" % len(episodes)
    write_csv(OUT_BLIND, BLIND_COLS, episodes)
    write_csv(OUT_KEY, KEY_COLS, episodes)
    print("Episodes exported: %d" % len(episodes))
    print("Hidden class distribution (key only):")
    for k in sorted(Counter(e["engine_label"] for e in episodes)):
        print("  %s: %d" % (k, Counter(e["engine_label"]
                                       for e in episodes)[k]))
    print("Per run:")
    for k in sorted(Counter(e["run_id"] for e in episodes)):
        print("  %s: %d" % (k, Counter(e["run_id"] for e in episodes)[k]))
    print("Wrote %s" % OUT_BLIND)
    print("Wrote %s" % OUT_KEY)


if __name__ == "__main__":
    main()

