| Metric | rules | llm_only | hybrid |
|---|---|---|---|
| Precision (micro) | 1.000 | 0.956 | 1.000 |
| Recall (micro) | 0.893 | 0.832 | 0.984 |
| F1 (micro) | 0.943 | 0.890 | 0.992 |
| F1 (macro over types) | 0.947 | 0.889 | 0.993 |
| False-discovery rate | 0.000 | 0.044 | 0.000 |
| FP rate (record x type) | 0.0000 | 0.0102 | 0.0000 |
| Issue-level accuracy | 0.983 | 0.988 | 0.997 |
| F1 - duplicate | 0.936 | 0.851 | 0.982 |
| F1 - contradiction | 0.857 | 0.814 | 1.000 |
| F1 - missing | 1.000 | 0.985 | 1.000 |
| F1 - temporal | 0.993 | 0.898 | 0.993 |
| F1 - terminology | 0.948 | 0.897 | 0.991 |
| Predictions | 1174 | 1236 | 1369 |
| LLM calls | 0 | 42 | 98 |
| Input tokens | 0 | 246090 | 182393 |
| Output tokens | 0 | 839014 | 337321 |
| Cost (USD) | 0.0000 | 10.5603 | 4.4126 |
| Wall latency (s) | 0.2 | 1163.6 | 2323.9 |

Per-type precision / recall:

| Type | n_truth | rules P / R | llm_only P / R | hybrid P / R |
|---|---|---|---|---|
| duplicate | 58 | 1.00 / 0.88 | 1.00 / 0.74 | 1.00 / 0.97 |
| contradiction | 152 | 1.00 / 0.75 | 0.76 / 0.88 | 1.00 / 1.00 |
| missing | 68 | 1.00 / 1.00 | 1.00 / 0.97 | 1.00 / 1.00 |
| temporal | 68 | 1.00 / 0.99 | 0.84 / 0.97 | 1.00 / 0.99 |
| terminology | 1070 | 1.00 / 0.90 | 1.00 / 0.81 | 1.00 / 0.98 |
