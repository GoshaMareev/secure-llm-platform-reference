# Versioned portfolio evidence

This local reference was measured on synthetic data. Every result links to its source runtime,
corpus manifest, frozen suite, policy and configuration where applicable. [Evidence inventory](evidence-index.json)
records file SHA-256 values. [Reproduction guide](local-verification.md) starts an isolated stack
without paid-provider keys. Hosted runs use separate budget-controlled operator tooling.

| Area | Current observation | Evidence |
|---|---|---|
| Baseline | 13 historical failure explanations, retained release1.0.0 | [Causes](baseline-causes.md), [environment](baseline-environment.json) |
| RAG | Native core32/32 in3 runs; expanded125/128; holdout30/32; offline32/32 | [Quality and limitations](quality-results.md), [all32 source reviews](holdout-review-4aa3909.md) |
| Corpus | 1.0.0→1.1.0→1.0.0; interrupted/repeated upload, hash and stale-model denial | [Lifecycle](corpus-lifecycle-1b03896.json), [versioning](../corpus-versioning.md) |
| Access | 28/28 native ACL/bypass checks | [ACL](native-acl-63f1b26.json) |
| Fault/load | 14,916 successful requests in600 s atc4; p95168.76 ms | [Load conditions and failures](load-results.md) |
| Media | Natural candidate64/64; benign24/24; native8/8; portableRU stress rejected | [Privacy/recognition limits](media-results.md) |
| Jev | 128 shadow cases; development6 missed risks and2 false alarms | [Language/task decision metrics](jev-results.md) |
| Audit | Durable local spool; private mTLS recovery, replay deduplication | [Delivery evidence](audit-results.md) |
| Supply chain | Syft1.54.0 app/site/11-image inventories plus models/OCR | [License notices](third-party-notices.md), [SBOM index](sbom-4aa3909/index.json) |
| Security | Immutable foundation scan + supplemental reviews and disposition | [Review scope](security-review.md) |
| Checks | Offline, frozen suites, configuration, pinned runtime/media regressions | [Verification summary](checks-2421193.json) |

Text runtime: `4aa3909b5d34941353f13bdfea5e9fd2e8d4ad1e`. Final media runtime:
`a62acc4ebe24448db72b4eaa60f4f1e5a03c5a88` (`local-media-4`). Independent extractive API final revision is `24211939c4b3bf56275629c5d7f5ba51845e66c7`;
other subsequent commits adjust verification/reporting. Corpus1.1.0 manifest:
`3db86a97a0d539ac8d71457debe5ab0d463d29fcf36ee1e9261f53acd41a1873`.
Measurements from `1b03896` are separately labelled and retained; no historical report or
baseline is replaced to achieve acceptance. [Rejected trials](trials/) remain available.

The [implementation ledger](implementation-status.md) explains protocol deviations and excluded
scope. Numbers establish those finite observations, not production guarantees, independent
penetration testing, human certification or general OCR/STT/PII recall. Static portfolio and
its narrated evidence replay are delivered in the separate living-portfolio repository.
