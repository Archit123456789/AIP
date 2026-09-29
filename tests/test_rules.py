from aip.rules import run_rules, link_patients
from aip.schema import ClinicalRecord, Diagnosis, Medication, Allergy


def rec(rid, name="John Smith", dob="1960-01-01", sex="M", date="2024-05-01", src="A", ref="1", **kw):
    base = dict(record_id=rid, local_patient_ref=ref, source_system=src, encounter_type="outpatient",
                encounter_date=date, sex=sex, date_of_birth=dob, patient_name=name,
                diagnoses=[Diagnosis("hypertension", "2010-01-01")], medications=[], allergies=[Allergy("NKDA")], notes=None)
    base.update(kw)
    return ClinicalRecord(**base)


def types(res, t):
    return [i for i in res.issues if i.issue_type == t]


def test_linkage_name_variants_but_not_twins_or_homonyms():
    rs = [rec("1", "John Smith", ref="1"), rec("2", "SMITH, JOHN", src="B", ref="2"),
          rec("3", "Jon Smith", src="C", ref="3"),                                    # typo -> same patient
          rec("4", "James Smith", ref="9"),                                            # twin: same DOB, different first name
          rec("5", "John Smith", dob="1985-07-07", ref="8")]                           # homonym: different DOB
    c = link_patients(rs)
    assert c["1"] == c["2"] == c["3"]
    assert len({c["4"], c["5"], c["1"]}) == 3


def test_dose_conflict_only_within_window():
    m = lambda d: [Medication("metformin", d, "mg", "twice daily", "2020-01-01")]
    close = run_rules([rec("1", medications=m(500), date="2024-05-01"), rec("2", src="B", ref="2", medications=m(1000), date="2024-05-06")])
    far = run_rules([rec("1", medications=m(500), date="2024-01-01"), rec("2", src="B", ref="2", medications=m(1000), date="2024-06-06")])
    assert types(close, "contradiction") and not types(far, "contradiction")


def test_allergy_vs_nkda_is_time_aware():
    allergic = lambda rid, d: rec(rid, date=d, src=rid, ref=rid, allergies=[Allergy("penicillin", "rash")])
    nkda = lambda rid, d: rec(rid, date=d, src=rid, ref=rid)
    later_nkda = run_rules([allergic("1", "2024-01-01"), nkda("2", "2024-06-01")])
    acquired = run_rules([nkda("1", "2024-01-01"), allergic("2", "2024-06-01")])
    assert types(later_nkda, "contradiction") and not types(acquired, "contradiction")


def test_temporal_cascade_suppressed_when_encounter_date_impossible():
    r = rec("1", date="1950-01-01", diagnoses=[Diagnosis("hypertension", "2010-01-01")])   # encounter before DOB
    res = run_rules([r])
    t = types(res, "temporal")
    assert len(t) == 1 and t[0].field_path == "encounter_date"


def test_missing_and_end_before_start():
    r = rec("1", sex=None, allergies=None, medications=[Medication("aspirin", 81, "mg", "once daily", "2020-05-01", "2020-01-01")])
    res = run_rules([r])
    assert {i.field_path for i in types(res, "missing")} == {"sex", "allergies"}
    assert any("end_date" in i.field_path for i in types(res, "temporal"))


def test_explicit_note_contradiction_and_decoy():
    bad = rec("1", allergies=[Allergy("PCN", "rash")], notes="Follow-up. Patient denies any drug allergies.")
    decoy = rec("2", name="Ann Lee", allergies=[Allergy("PCN", "rash")], notes="Follow-up. Denies any new allergies. Denies chest pain.")
    res = run_rules([bad, decoy])
    flagged = {r for i in types(res, "contradiction") for r in i.record_ids}
    assert "1" in flagged and "2" not in flagged
    assert "2" in res.note_candidates          # ambiguous -> handed to the LLM in the hybrid


def test_terminology_dictionary_vs_residual():
    a = rec("1", diagnoses=[Diagnosis("CVA")]); b = rec("2", src="B", ref="2", diagnoses=[Diagnosis("stroke")])
    c = rec("3", src="C", ref="3", diagnoses=[Diagnosis("brain attack")])           # hard form: only LLM can map
    res = run_rules([a, b, c])
    assert len(types(res, "terminology")) == 1 and set(types(res, "terminology")[0].record_ids) == {"1", "2"}
    assert ("dx", "brain attack") in res.unresolved_terms
