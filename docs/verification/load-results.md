# Isolated fault, load and lifecycle evidence

[Accepted run](load-confirmed-4aa3909.json) uses an isolated Compose project, separate databases,
volumes and synthetic identities. Chat/embedding/rerank URLs are fixed to a local fake provider;
there are no paid keys. Chat upstream delay is 100 ms. Host is Apple M1 Pro, 8 logical CPUs,
16 GiB RAM; Docker has approximately 8 GiB. This is gateway admission/policy performance,
not full native retrieval or hosted-model latency. Source runtime is `4aa3909`; harness is
`63f1b26`. Exact configuration hashes accompany the JSON.

| Concurrency | Requests | Success / HTTP 429 | Accepted p95 | Accepted throughput |
|---|---:|---:|---:|---:|
| 1 | 100 | 100 / 0 | 151.26 ms | 7.169/s |
| 2 | 100 | 100 / 0 | 153.87 ms | 14.289/s |
| 4 | 100 | 100 / 0 | 166.24 ms | 26.728/s |
| 8 | 100 | 4 / 96 | 167.33 ms | 23.669/s |
| 4, soak | 14,916 in 600.163 s | 14,916 / 0 | 168.76 ms | 24.853/s |

The 5-second synthetic p95 criterion passes at concurrency up to four after warmup.
The c8 offered throughput includes immediate rejections and is **not** inference throughput.
No known-marker privacy failures or response-fingerprint ownership mismatches occurred in the
accepted run. These checks cover specified synthetic identities/markers, not all possible leaks.
Resource consumption in the JSON is an end-of-run Docker snapshot, not measured peak usage.
[Stage metrics](load-stage-metrics.prom) separate PII, media extraction, shadow decisions,
inference and output checking. Retrieval timing includes its embedding/rerank/policy subwork;
do not add these overlapping timers as independent wall time. Labels are bounded stage, model
alias and verdict; IDs, identities and text are excluded. Both native Prometheus targets were up.
Hosted latency remains in the [quality reports](quality-results.md), measured separately.

Faults in the load JSON cover upstream 429/500/503, disconnect, malformed JSON, excessive answer
and a 45-second upstream timeout, expired identity, mismatched signed context and injection.
They deny without content-bearing errors; none counts as correct abstention.
[Service faults](service-faults-4aa3909.json) cover analyzer/anonymizer, inspector OCR/STT,
mandatory reranker, spool quota, restart, actual socket cancellation and mixed identities.
[Disk permission probes](storage-faults-final.json) observe operational failure as HTTP 200 plus
degraded health, and audit failure as HTTP 503 `audit_unavailable` plus degraded health.
Quota exhaustion uses a bounded sparse spool; physical ENOSPC/fsync failures use unit injection,
not filling the host filesystem. The storage harness's audit predicate permits any error;
the actual recorded observation is the specific 503 above.

[Native lifecycle](native-lifecycle-final.json) exercises both chat aliases and owned stored
background completion with 2-second upstream stage delays. Saved answers are done and native
active slots are zero on HTTP return. Multi-model fanout is denied; nine concurrent calls
observe native admission rejection. This is not peak child-count measurement, WebSocket
verification or a browser Stop-action test. Gateway has four chat slots; native admission has
eight. The pinned WebUI can present downstream gateway overload as its generic HTTP 400;
gateway and native admission themselves return 429. No unbounded pending queue is introduced.
Text/media configured deadlines are 60/120 seconds; accelerated unit tests verify cancellation,
joined workers and native child cleanup. Actual 60-second incomplete-body and single-media-slot
probes are recorded in [actual runtime probes](capacity-runtime-final.json): 60.01 seconds/504 and
concurrent benign audio200 +429. The 120-second media deadline is configured/unit-tested,
not an actual120-second integration soak.

The [earlier rejected nonce trial](trials/load-nonce-trial-4aa3909.json) had three ownership
mismatches: the English NER masked `synthetic-49` as PERSON. The revised verification nonce was
checked against actual Presidio for all 100 values before repeating the entire ten-minute run.
The runtime and acceptance thresholds did not change to hide that trial.
