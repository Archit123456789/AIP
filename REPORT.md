# Healthcare Data Quality Firewall: evaluation report

**Question.** Which design gives the best quality firewall for fragmented clinical records: deterministic rules only, an LLM only, or a hybrid in which rules decide the clear-cut cases and an LLM handles the ambiguous residual?

**Everything below is measured** on one synthetic dataset (seed 42: 300 patients, 1,033 records, 1,416 labelled issues) with `gemini-3.1-pro-preview` as the LLM. No human review sample was collected, so all precision figures are relative to the synthetic answer key (see "Validity" for what that implies). Reproduce with the commands in `README.md`.

## 1. Headline result

| Metric | Rule-based | LLM-only | Hybrid |
|---|---|---|---|
| Precision (micro) | 1.000 | 0.956 | **1.000** |
| Recall (micro) | 0.893 | 0.832 | **0.984** |
| F1 (micro) | 0.943 | 0.890 | **0.992** |
| F1 (macro over the 5 types) | 0.947 | 0.889 | **0.993** |
| False-discovery rate | 0.000 | 0.044 | 0.000 |
| FP rate (record x type grid) | 0.0000 | 0.0102 | 0.0000 |
| Issue-level accuracy | 0.983 | 0.988 | 0.997 |
| Predictions | 1,174 | 1,236 | 1,369 |
| LLM calls | 0 | 42 | 98 |
| Input / output tokens | 0 / 0 | 246,090 / 839,014 | 182,393 / 337,321 |
| Cost (USD, list-price assumption) | 0 | 10.56 | 4.41 |
| Wall time | 0.2 s | 1,164 s (4 parallel calls) | 2,324 s (sequential) |
| Summed LLM time | - | 5,455 s | 2,379 s |

Per type, precision / recall:

| Type | n | Rules | LLM-only | Hybrid |
|---|---|---|---|---|
| duplicate | 58 | 1.00 / 0.88 | 1.00 / 0.74 | 1.00 / 0.97 |
| contradiction | 152 | 1.00 / 0.75 | 0.76 / 0.88 | 1.00 / 1.00 |
| missing | 68 | 1.00 / 1.00 | 1.00 / 0.97 | 1.00 / 1.00 |
| temporal | 68 | 1.00 / 0.99 | 0.84 / 0.97 | 1.00 / 0.99 |
| terminology | 1,070 | 1.00 / 0.90 | 1.00 / 0.81 | 1.00 / 0.98 |

Terminology is 76% of all labels, so micro-averages are largely a terminology score; macro-F1 and the per-type rows are the fairer summary. Patient re-linking (which all cross-record checks depend on) reached pairwise precision/recall 1.000 / 0.985.

Metric definitions (plain text; matching rules are in the `aip/evaluate.py` docstring):

    precision = predictions matching >=1 true issue / all predictions
    recall    = true issues matched by >=1 prediction / all true issues
    F1        = 2 * precision * recall / (precision + recall)
    FPR       = false-positive (record, type) units / negative (record, type) units

## 2. Sensitivity: one lost LLM-only chunk

For one of its 42 chunks, Gemini used its whole output budget (65,522 of 65,536 tokens) on reasoning and returned truncated, unparseable JSON, on both attempts. That chunk (25 records, 35 labelled issues) contributes no LLM-only predictions. Excluding those records and issues from both systems:

| | Precision / Recall / F1, full | Precision / Recall / F1, excluding the chunk |
|---|---|---|
| LLM-only | 0.956 / 0.832 / 0.890 | 0.956 / 0.853 / 0.902 |
| Hybrid | 1.000 / 0.984 / 0.992 | 1.000 / 0.983 / 0.992 |

The loss costs LLM-only about 2 points of recall; the ranking and the size of the gap are unchanged. The headline table keeps the full numbers because that is what actually happened. (A later code change splits such a chunk in half and re-asks; the quota on the account ran out before that path could be run, so the figures above do not use it.)

## 3. Where the hybrid won, and why

**vs rules.** The gain is all recall, with no precision cost: contradictions 0.75 to 1.00, terminology 0.90 to 0.98, duplicates 0.88 to 0.97. The rules missed 152 labelled issues; the hybrid missed 23. Three mechanisms:
1. *LLM term mapping* (52 of 71 unresolved strings mapped) let the rules recognise concepts written in hard forms ("sugar diabetes", "brain attack", "low thyroid"). That one step enabled 334 additional rule-generated issues, all correct: 315 terminology, 7 dose conflicts, 5 duplicates, and 7 others (allergy-versus-NKDA, drug-versus-allergy, missing, temporal). The non-terminology ones matter because those checks silently fail whenever a drug or diagnosis cannot be normalised.
2. *Free-text review* of 609 cue-bearing notes found 32 contradictions (paraphrased or worded in ways no regex covers), all correct; one further finding was dropped because its quote was not in the note.
3. Better term normalisation raised duplicate-pair similarity: 5 duplicates were found by the duplicate rule only after the LLM had mapped the hard-form terms. The LLM duplicate-judge stage itself confirmed none (the 4 grey-zone pairs were all judged non-duplicates).

**vs LLM-only.** Higher recall on every type, equal or better precision, 2.4x lower cost, and 2.5x fewer output tokens in total (about 3,400 vs 20,000 per call, a 5.8x difference per call). Narrow questions ("map these 20 strings", "does this sentence contradict that field") are cheap and bounded; "find every problem in these 25 records" forces long reasoning, which is where the truncation failure and the cost came from.

