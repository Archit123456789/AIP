# Speaker outline: Healthcare Data Quality & Consistency Intelligence ("Quality Firewall")

How to use this document: each section has **Say** (what to tell the panel, in plain words), **Detail** (facts to have ready if someone digs in), and where useful **Show** (a demo or visual) and **Why it matters** (the reasoning an expert will want). Section 17 is Q&A preparation; Section 18 is a numbers cheat sheet; Section 19 is a glossary. Timing for a ~25 minute talk is in Section 0.

All numbers are real, measured on one synthetic dataset (seed 42) with `gemini-3.1-pro-preview`.

---

## 0. Plan for the talk

| Part | Sections | Minutes |
|---|---|---|
| Problem, goal, approach | 1-3 | 4 |
| Data and ground truth | 4 | 4 |
| The three systems | 5-9 | 8 |
| Evaluation method | 10 | 2 |
| Results and analysis | 11-13 | 5 |
| Limits, lessons, next steps, close | 14-16 | 2 |
| Q&A | 17 | 10+ |

Suggested slides (about 14): 1 title; 2 problem and the five issue types; 3 goal and the three systems; 4 architecture diagram; 5 synthetic data and the answer key; 6 fragmentation and decoys; 7 rules layer; 8 hybrid pipeline (six stages); 9 LLM guardrails; 10 evaluation design; 11 results table; 12 per-type chart and error analysis; 13 cost and reliability; 14 limitations and next steps.

Rule for yourself: **state the limitations before the panel finds them** (Section 14). It makes the rest of the talk more credible.

---

## 1. The problem

**Say:**
- "A patient's health record is rarely in one place. A person might be seen at a hospital, a clinic and an urgent-care center. Each system keeps its own record, with its own patient ID, its own way of writing the name, and its own wording for the same diagnosis."
- "When that fragmented data is combined and fed into clinical AI or analytics, the errors flow straight through into models and decisions. So we want a **quality firewall**: a checkpoint that finds data-quality problems *before* the data reaches downstream systems."
- "It flags problems for a **human** to review. It makes no clinical decisions. That boundary is deliberate."

**The five issue categories (give one concrete example of each):**
1. **Duplicate records.** The same visit recorded twice, perhaps in two systems, with a slightly misspelled name.
2. **Contradictions.** One record says allergic to penicillin; a later one says no known allergies. Or two records show different doses of the same drug during the same week. Or a note says "patient denies any allergies" while the structured field lists one.
3. **Missing information.** No date of birth, no dose on a medication, no allergy status.
4. **Temporal inconsistencies.** A medication that ends before it starts; an encounter date in the future or before the patient was born.
5. **Terminology inconsistencies.** "MI" in one record, "heart attack" in another, "myocardial infarction" in a third. A model sees three different things.

**Why it matters:** each category breaks a different downstream thing: duplicates inflate counts, contradictions create unsafe or wrong features, missing data biases models, temporal errors corrupt timelines, and terminology differences split one concept into many.

---

## 2. The goal and the research question

**Say:**
- "The project builds this firewall and, more importantly, **evaluates how best to build it**."
- "The question is: *rules only, LLM only, or a hybrid in which rules handle the clear-cut cases and an LLM handles only the ambiguous remainder?*"
- "I compared the three on precision, recall, F1, false-positive rate, issue-level accuracy, cost and latency."

**Hypothesis (state it as a hypothesis, not a result):** rules are precise, cheap and auditable but brittle; LLMs handle meaning and paraphrase but cost more and can be inconsistent or hallucinate; a hybrid should capture both strengths.

**Scope boundaries to state:** synthetic data only (no real patients); flags, not decisions; the system detects and explains, it does not auto-correct records.

---

## 3. Approach and architecture

**Show:** this diagram.

```
Clinical records (fragmented, from several source systems)
        |
        v
Patient linkage (which records belong to the same person?)
        |
        +---------------------+------------------------+
        v                     v                        v
 Deterministic rules     Semantic/LLM analysis     (rules hand the LLM
 (explicit checks)       (Gemini, residual only)    only what they can't decide)
        |                     |
        +----------+----------+
                   v
        Issue detection + evidence + provenance
                   |
                   v
            Human review (accept / reject / unsure)
```

**Say:**
- "Three systems share the same input and output format so they are directly comparable: **rules-only**, **LLM-only**, and **hybrid**."
- "The key design principle: **the LLM is not a blanket first pass.** It is used only where rules cannot decide: matching unfamiliar wording to a concept, reading free-text notes, judging borderline duplicates, and writing explanations."

