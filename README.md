# Healthcare Data Quality & Consistency Intelligence ("quality firewall")

Hybrid rules + LLM pipeline that flags data-quality issues in fragmented clinical records **for human review**
(no autonomous clinical decisions). Course: ML Evaluation, Lab 10. Synthetic data only.

```
records -> patient linkage -> [deterministic rules] + [Gemini on the ambiguous residual] -> issues + evidence/provenance -> human review
```

Five issue categories: `duplicate`, `contradiction`, `missing`, `temporal`, `terminology`.

## Quick start
```bash
pip install -r requirements.txt
python -m aip.generator --n-patients 300 --seed 42 --out data     # Step 1: records.jsonl + ground_truth.jsonl (+ patient_links.jsonl, manifest.json)
python -m aip.run --system rules                                  # Step 2: rule baseline      -> results/rules.jsonl
export GEMINI_API_KEY=...                                         # never commit this; optional AIP_GEMINI_MODEL (default gemini-3.1-pro-preview)
python -m aip.run --system llm_only                               # Step 3: LLM-only baseline
python -m aip.run --system hybrid                                 # Step 4: hybrid (degrades to rules if no key; skipped stages are logged in meta)
python -m aip.evaluate --systems rules,llm_only,hybrid            # Step 5: metrics table -> results/metrics.{md,json}
python -m aip.review --issues results/hybrid.jsonl --html results/review.html   # Step 6 (or --cli)
python -m pytest -q
```
`--llm oracle` runs the LLM stages against the answer key: a plumbing test / ceiling only, never Gemini performance.
LLM responses are cached on disk (`.llm_cache/`, keyed by model+prompt) so re-runs are free and reproducible; cached calls still report the original token counts/latency.

## Layout
| file | role |
|---|---|
| `aip/schema.py` | `ClinicalRecord`, `Diagnosis`/`Medication`/`Allergy`, `IssueLabel`, `PredictedIssue` (adds detector/confidence/evidence/explanation), JSONL I/O |
| `aip/vocab.py` | controlled vocabulary: 28 diagnoses, 25 drugs (brand/generic), 10 allergen concepts (incl. NKDA). Each form is tiered `common` (rule dictionary) or `hard` (colloquial/misspelt; needs semantic judgment) |
| `aip/generator.py` | hidden true history -> per-source fragments -> injections -> exact labels |
| `aip/rules.py` | patient linkage + all deterministic checks; also returns the residual for the LLM |
| `aip/llm.py`, `prompts.py` | Gemini client (JSON mode, cache, retry, token/cost/latency accounting), shared prompt text |
| `aip/llm_only.py`, `aip/hybrid.py` | Steps 3 and 4 |
| `aip/evaluate.py` | Step 5 metrics; matching rules and metric equations are in its docstring |
| `aip/review.py` | Step 6: HTML page (accept/reject/unsure, export JSONL) and CLI |
| `aip/oracle.py` | answer-key stand-in for the LLM (tests / ceiling) |

## Data design (Step 1)
* **Fragmentation**: each patient has a hidden history that is split across 2-4 source systems (+ optional follow-up visit). Every source has its own
  `local_patient_ref`, name format, and *independently rolled surface form per mention*, so terminology inconsistencies arise naturally rather than being injected.
  Partial coverage per source (items dropped with p~0.2) is legitimate incompleteness, not an issue.
* **Linkage is part of the task**: `records.jsonl` carries `patient_id = null` (generate with `--expose-patient-id` for oracle linkage). Systems must re-link records by name/DOB/sex.
  `patient_links.jsonl` is the linkage answer key.
* **Injections** (each logs an exact label): duplicate records (same/different source, name typo, date +-1 day, re-rolled forms); contradictions (dose conflict in one care episode, allergy vs NKDA where the allergy "disappears", mutually exclusive diagnoses, sex-incompatible diagnosis, drug-vs-allergy conflict, sex/DOB mismatch, free-text notes contradicting structured fields - half explicit wording, half paraphrased); missing critical fields; temporal impossibilities.
* **Decoys that must NOT be flagged**: legitimate dose titration between episodes; allergy acquired after an earlier NKDA record; homonyms (same name, different DOB); twins (same DOB+surname); same-episode records from two systems (>=3 days apart); notes with benign negations ("denies chest pain", "denies any *new* allergies", "completed course; discontinued as planned").
* **Terminology label** = one per (patient, concept) written >=2 different ways across that patient's records (computed from the final records via the vocabulary key).
* Deviations from the pitch schema: added `patient_name` (the fuzzy name+DOB+date duplicate rule needs it); `patient_id` is nulled in the input file; NKDA is an `Allergy` whose substance resolves to the `nkda` concept; `allergies=None`/`[]` means "status undocumented".
* Not done: Febrl/Synthea/UMLS supplements (the generator's vocabulary is hand-rolled), n2c2/MIMIC (DUA).

## What "hybrid" does (Step 4)
Rules first; the LLM only sees the residual: (1) surface strings the dictionary + typo-tolerant matcher could not map -> concept ids (then rules re-run, so terminology, dose, allergy and duplicate checks all benefit);
(2) duplicate pairs whose content similarity is in the grey zone; (3) notes with a negation/cessation cue about a medication/diagnosis/allergy that no explicit rule explained (~60% of notes pass this gate; recall of the gate on labelled note contradictions is 100%);
(4) plain-language explanations for non-terminology issues. LLM free-text findings must quote the note verbatim - ungrounded quotes are dropped. Provenance is in `detector` (`rule:*`, `rule+llm_terms:*`, `llm:*`).


## Extension: RAG, a guarded review agent, and red-teaming (Lab 6 pattern)
```bash
python -m aip.rag_eval                          # retrieval metrics for the terminology RAG (recall@k, MRR)
python -m aip.run --system hybrid --rag         # hybrid with retrieval-augmented term mapping (live Gemini)
python -m aip.redteam                           # 21-case red-team (17 attacks + 4 controls), worst-case simulated model
python -m aip.redteam --model gemini            # same suite against live Gemini (costs money; needs a working key)
```
| file | role |
|---|---|
| `aip/kb.py` | knowledge base (10 fictional SOP documents + one entry per vocabulary concept) and a dependency-free BM25 + char-n-gram retriever |
| `aip/agent.py` | the review agent: tool loop with three budgets, Pydantic tool contracts, scope enforcement, human confirmation on the one privileged tool, injection detector, structured output with citation grounding, output filter, verdict cross-check |
| `aip/redteam.py` | attack harness and the layered evaluation; success criteria are written in the module docstring |
| `data/attacks/attack_suite.jsonl` | 9 direct attacks, 8 indirect attacks (poisoned notes and a poisoned KB document), 4 benign controls |
| `reports/lab6_redteam.{json,md}` | layered results; `results/rag_retrieval.json`, `results/rag_ceiling.md` | retrieval results |
