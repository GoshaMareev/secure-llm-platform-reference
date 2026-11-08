# Semantic shadow decision evidence

[Frozen 128-case report](decision-expanded-1b03896.json) uses `typesafe/jev-1.13`, resolved to
`typesafe/jev-1.13-20260917`, policy `semantic-shadow-2`, threshold 0.8, corpus 1.1.0.
The dataset contains 64 EN and 64 RU cases, with 80 development and 48 holdout cases fixed
before inference. It covers indirect/quoted instructions, Unicode obfuscation, benign controls,
contradictory evidence and unsupported output. Labels are risk judgments, so their denominator
can exceed case count. No holdout results were used to tune enforcement.

| Risk judgments | TP | FN | FP | TN |
|---|---:|---:|---:|---:|
| Development EN | 19 | 2 | 1 | 32 |
| Development RU | 15 | 4 | 1 | 28 |
| Holdout EN | 19 | 0 | 0 | 18 |
| Holdout RU | 17 | 0 | 0 | 20 |

Development has six missed risks and two false alarms: FNR 15%, FPR 3.23% over its labeled
judgments. Zero observed holdout errors on this small synthetic set is not a general guarantee.
Unavailable calls: 0/128. Overall p95: 640.88 ms. Per-language/task p95 and cost are in
`call_metrics`, including RU output p95 1134.32 ms. Provider-returned cost sums to $0.00235771;
the contemporaneous account delta was $0.00176408. Delayed/account-level billing makes them
different observations, not interchangeable per-run prices.

Jev remains **shadow**, including observation of cleaned OCR/STT as untrusted user input.
It cannot authorize documents, turn media into RAG evidence or bypass deterministic checks.
Clef comparison requires optional operator credentials and does not block this release.
