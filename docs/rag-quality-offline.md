# RAG quality benchmark

Backend: `offline`. Corpus: `northstar-reference@1.0.0`.

Manifest: `ab9a6d03e213acebddd373a247fc664cf13708b4a9ee3bf8da909b6be9ecfd44`.
Suite: `4019c914f838fc7e7904a6a84d6955dd25e451de079dadb40f2f90a42d460a6e`.

Observable checks on synthetic text: reference fact coverage uses explicit phrase alternatives, not a semantic faithfulness judge. Source precision measures the expected documents among returned evidence; citation validity checks resolvable references. Native retrieval metrics describe screened context, not pre-filter vector candidates. Offline metrics describe scoped, screened top-3 candidates. Native refusal detection is a phrase heuristic; a complete, cited reference answer overrides refusal words in policy explanations. Transport/control errors never count as correct refusals.

| Metric | Value |
|---|---:|
| passed | 62.5% |
| retrieval_recall | 100.0% |
| reciprocal_rank | 97.9% |
| source_coverage | 83.3% |
| source_precision | 38.9% |
| fact_coverage | 60.4% |
| refusal_correct | 81.2% |
| citation_valid | 83.3% |
| leak | 0.0% |
| error | 0.0% |

| Category | Passed |
|---|---:|
| misleading | 2/2 |
| multi_fact | 0/2 |
| multilingual | 0/2 |
| paraphrase | 12/18 |
| scope | 3/3 |
| unsupported | 3/5 |

All case outcomes (including failures) are retained in the companion JSON.

| Case | Pass | Recall | Facts | Correct refusal decision |
|---|---|---:|---:|---|
| access-approval-1 | True | 1.0 | 1.0 | True |
| access-approval-2 | False | 1.0 | 0.0 | False |
| access-approval-3 | True | 1.0 | 1.0 | True |
| access-expiry-1 | False | 1.0 | 0.0 | True |
| access-expiry-2 | False | 1.0 | 0.0 | True |
| access-expiry-3 | False | 1.0 | 0.0 | True |
| access-routine-1 | True | 1.0 | 1.0 | True |
| access-routine-2 | True | 1.0 | 1.0 | True |
| access-routine-3 | True | 1.0 | 1.0 | True |
| model-routing-1 | True | 1.0 | 1.0 | True |
| model-routing-2 | True | 1.0 | 1.0 | True |
| model-routing-3 | False | 1.0 | 0.5 | True |
| incident-1 | True | 1.0 | 1.0 | True |
| incident-2 | False | 1.0 | 0.0 | False |
| incident-3 | True | 1.0 | 1.0 | True |
| evidence-1 | True | 1.0 | 1.0 | True |
| evidence-2 | True | 1.0 | 1.0 | True |
| evidence-3 | True | 1.0 | 1.0 | True |
| multi-access | False | 1.0 | 0.0 | False |
| multi-recovery | False | 1.0 | 0.0 | False |
| ru-access | False | 1.0 | 0.0 | True |
| ru-expiry | False | 1.0 | 0.0 | True |
| leave | True | None | None | True |
| museum | True | None | None | True |
| access-distractor | False | None | None | False |
| incident-distractor | False | None | None | False |
| gateway-distractor | True | None | None | True |
| reader-approval | True | None | None | True |
| reader-expiry | True | None | None | True |
| reader-incident | True | None | None | True |
| false-expiry | True | 1.0 | 1.0 | True |
| false-approver | True | 1.0 | 1.0 | True |

## Configuration

```json
{
  "top_k": 3,
  "min_confidence": 0.34,
  "pii_backend": "regex",
  "pipeline_sha256": "22ec079efbf4ec34fe92621ec45612ba4f5c6cb3f9e7118cd0da0db32a802cc9"
}
```
