#!/usr/bin/env python3
"""Jev (TypeSafe System One) as the blind second annotator. Standard library only.

    python tools/jev_annotate.py sample SAMPLE.csv [--out OUT.csv] [--limit N] [--dry-run]
    python tools/jev_annotate.py reaudit [--labels-dir DIR] [--out-dir DIR] [--runs RUNS] [--dry-run]

`sample` reads the CSV that `python tools/exit_audit.py sample` draws, asks Jev the codebook question once per
row, and writes a copy with `annotator_2`, the probabilities, the confidence and the resolved model id filled in.
`reaudit` asks the same kind of typed question of the D1 and D2 rows in docs/detector_labels/ and reports Jev's
agreement with the single annotator before and after the T144 fixes.

The state sent to Jev is blind: it holds the raw answers and the recorded row facts, but not the engine's own
reading (`parsed`) and not the first annotator's label. The codebook's label rules and the blind protocol are in
docs/EXIT_AUDIT_CODEBOOK.md and docs/JEV_ANNOTATOR.md.

The key is read from TYPESAFE_API_KEY by karamaniya/backends/systemone.py; this tool never prints, logs or stores
it. `--dry-run` prints the cost estimate and the requests without sending anything and needs no key.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from karamaniya.backends.systemone import SystemOneBackend  # noqa: E402
from tools import exit_audit as ea  # noqa: E402

#: The exit-audit codebook labels. The brief calls them supported / ambiguous / parser.
LABELS = ea.LABELS
#: The detector-audit labels, from docs/DETECTOR_PRECISION.md.
D1_LABELS = ("TRUE_ERROR", "FALSE_POSITIVE", "UNCLEAR")
D2_LABELS = ("TRUE_MISMATCH", "FALSE_POSITIVE", "UNCLEAR")
QUESTION_ID = "exit_label"
D1_QUESTION_ID = "d1_label"
D2_QUESTION_ID = "d2_label"
#: The contract bills input tokens only ($42 per Btok == $0.042 per Mtok); output is free.
PRICE_PER_MTOK = SystemOneBackend.price_in_per_mtok
#: Cost estimate only: the repository cannot count tokens without a tokenizer. The contract's own examples are
#: roughly four characters per token; the estimate is labelled approximate wherever it is printed.
CHARS_PER_TOKEN = 4
#: The contract gives 64k tokens per request, and 32k for the state plus the single longest question. Keep the
#: conservative 32k bound; a row beyond it stops before any call rather than failing as a 422 mid-run.
MAX_EST_TOKENS = 30000
#: Columns `sample` adds to the exit-audit sheet. `annotator_2` is already one of exit_audit.CSV_FIELDS.
NEW_FIELDS = ("annotator_2_probabilities", "annotator_2_confidence", "annotator_2_model")
DETECTOR_DIR = os.path.join(ROOT, "docs", "detector_labels")
#: The recorded runs are read-only input for the current D2 rule. The path is the live checkout, as in
#: tools/detector_audit.py; a missing folder is reported, never created.
RESEARCH_RUNS = "C:/Users/litle/Karamaniya/research/runs"


class AnnotateError(Exception):
    """A problem with the inputs or a call. The command stops and reports it; nothing is silently skipped."""


class AuditingSystemOne(SystemOneBackend):
    """The repository's System One backend, keeping the Choice confidence as a number.

    SystemOneBackend._row (karamaniya/backends/systemone.py:114) records the contract's confidence only inside the
    free-text `reason` ("confidence 0.4"). The audit writes it as its own column, so this subclass adds the field
    and changes nothing else: the request, retries, usage and resolved model id are the base class's.
    """

    @staticmethod
    def _row(q, a):
        row = SystemOneBackend._row(q, a)
        value = a.get("confidence")
        row["confidence"] = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        return row


# ---- the questions -------------------------------------------------------------------------------------------

def exit_question():
    """The exit-audit question: one Choice of the codebook's three labels, with the rules as criteria.

    The criteria restate docs/EXIT_AUDIT_CODEBOOK.md section 3. They are kept here as text because the contract
    takes free-form criteria, not a document reference.
    """
    return {
        "id": QUESTION_ID,
        "kind": "choice",
        "text": (
            "You are the second annotator of an exit-event trace audit. The row below is one apparent exit, or one "
            "executed or refused motion. Label it from its raw answers with the codebook's rules, in order: apply "
            "formatting_or_parser (F1-F4) first; if none fits, apply ambiguous (A1-A4); otherwise it is "
            "substantively_supported. The flag decides whether the engine records an exit; the words decide the "
            "label, so read the raw answers, not the engine's summary. A reason is not a condition: 'the arrears "
            "crisis is beyond my ministry' explains a resignation; 'if X happens, I will resign' conditions it. "
            "The engine's own reading (the parsed field) is deliberately withheld. The recorded state change, the "
            "engine flags and the parser checks are shown, because the codebook reads them."
        ),
        "options": list(LABELS),
        "criteria": {
            "formatting_or_parser": (
                "F1: no usable answer - the answers that carry the exit are empty, an error message, or missing. "
                "F2: the engine read something the answer does not say - a resign token that is not the JSON true, "
                "an election response outside the allowed words, a coup action different from the raw one, or a "
                "motion whose type, subject or value differs from the raw text. F3: the words that would carry the "
                "exit are placeholders (notes, statement, private_position or vote_reasons hold only dots, dashes "
                "or nothing), so the exit rests on a bare flag. F4: the answer times or conditions the exit "
                "differently from the reading - 'if ... I will resign', a date later than the current month, or a "
                "statement that the delegate stays - and the engine read it as an immediate exit."
            ),
            "ambiguous": (
                "Not F1-F4, and any of: A1 the exit rests only on a clean flag or motion, and the rest of the "
                "answer is ordinary text that says nothing about leaving office (a bare \"resign\": true with "
                "ordinary notes is A1); A2 the answer hedges the exit in the same sentence ('may', 'might', "
                "'considering', 'would consider'); A3 a mechanical exit depends on a recorded route whose outcome "
                "is not recorded (a recount, a court challenge, a coalition); A4 two readings are plausible from "
                "the answer and the row does not settle it."
            ),
            "substantively_supported": (
                "Not F1-F4 and not A1-A4. The answer says, in its own words (notes, statement, or a communication "
                "about the delegate's own office), and says it now, that the delegate is leaving. The flag or "
                "motion matches the words, and the state change follows. For mechanical exits (handover, election "
                "defeat): the recorded shares give the Charter verdict, and every recorded response reads as the "
                "answer says."
            ),
        },
    }


def detector_question(kind):
    """The re-audit question for D1 or D2, with docs/DETECTOR_PRECISION.md's label definitions as criteria."""
    if kind == "d1":
        return {
            "id": D1_QUESTION_ID,
            "kind": "choice",
            "text": (
                "One NUMERIC_GROUNDING_ERROR flag from the detector audit. Decide whether it is a true error. The "
                "sentence is the delegate's own text around the flagged figure; the observed value is the "
                "canonical state recorded at the time; the briefing lines are what the delegate was shown. Judge "
                "the sentence, not the detector's code."
            ),
            "options": list(D1_LABELS),
            "criteria": {
                "TRUE_ERROR": ("The sentence states a current or past level of the flagged metric, and the "
                               "canonical state (observed) contradicts it."),
                "FALSE_POSITIVE": ("The sentence does not state that level (it is a threshold, a flow, an amount, "
                                   "a count, a setting, or a forecast), or the level it states is accurate."),
                "UNCLEAR": "The record does not settle it.",
            },
        }
    if kind == "d2":
        return {
            "id": D2_QUESTION_ID,
            "kind": "choice",
            "text": (
                "One VOTE_INTENT_MISMATCH flag from the detector audit: a delegate's final vote and the reason it "
                "gave. Decide whether the vote is really inconsistent with the stated reason. The recorded stance "
                "is shown, but the question is the reason against the vote: a reason can be consistent with the "
                "vote while the stance field is the outlier."
            ),
            "options": list(D2_LABELS),
            "criteria": {
                "TRUE_MISMATCH": "The reason argues against the vote.",
                "FALSE_POSITIVE": "The reason is consistent with the vote.",
                "UNCLEAR": "The record does not settle it.",
            },
        }
    raise AnnotateError(f"unknown detector question {kind!r}")


