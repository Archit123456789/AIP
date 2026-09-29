# Evaluation report (Step 7) - status: rule baseline measured; Gemini systems not yet run

**What is real and what is not.** No Gemini API key exists in the build environment, so the LLM-only and hybrid-with-Gemini columns are
**not measured**. Everything in the "Measured" table is real output of `python -m aip.run --system rules` on `data/` (seed 42, 300 patients,
1,007 records, 1,376 labelled issues). The "Oracle ceiling" table replaces Gemini with the answer key and is an upper bound on the pipeline
design, **not** an LLM result. To fill the missing columns: set `GEMINI_API_KEY`, run `llm_only` and `hybrid`, then `python -m aip.evaluate`.

## Dataset (seed 42)
| type | labelled issues | how produced |
|---|---|---|
| terminology | 1,070 | natural (independent surface-form rolls per source) |
| contradiction | 152 | injected: 58 note-vs-structured, 29 drug-vs-allergy, 20 sex-vs-diagnosis, 12 each dose / allergy-vs-NKDA / demographic, 9 exclusive dx |
| temporal | 68 | injected |
| missing | 68 | injected |
| duplicate | 58 | injected |

Terminology is ~78% of all labels, so micro-averages are mostly a terminology score; read macro-F1 and the per-type rows.

## Measured: deterministic rule baseline
| Metric | Rule-based | LLM-only | Hybrid (rules + Gemini) |
|---|---|---|---|
| Precision (micro) | 1.000 | not run | not run |
| Recall (micro) | 0.893 | not run | not run |
| F1 (micro / macro) | 0.943 / 0.947 | not run | not run |
| False-discovery rate | 0.000 | not run | not run |
| FP rate (record x type units) | 0.0000 | not run | not run |
| Issue-level accuracy | 0.983 | not run | not run |
| Cost (USD) / latency | $0 / 0.4 s | not run | not run |

Per type (precision / recall): duplicate 1.00 / 0.88, contradiction 1.00 / 0.75, missing 1.00 / 1.00, temporal 1.00 / 0.99, terminology 1.00 / 0.90.
Patient linkage (pairwise P / R): 1.000 / 0.985. Across 5 other seeds the rule baseline stays at micro-F1 0.931-0.943, precision >= 0.996.

## Oracle ceiling (not an LLM result) - `results/oracle_ceiling_metrics.md`
With every LLM stage answered from the key, the hybrid reaches micro-F1 0.999 (recall 0.997, precision 1.000). Recall goes: contradiction 0.75 -> 1.00, terminology 0.90 -> 1.00, duplicate 0.88 -> 0.97.
So the architecture routes the right residual to the LLM: the gaps the rules leave are exactly notes with paraphrased contradictions, hard-tier surface forms, and cross-source duplicates with re-rolled forms.
What the ceiling does *not* tell you is how often Gemini gets those judgments right.

## Discussion
**Where rules win/lose (measured).** Rules are perfect on missing fields and temporal logic and never fired a false alarm. That is expected and should not be over-read: I wrote the rules and the generator together, and
the checks are near-exact restatements of the injections. Precision 1.000 says the rules do not misfire on the decoys (titration, acquired allergy, homonyms, twins, benign negations), not that real EHR data would be this clean.
Rules lose on recall where meaning is required: paraphrased note contradictions (all ~26 implicit ones missed), hard-tier terms ("sugar diabetes", "brain attack", "Basaglar") that also silently break downstream dose / exclusive-diagnosis / duplicate checks, and low-similarity duplicates.

**What to expect from Gemini (hypotheses to test, not results).** LLM-only should be strong on free-text contradictions and synonym judgment but weaker on (a) exact arithmetic-like checks over many records, (b) cross-record checks when a patient's records fall in different chunks (chunking is a real handicap of this baseline), and (c) consistency / cost: ~1,000 records cost roughly one prompt-token pass over the whole dataset plus reasoning tokens, versus the hybrid's ~100 small calls. The hybrid's risk is the opposite: rules never see what the LLM alone would notice outside the gates (e.g. a contradiction in a note sentence with no negation cue).

**Caveats.** (1) Synthetic data with hand-built vocabulary; the common/hard tier split is my own construction of "what a curated dictionary would know". (2) Matching is lenient for multi-record issues (record overlap + type + field root), so a prediction touching the right record of a contradiction counts. (3) FPR is defined on a record x type grid because issue-level negatives are undefined. (4) Cost uses list-price assumptions in `aip/llm.py` (`PRICE_TABLE`; override via env) - verify before quoting.
