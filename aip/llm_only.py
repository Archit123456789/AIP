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


def run_llm_only(records: list, chunk_size: int = 25, llm=None):
    llm = llm or default_client()
    ordered = sorted(records, key=_sort_key)
    known = {r.record_id for r in records}
    issues, dropped = [], 0
    for i in range(0, len(ordered), chunk_size):
        chunk = ordered[i:i + chunk_size]
        prompt = (f"{CATEGORY_DEFS}\nBelow are {len(chunk)} records, sorted by patient name. Records may belong to the same "
                  f"patient across different source systems (names/local refs differ per source). Find every data-quality issue.\n\n"
                  f"{render_records(chunk)}\n\n{OUTPUT_SPEC}")
        obj = llm.generate_json(prompt, system=SYSTEM, tag="llm_only")
        ids_in_chunk = {r.record_id for r in chunk}
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
    meta.update(model=llm.model, chunk_size=chunk_size, malformed_issues_dropped=dropped)
    return issues, meta
