"""Controlled terminology vocabulary.

Serves two purposes:
  1. The generator renders surface-form variation from it.
  2. It is the answer key for terminology normalization.

Every concept has `common` forms (abbreviations / standard synonyms a curated
rule dictionary would plausibly contain) and `hard` forms (colloquialisms,
misspellings, brand-strengths, less-standard synonyms). The rule layer only
gets the `common` tier; `hard` forms are the residual that needs semantic
(LLM) judgment. That split is deliberate: it stops the rule baseline from
trivially seeing the whole answer key.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

DX, MED, ALLERGY = "dx", "med", "allergy"


@dataclass(frozen=True)
class Concept:
    cid: str
    kind: str
    canonical: str
    common: tuple = ()
    hard: tuple = ()

    @property
    def all_forms(self) -> tuple:
        return (self.canonical,) + tuple(self.common) + tuple(self.hard)


def _c(cid, kind, canonical, common=(), hard=()):
    return Concept(cid, kind, canonical, tuple(common), tuple(hard))


# ---------------------------------------------------------------- diagnoses
_DX = [
    _c("t2dm", DX, "type 2 diabetes mellitus", ["T2DM", "type 2 diabetes", "DM2", "NIDDM"],
       ["adult-onset diabetes", "sugar diabetes", "diabetis type 2"]),
    _c("t1dm", DX, "type 1 diabetes mellitus", ["T1DM", "type 1 diabetes", "IDDM"],
       ["juvenile diabetes"]),
    _c("htn", DX, "hypertension", ["HTN", "high blood pressure"], ["elevated BP", "hypertention"]),
    _c("mi", DX, "myocardial infarction", ["MI", "heart attack", "AMI"], ["myocardial infarct", "STEMI"]),
    _c("chf", DX, "congestive heart failure", ["CHF", "heart failure", "HF"],
       ["cardiac failure", "congestive cardiac failure"]),
    _c("copd", DX, "chronic obstructive pulmonary disease", ["COPD", "chronic obstructive lung disease"],
       ["COAD", "chronic airflow obstruction"]),
    _c("ckd", DX, "chronic kidney disease", ["CKD", "chronic renal disease"],
       ["chronic renal insufficiency", "CRF"]),
    _c("asthma", DX, "asthma", ["bronchial asthma"], ["reactive airway disease", "asthama"]),
    _c("afib", DX, "atrial fibrillation", ["AFib", "AF", "a-fib"], ["auricular fibrillation"]),
    _c("hld", DX, "hyperlipidemia", ["HLD", "high cholesterol", "dyslipidemia"],
       ["elevated lipids", "hypercholesterolaemia"]),
    _c("gerd", DX, "gastroesophageal reflux disease", ["GERD", "acid reflux"], ["reflux disease", "GORD"]),
    _c("hypothyroid", DX, "hypothyroidism", ["underactive thyroid"], ["low thyroid", "hypothyroid state"]),
    _c("hyperthyroid", DX, "hyperthyroidism", ["overactive thyroid"], ["thyrotoxicosis"]),
    _c("mdd", DX, "major depressive disorder", ["MDD", "depression"],
       ["clinical depression", "depressive disorder"]),
    _c("pneumonia", DX, "pneumonia", ["PNA"], ["chest infection", "pnuemonia"]),
    _c("uti", DX, "urinary tract infection", ["UTI", "bladder infection"], ["urinary infection"]),
    _c("stroke", DX, "cerebrovascular accident", ["CVA", "stroke"], ["brain attack", "cerebral infarction"]),
    _c("dvt", DX, "deep vein thrombosis", ["DVT", "deep venous thrombosis"], ["leg clot"]),
    _c("anemia", DX, "anemia", ["anaemia"], ["low hemoglobin", "low blood count"]),
    _c("oa", DX, "osteoarthritis", ["OA", "degenerative joint disease", "DJD"], ["wear-and-tear arthritis"]),
    _c("migraine", DX, "migraine", ["migraine headache"], ["migrane"]),
    _c("obesity", DX, "obesity", ["obese"], ["adiposity", "class II obesity"]),
    _c("cad", DX, "coronary artery disease", ["CAD", "coronary heart disease", "CHD"],
       ["ischemic heart disease", "IHD"]),
    _c("pe", DX, "pulmonary embolism", ["PE"], ["lung clot"]),
    _c("epilepsy", DX, "epilepsy", ["seizure disorder"], ["convulsive disorder"]),
    _c("gad", DX, "generalized anxiety disorder", ["GAD", "anxiety"], ["anxiety disorder", "chronic anxiety"]),
    _c("pregnancy", DX, "pregnancy", ["IUP", "intrauterine pregnancy"], ["gravid state"]),
    _c("bph", DX, "benign prostatic hyperplasia", ["BPH", "enlarged prostate"], ["prostatic hypertrophy"]),
]

DX_META = {
    "t2dm": dict(icd10="E11.9"), "t1dm": dict(icd10="E10.9"), "htn": dict(icd10="I10"),
    "mi": dict(icd10="I21.9"), "chf": dict(icd10="I50.9"), "copd": dict(icd10="J44.9"),
    "ckd": dict(icd10="N18.9"), "asthma": dict(icd10="J45.909"), "afib": dict(icd10="I48.91"),
    "hld": dict(icd10="E78.5"), "gerd": dict(icd10="K21.9"), "hypothyroid": dict(icd10="E03.9"),
    "hyperthyroid": dict(icd10="E05.90"), "mdd": dict(icd10="F32.9"),
    "pneumonia": dict(icd10="J18.9", acute=True), "uti": dict(icd10="N39.0", acute=True),
    "stroke": dict(icd10="I63.9"), "dvt": dict(icd10="I82.40", acute=True), "anemia": dict(icd10="D64.9"),
    "oa": dict(icd10="M19.90"), "migraine": dict(icd10="G43.909"), "obesity": dict(icd10="E66.9"),
    "cad": dict(icd10="I25.10"), "pe": dict(icd10="I26.99", acute=True), "epilepsy": dict(icd10="G40.909"),
    "gad": dict(icd10="F41.1"), "pregnancy": dict(icd10="Z33.1", sex="F"),
    "bph": dict(icd10="N40.0", sex="M"),
}
# mutually exclusive diagnosis pairs (contradiction if both appear for one patient)
DX_EXCLUSIVE = [("t1dm", "t2dm"), ("hypothyroid", "hyperthyroid")]

# ------------------------------------------------------------- medications
_MED = [
    _c("metformin", MED, "metformin", ["Glucophage"], ["metformin hydrochloride", "Glucophage XR"]),
    _c("insulin_glargine", MED, "insulin glargine", ["Lantus"], ["Basaglar", "glargine insulin"]),
    _c("lisinopril", MED, "lisinopril", ["Prinivil", "Zestril"], ["lisinapril"]),
    _c("amlodipine", MED, "amlodipine", ["Norvasc"], ["amlodipine besylate"]),
    _c("atorvastatin", MED, "atorvastatin", ["Lipitor"], ["atorvastatin calcium", "atorvastin"]),
    _c("simvastatin", MED, "simvastatin", ["Zocor"], ["simvastin"]),
    _c("metoprolol", MED, "metoprolol", ["Lopressor"], ["Toprol-XL", "metoprolol tartrate"]),
    _c("furosemide", MED, "furosemide", ["Lasix"], ["water pill (furosemide)"]),
    _c("warfarin", MED, "warfarin", ["Coumadin"], ["Jantoven", "warfarin sodium"]),
    _c("apixaban", MED, "apixaban", ["Eliquis"], ["apixiban"]),
    _c("aspirin", MED, "aspirin", ["ASA", "Ecotrin"], ["acetylsalicylic acid"]),
    _c("clopidogrel", MED, "clopidogrel", ["Plavix"], ["clopidogrel bisulfate"]),
    _c("albuterol", MED, "albuterol", ["Ventolin", "ProAir"], ["salbutamol"]),
    _c("levothyroxine", MED, "levothyroxine", ["Synthroid", "Levoxyl"], ["L-thyroxine"]),
    _c("omeprazole", MED, "omeprazole", ["Prilosec"], ["omeprazol"]),
    _c("sertraline", MED, "sertraline", ["Zoloft"], ["sertraline HCl"]),
    _c("levetiracetam", MED, "levetiracetam", ["Keppra"], ["levetiracetam ER"]),
    _c("sumatriptan", MED, "sumatriptan", ["Imitrex"], ["sumatriptan succinate"]),
    _c("ibuprofen", MED, "ibuprofen", ["Advil", "Motrin"], ["ibuprofin"]),
    _c("acetaminophen", MED, "acetaminophen", ["Tylenol", "paracetamol"], ["APAP"]),
    _c("amoxicillin", MED, "amoxicillin", ["Amoxil"], ["amoxycillin"]),
    _c("nitrofurantoin", MED, "nitrofurantoin", ["Macrobid"], ["nitrofurantoin monohydrate"]),
    _c("methimazole", MED, "methimazole", ["Tapazole"], ["methimazol"]),
    _c("tamsulosin", MED, "tamsulosin", ["Flomax"], ["tamsulosin HCl"]),
    _c("prednisone", MED, "prednisone", ["Deltasone"], ["prednisone taper"]),
]

MED_META = {
    "metformin": dict(doses=[500, 850, 1000], unit="mg", freq="twice daily", ind=["t2dm"]),
    "insulin_glargine": dict(doses=[10, 20, 30, 40], unit="units", freq="once daily", ind=["t1dm", "t2dm"]),
    "lisinopril": dict(doses=[5, 10, 20, 40], unit="mg", freq="once daily", ind=["htn", "chf", "ckd"]),
    "amlodipine": dict(doses=[2.5, 5, 10], unit="mg", freq="once daily", ind=["htn"]),
    "atorvastatin": dict(doses=[10, 20, 40, 80], unit="mg", freq="once daily", ind=["hld", "cad", "mi", "stroke"]),
    "simvastatin": dict(doses=[20, 40], unit="mg", freq="once daily", ind=["hld"]),
    "metoprolol": dict(doses=[25, 50, 100], unit="mg", freq="twice daily", ind=["htn", "chf", "afib", "mi"]),
    "furosemide": dict(doses=[20, 40, 80], unit="mg", freq="once daily", ind=["chf", "ckd"]),
    "warfarin": dict(doses=[2.5, 5], unit="mg", freq="once daily", ind=["afib", "dvt", "pe"]),
    "apixaban": dict(doses=[2.5, 5], unit="mg", freq="twice daily", ind=["afib", "dvt", "pe"]),
    "aspirin": dict(doses=[81, 325], unit="mg", freq="once daily", ind=["mi", "cad", "stroke"]),
    "clopidogrel": dict(doses=[75], unit="mg", freq="once daily", ind=["mi", "cad", "stroke"]),
    "albuterol": dict(doses=[90], unit="mcg", freq="as needed", ind=["asthma", "copd"]),
    "levothyroxine": dict(doses=[25, 50, 75, 100, 150], unit="mcg", freq="once daily", ind=["hypothyroid"]),
    "omeprazole": dict(doses=[20, 40], unit="mg", freq="once daily", ind=["gerd"]),
    "sertraline": dict(doses=[50, 100, 150], unit="mg", freq="once daily", ind=["mdd", "gad"]),
    "levetiracetam": dict(doses=[500, 1000], unit="mg", freq="twice daily", ind=["epilepsy"]),
    "sumatriptan": dict(doses=[50, 100], unit="mg", freq="as needed", ind=["migraine"]),
    "ibuprofen": dict(doses=[200, 400, 600], unit="mg", freq="three times daily", ind=["oa", "migraine"]),
    "acetaminophen": dict(doses=[500, 650], unit="mg", freq="every 6 hours", ind=["oa", "migraine"]),
    "amoxicillin": dict(doses=[500], unit="mg", freq="three times daily", ind=["pneumonia"], acute=True),
    "nitrofurantoin": dict(doses=[100], unit="mg", freq="twice daily", ind=["uti"], acute=True),
    "methimazole": dict(doses=[5, 10, 20], unit="mg", freq="once daily", ind=["hyperthyroid"]),
    "tamsulosin": dict(doses=[0.4], unit="mg", freq="once daily", ind=["bph"]),
    "prednisone": dict(doses=[5, 10, 20], unit="mg", freq="once daily", ind=["copd", "asthma"]),
}

# ---------------------------------------------------------------- allergies
_ALLERGY = [
    _c("penicillin", ALLERGY, "penicillin", ["PCN", "penicillins"], ["penicillin VK", "pencillin"]),
    _c("sulfa", ALLERGY, "sulfonamide antibiotics", ["sulfa", "sulfa drugs"], ["sulfamethoxazole", "Bactrim"]),
    _c("aspirin_allergy", ALLERGY, "aspirin", ["ASA", "acetylsalicylic acid"], ["salicylates"]),
    _c("codeine", ALLERGY, "codeine", ["codeine phosphate"], ["opioid (codeine)"]),
    _c("latex", ALLERGY, "latex", ["natural rubber latex"], ["latex gloves"]),
    _c("shellfish", ALLERGY, "shellfish", ["crustacean allergy"], ["seafood (shellfish)"]),
    _c("contrast", ALLERGY, "iodinated contrast media", ["contrast dye", "IV contrast"], ["radiocontrast"]),
    _c("peanut", ALLERGY, "peanuts", ["peanut", "groundnuts"], ["arachis"]),
    _c("ace_inhibitors", ALLERGY, "ACE inhibitors", ["ACEI", "ACE inhibitor"], ["angiotensin converting enzyme inhibitors"]),
    _c("nkda", ALLERGY, "no known drug allergies", ["NKDA", "NKA", "no known allergies"],
       ["no drug allergies reported", "nil known allergies"]),
]

ALLERGY_META = {
    "penicillin": dict(reactions=["rash", "hives", "anaphylaxis"], conflicts=["amoxicillin"]),
    "sulfa": dict(reactions=["rash", "hives"], conflicts=[]),
    "aspirin_allergy": dict(reactions=["hives", "bronchospasm"], conflicts=["aspirin", "ibuprofen"]),
    "codeine": dict(reactions=["nausea", "rash"], conflicts=[]),
    "latex": dict(reactions=["contact dermatitis", "hives"], conflicts=[]),
    "shellfish": dict(reactions=["swelling", "anaphylaxis"], conflicts=[]),
    "contrast": dict(reactions=["hives", "rash"], conflicts=[]),
    "peanut": dict(reactions=["swelling", "anaphylaxis"], conflicts=[]),
    "ace_inhibitors": dict(reactions=["angioedema", "cough"], conflicts=["lisinopril"]),
}
NKDA = "nkda"

# ---------------------------------------------------------------- lookups
CONCEPTS: dict = {}          # (kind, cid) -> Concept
_FORM_TO_CID: dict = {}      # kind -> {casefolded form -> cid}   (all tiers = answer key)
_COMMON_TO_CID: dict = {}    # kind -> {casefolded form -> cid}   (common tier = rule dictionary)
for _lst in (_DX, _MED, _ALLERGY):
    for _cn in _lst:
        CONCEPTS[(_cn.kind, _cn.cid)] = _cn
        full = _FORM_TO_CID.setdefault(_cn.kind, {})
        com = _COMMON_TO_CID.setdefault(_cn.kind, {})
        for _f in _cn.all_forms:
            k = _f.casefold()
            assert k not in full, f"duplicate surface form {k!r} in {_cn.kind}"
            full[k] = _cn.cid
        for _f in (_cn.canonical,) + _cn.common:
            com[_f.casefold()] = _cn.cid


def concepts_of(kind: str) -> list:
    return [c for (k, _), c in CONCEPTS.items() if k == kind]


def resolve(kind: str, text: str | None):
    """Answer-key lookup (all tiers). Returns concept id or None."""
    if not text:
        return None
    return _FORM_TO_CID[kind].get(text.strip().casefold())


def resolve_common(kind: str, text: str | None):
    """Rule-dictionary lookup (common tier only)."""
    if not text:
        return None
    return _COMMON_TO_CID[kind].get(text.strip().casefold())


def render(rng: random.Random, kind: str, cid: str, p_canonical=0.35, p_hard=0.15) -> str:
    """Independently roll a surface form for one concept mention."""
    c = CONCEPTS[(kind, cid)]
    r = rng.random()
    if c.hard and r < p_hard:
        return rng.choice(c.hard)
    if c.common and r < p_hard + (1 - p_hard) * (1 - p_canonical):
        return rng.choice(c.common)
    return c.canonical


def canonical_name(kind: str, cid: str) -> str:
    return CONCEPTS[(kind, cid)].canonical


def concept_menu(kind: str) -> list:
    """(cid, canonical) list shown to the LLM as the target vocabulary."""
    return [(c.cid, c.canonical) for c in concepts_of(kind)]