# ---- the blind state -----------------------------------------------------------------------------------------

def build_state(row):
    """The exit-audit row as Jev sees it.

    Blind protocol: the raw answers are included in full; the engine's own reading (`parsed`), the tool's machine
    reading of the answer (`raw_reading`), and the annotators' columns (`annotator_1`, `annotator_2`, `adjudicated`,
    `notes`) are left out. The codebook's own rule is to read the raw answer, not the engine's text; the flags are
    part of the row the codebook tells the annotator to use.
    """
    lines = ["EXIT-EVENT AUDIT ROW (one apparent exit, or one executed or refused motion)", ""]
    facts = (("event id", "event_id"), ("run", "run"), ("month", "month_label"), ("event type", "event_type"),
             ("exit class", "exit_class"), ("is an exit", "is_exit"), ("member", "member"), ("office", "office"),
             ("motion", "motion_id"), ("motion type", "motion_type"))
    for label, key in facts:
        value = str(row.get(key, "") or "").strip()
        if value:
            lines.append(f"{label}: {value}")
    lines += ["", "RAW ANSWERS (verbatim; every phase the engine recorded):",
              str(row.get("raw_answers", "") or "")]
    lines += ["", "STATE CHANGE RECORDED BY THE ENGINE:", str(row.get("state_change", "") or "")]
    lines += ["", "ENGINE FLAGS (what the engine recorded about this member and month):",
              str(row.get("engine_flags", "") or "(none)")]
    lines += ["", "PARSER CHECKS (the audit tool's comparison of the raw answer with the engine's reading):",
              str(row.get("parser_checks", "") or "(none)")]
    return "\n".join(lines).strip()


