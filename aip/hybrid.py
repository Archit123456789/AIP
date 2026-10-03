"""Hybrid pipeline (Step 4): rules decide the clear-cut cases, Gemini handles the ambiguous residual.

  1. rules pass 1                      -> issues + residuals (unresolved terms, ambiguous duplicate pairs, cue-bearing notes)
  2. LLM: terminology equivalence      -> maps only strings the dictionary/fuzzy matcher could NOT resolve
  3. rules pass 2 (with LLM term map)  -> terminology / dose / allergy / duplicate checks now see the mapped concepts
  4. LLM: ambiguous duplicate pairs    -> judge pairs whose content similarity fell in the grey zone
  5. LLM: free-text contradictions     -> notes with negation/cessation cues that no explicit rule explained
  6. LLM: explanations                 -> plain-language explanation per flagged (non-terminology) issue

Every issue carries provenance in `detector`: "rule:<name>", "rule+llm_terms:<name>" (rule fired only because the LLM
resolved a term), "llm:duplicate_judge", "llm:free_text".  If the LLM is unavailable each LLM stage is skipped and logged
in meta["skipped_stages"], so the output degrades to the rule baseline instead of failing.
"""
from __future__ import annotations

import re

from . import vocab as V
from .llm import LLMUnavailable, default_client
from .prompts import CATEGORY_DEFS, SYSTEM, render_record
from .rules import RuleEngine, _mention_items as _mentions
from .schema import CONTRADICTION, DUPLICATE, TERMINOLOGY, PredictedIssue

TERM_BATCH = 80
PAIR_BATCH = 8
NOTE_BATCH = 8
EXPLAIN_BATCH = 20
_KIND_LABEL = {V.DX: "diagnosis", V.MED: "medication", V.ALLERGY: "allergen / allergy statement"}


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", (s or "").casefold()).strip()


def _key(i: PredictedIssue):
    return (i.issue_type, tuple(sorted(i.record_ids)), i.field_path)


# ------------------------------------------------------------------ stage 2
def llm_map_terms(llm, unresolved: dict) -> dict:
    """unresolved: {(kind, text): record_ids} -> {(kind, text): cid | None}"""
    out = {}
    by_kind = {}
    for kind, text in unresolved:
        by_kind.setdefault(kind, []).append(text)
    for kind, terms in by_kind.items():
        menu = "\n".join(f"{cid}: {name}" for cid, name in V.concept_menu(kind))
        valid = {cid for cid, _ in V.concept_menu(kind)}
        for i in range(0, len(terms), TERM_BATCH):
            batch = terms[i:i + TERM_BATCH]
            prompt = (f"Map each {_KIND_LABEL[kind]} term to a concept id from the vocabulary below.\n"
                      f"Map only when the term denotes EXACTLY that concept (synonym, abbreviation, brand/generic name, "
                      f"colloquial name or misspelling). A more specific subtype, a different condition, or anything you are "
                      f"not confident about -> null.\n\nVocabulary (id: canonical name):\n{menu}\n\nTerms:\n"
                      + "\n".join(f"- {t}" for t in batch) +
                      '\n\nReturn JSON: {"mappings": [{"term": <exact term>, "concept_id": <id or null>}]}')
            obj = llm.generate_json(prompt, system=SYSTEM, tag="terminology")
            for m in (obj or {}).get("mappings", []) if isinstance(obj, dict) else []:
                t, cid = m.get("term"), m.get("concept_id")
                if t is not None and (cid in valid or cid is None):
                    out[(kind, t.strip().casefold())] = cid
    return out


