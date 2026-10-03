"""Run one system over records.jsonl and write results/<system>.jsonl + results/<system>.meta.json.

  python -m aip.run --system rules
  python -m aip.run --system llm_only     # needs GEMINI_API_KEY
  python -m aip.run --system hybrid       # needs GEMINI_API_KEY for the LLM stages (else degrades to rules, logged)
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .llm import LLMUnavailable
from .schema import load_records, write_jsonl


def run_system(name: str, records: list, use_patient_id: bool = False, **kw):
    """returns (issues, meta)."""
    t0 = time.perf_counter()
    if name == "rules":
        from .rules import run_rules
        res = run_rules(records, use_patient_id=use_patient_id)
        issues, meta = res.issues, dict(clusters=res.clusters, llm_calls=0, input_tokens=0, output_tokens=0, cost_usd=0.0)
    elif name == "llm_only":
        from .llm_only import run_llm_only
        issues, meta = run_llm_only(records, **kw)
    elif name == "hybrid":
        from .hybrid import run_hybrid
        issues, meta = run_hybrid(records, use_patient_id=use_patient_id, **kw)
    else:
        raise SystemExit(f"unknown system {name!r}")
    meta["wall_seconds"] = time.perf_counter() - t0
    meta["system"] = name
    return issues, meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", required=True, choices=["rules", "llm_only", "hybrid"])
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="results")
    ap.add_argument("--use-patient-id", action="store_true", help="oracle linkage (dataset must expose patient_id)")
    ap.add_argument("--limit-patients", type=int, default=0, help="debug: only first N records' worth (0 = all)")
    ap.add_argument("--no-explain", action="store_true", help="hybrid: skip LLM explanations")
    ap.add_argument("--llm", choices=["gemini", "oracle"], default="gemini",
                    help="oracle = answer-key stand-in for the LLM (plumbing test / ceiling ONLY, not LLM results)")
    ap.add_argument("--rag", action="store_true", help="hybrid: retrieval-augmented term mapping (top-k candidates instead of full menu)")
    ap.add_argument("--rag-k", type=int, default=10)
    ap.add_argument("--workers", type=int, default=1, help="llm_only: parallel Gemini calls (try 4)")
    ap.add_argument("--chunk-size", type=int, default=25, help="llm_only: records per prompt")
    a = ap.parse_args(argv)
    records = load_records(Path(a.data) / "records.jsonl")
    if a.limit_patients:
        records = records[: a.limit_patients]
    kw = {}
    if a.llm == "oracle":
        from .oracle import OracleClient
        from .schema import load_labels
        kw["llm"] = OracleClient(load_labels(Path(a.data) / "ground_truth.jsonl"), records)
    if a.system == "hybrid":
        kw["explain"] = not a.no_explain
        kw["rag"] = a.rag
        kw["rag_k"] = a.rag_k
    if a.system == "llm_only":
        kw["chunk_size"] = a.chunk_size
        kw["workers"] = a.workers
    try:
        issues, meta = run_system(a.system, records, use_patient_id=a.use_patient_id, **kw)
    except LLMUnavailable as e:
        raise SystemExit(f"[{a.system}] cannot run: {e}. Set GEMINI_API_KEY (see README).")
    out = Path(a.out)
    write_jsonl(out / f"{a.system}.jsonl", (i.to_dict() for i in issues))
    (out / f"{a.system}.meta.json").write_text(json.dumps(meta, indent=2))
    print(f"{a.system}: {len(issues)} issues, {meta['wall_seconds']:.1f}s, "
          f"llm_calls={meta.get('llm_calls', 0)}, cost=${meta.get('cost_usd', 0):.4f}")
    for msg in meta.get("skipped_stages", []):
        print(f"  [WARNING] LLM stage skipped -> {msg}")
    if meta.get("skipped_stages"):
        print("  The output above is NOT a real hybrid run (skipped stages fell back to rules).")


if __name__ == "__main__":
    main()
