# RAG term-mapping: retrieval metrics and offline ceiling (NOT Gemini results)

Retrieval (`python -m aip.rag_eval`) on the 71 strings the rule dictionary could not resolve (the ones the LLM is asked about),
lexical retriever (BM25 + character 3-gram, rank-fused) over the term KB, which holds canonical + COMMON synonyms only:

| k | recall@k |
|---|---|
| 1 | 0.56 |
| 3 | 0.68 |
| 5 | 0.80 |
| 10 | 0.89 |

MRR 0.65. recall@5 by kind: medication 0.90, allergen 0.91, diagnosis 0.72. Misses are the semantic ones lexical matching cannot
see ("brain attack" -> stroke, "leg clot" -> DVT, "low blood count" -> anemia, "APAP" -> acetaminophen).

Ceiling = hybrid pipeline with a PERFECT LLM that may only answer with a retrieved candidate (`--llm oracle --rag`); prompt size is the
approximate token count of the term-mapping prompts (chars/4):

| Term-mapping prompt | Hybrid recall (ceiling) | Hybrid micro-F1 (ceiling) | Prompt tokens |
|---|---|---|---|
| Full vocabulary menu (no retrieval) | 0.997 | 0.999 | ~1,040 |
| RAG top-10 candidates | 0.992 | 0.996 | ~11,300 |
| RAG top-5 candidates | 0.984 | 0.992 | ~6,200 |

Reading: with a 63-concept vocabulary, listing the whole menu is both cheaper and more accurate than retrieval. Retrieval pays off
only when the vocabulary is too large to list (UMLS/RxNorm/SNOMED have 10^5-10^6 concepts) and then needs a semantic (embedding)
retriever, because lexical recall@5 of 0.80 caps accuracy. Run live with `python -m aip.run --system hybrid --rag --rag-k 10`.