# ------------------------------------------------------------------ stage 4
def llm_judge_duplicates(llm, pairs: list, by_id: dict) -> dict:
    """pairs: [(a, b, sim)] -> {(a, b): (is_dup, reason)}"""
    out = {}
    for i in range(0, len(pairs), PAIR_BATCH):
        batch = pairs[i:i + PAIR_BATCH]
        body = "\n\n".join(f"PAIR {n}:\n{render_record(by_id[a])}\n{render_record(by_id[b])}"
                           for n, (a, b, _) in enumerate(batch))
        prompt = ("For each PAIR decide whether the two records are the SAME encounter recorded twice (a duplicate) or two "
                  "different encounters of the same person. Surface-form differences (abbreviations, brand vs generic names, "
                  "name spelling) do not make records different; different dates more than a day apart usually do.\n\n"
                  + body + '\n\nReturn JSON: {"judgements": [{"pair": <n>, "duplicate": true|false, "reason": <short>}]}')
        obj = llm.generate_json(prompt, system=SYSTEM, tag="duplicate_judge")
        for j in (obj or {}).get("judgements", []) if isinstance(obj, dict) else []:
            try:
                a, b, _ = batch[int(j["pair"])]
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            out[(a, b)] = (bool(j.get("duplicate")), str(j.get("reason", "")))
    return out


# ------------------------------------------------------------------ stage 5
def llm_free_text(llm, record_ids: list, by_id: dict):
    """returns ([(rid, quote, item, reason)], n_ungrounded_dropped)"""
    found, dropped = [], 0
    cue = RuleEngine.CUE
    for i in range(0, len(record_ids), NOTE_BATCH):
        batch = [by_id[r] for r in record_ids[i:i + NOTE_BATCH]]
        prompt = ("For each record below, decide whether its free-text `note` contradicts that SAME record's structured fields "
                  "(allergies, medications incl. end dates, diagnoses). Report ONLY genuine contradictions, e.g. the note says the "
                  "patient has no drug allergies while an allergy is listed; says a listed active medication was stopped or is not "
                  "taken; or says the patient never had a diagnosis that is listed. Do NOT report: statements consistent with the "
                  "structured data, statements about NEW allergies/medications, a course that is completed and has an end date, "
                  "adherence remarks, or unrelated symptoms. The quoted sentence MUST itself deny, negate or report stopping something that is "
                  "listed (it contains words like no / not / never / denies / stopped / discontinued / without); a sentence that merely "
                  "repeats or affirms a listed item (e.g. 'Assessment: asthma') is NOT a contradiction, even if other fields look odd.\n\n"
                  + "\n\n".join(render_record(r) for r in batch) +
                  '\n\nReturn JSON: {"findings": [{"record_id": <id>, "quote": <exact substring of the note>, '
                  '"structured_item": <which field/item it contradicts>, "reason": <short>}]}')
        obj = llm.generate_json(prompt, system=SYSTEM, tag="free_text")
        for f in (obj or {}).get("findings", []) if isinstance(obj, dict) else []:
            r = by_id.get(f.get("record_id"))
            quote = str(f.get("quote", ""))
            if r is None or not quote or _norm(quote) not in _norm(r.notes or ""):
                dropped += 1          # ungrounded: quote is not in the note -> reject (guards against hallucinated evidence)
                continue
            if not cue.search(quote):
                dropped += 1          # a contradiction must be a denial/negation/cessation statement; affirmations are not
                continue
            found.append((r.record_id, quote, str(f.get("structured_item", "")), str(f.get("reason", ""))))
    return found, dropped


# ------------------------------------------------------------------ stage 6
def llm_explain(llm, issues: list) -> None:
    for i in range(0, len(issues), EXPLAIN_BATCH):
        batch = issues[i:i + EXPLAIN_BATCH]
        body = "\n".join(f"{n}. [{x.issue_type}] records={x.record_ids} field={x.field_path} finding={x.description} "
                         f"evidence={[e.get('value') for e in x.evidence][:3]}" for n, x in enumerate(batch))
        prompt = ("Below are flagged data-quality issues. For each, write 1-2 plain-language sentences for a data steward: what "
                  "is inconsistent and what to check in the source records. State only facts present in the finding/evidence; "
                  "give no treatment or clinical advice.\n\n" + body +
                  '\n\nReturn JSON: {"explanations": [{"i": <n>, "text": <string>}]}')
        obj = llm.generate_json(prompt, system=SYSTEM, tag="explain")
        for e in (obj or {}).get("explanations", []) if isinstance(obj, dict) else []:
            try:
                batch[int(e["i"])].explanation = str(e["text"])
            except (KeyError, ValueError, IndexError, TypeError):
                continue