def build_d1_state(row):
    """One D1 row: the sentence, the recorded metric, the canonical value and the briefing lines."""
    lines = ["NUMERIC-GROUNDING FLAG (D1) FROM THE DETECTOR AUDIT", ""]
    facts = (("flag", "flag_id"), ("run", "run"), ("month", "month_no"), ("member", "member"), ("field", "field"),
             ("flagged metric", "metric"), ("engine's claim text", "claim_text"), ("claimed", "claimed"),
             ("observed (canonical)", "observed"), ("figure located by", "located"),
             ("decision prompt recorded", "prompt_found"))
    for label, key in facts:
        value = str(row.get(key, "") or "").strip()
        if value:
            lines.append(f"{label}: {value}")
    lines += ["", "THE SENTENCE (the delegate's text around the flagged figure):",
              str(row.get("sentence", "") or "(not found)")]
    lines += ["", "WHAT THE DELEGATE WAS SHOWN (decision-prompt lines naming the metric):",
              str(row.get("briefing", "") or "(not recorded)")]
    return "\n".join(lines).strip()


def build_d2_state(row):
    """One D2 row: the motion, the vote, the recorded stance and the delegate's own reason, in full."""
    lines = ["VOTE-INTENT FLAG (D2) FROM THE DETECTOR AUDIT", ""]
    facts = (("flag", "flag_id"), ("run", "run"), ("month", "month_no"), ("member", "member"),
             ("motion", "motion"), ("motion type", "motion_type"), ("motion subject", "motion_subject"),
             ("passed", "passed"), ("tally", "tally"), ("final vote", "vote"), ("recorded stance", "stance"),
             ("stance source", "source"))
    for label, key in facts:
        value = str(row.get(key, "") or "").strip()
        if value:
            lines.append(f"{label}: {value}")
    lines += ["", "MOTION TEXT:", str(row.get("motion_text", "") or "(not recorded)")]
    lines += ["", "VOTE CONDITION:", str(row.get("vote_condition", "") or "(none)")]
    lines += ["", "THE DELEGATE'S STATED REASON (verbatim):", str(row.get("reason_full", "") or "(none)")]
    lines += ["", "THE DELEGATE'S STATEMENT FOR THE MONTH:", str(row.get("statement", "") or "(none)")]
    return "\n".join(lines).strip()


