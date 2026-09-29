"""Deterministic quality rules (Step 2) -- also the first stage of the hybrid pipeline.

Stages
  1. link_patients(): records arrive fragmented with per-source refs, so patients are
     re-linked by fuzzy name + DOB + sex (+ same-source-ref).  Clusters ~= patients.
  2. Per-category checks over records / clusters, each emitting a PredictedIssue with
     evidence and provenance (detector = "rule:<name>").
  3. Anything a rule cannot decide is *returned* (ambiguous duplicate pairs, unresolved
     terms, notes with negation cues) so the hybrid layer can hand exactly those to the LLM.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher
from itertools import combinations
from typing import Optional

from . import vocab as V
from .names import CANON_FIRST
from .schema import (
    ClinicalRecord, PredictedIssue,
    CONTRADICTION, DUPLICATE, MISSING, TEMPORAL, TERMINOLOGY,
)

AS_OF = date(2025, 6, 30)
DUP_DATE_WINDOW_DAYS = 1
DUP_SIM_HIGH = 0.6          # >= : rule flags duplicate
DUP_SIM_LOW = 0.3           # [LOW, HIGH): ambiguous -> LLM in hybrid
DOSE_WINDOW_DAYS = 21
FUZZY_TERM_THRESHOLD = 0.88


def _d(s: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


# ============================================================ patient linkage
def parse_name(name: Optional[str]):
    if not name:
        return "", ""
    n = re.sub(r"[^\w\s,]", " ", name.lower())
    if "," in n:
        last, _, rest = n.partition(",")
        toks = rest.split()
        first = toks[0] if toks else ""
        last = last.strip()
    else:
        toks = n.split()
        if not toks:
            return "", ""
        first, last = toks[0], toks[-1]
    return CANON_FIRST.get(first, first), last


def _ratio(a, b):
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def _first_sim(a, b):
    if not a or not b:
        return 0.5
    if a == b:
        return 1.0
    if a[0] == b[0] and (len(a) == 1 or len(b) == 1):
        return 0.8
    return _ratio(a, b)


def _dob_sim(a, b):
    if not a or not b:
        return None
    if a == b:
        return 1.0
    if len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1:
        return 0.8
    ya, ma, da = a.split("-")
    yb, mb, db = b.split("-")
    if ya == yb and ma == db and da == mb:
        return 0.8                          # day/month transposition
    return 0.0


def link_score(a: ClinicalRecord, b: ClinicalRecord) -> float:
    fa, la = parse_name(a.patient_name)
    fb, lb = parse_name(b.patient_name)
    last, first = _ratio(la, lb), _first_sim(fa, fb)
    if last < 0.75 or first < 0.6:
        return 0.0
    dob = _dob_sim(a.date_of_birth, b.date_of_birth)
    if dob == 0.0:
        return 0.0
    if dob is None:                          # DOB missing on one side: only link on strong name + same source ref
        same_ref = a.source_system == b.source_system and a.local_patient_ref == b.local_patient_ref
        return 0.95 if same_ref and last > 0.9 else 0.0
    sex = 1.0 if (a.sex is None or b.sex is None or a.sex == b.sex) else 0.7
    return 0.4 * last + 0.25 * first + 0.25 * dob + 0.1 * sex


def link_patients(records: list, use_patient_id: bool = False, threshold: float = 0.85) -> dict:
    """record_id -> cluster id."""
    if use_patient_id and all(r.patient_id for r in records):
        return {r.record_id: r.patient_id for r in records}
    parent = {r.record_id: r.record_id for r in records}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    blocks = defaultdict(list)
    for r in records:
        f, l = parse_name(r.patient_name)
        for key in {("dob", r.date_of_birth), ("ln", l[:3]), ("fn", f[:3], r.date_of_birth)}:
            if key[1] is not None and key[1] != "":
                blocks[key].append(r)
    for rs in blocks.values():
        for a, b in combinations(rs, 2):
            if find(a.record_id) != find(b.record_id) and link_score(a, b) >= threshold:
                parent[find(a.record_id)] = find(b.record_id)
    ids, out = {}, {}
    for r in sorted(records, key=lambda r: r.record_id):
        root = find(r.record_id)
        out[r.record_id] = ids.setdefault(root, f"C{len(ids) + 1:04d}")
    return out


# ============================================================ normalization
class Normalizer:
    """Surface form -> concept id using the rule dictionary (common tier) + typo-tolerant fuzzy match."""

    def __init__(self):
        self._cache = {}
        self._candidates = {}
        for kind in (V.DX, V.MED, V.ALLERGY):
            self._candidates[kind] = [(f.casefold(), c.cid) for c in V.concepts_of(kind)
                                      for f in (c.canonical,) + c.common if len(f) >= 7]

    def resolve(self, kind: str, text: str, llm_map: dict | None = None):
        """returns (cid | None, method)."""
        key = (kind, (text or "").strip().casefold())
        if not key[1]:
            return None, "empty"
        if key not in self._cache:
            cid = V.resolve_common(kind, key[1])
            res = (cid, "dictionary") if cid else (None, "unresolved")
            if not cid and len(key[1]) >= 7:
                best, best_r = None, 0.0
                for form, c in self._candidates[kind]:
                    r = SequenceMatcher(None, key[1], form).ratio()
                    if r > best_r:
                        best, best_r = c, r
                if best_r >= FUZZY_TERM_THRESHOLD:
                    res = (best, "fuzzy")
            self._cache[key] = res
        res = self._cache[key]
        if res[0] is None and llm_map and key in llm_map and llm_map[key]:
            return llm_map[key], "llm"
        return res


def _mention_items(r: ClinicalRecord):
    """(kind, surface text, field path root) for every normalizable mention in a record."""
    for d in r.diagnoses:
        yield V.DX, d.name, "diagnoses"
    for m in r.medications:
        yield V.MED, m.name, "medications"
    for a in r.allergies or []:
        yield V.ALLERGY, a.substance, "allergies"


# ============================================================ result container
@dataclass
class RuleResult:
    issues: list = field(default_factory=list)
    clusters: dict = field(default_factory=dict)            # record_id -> cluster id
    ambiguous_duplicates: list = field(default_factory=list)   # [(rec_a, rec_b, sim)]
    unresolved_terms: dict = field(default_factory=dict)    # (kind, casefolded text) -> [record ids]
    note_candidates: list = field(default_factory=list)     # record ids with unresolved free-text assertions


# ============================================================ the engine
class RuleEngine:
    def __init__(self, records: list, as_of: date = AS_OF, use_patient_id: bool = False,
                 llm_term_map: dict | None = None):
        self.records = records
        self.by_id = {r.record_id: r for r in records}
        self.as_of = as_of
        self.use_patient_id = use_patient_id
        self.norm = Normalizer()
        self.llm_term_map = llm_term_map or {}
        self.issues: list = []
        self.res = RuleResult()

    # --------------------------------------------------------------- utils
    def _emit(self, itype, recs, desc, path, detector, evidence, conf=1.0):
        ids = list(dict.fromkeys(r if isinstance(r, str) else r.record_id for r in recs))
        pid = self.clusters.get(ids[0])
        self.issues.append(PredictedIssue(
            issue_id=f"P{len(self.issues) + 1:05d}", issue_type=itype, record_ids=ids, patient_id=pid,
            description=desc, field_path=path, detector=f"rule:{detector}", confidence=conf, evidence=evidence))

    @staticmethod
    def _ev(r, fieldname, value):
        return dict(record_id=r.record_id, field=fieldname, value=value)

    def cid(self, kind, text):
        return self.norm.resolve(kind, text, self.llm_term_map)[0]

    # ----------------------------------------------------------------- run
    def run(self) -> RuleResult:
        self.clusters = link_patients(self.records, self.use_patient_id)
        groups = defaultdict(list)
        for r in self.records:
            groups[self.clusters[r.record_id]].append(r)
        self.groups = groups
        for r in self.records:
            self.check_missing(r)
            self.check_temporal(r)
            self.check_sex_dx(r)
            self.check_note_assertions(r)
        for recs in groups.values():
            self.check_duplicates(recs)
            self.check_dose_conflict(recs)
            self.check_allergy_nkda(recs)
            self.check_dx_exclusive(recs)
            self.check_allergy_med(recs)
            self.check_demographics(recs)
            self.check_terminology(recs)
        self.res.issues = self.issues
        self.res.clusters = self.clusters
        return self.res

    # ------------------------------------------------------------- missing
    def check_missing(self, r):
        for f, label in (("date_of_birth", "date of birth"), ("sex", "sex"), ("encounter_date", "encounter date"),
                         ("encounter_type", "encounter type"), ("patient_name", "patient name")):
            if not getattr(r, f):
                self._emit(MISSING, [r], f"Missing {label}.", f, "null_field", [self._ev(r, f, None)])
        if not r.allergies:
            self._emit(MISSING, [r], "Allergy status undocumented (neither allergies nor NKDA recorded).",
                       "allergies", "null_field", [self._ev(r, "allergies", r.allergies)])
        if not r.diagnoses:
            self._emit(MISSING, [r], "Record has no diagnoses.", "diagnoses", "null_field",
                       [self._ev(r, "diagnoses", [])])
        for m in r.medications:
            if m.dose is None:
                cid = self.cid(V.MED, m.name) or m.name
                self._emit(MISSING, [r], f"Medication {m.name} has no dose.", f"medications[{cid}].dose",
                           "null_field", [self._ev(r, f"medications[{m.name}].dose", None)])

    # ------------------------------------------------------------ temporal
    def check_temporal(self, r):
        enc, dob = _d(r.encounter_date), _d(r.date_of_birth)
        enc_bad = False
        if enc and enc > self.as_of:
            enc_bad = True
            self._emit(TEMPORAL, [r], f"Encounter date {r.encounter_date} is in the future (as-of {self.as_of}).",
                       "encounter_date", "future_encounter", [self._ev(r, "encounter_date", r.encounter_date)])
        if enc and dob and enc < dob:
            enc_bad = True
            self._emit(TEMPORAL, [r], f"Encounter date {r.encounter_date} precedes date of birth {r.date_of_birth}.",
                       "encounter_date", "encounter_before_dob",
                       [self._ev(r, "encounter_date", r.encounter_date), self._ev(r, "date_of_birth", r.date_of_birth)])
        for m in r.medications:
            s, e = _d(m.start_date), _d(m.end_date)
            cid = self.cid(V.MED, m.name) or m.name
            if s and e and e < s:
                self._emit(TEMPORAL, [r], f"Medication {m.name} end_date {m.end_date} is before start_date {m.start_date}.",
                           f"medications[{cid}].end_date", "end_before_start",
                           [self._ev(r, f"medications[{m.name}].start_date", m.start_date),
                            self._ev(r, f"medications[{m.name}].end_date", m.end_date)])
            if s and dob and s < dob:
                self._emit(TEMPORAL, [r], f"Medication {m.name} start_date {m.start_date} precedes date of birth {r.date_of_birth}.",
                           f"medications[{cid}].start_date", "med_before_dob",
                           [self._ev(r, f"medications[{m.name}].start_date", m.start_date),
                            self._ev(r, "date_of_birth", r.date_of_birth)])
            if s and enc and not enc_bad and s > enc:
                self._emit(TEMPORAL, [r], f"Medication {m.name} start_date {m.start_date} is after the encounter date {r.encounter_date}.",
                           f"medications[{cid}].start_date", "med_after_encounter",
                           [self._ev(r, f"medications[{m.name}].start_date", m.start_date),
                            self._ev(r, "encounter_date", r.encounter_date)])
        for dx in r.diagnoses:
            o, res = _d(dx.onset_date), _d(dx.resolved_date)
            cid = self.cid(V.DX, dx.name) or dx.name
            if o and res and res < o:
                self._emit(TEMPORAL, [r], f"Diagnosis {dx.name} resolved_date {dx.resolved_date} precedes onset_date {dx.onset_date}.",
                           f"diagnoses[{cid}].resolved_date", "resolved_before_onset",
                           [self._ev(r, f"diagnoses[{dx.name}].onset_date", dx.onset_date),
                            self._ev(r, f"diagnoses[{dx.name}].resolved_date", dx.resolved_date)])
            if o and enc and not enc_bad and o > enc:
                self._emit(TEMPORAL, [r], f"Diagnosis {dx.name} onset_date {dx.onset_date} is after the encounter date {r.encounter_date}.",
                           f"diagnoses[{cid}].onset_date", "onset_after_encounter",
                           [self._ev(r, f"diagnoses[{dx.name}].onset_date", dx.onset_date),
                            self._ev(r, "encounter_date", r.encounter_date)])
            if o and o > self.as_of and not (enc and not enc_bad and o > enc):
                self._emit(TEMPORAL, [r], f"Diagnosis {dx.name} onset_date {dx.onset_date} is in the future (as-of {self.as_of}).",
                           f"diagnoses[{cid}].onset_date", "future_onset",
                           [self._ev(r, f"diagnoses[{dx.name}].onset_date", dx.onset_date)])
            if o and dob and o < dob:
                self._emit(TEMPORAL, [r], f"Diagnosis {dx.name} onset_date {dx.onset_date} precedes date of birth {r.date_of_birth}.",
                           f"diagnoses[{cid}].onset_date", "onset_before_dob",
                           [self._ev(r, f"diagnoses[{dx.name}].onset_date", dx.onset_date),
                            self._ev(r, "date_of_birth", r.date_of_birth)])

    # ---------------------------------------------------------- duplicates
    def _content_set(self, r):
        s = set()
        for kind, text, _ in _mention_items(r):
            cid = self.cid(kind, text)
            s.add((kind, cid or text.strip().casefold()))
        return s

    def dup_similarity(self, a, b) -> float:
        sa, sb = self._content_set(a), self._content_set(b)
        if not sa and not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    def check_duplicates(self, recs):
        for a, b in combinations(recs, 2):
            da, db = _d(a.encounter_date), _d(b.encounter_date)
            if not da or not db or abs((da - db).days) > DUP_DATE_WINDOW_DAYS:
                continue
            sim = self.dup_similarity(a, b)
            if sim >= DUP_SIM_HIGH:
                self._emit(DUPLICATE, [a, b],
                           f"{a.record_id} and {b.record_id} look like the same encounter recorded twice "
                           f"(same patient, dates {a.encounter_date}/{b.encounter_date}, clinical-content similarity {sim:.2f}).",
                           "record", "fuzzy_duplicate",
                           [self._ev(a, "patient_name", a.patient_name), self._ev(b, "patient_name", b.patient_name),
                            self._ev(a, "encounter_date", a.encounter_date), self._ev(b, "encounter_date", b.encounter_date)],
                           conf=min(1.0, 0.5 + sim / 2))
            elif sim >= DUP_SIM_LOW:
                self.res.ambiguous_duplicates.append((a.record_id, b.record_id, sim))

    # ------------------------------------------------------ contradictions
    def check_dose_conflict(self, recs):
        for a, b in combinations(recs, 2):
            da, db = _d(a.encounter_date), _d(b.encounter_date)
            if not da or not db or abs((da - db).days) > DOSE_WINDOW_DAYS:
                continue
            if abs((da - db).days) <= DUP_DATE_WINDOW_DAYS and self.dup_similarity(a, b) >= DUP_SIM_HIGH:
                pass  # duplicate records may still disagree on dose -- that IS a contradiction, keep checking
            ma = {self.cid(V.MED, m.name): m for m in a.medications if m.dose is not None}
            for mb in b.medications:
                cid = self.cid(V.MED, mb.name)
                if cid and cid in ma and mb.dose is not None:
                    x = ma[cid]
                    if x.unit == mb.unit and x.dose != mb.dose:
                        self._emit(CONTRADICTION, [a, b],
                                   f"Conflicting {V.canonical_name(V.MED, cid)} dose within {DOSE_WINDOW_DAYS} days: "
                                   f"{x.dose:g} {x.unit} in {a.record_id} vs {mb.dose:g} {mb.unit} in {b.record_id}.",
                                   f"medications[{cid}].dose", "dose_conflict",
                                   [self._ev(a, f"medications[{x.name}].dose", x.dose),
                                    self._ev(b, f"medications[{mb.name}].dose", mb.dose)])

    def _allergy_cids(self, r):
        out = []
        for al in r.allergies or []:
            c = self.cid(V.ALLERGY, al.substance)
            out.append((c, al))
        return out

    def check_allergy_nkda(self, recs):
        """NKDA is only contradicted by an allergy documented no later than the NKDA record
        (an allergy acquired after an earlier NKDA record is clinically normal)."""
        real = [(r, c) for r in recs for c, al in self._allergy_cids(r) if c is not None and c != V.NKDA]
        for r in recs:
            if any(c == V.NKDA for c, _ in self._allergy_cids(r)):
                dr = _d(r.encounter_date)
                partners = []
                for p, _ in real:
                    dp = _d(p.encounter_date)
                    if p is not r and p not in partners and (dr is not None and dp is not None and dp <= dr):
                        partners.append(p)
                if partners:
                    self._emit(CONTRADICTION, [r] + partners,
                               f"{r.record_id} states no known allergies but earlier/same-day records of the same patient document an allergy.",
                               "allergies", "allergy_vs_nkda",
                               [self._ev(r, "allergies", [a.substance for a in r.allergies])] +
                               [self._ev(p, "allergies", [a.substance for a in p.allergies]) for p in partners[:3]])

    def check_dx_exclusive(self, recs):
        seen = defaultdict(list)
        for r in recs:
            for d in r.diagnoses:
                c = self.cid(V.DX, d.name)
                if c:
                    seen[c].append(r)
        for x, y in V.DX_EXCLUSIVE:
            if x in seen and y in seen:
                self._emit(CONTRADICTION, seen[x] + seen[y],
                           f"Mutually exclusive diagnoses documented for one patient: {V.canonical_name(V.DX, x)} "
                           f"and {V.canonical_name(V.DX, y)}.", "diagnoses", "dx_exclusive",
                           [self._ev(r, "diagnoses", [d.name for d in r.diagnoses]) for r in (seen[x] + seen[y])[:4]])

    def check_sex_dx(self, r):
        if r.sex not in ("F", "M"):
            return
        for d in r.diagnoses:
            c = self.cid(V.DX, d.name)
            req = V.DX_META.get(c, {}).get("sex") if c else None
            if req and req != r.sex:
                self._emit(CONTRADICTION, [r],
                           f"Diagnosis '{V.canonical_name(V.DX, c)}' is incompatible with recorded sex {r.sex}.",
                           f"diagnoses[{c}]", "sex_dx_conflict",
                           [self._ev(r, "sex", r.sex), self._ev(r, "diagnoses", d.name)])

    def check_allergy_med(self, recs):
        allergies = defaultdict(list)          # allergy cid -> records
        for r in recs:
            for c, _ in self._allergy_cids(r):
                if c and c != V.NKDA:
                    allergies[c].append(r)
        for r in recs:
            for m in r.medications:
                mc = self.cid(V.MED, m.name)
                for ac, holders in allergies.items():
                    if mc and mc in V.ALLERGY_META.get(ac, {}).get("conflicts", []):
                        self._emit(CONTRADICTION, [r] + [h for h in holders if h is not r],
                                   f"Medication {V.canonical_name(V.MED, mc)} in {r.record_id} conflicts with documented "
                                   f"{V.canonical_name(V.ALLERGY, ac)} allergy.", f"medications[{mc}]", "allergy_med_conflict",
                                   [self._ev(r, f"medications[{m.name}]", m.name)] +
                                   [self._ev(h, "allergies", [a.substance for a in h.allergies]) for h in holders[:2]])

    def check_demographics(self, recs):
        for f in ("sex", "date_of_birth"):
            vals = defaultdict(list)
            for r in recs:
                v = getattr(r, f)
                if v:
                    vals[v].append(r)
            if len(vals) >= 2:
                allr = [r for rs in vals.values() for r in rs]
                self._emit(CONTRADICTION, allr, f"Records linked to the same patient disagree on {f}: {sorted(vals)}.",
                           f, "demographic_mismatch", [self._ev(r, f, getattr(r, f)) for r in allr[:5]])

    # -------------------------------------------- free-text (explicit only)
    _ALLERGY_DENIAL = re.compile(r"\b(denies (any )?(drug )?allerg|no known (drug )?allerg|no history of (drug )?allerg|no allergies)", re.I)
    CUE = re.compile(r"\b(no|not|denies|denied|never|stopped|discontinu\w*|quit|off|without|"
                     r"ruled out|excluded|resolved|longer|removed|taken out)\b", re.I)

    # sentence must both carry a negation/cessation cue and talk about a medication/diagnosis/allergy fact
    FACT = re.compile(r"allerg|medicat|\bdrugs?\b|antibiotic|regimen|diagnos|history of|\bhx\b|taking|taken|took|"
                      r"pharmacy|prescri|tolerat|reaction|condition|workup|\bdoses?\b", re.I)

    def check_note_assertions(self, r):
        note = r.notes or ""
        if not note:
            return
        matched = False
        real_allergy = [al for c, al in self._allergy_cids(r) if c is not None and c != V.NKDA]
        m = self._ALLERGY_DENIAL.search(note)
        if m and real_allergy:
            matched = True
            self._emit(CONTRADICTION, [r], f"Note says \"{m.group(0)}\" but the record lists allergy "
                       f"{real_allergy[0].substance}.", "notes", "note_allergy_denial",
                       [self._ev(r, "notes", note), self._ev(r, "allergies", [a.substance for a in real_allergy])])
        for med in r.medications:
            if med.end_date:
                continue
            n = re.escape(med.name)
            pat = re.compile(rf"\b(stopped(?: taking)?|discontinued|no longer (?:taking|on)|off(?: of)?)\s+(?:the\s+)?{n}\b|"
                             rf"\b{n}\b\W+(?:\w+\W+){{0,3}}?(?:was|were|has been)\s+(?:stopped|discontinued)", re.I)
            m = pat.search(note)
            if m:
                matched = True
                self._emit(CONTRADICTION, [r], f"Note indicates {med.name} was stopped (\"{m.group(0)}\") but the record "
                           f"lists it as an active medication.", "notes", "note_med_stopped",
                           [self._ev(r, "notes", note), self._ev(r, f"medications[{med.name}]", med.name)])
        for dx in r.diagnoses:
            n = re.escape(dx.name)
            pat = re.compile(rf"(no (?:known )?(?:history|hx) of|never been diagnosed with|denies (?:a )?(?:history of|ever having been diagnosed with))\s+(?:any\s+)?{n}", re.I)
            m = pat.search(note)
            if m:
                matched = True
                self._emit(CONTRADICTION, [r], f"Note negates diagnosis {dx.name} (\"{m.group(0)}\") that is listed in the record.",
                           "notes", "note_dx_negated",
                           [self._ev(r, "notes", note), self._ev(r, f"diagnoses[{dx.name}]", dx.name)])
        # cue-bearing note that no rule explained -> candidate for semantic (LLM) review
        if not matched and (r.medications or r.diagnoses or real_allergy):
            names = [x.name.casefold() for x in r.medications] + [x.name.casefold() for x in r.diagnoses]
            for sent in re.split(r"(?<=[.;])\s+", note):
                if self.CUE.search(sent) and (self.FACT.search(sent) or any(n in sent.casefold() for n in names)):
                    self.res.note_candidates.append(r.record_id)
                    break

    # --------------------------------------------------------- terminology
    def check_terminology(self, recs):
        by_concept = defaultdict(lambda: defaultdict(set))    # (kind,cid) -> form -> record ids
        for r in recs:
            for kind, text, root in _mention_items(r):
                cid, how = self.norm.resolve(kind, text, self.llm_term_map)
                if cid:
                    by_concept[(kind, cid)][text.strip().casefold()].add(r.record_id)
                elif text.strip():
                    self.res.unresolved_terms.setdefault((kind, text.strip().casefold()), set()).add(r.record_id)
        root = {V.DX: "diagnoses", V.MED: "medications", V.ALLERGY: "allergies"}
        for (kind, cid), forms in by_concept.items():
            if len(forms) >= 2:
                rids = sorted(set().union(*forms.values()))
                self._emit(TERMINOLOGY, rids,
                           f"'{V.canonical_name(kind, cid)}' is written {len(forms)} different ways across records: "
                           f"{sorted(forms)}. Suggest mapping all to '{V.canonical_name(kind, cid)}'.",
                           f"{root[kind]}[{cid}]", "terminology_dictionary",
                           [dict(record_id=rid, field=root[kind], value=f) for f, rs in sorted(forms.items()) for rid in sorted(rs)[:2]])


def run_rules(records: list, **kw) -> RuleResult:
    return RuleEngine(records, **kw).run()
