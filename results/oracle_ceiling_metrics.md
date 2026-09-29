> **ORACLE CEILING - NOT LLM RESULTS.** Produced with `--llm oracle`: the "LLM" answers each prompt from the ground-truth answer key
> (`aip/oracle.py`). It shows the score the pipeline *would* get if every LLM stage were perfect (plumbing check + upper bound).
> Token/cost/latency rows are prompt-length estimates from the stand-in, not real usage. The llm_only column is a
> ceiling for the chunked-prompt format only (the oracle sees the whole chunk's truth); it says nothing about how Gemini does.

| Metric | llm_only | hybrid |
|---|---|---|
| Precision (micro) | 1.000 | 1.000 |
| Recall (micro) | 0.875 | 0.997 |
| F1 (micro) | 0.933 | 0.999 |
| F1 (macro over types) | 0.959 | 0.995 |
| False-discovery rate | 0.000 | 0.000 |
| FP rate (record x type) | 0.0000 | 0.0000 |
| Issue-level accuracy | 0.988 | 0.999 |
| F1 - duplicate | 0.906 | 0.982 |
| F1 - contradiction | 0.969 | 1.000 |
| F1 - missing | 1.000 | 1.000 |
| F1 - temporal | 1.000 | 0.993 |
| F1 - terminology | 0.920 | 1.000 |
| Predictions | 1231 | 1418 |
| LLM calls | 42 | 98 |
| Input tokens | 179624 | 128183 |
| Output tokens | 2100 | 4900 |
| Cost (USD) | 0.2455 | 0.2092 |
| Wall latency (s) | 0.0 | 0.8 |

Per-type precision / recall:

| Type | n_truth | llm_only P / R | hybrid P / R |
|---|---|---|---|
| duplicate | 58 | 1.00 / 0.83 | 1.00 / 0.97 |
| contradiction | 152 | 1.00 / 0.94 | 1.00 / 1.00 |
| missing | 68 | 1.00 / 1.00 | 1.00 / 1.00 |
| temporal | 68 | 1.00 / 1.00 | 1.00 / 0.99 |
| terminology | 1070 | 1.00 / 0.85 | 1.00 / 1.00 |
