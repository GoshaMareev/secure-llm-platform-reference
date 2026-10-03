# Portfolio implementation ledger

Acceptance thresholds and excluded scope are defined by the approved eight-stage plan. Historical reports are retained without replacement. New measurements live in `docs/verification`; raw synthetic traces and private operator state stay in `.local`.

| Stage | Implemented | Verification still required |
|---|---|---|
| Baseline / evaluator | 13 failure explanations, private baseline snapshot, negation/contradiction/false-citation tests | Capture current complete machine/container inventory in public sanitized report |
| RAG quality | Frozen 128-case suite; multi-sentence offline extraction; used-source citations; Unicode glossary; native completeness prompt | Three live native core runs; extended native and manual holdout review |
| Corpus | Immutable 1.1.0 manifest, unchanged source facts, complete 1.0.0 rollback inputs, stable-ID offline comparison | Native upgrade/interruption/retry/hash/stale-model/rollback exercise |
| Fault / load | Pending | Isolated profile and all scenarios, capacity/deadline, 10-minute soak |
| EN/RU / media / Jev | Pinned Russian spaCy artifact and mandatory mixed-language span union | Expanded frozen datasets, real OCR/STT/PII and Jev measurements |
| Audit delivery | Pending | Durable native contract, bounded spool, mTLS collector/shipper and recovery tests |
| SBOM / review | Pending | Versioned Syft, license inventory, final diff review |
| Video / site / publication | Pending | Safe demo, accurate linked results, PR review and production verification |

Protocol note: an initial offline smoke command evaluated the full frozen suite before a group filter existed. No holdout case outcomes were inspected for tuning; subsequent tuning used only the original 32 core cases. This deviation is recorded, and holdout thresholds/questions/split remain unchanged. The eventual report must disclose this limitation.
