"""Structured patient representation + ground-truth / prediction issue schema.

Everything is a plain dataclass with to_dict/from_dict so that records and
issues round-trip through JSONL without any third-party dependency.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

# ---- the five target issue categories -------------------------------------
DUPLICATE = "duplicate"
CONTRADICTION = "contradiction"
MISSING = "missing"
TEMPORAL = "temporal"
TERMINOLOGY = "terminology"
ISSUE_TYPES = (DUPLICATE, CONTRADICTION, MISSING, TEMPORAL, TERMINOLOGY)

SEX_VALUES = ("F", "M")


@dataclass
class Diagnosis:
    name: str                           # surface form as written in the source
    onset_date: Optional[str] = None    # ISO yyyy-mm-dd
    resolved_date: Optional[str] = None
    status: Optional[str] = None        # "active" | "resolved"


@dataclass
class Medication:
    name: str                           # generic OR brand, as written
    dose: Optional[float] = None
    unit: Optional[str] = None
    frequency: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


@dataclass
class Allergy:
    substance: str                      # also used for "NKDA"-style statements
    reaction: Optional[str] = None
    severity: Optional[str] = None


@dataclass
class ClinicalRecord:
    record_id: str
    local_patient_ref: str              # per-source identifier, differs across sources
    source_system: str
    encounter_type: Optional[str]
    encounter_date: Optional[str]
    sex: Optional[str]
    date_of_birth: Optional[str]
    diagnoses: list = field(default_factory=list)          # list[Diagnosis]
    medications: list = field(default_factory=list)        # list[Medication]
    allergies: Optional[list] = field(default_factory=list)  # list[Allergy]; None = status undocumented
    notes: Optional[str] = None
    # Extension over the pitch schema: the fuzzy name+DOB+date duplicate rule needs a name.
    patient_name: Optional[str] = None
    # Enterprise/true id. NULL in records.jsonl by default (records arrive fragmented, unlinked);
    # only populated if the generator is run with --expose-patient-id (oracle-linkage experiments).
    patient_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ClinicalRecord":
        d = dict(d)
        d["diagnoses"] = [Diagnosis(**x) for x in d.get("diagnoses") or []]
        d["medications"] = [Medication(**x) for x in d.get("medications") or []]
        al = d.get("allergies")
        d["allergies"] = None if al is None else [Allergy(**x) for x in al]
        return cls(**d)


@dataclass
class IssueLabel:
    """Ground-truth issue (also the base of a system's prediction)."""
    issue_id: str
    issue_type: str                     # one of ISSUE_TYPES
    record_ids: list
    patient_id: Optional[str]
    description: str
    field_path: str                     # e.g. "medications[metformin].dose", "sex", "record"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "IssueLabel":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class PredictedIssue(IssueLabel):
    """A flagged issue plus everything a human reviewer needs (evidence & provenance)."""
    detector: str = ""                  # e.g. "rule:dose_conflict", "llm:free_text", "llm_only"
    confidence: float = 1.0
    evidence: list = field(default_factory=list)   # [{"record_id":..., "field":..., "value":...}]
    explanation: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "PredictedIssue":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


def field_root(path: Optional[str]) -> str:
    """'medications[metformin].dose' -> 'medications'; used to compare field paths loosely."""
    if not path:
        return ""
    p = path.strip().lower()
    for i, ch in enumerate(p):
        if ch in "[.":
            p = p[:i]
            break
    aliases = {
        "dob": "date_of_birth", "birth_date": "date_of_birth", "birthdate": "date_of_birth",
        "medication": "medications", "meds": "medications",
        "diagnosis": "diagnoses", "dx": "diagnoses",
        "allergy": "allergies",
        "note": "notes", "free_text": "notes", "text": "notes",
        "gender": "sex",
        "encounter": "encounter_date", "date": "encounter_date",
        "name": "patient_name", "demographics": "sex",
        "": "",
    }
    return aliases.get(p, p)


# ---- JSONL helpers ----------------------------------------------------------
def write_jsonl(path: str | Path, rows: Iterable[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: str | Path) -> Iterator[dict]:
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_records(path: str | Path) -> list[ClinicalRecord]:
    return [ClinicalRecord.from_dict(d) for d in read_jsonl(path)]


def load_labels(path: str | Path) -> list[IssueLabel]:
    return [IssueLabel.from_dict(d) for d in read_jsonl(path)]


def load_predictions(path: str | Path) -> list[PredictedIssue]:
    return [PredictedIssue.from_dict(d) for d in read_jsonl(path)]
