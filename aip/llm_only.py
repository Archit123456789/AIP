"""LLM-only baseline (Step 3): raw records straight to Gemini, no rules, same issue-label output format.

Fairness notes
  - The model gets the same category definitions / field_path conventions the hybrid's prompts use.
  - It gets NO vocabulary, NO linkage, NO date arithmetic helpers.
  - Records are sorted by (last name, first name, DOB) and sent in chunks (default 25). That sort is the
    minimum needed to make cross-record checks feasible in a finite context; a patient whose records straddle a
    chunk boundary loses cross-record checks (a real limitation of this baseline; use --chunk-size to trade cost for recall).
"""
from __future__ import annotations

from .llm import LLMUnavailable, default_client
from .prompts import CATEGORY_DEFS, OUTPUT_SPEC, SYSTEM, render_records
from .rules import parse_name
from .schema import ISSUE_TYPES, PredictedIssue


def _sort_key(r):
    f, l = parse_name(r.patient_name)
    return (l, f, r.date_of_birth or "", r.encounter_date or "")


def run_llm_only(records: list, chunk_size: int = 25, llm=None, workers: int = 1):
    llm = llm or default_client()
    ordered = sorted(records, key=_sort_key)
    known = {r.record_id for r in records}
    issues, dropped = [], 0
    chunks = [ordered[i:i + chunk_size] for i in range(0, len(ordered), chunk_size)]
    make_prompt = lambda c: (f"{CATEGORY_DEFS}\nBelow are {len(c)} records, sorted by patient name. Records may belong to the same "
                             f"patient across different source systems (names/local refs differ per source). Find every data-quality issue.\n\n"
                             f"{render_records(c)}\n\n{OUTPUT_SPEC}")
    prompts = [make_prompt(c) for c in chunks]
    call = lambda p: llm.generate_json(p, system=SYSTEM, tag="llm_only")
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            objs = list(ex.map(call, prompts))          # order-preserving; calls are independent
    else:
        objs = [call(p) for p in prompts]
    # A chunk whose answer is still unparseable after the client's retry (typically the model exhausted its output-token
    # budget) is split in half and re-asked, recursively. Splitting costs some cross-record context; it is logged in meta.
    splits = []

    def ask(chunk, depth=0):
        obj = call(make_prompt(chunk))
        if obj is None and len(chunk) > 4 and depth < 3:
            splits.append(len(chunk))
            mid = len(chunk) // 2
            return ask(chunk[:mid], depth + 1) + ask(chunk[mid:], depth + 1)
        return [(chunk, obj)]

    pairs = []
    for chunk, obj in zip(chunks, objs):
        pairs += ask(chunk) if obj is None else [(chunk, obj)]
    for chunk, obj in pairs:
        for it in (obj or {}).get("issues", []) if isinstance(obj, dict) else []:
            rids = [x for x in it.get("record_ids", []) if x in known]
            if it.get("issue_type") not in ISSUE_TYPES or not rids:
                dropped += 1
                continue
            issues.append(PredictedIssue(
                issue_id=f"L{len(issues) + 1:05d}", issue_type=it["issue_type"], record_ids=rids, patient_id=None,
                description=str(it.get("description", "")), field_path=str(it.get("field_path", "")),
                detector="llm_only", confidence=0.5, explanation=str(it.get("description", "")),
                evidence=[dict(record_id=x, field=str(it.get("field_path", "")), value="(see description)") for x in rids[:3]]))
    meta = llm.stats.as_meta()
    meta.update(model=llm.model, chunk_size=chunk_size, workers=workers, malformed_issues_dropped=dropped,
                split_events=len(splits), split_chunk_sizes=splits)
    return issues, meta
