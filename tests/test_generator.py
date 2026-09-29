import json
from datetime import date

from aip import vocab as V
from aip.generator import GenConfig, generate, REF_DATE
from aip.schema import TEMPORAL, MISSING, TERMINOLOGY, DUPLICATE


def _gen(seed=7, n=60):
    return generate(GenConfig(n_patients=n, seed=seed))


def test_reproducible_and_seed_sensitive():
    a, b, c = _gen(7), _gen(7), _gen(8)
    dump = lambda g: json.dumps([r.to_dict() for r in g[0]] + [l.to_dict() for l in g[1]], sort_keys=True)
    assert dump(a) == dump(b)
    assert dump(a) != dump(c)


def test_no_label_or_patient_leakage_in_records():
    records, labels, links, _ = _gen()
    assert all(r.patient_id is None for r in records)
    ids = {r.record_id for r in records}
    assert len(ids) == len(records)
    assert all(set(l.record_ids) <= ids for l in labels)
    assert {x["record_id"] for x in links} == ids


def test_all_five_categories_present():
    _, labels, _, m = generate(GenConfig(n_patients=150, seed=3))
    assert {l.issue_type for l in labels} == {"duplicate", "contradiction", "missing", "temporal", "terminology"}


def test_temporal_and_missing_labels_are_verifiable_from_records():
    records, labels, _, _ = _gen(n=120)
    by = {r.record_id: r for r in records}
    for l in labels:
        r = by[l.record_ids[0]]
        if l.issue_type == MISSING and "." not in l.field_path and l.field_path not in ("allergies", "diagnoses"):
            assert getattr(r, l.field_path) is None
        if l.issue_type == TEMPORAL and l.field_path.endswith("end_date"):
            assert any(m.end_date and m.start_date and m.end_date < m.start_date for m in r.medications)
        if l.issue_type == TEMPORAL and l.field_path == "encounter_date":
            assert r.encounter_date > REF_DATE.isoformat() or r.encounter_date < r.date_of_birth


def test_terminology_labels_have_two_distinct_forms_of_one_concept():
    records, labels, _, _ = _gen(n=80)
    by = {r.record_id: r for r in records}
    for l in labels:
        if l.issue_type != TERMINOLOGY:
            continue
        kind = {"diagnoses": V.DX, "medications": V.MED, "allergies": V.ALLERGY}[l.field_path.split("[")[0]]
        cid = l.field_path.split("[")[1].rstrip("]")
        forms = set()
        for rid in l.record_ids:
            r = by[rid]
            items = {V.DX: [d.name for d in r.diagnoses], V.MED: [m.name for m in r.medications],
                     V.ALLERGY: [a.substance for a in r.allergies or []]}[kind]
            forms |= {x.casefold() for x in items if V.resolve(kind, x) == cid}
        assert len(forms) >= 2


def test_vocab_forms_unique_and_tiers():
    assert V.resolve(V.DX, "heart attack") == "mi" == V.resolve(V.DX, "MI")
    assert V.resolve(V.MED, "Glucophage") == "metformin"
    assert V.resolve_common(V.DX, "sugar diabetes") is None and V.resolve(V.DX, "sugar diabetes") == "t2dm"
