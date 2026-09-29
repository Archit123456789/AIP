"""Evaluation harness (Step 5): score any system's predicted issues against ground_truth.jsonl.

Matching (a prediction P matches a truth issue T) requires ALL of:
  - same issue_type
  - same field root (e.g. "medications"), when both sides give a field_path
  - record overlap: |P.records & T.records| >= need, where need = min(2, |T|) for
    duplicate/terminology (cross-record by nature) and 1 otherwise.

Metrics (plain-text equations):
  precision = #predictions matching >=1 truth / #predictions
  recall    = #truth issues matched by >=1 prediction / #truth issues
  F1        = 2 * P * R / (P + R)
  FDR       = 1 - precision
  FPR       = #FP units / #negative units, where a unit is a (record, issue_type) pair; a unit is
              positive if any truth issue of that type touches the record; a FP unit is a negative
              unit touched by some prediction of that type.  (Issue-level TN is undefined, so the
              record x type grid is the denominator.)
  issue-level accuracy = among truth issues that some prediction *localises* (record overlap and
              same field root), the fraction where a localising prediction also has the right type.
  macro-F1  = mean of per-type F1 (terminology has ~10x more items than any other type, so micro
              numbers are dominated by it; look at macro and per-type rows).
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .schema import (
    ISSUE_TYPES, DUPLICATE, TERMINOLOGY, field_root, load_labels, load_predictions, load_records, read_jsonl,
)


def _need(truth):
    return min(2, len(truth.record_ids)) if truth.issue_type in (DUPLICATE, TERMINOLOGY) else 1


def _root_ok(p, t):
    rp, rt = field_root(p.field_path), field_root(t.field_path)
    return not rp or not rt or rp == rt


def matches(p, t) -> bool:
    return (p.issue_type == t.issue_type and _root_ok(p, t)
            and len(set(p.record_ids) & set(t.record_ids)) >= _need(t))


def _prf(tp_pred, n_pred, tp_truth, n_truth):
    p = tp_pred / n_pred if n_pred else 0.0
    r = tp_truth / n_truth if n_truth else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def score(preds: list, truth: list, n_records: int) -> dict:
    by_type_t = defaultdict(list)
    for t in truth:
        by_type_t[t.issue_type].append(t)
    by_type_p = defaultdict(list)
    for p in preds:
        by_type_p[p.issue_type].append(p)

    def block(ps, ts):
        tp_pred = sum(any(matches(p, t) for t in ts) for p in ps)
        tp_truth = sum(any(matches(p, t) for p in ps) for t in ts)
        P, R, F = _prf(tp_pred, len(ps), tp_truth, len(ts))
        return dict(n_pred=len(ps), n_truth=len(ts), tp_pred=tp_pred, tp_truth=tp_truth,
                    precision=P, recall=R, f1=F, fdr=1 - P if ps else 0.0)

    overall = block(preds, truth)
    per_type = {}
    for ty in ISSUE_TYPES:
        # match against ALL truth of the type; predictions of other types can never match
        per_type[ty] = block(by_type_p[ty], by_type_t[ty])
    macro_f1 = sum(v["f1"] for v in per_type.values() if v["n_truth"]) / max(1, sum(1 for v in per_type.values() if v["n_truth"]))

    # record x type false-positive rate
    pos = defaultdict(set)
    for t in truth:
        for r in t.record_ids:
            pos[t.issue_type].add(r)
    fp_units = set()
    for p in preds:
        for r in p.record_ids:
            if r not in pos[p.issue_type]:
                fp_units.add((r, p.issue_type))
    n_pos = sum(len(v) for v in pos.values())
    n_neg = n_records * len(ISSUE_TYPES) - n_pos
    fpr = len(fp_units) / n_neg if n_neg > 0 else 0.0

    # issue-level accuracy (classification of localised issues)
    localised = correct = 0
    for t in truth:
        loc = [p for p in preds if set(p.record_ids) & set(t.record_ids) and _root_ok(p, t)]
        if loc:
            localised += 1
            correct += any(p.issue_type == t.issue_type for p in loc)
    acc = correct / localised if localised else 0.0
    return dict(overall=overall, per_type=per_type, macro_f1=macro_f1, fpr_record_type=fpr,
                fp_units=len(fp_units), neg_units=n_neg, issue_level_accuracy=acc,
                localised=localised, truth_total=len(truth))


def linkage_score(clusters: dict, links: dict) -> dict:
    """Pairwise precision/recall of patient linkage (only meaningful for systems that link)."""
    def pairs(m):
        g = defaultdict(list)
        for r, c in m.items():
            g[c].append(r)
        return {frozenset((a, b)) for rs in g.values() for i, a in enumerate(rs) for b in rs[i + 1:]}
    pred, true = pairs(clusters), pairs(links)
    tp = len(pred & true)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(true) if true else 0.0
    return dict(precision=p, recall=r, f1=2 * p * r / (p + r) if p + r else 0.0)


def fmt_table(results: dict) -> str:
    names = list(results)
    lines = ["| Metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]

    def row(label, fn, f="{:.3f}"):
        lines.append(f"| {label} | " + " | ".join(f.format(fn(results[n])) if fn(results[n]) is not None else "n/a" for n in names) + " |")

    row("Precision (micro)", lambda r: r["score"]["overall"]["precision"])
    row("Recall (micro)", lambda r: r["score"]["overall"]["recall"])
    row("F1 (micro)", lambda r: r["score"]["overall"]["f1"])
    row("F1 (macro over types)", lambda r: r["score"]["macro_f1"])
    row("False-discovery rate", lambda r: r["score"]["overall"]["fdr"])
    row("FP rate (record x type)", lambda r: r["score"]["fpr_record_type"], "{:.4f}")
    row("Issue-level accuracy", lambda r: r["score"]["issue_level_accuracy"])
    for ty in ISSUE_TYPES:
        row(f"F1 - {ty}", lambda r, ty=ty: r["score"]["per_type"][ty]["f1"])
    row("Predictions", lambda r: r["score"]["overall"]["n_pred"], "{:d}")
    row("LLM calls", lambda r: r["meta"].get("llm_calls", 0), "{:d}")
    row("Input tokens", lambda r: r["meta"].get("input_tokens", 0), "{:d}")
    row("Output tokens", lambda r: r["meta"].get("output_tokens", 0), "{:d}")
    row("Cost (USD)", lambda r: r["meta"].get("cost_usd", 0.0), "{:.4f}")
    row("Wall latency (s)", lambda r: r["meta"].get("wall_seconds", 0.0), "{:.1f}")
    lines.append("")
    lines.append("Per-type precision / recall:")
    lines.append("")
    lines.append("| Type | n_truth | " + " | ".join(f"{n} P / R" for n in names) + " |")
    lines.append("|---|---|" + "---|" * len(names))
    for ty in ISSUE_TYPES:
        nt = results[names[0]]["score"]["per_type"][ty]["n_truth"]
        cells = [f"{results[n]['score']['per_type'][ty]['precision']:.2f} / {results[n]['score']['per_type'][ty]['recall']:.2f}" for n in names]
        lines.append(f"| {ty} | {nt} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def evaluate_files(pred_files: dict, data_dir: str) -> dict:
    d = Path(data_dir)
    truth = load_labels(d / "ground_truth.jsonl")
    n_records = sum(1 for _ in read_jsonl(d / "records.jsonl"))
    links = {x["record_id"]: x["patient_id"] for x in read_jsonl(d / "patient_links.jsonl")}
    out = {}
    for name, path in pred_files.items():
        preds = load_predictions(path)
        meta_path = Path(path).with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        entry = dict(score=score(preds, truth, n_records), meta=meta)
        if meta.get("clusters"):
            entry["linkage"] = linkage_score(meta["clusters"], links)
        out[name] = entry
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Score prediction files against ground truth.")
    ap.add_argument("--data", default="data")
    ap.add_argument("--results", default="results")
    ap.add_argument("--systems", default="rules,llm_only,hybrid")
    a = ap.parse_args(argv)
    files = {}
    for s in a.systems.split(","):
        p = Path(a.results) / f"{s}.jsonl"
        if p.exists():
            files[s] = p
        else:
            print(f"[skip] {p} not found (system '{s}' has not been run)")
    res = evaluate_files(files, a.data)
    table = fmt_table(res)
    print(table)
    for n, r in res.items():
        if "linkage" in r:
            print(f"\n[{n}] patient-linkage pairwise P/R/F1: "
                  f"{r['linkage']['precision']:.3f} / {r['linkage']['recall']:.3f} / {r['linkage']['f1']:.3f}")
    Path(a.results).mkdir(parents=True, exist_ok=True)
    (Path(a.results) / "metrics.json").write_text(json.dumps(res, indent=2))
    (Path(a.results) / "metrics.md").write_text(table + "\n")


if __name__ == "__main__":
    main()
