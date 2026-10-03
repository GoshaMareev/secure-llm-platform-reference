# Expanded RAG quality evaluation

The quality benchmark has 32 cases tied to `northstar-reference@1.0.0`:
18 paraphrases, 2 questions requiring several facts, 2 Russian questions over English sources,
5 unsupported questions (including distractors using corpus vocabulary), 3 reader-scope questions and
2 misleading premises. Every answerable case supplies expected documents and explicit alternatives
for required facts. This suite complements the existing 40 regex / 43 Presidio control cases.

```bash
make quality
```

The deterministic benchmark checks each case against
[`evals/quality-baseline.json`](../evals/quality-baseline.json). Any decrease in per-case recall, reciprocal
rank, source coverage/precision, reference fact coverage, citation validity, correct refusal decision or pass
status fails the regression gate. Leaked restricted sources/fragments and runtime errors always fail.
A changed backend, corpus, case inventory or suite fingerprint requires a separately reviewed baseline.
Existing failures remain visible; the baseline prevents further degradation rather than claiming that the
current answer quality meets a production threshold. `--record-baseline` creates a file and never overwrites it.

[Offline measurement](rag-quality-offline.md) · [complete JSON](rag-quality-offline.json).
[Native measurement](rag-quality-native.md) · [complete JSON](rag-quality-native.json).

The 2026-10-03 measurement passed **20/32 offline** and **31/32 native**. Both found every expected
document in the answerable cases. Native citation validity and refusal decisions were 100%; reference
fact coverage was 97.9%. `model-routing-3` passed source attribution but omitted the local route for
restricted content (one of two required facts). It remains a failed case, and the strict native command
returned exit code 1. This is a recorded quality gap, not a transport/control error. Model sampling can
change outcomes on a future run. Text leakage checks observed no forbidden source/fragment in this suite.

## Metric meanings

| Metric | Observable check |
|---|---|
| Retrieval recall | Fraction of expected documents in unique retrieved/screened evidence |
| Reciprocal rank | Reciprocal rank of the first expected document |
| Source coverage | Fraction of expected documents referenced by the answer |
| Source precision | Fraction of referenced documents that are expected for this question |
| Reference fact coverage | Fraction of required phrase-alternative groups present in the answer |
| Citation validity | Answer references resolve to returned evidence; numeric IDs are checked for native answers |
| Correct refusal decision | Answer/abstention matches the case's expected answerability |
| Leakage | Forbidden documents in context/citations or forbidden fragments in the answer |
| Runtime error | Transport, empty response, unmapped native evidence, or a failed required control |

Recall/rank/coverage/precision/facts/citation validity use the 24 answerable cases as their denominator.
Correct refusal decisions and pass rate use all 32. An answerable case that refuses has zero answer evidence
and fact coverage. Offline retrieval metrics measure scoped, screened top-3 candidates even when the later
confidence check refuses. Native metrics measure the screened context returned by Open WebUI, not its raw
vector candidates. The two retrieval measurements should be read in that context.

Phrase alternatives are deterministic reference checks, not a semantic correctness/faithfulness judge.
They can miss legitimate paraphrases or accept a matching fragment in a wrong answer. Native refusal
detection also uses phrases; a complete, cited reference answer overrides refusal vocabulary inside a
policy explanation. Human review and a wider domain dataset remain necessary. Offline citation validity
covers structured source attribution, while native validity checks inline numeric references.

## Native hosted-model measurement

With the stack provisioned as in [the walkthrough](openwebui.md):

```bash
docker exec secure-llm-platform-reference-open-webui-1 \
  python /reference/evaluate.py --live

docker cp secure-llm-platform-reference-open-webui-1:/app/backend/data/quality-native.json \
  .local/quality-native.json
docker cp secure-llm-platform-reference-open-webui-1:/app/backend/data/quality-native.md \
  .local/quality-native.md
```

`--live` enables hosted model, embedding and reranking calls using the existing operator credentials.
The runner validates release-specific native content and model scope, signs in the enrolled reader/engineer,
and uses the same corpus/questions/reference facts as the offline benchmark. No credentials, email
addresses, raw questions, raw answers or source text are included in the report. Transport errors and
unavailable reranking/PII checks never count as correct abstention. Only `no_safe_evidence` is a safe
policy refusal. Reports retain per-case outcomes, latency, source IDs, release/suite/evaluator fingerprints,
model parameters and retrieval configuration. The native command exits nonzero if any quality case fails;
this is intentionally stricter than the offline historical regression baseline.

Hosted measurements are separate from deterministic CI: model output can vary between runs. CI runs
release verification, offline quality regression checks and pinned-image policy tests without provider keys.
Image/audio sensitive-content inspection remains outside this text benchmark.
