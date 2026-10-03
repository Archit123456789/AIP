"""Oracle "LLM" -- answers the pipeline's LLM prompts from the ground-truth answer key.

This is NOT a model and its numbers are NOT LLM results. It exists to
  (a) unit-test the hybrid / LLM-only plumbing (prompt parsing, JSON contracts, grounding checks, merging) offline, and
  (b) report a ceiling: "if the LLM stages were perfect, what would the pipeline score?"
Never quote its output as Gemini performance.
"""
from __future__ import annotations

import re

from . import vocab as V
from .llm import ScriptedClient
from .schema import DUPLICATE, IssueLabel


class OracleClient(ScriptedClient):
    model = "oracle-simulation"

    def __init__(self, truth: list, records: list):
        self.truth = truth
        self.notes_truth = {l.record_ids[0]: l for l in truth if l.field_path == "notes"}
        self.dup_pairs = {frozenset(l.record_ids) for l in truth if l.issue_type == DUPLICATE}
        self.records = {r.record_id: r for r in records}
        super().__init__(self._answer)

    def _answer(self, system: str, prompt: str):
        if prompt.startswith("Map each"):
            kind = V.DX if "diagnosis term" in prompt else V.MED if "medication term" in prompt else V.ALLERGY
            if "TERM: " in prompt:      # RAG prompt: answer correctly only if the true concept is among the retrieved candidates
                out = []
                for blk in prompt.split("TERM: ")[1:]:
                    term = blk.split("\n", 1)[0]
                    cands = set(re.findall(r"^\s{4}([\w]+): ", blk, flags=re.M))
                    cid = V.resolve(kind, term)
                    out.append({"term": term, "concept_id": cid if cid in cands else None})
                return {"mappings": out}
            terms = prompt.split("Terms:\n", 1)[1].split("\n\nReturn JSON")[0].splitlines()
            return {"mappings": [{"term": t[2:], "concept_id": V.resolve(kind, t[2:])} for t in terms]}
        if prompt.startswith("For each PAIR"):
            out = []
            for blk in re.split(r"(?=^PAIR \d+:)", prompt, flags=re.M):
                m = re.match(r"PAIR (\d+):", blk)
                ids = re.findall(r"^\[(R\d+)\]", blk, flags=re.M)
                if m and len(ids) >= 2:
                    out.append({"pair": int(m.group(1)), "duplicate": frozenset(ids[:2]) in self.dup_pairs, "reason": "oracle"})
            return {"judgements": out}
        if prompt.startswith("For each record below"):
            out = []
            for rid in re.findall(r"^\[(R\d+)\]", prompt, flags=re.M):
                lab = self.notes_truth.get(rid)
                if lab:
                    q = re.search(r'"(.*)"\s*$', lab.description)
                    out.append({"record_id": rid, "quote": q.group(1) if q else "", "structured_item": "structured data",
                                "reason": "oracle"})
            return {"findings": out}
        if prompt.startswith("Below are flagged"):
            n = len(re.findall(r"^\d+\. \[", prompt, flags=re.M))
            return {"explanations": [{"i": i, "text": "oracle explanation"} for i in range(n)]}
        if "Below are" in prompt and "records, sorted by patient name" in prompt:
            ids = set(re.findall(r"^\[(R\d+)\]", prompt, flags=re.M))
            return {"issues": [{"issue_type": l.issue_type, "record_ids": l.record_ids, "field_path": l.field_path,
                                "description": l.description} for l in self.truth if set(l.record_ids) <= ids]}
        return {}