## 4. Where the hybrid lost or is weak

- **Wall time as run.** The hybrid made 98 sequential calls (39 minutes). LLM-only finished in 19 minutes only because it ran 4 calls in parallel; its summed LLM time is 5,455 s (about 91 minutes if run sequentially) versus 2,379 s (about 40 minutes) for the hybrid. The hybrid stages here are not parallelised, so its wall time could be cut the same way.
- **Residual terminology misses (20).** Mostly cases where Gemini declined to map a term, e.g. "class II obesity" to obesity, "chronic anxiety" to generalized anxiety disorder. The prompt told it to map only exact synonyms, so these refusals are arguably correct and my "hard" synonym list is arguably too generous.
- **Two duplicates and one temporal issue missed.** Typically a later injected missing field (date or DOB) removed the evidence the rule needs.
- **Narrow by design.** The free-text stage only reports negations/cessations, so it does not report other note-versus-record inconsistencies (see 5). That raises precision and caps recall on a broader definition of "contradiction".
- **Rules still do the heavy lifting**: 1,003 of the 1,369 predictions come from rules alone, so the hybrid is only as good as the rule set and the vocabulary behind it.

## 5. Error analysis of the LLM-only baseline

Of its 54 predictions that matched no label, almost all point at something real that the answer key does not contain:
- **23**: a note mentions an item that the structured field lacks, because my "missing field" injection emptied that field (e.g. note says codeine allergy, allergies field is null).
- **14**: a defect in my generator: notes say "Currently taking X" even for medications that already have an end date. Gemini correctly noticed the disagreement.
- **13**: a chain reaction from one corrupted encounter date; the model reported every diagnosis as "onset after encounter" instead of only the root cause.
- **4 others**: two more note-versus-emptied-field cases, one flag on the "allergy acquired later, earlier record says NKDA" decoy (a genuine decoy failure), and one date-of-birth mismatch that may be two different people being compared (also likely a genuine false positive).

If the ~50 label-gap flags were counted as correct, LLM-only precision would be about 0.997 instead of 0.956. So LLM-only's weakness in this study is **recall, cost and reliability**, not precision. It also found a class of problem (notes versus emptied fields) that neither the rules nor the hybrid look for.

LLM-only's misses (recall 0.83): 200 of 1,070 terminology issues, 15 duplicates, 19 contradictions. Chunking explains part: 49 terminology misses, 10 of the 15 missed duplicates and 3 contradiction misses involve records that landed in different 25-record chunks; the lost chunk accounts for 35 issues. The rest are genuine omissions: the model does not exhaustively enumerate every spelling variant of every concept across a patient's records.

## 6. Cost and latency notes

- Cost = tokens x list price, assumed at $2.00 per 1M input and $12.00 per 1M output tokens (taken from third-party price trackers; not verified against Google's own page). Thinking tokens are counted as output, as they are billed. Token counts are exact; only the dollar figure depends on the price.
- The figures exclude a few dollars spent on smoke tests and one failed retry.
- The rule baseline costs nothing and runs in 0.2 s.

## 7. Validity: what these numbers do and do not show

1. **Synthetic data, hand-built vocabulary.** Real EHR text is messier. The "common vs hard" vocabulary tiers are my model of what a curated dictionary knows.
2. **The rules were written next to the generator**, so their 1.000 precision means they do not misfire on the decoys (twins, same-name patients, legitimate dose change, acquired allergy, benign negations). It is not a prediction of real-world precision.
3. **Label gaps.** Some inconsistencies in the data are side effects of injections and are unlabelled (Section 5). This makes measured precision pessimistic for any system that reports them, most of all LLM-only.
4. **Easy paraphrases.** Planted note contradictions use a small set of phrasings, so the hybrid's perfect contradiction recall (1.00) likely overstates how it would do on more varied notes.
5. **Matching is lenient for multi-record issues** (type + field root + record overlap), and FPR is defined on a record x type grid because issue-level negatives are undefined.
6. **One dataset, one seed, one LLM run each.** Across five other seeds the rule baseline stays within micro-F1 0.931-0.943, but the LLM systems were run once, so their run-to-run variance is unmeasured. LLM outputs at temperature 0 are not guaranteed to be identical across runs.
7. **LLM-only handicaps**: chunking and no vocabulary or linkage are deliberate parts of that baseline; a larger context window or better chunking would help it.
8. **Preview model.** `gemini-3.1-pro-preview` may change; results are tied to this model and date.

## 8. Takeaways

- Rules alone are fast, free, auditable and precise on what they were designed for, but miss anything that needs meaning (about 11% of issues here).
- An LLM alone is flexible and found issues no rule looks for, but in this setup it was the least accurate on the planned issue types, the costliest, and had a real reliability failure (truncated output).
- The hybrid combined them: precision of the rules, recall close to the ceiling of 0.997 that an ideal LLM stage would reach, at 42% of the cost of LLM-only. The design principle that worked is to give the LLM small, well-posed questions on the residual, and to guard its output (verbatim quote, negation cue) rather than trusting it blindly.
- Natural next steps: replace the hand-built vocabulary with UMLS/RxNorm; benchmark the duplicate component on Febrl; collect a human-reviewed sample with the review page to get a label-independent precision estimate; fix the generator's label gaps (v2); run each LLM system on several seeds.