# ------------------------------------------------------------------ driver
def run_hybrid(records: list, use_patient_id: bool = False, explain: bool = True, llm=None):
    llm = llm or default_client()
    by_id = {r.record_id: r for r in records}
    meta = dict(model=llm.model, skipped_stages=[], stage_counts={})

    def stage(name, fn, default=None):
        try:
            return fn()
        except LLMUnavailable as e:
            meta["skipped_stages"].append(f"{name}: {e}")
        except Exception as e:                       # keep the pipeline alive; the failure is logged in the output meta
            meta["skipped_stages"].append(f"{name}: {type(e).__name__}: {e}")
        return default

    res1 = RuleEngine(records, use_patient_id=use_patient_id).run()
    meta["stage_counts"]["rules_pass1_issues"] = len(res1.issues)
    meta["stage_counts"]["unresolved_terms"] = len(res1.unresolved_terms)
    meta["stage_counts"]["ambiguous_duplicate_pairs"] = len(res1.ambiguous_duplicates)
    meta["stage_counts"]["note_candidates"] = len(res1.note_candidates)

    term_map = stage("terminology", lambda: llm_map_terms(llm, res1.unresolved_terms), {}) or {}
    term_map = {k: v for k, v in term_map.items() if v}
    meta["stage_counts"]["llm_term_mappings"] = len(term_map)

    if term_map:
        eng = RuleEngine(records, use_patient_id=use_patient_id, llm_term_map=term_map)
        res = eng.run()
        before = {_key(i) for i in res1.issues}
        mentions = {r.record_id: {t.strip().casefold() for _, t, _ in _mentions(r)} for r in records}
        for i in res.issues:
            if _key(i) not in before:
                i.detector = i.detector.replace("rule:", "rule+llm_terms:", 1)
                used = {t: c for (_, t), c in term_map.items() if any(t in mentions[r] for r in i.record_ids)}
                i.evidence.append(dict(record_id=i.record_ids[0], field="llm_term_map", value=used))
    else:
        res = res1
    issues = list(res.issues)
    clusters = res.clusters

    # -- ambiguous duplicates
    judged = stage("duplicate_judge", lambda: llm_judge_duplicates(llm, res.ambiguous_duplicates, by_id), {}) or {}
    sims = {(a, b): s for a, b, s in res.ambiguous_duplicates}
    for (a, b), (is_dup, reason) in judged.items():
        if is_dup:
            issues.append(PredictedIssue(
                issue_id="", issue_type=DUPLICATE, record_ids=[a, b], patient_id=clusters.get(a),
                description=f"{a} and {b} judged to be the same encounter recorded twice: {reason}",
                field_path="record", detector="llm:duplicate_judge", confidence=0.7,
                evidence=[dict(record_id=a, field="record", value=f"content similarity {sims[(a, b)]:.2f}"),
                          dict(record_id=b, field="record", value=reason)]))
    meta["stage_counts"]["llm_confirmed_duplicates"] = sum(v[0] for v in judged.values())

    # -- free-text contradictions
    found, dropped = stage("free_text", lambda: llm_free_text(llm, res.note_candidates, by_id), ([], 0)) or ([], 0)
    for rid, quote, item, reason in found:
        issues.append(PredictedIssue(
            issue_id="", issue_type=CONTRADICTION, record_ids=[rid], patient_id=clusters.get(rid),
            description=f"Note says \"{quote}\", which contradicts {item}: {reason}", field_path="notes",
            detector="llm:free_text", confidence=0.7,
            evidence=[dict(record_id=rid, field="notes", value=quote), dict(record_id=rid, field=item, value=reason)]))
    meta["stage_counts"]["llm_free_text_findings"] = len(found)
    meta["stage_counts"]["llm_ungrounded_findings_dropped"] = dropped

    for n, i in enumerate(issues, 1):
        i.issue_id = f"H{n:05d}"
        i.explanation = i.explanation or i.description

    if explain:
        stage("explain", lambda: llm_explain(llm, [i for i in issues if i.issue_type != TERMINOLOGY]))

    meta.update(llm.stats.as_meta())
    meta["clusters"] = clusters
    meta["llm_available"] = llm.stats.calls > 0
    return issues, meta