# ---- cost estimate and calls ---------------------------------------------------------------------------------

def estimate_cost(states, question):
    """An approximate input-token and dollar estimate before any call. Output tokens are free.

    tokens = (len(state) + len(question JSON)) / CHARS_PER_TOKEN per request. The contract bills per question;
    this tool asks one question per request, so the sum is the estimate.
    """
    qlen = len(json.dumps(question))
    per_request = [max(1, (len(state) + qlen) // CHARS_PER_TOKEN) for state in states]
    total = sum(per_request)
    return {"rows": len(per_request), "tokens_per_request": per_request, "total_tokens": total,
            "cost_usd": total / 1e6 * PRICE_PER_MTOK,
            "oversized": [i for i, tokens in enumerate(per_request) if tokens > MAX_EST_TOKENS]}


def check_sizes(est, ids):
    """Stop before a call that the contract's 32k state-plus-question bound says is too large."""
    if est["oversized"]:
        names = ", ".join(str(ids[i]) for i in est["oversized"][:10])
        raise AnnotateError(
            f"{len(est['oversized'])} request(s) exceed the estimated {MAX_EST_TOKENS}-token state cap "
            f"(the contract gives 32k for state plus the longest question): {names}")


def print_estimate(est, prefix="Cost estimate"):
    if not est["rows"]:
        print(f"{prefix}: no rows.")
        return
    low, high = min(est["tokens_per_request"]), max(est["tokens_per_request"])
    print(f"{prefix} (input tokens only; output is free; approximate, characters/4): "
          f"{est['rows']} rows, ~{low}-{high} tokens per request ({est['total_tokens']} total); "
          f"at ${PRICE_PER_MTOK:.3f} per Mtok = ${est['cost_usd']:.6f}.")


def _ask_label(backend, state, question, allowed, row_id):
    try:
        out = backend.ask(state, [question])
    except (ValueError, RuntimeError, OSError) as exc:  # HTTP/transport failures the backend reports
        raise AnnotateError(f"{row_id}: {exc}") from None
    answer = (out.get("answers") or [{}])[0]
    # SystemOneBackend._row lowercases the contract's choice (systemone.py:117). The exit labels are lowercase
    # already; the detector labels are upper case, so match case-insensitively and write the codebook spelling.
    by_lower = {label.lower(): label for label in allowed}
    label = by_lower.get(str(answer.get("choice") or "").strip().lower())
    if label is None:
        raise AnnotateError(f"{row_id}: the answer {answer.get('choice')!r} is not one of {', '.join(allowed)}")
    return label, answer


def annotate(rows, states, question, allowed, backend, id_field="event_id"):
    """Ask one question per row. Returns (results, usage); a failure stops the run with the row id in the message."""
    results, total_input, total_cost = [], 0, 0.0
    for row, state in zip(rows, states):
        row_id = str(row.get(id_field) or f"row-{len(results) + 1}")
        label, answer = _ask_label(backend, state, question, allowed, row_id)
        usage = backend.last_usage or {}
        total_input += int(usage.get("input_tokens", 0))
        total_cost += float(backend.last_cost_usd or 0.0)
        results.append((label, answer, str(usage.get("served_model") or "")))
    return results, {"input_tokens": total_input, "cost_usd": total_cost}


def _confidence_text(answer):
    value = answer.get("confidence")
    return "" if value is None else f"{float(value):g}"


def _probabilities_text(answer):
    return json.dumps(answer.get("probabilities") or {}, sort_keys=True, ensure_ascii=False)


def write_rows(path, rows, fields):
    with open(path, "w", encoding="utf-8", newline="") as f:
        # The repository is LF (.gitattributes); csv would write CRLF by default.
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    if not os.path.isfile(path):
        raise AnnotateError(f"{path}: not a file")
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def agreement_line(name, pairs):
    """Exact agreement and the exit-audit agreement statistics for (Jev label, annotator_1 label) pairs."""
    if not pairs:
        return f"{name}: no paired labels; agreement undefined."
    stats = ea._kappa_alpha(pairs)
    fmt = lambda v: "undefined" if v is None else f"{v:.4f}"
    agree = sum(1 for a, b in pairs if a == b)
    return (f"{name}: {len(pairs)} rows; Jev vs annotator_1 {agree}/{len(pairs)} = {stats['p_o']:.4f}; "
            f"Cohen's kappa {fmt(stats['kappa'])}; Krippendorff's alpha {fmt(stats['alpha'])}")


# ---- sample command ------------------------------------------------------------------------------------------

def cmd_sample(args):
    rows = read_csv(args.sample)
    if not rows:
        raise AnnotateError(f"{args.sample}: no rows")
    for needed in ("event_id", "raw_answers"):
        if needed not in rows[0]:
            raise AnnotateError(f"{args.sample}: not an exit-audit sample (no {needed} column); "
                                f"draw it with python tools/exit_audit.py sample")
    if args.limit:
        rows = rows[:args.limit]
    if not args.out:
        stem = args.sample[:-4] if args.sample.lower().endswith(".csv") else args.sample
        args.out = stem + ".jev.csv"
    question = exit_question()
    states = [build_state(row) for row in rows]
    ids = [row.get("event_id") or f"row-{i + 1}" for i, row in enumerate(rows)]
    est = estimate_cost(states, question)
    print_estimate(est)
    if est["oversized"]:
        if args.dry_run:
            print(f"Warning: {len(est['oversized'])} request(s) exceed the estimated cap; a real run would stop.")
        else:
            check_sizes(est, ids)
    if args.dry_run:
        print(f"\nDry run: {len(rows)} rows. No request was sent. The blind state and the question for the first "
              f"row follow.")
        print("\n--- state (what Jev would see) ---")
        print(states[0])
        print("\n--- question ---")
        print(json.dumps(question, ensure_ascii=False, indent=2, sort_keys=True))
        print("\nThe blind state leaves out: parsed (the engine's reading), raw_reading, annotator_1, annotator_2, "
              "adjudicated, notes.")
        print(f"With a key in TYPESAFE_API_KEY, this run would write {args.out}.")
        return 0
    try:
        backend = AuditingSystemOne({"model": args.model, "base_url": args.base_url,
                                     "api_key_env": "TYPESAFE_API_KEY", "timeout": args.timeout,
                                     "retries": args.retries})
    except ValueError as exc:
        raise AnnotateError(str(exc)) from None
    results, usage = annotate(rows, states, question, LABELS, backend)
    out_rows = []
    for row, (label, answer, model) in zip(rows, results):
        out = dict(row)
        out["annotator_2"] = label
        out["annotator_2_probabilities"] = _probabilities_text(answer)
        out["annotator_2_confidence"] = _confidence_text(answer)
        out["annotator_2_model"] = model
        out_rows.append(out)
    fields = list(rows[0].keys())
    for name in ("annotator_2",) + NEW_FIELDS:
        if name not in fields:
            fields.append(name)
    write_rows(args.out, out_rows, fields)
    model = next((model for _label, _answer, model in results if model), "")
    print(f"\nWrote {len(out_rows)} rows to {args.out}; resolved model: {model or '(not reported)'}.")
    print(f"Actual usage reported: {usage['input_tokens']} input tokens, ${usage['cost_usd']:.6f} "
          f"(the estimate was ${est['cost_usd']:.6f}).")
    print("Labels: " + json.dumps(dict(Counter(label for label, _a, _m in results)), sort_keys=True))
    human = {row.get("event_id", ""): (row.get("annotator_1") or "").strip() for row in rows}
    pairs = [(out["annotator_2"], human[out["event_id"]]) for out in out_rows if human.get(out["event_id"])]
    if pairs:
        print(agreement_line("Jev vs annotator_1 on this sample", pairs))
    return 0


# ---- re-audit command ----------------------------------------------------------------------------------------

def load_detector_rows(labels_dir, kind):
    """The detector evidence joined to the single annotator's labels. Only labelled rows are re-audited."""
    if kind == "d1":
        evidence_path = os.path.join(labels_dir, "D1_evidence_all137.csv")
        label_files = ("D1_labels_sample40.csv", "D1_labels_replay_unsampled11.csv")
        default_file = "D1_labels_sample40.csv"
    else:
        evidence_path = os.path.join(labels_dir, "D2_evidence_36.csv")
        label_files = ("D2_labels_36.csv",)
        default_file = "D2_labels_36.csv"
    evidence = {}
    if os.path.isfile(evidence_path):
        evidence = {row["flag_id"]: row for row in read_csv(evidence_path)}
    labels = []
    for name in label_files:
        path = os.path.join(labels_dir, name)
        if os.path.isfile(path):
            labels += read_csv(path)
    if not labels:
        raise AnnotateError(f"{labels_dir}: no {default_file}; the single annotator's labels are the comparison")
    rows = []
    for label in labels:
        flag_id = str(label.get("flag_id") or "").strip()
        if flag_id not in evidence:
            raise AnnotateError(f"{labels_dir}: no evidence row for {flag_id or '(blank flag_id)'}")
        row = dict(evidence[flag_id])
        row["annotator_1"] = label.get("label", "")
        rows.append(row)
    return rows


def current_d2_flags(runs_dir):
    """The fixed T144 reason rule on every yes or no ballot in the recorded runs. Read-only; no model is called.

    This is the same rule tools/detector_audit.py reason-check prints, re-read here instead of the tool's absolute
    runs path so the caller chooses the runs folder. Ballots the fixed rule still flags have no evidence rows in
    docs/detector_labels; the count is reported, and a non-zero count is a sign the labels need extending.
    """
    if not runs_dir or not os.path.isdir(runs_dir):
        return None
    from karamaniya import council as C
    ballots = flagged = 0
    for name in sorted(os.listdir(runs_dir)):
        log = os.path.join(runs_dir, name, "log.jsonl")
        if not os.path.isfile(log):
            continue
        with open(log, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("type") != "month":
                    continue
                for decision in (rec.get("decisions") or {}).values():
                    if not isinstance(decision, dict):
                        continue
                    ballots += sum(1 for vote in (decision.get("votes") or {}).values() if vote in ("yes", "no"))
                    flagged += len(C._reason_contradictions(decision))
    return {"ballots": ballots, "flagged": flagged}


def _annotation_sheet(rows, results):
    out = []
    for row, (label, answer, model) in zip(rows, results):
        out.append({"flag_id": row.get("flag_id", ""), "annotator_1": row.get("annotator_1", ""),
                    "annotator_2": label, "annotator_2_probabilities": _probabilities_text(answer),
                    "annotator_2_confidence": _confidence_text(answer), "annotator_2_model": model})
    return out


def cmd_reaudit(args):
    labels_dir = args.labels_dir
    d1_rows = load_detector_rows(labels_dir, "d1")
    d2_rows = load_detector_rows(labels_dir, "d2")
    d1_question, d2_question = detector_question("d1"), detector_question("d2")
    d1_states = [build_d1_state(row) for row in d1_rows]
    d2_states = [build_d2_state(row) for row in d2_rows]
    est1 = estimate_cost(d1_states, d1_question)
    est2 = estimate_cost(d2_states, d2_question)
    print_estimate(est1, "D1 cost estimate")
    print_estimate(est2, "D2 cost estimate")
    d1_ids = [row.get("flag_id", "") for row in d1_rows]
    d2_ids = [row.get("flag_id", "") for row in d2_rows]
    if d1_states:
        check_sizes(est1, d1_ids) if not args.dry_run else None
    if d2_states:
        check_sizes(est2, d2_ids) if not args.dry_run else None
    if args.dry_run:
        print(f"\nDry run: {len(d1_rows)} D1 rows and {len(d2_rows)} D2 rows. No request was sent.")
        print("\n--- first D1 state (what Jev would see) ---")
        print(d1_states[0] if d1_states else "(none)")
        print("\n--- first D1 question ---")
        print(json.dumps(d1_question, ensure_ascii=False, indent=2, sort_keys=True))
        print("\n--- first D2 state (what Jev would see) ---")
        print(d2_states[0] if d2_states else "(none)")
        print("\n--- first D2 question ---")
        print(json.dumps(d2_question, ensure_ascii=False, indent=2, sort_keys=True))
        print(f"\nWith a key in TYPESAFE_API_KEY, this run would write D1_jev_labels.csv and D2_jev_labels.csv "
              f"to {args.out_dir}.")
        return 0
    try:
        backend = AuditingSystemOne({"model": args.model, "base_url": args.base_url,
                                     "api_key_env": "TYPESAFE_API_KEY", "timeout": args.timeout,
                                     "retries": args.retries})
    except ValueError as exc:
        raise AnnotateError(str(exc)) from None
    d1_results, d1_usage = annotate(d1_rows, d1_states, d1_question, D1_LABELS, backend, "flag_id")
    d2_results, d2_usage = annotate(d2_rows, d2_states, d2_question, D2_LABELS, backend, "flag_id")
    os.makedirs(args.out_dir, exist_ok=True)
    d1_out, d2_out = _annotation_sheet(d1_rows, d1_results), _annotation_sheet(d2_rows, d2_results)
    fields = ["flag_id", "annotator_1", "annotator_2", "annotator_2_probabilities",
              "annotator_2_confidence", "annotator_2_model"]
    write_rows(os.path.join(args.out_dir, "D1_jev_labels.csv"), d1_out, fields)
    write_rows(os.path.join(args.out_dir, "D2_jev_labels.csv"), d2_out, fields)
    model = next((model for _l, _a, model in d1_results + d2_results if model), "")
    print(f"\nWrote {len(d1_out)} D1 and {len(d2_out)} D2 labels to {args.out_dir}; "
          f"resolved model: {model or '(not reported)'}.")
    print(f"Actual usage reported: {d1_usage['input_tokens'] + d2_usage['input_tokens']} input tokens, "
          f"${d1_usage['cost_usd'] + d2_usage['cost_usd']:.6f}.")
    print("Labels: D1 " + json.dumps(dict(Counter(r["annotator_2"] for r in d1_out)), sort_keys=True)
          + "; D2 " + json.dumps(dict(Counter(r["annotator_2"] for r in d2_out)), sort_keys=True))

    pairs = lambda rows: [(row["annotator_2"], row["annotator_1"]) for row in rows]
    sample_path = os.path.join(labels_dir, "D1_labels_sample40.csv")
    replay_path = os.path.join(labels_dir, "D1_labels_replay_unsampled11.csv")
    sample_ids = {row["flag_id"] for row in read_csv(sample_path)} if os.path.isfile(sample_path) else set()
    replay_ids = {row["flag_id"] for row in read_csv(replay_path)} if os.path.isfile(replay_path) else set()
    print("\nRe-audit: Jev's agreement with the single annotator")
    print(agreement_line("D1 sample (recorded flags, before T144)",
                         pairs([row for row in d1_out if row["flag_id"] in sample_ids])))
    print(agreement_line("D1 replay-labelled remainder (after the replay)",
                         pairs([row for row in d1_out if row["flag_id"] in replay_ids])))
    print(agreement_line("D1 all labelled rows", pairs(d1_out)))
    replay_csv = os.path.join(labels_dir, "D1_replay_current_main.csv")
    if os.path.isfile(replay_csv):
        replay = read_csv(replay_csv)
        flagged = [row for row in replay if row.get("replay") == "flagged"]
        counts = Counter(row.get("replay", "") for row in replay)
        print(f"D1 current fixed check (after T144): {len(flagged)} flagged of {len(replay)} recorded texts "
              f"({counts.get('unverifiable', 0)} unverifiable, {counts.get('clear', 0)} clear); "
              + ("no rows to compare." if not flagged else "the labelled rows among them are compared below."))
        if flagged:
            ids = {row["flag_id"] for row in flagged}
            print(agreement_line("D1 current flags", pairs([row for row in d1_out if row["flag_id"] in ids])))
    else:
        print(f"D1 current fixed check (after T144): no {os.path.basename(replay_csv)}; not computed.")
    print(agreement_line("D2 recorded stance flags (before T144)", pairs(d2_out)))
    current = current_d2_flags(args.runs)
    if current is None:
        print(f"D2 current reason rule (after T144): not computed ({args.runs} is not a folder).")
    else:
        print(f"D2 current reason rule (after T144): {current['flagged']} flagged of {current['ballots']} ballots; "
              + ("no rows to compare." if not current["flagged"] else
                 "the fixed rule's flags have no labelled evidence rows in docs/detector_labels."))
    return 0


# ---- command line --------------------------------------------------------------------------------------------

def add_api_args(parser):
    parser.add_argument("--model", default="jev-latest",
                        help="the TypeSafe model alias or versioned id (default: jev-latest)")
    parser.add_argument("--base-url", default="",
                        help="the System One server (default: https://api.typesafe.ai; tests use the stub)")
    parser.add_argument("--timeout", type=int, default=30, help="seconds per HTTP request (default: 30)")
    parser.add_argument("--retries", type=int, default=2, help="retries on 429/5xx (default: 2)")
    parser.add_argument("--dry-run", action="store_true",
                        help="build the requests and print the cost estimate; send nothing and need no key")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="jev_annotate", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_sample = sub.add_parser("sample", help="label an exit-audit sample CSV with annotator_2")
    p_sample.add_argument("sample", help="the CSV written by tools/exit_audit.py sample")
    p_sample.add_argument("--out", default="", help="the output CSV (default: <sample>.jev.csv)")
    p_sample.add_argument("--limit", type=int, default=0, help="label only the first N rows (a trial run)")
    add_api_args(p_sample)
    p_sample.set_defaults(func=cmd_sample)
    p_re = sub.add_parser("reaudit", help="label the D1 and D2 rows and report agreement before and after T144")
    p_re.add_argument("--labels-dir", default=DETECTOR_DIR,
                      help="the evidence and label CSVs (default: docs/detector_labels)")
    p_re.add_argument("--out-dir", default=DETECTOR_DIR,
                      help="where D1_jev_labels.csv and D2_jev_labels.csv are written (default: docs/detector_labels)")
    p_re.add_argument("--runs", default=RESEARCH_RUNS,
                      help="read-only recorded runs for the current D2 rule (default: the live research runs)")
    add_api_args(p_re)
    p_re.set_defaults(func=cmd_reaudit)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except AnnotateError as exc:
        print(f"jev_annotate: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
