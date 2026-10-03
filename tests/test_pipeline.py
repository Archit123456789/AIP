from pathlib import Path

from aip.evaluate import matches, score
from aip.generator import GenConfig, generate
from aip.hybrid import run_hybrid
from aip.llm import ScriptedClient, UnavailableClient
from aip.llm_only import run_llm_only
from aip.oracle import OracleClient
from aip.rules import run_rules
from aip.schema import IssueLabel, PredictedIssue

DATA = generate(GenConfig(n_patients=80, seed=11))
RECORDS, LABELS = DATA[0], DATA[1]


def f1(issues):
    return score(issues, LABELS, len(RECORDS))


def test_rules_are_precise_on_synthetic_data():
    s = f1(run_rules(RECORDS).issues)
    assert s["overall"]["precision"] >= 0.98 and s["overall"]["recall"] > 0.8


def test_hybrid_degrades_to_rules_without_llm():
    issues, meta = run_hybrid(RECORDS, llm=UnavailableClient())
    assert len(meta["skipped_stages"]) == 4
    assert {i.issue_id for i in issues}                       # ids assigned
    assert len(issues) == len(run_rules(RECORDS).issues)


def test_hybrid_with_oracle_llm_improves_recall_and_keeps_precision():
    base = f1(run_rules(RECORDS).issues)["overall"]
    issues, meta = run_hybrid(RECORDS, llm=OracleClient(LABELS, RECORDS))
    s = f1(issues)["overall"]
    assert s["recall"] > base["recall"] and s["precision"] >= 0.98
    assert any(i.detector.startswith("llm:") for i in issues) or any("llm_terms" in i.detector for i in issues)
    assert all(i.explanation for i in issues)


def test_ungrounded_free_text_findings_are_dropped():
    rid = RECORDS[0].record_id
    llm = ScriptedClient(lambda s, p: {"findings": [{"record_id": r, "quote": "this text is not in the note", "structured_item": "x", "reason": "y"}
                                                   for r in [x.record_id for x in RECORDS]]}
                         if p.startswith("For each record below") else {})
    issues, meta = run_hybrid(RECORDS, llm=llm, explain=False)
    assert meta["stage_counts"]["llm_free_text_findings"] == 0
    assert meta["stage_counts"]["llm_ungrounded_findings_dropped"] > 0


def test_llm_only_validates_ids_and_types():
    def fn(s, p):
        return {"issues": [{"issue_type": "bogus", "record_ids": ["R000001"], "field_path": "x", "description": "d"},
                           {"issue_type": "missing", "record_ids": ["NOPE"], "field_path": "sex", "description": "d"},
                           {"issue_type": "missing", "record_ids": [RECORDS[0].record_id], "field_path": "sex", "description": "ok"}]}
    issues, meta = run_llm_only(RECORDS[:10], llm=ScriptedClient(fn), chunk_size=10)
    assert len(issues) == 1 and meta["malformed_issues_dropped"] == 2


def test_matching_semantics():
    t = IssueLabel("I1", "duplicate", ["a", "b"], "P1", "d", "record")
    ok = PredictedIssue("p", "duplicate", ["a", "b"], None, "d", "record")
    half = PredictedIssue("p", "duplicate", ["a", "z"], None, "d", "record")
    wrong_type = PredictedIssue("p", "contradiction", ["a", "b"], None, "d", "record")
    assert matches(ok, t) and not matches(half, t) and not matches(wrong_type, t)
    t2 = IssueLabel("I2", "missing", ["a"], "P1", "d", "medications[x].dose")
    assert matches(PredictedIssue("p", "missing", ["a"], None, "d", "medications"), t2)
    assert not matches(PredictedIssue("p", "missing", ["a"], None, "d", "sex"), t2)


def test_affirming_quote_without_negation_cue_is_rejected():
    r = next(x for x in RECORDS if x.notes)
    sentence = r.notes.split(". ")[0]      # an affirmative/neutral sentence of the note, e.g. "Follow-up visit"
    llm = ScriptedClient(lambda s, p: {"findings": [{"record_id": r.record_id, "quote": "Hx of", "structured_item": "dx", "reason": "x"}]}
                         if p.startswith("For each record below") else {})
    issues, meta = run_hybrid([r], llm=llm, explain=False)
    assert meta["stage_counts"]["llm_free_text_findings"] == 0


def test_unparseable_llm_answer_is_retried_once():
    from aip.llm import LLMClient

    class Flaky(LLMClient):
        model = "flaky"
        def __init__(self):
            super().__init__(); self.n = 0
        def _cache_path(self, system, prompt):
            return None
        def _call(self, system, prompt):
            self.n += 1
            return ('{"issues": [' if self.n == 1 else '{"issues": []}'), 10, 5   # first answer is truncated JSON

    c = Flaky()
    assert c.generate_json("p") == {"issues": []}
    assert c.n == 2 and c.stats.parse_failures == 1
