"""Retrieval evaluation for the terminology RAG: does the correct concept appear in the retriever's top-k?

  python -m aip.rag_eval                     # evaluates on the strings the rule dictionary could not resolve in data/
Reports recall@k and MRR, plus how much smaller the LLM prompt gets versus listing the whole vocabulary menu.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from . import vocab as V
from .kb import Retriever
from .rules import Normalizer, _mention_items
from .schema import load_records


def unresolved_terms(records: list) -> dict:
    norm, out = Normalizer(), {}
    for r in records:
        for kind, text, _ in _mention_items(r):
            key = (kind, text.strip().casefold())
            if key[1] and norm.resolve(kind, text)[0] is None:
                out[key] = out.get(key, 0) + 1
    return out


def evaluate(terms: dict, retr: Retriever, ks=(1, 3, 5, 10)) -> dict:
    hits = {k: 0 for k in ks}
    rr, n, fails = 0.0, 0, []
    by_kind = defaultdict(lambda: [0, 0])
    for (kind, text), _ in terms.items():
        truth = V.resolve(kind, text)
        if truth is None:
            continue
        cands = [d.meta["cid"] for d in retr.term_candidates(text, kind, k=max(ks))]
        n += 1
        by_kind[kind][1] += 1
        rank = cands.index(truth) + 1 if truth in cands else None
        for k in ks:
            hits[k] += bool(rank and rank <= k)
        rr += 1.0 / rank if rank else 0.0
        by_kind[kind][0] += bool(rank and rank <= 5)
        if not (rank and rank <= 5):
            fails.append((kind, text, truth, cands[:3]))
    menu = {k: len(V.concepts_of(k)) for k in (V.DX, V.MED, V.ALLERGY)}
    return dict(n_terms=n, recall_at={k: hits[k] / n for k in ks}, mrr=rr / n,
                recall_at_5_by_kind={k: v[0] / v[1] for k, v in by_kind.items()},
                menu_sizes=menu, failures=fails)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="results/rag_retrieval.json")
    a = ap.parse_args(argv)
    terms = unresolved_terms(load_records(Path(a.data) / "records.jsonl"))
    res = evaluate(terms, Retriever())
    print(f"{res['n_terms']} unresolved terms (LLM-bound) | recall@1/3/5/10 = "
          + " / ".join(f"{res['recall_at'][k]:.2f}" for k in (1, 3, 5, 10)) + f" | MRR {res['mrr']:.2f}")
    print("recall@5 by kind:", {k: round(v, 2) for k, v in res["recall_at_5_by_kind"].items()},
          "| full-menu sizes (no retrieval):", res["menu_sizes"])
    for f in res["failures"][:12]:
        print("  miss@5:", f)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({k: v for k, v in res.items() if k != "failures"} | {"n_failures_at_5": len(res["failures"]),
                                      "failures": [list(map(str, f)) for f in res["failures"]]}, indent=2, default=str))


if __name__ == "__main__":
    main()
