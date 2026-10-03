# Jev decision evaluation — 2026-10-03

Measured with real OpenRouter SystemOne calls, using synthetic English/Russian fixtures.
This is a preliminary shadow-mode evaluation. No automatic blocking is enabled.

- Requested model: `typesafe/jev-1.13`; resolved: `typesafe/jev-1.13-20260917`.
- Corpus: `northstar-reference@1.0.0`; manifest `ab9a6d03e213acebddd373a247fc664cf13708b4a9ee3bf8da909b6be9ecfd44`.
- Policy: `semantic-shadow-1`; fingerprint `3b51f989c0531f22f152600a96c1b9a7dfbdc3d4a2afe2a06ea3081660fc393b`.
- Dataset fingerprint: `8b689093c77717b15298e668b2b889c6e0b2d791ada5d82a53dc1b63abc96319`.
- 32 calls, 52 labeled judgments, 0 unavailable calls.
- Fixed exploratory risk threshold: 0.8; no tuning on observed holdout outcomes.
- p95 classifier latency: **543.94 ms per call**.
- Provider-reported cost of this completed benchmark: **$0.00056356**.

| Group | Available judgments | TP | FN | FP | TN | Brier score |
|---|---:|---:|---:|---:|---:|---:|
| Holdout risk, all | 30 | 12 | 0 | 0 | 18 | 0.0245 |
| Holdout risk, English | 15 | 7 | 0 | 0 | 8 | 0.0061 |
| Holdout risk, Russian | 15 | 5 | 0 | 0 | 10 | 0.0428 |
| Development risk, all | 14 | 4 | 0 | 0 | 10 | 0.0082 |
| Passage relevance, diagnostic | 8 | 5 | 1 | 0 | 2 | 0.024 |

All 30 holdout risk judgments matched their labels (12 positives, 18 negatives). The corresponding
pattern-only baseline detected 3 positives, missed 9, and produced 1 false positive.
The comparison includes unsupported-answer judgments that regex rules do not implement. It compares
these narrow classifiers, not the whole platform's access-control/PII protections.

The one label mismatch across all 52 judgments was diagnostic relevance for `poison-en`: Jev returned
0.59 for a passage that combined a relevant gateway fact with an injected instruction. Injection detection
for that passage succeeded. Relevance never sets `would_block` and does not change retrieval in this release.

This small dataset cannot establish robust real-world false-negative or false-positive rates. The judgment
counts include correlated questions from the same case. Russian Brier score is worse than English even
though the risk decisions matched here. Thresholds and failure behavior need representative domain,
multilingual and adaptive adversarial testing before enforcement. Scores are model estimates, not calibrated
correctness guarantees. Clef has only an offline-tested protocol adapter; no Cloudflare hosted result is claimed.

[Full sanitized JSON](decision-evaluation-jev.json) · [policy and reproduction](decision-guardrails.md).

The local native stack runs Jev in shadow mode. Its existing 28 live boundary checks passed after the
change. The additional [native decision smoke report](decision-native.json) passed all seven checks:
reader/engineer completions despite forged client state, independent requests, both observation stages,
server-owned policy/model/corpus provenance and restricted telemetry fields. Offline verification,
the pinned-image gateway/native suites and the publication scan also passed. Historical RAG quality
measurements remain separate; the semantic layer does not change retrieval or the generated answer.
