"""Synthetic fragmented-clinical-record generator with exact ground truth.

Pipeline
  1. For each synthetic patient build a hidden "true" history (diagnoses, meds, allergies).
  2. Fragment it into 2-4 independent per-source records (different local ref per source,
     independently-rolled surface form per concept mention, per-record partial coverage).
     Terminology inconsistencies emerge from this step -- they are NOT injected.
  3. Run targeted injection passes (duplicates, contradictions, missing, temporal). Each
     injection logs an exact IssueLabel.
  4. Compute terminology labels from the FINAL records via the vocabulary answer key.

Everything is driven by one seeded random.Random and a fixed reference date, so a
(seed, config) pair reproduces byte-identical output.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from . import vocab as V
from .names import NICKNAMES
from .schema import (
    Allergy, ClinicalRecord, Diagnosis, IssueLabel, Medication, write_jsonl,
    CONTRADICTION, DUPLICATE, MISSING, TEMPORAL, TERMINOLOGY,
)

REF_DATE = date(2025, 6, 30)   # fixed "today" -> reproducible

FIRST_F = ["Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah",
           "Karen", "Nancy", "Lisa", "Margaret", "Sandra", "Ashley", "Kimberly", "Emily", "Donna",
           "Michelle", "Carol", "Amanda", "Melissa", "Deborah", "Stephanie", "Rebecca", "Laura"]
FIRST_M = ["James", "Robert", "John", "Michael", "David", "William", "Richard", "Joseph", "Thomas",
           "Charles", "Christopher", "Daniel", "Matthew", "Anthony", "Mark", "Donald", "Steven", "Paul",
           "Andrew", "Kenneth", "Joshua", "Kevin", "Brian", "George", "Edward", "Ronald"]
LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
        "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
        "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
        "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
        "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts",
        "Patel", "Khan", "Kim", "Chen", "Singh", "Okafor", "Novak", "Kowalski", "Rossi", "Silva"]

SOURCES = {
    "GeneralHospital_EHR": dict(prefix="GH", style="last_comma_first", types=["inpatient", "emergency", "outpatient"]),
    "Northside_Clinic": dict(prefix="NC", style="first_last", types=["outpatient", "telehealth"]),
    "UrgentCare_Plus": dict(prefix="UC", style="first_last", types=["emergency", "outpatient"]),
    "Lakeview_Specialty": dict(prefix="LV", style="last_comma_first_upper", types=["outpatient", "inpatient"]),
    "Community_Health_Center": dict(prefix="CH", style="first_mi_last", types=["outpatient", "telehealth"]),
}


@dataclass
class GenConfig:
    n_patients: int = 300
    seed: int = 42
    expose_patient_id: bool = False
    # injection rates (fractions of patients / records; each is realised as round(rate * N))
    dup_rate: float = 0.06               # of records
    dose_conflict_rate: float = 0.04     # of patients
    allergy_nkda_rate: float = 0.04      # of patients
    demographic_rate: float = 0.04       # of patients
    dx_exclusive_rate: float = 0.03      # of patients
    sex_dx_rate: float = 0.02            # of records
    allergy_med_rate: float = 0.03       # of records
    note_contradiction_rate: float = 0.06  # of records
    temporal_rate: float = 0.07          # of records
    missing_rate: float = 0.07           # of records
    homonym_rate: float = 0.04           # decoy: different person, same name
    twin_rate: float = 0.015             # decoy: same DOB + surname, different first name


def _iso(d):
    return d.isoformat() if d else None


def _d(s):
    return date.fromisoformat(s) if s else None


class Generator:
    def __init__(self, cfg: GenConfig):
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.patients: list = []
        self.records: dict = {}          # tmp record id -> ClinicalRecord
        self.rec_patient: dict = {}      # tmp record id -> patient id
        self.rec_episode: dict = {}      # tmp record id -> (patient id, episode idx)
        self.labels: list = []           # (issue_type, [tmp rids], pid, description, path)
        self.touched: set = set()        # (rid, root field) already corrupted
        self.dup_involved: set = set()
        self._n = 0

    # ------------------------------------------------------------ helpers
    def new_rid(self):
        self._n += 1
        return f"T{self._n:06d}"

    def by_patient(self, pid):
        return [r for rid, r in self.records.items() if self.rec_patient[rid] == pid]

    def free(self, rec, root):
        return (rec.record_id, root) not in self.touched

    def touch(self, rec, root):
        self.touched.add((rec.record_id, root))

    def label(self, itype, recs, pid, desc, path):
        rids = []
        for r in recs:
            rid = r if isinstance(r, str) else r.record_id
            if rid not in rids:
                rids.append(rid)
        self.labels.append((itype, rids, pid, desc, path))

    @staticmethod
    def concept_of_med(m):
        return V.resolve(V.MED, m.name)

    @staticmethod
    def concept_of_dx(dx):
        return V.resolve(V.DX, dx.name)

    @staticmethod
    def concept_of_allergy(a):
        return V.resolve(V.ALLERGY, a.substance)

    # ------------------------------------------------------------ patients
    def make_patient(self, idx):
        rng = self.rng
        sex = rng.choice(["F", "M"])
        first = rng.choice(FIRST_F if sex == "F" else FIRST_M)
        last = rng.choice(LAST)
        age = rng.randint(30, 88)
        dob = REF_DATE - timedelta(days=age * 365 + rng.randint(0, 364))
        # decoys: distinct people who look alike
        if self.patients:
            r = rng.random()
            other = rng.choice(self.patients)
            if r < self.cfg.homonym_rate:      # same name, DOB years apart
                first, last, sex = other.first, other.last, other.sex
                while abs((dob - other.dob).days) < 3 * 365:
                    dob = REF_DATE - timedelta(days=rng.randint(30, 88) * 365 + rng.randint(0, 364))
            elif r < self.cfg.homonym_rate + self.cfg.twin_rate:   # twin: same DOB + surname
                last, dob, sex = other.last, other.dob, other.sex
                pool = FIRST_F if sex == "F" else FIRST_M
                first = rng.choice([n for n in pool if n != other.first])
        tp = SimpleNamespace(
            pid=f"P{idx:05d}", first=first, last=last, sex=sex, dob=dob,
            mi=rng.choice("ABCDEFGHJKLMNPRST") if rng.random() < 0.5 else None,
            dx=[], meds=[], allergies=[], refs={},
        )
        self.build_history(tp)
        return tp

    def build_history(self, tp):
        rng = self.rng
        pool = [c for c in V.concepts_of(V.DX)
                if V.DX_META[c.cid].get("sex") in (None, tp.sex)
                and not (c.cid == "pregnancy" and (tp.sex != "F" or REF_DATE.year - tp.dob.year > 45))]
        weights = [0.25 if V.DX_META[c.cid].get("acute") else 1.0 for c in pool]
        weights = [0.15 if c.cid == "pregnancy" else w for c, w in zip(pool, weights)]
        chosen = []
        while len(chosen) < rng.randint(1, 4):
            c = rng.choices(pool, weights)[0]
            if c.cid in [x.cid for x in chosen]:
                continue
            if any(c.cid in pair and o.cid in pair for pair in V.DX_EXCLUSIVE for o in chosen):
                continue
            chosen.append(c)
        for c in chosen:
            acute = V.DX_META[c.cid].get("acute")
            lo = max(tp.dob + timedelta(days=16 * 365), REF_DATE - timedelta(days=15 * 365))
            hi = REF_DATE - timedelta(days=int(2.6 * 365))
            onset = lo + timedelta(days=rng.randint(0, max(1, (hi - lo).days)))
            resolved = onset + timedelta(days=rng.randint(10, 30)) if acute else None
            tp.dx.append(dict(cid=c.cid, onset=onset, resolved=resolved))
        # allergies (needed first so meds can avoid conflicts)
        if rng.random() < 0.38:
            cands = [c for c in V.concepts_of(V.ALLERGY) if c.cid != V.NKDA]
            for c in rng.sample(cands, rng.randint(1, 2)):
                meta = V.ALLERGY_META[c.cid]
                tp.allergies.append(dict(cid=c.cid, reaction=rng.choice(meta["reactions"]),
                                         severity=rng.choice(["mild", "moderate", "severe"])))
        banned = {m for a in tp.allergies for m in V.ALLERGY_META[a["cid"]]["conflicts"]}
        for dx in tp.dx:
            cands = [m for m, meta in V.MED_META.items()
                     if dx["cid"] in meta["ind"] and m not in banned and m not in [x["cid"] for x in tp.meds]]
            if cands and rng.random() < 0.75:
                mid = rng.choice(cands)
                meta = V.MED_META[mid]
                acute = meta.get("acute")
                start = dx["onset"] + timedelta(days=rng.randint(0, 3 if acute else 90))
                end = start + timedelta(days=rng.randint(7, 14)) if acute else None
                tp.meds.append(dict(cid=mid, dose=rng.choice(meta["doses"]), dose2=None, titr=None,
                                    unit=meta["unit"], freq=meta["freq"], start=start, end=end))

    # ------------------------------------------------------ fragmentation
    def render_name(self, tp, source, typo=False, style=None):
        rng = self.rng
        style = style or SOURCES[source]["style"]
        first = tp.first
        if first in NICKNAMES and rng.random() < 0.15:
            first = NICKNAMES[first]
        last = tp.last
        if typo:
            i = rng.randrange(1, len(last) - 1) if len(last) > 3 else 0
            last = last[:i] + last[i + 1] + last[i] + last[i + 2:] if rng.random() < 0.5 else last[:i] + last[i + 1:]
        if style == "first_last":
            return f"{first} {last}"
        if style == "last_comma_first":
            return f"{last}, {first}"
        if style == "last_comma_first_upper":
            return f"{last}, {first}".upper()
        return f"{first} {tp.mi} {last}" if tp.mi else f"{first} {last}"

    def make_note(self, rec):
        rng = self.rng
        parts = [rng.choice(["Follow-up visit.", "Routine review.", "Presented for scheduled assessment.",
                             "Patient seen for evaluation."])]
        if rec.diagnoses:
            parts.append(f"{rng.choice(['Hx of', 'Known', 'Assessment:'])} "
                         f"{', '.join(d.name for d in rec.diagnoses[:3])}.")
        for m in rec.medications[:2]:
            dose = f" {m.dose:g}{m.unit}" if m.dose is not None else ""
            parts.append(f"Currently taking {m.name}{dose}{' ' + m.frequency if m.frequency else ''}.")
        if rec.allergies:
            a = rec.allergies[0]
            if V.resolve(V.ALLERGY, a.substance) == V.NKDA:
                parts.append(f"Allergies: {a.substance}.")
            else:
                parts.append(f"Allergy: {a.substance}" + (f" ({a.reaction})." if a.reaction else "."))
        for m in rec.medications:
            if m.end_date and rng.random() < 0.7:
                parts.append(f"Completed course of {m.name}; discontinued as planned.")
        parts += rng.sample(["Denies chest pain.", "No shortness of breath.", "Denies fever or chills.",
                             "No acute distress noted.", "Patient reports no recent falls.",
                             "Denies any new allergies.", "No new medications started since last visit.",
                             "Reports occasionally missing evening doses."], rng.randint(1, 2))
        parts.append(rng.choice(["Continue current management.", "Follow up in 3 months.", "Labs ordered.",
                                 "Return precautions reviewed."]))
        return " ".join(parts)

    def rebuild_note(self, rec):
        rec.notes = self.make_note(rec)

    def episode_dates(self, n):
        rng = self.rng
        for _ in range(500):
            days = sorted(rng.sample(range(40, 720), n))
            if all(b - a >= 50 for a, b in zip(days, days[1:])):
                return [REF_DATE - timedelta(days=x) for x in reversed(days)]
        return [REF_DATE - timedelta(days=60 + 100 * i) for i in reversed(range(n))]

    def fragment(self, tp):
        rng = self.rng
        n_src = rng.randint(2, 4)
        sources = rng.sample(list(SOURCES), n_src)
        specs = list(sources)
        if rng.random() < 0.25:
            specs.append(rng.choice(sources))    # follow-up visit in a source already used
        n_ep = min(len(specs), rng.randint(1, 3))
        if len(specs) > n_src:
            n_ep = max(n_ep, 2)
        for _ in range(50):
            rng.shuffle(specs)
            eps = [i % n_ep for i in range(len(specs))]
            bad = any(specs[i] == specs[j] and eps[i] == eps[j]
                      for i in range(len(specs)) for j in range(i + 1, len(specs)))
            if not bad:
                break
        ep_dates = self.episode_dates(n_ep)
        # place records inside episodes: >= 3 days apart pairwise
        rec_dates = [None] * len(specs)
        for e in range(n_ep):
            off = 0
            for i in [i for i, x in enumerate(eps) if x == e]:
                rec_dates[i] = ep_dates[e] + timedelta(days=off)
                off += rng.randint(3, 5)
        # dose titration decoy: legitimate dose change placed in the gap between episodes
        if n_ep >= 2:
            for m in tp.meds:
                meta = V.MED_META[m["cid"]]
                if len(meta["doses"]) > 1 and not meta.get("acute") and rng.random() < 0.15:
                    g = rng.randrange(n_ep - 1)
                    last_g = max(d for d, e in zip(rec_dates, eps) if e == g)
                    first_n = min(d for d, e in zip(rec_dates, eps) if e == g + 1)
                    m["titr"] = last_g + (first_n - last_g) / 2
                    m["dose2"] = rng.choice([x for x in meta["doses"] if x != m["dose"]])
        tp.allergy_from = None
        if tp.allergies and n_ep >= 2 and rng.random() < 0.25:
            g = rng.randrange(n_ep - 1)     # allergy first documented after episode g: earlier records say NKDA
            last_g = max(d for d, e in zip(rec_dates, eps) if e == g)
            first_n = min(d for d, e in zip(rec_dates, eps) if e == g + 1)
            tp.allergy_from = last_g + (first_n - last_g) / 2
        for src in sources:
            tp.refs[src] = f"{SOURCES[src]['prefix']}-{rng.randint(100000, 999999)}"
        for spec, dt_, e in zip(specs, rec_dates, eps):
            rec = self.build_record(tp, spec, dt_)
            self.records[rec.record_id] = rec
            self.rec_patient[rec.record_id] = tp.pid
            self.rec_episode[rec.record_id] = (tp.pid, e)

    def build_record(self, tp, source, when):
        rng = self.rng
        rec = ClinicalRecord(
            record_id=self.new_rid(), local_patient_ref=tp.refs[source], source_system=source,
            encounter_type=rng.choice(SOURCES[source]["types"]), encounter_date=_iso(when),
            sex=tp.sex, date_of_birth=_iso(tp.dob),
            patient_name=self.render_name(tp, source, typo=rng.random() < 0.03),
            patient_id=tp.pid,
        )
        dxs = [d for d in tp.dx if rng.random() < 0.8] or [rng.choice(tp.dx)]
        for d in dxs:
            resolved = d["resolved"] if d["resolved"] and d["resolved"] <= when else None
            rec.diagnoses.append(Diagnosis(V.render(rng, V.DX, d["cid"]), _iso(d["onset"]), _iso(resolved),
                                           "resolved" if resolved else "active"))
        for m in tp.meds:
            if rng.random() > 0.8:
                continue
            dose = m["dose2"] if m["titr"] and when >= m["titr"] else m["dose"]
            end = m["end"] if m["end"] and m["end"] <= when else None
            rec.medications.append(Medication(V.render(rng, V.MED, m["cid"]), dose, m["unit"], m["freq"],
                                              _iso(m["start"]), _iso(end)))
        if tp.allergies and not (tp.allergy_from and when < tp.allergy_from):
            for a in [a for a in tp.allergies if rng.random() < 0.85] or [rng.choice(tp.allergies)]:
                rec.allergies.append(Allergy(V.render(rng, V.ALLERGY, a["cid"]), a["reaction"], a["severity"]))
        else:
            rec.allergies.append(Allergy(V.render(rng, V.ALLERGY, V.NKDA)))
        self.rebuild_note(rec)
        return rec

    # ------------------------------------------------------- injections
    def attempt(self, n, fn):
        done = tries = 0
        while done < n and tries < n * 80 + 200:
            tries += 1
            if fn():
                done += 1
        return done

    def _rand_rec(self):
        return self.rng.choice(list(self.records.values()))

    def inject_duplicates(self, n):
        rng = self.rng

        def one():
            r = self._rand_rec()
            if r.record_id in self.dup_involved or not r.encounter_date:
                return False
            pid = self.rec_patient[r.record_id]
            tp = self.tp_by_id[pid]
            same_src = rng.random() < 0.7
            src = r.source_system if same_src else rng.choice([s for s in SOURCES if s != r.source_system])
            c = copy.deepcopy(r)
            c.record_id = self.new_rid()
            c.source_system = src
            if not same_src:
                c.local_patient_ref = f"{SOURCES[src]['prefix']}-{rng.randint(100000, 999999)}"
                c.encounter_type = rng.choice(SOURCES[src]["types"])
            elif rng.random() < 0.4:
                c.local_patient_ref = f"{SOURCES[src]['prefix']}-{rng.randint(100000, 999999)}"  # re-registered
            if rng.random() < 0.6:
                c.patient_name = self.render_name(tp, src, typo=rng.random() < 0.5)
            if rng.random() < 0.3:
                c.encounter_date = _iso(_d(r.encounter_date) + timedelta(days=rng.choice([-1, 1])))
            if not same_src and rng.random() < 0.6:   # re-roll surface forms independently
                for d in c.diagnoses:
                    cid = V.resolve(V.DX, d.name)
                    d.name = V.render(rng, V.DX, cid) if cid else d.name
                for m in c.medications:
                    cid = V.resolve(V.MED, m.name)
                    m.name = V.render(rng, V.MED, cid) if cid else m.name
            if rng.random() < 0.25 and len(c.medications) > 1:
                c.medications.pop(rng.randrange(len(c.medications)))
            self.rebuild_note(c)
            self.records[c.record_id] = c
            self.rec_patient[c.record_id] = pid
            self.rec_episode[c.record_id] = self.rec_episode[r.record_id]
            self.dup_involved |= {r.record_id, c.record_id}
            self.touch(r, "encounter_date")
            self.touch(c, "encounter_date")
            self.label(DUPLICATE, [r, c], pid,
                       f"Record {c.record_id} duplicates {r.record_id} "
                       f"({'same' if same_src else 'different'} source, near-identical demographics/encounter).",
                       "record")
            return True

        return self.attempt(n, one)

    def _patient_recs(self):
        pid = self.rng.choice(list(self.tp_by_id))
        return pid, self.by_patient(pid)

    def inject_dose_conflict(self, n):
        rng = self.rng

        def one():
            pid, recs = self._patient_recs()
            titrated = {m["cid"] for m in self.tp_by_id[pid].meds if m["titr"]}
            pairs = [(a, b) for a in recs for b in recs if a is not b and a.encounter_date and b.encounter_date
                     and self.rec_episode[a.record_id] == self.rec_episode[b.record_id]
                     and a.record_id not in self.dup_involved and b.record_id not in self.dup_involved]
            rng.shuffle(pairs)
            for a, b in pairs:
                if not self.free(b, "medications"):
                    continue
                am = {V.resolve(V.MED, m.name): m for m in a.medications if m.dose is not None}
                for mb in b.medications:
                    cid = V.resolve(V.MED, mb.name)
                    if cid in am and cid not in titrated and mb.dose is not None:
                        old = mb.dose
                        opts = [x for x in V.MED_META[cid]["doses"] if x != old] + [old * 10, old / 10]
                        mb.dose = rng.choice(opts)
                        self.touch(b, "medications")
                        self.touch(a, "encounter_date")
                        self.touch(b, "encounter_date")
                        partners = [r for r in recs if r is not b and any(
                            V.resolve(V.MED, m.name) == cid and m.dose is not None and m.dose != mb.dose
                            and abs((_d(r.encounter_date) - _d(b.encounter_date)).days) <= 21
                            for m in r.medications if r.encounter_date)]
                        self.rebuild_note(b)
                        self.label(CONTRADICTION, [b] + partners, pid,
                                   f"Conflicting {V.canonical_name(V.MED, cid)} dose within the same care episode: "
                                   f"{mb.dose:g} {mb.unit} in {b.record_id} vs {am[cid].dose:g} {am[cid].unit} "
                                   f"in {a.record_id}.", f"medications[{cid}].dose")
                        return True
            return False

        return self.attempt(n, one)

    def inject_allergy_nkda(self, n):
        rng = self.rng

        def one():
            pid, recs = self._patient_recs()
            recs = [r for r in recs if r.allergies is not None]
            real = lambda r: [a for a in r.allergies if V.resolve(V.ALLERGY, a.substance) not in (None, V.NKDA)]
            b = rng.choice(recs)
            db = _d(b.encounter_date)
            # contradiction only when the allergy "disappears": partner records are not later than b
            partners = [r for r in recs if r is not b and real(r) and _d(r.encounter_date) and db
                        and _d(r.encounter_date) <= db]
            if not real(b) or not partners or not self.free(b, "allergies") or not self.free(b, "encounter_date"):
                return False
            self.touch(b, "encounter_date")
            for p in partners:
                self.touch(p, "encounter_date")
            b.allergies = [Allergy(V.render(rng, V.ALLERGY, V.NKDA))]
            self.touch(b, "allergies")
            self.rebuild_note(b)
            self.label(CONTRADICTION, [b] + partners, pid,
                       f"{b.record_id} states no known allergies but earlier/same-day records of the same patient "
                       f"document an allergy.", "allergies")
            return True

        return self.attempt(n, one)

    def inject_demographic(self, n):
        rng = self.rng

        def one():
            pid, recs = self._patient_recs()
            b = rng.choice(recs)
            if len(recs) < 2:
                return False
            if rng.random() < 0.5:
                if not b.sex or not self.free(b, "sex"):
                    return False
                b.sex = "M" if b.sex == "F" else "F"
                path = "sex"
                others = [r for r in recs if r is not b and r.sex and r.sex != b.sex]
            else:
                if not b.date_of_birth or not self.free(b, "date_of_birth"):
                    return False
                y, m, d = b.date_of_birth.split("-")
                if rng.random() < 0.5 and int(d) <= 12 and d != m:
                    b.date_of_birth = f"{y}-{d}-{m}"                       # day/month transposition
                else:
                    y2 = list(y); i = rng.randrange(2, 4); y2[i] = str((int(y2[i]) + rng.randint(1, 8)) % 10)
                    b.date_of_birth = f"{''.join(y2)}-{m}-{d}"             # digit typo in year
                path = "date_of_birth"
                others = [r for r in recs if r is not b and r.date_of_birth and r.date_of_birth != b.date_of_birth]
            if not others:
                return False
            self.touch(b, path)
            self.label(CONTRADICTION, [b] + others, pid,
                       f"Demographic mismatch on {path} between {b.record_id} and other records of the same patient.",
                       path)
            return True

        return self.attempt(n, one)

    def inject_dx_exclusive(self, n):
        rng = self.rng

        def one():
            pid, recs = self._patient_recs()
            b = rng.choice(recs)
            if not self.free(b, "diagnoses"):
                return False
            for dx in b.diagnoses:
                cid = V.resolve(V.DX, dx.name)
                pair = next((p for p in V.DX_EXCLUSIVE if cid in p), None)
                if not pair:
                    continue
                partners = [r for r in recs if r is not b and any(V.resolve(V.DX, d.name) == cid for d in r.diagnoses)]
                if not partners:
                    continue
                other = pair[0] if pair[1] == cid else pair[1]
                dx.name = V.render(rng, V.DX, other)
                self.touch(b, "diagnoses")
                self.rebuild_note(b)
                self.label(CONTRADICTION, [b] + partners, pid,
                           f"Mutually exclusive diagnoses: {V.canonical_name(V.DX, other)} in {b.record_id} vs "
                           f"{V.canonical_name(V.DX, cid)} in other records.", f"diagnoses[{other}]")
                return True
            return False

        return self.attempt(n, one)

    def inject_sex_dx(self, n):
        rng = self.rng

        def one():
            b = self._rand_rec()
            if b.sex not in ("F", "M") or not self.free(b, "diagnoses") or not self.free(b, "sex"):
                return False
            cid = "bph" if b.sex == "F" else "pregnancy"
            b.diagnoses.append(Diagnosis(V.render(rng, V.DX, cid), b.encounter_date and _iso(_d(b.encounter_date) - timedelta(days=200)),
                                         None, "active"))
            self.touch(b, "diagnoses")
            self.rebuild_note(b)
            self.label(CONTRADICTION, [b], self.rec_patient[b.record_id],
                       f"Diagnosis '{V.canonical_name(V.DX, cid)}' is incompatible with recorded sex {b.sex}.",
                       f"diagnoses[{cid}]")
            return True

        return self.attempt(n, one)

    def inject_allergy_med(self, n):
        rng = self.rng

        def one():
            pid, recs = self._patient_recs()
            b = rng.choice(recs)
            if not b.encounter_date or not self.free(b, "medications"):
                return False
            have = {V.resolve(V.MED, m.name) for m in b.medications}
            for holder in rng.sample(recs, len(recs)):
                for a in holder.allergies or []:
                    acid = V.resolve(V.ALLERGY, a.substance)
                    meds = [m for m in V.ALLERGY_META.get(acid, {}).get("conflicts", []) if m not in have]
                    if not meds:
                        continue
                    mid = rng.choice(meds)
                    meta = V.MED_META[mid]
                    b.medications.append(Medication(V.render(rng, V.MED, mid), rng.choice(meta["doses"]), meta["unit"],
                                                    meta["freq"], _iso(_d(b.encounter_date) - timedelta(days=30)), None))
                    self.touch(b, "medications")
                    holders = [r for r in recs if any(V.resolve(V.ALLERGY, x.substance) == acid for x in r.allergies or [])]
                    self.rebuild_note(b)
                    self.label(CONTRADICTION, [b] + [h for h in holders if h is not b], pid,
                               f"Medication {V.canonical_name(V.MED, mid)} in {b.record_id} conflicts with documented "
                               f"{V.canonical_name(V.ALLERGY, acid)} allergy.", f"medications[{mid}]")
                    return True
            return False

        return self.attempt(n, one)

    NOTE_ALLERGY_EXPLICIT = ["Patient denies any drug allergies.", "No known allergies per patient report today.",
                             "Pt states no history of allergies."]
    NOTE_ALLERGY_IMPLICIT = ["Patient reports never having had an adverse reaction to any medication.",
                             "Tolerates all medications well; no reactions ever experienced.",
                             "Per patient, has taken every antibiotic in the past without any problem."]
    NOTE_MED_EXPLICIT = ["Patient states they stopped taking {x} several months ago.", "{x} was discontinued last year.",
                         "No longer taking {x}."]
    NOTE_MED_IMPLICIT = ["Patient reports not having picked up {x} from the pharmacy in over a year.",
                         "Patient says {x} was taken out of the regimen by their PCP last year.",
                         "Has not taken {x} for the past eight months per patient."]
    NOTE_DX_EXPLICIT = ["No history of {x}.", "Patient denies ever having been diagnosed with {x}."]
    NOTE_DX_IMPLICIT = ["Chart review found no evidence that the patient has ever had {x}.",
                        "{X} was excluded on prior workup and does not apply to this patient.",
                        "Patient has never carried a diagnosis of {x}."]

    def inject_note_contradictions(self, n):
        rng = self.rng

        def one():
            b = self._rand_rec()
            if not b.notes or not self.free(b, "notes"):
                return False
            explicit = rng.random() < 0.5
            kinds = []
            if b.allergies and any(V.resolve(V.ALLERGY, a.substance) not in (None, V.NKDA) for a in b.allergies):
                kinds.append("allergy")
            if any(m.end_date is None for m in b.medications):
                kinds.append("med")
            if b.diagnoses:
                kinds.append("dx")
            if not kinds:
                return False
            kind = rng.choice(kinds)
            if kind == "allergy":
                s = rng.choice(self.NOTE_ALLERGY_EXPLICIT if explicit else self.NOTE_ALLERGY_IMPLICIT)
                what = "allergy"
            elif kind == "med":
                m = rng.choice([m for m in b.medications if m.end_date is None])
                s = rng.choice(self.NOTE_MED_EXPLICIT if explicit else self.NOTE_MED_IMPLICIT).format(x=m.name)
                what = f"active medication {m.name}"
            else:
                d = rng.choice(b.diagnoses)
                s = rng.choice(self.NOTE_DX_EXPLICIT if explicit else self.NOTE_DX_IMPLICIT).format(
                    x=d.name, X=d.name[:1].upper() + d.name[1:])
                what = f"diagnosis {d.name}"
            parts = b.notes.split(". ")
            parts.insert(rng.randint(1, len(parts) - 1), s.rstrip("."))
            b.notes = ". ".join(parts)
            self.touch(b, "notes")
            self.label(CONTRADICTION, [b], self.rec_patient[b.record_id],
                       f"Free-text note contradicts structured {what}: \"{s}\"", "notes")
            return True

        return self.attempt(n, one)

    def inject_temporal(self, n):
        rng = self.rng

        def one():
            b = self._rand_rec()
            if not b.encounter_date or not b.date_of_birth:
                return False
            enc, dob = _d(b.encounter_date), _d(b.date_of_birth)
            pid = self.rec_patient[b.record_id]
            kind = rng.choice(["med_end", "dx_resolved", "dx_future", "enc_future", "enc_pre_dob", "med_pre_dob"])
            if kind in ("med_end", "med_pre_dob"):
                ms = [m for m in b.medications if m.start_date]
                if not ms or not self.free(b, "medications"):
                    return False
                m = rng.choice(ms)
                cid = V.resolve(V.MED, m.name)
                if kind == "med_end":
                    m.end_date = _iso(_d(m.start_date) - timedelta(days=rng.randint(5, 200)))
                    desc = f"Medication {m.name} end_date {m.end_date} is before start_date {m.start_date}."
                    path = f"medications[{cid}].end_date"
                else:
                    m.start_date = _iso(dob - timedelta(days=rng.randint(100, 3000)))
                    desc = f"Medication {m.name} start_date {m.start_date} precedes date of birth {b.date_of_birth}."
                    path = f"medications[{cid}].start_date"
                self.touch(b, "medications")
            elif kind in ("dx_resolved", "dx_future"):
                ds = [d for d in b.diagnoses if d.onset_date]
                if not ds or not self.free(b, "diagnoses"):
                    return False
                d = rng.choice(ds)
                cid = V.resolve(V.DX, d.name)
                if kind == "dx_resolved":
                    d.resolved_date = _iso(_d(d.onset_date) - timedelta(days=rng.randint(5, 300)))
                    d.status = "resolved"
                    desc = f"Diagnosis {d.name} resolved_date {d.resolved_date} precedes onset_date {d.onset_date}."
                    path = f"diagnoses[{cid}].resolved_date"
                else:
                    d.onset_date = _iso(enc + timedelta(days=rng.randint(30, 400)))
                    desc = f"Diagnosis {d.name} onset_date {d.onset_date} is after the encounter date {b.encounter_date}."
                    path = f"diagnoses[{cid}].onset_date"
                self.touch(b, "diagnoses")
            else:
                if not self.free(b, "encounter_date"):
                    return False
                if kind == "enc_future":
                    b.encounter_date = _iso(REF_DATE + timedelta(days=rng.randint(30, 400)))
                    desc = f"Encounter date {b.encounter_date} is in the future (as-of {REF_DATE})."
                else:
                    b.encounter_date = _iso(dob - timedelta(days=rng.randint(30, 2000)))
                    desc = f"Encounter date {b.encounter_date} precedes date of birth {b.date_of_birth}."
                path = "encounter_date"
                self.touch(b, "encounter_date")
            self.label(TEMPORAL, [b], pid, desc, path)
            return True

        return self.attempt(n, one)

    def inject_missing(self, n):
        rng = self.rng

        def one():
            b = self._rand_rec()
            pid = self.rec_patient[b.record_id]
            f = rng.choice(["date_of_birth", "sex", "encounter_date", "encounter_type", "allergies",
                            "diagnoses", "med_dose"])
            if f == "med_dose":
                ms = [m for m in b.medications if m.dose is not None]
                if not ms or not self.free(b, "medications"):
                    return False
                m = rng.choice(ms)
                cid = V.resolve(V.MED, m.name)
                m.dose = None
                self.touch(b, "medications")
                self.label(MISSING, [b], pid, f"Medication {m.name} has no dose.", f"medications[{cid}].dose")
                return True
            if not self.free(b, f):
                return False
            cur = getattr(b, f)
            if cur in (None, []):
                return False
            setattr(b, f, [] if f == "diagnoses" else None)
            self.touch(b, f)
            desc = {"allergies": "Allergy status undocumented (neither allergies nor NKDA recorded).",
                    "diagnoses": "Record has no diagnoses."}.get(f, f"Missing {f}.")
            self.label(MISSING, [b], pid, desc, f)
            return True

        return self.attempt(n, one)

    # -------------------------------------------------- terminology labels
    def terminology_labels(self):
        per = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))   # pid -> (kind,cid) -> form -> rids
        for rid, r in self.records.items():
            pid = self.rec_patient[rid]
            for d in r.diagnoses:
                c = V.resolve(V.DX, d.name)
                if c:
                    per[pid][(V.DX, c)][d.name.casefold()].add(rid)
            for m in r.medications:
                c = V.resolve(V.MED, m.name)
                if c:
                    per[pid][(V.MED, c)][m.name.casefold()].add(rid)
            for a in r.allergies or []:
                c = V.resolve(V.ALLERGY, a.substance)
                if c:
                    per[pid][(V.ALLERGY, c)][a.substance.casefold()].add(rid)
        root = {V.DX: "diagnoses", V.MED: "medications", V.ALLERGY: "allergies"}
        for pid in sorted(per):
            for (kind, cid), forms in sorted(per[pid].items()):
                if len(forms) >= 2:
                    rids = sorted(set().union(*forms.values()))
                    self.label(TERMINOLOGY, rids, pid,
                               f"Concept '{V.canonical_name(kind, cid)}' written {len(forms)} different ways across "
                               f"records: {sorted(forms)}.", f"{root[kind]}[{cid}]")

    # ------------------------------------------------------------ driver
    def run(self):
        cfg, rng = self.cfg, self.rng
        for i in range(1, cfg.n_patients + 1):
            tp = self.make_patient(i)
            self.patients.append(tp)
            self.fragment(tp)
        self.tp_by_id = {p.pid: p for p in self.patients}
        nrec, npat = len(self.records), len(self.patients)
        R = lambda rate, base: round(rate * base)
        counts = {}
        counts["duplicate"] = self.inject_duplicates(R(cfg.dup_rate, nrec))
        counts["dose_conflict"] = self.inject_dose_conflict(R(cfg.dose_conflict_rate, npat))
        counts["allergy_nkda"] = self.inject_allergy_nkda(R(cfg.allergy_nkda_rate, npat))
        counts["demographic"] = self.inject_demographic(R(cfg.demographic_rate, npat))
        counts["dx_exclusive"] = self.inject_dx_exclusive(R(cfg.dx_exclusive_rate, npat))
        counts["sex_dx"] = self.inject_sex_dx(R(cfg.sex_dx_rate, nrec))
        counts["allergy_med"] = self.inject_allergy_med(R(cfg.allergy_med_rate, nrec))
        counts["note_contradiction"] = self.inject_note_contradictions(R(cfg.note_contradiction_rate, nrec))
        counts["temporal"] = self.inject_temporal(R(cfg.temporal_rate, nrec))
        counts["missing"] = self.inject_missing(R(cfg.missing_rate, nrec))
        self.terminology_labels()
        return self.finalize(counts)

    def finalize(self, counts):
        rng = self.rng
        tmp_ids = sorted(self.records)
        final_ids = [f"R{i:06d}" for i in range(1, len(tmp_ids) + 1)]
        rng.shuffle(final_ids)                       # ids must not leak patient grouping
        remap = dict(zip(tmp_ids, final_ids))
        records = []
        for tid in tmp_ids:
            r = self.records[tid]
            r.record_id = remap[tid]
            if not self.cfg.expose_patient_id:
                r.patient_id = None
            records.append(r)
        rng.shuffle(records)
        labels = []
        for k, (itype, rids, pid, desc, path) in enumerate(self.labels, 1):
            for t, f in remap.items():
                desc = desc.replace(t, f) if t in desc else desc
            labels.append(IssueLabel(f"I{k:05d}", itype, [remap[x] for x in rids], pid, desc, path))
        links = [dict(record_id=remap[t], patient_id=self.rec_patient[t]) for t in tmp_ids]
        links.sort(key=lambda d: d["record_id"])
        manifest = dict(config=asdict(self.cfg), reference_date=_iso(REF_DATE), n_patients=len(self.patients),
                        n_records=len(records), injections=counts,
                        labels_by_type=dict(Counter(l.issue_type for l in labels)))
        return records, labels, links, manifest


def generate(cfg: GenConfig):
    return Generator(cfg).run()


def write_dataset(cfg: GenConfig, out_dir: str | Path):
    records, labels, links, manifest = generate(cfg)
    out = Path(out_dir)
    write_jsonl(out / "records.jsonl", (r.to_dict() for r in records))
    write_jsonl(out / "ground_truth.jsonl", (l.to_dict() for l in labels))
    write_jsonl(out / "patient_links.jsonl", links)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate a synthetic fragmented clinical dataset with ground truth.")
    ap.add_argument("--n-patients", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data")
    ap.add_argument("--expose-patient-id", action="store_true",
                    help="write the true patient_id into records.jsonl (oracle-linkage experiments)")
    a = ap.parse_args(argv)
    m = write_dataset(GenConfig(n_patients=a.n_patients, seed=a.seed, expose_patient_id=a.expose_patient_id), a.out)
    print(json.dumps({k: m[k] for k in ("n_patients", "n_records", "injections", "labels_by_type")}, indent=2))


if __name__ == "__main__":
    main()