**Why it matters:** this keeps cost down, keeps most decisions explainable and deterministic, and limits where the model could hallucinate.

---

## 4. The data: why synthetic, and how it is built

### 4.1 Why synthetic
**Say:** "Real clinical data needs credentialing and data-use agreements, and I can't show identifiable data. Synthetic data also gives me something real data never has: **exact ground truth.** I know every problem I planted, so scoring is objective."

### 4.2 The schema (what a record looks like)
**Detail:** `ClinicalRecord` has: record ID, local patient reference (differs per source), source system, encounter type and date, sex, date of birth, diagnoses (with onset/resolved dates and status), medications (name, dose, unit, frequency, start/end dates), allergies, free-text notes, and patient name. Ground truth uses `IssueLabel` (issue ID, type, record IDs, patient ID, description, field path). A system's output is a `PredictedIssue`, which adds **detector, confidence, evidence and explanation**: the provenance a reviewer needs.

**Deviations from the original pitch to mention:** I added a `patient_name` field because fuzzy name-based duplicate matching needs it. `patient_id` is deliberately blank in the input so that patient linkage is part of the task. "No known allergies" is stored as an allergy whose text maps to an "NKDA" concept; an allergy field that is null or empty means "status undocumented".

### 4.3 The controlled vocabulary
**Say:** "I built a vocabulary of 28 diagnoses, 25 drugs (brand and generic names) and 10 allergen concepts. It does two jobs: it generates realistic wording variation, and it is the answer key for terminology normalization."

**Detail (important design choice):** every term form is tagged **common** (abbreviations and standard synonyms that a curated dictionary would plausibly contain, e.g. "T2DM", "Glucophage", "heart attack") or **hard** (colloquial names and misspellings, e.g. "sugar diabetes", "brain attack", "low thyroid", "atorvastin"). The rules get only the common tier. This is what stops the rule baseline from trivially seeing the whole answer key and what creates room for the LLM to add value.

**Mention:** in production this vocabulary would be replaced by UMLS, RxNorm or SNOMED CT.

### 4.4 How a patient's data is generated and fragmented
**Say (walk through in order):**
1. "For each fake patient I build a hidden **true history**: diagnoses, medications and allergies, with dates."
2. "Then I **fragment** it across two to four independent source systems, plus sometimes a follow-up visit. Each source gets its own local patient ID, its own name format ('John Smith', 'SMITH, JOHN', 'John A Smith'), and, crucially, **an independent roll of the wording for every concept mention.**"
3. "That independence **naturally produces terminology inconsistencies** (I do not inject them by hand), the same way real systems drift apart."
4. "Each source sees only part of the history (items are randomly omitted). That is legitimate incompleteness, not an error, and the system must not flag it."

**Detail:** visits for one patient are grouped into "care episodes" (episodes at least 50 days apart; records within an episode are at least 3 days apart). That structure is what makes "same care episode" dose checks and "same encounter" duplicate checks well-defined.

### 4.5 The planted problems ("injections")
**Say:** "After fragmentation I run targeted injection passes. **Every injection writes an exact label** to the answer key."

| Category | What was planted (count in this dataset) |
|---|---|
| Duplicate | 58 duplicated records: 70% same source, 30% different source; name typos or format changes; encounter date shifted by one day in some; wording re-rolled in some cross-source copies; one medication dropped in some |
| Contradiction | 152 total: 58 free-text notes that contradict the record (half explicit wording, half paraphrased); 29 drug-versus-allergy conflicts; 20 sex-incompatible diagnoses; 12 dose conflicts within one care episode; 12 "allergy in earlier records, no known allergies later"; 12 sex or date-of-birth mismatches; 9 mutually exclusive diagnoses (e.g. type 1 vs type 2 diabetes) |
| Missing | 68: date of birth, sex, encounter date, encounter type, allergy status, diagnoses, or a medication dose |
| Temporal | 68: end before start, resolved before onset, onset after the encounter, encounter in the future or before birth, medication start before birth |
| Terminology | 1,070 labels, produced by the fragmentation itself: one label for each patient and concept written two or more different ways across that patient's records |

**Dataset total:** 300 patients, 1,033 records, **1,416 labelled issues**.

### 4.6 The decoys (things that must NOT be flagged)
**Say:** "A checker that flags everything would score perfect recall. So the data deliberately includes look-alikes that are **not** problems. They are how false positives are measured honestly."

- **Twins:** same birth date and surname, different first names. Must not be merged into one patient.
- **Same-name patients:** same name, different birth dates.
- **Legitimate dose titration:** a dose that changes between care episodes, months apart.
- **Allergy acquired later:** an early record says no known allergies, a later one lists an allergy. This is normal, not a contradiction.
- **Same-episode records from two systems** at least three days apart. Not duplicates.
- **Benign note text:** "denies chest pain", "denies any *new* allergies", "completed course; discontinued as planned".

