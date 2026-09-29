"""Prompt building blocks shared by the LLM-only baseline and the hybrid's LLM stages."""
from __future__ import annotations

from .schema import ClinicalRecord

SYSTEM = (
    "You are a clinical data-quality auditor. You flag potential data-quality problems in synthetic, "
    "de-identified patient records for HUMAN review. You never make clinical decisions or recommendations "
    "about treatment. Be precise: only report a problem when the record text itself supports it. "
    "Respond with JSON only."
)

CATEGORY_DEFS = """Issue categories (use exactly these issue_type strings):
- "duplicate": two records that are the same encounter recorded twice (same person, same/adjacent-day encounter,
  near-identical content, possibly different source system or name spelling). record_ids = the two records; field_path = "record".
  Two different visits days/weeks apart are NOT duplicates.
- "contradiction": conflicting clinical/demographic information: conflicting doses of the same drug in the same care episode
  (field_path "medications[<drug>].dose"), an allergy documented in earlier records but "no known allergies" in a later one
  ("allergies"), mutually exclusive diagnoses e.g. type 1 vs type 2 diabetes ("diagnoses"), sex-incompatible diagnosis
  ("diagnoses"), a drug that conflicts with a documented allergy ("medications"), sex / date_of_birth disagreeing across records of
  one patient ("sex" / "date_of_birth"), or free-text notes that contradict the same record's structured fields ("notes").
  An allergy acquired later, or a new dose after a long gap, is NOT a contradiction.
- "missing": a critical field is null/empty: date_of_birth, sex, encounter_date, encounter_type, allergy status
  (neither allergies nor NKDA), diagnoses, a medication's dose. field_path = the field, e.g. "date_of_birth" or "medications[<drug>].dose".
- "temporal": impossible/implausible dates: end before start, resolved before onset, onset after the encounter, encounter in the future
  (today is 2025-06-30) or before birth, medication start before birth. field_path e.g. "medications[<drug>].end_date", "encounter_date".
- "terminology": the SAME concept (diagnosis, drug, allergen) written with different surface forms (abbreviation, brand vs generic,
  synonym, misspelling) across the records of one patient. record_ids = all records of that patient using any of the forms;
  field_path = "diagnoses", "medications" or "allergies".
"""

OUTPUT_SPEC = """Return JSON: {"issues": [{"issue_type": <one of the five>, "record_ids": [<ids from the input only>],
"field_path": <string>, "description": <one sentence citing the evidence>}]}. Return {"issues": []} if nothing is wrong."""


def render_record(r: ClinicalRecord, include_note: bool = True) -> str:
    def v(x):
        return "NULL" if x is None or x == "" else x
    lines = [f"[{r.record_id}] source={r.source_system} local_ref={r.local_patient_ref} type={v(r.encounter_type)} "
             f"date={v(r.encounter_date)} name={v(r.patient_name)!r} sex={v(r.sex)} dob={v(r.date_of_birth)}"]
    dx = "; ".join(f"{d.name} (onset {v(d.onset_date)}, resolved {v(d.resolved_date)}, {v(d.status)})" for d in r.diagnoses)
    lines.append(f"  diagnoses: {dx or 'NONE LISTED'}")
    meds = "; ".join(f"{m.name} dose={v(m.dose)}{m.unit or ''} freq={v(m.frequency)} start={v(m.start_date)} end={v(m.end_date)}"
                     for m in r.medications)
    lines.append(f"  medications: {meds or 'NONE LISTED'}")
    if r.allergies is None:
        lines.append("  allergies: NOT DOCUMENTED (null)")
    else:
        al = "; ".join(f"{a.substance}" + (f" ({a.reaction})" if a.reaction else "") for a in r.allergies)
        lines.append(f"  allergies: {al or 'NOT DOCUMENTED (empty list)'}")
    if include_note:
        lines.append(f"  note: {v(r.notes)}")
    return "\n".join(lines)


def render_records(records: list, include_note: bool = True) -> str:
    return "\n".join(render_record(r, include_note) for r in records)
