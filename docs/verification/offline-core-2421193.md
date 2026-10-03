# RAG quality benchmark

Backend: `offline`. Corpus: `northstar-reference@1.1.0`.

Manifest: `3db86a97a0d539ac8d71457debe5ab0d463d29fcf36ee1e9261f53acd41a1873`.
Suite: `ad6fe4edde1af9bd210dbe31933aa2a1b0cbd094be7aa10b07deeb6f19462377`.

Observable checks on synthetic text: reference fact coverage uses explicit phrase alternatives with conservative negation/contradiction and keyword-only checks, not a semantic faithfulness judge. Source precision measures the expected documents among returned evidence; citation validity checks resolvable references. Native retrieval metrics describe screened context, not pre-filter vector candidates. Offline metrics describe scoped, screened top-3 candidates. Native refusal detection is a phrase heuristic; a complete, cited reference answer overrides refusal words in policy explanations. Transport/control errors never count as correct refusals.

| Metric | Value |
|---|---:|
| passed | 100.0% |
| retrieval_recall | 100.0% |
| reciprocal_rank | 100.0% |
| source_coverage | 100.0% |
| source_precision | 100.0% |
| fact_coverage | 100.0% |
| refusal_correct | 100.0% |
| citation_valid | 100.0% |
| leak | 0.0% |
| error | 0.0% |

| Category | Passed |
|---|---:|
| misleading | 2/2 |
| multi_fact | 2/2 |
| multilingual | 2/2 |
| paraphrase | 18/18 |
| scope | 3/3 |
| unsupported | 5/5 |

All case outcomes (including failures) are retained in the companion JSON.

| Case | Pass | Recall | Facts | Correct refusal decision |
|---|---|---:|---:|---|
| access-approval-1 | True | 1.0 | 1.0 | True |
| access-approval-2 | True | 1.0 | 1.0 | True |
| access-approval-3 | True | 1.0 | 1.0 | True |
| access-expiry-1 | True | 1.0 | 1.0 | True |
| access-expiry-2 | True | 1.0 | 1.0 | True |
| access-expiry-3 | True | 1.0 | 1.0 | True |
| access-routine-1 | True | 1.0 | 1.0 | True |
| access-routine-2 | True | 1.0 | 1.0 | True |
| access-routine-3 | True | 1.0 | 1.0 | True |
| model-routing-1 | True | 1.0 | 1.0 | True |
| model-routing-2 | True | 1.0 | 1.0 | True |
| model-routing-3 | True | 1.0 | 1.0 | True |
| incident-1 | True | 1.0 | 1.0 | True |
| incident-2 | True | 1.0 | 1.0 | True |
| incident-3 | True | 1.0 | 1.0 | True |
| evidence-1 | True | 1.0 | 1.0 | True |
| evidence-2 | True | 1.0 | 1.0 | True |
| evidence-3 | True | 1.0 | 1.0 | True |
| multi-access | True | 1.0 | 1.0 | True |
| multi-recovery | True | 1.0 | 1.0 | True |
| ru-access | True | 1.0 | 1.0 | True |
| ru-expiry | True | 1.0 | 1.0 | True |
| leave | True | None | None | True |
| museum | True | None | None | True |
| access-distractor | True | None | None | True |
| incident-distractor | True | None | None | True |
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
  "pipeline_sha256": "6679fce1caee7382d411d0a6249706be751ff3c2b7532429f42bc5d3835bbb3c"
}
```