### 4.7 Outputs and reproducibility
**Detail:** the generator writes `records.jsonl` (input, no labels), `ground_truth.jsonl` (the answer key), `patient_links.jsonl` (which records belong to which patient, to score linkage) and `manifest.json`. Record IDs are randomly permuted and shuffled so the order and numbering don't leak patient grouping. One random seed plus a fixed reference date reproduce the data byte for byte. Tests verify reproducibility and that no labels leak into the input.

---

## 5. Patient linkage (entity resolution)

**Say:** "Records arrive with **no shared patient ID.** Before any cross-record check can work, the system has to work out which records belong to the same person. In the literature this is *record linkage* or *entity resolution*."

**Detail (how it works):**
- Blocking (cheap candidate grouping) on date of birth, on the first letters of the last name, and on first name plus birth date, to avoid comparing every pair.
- Pair score = 0.4 x last-name similarity + 0.25 x first-name similarity + 0.25 x date-of-birth similarity + 0.1 x sex agreement. Link if the score is at least 0.85.
- **Gates** prevent bad merges: last name similarity at least 0.75 and first name at least 0.6 (nicknames normalised, so Bob = Robert; an initial matches a full name). A date of birth that differs by more than one digit or a day/month swap blocks the link, which is what separates same-name patients. A same first/last-name twin is separated by the first-name gate.
- Date-of-birth typos and day/month swaps are tolerated, because the data contains injected demographic mismatches that must still be linked so they can be detected.
- If a record is missing its date of birth, it links only through the same source system and local ID plus a strong name match.
- Records are grouped with union-find.

**Result:** pairwise precision 1.000 and recall 0.985 against the answer key. **Why it matters:** every cross-record check (duplicates, dose conflicts, allergy conflicts, terminology) depends on this step.

---

## 6. System 1: the deterministic rules layer

**Say:** "These are explicit, auditable checks. Each issue is emitted with its evidence and the name of the rule that fired. They are fast, free and deterministic."

**Checks by category (give the rule and its threshold):**

**Duplicates.** Same linked patient, encounter dates within **1 day**, and clinical-content similarity (shared diagnoses, drugs and allergies, as a Jaccard overlap) at least **0.6** are flagged. Pairs with similarity between 0.3 and 0.6 are *not* decided by rules; they are returned as "ambiguous" for the LLM.

**Contradictions.**
- *Dose conflict:* same drug, both doses present, same unit, different dose, encounter dates within **21 days** (this is why legitimate titration months apart is not flagged).
- *Allergy versus "no known allergies":* flagged only if the allergy was documented **no later than** the NKDA record (so an allergy acquired afterwards is not a contradiction).
- *Mutually exclusive diagnoses* (type 1 vs type 2 diabetes, hypothyroidism vs hyperthyroidism).
- *Sex-incompatible diagnoses* (pregnancy with male sex, prostate hyperplasia with female sex).
- *Drug versus allergy* (e.g. amoxicillin with a penicillin allergy; lisinopril with an ACE-inhibitor allergy; aspirin or ibuprofen with an aspirin allergy).
- *Demographic mismatch:* records linked to one patient disagree on sex or date of birth.
- *Free-text notes, explicit patterns only:* regex for "denies any drug allergies" against a listed allergy; "stopped/discontinued {drug}" against an active drug; "no history of {diagnosis}" against a listed diagnosis. Paraphrases are deliberately left for the LLM.

**Missing.** Null or empty checks on date of birth, sex, encounter date, encounter type, patient name, allergy status, diagnoses, and medication dose. (An empty medication list is not flagged, since some patients take no medication.)

**Temporal.** End before start; resolved before onset; onset after encounter; medication start after encounter; anything before birth; encounter date or onset in the future (as of a fixed reference date). **Cascade suppression:** if the encounter date itself is impossible, the rules emit one issue for it and suppress the derived "onset after encounter" noise, so one root cause produces one issue.

**Terminology.** Each diagnosis, drug and allergen string is normalised through the **common-tier dictionary**, plus a typo-tolerant fuzzy match (string similarity at least 0.88 on strings of seven or more characters). If one concept is written two or more different ways across a patient's records, one issue is raised. Strings the dictionary cannot resolve are **returned as residual**.

**What rules return for the LLM (the "residual"):** unresolved terms, ambiguous duplicate pairs, and notes containing negation or cessation cues that no explicit rule explained.

**Why it matters:** deterministic checks are reproducible and explainable, which matters in healthcare. They also define what the LLM should *not* be needed for.

---

## 7. The LLM layer (Gemini)

**Say:** "The LLM component is a thin, defensive wrapper around Gemini, built so that runs are reproducible, cheap to repeat, and measurable."

**Detail:**
- Model: `gemini-3.1-pro-preview`, JSON output mode, temperature 0.
- **On-disk cache** keyed by model and prompt: re-runs are free and reproducible, and cached calls still report their original token counts and latency.
- Retry with backoff for transient errors; a request timeout; permanent errors (bad key, unknown model) fail immediately with a clear message; a response that is not valid JSON is retried once.
- **Accounting:** input tokens, output tokens (including the model's reasoning tokens, because they are billed as output), per-stage cost and latency.
- The API key comes from an environment variable and is never stored in the repository.

**Guardrails on LLM output (say this explicitly; panels ask about hallucination):**
- Narrow, well-posed questions only.
- Free-text findings must **quote the note verbatim**; a quote that is not actually in the note is rejected (this guards against invented evidence).
- The quote must itself contain a **negation or cessation cue**; a sentence that merely repeats a listed item is not a contradiction. (This guard was added after the first live test produced a borderline false positive.)
- Term mappings are accepted only if they name a concept from the supplied vocabulary or null.
- Every LLM finding is labelled as LLM-sourced, and a human reviews it.

---

## 8. System 2: the LLM-only baseline

**Say:** "To be a fair comparison, the LLM-only baseline gets the raw records straight to Gemini with no rules, no vocabulary, and no linkage, but the *same* category definitions and the *same* output format as everything else."

**Detail (the fairness choices, state them openly):**
- Records are sorted by name and date of birth and sent in **chunks of 25** (42 chunks). The sort is the minimum needed to make cross-record checks possible in a finite context window. A patient whose records straddle two chunks loses cross-record checks. That is a real limitation of the baseline and I report its effect.
- The model returns issues with type, record IDs, field path and description. Invalid IDs or types are dropped.
- For speed, chunks can be run in parallel (I used 4).
- If a chunk comes back unparseable after one retry, the code splits it in half and re-asks (added late; see Section 13).

---

## 9. System 3: the hybrid pipeline

**Say:** "Rules decide the clear cases. Gemini sees only the residual. Every issue keeps a record of which component produced it."

**The six stages (with this dataset's numbers):**
1. **Rules, pass 1.** Produce 1,174 issues and hand back 71 unresolved terms, 4 ambiguous duplicate pairs and 609 cue-bearing notes (about 59% of the notes).
2. **LLM term mapping.** Unresolved strings, in batches of 80, are mapped to a concept from the vocabulary menu or to null. Instruction: map only when the term denotes *exactly* that concept (synonym, abbreviation, brand/generic, colloquial name, misspelling); subtypes and anything uncertain become null. Result: 52 of the 71 were mapped.
3. **Rules, pass 2, using the mappings.** This is the clever part: once a hard-form term is mapped, *all* the rule checks that depend on normalisation start working for it: terminology, dose conflicts, drug-versus-allergy, allergy-versus-NKDA, duplicate similarity. This stage added **334 correct issues**, labelled "rule+llm_terms" in the provenance.
4. **LLM duplicate judge** for the grey-zone pairs, 8 pairs per call, deciding "same encounter recorded twice" versus "two different encounters". On this data it was asked about 4 pairs and confirmed none.
5. **LLM free-text contradiction review** for the 609 cue-bearing notes, 8 per call. Reports only genuine contradictions with a verbatim quote. Found **32**, all correct (one further finding was rejected because its quote wasn't in the note).
6. **LLM explanations**, 20 issues per call, for the non-terminology issues: one or two plain sentences for a data steward on what is inconsistent and what to check. No treatment advice.

**Provenance labels:** `rule:*`, `rule+llm_terms:*`, `llm:free_text`, `llm:duplicate_judge`. Of the 1,369 hybrid predictions, 1,003 are plain rules, 334 are rule+LLM-terms, and 32 are LLM free-text.

**Graceful degradation:** if the LLM is unavailable (no key, quota, outage), each LLM stage is skipped and logged, and the output falls back to the rule baseline instead of failing. The run prints a loud warning that it is not a real hybrid run.

**Why it matters:** the LLM does six narrow, checkable jobs instead of one open-ended one, which is cheaper, more reliable and easier to audit.

---

## 10. Evaluation design

**Say:** "All three systems are scored against the same answer key with the same rules, so the comparison is apples to apples."

**Matching rule (when does a prediction count as correct?):** the same issue type, the same field (e.g. "medications"), and overlapping records. Duplicates and terminology must overlap on at least two records because they are cross-record by nature; other types need one overlapping record. A prediction is a true positive if it matches any true issue; a true issue is found if any prediction matches it.

**Metrics (plain-text equations):**
```
precision = predictions matching a true issue / all predictions
recall    = true issues matched / all true issues
F1        = 2 * precision * recall / (precision + recall)
FDR       = 1 - precision
FPR       = false-positive units / negative units
            (a unit is a record x issue-type pair, because true negatives are not defined at the issue level)
issue-level accuracy = among true issues that some prediction localised (right record and field),
                       the fraction where the prediction also had the right type
macro-F1  = average of the five per-type F1 scores
```

**Say about micro vs macro:** "Terminology is 76% of all labels, so the micro-average is mostly a terminology score. I report **macro-F1 and per-type results** alongside it."

**Cost and latency** come from the LLM client's accounting. Cost = tokens x list price ($2.00 per million input, $12.00 per million output, taken from third-party price trackers and not verified against Google's own page); the token counts themselves are exact.

**The oracle ceiling (explain carefully):** "I built a stand-in that answers the LLM prompts from the answer key. It is **not an LLM** and I never present it as one. It has two uses: it lets me test the whole pipeline offline, and it gives a ceiling: if every LLM stage were perfect, the hybrid would reach micro-F1 0.999 (recall 0.997). That tells me how much headroom the design has."

---

## 11. Results

**Say first:** "These are real results from running all three systems on the full dataset."

| Metric | Rules | LLM-only | Hybrid |
|---|---|---|---|
| Precision | 1.000 | 0.956 | **1.000** |
| Recall | 0.893 | 0.832 | **0.984** |
| F1 (micro / macro) | 0.943 / 0.947 | 0.890 / 0.889 | **0.992 / 0.993** |
| False-positive rate | 0.0000 | 0.0102 | 0.0000 |
| Issue-level accuracy | 0.983 | 0.988 | 0.997 |
| Cost | $0 | $10.56 | $4.41 |
| LLM calls | 0 | 42 | 98 |
| Output tokens | 0 | 839,014 | 337,321 |

Per type (precision / recall):

| Type | Rules | LLM-only | Hybrid |
|---|---|---|---|
| duplicate | 1.00 / 0.88 | 1.00 / 0.74 | 1.00 / 0.97 |
| contradiction | 1.00 / 0.75 | 0.76 / 0.88 | 1.00 / 1.00 |
| missing | 1.00 / 1.00 | 1.00 / 0.97 | 1.00 / 1.00 |
| temporal | 1.00 / 0.99 | 0.84 / 0.97 | 1.00 / 0.99 |
| terminology | 1.00 / 0.90 | 1.00 / 0.81 | 1.00 / 0.98 |

**Talking points:**
1. "The hybrid is best on every headline metric and costs **42% as much** as LLM-only."
2. "Over rules alone, the gain is entirely **recall**, with no loss of precision: the rules missed 152 issues, the hybrid missed 23."
3. "Where does the gain come from? Contradictions went from 0.75 to 1.00 recall, mainly because the LLM read paraphrased notes (32 found), and terminology from 0.90 to 0.98 because the LLM resolved the hard wording that dictionaries can't."
4. "A nice side effect: mapping terms also fixed *other* checks: dose conflicts and duplicates that rules had been missing because a drug name was written in an unfamiliar way."
5. "LLM-only has the lowest recall and used 2.5x the output tokens, because 'find every problem in these 25 records' makes the model reason at length."

---

## 12. Error analysis (shows depth)

**Rules:** missed 152 issues: 106 terminology (hard wording), 38 contradictions (paraphrased notes and hard-form drug names), 7 duplicates, 1 temporal.

**LLM-only: why recall is low.** 200 terminology misses, 15 duplicates, 19 contradictions. Chunking explains part: 49 of the terminology misses and 10 of the 15 duplicate misses involve records that landed in different chunks. The rest are real omissions: the model doesn't exhaustively list every spelling variant for every concept.

**LLM-only: its "false positives" are mostly not mistakes.** Of 54 unmatched predictions:
- 23: a note mentions something that a structured field lacks, because my own "missing field" injection emptied that field.
- 14: a **bug in my generator**: notes say "Currently taking X" even for medications that already have an end date. The model correctly noticed.
- 13: one corrupted encounter date made the model report every diagnosis as "onset after encounter" rather than only the root cause.
- 4 others: two more of the first kind, one genuine failure on the "allergy acquired later" decoy, and one possible mix-up of two different people.
- If the ~50 label-gap flags were counted as correct, its precision would be about 0.997. **So its real weakness here is recall, cost and reliability, not precision.** It also found a kind of problem that neither the rules nor the hybrid look for.

**Hybrid: the 23 residual misses.** 20 terminology (mostly cases where Gemini declined to map a term such as "class II obesity" to obesity or "chronic anxiety" to generalized anxiety disorder; I told it to map only exact synonyms, so these refusals are arguably correct and my "hard" synonym list is arguably too generous), 2 duplicates and 1 temporal (a later injected missing field removed the evidence).

**Sensitivity check (the lost chunk):** for one of the 42 chunks Gemini used its entire output budget (65,522 of 65,536 tokens) on reasoning and returned truncated JSON, twice. That chunk held 35 labelled issues. Excluding it, LLM-only recall rises from 0.832 to 0.853 (F1 0.902); the hybrid is unchanged at 0.983. The ranking and the size of the gap don't change.

---

## 13. Lessons from running an LLM for real (use as "engineering reality" material)

**Say:** "Several things went wrong in practice, and they are informative."
- **Model churn:** the model I first targeted (Gemini 2.5 Pro) was no longer available to new keys; the code now defaults to the current model and makes the model name configurable.
- **Long reasoning is a reliability risk:** broad prompts caused 100-240 second calls and one output truncated at the token limit. Narrow prompts (the hybrid) took about 4-77 seconds. I added timeouts, a retry on malformed output, and chunk splitting.
- **Quota and rate limits** are real operational constraints; the cache means a stopped run resumes without paying again.
- **Cost is dominated by reasoning tokens**, not input size: LLM-only sent only 246k input tokens but wrote 839k output tokens.
- **A live test caught a precision problem** (an affirming sentence flagged as a contradiction), which led to the negation-cue guard.
- **Security hygiene:** API keys come from the environment, never from the repository.

---

## 14. Limitations and validity (state these first, confidently)

1. **Synthetic data, hand-built vocabulary.** Real records are messier. The common/hard vocabulary split is my model of what a dictionary knows.
2. **The rules were written alongside the generator.** Their 1.000 precision shows they don't misfire on the decoys; it is not a prediction of real-world precision.
3. **Label gaps.** Some inconsistencies in the data are side effects of injections and are unlabelled (Section 12). Measured precision is therefore pessimistic for any system that reports them, most of all LLM-only.
4. **Easy paraphrases.** The planted note contradictions use a small set of phrasings, so the hybrid's perfect contradiction recall probably overstates performance on more varied real notes.
5. **Lenient matching** for multi-record issues, and a record x type definition of false-positive rate.
6. **One dataset, one run per LLM system.** The rule baseline varies little across five other seeds (micro-F1 0.931-0.943), but LLM run-to-run variance is not measured.
7. **LLM-only is handicapped by design** (chunking; no vocabulary or linkage). A larger context window or smarter chunking would help it.
8. **No human review sample** was collected, so all precision figures are relative to the synthetic answer key.
9. **Preview model and assumed prices:** results are tied to this model and date; prices come from third-party sources.

---

## 15. The human-review surface and engineering quality

**Review page:** a self-contained HTML page listing flagged issues with filters by type, the explanation, the evidence, the source records, and **Accept / Reject / Unsure** buttons plus a note field. Decisions are saved in the browser and exportable as JSONL. There is also a command-line mode. **Why it matters:** the system never acts on its own; reviewer decisions can become labelled data, and reviewing a sample gives a precision estimate that doesn't depend on the synthetic labels.

**Engineering quality:** 22 automated tests (generator reproducibility and no label leakage; labels verifiable from the records; rule behaviour on decoys; time-aware allergy logic; cascade suppression; evaluator semantics; LLM guardrails; retry and splitting behaviour; graceful degradation). Everything is driven from the command line (`python -m aip.generator`, `.run`, `.evaluate`, `.review`) and reproducible from a seed.

**Repository map (one line each):**
- `schema.py`: record, issue and prediction definitions and JSONL I/O.
- `vocab.py`: the controlled vocabulary with common and hard tiers.
- `names.py`: nickname table for linkage.
- `generator.py`: builds the synthetic data and the answer key.
- `rules.py`: patient linkage and all deterministic checks.
- `llm.py`: Gemini client, cache, retries, cost and latency accounting.
- `prompts.py`: shared instruction text and record rendering.
- `llm_only.py`: the LLM-only baseline.
- `hybrid.py`: the six-stage hybrid.
- `run.py`: runs one system and saves its issues.
- `evaluate.py`: matching and metrics.
- `review.py`: the human-review page and CLI.
- `oracle.py`: the answer-key stand-in used only for tests and the ceiling.
- `tests/`: the automated tests.
- `data/`, `results/`: the dataset and the outputs; `README.md` and `REPORT.md`: how to run, and the full write-up.

---

## 16. Takeaways and next steps

**Takeaways (say these as the close):**
1. "Rules alone are fast, free and precise on what they were designed for, but miss anything that needs meaning, about 11% of issues here."
2. "An LLM alone is flexible, but in this study it had the lowest recall, the highest cost and a real reliability failure."
3. "The hybrid combined them: precision of the rules, recall near the ceiling, at 42% of LLM-only's cost. The principle that worked: **give the LLM small, well-posed questions about the residual, and guard its output instead of trusting it.**"
4. "The system flags and explains; humans decide."

**Next steps:**
- Replace the hand-built vocabulary with UMLS, RxNorm or SNOMED CT.
- Benchmark the duplicate component on the Febrl dataset.
- Collect a human-reviewed sample for a label-independent precision estimate.
- Fix the generator's label gaps and note bug (a v2 dataset) and rerun on several seeds.
- Parallelise the hybrid stages and test a smaller or cheaper model for the narrow tasks.
- For deployment: de-identification, audit logging, access control and a governance process.

---

## 17. Q&A preparation

**Q: Why not use an LLM for everything?**
A: Cost, latency and consistency. In my run LLM-only cost 2.4x as much, found fewer issues, and had a truncation failure. Rules are free, deterministic and explainable for the clear cases, so the LLM is reserved for ambiguity.

**Q: How do you prevent hallucinations?**
A: Narrow questions; term mappings must come from a supplied vocabulary or be null; free-text findings must quote the note verbatim and the quote must contain a negation or cessation cue; everything is labelled by source and reviewed by a human.

**Q: Isn't a rule precision of 1.000 suspicious?**
A: Yes, and I say so. I wrote the rules next to the generator, so it shows they don't misfire on the decoys I built, not that real data would be this clean. That's why I treat the *relative* comparison and the recall gains as the finding, not the absolute precision.

**Q: Is your ground truth reliable?**
A: It is exact for what I planted, and incomplete for side effects of the injections. I found and quantified those (Section 12). Real data would need human-labelled samples; the review page is built for that.

**Q: Could this work on real data?**
A: The architecture would, but it would need real terminologies, tuning on real error patterns, and a labelled evaluation sample. I would also expect real notes to be more varied than my planted paraphrases.

**Q: Why is the hybrid slower than rules, and is it fast enough?**
A: It made 98 sequential calls (about 39 minutes for 1,033 records). It is a batch quality check, not a real-time one, and the stages can be parallelised.

**Q: Why not just use a rule dictionary for terminology?**
A: That is exactly what the rule layer does for common forms. It fails on colloquial names and misspellings. The LLM maps those, and then the rules take over again. A bigger dictionary such as UMLS would shrink the residual but never eliminate it.

**Q: How did you choose the thresholds (1 day, 21 days, 0.6, 0.85, 0.88)?**
A: From the structure of the data and clinical sense: duplicates are same-encounter so a one-day window; dose conflicts must be inside a care episode so 21 days, which excludes legitimate titration; the similarity and linkage thresholds were set to separate decoys from true matches. I did not run a formal threshold sweep, which is a fair criticism.

**Q: What about patient privacy and compliance?**
A: No real patient data was used. In production you'd add de-identification, audit trails, access control, and a review of whether sending data to an external LLM API is permitted under your data-governance rules (or use a locally hosted model).

**Q: Why Gemini?**
A: It was the API available for the project; the design is model-agnostic behind a small client interface. The key finding is about *how* to use an LLM (narrow tasks on the residual), not about one vendor.

**Q: How do you know the hybrid's gain isn't just luck or one seed?**
A: I have one run per LLM system, which is a limitation. The rule baseline is stable across five other seeds. The gap between hybrid and LLM-only is large (about 15 points of recall), so I would expect the ranking to hold, but I haven't measured variance and I say so.

**Q: What does the "oracle ceiling" mean?**
A: A stand-in that answers the LLM prompts from the answer key. It's a plumbing test and an upper bound for the design (0.999 micro-F1), never an LLM result.

**Q: What would you do differently?**
A: Fix the generator's label gaps before evaluating; run several seeds; add a human-labelled sample; and give LLM-only a better chunking strategy so the baseline is as strong as I can make it.

**Q: Why are there so many terminology issues, and is that fair?**
A: They emerge naturally from independent wording per source, as in real fragmented data, so they dominate the label count. That's why I report macro-F1 and per-type scores as well as micro.

**Q: Why does the LLM-only baseline get no vocabulary or linkage?**
A: To measure what an LLM can do on raw records without the surrounding engineering. The hybrid shows the benefit of that engineering. A fairer extension would be a "LLM plus vocabulary" variant.

**Q: What happens when the LLM is down?**
A: The hybrid degrades to the rule baseline and says so loudly, so it never silently pretends to be a full run.

**Q: Why do you believe the explanations are safe?**
A: The explanation prompt allows only facts in the finding and evidence, forbids clinical advice, and the explanation sits next to the raw evidence so the reviewer can verify it. I did not formally evaluate explanation quality, which is a gap.

---

## 18. Numbers cheat sheet

- Dataset: 300 patients, 1,033 records, 1,416 labelled issues (terminology 1,070; contradiction 152; temporal 68; missing 68; duplicate 58).
- Vocabulary: 28 diagnoses, 25 drugs, 10 allergen concepts.
- Linkage: pairwise precision 1.000, recall 0.985.
- Rules: P 1.000, R 0.893, F1 0.943 (macro 0.947), $0, 0.2 s; stable across 5 other seeds (F1 0.931-0.943).
- LLM-only: P 0.956, R 0.832, F1 0.890 (macro 0.889), $10.56, 42 calls, 246,090 in / 839,014 out tokens, 19 minutes with 4 parallel workers (5,455 s summed LLM time).
- Hybrid: P 1.000, R 0.984, F1 0.992 (macro 0.993), $4.41, 98 calls, 182,393 in / 337,321 out tokens, 39 minutes sequential (2,379 s summed LLM time).
- Hybrid stages: 71 unresolved terms (52 mapped); 4 grey-zone duplicate pairs (0 confirmed); 609 note candidates (32 contradictions found); 334 extra correct rule issues from term mapping; 1,369 predictions = 1,003 rule + 334 rule+LLM-terms + 32 LLM free-text.
- Oracle ceiling for the hybrid: micro-F1 0.999, recall 0.997.
- Lost-chunk sensitivity: LLM-only recall 0.832 to 0.853, F1 0.890 to 0.902; hybrid unchanged.
- LLM-only unmatched predictions: 54 (23 + 14 + 13 + 4 explained in Section 12); adjusted precision about 0.997 if label gaps counted correct.
- Misses: rules 152, hybrid 23, LLM-only 238 (200 terminology, 19 contradictions, 15 duplicates, 2 temporal, 2 missing).
- Cost ratio: hybrid is 42% of LLM-only; LLM-only wrote 5.8x more output tokens per call.
- Tests: 22.

---

## 19. Glossary (for your own clarity and for panelists outside the field)

- **Quality firewall:** a checkpoint that validates data before downstream use.
- **Ground truth / answer key:** the known list of planted problems used to score systems.
- **Record linkage / entity resolution:** deciding which records refer to the same real person.
- **Precision:** of the things flagged, the share that were real problems.
- **Recall:** of the real problems, the share that were found.
- **F1:** a single score balancing precision and recall.
- **Micro vs macro average:** micro pools all issues together; macro averages the per-category scores so small categories count equally.
- **False-positive rate:** how often the system raises an alarm where nothing is wrong.
- **Decoy:** a legitimate look-alike case designed to trip a careless checker.
- **Terminology normalisation:** mapping different wordings to one standard concept.
- **Residual:** the cases rules cannot decide, passed to the LLM.
- **Provenance:** a record of which component produced each finding and from what evidence.
- **Grounding:** requiring an LLM's claim to be backed by quoted source text.
- **Thinking / reasoning tokens:** tokens the model spends reasoning before answering; billed as output.
- **Cache:** saved model responses reused on identical prompts.
- **Oracle:** a stand-in that answers from the answer key; for testing only.
- **UMLS / RxNorm / SNOMED CT:** standard medical terminologies a production system would use.
- **Febrl:** a public record-linkage benchmark with known duplicates.

---

## 20. What NOT to claim

- Don't say the system "works on real clinical data": it was evaluated only on synthetic data.
- Don't present rule precision of 1.000 as real-world precision.
- Don't present the oracle numbers as LLM results.
- Don't claim the dollar costs are exact: token counts are, prices are third-party figures.
- Don't claim the results are statistically established for the LLM systems: one run each.
- Don't say the hybrid "beats LLMs": say it beat an LLM-only baseline under this setup, with its stated handicaps.
- Don't claim explanation quality was evaluated: it wasn't.
